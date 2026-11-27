"""Exportação para a folha de pagamento: verbas, matrículas e o arquivo do mês (Domínio, Alterdata ou CSV)."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, require
from ..models import Company, User
from ..services import audit, payroll

router = APIRouter(prefix="/payroll", tags=["folha de pagamento"])
MONTH = r"\d{4}-(0[1-9]|1[0-2])"


class ConfigIn(BaseModel):
    system: str = "csv"
    company_code: str = Field("", max_length=10)
    process: str = Field("", max_length=2)
    codes: dict[str, str] = {}


class CodeItem(BaseModel):
    user_id: int
    code: str | None = Field(None, max_length=10)


class CodesIn(BaseModel):
    items: list[CodeItem] = Field(max_length=2000)


def _month(month: str) -> tuple[int, int]:
    if not re.fullmatch(MONTH, month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    return int(month[:4]), int(month[5:])


def _run(fn):
    try:
        return fn()
    except payroll.PayrollError as e:
        raise HTTPException(e.status, e.message) from None


@router.get("/config")
def get_config(actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    company = db.get(Company, actor.company_id)
    return {"config": payroll.config(company), "events": payroll.events(company), "systems": payroll.SYSTEMS,
            "processes": payroll.PROCESSES, "limits": payroll.LIMITS}


@router.put("/config")
def put_config(body: ConfigIn, request: Request, actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    company = db.get(Company, actor.company_id)
    before = company.payroll_export
    company.payroll_export = _run(lambda: payroll.validate_config(body.model_dump()))
    audit.log(db, actor, "update", "payroll_config", company.id, before=before, after=company.payroll_export, ip=client_ip(request))
    db.commit()
    return get_config(actor, db)


@router.put("/codes")
def put_codes(body: CodesIn, request: Request, actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    """Matrícula de cada pessoa no sistema de folha (só números; vazio apaga)."""
    company = db.get(Company, actor.company_id)
    limit = payroll.LIMITS[payroll.config(company)["system"]]["employee"]
    users = {u.id: u for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    changes = {}
    for it in body.items:
        u = users.get(it.user_id)
        if not u:
            raise HTTPException(404, "Pessoa não encontrada")
        code = (it.code or "").strip() or None
        if code is not None:
            if not re.fullmatch(rf"\d{{1,{limit}}}", code):
                raise HTTPException(422, f"Matrícula de {u.name}: só números, até {limit} dígitos")
        if code != u.payroll_code:
            changes[u.id] = (u.payroll_code, code)
            u.payroll_code = code
    taken: dict[str, str] = {}
    for u in users.values():
        if u.payroll_code:
            if u.payroll_code in taken:
                msg = f"A matrícula {u.payroll_code} está em {taken[u.payroll_code]} e em {u.name}"
                db.rollback()
                raise HTTPException(409, msg)
            taken[u.payroll_code] = u.name
    for uid, (old, new) in changes.items():
        audit.log(db, actor, "update", "user_payroll_code", uid, before={"payroll_code": old}, after={"payroll_code": new},
                  ip=client_ip(request))
    db.commit()
    return {"changed": len(changes)}


@router.get("/preview")
def preview(month: str = Query(...), actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    year, mon = _month(month)
    return _run(lambda: payroll.preview(db, db.get(Company, actor.company_id), year, mon))


@router.get("/export")
def export(request: Request, month: str = Query(...), format: str = Query("csv"),
           actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    year, mon = _month(month)
    company = db.get(Company, actor.company_id)
    content, ext, count = _run(lambda: payroll.export(db, company, year, mon, format))
    audit.log(db, actor, "export", "payroll", 0, after={"month": month, "format": format, "lines": count}, ip=client_ip(request))
    db.commit()
    media = "text/csv; charset=utf-8" if ext == "csv" else "text/plain; charset=us-ascii"
    name = f"folha-{format}-{month}.{ext}"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
