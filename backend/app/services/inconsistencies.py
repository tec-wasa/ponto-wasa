"""Inconsistências do ponto à luz da CLT: o que a gestão precisa olhar antes de fechar o mês.

Calculadas a partir do mesmo espelho (marcações válidas, inclusões aprovadas, ausências e feriados); nada é gravado
além da decisão "resolvido" (`InconsistencyResolution`). `detect` é puro e testável; `collect` busca os dados.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, InconsistencyResolution, User
from .timecalc import DayResult

MIN_REST_BETWEEN = 11 * 60  # art. 66: 11 h consecutivas entre duas jornadas
MAX_DAYS_IN_A_ROW = 6  # art. 67: descanso semanal; o 7º dia seguido de trabalho é inconsistência
MAX_STRETCH = 6 * 60  # art. 71: trabalho contínuo acima de 6 h exige intervalo
LONG_DAY, LONG_BREAK = 6 * 60, 60  # art. 71: jornada acima de 6 h, intervalo mínimo de 1 h
SHORT_DAY, SHORT_BREAK = 4 * 60, 15  # art. 71 §1º: jornada acima de 4 h até 6 h, intervalo de 15 min
MAX_EXTRA = 120  # art. 59: no máximo 2 h extras por dia
BRITISH_RUN = 5  # dias seguidos com os mesmos horários (Súmula 338, III, do TST)
LOOKBACK_DAYS = 7  # dias antes do período, para o 7º dia seguido e as 11 h entre jornadas

KINDS: dict[str, tuple[str, str]] = {  # tipo: (rótulo, base legal)
    "falta": ("Falta", "Dia de trabalho previsto sem marcação nem justificativa"),
    "saida_ausente": ("Saída não registrada", "Entrada sem a saída correspondente"),
    "intervalo": ("Intervalo insuficiente", "CLT art. 71"),
    "sem_intervalo": ("Mais de 6 h sem intervalo", "CLT art. 71"),
    "horas_extras": ("Mais de 2 h extras no dia", "CLT art. 59"),
    "interjornada": ("Menos de 11 h entre jornadas", "CLT art. 66"),
    "dsr": ("7º dia seguido sem folga", "CLT art. 67"),
    "britanico": ("Ponto britânico", "Horários idênticos todo dia (Súmula 338 do TST)"),
}


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


@dataclass
class Finding:
    day: date
    kind: str
    detail: str


def detect(days: list[DayResult], start: date, end: date, today: date) -> list[Finding]:
    """`days`: dias seguidos e em ordem, de preferência começando `LOOKBACK_DAYS` antes de `start`.

    Só aponta dias dentro de [start, end]. Dias ainda em andamento (hoje ou futuros) só entram no teste das 11 h entre
    jornadas e no 7º dia seguido, que já valem assim que a pessoa começa a trabalhar.
    """
    out: list[Finding] = []
    prev_out = None
    streak = 0
    british_sig: tuple[str, ...] | None = None
    british_days: list[date] = []

    def close_british_run() -> None:
        # Um item por sequência, no primeiro dia dela dentro do período: a data fica estável enquanto a sequência
        # cresce (o "resolvido" não reabre a cada dia novo) e o detalhe mostra até onde ela foi.
        shown = [x for x in british_days if start <= x <= end]
        if len(british_days) >= BRITISH_RUN and shown and british_sig:
            out.append(Finding(shown[0], "britanico", f"Mesmos horários ({' · '.join(british_sig)}) em {len(british_days)} dias "
                                                      f"seguidos, de {british_days[0]:%d/%m} a {british_days[-1]:%d/%m}."))

    for d in sorted(days, key=lambda x: x.date):
        inside = start <= d.date <= end
        finished = d.date < today
        worked_day = bool(d.punches)

        def emit(kind: str, detail: str, day: date = d.date, inside: bool = inside) -> None:
            if inside:
                out.append(Finding(day, kind, detail))

        if d.first_in and prev_out:
            rest = int((d.first_in - prev_out).total_seconds() // 60)
            if 0 <= rest < MIN_REST_BETWEEN:
                emit("interjornada", f"Descanso de {hm(rest)} desde a saída de {prev_out:%d/%m} às {prev_out:%H:%M}; o mínimo é 11 h.")
        if d.last_out:
            prev_out = d.last_out

        streak = streak + 1 if worked_day else 0
        if streak > MAX_DAYS_IN_A_ROW:
            emit("dsr", f"{streak}º dia seguido com trabalho, sem folga na semana.")

        if not finished or d.status == "anterior":
            close_british_run()
            british_sig, british_days = None, []
            continue

        if d.status == "falta":
            emit("falta", f"Jornada prevista de {hm(d.expected)} sem marcação.")
        elif d.status == "incompleto":
            emit("saida_ausente", "Há uma entrada sem a saída: complete no tratamento.")
        elif d.worked > 0:
            if d.worked > LONG_DAY and d.break_minutes < LONG_BREAK:
                emit("intervalo", f"Intervalo de {hm(d.break_minutes)} numa jornada de {hm(d.worked)}; o mínimo é 1 h.")
            elif SHORT_DAY < d.worked <= LONG_DAY and d.break_minutes < SHORT_BREAK:
                emit("intervalo", f"Intervalo de {hm(d.break_minutes)} numa jornada de {hm(d.worked)}; o mínimo é 15 min.")
            elif d.longest_stretch > MAX_STRETCH:
                emit("sem_intervalo", f"{hm(d.longest_stretch)} de trabalho seguido; acima de 6 h é preciso intervalo.")
            if d.expected > 0 and d.balance > MAX_EXTRA:  # em folga/feriado não há jornada prevista (o 7º dia vira "dsr")
                emit("horas_extras", f"{hm(d.balance)} além da jornada prevista; o limite é 2 h por dia.")

        # Ponto britânico: dias trabalhados em sequência com exatamente os mesmos horários. Folgas, feriados e
        # ausências sem marcação não interrompem a sequência.
        if not worked_day and d.status in ("folga", "feriado", "justificada"):
            continue
        sig = tuple(p.split(" ")[0] for p in d.punches) if d.status == "ok" and len(d.punches) >= 2 else None
        if sig and sig == british_sig:
            british_days.append(d.date)
        else:
            close_british_run()
            british_sig, british_days = sig, [d.date] if sig else []
    close_british_run()
    return out


def _months(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def user_findings(db: Session, company: Company, user: User, start: date, end: date, today: date) -> list[Finding]:
    from .mirror import month_days

    first = start - timedelta(days=LOOKBACK_DAYS)
    days = [d for y, m in _months(first, end) for d in month_days(db, user, company, y, m) if first <= d.date <= end]
    return detect(days, start, end, today)


def resolutions(db: Session, user_ids: list[int], start: date, end: date) -> dict[tuple[int, date, str], InconsistencyResolution]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(InconsistencyResolution).where(
            InconsistencyResolution.user_id.in_(user_ids), InconsistencyResolution.day >= start, InconsistencyResolution.day <= end,
        )
    ).scalars()
    return {(r.user_id, r.day, r.kind): r for r in rows}
