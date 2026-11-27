"""Atestados, abonos, férias, licenças e afastamentos (RF-13)."""
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..db import get_db
from ..deps import authorize_decision, client_ip, get_current_user, require, require_punch
from ..models import Absence, Company, User
from ..services import absences as svc
from ..services import audit
from ..services.hourbank import today_local
from ..services.mirror import ABSENCE_LABEL

router = APIRouter(prefix="/absences", tags=["ausências"])

class AbsenceIn(BaseModel):
    kind: str
    start_date: date
    end_date: date
    minutes: int | None = Field(None, description="Justificativa parcial, em minutos (um único dia)")
    reason: str = Field(min_length=3, max_length=500, description="Sem diagnóstico ou CID")
    attachment_name: str | None = Field(None, max_length=300)
    user_id: int | None = Field(None, description="RH/admin registra em nome de outro colaborador")


class BatchIn(BaseModel):
    kind: str = Field(description="abono (ponte, recesso, queda de energia) ou ferias (férias coletivas)")
    start_date: date
    end_date: date
    minutes: int | None = Field(None, description="Abono parcial, em minutos (um único dia)")
    reason: str = Field(min_length=3, max_length=500)
    user_ids: list[int] = Field(min_length=1, max_length=500)
    dry_run: bool = Field(False, description="Só confere: diz quem entraria e quem seria pulado, sem gravar")


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
        if not perm.can(actor, "absences.register"):
            raise HTTPException(403, "Só o RH ou a Administração registram ausência em nome de outra pessoa")
        target = db.get(User, body.user_id)
        if not target or target.company_id != actor.company_id or not target.active:
            raise HTTPException(404, "Colaborador não encontrado")
        if not target.tracks_time:
            raise HTTPException(422, "Esta pessoa não registra ponto: não há ausência a justificar")
    else:
        require_punch(actor)

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
    if mine or not perm.can(actor, "team.view"):
        q = q.where(Absence.user_id == actor.id)
    else:
        q = q.where(perm.scope_condition(actor))
    if user_id:
        q = q.where(Absence.user_id == user_id)
    if status:
        q = q.where(Absence.status == status)
    rows = db.execute(q.order_by(Absence.start_date.desc(), Absence.id.desc()).limit(300)).all()
    owners = {u.id: u for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    out = []
    for a, name in rows:
        item = svc.serialize(actor, a, name)
        mode = perm.decision_mode(db, actor, owners[a.user_id]) if a.status == "pending" else None
        item["can_decide"], item["self_decision"] = mode is not None, mode == "self"
        out.append(item)
    return out


@router.post("/{absence_id}/decision")
def decide(
    absence_id: int, body: DecisionIn, request: Request, actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    a = db.get(Absence, absence_id)
    if not a or a.company_id != actor.company_id:
        raise HTTPException(404, "Ausência não encontrada")
    owner = db.get(User, a.user_id)
    own = authorize_decision(db, actor, owner, body.note, "pedido de ausência")
    if a.status != "pending":
        raise HTTPException(409, "Ausência já decidida")
    _guard_closed(db, db.get(Company, a.company_id), a.start_date, a.end_date)

    a.status = "approved" if body.approve else "rejected"
    a.decided_by, a.decided_at, a.decision_note = actor.id, _now(), body.note
    audit.log(db, actor, ("self_" if own else "") + ("approve" if body.approve else "reject"), "absence", a.id, ip=client_ip(request),
              before={"status": "pending"}, after={"status": a.status, "self_approval": own, "note": body.note if own else None})
    db.commit()
    return svc.serialize(actor, a, owner.name)


@router.post("/{absence_id}/cancel")
def cancel(absence_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """O dono cancela o pedido pendente; o RH cancela também as aprovadas (enquanto o mês estiver aberto)."""
    a = db.get(Absence, absence_id)
    if not a or a.company_id != actor.company_id:
        raise HTTPException(404, "Ausência não encontrada")
    owner_pending = a.user_id == actor.id and a.status == "pending"
    if not (owner_pending or perm.can(actor, "absences.register")):
        raise HTTPException(403, "Sem permissão para cancelar esta ausência")
    if a.status not in ("pending", "approved"):
        raise HTTPException(409, "Esta ausência não pode mais ser cancelada")
    _guard_closed(db, db.get(Company, a.company_id), a.start_date, a.end_date)
    before = a.status
    a.status = "cancelled"
    audit.log(db, actor, "cancel", "absence", a.id, ip=client_ip(request), before={"status": before}, after={"status": "cancelled"})
    db.commit()
    return svc.serialize(actor, a, db.get(User, a.user_id).name)


# --- Lançamento em lote ------------------------------------------------------------
BATCH_KINDS = ("abono", "ferias")


@router.post("/batch")
def create_batch(
    body: BatchIn, request: Request, actor: User = Depends(require("absences.register")), db: Session = Depends(get_db),
):
    """Mesma ausência (já aprovada) para várias pessoas: ponte de feriado, recesso, queda de energia, férias coletivas.

    Quem não pode receber (inativo, não registra ponto, já tem ausência no período) é pulado e aparece na resposta;
    os demais entram juntos, com o mesmo `batch_id`, para conferência e cancelamento do lote inteiro.
    """
    company = db.get(Company, actor.company_id)
    if body.kind not in BATCH_KINDS:
        raise HTTPException(422, "Em lote só se lança abono ou férias coletivas")
    problem = svc.validate_period(body.kind, body.start_date, body.end_date, body.minutes)
    if problem:
        raise HTTPException(422, problem)
    if body.end_date > today_local(company) + timedelta(days=svc.MAX_DAYS):
        raise HTTPException(422, "A data final está longe demais no futuro")
    _guard_closed(db, company, body.start_date, body.end_date)

    users = {u.id: u for u in db.execute(select(User).where(User.company_id == company.id, User.id.in_(set(body.user_ids)))).scalars()}
    batch_id = uuid.uuid4().hex
    created, skipped = [], []
    for uid in dict.fromkeys(body.user_ids):  # sem repetir, na ordem enviada
        u = users.get(uid)
        if not u:
            skipped.append({"user_id": uid, "name": None, "reason": "Colaborador não encontrado"})
        elif not u.active:
            skipped.append({"user_id": u.id, "name": u.name, "reason": "Cadastro desativado"})
        elif not u.tracks_time:
            skipped.append({"user_id": u.id, "name": u.name, "reason": "Não registra ponto"})
        elif clash := svc.overlapping(db, u.id, body.start_date, body.end_date):
            c = clash[0]
            skipped.append({"user_id": u.id, "name": u.name, "reason":
                            f"Já tem {ABSENCE_LABEL[c.kind].lower()} de {c.start_date:%d/%m} a {c.end_date:%d/%m}"})
        else:
            created.append(u)

    if not body.dry_run and created:
        now = _now()
        for u in created:
            a = Absence(company_id=company.id, user_id=u.id, kind=body.kind, start_date=body.start_date, end_date=body.end_date,
                        minutes=body.minutes, reason=body.reason, created_by=actor.id, status="approved",
                        decided_by=actor.id, decided_at=now, batch_id=batch_id)
            db.add(a)
            db.flush()
            audit.log(db, actor, "create", "absence", a.id, ip=client_ip(request), after={
                "user_id": u.id, "kind": body.kind, "start": str(body.start_date), "end": str(body.end_date),
                "status": "approved", "batch_id": batch_id})
        audit.log(db, actor, "create_batch", "absence_batch", batch_id, ip=client_ip(request), after={
            "kind": body.kind, "start": str(body.start_date), "end": str(body.end_date), "minutes": body.minutes,
            "reason": body.reason, "people": len(created), "skipped": len(skipped)})
        db.commit()
    return {
        "batch_id": None if body.dry_run or not created else batch_id, "dry_run": body.dry_run,
        "created": [{"user_id": u.id, "name": u.name} for u in created], "skipped": skipped,
    }


@router.get("/batches")
def list_batches(actor: User = Depends(require("absences.register")), db: Session = Depends(get_db)):
    """Lotes lançados na empresa, do mais recente ao mais antigo (até 100)."""
    rows = db.execute(
        select(Absence).where(Absence.company_id == actor.company_id, Absence.batch_id.is_not(None)).order_by(Absence.id)
    ).scalars()
    names = {u.id: u.name for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    batches: dict[str, dict] = {}
    for a in rows:
        b = batches.setdefault(a.batch_id, {
            "batch_id": a.batch_id, "kind": a.kind, "kind_label": ABSENCE_LABEL[a.kind], "start_date": a.start_date.isoformat(),
            "end_date": a.end_date.isoformat(), "minutes": a.minutes, "reason": a.reason, "created_by": names.get(a.created_by),
            "created_at": a.created_at.isoformat(timespec="seconds"), "active": [], "cancelled": 0,
        })
        if a.status == "approved":
            b["active"].append({"absence_id": a.id, "user_id": a.user_id, "name": names.get(a.user_id)})
        else:
            b["cancelled"] += 1
    return sorted(batches.values(), key=lambda b: b["created_at"], reverse=True)[:100]


@router.post("/batch/{batch_id}/cancel")
def cancel_batch(batch_id: str, request: Request, actor: User = Depends(require("absences.register")), db: Session = Depends(get_db)):
    """Cancela de uma vez as ausências ainda aprovadas do lote (o mês precisa estar aberto)."""
    rows = list(db.execute(select(Absence).where(
        Absence.company_id == actor.company_id, Absence.batch_id == batch_id, Absence.status == "approved",
    )).scalars())
    if not rows:
        raise HTTPException(404, "Lote não encontrado ou já cancelado")
    _guard_closed(db, db.get(Company, actor.company_id), min(a.start_date for a in rows), max(a.end_date for a in rows))
    for a in rows:
        a.status = "cancelled"
        audit.log(db, actor, "cancel", "absence", a.id, ip=client_ip(request), before={"status": "approved"},
                  after={"status": "cancelled", "batch_id": batch_id})
    audit.log(db, actor, "cancel_batch", "absence_batch", batch_id, ip=client_ip(request), after={"people": len(rows)})
    db.commit()
    return {"cancelled": len(rows)}
