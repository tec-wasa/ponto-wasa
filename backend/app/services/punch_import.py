"""Importação de marcações de outro sistema de ponto (CSV), como INCLUSÕES aprovadas (tratamento).

Pela Portaria 671, uma marcação feita em outro relógio não vira marcação original deste REP-P (não ganha NSR nem
comprovante e não entra no AFD como marcação): entra como inclusão, com o motivo, aparece tratada no Espelho e vai para o
AEJ. Os registros originais continuam sendo os do sistema anterior, que a empresa deve guardar.

Formato (separador ';' ou ','; UTF-8 ou Excel em português): uma linha por pessoa e dia.
  cpf; data (dd/mm/aaaa); batida_1; batida_2; ... (HH:MM)   — ou uma coluna "batidas" com os horários separados por espaço.
Outras colunas (nome, ocorrência, totais) são ignoradas. Linhas sem batidas (folga, feriado, férias) são ignoradas.
"""
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, Company, Punch, User
from .cpf import digits
from .csv_import import _parse_date
from .punching import month_is_closed

MAX_ROWS = 3000
TAG_PREFIX = "Importação "
TIME = re.compile(r"^(?:\(m\))?([01]\d|2[0-3]):([0-5]\d)$")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in text if c.isalnum())


def kinds_for(n: int) -> list[str]:
    """Tipo de cada batida do dia pela ordem: entrada, (início/fim do intervalo)..., saída."""
    out = []
    for i in range(n):
        if i == 0:
            out.append("entrada")
        elif i == n - 1 and n % 2 == 0:
            out.append("saida")
        else:
            out.append("inicio_intervalo" if i % 2 else "fim_intervalo")
    return out


@dataclass
class Issue:
    line: int
    message: str
    person: str = ""


@dataclass
class DayRow:
    line: int
    user: User
    day: date
    times: list[str]


@dataclass
class Result:
    rows: list[DayRow] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    skipped: list[Issue] = field(default_factory=list)  # dia que já tem marcações no app
    total: int = 0
    empty: int = 0


def _days_with_marks(db: Session, user: User, zone: ZoneInfo, first: date, last: date) -> set[date]:
    lo = datetime(first.year, first.month, first.day, tzinfo=zone).astimezone(UTC).replace(tzinfo=None) - timedelta(hours=1)
    hi = datetime(last.year, last.month, last.day, tzinfo=zone).astimezone(UTC).replace(tzinfo=None) + timedelta(days=1, hours=1)
    local = lambda dt: dt.replace(tzinfo=UTC).astimezone(zone).date()  # noqa: E731
    out = {local(p.occurred_at) for p in db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at >= lo, Punch.occurred_at < hi)).scalars()}
    out |= {local(a.requested_at) for a in db.execute(
        select(Adjustment).where(Adjustment.user_id == user.id, Adjustment.kind == "incluir", Adjustment.status == "approved",
                                 Adjustment.requested_at >= lo, Adjustment.requested_at < hi)).scalars()}
    return out


