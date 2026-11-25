"""Painel do gestor (RF-18) e banco de horas (RF-15)."""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..db import get_db
from ..deps import can_view_user, client_ip, get_current_user, require
from ..models import Adjustment, Company, HourBankEntry, User
from ..schemas import HourBankEntryIn, HourBankEntryOut
from ..services import audit, hourbank, panel
from ..services.punching import month_is_closed, month_of

router = APIRouter(tags=["gestão"])

def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --- Painel do gestor -----------------------------------------------------------
@router.get("/dashboard")
def dashboard(
    at: datetime | None = Query(None, description="Instante consultado (UTC); padrão: agora. Só passado ou presente."),
    bank: bool = Query(False, description="Inclui o saldo do banco de horas de quem o utiliza"),
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Situação da equipe (gestor) ou da empresa (RH/admin) em um instante."""
    company = db.get(Company, actor.company_id)
    moment = _utcnow() if at is None else (at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo else at)
    if moment > _utcnow() + timedelta(minutes=1):
        raise HTTPException(422, "Só é possível consultar o presente ou o passado")

    users = panel.scope_users(db, actor)
    approved = db.execute(select(Adjustment).where(Adjustment.status == "approved", Adjustment.kind == "desconsiderar")).scalars()
    voided = {a.target_punch_id for a in approved}
    people = [panel.person_state(db, company, u, moment, voided) for u in users]

    counts = {s: 0 for s in panel.STATE_ORDER}
    for p in people:
        counts[p.state] += 1
    people.sort(key=lambda p: (panel.STATE_ORDER.index(p.state), -p.late_minutes, p.user.name))

    rows = []
    bank_alerts = 0
    for p in people:
        row = {
            "user_id": p.user.id, "name": p.user.name, "job_title": p.user.job_title, "state": p.state,
            "state_label": panel.STATE_LABEL[p.state], "first_entry": p.first_entry, "last_punch": p.last_punch,
            "worked_minutes": p.worked_minutes, "late_minutes": p.late_minutes, "no_schedule": p.no_schedule,
        }
        if bank and p.user.hour_bank_enabled:
            s = hourbank.summary(db, company, p.user)
            row["bank_balance"], row["bank_alerts"] = s["balance"], s["alerts"]
            bank_alerts += 1 if s["alerts"] else 0
        rows.append(row)

    local_at = moment.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(company.timezone))
    return {
        "as_of": local_at.strftime("%Y-%m-%dT%H:%M"), "date": local_at.date().isoformat(),
        "summary": {
            "total": len(people), **counts, "late": sum(1 for p in people if p.late_minutes),
            "pending_adjustments": panel.pending_adjustments(db, users), "bank_alerts": bank_alerts,
        },
        "people": rows,
    }


# --- Banco de horas -------------------------------------------------------------
def _target(db: Session, actor: User, user_id: int | None) -> User:
    target = db.get(User, user_id) if user_id else actor
    if not target or not can_view_user(db, actor, target):
        raise HTTPException(404, "Colaborador não encontrado")
    return target


@router.get("/hour-bank")
def hour_bank(user_id: int | None = None, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Saldo, limite e alertas do banco de horas do trabalhador."""
    target = _target(db, actor, user_id)
    return {"user_id": target.id, **hourbank.summary(db, db.get(Company, target.company_id), target)}


@router.get("/hour-bank/statement")
def hour_bank_statement(
    start: date, end: date, user_id: int | None = None,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Extrato do banco de horas com saldo corrente."""
    if end < start or (end - start).days > 400:
        raise HTTPException(422, "Período inválido (máximo de 400 dias)")
    target = _target(db, actor, user_id)
    return {"user_id": target.id, **hourbank.statement(db, db.get(Company, target.company_id), target, start, end)}


@router.get("/hour-bank/team")
def hour_bank_team(actor: User = Depends(require("team.view")), db: Session = Depends(get_db)):
    """Saldos de quem usa banco de horas (equipe do gestor; empresa toda para RH, admin e auditor)."""
    company = db.get(Company, actor.company_id)
    q = select(User).where(perm.scope_condition(actor), User.active.is_(True), User.hour_bank_enabled.is_(True),
                           User.tracks_time.is_(True))
    rows = []
    for u in db.execute(q.order_by(User.name)).scalars():
        s = hourbank.summary(db, company, u)
        rows.append({"user_id": u.id, "name": u.name, "balance": s["balance"], "limit_minutes": s["limit_minutes"],
                     "at_risk_minutes": s["at_risk_minutes"], "alerts": s["alerts"]})
    return rows


@router.post("/hour-bank/entries", response_model=HourBankEntryOut, status_code=201)
def add_entry(
    body: HourBankEntryIn, request: Request,
    actor: User = Depends(require("hourbank.entries")), db: Session = Depends(get_db),
):
    """Lançamento manual do RH: crédito ou compensação. Não se edita nem se apaga; corrige-se com o lançamento contrário."""
    company = db.get(Company, actor.company_id)
    target = db.get(User, body.user_id)
    if not target or target.company_id != actor.company_id:
        raise HTTPException(404, "Colaborador não encontrado")
    if not target.hour_bank_enabled or not target.tracks_time:
        raise HTTPException(409, "Este colaborador não usa banco de horas")
    if body.entry_date > hourbank.today_local(company):
        raise HTTPException(422, "A data do lançamento não pode ser futura")
    if body.entry_date < (target.hour_bank_start or body.entry_date):
        raise HTTPException(422, "A data é anterior ao início do banco de horas do colaborador")
    entry_month = month_of(company, datetime.combine(body.entry_date, datetime.min.time()) + timedelta(hours=12))
    if month_is_closed(db, company.id, entry_month):
        raise HTTPException(409, "O mês do lançamento está fechado")

    if body.kind == "compensacao":
        balance = hourbank.summary(db, company, target)["balance"]
        if body.minutes > balance:
            raise HTTPException(409, f"Saldo insuficiente: o saldo atual é de {balance} minutos")

    entry = HourBankEntry(
        company_id=company.id, user_id=target.id, entry_date=body.entry_date, kind=body.kind,
        minutes=body.minutes, reason=body.reason, created_by=actor.id,
    )
    db.add(entry)
    db.flush()
    audit.log(db, actor, "create", "hour_bank_entry", entry.id, ip=client_ip(request),
              after={"user_id": target.id, "kind": body.kind, "minutes": body.minutes, "date": str(body.entry_date)})
    db.commit()
    return entry


@router.get("/hour-bank/entries", response_model=list[HourBankEntryOut])
def list_entries(user_id: int | None = None, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = _target(db, actor, user_id)
    rows = db.execute(
        select(HourBankEntry).where(HourBankEntry.user_id == target.id).order_by(HourBankEntry.entry_date.desc(), HourBankEntry.id.desc())
    ).scalars()
    return list(rows)
