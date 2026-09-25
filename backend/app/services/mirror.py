"""Espelho de ponto: junta marcações originais (menos as desconsideradas) e inclusões aprovadas."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Absence, Adjustment, Company, Punch, Schedule, User
from .timecalc import DayResult, Justification, ScheduleRule, compute_month


def schedule_rule(sched: Schedule | None) -> ScheduleRule:
    if not sched:
        return ScheduleRule()
    return ScheduleRule(
        weekdays=tuple(int(x) for x in sched.weekdays.split(",") if x),
        daily_minutes=sched.daily_minutes,
        tolerance_minutes=sched.tolerance_minutes, crosses_midnight=sched.crosses_midnight,
    )


def user_marks(db: Session, user: User, lo: datetime, hi: datetime) -> tuple[list[Punch], list[Adjustment], set[int]]:
    """Marcações originais, inclusões aprovadas e ids de marcações desconsideradas, na janela [lo, hi) (UTC)."""
    approved = db.execute(
        select(Adjustment).where(Adjustment.user_id == user.id, Adjustment.status == "approved")
    ).scalars().all()
    voided = {a.target_punch_id for a in approved if a.kind == "desconsiderar"}
    punches = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at >= lo, Punch.occurred_at < hi)
    ).scalars().all()
    inclusions = [a for a in approved if a.kind == "incluir" and a.requested_at and lo <= a.requested_at < hi]
    return punches, inclusions, voided


ABSENCE_LABEL = {
    "atestado_medico": "Atestado médico", "abono": "Abono", "ferias": "Férias", "licenca": "Licença",
    "afastamento_inss": "Afastamento INSS",
}


def justifications(db: Session, user: User, first: date, last: date) -> dict[date, Justification]:
    """Ausências aprovadas do trabalhador, por dia, dentro de [first, last]. Dia inteiro prevalece sobre parcial."""
    rows = db.execute(
        select(Absence).where(
            Absence.user_id == user.id, Absence.status == "approved", Absence.start_date <= last, Absence.end_date >= first
        ).order_by(Absence.id)
    ).scalars()
    out: dict[date, Justification] = {}
    for a in rows:
        d = max(a.start_date, first)
        while d <= min(a.end_date, last):
            current = out.get(d)
            if current is None or (a.minutes is None and current.minutes is not None):
                out[d] = Justification(ABSENCE_LABEL[a.kind], a.minutes)
            d += timedelta(days=1)
    return out


def month_days(db: Session, user: User, company: Company, year: int, month: int) -> list[DayResult]:
    zone = ZoneInfo(company.timezone)
    # Janela ampla (mês ± 1 dia) para capturar jornadas que atravessam a virada do mês.
    lo = datetime(year, month, 1) - timedelta(days=1)
    hi = datetime(year + (month == 12), month % 12 + 1, 1) + timedelta(days=1)
    punches, inclusions, voided = user_marks(db, user, lo, hi)
    valid = [(p.occurred_at, p.kind) for p in punches if p.id not in voided]
    valid += [(a.requested_at, a.punch_kind) for a in inclusions]

    sched = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    today = datetime.now(zone).date()
    admission = user.admitted_at or user.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).date()
    first, last = date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return compute_month(valid, schedule_rule(sched), company.timezone, year, month, today, start=admission,
                         justified=justifications(db, user, first, last))