def parse(db: Session, company: Company, text: str, now: datetime) -> Result:
    res = Result()
    zone = ZoneInfo(company.timezone)
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip()), None)
    if first is None:
        res.errors.append(Issue(1, "O arquivo está vazio"))
        return res
    delim = ";" if first.count(";") >= first.count(",") else ","
    numbered = [(n, c) for n, c in enumerate(csv.reader(lines, delimiter=delim), start=1) if any(x.strip() for x in c)]
    header = [_norm(h) for h in numbered[0][1]]
    col = lambda *names: next((i for i, h in enumerate(header) if h in names), None)  # noqa: E731
    i_cpf, i_date, i_name = col("cpf"), col("data", "dia", "date"), col("nome", "colaborador", "name")
    i_marks = [i for i, h in enumerate(header) if re.fullmatch(r"(batida|marcacao|ponto)\d+", h)]
    i_multi = col("batidas", "marcacoes", "pontos")
    if i_cpf is None or i_date is None or (not i_marks and i_multi is None):
        res.errors.append(Issue(1, "Cabeçalho: são obrigatórias as colunas cpf, data e batida_1, batida_2… (ou uma coluna batidas)"))
        return res
    data = numbered[1:]
    res.total = len(data)
    if not data:
        res.errors.append(Issue(1, "Não há linhas de dados"))
        return res
    if len(data) > MAX_ROWS:
        res.errors.append(Issue(1, f"O arquivo tem {len(data)} linhas; o máximo por importação é {MAX_ROWS}"))
        return res

    users = {u.cpf: u for u in db.execute(select(User).where(User.company_id == company.id)).scalars() if u.cpf}
    today = now.replace(tzinfo=UTC).astimezone(zone)
    seen: dict[tuple[int, date], int] = {}
    closed: dict[str, bool] = {}
    cell = lambda cells, i: cells[i].strip() if i is not None and i < len(cells) else ""  # noqa: E731
    for line, cells in data:
        name = cell(cells, i_name)
        raw = [cell(cells, i) for i in i_marks] if i_marks else cell(cells, i_multi).replace("|", " ").split()
        raw = [r for r in raw if r and r != "-"]
        if not raw:
            res.empty += 1
            continue
        user = users.get(digits(cell(cells, i_cpf)))
        who = user.name if user else name
        if not user:
            res.errors.append(Issue(line, "CPF não encontrado entre as pessoas da empresa", name))
            continue
        if not user.tracks_time:
            res.errors.append(Issue(line, "Esta pessoa não registra ponto (veja o cadastro)", who))
            continue
        day = _parse_date(cell(cells, i_date))
        if not day:
            res.errors.append(Issue(line, f"Data inválida: “{cell(cells, i_date)}” (use dd/mm/aaaa)", who))
            continue
        bad = [r for r in raw if not TIME.match(r)]
        if bad:
            res.errors.append(Issue(line, f"Horário inválido: {', '.join(bad)} (use HH:MM)", who))
            continue
        times = ["{}:{}".format(*TIME.match(r).groups()) for r in raw]
        if times != sorted(times) or len(set(times)) != len(times):
            res.errors.append(Issue(line, "Os horários do dia precisam estar em ordem crescente e sem repetição", who))
            continue
        last = datetime.combine(day, datetime.strptime(times[-1], "%H:%M").time(), tzinfo=zone)
        if last > today:
            res.errors.append(Issue(line, "Não é possível incluir marcação no futuro", who))
            continue
        month = day.strftime("%Y-%m")
        if month not in closed:
            closed[month] = month_is_closed(db, company.id, month)
        if closed[month]:
            res.errors.append(Issue(line, f"O mês {month} está fechado: reabra antes de importar", who))
            continue
        key = (user.id, day)
        if key in seen:
            res.errors.append(Issue(line, f"Dia repetido no arquivo (já está na linha {seen[key]})", who))
            continue
        seen[key] = line
        if len(times) % 2:
            res.warnings.append(Issue(line, f"{day:%d/%m}: número ímpar de batidas ({len(times)}); o dia ficará incompleto", who))
        if user.admitted_at and day < user.admitted_at:
            res.warnings.append(Issue(line, f"{day:%d/%m}: antes da admissão ({user.admitted_at:%d/%m/%Y})", who))
        res.rows.append(DayRow(line, user, day, times))

    # Dias que já têm marcações no app ficam de fora (não duplica).
    by_user: dict[int, list[DayRow]] = {}
    for r in res.rows:
        by_user.setdefault(r.user.id, []).append(r)
    keep = []
    for rows in by_user.values():
        taken = _days_with_marks(db, rows[0].user, zone, min(r.day for r in rows), max(r.day for r in rows))
        for r in rows:
            if r.day in taken:
                res.skipped.append(Issue(r.line, f"{r.day:%d/%m}: já tem marcações no app; o dia não será importado", r.user.name))
            else:
                keep.append(r)
    res.rows = sorted(keep, key=lambda r: r.line)
    return res


def to_adjustments(res: Result, company: Company, actor: User, reason: str, tag: str, now: datetime) -> list[Adjustment]:
    zone = ZoneInfo(company.timezone)
    out = []
    for r in res.rows:
        for hhmm, kind in zip(r.times, kinds_for(len(r.times)), strict=True):
            at = datetime.combine(r.day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
            out.append(Adjustment(
                company_id=company.id, user_id=r.user.id, kind="incluir", requested_at=at, punch_kind=kind, reason=reason,
                status="approved", decided_by=actor.id, decided_at=now, decision_note=tag,
            ))
    return out
