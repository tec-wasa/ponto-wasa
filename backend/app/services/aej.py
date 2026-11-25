"""Gerador do AEJ (Arquivo Eletrônico de Jornada) — Portaria MTP 671/2021, Anexo VI, versão 001.

O AEJ é gerado pelo programa de tratamento: junta as marcações originais do REP (fonte "O"),
as inclusões manuais aprovadas (fonte "I") e as desconsiderações aprovadas (tipo "D").
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Adjustment, Company, Schedule, User, utcnow
from . import arp, hourbank
from .afd import ExportError, resolve_identity, utc_bounds
from .arp import digits_only, fmt_dh
from .layout import encode, field
from .mirror import month_days, user_marks
from .punching import IN_KINDS


def _hhmm(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}{minutes % 60:02d}"


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def contract_hours(s: Schedule) -> list[str]:
    """Horário contratual (registro 04): pares entrada/saída derivados de início, intervalo e carga."""
    start = _to_min(s.start_time)
    if s.break_minutes > 0:
        b_start = _to_min(s.break_start)
        first = b_start - start
        e2 = b_start + s.break_minutes
        pairs = [_hhmm(start), _hhmm(b_start), _hhmm(e2), _hhmm(e2 + max(s.daily_minutes - first, 0))]
    else:
        pairs = [_hhmm(start), _hhmm(start + s.daily_minutes), "", ""]
    return [f"H{s.id}", str(s.daily_minutes), *pairs]


def build_aej(db: Session, company: Company, start: date, end: date, now: datetime | None = None) -> tuple[str, bytes]:
    if end < start:
        raise ExportError(422, "Data final anterior à data inicial")
    ident = resolve_identity(company)
    now = now or utcnow()
    lo, hi = utc_bounds(company, start, end)

    # Colaboradores com movimento no período (ou ativos) e suas marcações.
    users = db.execute(select(User).where(User.company_id == company.id, User.tracks_time.is_(True)).order_by(User.id)).scalars().all()
    people = []
    for u in users:
        punches, inclusions, voided = user_marks(db, u, lo, hi)
        reasons = {
            a.target_punch_id: a.reason
            for a in db.execute(
                select(Adjustment).where(Adjustment.user_id == u.id, Adjustment.status == "approved", Adjustment.kind == "desconsiderar")
            ).scalars()
        }
        if not (punches or inclusions) and not u.active:
            continue
        people.append((u, punches, inclusions, voided, reasons))

    missing = [u.name for u, p, i, _, _ in people if (p or i) and not u.schedule_id]
    if missing:
        raise ExportError(409, "Colaboradores com marcações e sem jornada (horário contratual) cadastrada: " + ", ".join(missing))

    off_now = arp.offset_minutes(company.timezone, now)
    counts = {f"{i:02d}": 0 for i in range(1, 9)}
    out: list[str] = []

    def add(kind: str, *values: str) -> None:
        out.append("|".join([kind, *values]))
        counts[kind] += 1

    add("01", ident.employer_type, ident.employer_id, digits_only(company.caepf), digits_only(company.cno),
        field(company.name, 150), f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}", fmt_dh(now, off_now), "001")
    add("02", "1", "3", ident.inpi.zfill(17))  # um único REP-P: id 1, tipo 3

    schedules: dict[int, Schedule] = {}
    for idx, (u, punches, inclusions, _voided, _reasons) in enumerate(people, start=1):
        add("03", str(idx), u.cpf, field(u.name, 150))
        if u.schedule_id and (punches or inclusions):
            schedules[u.schedule_id] = db.get(Schedule, u.schedule_id)
    for s in schedules.values():
        add("04", *contract_hours(s))

    for idx, (u, punches, inclusions, voided, reasons) in enumerate(people, start=1):
        marks = [(p.occurred_at, p.kind, "O", p.tz_offset_min, p.id in voided, reasons.get(p.id, "")) for p in punches]
        marks += [(a.requested_at, a.punch_kind, "I", arp.offset_minutes(company.timezone, a.requested_at), False, a.reason)
                  for a in inclusions]
        marks.sort(key=lambda m: m[0])
        per_day: dict[date, int] = {}
        current_seq, open_pair = 0, False
        for when, kind, source, offset, is_void, reason in marks:
            stamp = fmt_dh(when, offset)
            rep_id = "1" if source == "O" else ""
            if is_void:
                add("05", str(idx), stamp, rep_id, "D", "000", source, "", field(reason, 150))
                continue
            if kind in IN_KINDS:
                day = (when + timedelta(minutes=offset)).date()
                per_day[day] = per_day.get(day, 0) + 1
                current_seq, open_pair = per_day[day], True
                tp = "E"
            else:
                tp = "S"
                if not open_pair:  # saída sem entrada: mantém a última sequência conhecida
                    current_seq = max(current_seq, 1)
                open_pair = False
            code = f"H{u.schedule_id}" if tp == "E" and current_seq == 1 else ""
            motive = field(reason, 150) if source == "I" else ""
            add("05", str(idx), stamp, rep_id, tp, f"{current_seq:03d}", source, code, motive)

        # Registro 07, tipo 3: movimentos do banco de horas (1 = inclusão de horas; 2 = compensação).
        if u.hour_bank_enabled and u.hour_bank_start:
            bank_start = max(start, u.hour_bank_start)
            if bank_start <= end:
                for mv in hourbank.movements(db, company, u, bank_start, end):
                    add("07", str(idx), "3", f"{mv.date:%Y-%m-%d}", str(abs(mv.minutes)), "1" if mv.minutes > 0 else "2")

        # Registro 07, tipo 2: faltas não justificadas do período (DSR ainda não implementado).
        if u.schedule_id:
            months = sorted({(d.year, d.month) for d in _daterange(start, end)})
            for year, mon in months:
                for day in month_days(db, u, company, year, mon):
                    if day.status == "falta" and start <= day.date <= end:
                        add("07", str(idx), "2", f"{day.date:%Y-%m-%d}", "", "")

    # (o registro 07 do banco de horas é emitido dentro do laço de cada colaborador, acima)
    add("08", field(settings.program_name, 150), field(settings.program_version, 8), ident.dev_type,
        ident.dev_id, field(settings.dev_name, 150), field(settings.dev_email, 50))

    trailer = "|".join(["99"] + [str(counts[f"{i:02d}"]) for i in range(1, 9)])
    return f"AEJ{ident.employer_id}{start:%Y%m%d}{end:%Y%m%d}.txt", encode([*out, trailer])


def _daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)
