"""Registro de marcações (tipo 7 do AFD): NSR sequencial, hash SHA-256 encadeado e regras de sequência."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Closing, Company, Punch, Schedule, User, utcnow
from . import arp
from .arp import verify_chain  # noqa: F401  (reexportado: usado pelos roteadores e testes)

IN_KINDS = ("entrada", "fim_intervalo")
OUT_KINDS = ("saida", "inicio_intervalo")
ALL_KINDS = IN_KINDS + OUT_KINDS
COLLECTORS = ("01", "02", "03", "04", "05")  # 01 app mobile, 02 browser, 03 app desktop, 04/05 dispositivo


class PunchError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def month_of(company: Company, when: datetime) -> str:
    local = when.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(company.timezone))
    return local.strftime("%Y-%m")


def month_is_closed(db: Session, company_id: int, month: str) -> bool:
    row = db.execute(
        select(Closing).where(Closing.company_id == company_id, Closing.month == month)
    ).scalar_one_or_none()
    return bool(row and row.status == "closed")


def _crosses(db: Session, user: User) -> bool:
    s = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    return bool(s and s.crosses_midnight)


def _local_day(company: Company, dt: datetime):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(company.timezone)).date()


def _open_shift(db: Session, user: User, company: Company, last: Punch | None, now: datetime) -> bool:
    """Há um turno em aberto? Uma marcação de entrada vale por até 16 h e, salvo jornada que vira a meia-noite, só no
    mesmo dia local: depois da meia-noite a entrada esquecida fica como "saída ausente" e o dia novo recomeça."""
    if last is None or last.kind == "saida" or now - last.occurred_at > timedelta(hours=16):
        return False
    return _crosses(db, user) or _local_day(company, last.occurred_at) == _local_day(company, now)


def expected_next_class(db: Session, user: User, now: datetime) -> str:
    """'in' se a próxima marcação deve ser entrada; 'out' se deve ser saída."""
    last = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at <= now).order_by(Punch.occurred_at.desc(), Punch.nsr.desc()).limit(1)
    ).scalar_one_or_none()
    if last and last.kind in IN_KINDS and _open_shift(db, user, db.get(Company, user.company_id), last, now):
        return "out"
    return "in"


KIND_LABEL = {"entrada": "Entrada", "inicio_intervalo": "Intervalo", "fim_intervalo": "Retorno do intervalo", "saida": "Saída"}


def has_break(db: Session, user: User) -> bool:
    """A jornada do colaborador tem intervalo? Sem jornada cadastrada, trata como sem intervalo (entrada e saída)."""
    s = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    return bool(s and s.break_minutes > 0)


def next_kind(db: Session, user: User, now: datetime) -> str:
    """Tipo da próxima marcação pela ORDEM: entrada -> início do intervalo -> fim do intervalo -> saída.

    Sem intervalo na jornada: entrada -> saída. Uma marcação aberta há mais de 16 h é tratada como esquecida e
    recomeça em entrada. Quem sai sem ter feito o intervalo marca a saída explicitamente (kind="saida").
    """
    last = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at <= now)
        .order_by(Punch.occurred_at.desc(), Punch.nsr.desc()).limit(1)
    ).scalar_one_or_none()
    if not _open_shift(db, user, db.get(Company, user.company_id), last, now):
        return "entrada"
    if last.kind == "inicio_intervalo":
        return "fim_intervalo"
    if last.kind == "fim_intervalo":
        return "saida"
    return "inicio_intervalo" if has_break(db, user) else "saida"  # última = entrada


def day_closed(db: Session, user: User, company: Company, at: datetime) -> bool:
    """A jornada do dia já terminou? Sim quando a última marcação é uma saída. A saída é definitiva: não há quinta batida.
    Padrão (encerra à meia-noite): vale se a saída é do mesmo dia local. Jornada que vira a meia-noite: vale se o turno
    (a entrada que o abriu) começou no mesmo dia local, então quem saiu às 07h pode abrir outro turno à noite."""
    recent = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at <= at)
        .order_by(Punch.occurred_at.desc(), Punch.nsr.desc()).limit(6)
    ).scalars().all()
    if not recent or recent[0].kind != "saida":
        return False
    if not _crosses(db, user):
        return _local_day(company, recent[0].occurred_at) == _local_day(company, at)
    start = next((p for p in recent[1:] if p.kind == "entrada"), None)
    return _local_day(company, (start or recent[0]).occurred_at) == _local_day(company, at)


def register_punch(
    db: Session,
    user: User,
    *,
    kind: str | None,
    occurred_at: datetime,
    collector: str = "02",
    offline: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    accuracy_m: float | None = None,
    device_id: str | None = None,
    client_key: str | None = None,
    enforce_sequence: bool = True,
    kiosk_id: int | None = None,
    distance_m: int | None = None,
    keep_location: bool = False,
) -> Punch:
    company = db.get(Company, user.company_id)
    if not user.cpf:
        raise PunchError(422, "CPF do trabalhador não cadastrado")
    if collector not in COLLECTORS:
        raise PunchError(422, "Coletor inválido")

    if month_is_closed(db, company.id, month_of(company, occurred_at)):
        raise PunchError(409, "O mês desta marcação está fechado")

    if client_key:
        existing = db.execute(
            select(Punch).where(Punch.user_id == user.id, Punch.client_key == client_key)
        ).scalar_one_or_none()
        if existing:
            return existing  # idempotência: repetição do mesmo toque

    if enforce_sequence:
        if day_closed(db, user, company, occurred_at):
            raise PunchError(409, "Jornada encerrada: a saída de hoje já foi registrada. Se precisar corrigir, peça um ajuste")
        expected = expected_next_class(db, user, occurred_at)
        if kind is None:
            kind = next_kind(db, user, occurred_at)
        elif (kind in IN_KINDS) != (expected == "in"):
            raise PunchError(409, f"Sequência inválida: a próxima marcação deve ser {'entrada' if expected == 'in' else 'saída'}")
    if kind not in ALL_KINDS:
        raise PunchError(422, "Tipo de marcação inválido")

    # Sem consentimento LGPD não se grava localização.
    if user.gps_consent_at is None and not keep_location:  # Central: a posição é a do APARELHO, não a da pessoa
        latitude = longitude = accuracy_m = None

    counter = arp.lock_counter(db, company.id)
    recorded_at = utcnow()
    offset = arp.offset_minutes(company.timezone, occurred_at)
    nsr = counter.last_nsr + 1
    digest = arp.punch_hash(nsr, user.cpf, occurred_at, recorded_at, offset, collector, offline, counter.last_hash)
    punch = Punch(
        company_id=company.id, user_id=user.id, cpf=user.cpf, nsr=nsr, kind=kind, occurred_at=occurred_at,
        recorded_at=recorded_at, tz_offset_min=offset, collector=collector, offline=offline,
        latitude=latitude, longitude=longitude, accuracy_m=accuracy_m, device_id=device_id,
        client_key=client_key, prev_hash=counter.last_hash, hash=digest, kiosk_id=kiosk_id, distance_m=distance_m,
    )
    counter.last_nsr = nsr
    counter.last_hash = digest
    db.add(punch)
    db.flush()
    return punch
