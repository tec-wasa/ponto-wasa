"""Motor de cálculo do espelho de ponto. Puro: não acessa banco."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .punching import IN_KINDS

INTERVAL_THRESHOLD = 360  # CLT art. 71: jornada > 6 h exige intervalo mínimo de 1 h
MIN_INTERVAL = 60
EXTRA_LIMIT = 120  # CLT art. 59: no máximo 2 h extras por dia
NIGHT_START, NIGHT_END = 22, 5  # CLT art. 73 (trabalho urbano): 22h às 5h
NIGHT_HOUR_MINUTES = 52.5  # a hora noturna tem 52 min 30 s: cada 52,5 min reais contam como 60


def night_overlap_minutes(a: datetime, b: datetime) -> int:
    """Minutos reais do intervalo [a, b) (horário local) que caem entre 22h e 5h."""
    total = 0.0
    for offset in (-1, 0, 1):
        day = a.date() + timedelta(days=offset)
        w_start = datetime(day.year, day.month, day.day, NIGHT_START, tzinfo=a.tzinfo)
        w_end = datetime(day.year, day.month, day.day, tzinfo=a.tzinfo) + timedelta(days=1, hours=NIGHT_END)
        lo, hi = max(a, w_start), min(b, w_end)
        if hi > lo:
            total += (hi - lo).total_seconds() / 60
    return int(total)


def reduced_duration(worked: int, night: int) -> int:
    """Duração da jornada considerando a hora noturna reduzida (Art. 84, VI)."""
    return worked - night + round(night * 60 / NIGHT_HOUR_MINUTES)


@dataclass
class Justification:
    """Ausência justificada aprovada que cobre um dia. `minutes` vazio = dia inteiro."""
    label: str
    minutes: int | None = None


@dataclass
class ScheduleRule:
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    daily_minutes: int = 480
    tolerance_minutes: int = 10
    crosses_midnight: bool = False  # padrão: o turno se encerra à meia-noite


@dataclass
class DayResult:
    date: date
    expected: int = 0
    worked: int = 0
    night_minutes: int = 0  # minutos reais trabalhados entre 22h e 5h
    reduced_minutes: int = 0  # duração considerando a hora noturna reduzida
    balance: int = 0
    status: str = "ok"  # ok|folga|falta|incompleto|hoje|futuro|anterior|justificada
    justification: str | None = None
    punches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compute_month(
    punches: list[tuple[datetime, str]],
    rule: ScheduleRule,
    tz: str,
    year: int,
    month: int,
    today: date,
    start: date | None = None,
    justified: dict[date, Justification] | None = None,
) -> list[DayResult]:
    """`punches`: (occurred_at UTC naive, kind) válidos (sem desconsiderados), qualquer ordem.

    `start`: data de admissão; dias anteriores sem marcações não geram falta nem saldo.
    `justified`: ausências aprovadas por dia. Dia inteiro justificado sem marcações vira "justificada" (sem falta nem
    saldo); com marcações, a jornada esperada é zero (o que foi trabalhado conta como saldo). Justificativa parcial
    (em minutos) reduz a jornada esperada, mas só vale se houve marcações (sem marcações continua sendo falta).
    """
    zone = ZoneInfo(tz)
    local = sorted(
        ((p.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone), k) for p, k in punches),
        key=lambda x: x[0],
    )

    days = {
        date(year, month, d): DayResult(date(year, month, d))
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
    }
    pairs: dict[date, list[tuple[datetime, datetime]]] = {d: [] for d in days}
    open_in: dict[date, bool] = {}

    # Pareia entrada -> saída em sequência; o tempo é atribuído ao dia da entrada
    # (jornadas que viram a meia-noite ficam inteiras no dia em que começaram).
    current_in: datetime | None = None
    for when, kind in local:
        if current_in is not None and not rule.crosses_midnight and when.date() != current_in.date():
            open_in[current_in.date()] = True  # jornada que não vira a noite: a entrada ficou sem saída ("saída ausente")
            current_in = None
        if current_in is None:
            if kind in IN_KINDS:
                current_in = when
        else:
            if kind in IN_KINDS:  # entrada repetida: mantém a primeira
                continue
            pairs.setdefault(current_in.date(), []).append((current_in, when))
            current_in = None
    if current_in is not None:
        open_in[current_in.date()] = True

    for when, kind in local:
        d = when.date()
        if d in days:
            days[d].punches.append(f"{when:%H:%M} {kind}")

    for d, res in days.items():
        working = d.weekday() in rule.weekdays
        res.expected = rule.daily_minutes if working else 0
        day_pairs = pairs.get(d, [])
        just = (justified or {}).get(d)
        if just and working:
            if just.minutes is None:
                res.justification, res.expected = just.label, 0
            elif any(when.date() == d for when, _ in local):  # parcial só vale se houve marcações no dia
                res.justification, res.expected = just.label, max(0, res.expected - just.minutes)
        res.worked = sum(int((b - a).total_seconds() // 60) for a, b in day_pairs)
        res.night_minutes = sum(night_overlap_minutes(a, b) for a, b in day_pairs)
        res.reduced_minutes = reduced_duration(res.worked, res.night_minutes)

        if start and d < start and not res.punches:
            res.status, res.expected = "anterior", 0
            continue

        if open_in.get(d):
            res.status = "hoje" if d >= today else "incompleto"
            if res.status == "incompleto":
                res.warnings.append("marcação de saída ausente")
            continue

        if d > today:
            res.status = "futuro"
        elif d == today:
            res.status = "hoje"
        elif res.justification and not res.punches and just.minutes is None:
            res.status = "justificada"
        elif res.expected == 0 and not res.punches:
            res.status = "folga"
        elif res.expected > 0 and not res.punches:
            res.status = "falta"
            res.balance = -res.expected
        else:
            diff = res.worked - res.expected
            res.balance = 0 if abs(diff) <= rule.tolerance_minutes else diff

        if res.worked > INTERVAL_THRESHOLD:
            gap = sum(
                int((day_pairs[i + 1][0] - day_pairs[i][1]).total_seconds() // 60)
                for i in range(len(day_pairs) - 1)
            )
            if gap < MIN_INTERVAL:
                res.warnings.append("intervalo inferior a 1 h em jornada acima de 6 h")
        if res.balance > EXTRA_LIMIT:
            res.warnings.append("horas extras acima de 2 h no dia")
    return list(days.values())
