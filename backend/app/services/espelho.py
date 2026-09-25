"""Relatório Espelho de Ponto Eletrônico (Portaria MTP 671/2021, Art. 84).

Conteúdo mínimo: (I) empregador com nome, CNPJ/CPF e CEI/CAEPF/CNO; (II) trabalhador com nome, CPF,
data de admissão e cargo/função; (III) data de emissão e período; (IV) horário e jornada contratual;
(V) marcações efetuadas no REP e marcações tratadas (incluídas e desconsideradas); (VI) duração das
jornadas realizadas, considerando a hora noturna reduzida.
"""
import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, Company, Schedule, User, utcnow
from .aej import contract_hours
from .mirror import month_days, user_marks
from .punching import IN_KINDS

KIND_LABEL = {"entrada": "Entrada", "saida": "Saída", "inicio_intervalo": "Intervalo", "fim_intervalo": "Retorno do intervalo"}
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
STATUS_LABEL = {"ok": "Regular", "folga": "Folga", "falta": "Falta", "incompleto": "Incompleto", "hoje": "Em andamento",
                "futuro": "-", "anterior": "Antes da admissão", "justificada": "Ausência justificada"}


def _hh_mm(hhmm4: str) -> str:
    return f"{hhmm4[:2]}:{hhmm4[2:]}"


def contract_text(s: Schedule | None) -> dict:
    if not s:
        return {"name": "Não cadastrado", "days": [], "text": "Sem horário contratual cadastrado", "daily_minutes": 0}
    _, dur, e1, s1, e2, s2 = contract_hours(s)
    periods = [f"{_hh_mm(e1)}-{_hh_mm(s1)}"] + ([f"{_hh_mm(e2)}-{_hh_mm(s2)}"] if e2 else [])
    days = [int(x) for x in s.weekdays.split(",") if x]
    return {"name": s.name, "days": days, "text": " e ".join(periods), "daily_minutes": int(dur),
            "weekdays": ", ".join(WEEKDAYS[d] for d in days)}


def build_espelho(db: Session, company: Company, user: User, year: int, month: int, now: datetime | None = None) -> dict:
    now = now or utcnow()
    zone = ZoneInfo(company.timezone)
    days = month_days(db, user, company, year, month)
    sched = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    contract = contract_text(sched)

    lo = datetime(year, month, 1) - timedelta(days=1)
    hi = datetime(year + (month == 12), month % 12 + 1, 1) + timedelta(days=1)
    punches, inclusions, voided = user_marks(db, user, lo, hi)
    reasons = {
        a.target_punch_id: a.reason
        for a in db.execute(
            select(Adjustment).where(Adjustment.user_id == user.id, Adjustment.status == "approved", Adjustment.kind == "desconsiderar")
        ).scalars()
    }

    def local(dt: datetime) -> datetime:
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)

    # Cada marca é exibida no dia em que o turno começou; a saída de um turno que atravessa a meia-noite
    # ganha "(dia seguinte)" em vez de aparecer solta no dia seguinte, o que pareceria um turno aberto.
    valid = sorted(
        [(local(p.occurred_at), "p", p, p.kind) for p in punches if p.id not in voided]
        + [(local(a.requested_at), "a", a, a.punch_kind) for a in inclusions],
        key=lambda t: t[0],
    )
    shown: dict[tuple[str, int], tuple[date, bool]] = {}
    open_in: datetime | None = None
    crosses = bool(sched and sched.crosses_midnight)
    for when, tag, obj, kind in valid:
        if open_in is not None and not crosses and when.date() != open_in.date():
            open_in = None  # jornada que se encerra à meia-noite: a entrada anterior ficou sem saída
        if open_in is None:
            if kind in IN_KINDS:
                open_in = when
            shown[(tag, obj.id)] = (when.date(), False)
        elif kind in IN_KINDS:  # entrada repetida: mantém a primeira, como o motor de cálculo
            shown[(tag, obj.id)] = (when.date(), False)
        else:
            shown[(tag, obj.id)] = (open_in.date(), when.date() > open_in.date())
            open_in = None

    rep: dict[date, list[str]] = {}
    treated: dict[date, list[str]] = {}
    for p in sorted(punches, key=lambda x: x.occurred_at):
        when = local(p.occurred_at)
        if p.id in voided:
            day_key, next_day = when.date(), False
            treated.setdefault(day_key, []).append(
                f"{when:%H:%M} {KIND_LABEL[p.kind]}: desconsiderada - {reasons.get(p.id, '')}".strip())
        else:
            day_key, next_day = shown[("p", p.id)]
        rep.setdefault(day_key, []).append(
            f"{when:%H:%M} {KIND_LABEL[p.kind]} (NSR {p.nsr})" + (" (off-line)" if p.offline else "")
            + (" (dia seguinte)" if next_day else ""))
    for a in sorted(inclusions, key=lambda x: x.requested_at):
        when = local(a.requested_at)
        day_key, next_day = shown[("a", a.id)]
        treated.setdefault(day_key, []).append(
            f"{when:%H:%M} {KIND_LABEL[a.punch_kind]}: incluída manualmente" + (" (dia seguinte)" if next_day else "")
            + f" - {a.reason}")

    rows = []
    for d in days:
        working = d.date.weekday() in contract["days"]
        rows.append({
            "date": d.date.isoformat(), "weekday": WEEKDAYS[d.date.weekday()],
            "contract": contract["text"] if working else "Folga",
            "rep": rep.get(d.date, []), "treated": treated.get(d.date, []),
            "worked": d.worked, "night": d.night_minutes, "reduced": d.reduced_minutes, "balance": d.balance,
            "status": STATUS_LABEL[d.status] + (f" ({d.justification})" if d.justification else ""), "warnings": d.warnings,
        })

    admission = user.admitted_at or local(user.created_at).date()
    last = calendar.monthrange(year, month)[1]
    return {
        "employer": {"name": company.name, "id": company.cnpj, "caepf_cno": company.caepf or company.cno,
                     "workplace": company.workplace},
        "worker": {"name": user.name, "cpf": user.cpf, "admitted_at": admission.isoformat(),
                   "job_title": user.job_title or "Não informado"},
        "issued_at": local(now).strftime("%d/%m/%Y %H:%M"),
        "period": {"start": date(year, month, 1).isoformat(), "end": date(year, month, last).isoformat()},
        "contract": {"name": contract["name"], "weekdays": contract.get("weekdays", ""), "periods": contract["text"],
                     "daily_minutes": contract["daily_minutes"]},
        "rows": rows,
        "totals": {"worked": sum(r["worked"] for r in rows), "night": sum(r["night"] for r in rows),
                   "reduced": sum(r["reduced"] for r in rows), "balance": sum(r["balance"] for r in rows),
                   "absences": sum(1 for r in rows if r["status"] == "Falta"),
                   "justified": sum(1 for r in rows if r["status"].startswith("Ausência justificada"))},
    }
