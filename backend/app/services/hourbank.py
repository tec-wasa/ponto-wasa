"""Banco de horas.

Saldo = movimento automático diário + créditos - compensações lançados pelo RH.

- **Automático:** o saldo de cada dia já apurado pelo espelho (depois da tolerância legal), a partir da data de
  início do banco do trabalhador. Só entram dias com jornada concluída (`status == "ok"`): dia em andamento,
  incompleto ou futuro não contam. **Faltas de dia inteiro não entram sozinhas**: descontá-las do banco é decisão do
  RH, feita com uma compensação.
- **Lançamentos do RH** (`hour_bank_entries`): append-only; corrigir é lançar o contrário.
- **Prazo de compensação:** o saldo positivo de mais de `bank_expiry_months` meses ainda não compensado é sinalizado.
  É uma estimativa (o que existia na data de corte e continua no saldo), não uma apuração por ordem de entrada.
"""
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, HourBankEntry, User
from .mirror import month_days


@dataclass
class Movement:
    date: date
    minutes: int  # com sinal: positivo soma, negativo subtrai
    source: str  # "automatico" | "lancamento"
    description: str


def today_local(company: Company) -> date:
    return datetime.now(ZoneInfo(company.timezone)).date()


def bank_start(user: User) -> date | None:
    return user.hour_bank_start if user.hour_bank_enabled else None


def months_ago(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    last_day = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m]
    return date(y, m + 1, min(d.day, last_day))


def _month_range(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def movements(db: Session, company: Company, user: User, start: date, end: date) -> list[Movement]:
    """Movimentos (automáticos e do RH) no período, em ordem de data."""
    out: list[Movement] = []
    for year, month in _month_range(start, end):
        for day in month_days(db, user, company, year, month):
            if start <= day.date <= end and day.status == "ok" and day.balance != 0:
                label = "horas extras do dia" if day.balance > 0 else "horas a menos no dia"
                out.append(Movement(day.date, day.balance, "automatico", label))
    entries = db.execute(
        select(HourBankEntry).where(
            HourBankEntry.user_id == user.id, HourBankEntry.entry_date >= start, HourBankEntry.entry_date <= end
        )
    ).scalars().all()
    for e in entries:
        sign = 1 if e.kind == "credito" else -1
        out.append(Movement(e.entry_date, sign * e.minutes, "lancamento", ("crédito: " if sign > 0 else "compensação: ") + e.reason))
    return sorted(out, key=lambda m: (m.date, m.source))


def summary(db: Session, company: Company, user: User) -> dict:
    if not user.hour_bank_enabled:
        return {"enabled": False, "balance": 0, "alerts": []}
    today = today_local(company)
    start = user.hour_bank_start or today
    moves = movements(db, company, user, start, today)
    balance = sum(m.minutes for m in moves)
    cutoff = months_ago(today, company.bank_expiry_months)
    balance_at_cutoff = sum(m.minutes for m in moves if m.date <= cutoff)
    at_risk = max(0, min(balance_at_cutoff, balance))

    alerts = []
    if company.bank_max_minutes is not None and balance > company.bank_max_minutes:
        alerts.append({"code": "acima_do_limite", "message": f"Saldo acima do limite de {company.bank_max_minutes // 60}h"})
    if at_risk > 0:
        alerts.append({"code": "prazo_de_compensacao",
                       "message": f"{at_risk // 60}h{at_risk % 60:02d} com mais de {company.bank_expiry_months} meses ainda não compensadas"})
    return {
        "enabled": True, "since": start.isoformat(), "balance": balance,
        "automatic": sum(m.minutes for m in moves if m.source == "automatico"),
        "credits": sum(m.minutes for m in moves if m.source == "lancamento" and m.minutes > 0),
        "compensations": -sum(m.minutes for m in moves if m.source == "lancamento" and m.minutes < 0),
        "limit_minutes": company.bank_max_minutes, "expiry_months": company.bank_expiry_months,
        "at_risk_minutes": at_risk, "alerts": alerts,
    }


def statement(db: Session, company: Company, user: User, start: date, end: date) -> dict:
    """Extrato com saldo corrente. `opening` é o saldo antes de `start`."""
    if not user.hour_bank_enabled:
        return {"enabled": False, "opening": 0, "lines": [], "closing": 0}
    first = user.hour_bank_start or start
    moves = movements(db, company, user, first, end)
    opening = sum(m.minutes for m in moves if m.date < start)
    running, lines = opening, []
    for m in moves:
        if m.date < start:
            continue
        running += m.minutes
        lines.append({"date": m.date.isoformat(), "minutes": m.minutes, "source": m.source,
                      "description": m.description, "balance": running})
    return {"enabled": True, "opening": opening, "lines": lines, "closing": running}
