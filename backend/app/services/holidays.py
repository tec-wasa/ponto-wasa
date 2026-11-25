"""Feriados: os nacionais são calculados (inclusive a Sexta-feira Santa, pela data da Páscoa); Carnaval e Corpus Christi
(pontos facultativos nacionais) entram só se a empresa marcar; os estaduais e municipais a empresa cadastra (repetem todo
ano ou valem numa data só). Num feriado, a jornada prevista do dia é zero: não há falta, e o trabalhado conta como extra."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Holiday

FIXED_NATIONAL = {  # (mês, dia): nome. Lei 662/1949, Lei 6.802/1980 (12/10), Lei 14.759/2023 (20/11)
    (1, 1): "Confraternização Universal", (4, 21): "Tiradentes", (5, 1): "Dia do Trabalho",
    (9, 7): "Independência do Brasil", (10, 12): "Nossa Senhora Aparecida", (11, 2): "Finados",
    (11, 15): "Proclamação da República", (11, 20): "Dia Nacional de Zumbi e da Consciência Negra", (12, 25): "Natal",
}


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo anônimo gregoriano)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lday = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lday) // 451
    month = (h + lday - 7 * m + 114) // 31
    day = (h + lday - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def national(year: int) -> dict[date, str]:
    out = {date(year, m, d): name for (m, d), name in FIXED_NATIONAL.items()}
    out[easter(year) - timedelta(days=2)] = "Sexta-feira Santa"
    return out


def optional(year: int, carnaval: bool, corpus_christi: bool) -> dict[date, str]:
    p = easter(year)
    out = {}
    if carnaval:
        out[p - timedelta(days=48)] = "Carnaval"
        out[p - timedelta(days=47)] = "Carnaval"
    if corpus_christi:
        out[p + timedelta(days=60)] = "Corpus Christi"
    return out


def company_holidays(db: Session, company: Company, first: date, last: date) -> dict[date, str]:
    """Todos os feriados da empresa entre `first` e `last` (inclusive): nacionais, opcionais marcados e os cadastrados."""
    out: dict[date, str] = {}
    for year in range(first.year, last.year + 1):
        out.update(national(year))
        out.update(optional(year, bool(company.holiday_carnaval), bool(company.holiday_corpus_christi)))
    for h in db.execute(select(Holiday).where(Holiday.company_id == company.id)).scalars():
        if h.recurring:
            for year in range(first.year, last.year + 1):
                try:
                    out[date(year, h.day.month, h.day.day)] = h.name
                except ValueError:  # 29/02 em ano comum
                    pass
        else:
            out[h.day] = h.name
    return {d: n for d, n in out.items() if first <= d <= last}


def year_list(db: Session, company: Company, year: int) -> list[dict]:
    """Calendário do ano para a tela: cada feriado com a origem (nacional, opcional ou da empresa)."""
    rows = [{"date": d, "name": n, "source": "nacional", "id": None} for d, n in national(year).items()]
    rows += [{"date": d, "name": n, "source": "opcional", "id": None}
             for d, n in optional(year, bool(company.holiday_carnaval), bool(company.holiday_corpus_christi)).items()]
    for h in db.execute(select(Holiday).where(Holiday.company_id == company.id)).scalars():
        if h.recurring:
            try:
                rows.append({"date": date(year, h.day.month, h.day.day), "name": h.name, "source": "empresa", "id": h.id,
                             "recurring": True})
            except ValueError:
                pass
        elif h.day.year == year:
            rows.append({"date": h.day, "name": h.name, "source": "empresa", "id": h.id, "recurring": False})
    return sorted(rows, key=lambda r: r["date"])
