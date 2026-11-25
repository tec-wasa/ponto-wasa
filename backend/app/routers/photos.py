"""Fotos opcionais das batidas (LGPD: consentimento por pessoa; visíveis só ao RH/admin; apagadas no fechamento do mês)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user, require
from ..models import Company, Punch, PunchPhoto, User
from ..services import audit, photos
from ..services.punching import month_is_closed, month_of

router = APIRouter(tags=["fotos"])


class PhotoIn(BaseModel):
    image_base64: str


@router.post("/punches/{punch_id}/photo", status_code=201)
def upload_photo(
    punch_id: int, body: PhotoIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Anexa a foto à PRÓPRIA batida, depois que ela foi registrada. A batida nunca depende da foto."""
    punch = db.get(Punch, punch_id)
    if not punch or punch.user_id != user.id:
        raise HTTPException(404, "Marcação não encontrada")
    company = db.get(Company, user.company_id)
    if not company.photo_enabled:
        raise HTTPException(403, "A foto na batida não está ativada nesta empresa")
    if user.photo_consent_at is None:
        raise HTTPException(403, "Sem consentimento para foto")
    month = month_of(company, punch.occurred_at)
    if month_is_closed(db, company.id, month):
        raise HTTPException(409, "O mês desta marcação está fechado")
    try:
        photo = photos.save(db, punch, month, photos.decode_jpeg(body.image_base64))
    except photos.PhotoError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    audit.log(db, user, "photo", "punch", punch.id, after={"bytes": photo.size, "sha256": photo.sha256}, ip=client_ip(request))
    db.commit()
    return {"id": photo.id, "bytes": photo.size, "sha256": photo.sha256}


def _photo_of(db: Session, actor: User, punch_id: int) -> PunchPhoto:
    photo = db.execute(select(PunchPhoto).where(PunchPhoto.punch_id == punch_id)).scalar_one_or_none()
    if not photo or photo.company_id != actor.company_id:
        raise HTTPException(404, "Foto não encontrada")  # já apagada no fechamento do mês, ou nunca existiu
    return photo


@router.get("/punches/{punch_id}/photo")
def view_photo(
    punch_id: int, request: Request, actor: User = Depends(require("photos.view")), db: Session = Depends(get_db),
):
    photo = _photo_of(db, actor, punch_id)
    try:
        data = photos.store().get(photo.storage_key)
    except photos.PhotoError as e:
        raise HTTPException(e.status, e.message) from None
    audit.log(db, actor, "view_photo", "punch", punch_id, after={"owner": photo.user_id}, ip=client_ip(request))
    db.commit()
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/photos")
def list_photos(
    user_id: int, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    actor: User = Depends(require("photos.view")), db: Session = Depends(get_db),
):
    """Quais batidas de uma pessoa, em um mês, têm foto (sem as imagens)."""
    target = db.get(User, user_id)
    if not target or target.company_id != actor.company_id:
        raise HTTPException(404, "Colaborador não encontrado")
    rows = db.execute(
        select(PunchPhoto, Punch).join(Punch, Punch.id == PunchPhoto.punch_id)
        .where(PunchPhoto.user_id == user_id, PunchPhoto.month == month).order_by(Punch.occurred_at)
    ).all()
    return [{"punch_id": p.id, "kind": p.kind, "occurred_at": p.occurred_at, "nsr": p.nsr} for _, p in rows]
