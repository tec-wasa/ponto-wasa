"""Inconsistências do ponto (CLT): lista do período, marcar como resolvida e reabrir."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..db import get_db
from ..deps import client_ip, require
from ..models import Company, InconsistencyResolution, User
from ..services import audit, hourbank, panel
from ..services import inconsistencies as svc

router = APIRouter(tags=["inconsistências"])

MAX_DAYS = 93
MAX_PEOPLE = 500


class ResolveIn(BaseModel):
    user_id: int
    date: date
    kind: str
    note: str = Field(min_length=3, max_length=300)


class ReopenIn(BaseModel):
    user_id: int
    date: date
    kind: str


def _target(db: Session, actor: User, user_id: int) -> User:
    target = db.get(User, user_id)
    if not target or target.company_id != actor.company_id or not perm.in_scope(actor, target):
        raise HTTPException(404, "Colaborador não encontrado")
    return target


@router.get("/inconsistencies")
def list_inconsistencies(
    start: date, end: date,
    user_id: int | None = None,
    kind: str | None = None,
    resolved: bool = Query(False, description="Inclui as já marcadas como resolvidas"),
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Inconsistências da equipe (gestor) ou da empresa (RH, administração, auditoria) no período."""
    company = db.get(Company, actor.company_id)
    today = hourbank.today_local(company)
    end = min(end, today)
    if end < start:
        raise HTTPException(422, "Período inválido")
    if (end - start).days >= MAX_DAYS:
        raise HTTPException(422, f"Escolha um período de até {MAX_DAYS} dias")
    if kind and kind not in svc.KINDS:
        raise HTTPException(422, "Tipo de inconsistência desconhecido")

    users = panel.scope_users(db, actor)
    if user_id is not None:
        users = [u for u in users if u.id == user_id]
        if not users:
            raise HTTPException(404, "Colaborador não encontrado")
    if len(users) > MAX_PEOPLE:
        raise HTTPException(413, "Escopo grande demais: filtre por colaborador")

    done = svc.resolutions(db, [u.id for u in users], start, end)
    names = {u.id: u.name for u in db.execute(select(User).where(User.company_id == company.id)).scalars()}
    counts = {k: 0 for k in svc.KINDS}
    resolved_count = 0
    items = []
    for u in users:
        for f in svc.user_findings(db, company, u, start, end, today):
            r = done.get((u.id, f.day, f.kind))
            if r:
                resolved_count += 1
            else:
                counts[f.kind] += 1
            if (kind and f.kind != kind) or (r and not resolved):
                continue
            items.append({
                "user_id": u.id, "name": u.name, "job_title": u.job_title, "date": f.day.isoformat(), "kind": f.kind,
                "label": svc.KINDS[f.kind][0], "legal": svc.KINDS[f.kind][1], "detail": f.detail,
                "resolved": None if not r else {
                    "note": r.note, "by": names.get(r.resolved_by), "at": r.resolved_at.isoformat(timespec="seconds"),
                },
            })
    items.sort(key=lambda i: (i["date"], i["name"], list(svc.KINDS).index(i["kind"])))
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "can_resolve": perm.can(actor, "approvals"),
        "kinds": [{"kind": k, "label": lbl, "legal": legal, "open": counts[k]} for k, (lbl, legal) in svc.KINDS.items()],
        "open": sum(counts.values()), "resolved": resolved_count,
        "items": items,
    }


@router.post("/inconsistencies/resolve", status_code=201)
def resolve(body: ResolveIn, request: Request, actor: User = Depends(require("approvals")), db: Session = Depends(get_db)):
    """Marca a inconsistência de um dia como resolvida, com uma observação (ex.: "hora extra autorizada pela diretoria")."""
    company = db.get(Company, actor.company_id)
    target = _target(db, actor, body.user_id)
    if target.id == actor.id:
        raise HTTPException(403, "Você não pode resolver as suas próprias inconsistências")
    if body.kind not in svc.KINDS:
        raise HTTPException(422, "Tipo de inconsistência desconhecido")
    found = svc.user_findings(db, company, target, body.date, body.date, hourbank.today_local(company))
    if not any(f.kind == body.kind for f in found):
        raise HTTPException(409, "Esta inconsistência não existe mais nesse dia (o ponto pode ter sido corrigido)")
    exists = db.execute(select(InconsistencyResolution.id).where(
        InconsistencyResolution.user_id == target.id, InconsistencyResolution.day == body.date,
        InconsistencyResolution.kind == body.kind,
    )).first()
    if exists:
        raise HTTPException(409, "Esta inconsistência já está marcada como resolvida")
    row = InconsistencyResolution(company_id=company.id, user_id=target.id, day=body.date, kind=body.kind,
                                  note=body.note.strip(), resolved_by=actor.id)
    db.add(row)
    db.flush()
    audit.log(db, actor, "resolve", "inconsistency", row.id, ip=client_ip(request),
              after={"user_id": target.id, "date": str(body.date), "kind": body.kind, "note": row.note})
    db.commit()
    return {"id": row.id}


@router.post("/inconsistencies/reopen", status_code=204)
def reopen(body: ReopenIn, request: Request, actor: User = Depends(require("approvals")), db: Session = Depends(get_db)):
    """Desfaz o "resolvido": a inconsistência volta para a lista (a trilha fica na auditoria)."""
    target = _target(db, actor, body.user_id)
    row = db.execute(select(InconsistencyResolution).where(
        InconsistencyResolution.user_id == target.id, InconsistencyResolution.day == body.date,
        InconsistencyResolution.kind == body.kind,
    )).scalars().first()
    if not row:
        raise HTTPException(404, "Esta inconsistência não está marcada como resolvida")
    audit.log(db, actor, "reopen", "inconsistency", row.id, ip=client_ip(request),
              before={"user_id": target.id, "date": str(row.day), "kind": row.kind, "note": row.note})
    db.delete(row)
    db.commit()
    return Response(status_code=204)
