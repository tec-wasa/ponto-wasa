"""Importação de marcações de outro sistema (CSV) como inclusões aprovadas; lista e desfaz importações."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, require
from ..models import Adjustment, Company, User
from ..services import audit, csv_import, punch_import
from ..services.punching import month_is_closed, month_of

router = APIRouter(tags=["importação"])


class PunchImportIn(BaseModel):
    content_base64: str = Field(max_length=int(csv_import.MAX_BYTES * 1.4))
    reason: str = Field("", max_length=300)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.post("/imports/punches")
def import_punches(
    body: PunchImportIn, request: Request, dry_run: bool = True,
    actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db),
):
    """Valida (`dry_run=true`, padrão) ou grava (`dry_run=false`, tudo ou nada) as marcações do arquivo como inclusões aprovadas.
    Dias que já têm marcações no app são pulados; avisos (dia ímpar, antes da admissão) não impedem a importação."""
    try:
        text = csv_import.decode_payload(body.content_base64)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    company = db.get(Company, actor.company_id)
    now = _now()
    res = punch_import.parse(db, company, text, now)
    own = next((r for r in res.rows if r.user.id == actor.id), None)
    if own:  # migração de registros do sistema anterior: permitido, mas fica visível na prévia e na auditoria
        res.warnings.append(punch_import.Issue(own.line, "Inclui as suas próprias marcações: ficarão aprovadas por você", actor.name))
    issue = lambda i: {"line": i.line, "person": i.person, "message": i.message}  # noqa: E731
    people: dict[str, dict] = {}
    for r in res.rows:
        p = people.setdefault(r.user.name, {"name": r.user.name, "days": 0, "marks": 0, "first": r.day, "last": r.day})
        p["days"] += 1
        p["marks"] += len(r.times)
        p["first"], p["last"] = min(p["first"], r.day), max(p["last"], r.day)
    payload = {
        "dry_run": dry_run, "total": res.total, "empty": res.empty, "days": len(res.rows), "marks": sum(len(r.times) for r in res.rows),
        "errors": [issue(i) for i in res.errors], "warnings": [issue(i) for i in res.warnings], "skipped": [issue(i) for i in res.skipped],
        "people": [{**p, "first": p["first"].isoformat(), "last": p["last"].isoformat()} for p in sorted(people.values(), key=lambda p: p["name"])],
        "imported": False, "batch": None,
    }
    if dry_run:
        return payload
    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(422, "Escreva o motivo da importação (ao menos 10 caracteres), ex.: Migração do sistema anterior")
    if res.errors or not res.rows:
        return JSONResponse(payload, status_code=422)
    tag = f"{punch_import.TAG_PREFIX}{now:%Y%m%d-%H%M%S}"
    adjustments = punch_import.to_adjustments(res, company, actor, reason, tag, now)
    db.add_all(adjustments)
    db.flush()
    audit.log(db, actor, "import", "adjustment", tag, after={
        "batch": tag, "reason": reason, "inclusions": len(adjustments), "days": len(res.rows),
        "people": len(people), "skipped_days": len(res.skipped),
    }, ip=client_ip(request))
    db.commit()
    return {**payload, "imported": True, "batch": tag}


@router.get("/imports/punches")
def list_imports(actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    """Importações feitas, com quantas inclusões continuam valendo."""
    rows = db.execute(
        select(Adjustment.decision_note, Adjustment.status, func.count(), func.min(Adjustment.requested_at), func.max(Adjustment.requested_at),
               func.min(Adjustment.decided_at), func.min(Adjustment.reason))
        .where(Adjustment.company_id == actor.company_id, Adjustment.kind == "incluir",
               Adjustment.decision_note.like(f"{punch_import.TAG_PREFIX}%"))
        .group_by(Adjustment.decision_note, Adjustment.status)
    ).all()
    out: dict[str, dict] = {}
    for tag, status, n, lo, hi, at, reason in rows:
        b = out.setdefault(tag, {"batch": tag, "active": 0, "revoked": 0, "first": lo, "last": hi, "at": at, "reason": reason})
        b["active" if status == "approved" else "revoked"] += n
        b["first"], b["last"] = min(b["first"], lo), max(b["last"], hi)
    return sorted(out.values(), key=lambda b: b["at"], reverse=True)


@router.post("/imports/punches/{batch}/undo")
def undo_import(batch: str, request: Request, actor: User = Depends(require("closing.manage")), db: Session = Depends(get_db)):
    """Desfaz uma importação inteira (as inclusões ficam como desfeitas, com a trilha na auditoria). Recusa se houver mês fechado."""
    adjs = db.execute(select(Adjustment).where(
        Adjustment.company_id == actor.company_id, Adjustment.kind == "incluir", Adjustment.decision_note == batch,
        Adjustment.status == "approved")).scalars().all()
    if not batch.startswith(punch_import.TAG_PREFIX) or not adjs:
        raise HTTPException(404, "Importação não encontrada ou já desfeita")
    company = db.get(Company, actor.company_id)
    closed = sorted({m for m in {month_of(company, a.requested_at) for a in adjs} if month_is_closed(db, company.id, m)})
    if closed:
        raise HTTPException(409, f"O mês {', '.join(closed)} está fechado: reabra antes de desfazer a importação")
    for a in adjs:
        a.status = "revoked"
    audit.log(db, actor, "undo_import", "adjustment", batch, after={"batch": batch, "revoked": len(adjs)}, ip=client_ip(request))
    db.commit()
    return {"batch": batch, "revoked": len(adjs)}
