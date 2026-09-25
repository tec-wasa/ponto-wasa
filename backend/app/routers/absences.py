"""Atestados, abonos, férias, licenças e afastamentos (RF-13)."""
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user
from ..models import Absence, Company, User
from ..services import absences as svc
from ..services import audit
from ..services.hourbank import today_local

router = APIRouter(prefix="/absences", tags=["ausências"])

HR = ("hr", "admin")


class AbsenceIn(BaseModel):
    kind: str
    start_date: date
    end_date: date
    minutes: int | None = Field(None, description="Justificativa parcial, em minutos (um único dia)")
    reason: str = Field(min_length=3, max_length=500, description="Sem diagnóstico ou CID")
    attachment_name: str | None = Field(None, max_length=300)
    user_id: int | None = Field(None, description="RH/admin registra em nome de outro colaborador")


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=500)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _guard_closed(db: Session, company: Company, a_start: date, a_end: date) -> None:
    month = svc.touches_closed_month(db, company, a_start, a_end)
    if month:
        raise HTTPException(409, f"O mês {month} está fechado")


@router.post("", status_code=201)
def create_absence(
    body: AbsenceIn, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """O colaborador pede (fica pendente); o RH registra em nome de outro (já aprovada)."""
    company = db.get(Company, actor.company_id)
    on_behalf = bool(body.user_id) and body.user_id != actor.id
    target = actor
    if on_behalf:
        if actor.role not in HR:
            raise HTTPException(403, "Só o RH registra ausência em nome de outro colaborador")
        target = db.get(User, body.user_id)
        if not target or target.company_id != actor.company_id or not target.active:
            raise HTTPException(404, "Colaborador não encontrado")

    problem = svc.validate_period(body.kind, body.start_date, body.end_date, body.minutes)
    if problem:
        raise HTTPException(422, problem)
    today = today_local(company)
    if body.end_date > today + timedelta(days=svc.MAX_DAYS):
        raise HTTPException(422, "A data final está longe demais no futuro")

    if not on_behalf:  # pedido do próprio colaborador
        if body.kind not in svc.EMPLOYEE_KINDS:
            raise HTTPException(403, "Este tipo de ausência é registrado pelo RH")
        if body.start_date < today - timedelta(days=svc.EMPLOYEE_LOOKBACK_DAYS):
            raise HTTPException(422, f"O pedido não pode ser de mais de {svc.EMPLOYEE_LOOKBACK_DAYS} dias atrás; procure o RH")

    _guard_closed(db, company, body.start_date, body.end_date)
    clash = svc.overlapping(db, target.id, body.start_date, body.end_date)
    if clash:
        raise HTTPException(409, f"Já existe ausência no período ({clash[0].start_date:%d/%m/%Y} a {clash[0].end_date:%d/%m/%Y})")

    absence = Absence(
        company_id=company.id, user_id=target.id, kind=body.kind, start_date=body.start_date, end_date=body.end_date,
        minutes=body.minutes, reason=body.reason, attachment_name=body.attachment_name, created_by=actor.id,
        status="approved" if on_behalf else "pending",
    )
    if on_behalf:
        absence.decided_by, absence.decided_at = actor.id, _now()
    db.add(absence)
    db.flush()
    audit.log(db, actor, "create", "absence", absence.id, ip=client_ip(request), after={
        "user_id": target.id, "kind": body.kind, "start": str(body.start_date), "end": str(body.end_date),
        "status": absence.status})  # o motivo (dado de saúde) não vai para a trilha
    db.commit()
    return svc.serialize(actor, absence, target.name)


@router.get("")
def list_absences(
    status: str | None = None, user_id: int | None = None, mine: bool = False,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    q = select(Absence, User.name).join(User, User.id == Absence.user_id).where(Absence.company_id == actor.company_id)
    if mine or actor.role in ("employee", "auditor"):
        q = q.where(Absence.user_id == actor.id)
    elif actor.role == "manager":
        q = q.where(or_(Absence.user_id == actor.id, User.manager_id == actor.id))
    if user_id:
        q = q.where(Absence.user_id == user_id)
    if status:
        q = q.where(Absence.status == status)
    rows = db.execute(q.order_by(Absence.start_date.desc(), Absence.id.desc()).limit(300)).all()
    return [svc.serialize(actor, a, name) for a, name in rows]


@router.post("/{absence_id}/decision")
def decide(
    absence_id: int, body: DecisionIn, request: Request, actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    a = db.get(Absence, absence_id)
    if not a or a.company_id != actor.company_id:
        raise HTTPException(404, "Ausência não encontrada")
    owner = db.get(User, a.user_id)
    if not (actor.role in HR or (actor.role == "manager" and owner.manager_id == actor.id)):
        raise HTTPException(403, "Sem permissão para decidir esta ausência")
    if a.user_id == actor.id:
        raise HTTPException(403, "Não é permitido aprovar a própria ausência")
    if a.status != "pending":
        raise HTTPException(409, "Ausência já decidida")
    _guard_closed(db, db.get(Company, a.company_id), a.start_date, a.end_date)

    a.status = "approved" if body.approve else "rejected"
    a.decided_by, a.decided_at, a.decision_note = actor.id, _now(), body.note
    audit.log(db, actor, "approve" if body.approve else "reject", "absence", a.id, ip=client_ip(request),
              before={"status": "pending"}, after={"status": a.status})
    db.commit()
    return svc.serialize(actor, a, owner.name)


@router.post("/{absence_id}/cancel")
def cancel(absence_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """O dono cancela o pedido pendente; o RH cancela também as aprovadas (enquanto o mês estiver aberto)."""
    a = db.get(Absence, absence_id)
    if not a or a.company_id != actor.company_id:
        raise HTTPException(404, "Ausência não encontrada")
    owner_pending = a.user_id == actor.id and a.status == "pending"
    if not (owner_pending or actor.role in HR):
        raise HTTPException(403, "Sem permissão para cancelar esta ausência")
    if a.status not in ("pending", "approved"):
        raise HTTPException(409, "Esta ausência não pode mais ser cancelada")
    _guard_closed(db, db.get(Company, a.company_id), a.start_date, a.end_date)
    before = a.status
    a.status = "cancelled"
    audit.log(db, actor, "cancel", "absence", a.id, ip=client_ip(request), before={"status": before}, after={"status": "cancelled"})
    db.commit()
    return svc.serialize(actor, a, db.get(User, a.user_id).name)
