"""Painel do gestor (RF-18): quem está presente, em intervalo, atrasado ou sem marcação, em um instante.

O estado é calculado só com as marcações reais do REP (ajustes não mudam quem "está aqui agora").
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..models import Absence, Adjustment, Company, Punch, Schedule, User
from .holidays import company_holidays
from .mirror import schedule_rule
from .punching import IN_KINDS, month_is_closed

PUNCH_TOLERANCE = 5  # CLT art. 58 §1º: 5 minutos por marcação
OPEN_ENTRY_LIMIT = timedelta(hours=16)  # entrada aberta há mais que isso = saída esquecida (mesma regra do registro)

# Ordem de atenção no painel: o que exige ação do gestor vem primeiro.
STATE_ORDER = ["sem_marcacao", "incompleto", "presente", "em_intervalo", "aguardando", "saiu", "justificada", "folga"]
STATE_LABEL = {
    "sem_marcacao": "Sem marcação", "incompleto": "Saída não registrada", "presente": "Presente",
    "em_intervalo": "Em intervalo", "aguardando": "Ainda não iniciou", "saiu": "Saiu", "justificada": "Ausência justificada",
    "folga": "Folga",
}


@dataclass
class Person:
    user: User
    state: str
    first_entry: str | None
    last_punch: str | None
    worked_minutes: int
    late_minutes: int
    no_schedule: bool


def _hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def person_state(db: Session, company: Company, user: User, at: datetime, voided: set[int]) -> Person:
    """`at`: instante em UTC (naive). Considera as marcações até `at`."""
    zone = ZoneInfo(company.timezone)
    utc = ZoneInfo("UTC")
    local_at = at.replace(tzinfo=utc).astimezone(zone)
    day = local_at.date()

    sched = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    rule = schedule_rule(sched)
    start_min = _hm(sched.start_time) if sched else 8 * 60
    holiday = company_holidays(db, company, day, day).get(day)
    working = day.weekday() in rule.weekdays and not holiday

    def local(p: Punch) -> datetime:
        return p.occurred_at.replace(tzinfo=utc).astimezone(zone)

    # Marcações do dia local (até `at`) e a última marcação válida de qualquer data: uma entrada esquecida há
    # dias precisa continuar aparecendo como "saída não registrada".
    day_start = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(utc).replace(tzinfo=None)
    today_rows = [
        p for p in db.execute(
            select(Punch).where(Punch.user_id == user.id, Punch.occurred_at >= day_start, Punch.occurred_at <= at)
            .order_by(Punch.occurred_at)
        ).scalars() if p.id not in voided
    ]
    latest = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at <= at).order_by(Punch.occurred_at.desc()).limit(30)
    ).scalars()
    last = next((p for p in latest if p.id not in voided), None)
    first_in = next((p for p in today_rows if p.kind in IN_KINDS), None)

    # tempo trabalhado hoje: pares entrada -> saída; entrada aberta conta até `at`
    worked, open_since = 0, None
    for p in today_rows:
        if p.kind in IN_KINDS:
            open_since = open_since or p.occurred_at
        elif open_since:
            worked += int((p.occurred_at - open_since).total_seconds() // 60)
            open_since = None
    if open_since:
        worked += int((at - open_since).total_seconds() // 60)

    late = 0
    if first_in and working and sched:
        lateness = local(first_in).hour * 60 + local(first_in).minute - start_min
        late = lateness if lateness > PUNCH_TOLERANCE else 0

    crosses = bool(sched and sched.crosses_midnight)
    if last and last.kind in IN_KINDS:
        still_open = at - last.occurred_at <= OPEN_ENTRY_LIMIT and (crosses or local(last).date() == day)
        state = "presente" if still_open else "incompleto"
    elif last and last.kind == "inicio_intervalo" and local(last).date() == day:
        state = "em_intervalo"
    elif last and local(last).date() == day:
        state = "saiu"
    elif working and db.execute(
        select(Absence.id).where(
            Absence.user_id == user.id, Absence.status == "approved", Absence.minutes.is_(None),
            Absence.start_date <= day, Absence.end_date >= day,
        ).limit(1)
    ).first():
        state = "justificada"  # atestado, férias, licença...: não é "sem marcação"
    elif not working:
        state = "folga"
    elif local_at.hour * 60 + local_at.minute < start_min + PUNCH_TOLERANCE:
        state = "aguardando"
    else:
        state = "sem_marcacao"

    return Person(
        user=user, state=state, first_entry=f"{local(first_in):%H:%M}" if first_in else None,
        last_punch=f"{local(last):%H:%M}" if last and local(last).date() == day else None,
        worked_minutes=worked, late_minutes=late, no_schedule=sched is None,
    )


def scope_users(db: Session, actor: User) -> list[User]:
    """Quem a pessoa acompanha na gestão (equipe ou empresa), entre quem registra ponto; nunca ela mesma."""
    q = select(User).where(perm.scope_condition(actor, include_self=False), User.active.is_(True),
                           User.role != "auditor", User.tracks_time.is_(True))
    return list(db.execute(q.order_by(User.name)).scalars())


def pending_adjustments(db: Session, users: list[User]) -> int:
    if not users:
        return 0
    ids = [u.id for u in users]
    return len(db.execute(select(Adjustment.id).where(Adjustment.status == "pending", Adjustment.user_id.in_(ids))).all())


# --- Indicadores do mês (dashboard) ----------------------------------------------
DAY_KINDS = ("ok", "incompleto", "falta", "justificada")


def month_overview(db: Session, company: Company, actor: User, year: int, month: int) -> dict:
    """Indicadores do mês de quem a pessoa acompanha: totais, situação dia a dia e por pessoa.

    Usa o mesmo cálculo do espelho (ajustes aprovados, ausências, feriados). Dias futuros não entram; o dia de hoje
    entra como "ok" só se já tem marcação.
    """
    from . import hourbank
    from .mirror import month_days

    users = scope_users(db, actor)
    by_day: dict[str, dict[str, int]] = {}
    people = []
    for u in users:
        days = month_days(db, u, company, year, month)
        sched = db.get(Schedule, u.schedule_id) if u.schedule_id else None
        start_min = _hm(sched.start_time) if sched else None
        late_days = late_minutes = 0
        for d in days:
            kind = d.status if d.status in DAY_KINDS else ("ok" if d.status == "hoje" and d.punches else None)
            if kind:
                slot = by_day.setdefault(d.date.isoformat(), {k: 0 for k in DAY_KINDS})
                slot[kind] += 1
            first_in = next((p for p in d.punches if p.split(" ")[1] in IN_KINDS), None)
            if start_min is not None and first_in and d.expected > 0:
                lateness = _hm(first_in.split(" ")[0]) - start_min
                if lateness > PUNCH_TOLERANCE:
                    late_days += 1
                    late_minutes += lateness
        bank = hourbank.summary(db, company, u) if u.hour_bank_enabled else None
        people.append({
            "user_id": u.id, "name": u.name, "job_title": u.job_title,
            "worked": sum(d.worked for d in days),
            "expected": sum(d.expected for d in days if d.status not in ("futuro", "hoje", "anterior")),
            "balance": sum(d.balance for d in days),
            "extra": sum(d.balance for d in days if d.balance > 0),
            "absences": sum(1 for d in days if d.status == "falta"),
            "incomplete": sum(1 for d in days if d.status == "incompleto"),
            "justified": sum(1 for d in days if d.status == "justificada"),
            "late_days": late_days, "late_minutes": late_minutes,
            "bank_balance": bank["balance"] if bank else None, "bank_alerts": len(bank["alerts"]) if bank else 0,
        })

    ids = [u.id for u in users]
    pending_abs = len(db.execute(select(Absence.id).where(Absence.status == "pending", Absence.user_id.in_(ids))).all()) if ids else 0
    keys = ("worked", "expected", "balance", "extra", "absences", "incomplete", "justified", "late_days")
    totals = {k: sum(p[k] for p in people) for k in keys}
    totals["debit"] = sum(p["balance"] - p["extra"] for p in people)
    with_bank = [p for p in people if p["bank_balance"] is not None]
    return {
        "month": f"{year:04d}-{month:02d}",
        "closed": month_is_closed(db, company.id, f"{year:04d}-{month:02d}"),
        "people_count": len(people),
        "totals": totals,
        "pending": {"adjustments": pending_adjustments(db, users), "absences": pending_abs},
        "bank": {"people": len(with_bank), "balance": sum(p["bank_balance"] for p in with_bank),
                 "alerts": sum(1 for p in with_bank if p["bank_alerts"])},
        "days": [{"date": k, **v} for k, v in sorted(by_day.items())],
        "people": sorted(people, key=lambda p: p["name"]),
    }
