"""Gerador do AFD (Arquivo Fonte de Dados) para REP-P — Portaria MTP 671/2021, Anexo V, leiaute 003."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ArpEvent, Company, Punch, utcnow
from . import arp
from .arp import digits_only, fmt_dh
from .layout import alpha, crc16, encode, num


class ExportError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@dataclass
class Identity:
    """Identificação do empregador e do desenvolvedor, validada para os cabeçalhos dos arquivos."""
    employer_type: str  # "1" CNPJ | "2" CPF
    employer_id: str
    dev_type: str
    dev_id: str
    inpi: str
    test_mode: bool = False  # sem INPI/desenvolvedor: arquivo apenas para testes


def resolve_identity(company: Company) -> Identity:
    emp = digits_only(company.cnpj)
    if len(emp) not in (11, 14):
        raise ExportError(409, "CNPJ/CPF do empregador inválido (esperado 14 ou 11 dígitos)")
    inpi = digits_only(settings.inpi_number)
    dev = digits_only(settings.dev_id)
    test_mode = False
    if not inpi or len(inpi) > 17 or len(dev) not in (11, 14):
        if not settings.allow_missing_inpi:
            if not inpi or len(inpi) > 17:
                raise ExportError(409, "Número de registro no INPI não configurado (PONTO_INPI_NUMBER, até 17 dígitos)")
            raise ExportError(409, "CNPJ/CPF do desenvolvedor não configurado (PONTO_DEV_ID)")
        test_mode = True  # modo de teste: placeholders zerados, nunca válidos para a fiscalização
        inpi = inpi if inpi and len(inpi) <= 17 else "0"
        dev = dev if len(dev) in (11, 14) else "0" * 14
    return Identity("1" if len(emp) == 14 else "2", emp, "1" if len(dev) == 14 else "2", dev, inpi, test_mode)


def utc_bounds(company: Company, start: date, end: date) -> tuple[datetime, datetime]:
    """[início do dia `start`, fim do dia `end`) no fuso da empresa, convertidos para UTC (naive)."""
    zone = ZoneInfo(company.timezone)

    def to_utc(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=zone).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    return to_utc(start), to_utc(end + timedelta(days=1))


def filename(company: Company, ident: Identity) -> str:
    return f"AFD{num(ident.inpi, 17)}{ident.employer_id}REP_P.txt"


def build_afd(db: Session, company: Company, start: date, end: date, now: datetime | None = None) -> tuple[str, bytes]:
    if end < start:
        raise ExportError(422, "Data final anterior à data inicial")
    ident = resolve_identity(company)
    now = now or utcnow()
    lo, hi = utc_bounds(company, start, end)

    punches = db.execute(
        select(Punch).where(Punch.company_id == company.id, Punch.occurred_at >= lo, Punch.occurred_at < hi)
    ).scalars().all()
    events = db.execute(
        select(ArpEvent).where(ArpEvent.company_id == company.id, ArpEvent.recorded_at >= lo, ArpEvent.recorded_at < hi)
    ).scalars().all()

    off_now = arp.offset_minutes(company.timezone, now)
    cno_or_caepf = digits_only(company.caepf) or digits_only(company.cno)

    # Tipo 1 — cabeçalho (posições 001-302)
    body = (
        "000000000" "1" f"{ident.employer_type}{num(ident.employer_id, 14)}{num(cno_or_caepf or 0, 14)}"
        f"{alpha(company.name, 150)}{num(ident.inpi, 17)}"
        f"{start:%Y-%m-%d}{end:%Y-%m-%d}{fmt_dh(now, off_now)}" "003"
        f"{ident.dev_type}{num(ident.dev_id, 14)}{alpha('', 30)}"
    )
    lines = [body + crc16(body)]

    counts = {"2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0}
    records: list[tuple[int, str]] = []
    for e in events:
        stamp = fmt_dh(e.recorded_at, e.tz_offset_min)
        d = e.data
        if e.record_type == "2":  # 2: inclusão/alteração da identificação da empresa no REP (001-331)
            emp = digits_only(d["id"])
            text = (
                f"{num(e.nsr, 9)}2{stamp}{num(e.actor_cpf or 0, 14)}{'1' if len(emp) == 14 else '2'}{num(emp, 14)}"
                f"{num(digits_only(d.get('caepf')) or digits_only(d.get('cno')) or 0, 14)}"
                f"{alpha(d['name'], 150)}{alpha(d.get('workplace'), 100)}"
            )
            text += crc16(text)
        elif e.record_type == "5":  # 5: inclusão, alteração ou exclusão de empregado (001-118)
            text = (
                f"{num(e.nsr, 9)}5{stamp}{d['op']}{num(d['cpf'], 12)}{alpha(d['name'], 52)}{alpha('', 4)}"
                f"{num(e.actor_cpf or 0, 11)}"
            )
            text += crc16(text)
        else:  # 6: eventos sensíveis do REP (001-036), sem CRC
            text = f"{num(e.nsr, 9)}6{stamp}{num(d['event'], 2)}"
        counts[e.record_type] += 1
        records.append((e.nsr, text))
    for p in punches:  # 7: marcação de ponto para REP-P (001-137), sem CRC
        text = (
            f"{num(p.nsr, 9)}7{fmt_dh(p.occurred_at, p.tz_offset_min)}{num(p.cpf, 12)}"
            f"{fmt_dh(p.recorded_at, p.tz_offset_min)}{p.collector}{1 if p.offline else 0}{p.hash}"
        )
        counts["7"] += 1
        records.append((p.nsr, text))
    lines += [text for _, text in sorted(records)]

    # Trailer (001-064)
    lines.append("999999999" + "".join(num(counts[t], 9) for t in ("2", "3", "4", "5", "6", "7")) + "9")
    return filename(company, ident), encode(lines)
