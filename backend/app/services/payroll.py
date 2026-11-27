"""Exportação para a folha de pagamento: os eventos do mês de cada pessoa, com o código da verba no sistema de folha.

Eventos (calculados do espelho, os mesmos números das telas e dos relatórios):
- horas extras por percentual (regra da empresa, services/overtime.py), só de quem NÃO usa banco de horas;
- adicional noturno: horas noturnas já com a hora noturna reduzida (52min30s = 1 h, CLT art. 73 §1º);
- faltas (dias inteiros sem marcação nem justificativa) e o DSR perdido na semana da falta (Lei 605/49, art. 6º):
  o domingo de descanso daquela semana, quando cai no mês;
- atrasos e saídas antecipadas (horas a menos nos dias trabalhados), só de quem NÃO usa banco de horas
  (para quem usa, o saldo do dia vai para o banco).

Formatos:
- Domínio Sistemas, "Importação Arquivo Texto | De Lançamentos" (Folha, solução 8813): registro 10 de 48 posições
  e registro 11 com as datas da falta (tipo 1) e do DSR perdido (tipo 2), logo abaixo da verba de faltas;
- Alterdata (WDP), arquivo de movimento de "Lançamento por Funcionário": 90 posições por linha;
- CSV para conferência ou para qualquer outro sistema.
Horas vão em horas centesimais (10h30 = 10,50) e dias em quantidade, com 2 casas decimais implícitas nos arquivos texto.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..models import Closing, Company, Punch, User
from . import mirror, overtime
from .timecalc import DayResult

SYSTEMS = {"dominio": "Domínio Sistemas (TXT)", "alterdata": "Alterdata (TXT)", "csv": "Planilha (CSV)"}
# Tamanho máximo, em dígitos, de cada código no leiaute de cada sistema
LIMITS = {
    "dominio": {"company": 10, "employee": 10, "event": 9},
    "alterdata": {"company": 5, "employee": 6, "event": 3},
    "csv": {"company": 10, "employee": 10, "event": 10},
}
PROCESSES = {
    "dominio": {"11": "11 - Folha mensal", "41": "41 - Adiantamento", "42": "42 - Complementar"},
    "alterdata": {"M": "M - Folha mensal", "S": "S - Folha semanal", "Q": "Q - Folha quinzenal", "A": "A - Adiantamento"},
    "csv": {},
}
DEFAULT_PROCESS = {"dominio": "11", "alterdata": "M", "csv": ""}
FIXED_EVENTS = [
    ("noturno", "Adicional noturno (com hora reduzida)", "horas"),
    ("faltas", "Faltas", "dias"),
    ("dsr", "DSR perdido por falta", "dias"),
    ("atrasos", "Atrasos e saídas antecipadas", "horas"),
]
DEFAULT_CONFIG = {"system": "csv", "company_code": "", "process": "", "codes": {}}


class PayrollError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def config(company: Company) -> dict:
    saved = company.payroll_export or {}
    out = {**DEFAULT_CONFIG, **saved, "codes": dict(saved.get("codes") or {})}
    if out["system"] not in SYSTEMS:
        out["system"] = "csv"
    if not out["process"]:
        out["process"] = DEFAULT_PROCESS[out["system"]]
    return out


def events(company: Company) -> list[dict]:
    """As verbas que este ponto calcula: uma de hora extra para cada percentual da regra da empresa, mais as fixas."""
    rule = overtime.company_rule(company)
    pcts = sorted({b[k] for b in rule.values() for k in ("first", "excess")})
    return ([{"key": f"he_{p}", "label": f"Horas extras {p}%", "unit": "horas"} for p in pcts]
            + [{"key": k, "label": label, "unit": unit} for k, label, unit in FIXED_EVENTS])


def validate_config(data: dict) -> dict:
    system = data.get("system") or "csv"
    if system not in SYSTEMS:
        raise PayrollError("Sistema de folha inválido")
    lim = LIMITS[system]
    company_code = (data.get("company_code") or "").strip()
    if company_code and not re.fullmatch(rf"\d{{1,{lim['company']}}}", company_code):
        raise PayrollError(f"O código da empresa no {SYSTEMS[system]} tem só números, até {lim['company']} dígitos")
    process = (data.get("process") or DEFAULT_PROCESS[system]).strip()
    if PROCESSES[system] and process not in PROCESSES[system]:
        raise PayrollError("Tipo de processo inválido para este sistema")
    codes = {}
    for key, code in (data.get("codes") or {}).items():
        code = (code or "").strip()
        if not re.fullmatch(r"he_\d{2,3}|noturno|faltas|dsr|atrasos", key):
            raise PayrollError(f"Verba desconhecida: {key}")
        if code and not re.fullmatch(rf"\d{{1,{lim['event']}}}", code):
            raise PayrollError(f"O código de cada verba no {SYSTEMS[system]} tem só números, até {lim['event']} dígitos")
        if code:
            codes[key] = code
    return {"system": system, "company_code": company_code, "process": process, "codes": codes}


# --- Cálculo ------------------------------------------------------------------------------------------------------------
def night_reduced(minutes: int) -> int:
    """Minutos noturnos reais -> minutos de hora noturna reduzida (7 h reais das 22h às 5h valem 8 h)."""
    return round(minutes * 60 / 52.5)


def lost_dsr(days: list[DayResult]) -> list[date]:
    """O domingo de descanso das semanas (segunda a domingo) com falta sem justificativa, dentro do mês."""
    by_date = {d.date: d for d in days}
    out = []
    for d in days:
        if d.status != "falta":
            continue
        sunday = d.date + timedelta(days=6 - d.date.weekday())
        rest = by_date.get(sunday)
        if rest and rest.expected == 0 and not rest.worked and sunday not in out:
            out.append(sunday)
    return sorted(out)


@dataclass
class PersonEvents:
    user: User
    minutes: dict[str, int] = field(default_factory=dict)  # verbas em horas, em minutos
    days: dict[str, int] = field(default_factory=dict)  # verbas em dias
    falta_dates: list[date] = field(default_factory=list)
    dsr_dates: list[date] = field(default_factory=list)
    incomplete: int = 0  # dias com marcação ímpar: corrigir no Tratamento antes de exportar

    def amount(self, key: str) -> float:
        """Quantidade da verba: horas centesimais ou dias."""
        if key in self.days:
            return float(self.days[key])
        return round(self.minutes.get(key, 0) / 60, 2)

    def keys(self) -> list[str]:
        return [k for k, v in {**self.minutes, **self.days}.items() if v]


def person_events(user: User, company: Company, days: list[DayResult]) -> PersonEvents:
    pe = PersonEvents(user)
    if not user.hour_bank_enabled:
        ot = overtime.compute(days, overtime.company_rule(company))
        for pct, m in ot.by_percent.items():
            pe.minutes[f"he_{pct}"] = m
        pe.minutes["atrasos"] = sum(-d.balance for d in days if d.balance < 0 and d.status == "ok")
    pe.minutes["noturno"] = night_reduced(sum(d.night_minutes for d in days))
    pe.falta_dates = [d.date for d in days if d.status == "falta"]
    pe.dsr_dates = lost_dsr(days)
    pe.incomplete = sum(1 for d in days if d.status == "incompleto")
    pe.days["faltas"] = len(pe.falta_dates)
    pe.days["dsr"] = len(pe.dsr_dates)
    return pe


def people(db: Session, company: Company, year: int, month: int) -> list[User]:
    """Quem registra ponto na empresa: os ativos e quem saiu mas tem marcação no mês (rescisão)."""
    lo = datetime(year, month, 1) - timedelta(days=1)
    hi = datetime(year + (month == 12), month % 12 + 1, 1) + timedelta(days=1)
    worked = exists().where(Punch.user_id == User.id, Punch.occurred_at >= lo, Punch.occurred_at < hi)
    q = select(User).where(User.company_id == company.id, User.tracks_time.is_(True), User.role != "auditor",
                           or_(User.active.is_(True), worked))
    return list(db.execute(q.order_by(User.name)).scalars())


def month_events(db: Session, company: Company, year: int, month: int) -> list[PersonEvents]:
    return [person_events(u, company, mirror.month_days(db, u, company, year, month)) for u in people(db, company, year, month)]


def preview(db: Session, company: Company, year: int, month: int) -> dict:
    cfg = config(company)
    evs = events(company)
    labels = {e["key"]: e["label"] for e in evs}
    rows, totals = [], {e["key"]: 0.0 for e in evs}
    no_code, unmapped, incomplete = [], set(), []
    for pe in month_events(db, company, year, month):
        keys = pe.keys()
        for k in keys:
            totals[k] = round(totals.get(k, 0) + pe.amount(k), 2)
            if k not in cfg["codes"]:
                unmapped.add(k)
        if keys and not pe.user.payroll_code:
            no_code.append(pe.user.name)
        if pe.incomplete:
            incomplete.append(pe.user.name)
        rows.append({
            "user_id": pe.user.id, "name": pe.user.name, "job_title": pe.user.job_title or "", "payroll_code": pe.user.payroll_code,
            "hour_bank": pe.user.hour_bank_enabled, "active": pe.user.active,
            "values": {k: pe.amount(k) for k in keys},
        })
    closed = db.execute(select(Closing.id).where(Closing.company_id == company.id, Closing.month == f"{year:04d}-{month:02d}",
                                                 Closing.status == "closed")).first() is not None
    needs_company = cfg["system"] != "csv" and not cfg["company_code"]
    return {
        "month": f"{year:04d}-{month:02d}", "closed": closed, "config": cfg, "events": evs, "rows": rows, "totals": totals,
        "pending": {
            "company_code": needs_company,
            "people_without_code": no_code,
            "events_without_code": [labels.get(k, k) for k in [e["key"] for e in evs] if k in unmapped],
            "incomplete_days": incomplete,
        },
    }


# --- Arquivos -----------------------------------------------------------------------------------------------------------
def _zeros(value, size: int) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) > size:
        raise PayrollError(f"Valor {value} não cabe em {size} posições")
    return digits.rjust(size, "0")


def _cents(amount: float) -> int:
    return round(amount * 100)


def _items(pe: PersonEvents, cfg: dict, evs: list[dict]) -> list[tuple[str, str, float]]:
    """(chave, código da verba, quantidade) do que tem valor e código configurado, na ordem do catálogo."""
    keys = pe.keys()
    return [(e["key"], cfg["codes"][e["key"]], pe.amount(e["key"])) for e in evs
            if e["key"] in keys and e["key"] in cfg["codes"] and _cents(pe.amount(e["key"])) > 0]


def _require_ready(cfg: dict) -> None:
    if not cfg["company_code"]:
        raise PayrollError(f"Informe o código da empresa no {SYSTEMS[cfg['system']]} antes de exportar")
    if not cfg["codes"]:
        raise PayrollError("Cadastre o código de pelo menos uma verba antes de exportar")


def dominio_txt(data: list[PersonEvents], cfg: dict, evs: list[dict], year: int, month: int) -> bytes:
    _require_ready(cfg)
    comp, lines = f"{year:04d}{month:02d}", []
    for pe in data:
        if not pe.user.payroll_code:
            continue
        for key, code, qty in _items(pe, cfg, evs):
            lines.append("10" + _zeros(pe.user.payroll_code, 10) + comp + _zeros(code, 9) + _zeros(cfg["process"], 2)
                         + _zeros(_cents(qty), 9) + _zeros(cfg["company_code"], 10))
            if key == "faltas":
                lines += [f"11{d:%Y%m%d}1" for d in pe.falta_dates] + [f"11{d:%Y%m%d}2" for d in pe.dsr_dates]
    return "".join(line + "\r\n" for line in lines).encode("ascii")


def alterdata_txt(data: list[PersonEvents], cfg: dict, evs: list[dict], company: Company, year: int, month: int) -> bytes:
    _require_ready(cfg)
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    cnpj = _zeros(company.cnpj, 14)
    lines = []
    for pe in data:
        if not pe.user.payroll_code:
            continue
        for _key, code, qty in _items(pe, cfg, evs):
            lines.append(_zeros(len(lines) + 1, 6) + _zeros(cfg["company_code"], 5) + f"{first:%d%m%y}{last:%d%m%y}"
                         + "0" * 6 + "0" * 6 + "00" + _zeros(code, 3) + _zeros(_cents(qty), 14)
                         + _zeros(pe.user.payroll_code, 6) + cfg["process"][:1] + cnpj + "0" * 11 + "0" * 4)
    return "".join(line + "\r\n" for line in lines).encode("ascii")


def payroll_csv(data: list[PersonEvents], cfg: dict, evs: list[dict], year: int, month: int) -> bytes:
    from .reports import _fmt_cpf, to_csv
    head = ["Competência", "Matrícula", "Nome", "CPF", "Código da verba", "Verba", "Quantidade", "Unidade", "Datas"]
    rows = []
    for pe in data:
        keys = pe.keys()
        for e in evs:
            if e["key"] not in keys:
                continue
            dates = pe.falta_dates if e["key"] == "faltas" else pe.dsr_dates if e["key"] == "dsr" else []
            rows.append([f"{month:02d}/{year:04d}", pe.user.payroll_code or "", pe.user.name, _fmt_cpf(pe.user.cpf),
                         cfg["codes"].get(e["key"], ""), e["label"], f"{pe.amount(e['key']):.2f}".replace(".", ","), e["unit"],
                         " ".join(f"{d:%d/%m}" for d in dates)])
    return to_csv(head, rows)


def export(db: Session, company: Company, year: int, month: int, fmt: str) -> tuple[bytes, str, int]:
    """(conteúdo, extensão, número de lançamentos)."""
    cfg, evs = config(company), events(company)
    if fmt in ("dominio", "alterdata") and fmt != cfg["system"]:
        raise PayrollError(f"A empresa está configurada para {SYSTEMS[cfg['system']]}: mude o sistema nas verbas antes de exportar")
    data = month_events(db, company, year, month)
    if fmt == "dominio":
        content, ext = dominio_txt(data, cfg, evs, year, month), "txt"
    elif fmt == "alterdata":
        content, ext = alterdata_txt(data, cfg, evs, company, year, month), "txt"
    elif fmt == "csv":
        content, ext = payroll_csv(data, cfg, evs, year, month), "csv"
    else:
        raise PayrollError("Formato deve ser dominio, alterdata ou csv")
    if fmt != "csv" and not content:
        raise PayrollError("Nada para exportar: confira as matrículas e os códigos das verbas")
    count = sum(1 for line in content.decode("utf-8-sig").splitlines()[1 if fmt == "csv" else 0:] if not line.startswith("11"))
    return content, ext, count
