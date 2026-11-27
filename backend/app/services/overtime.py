"""Horas extras pagas: faixas e percentuais por tipo de dia (útil, sábado, domingo, feriado).

Vale para quem NÃO usa banco de horas: o saldo positivo do dia (o mesmo do espelho, já com a tolerância) é a hora
extra. Em cada tipo de dia, as primeiras `limit` minutos do dia pagam `first` %, e o que passar paga `excess` %.
Para quem usa banco de horas, o saldo positivo vai para o banco e não é pago aqui.

A hora noturna reduzida e o adicional noturno continuam à parte (minutos noturnos no espelho e no fechamento).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ..models import Company, User
from .timecalc import DayResult

DAY_TYPES = ("util", "sabado", "domingo", "feriado")
DAY_TYPE_LABEL = {"util": "Dias úteis", "sabado": "Sábados", "domingo": "Domingos", "feriado": "Feriados"}

# Padrão: CLT art. 59 §1º (no mínimo 50 %) e Súmula 146 do TST (domingo e feriado trabalhados sem folga: em dobro).
DEFAULT_RULE: dict[str, dict] = {
    "util": {"limit": None, "first": 50, "excess": 50},
    "sabado": {"limit": None, "first": 50, "excess": 50},
    "domingo": {"limit": None, "first": 100, "excess": 100},
    "feriado": {"limit": None, "first": 100, "excess": 100},
}


def company_rule(company: Company) -> dict[str, dict]:
    """A regra da empresa, completada com o padrão onde faltar."""
    saved = company.overtime_rule or {}
    return {t: {**DEFAULT_RULE[t], **(saved.get(t) or {})} for t in DAY_TYPES}


def day_type(d: DayResult) -> str:
    if d.holiday:
        return "feriado"
    return {5: "sabado", 6: "domingo"}.get(d.date.weekday(), "util")


def split(minutes: int, band: dict) -> list[tuple[int, int]]:
    """Divide os minutos extras do dia em (percentual, minutos) conforme a faixa."""
    if minutes <= 0:
        return []
    limit = band.get("limit")
    if limit is None or minutes <= limit or band["first"] == band["excess"]:
        return [(band["first"], minutes)]
    parts = [(band["first"], limit)] if limit > 0 else []
    return parts + [(band["excess"], minutes - limit)]


@dataclass
class OvertimeDay:
    date: date
    type: str
    minutes: int
    parts: list[tuple[int, int]]


@dataclass
class Overtime:
    total: int = 0
    by_percent: dict[int, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    days: list[OvertimeDay] = field(default_factory=list)


def compute(days: list[DayResult], rule: dict[str, dict]) -> Overtime:
    by_pct: dict[int, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    out = Overtime()
    for d in days:
        if d.balance <= 0:
            continue
        t = day_type(d)
        parts = split(d.balance, rule[t])
        for pct, m in parts:
            by_pct[pct] += m
        by_type[t] += d.balance
        out.total += d.balance
        out.days.append(OvertimeDay(d.date, t, d.balance, parts))
    out.by_percent = dict(sorted(by_pct.items()))
    out.by_type = {t: by_type[t] for t in DAY_TYPES if by_type.get(t)}
    return out


def for_user(user: User, company: Company, days: list[DayResult]) -> Overtime | None:
    """Horas extras pagas do período; None para quem usa banco de horas (o saldo vai para o banco)."""
    if user.hour_bank_enabled:
        return None
    return compute(days, company_rule(company))


def as_dict(ot: Overtime | None) -> dict | None:
    if ot is None:
        return None
    return {
        "total": ot.total,
        "by_percent": [{"percent": p, "minutes": m} for p, m in ot.by_percent.items()],
        "by_type": [{"type": t, "label": DAY_TYPE_LABEL[t], "minutes": m} for t, m in ot.by_type.items()],
    }
