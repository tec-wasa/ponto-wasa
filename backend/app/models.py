"""Modelo de dados. Todos os datetimes são armazenados em UTC, sem tzinfo.

`punches` (marcações, registro tipo 7 do AFD) e `arp_events` (tipos 2, 5 e 6) formam o ARP
(Armazenamento de Registro de Ponto, Anexo IX da Portaria MTP 671/2021): append-only e com
uma única sequência de NSR por empresa (estabelecimento).
"""
from datetime import UTC, date, datetime

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from . import immutability
from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Company(Base):
    """Empresa = estabelecimento (cada um tem a sua sequência de NSR)."""
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    cnpj: Mapped[str] = mapped_column(String(20), unique=True)  # CNPJ (14 dígitos) ou CPF (11), com ou sem máscara
    caepf: Mapped[str | None] = mapped_column(String(14), default=None)
    cno: Mapped[str | None] = mapped_column(String(14), default=None)
    bank_max_minutes: Mapped[int | None] = mapped_column(Integer, default=None)  # teto do saldo positivo do banco de horas
    bank_expiry_months: Mapped[int] = mapped_column(Integer, default=6, server_default="6")  # prazo de compensação
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    workplace: Mapped[str | None] = mapped_column(String(300), default=None)  # local de prestação do serviço
    photo_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # foto opcional na batida (consentimento por pessoa)
    kiosk_pin_required: Mapped[bool] = mapped_column(Boolean, default=False)
    password_login: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # False = só "Entrar com Google"
    holiday_carnaval: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # segunda e terça de Carnaval
    holiday_corpus_christi: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # a Central pede o PIN (configurável; padrão: não)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Holiday(Base):
    """Feriado estadual, municipal ou da própria empresa (os nacionais são calculados em services/holidays.py)."""
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    day: Mapped[date] = mapped_column("date", Date)
    name: Mapped[str] = mapped_column(String(100))
    recurring: Mapped[bool] = mapped_column(Boolean, default=True)  # repete todo ano no mesmo dia e mês
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NsrCounter(Base):
    """Uma linha por empresa. Travada com FOR UPDATE ao gerar o NSR (todos os tipos de registro)."""
    __tablename__ = "nsr_counters"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    last_nsr: Mapped[int] = mapped_column(Integer, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), default="")  # hash da última marcação (tipo 7)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4")  # 0 = segunda
    daily_minutes: Mapped[int] = mapped_column(Integer, default=480)
    break_minutes: Mapped[int] = mapped_column(Integer, default=60)
    tolerance_minutes: Mapped[int] = mapped_column(Integer, default=10)
    start_time: Mapped[str] = mapped_column(String(5), default="08:00")  # primeira entrada (HH:MM)
    break_start: Mapped[str] = mapped_column(String(5), default="12:00")  # início do intervalo (HH:MM)
    # Padrão: a jornada se encerra à meia-noite (uma entrada em aberto vira "saída ausente" e o dia seguinte recomeça).
    # Ligado, o turno pode começar num dia e terminar no outro (turno da noite).
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_company_code", "company_id", "employee_code", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), unique=True, default=None)  # login; vazio = só usa a Central
    cpf: Mapped[str] = mapped_column(String(11))  # só dígitos, validado; obrigatório (identifica o trabalhador no REP-P)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="employee")  # perfil mais alto de `roles` (compatibilidade): employee|manager|hr|admin|auditor
    roles: Mapped[str] = mapped_column(String(60), default="", server_default="")  # funções de gestão acumuláveis, ex.: "admin,hr,manager"
    tracks_time: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # False = só gere, não bate ponto
    app_access: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # False = só bate ponto na Central, sem login
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, default=None)  # conta Google vinculada
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id"), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    gps_consent_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    photo_consent_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)  # LGPD: foto na batida (opcional)
    punch_policy: Mapped[str] = mapped_column(String(8), default="both")  # both = aplicativo e Central; kiosk = só a Central
    # Central do Ponto: código interno (identifica), PIN opcional (confirma) e crachá QR
    employee_code: Mapped[str | None] = mapped_column(String(8), default=None)
    pin_hash: Mapped[str | None] = mapped_column(Text, default=None)
    pin_fails: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    pin_set_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    badge_version: Mapped[int] = mapped_column(Integer, default=1)  # regenerar invalida os crachás impressos
    badge_secret: Mapped[str | None] = mapped_column(Text, default=None)  # segredo do QR rotativo (cifrado)
    badge_last_step: Mapped[int | None] = mapped_column(Integer, default=None)  # anti-repetição do QR rotativo

    @property
    def role_list(self) -> list[str]:
        return [r for r in (self.roles or "").split(",") if r]

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash)

    admitted_at: Mapped[date | None] = mapped_column(Date, default=None)  # sem faltas antes desta data
    job_title: Mapped[str | None] = mapped_column(String(100), default=None)  # cargo/função (Art. 84, II)
    hour_bank_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # sobe ao trocar senha/2FA: derruba sessões
    totp_secret: Mapped[str | None] = mapped_column(Text, default=None)  # cifrado (Fernet)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    totp_last_step: Mapped[int | None] = mapped_column(Integer, default=None)  # anti-repetição de código
    totp_recovery: Mapped[list | None] = mapped_column(JSON, default=None)  # hashes dos códigos de recuperação
    hour_bank_start: Mapped[date | None] = mapped_column(Date, default=None)  # o saldo automático conta a partir daqui
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Punch(Base):
    """Marcação de ponto (registro tipo 7 do AFD). Imutável: nunca sofre UPDATE ou DELETE."""
    __tablename__ = "punches"
    __table_args__ = (
        UniqueConstraint("company_id", "nsr"),
        UniqueConstraint("user_id", "client_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cpf: Mapped[str] = mapped_column(String(11))  # CPF do trabalhador no momento da marcação
    nsr: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # entrada|saida|inicio_intervalo|fim_intervalo (uso interno)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # data/hora da marcação (UTC)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)  # data/hora da gravação (UTC)
    tz_offset_min: Mapped[int] = mapped_column(Integer)  # fuso da marcação e da gravação, em minutos (ex.: -180)
    collector: Mapped[str] = mapped_column(String(2), default="02")  # 01 app mobile, 02 browser, 03 desktop, 04/05 dispositivo
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    latitude: Mapped[float | None] = mapped_column(Float, default=None)
    longitude: Mapped[float | None] = mapped_column(Float, default=None)
    accuracy_m: Mapped[float | None] = mapped_column(Float, default=None)
    device_id: Mapped[str | None] = mapped_column(String(100), default=None)
    kiosk_id: Mapped[int | None] = mapped_column(Integer, default=None)  # Central que coletou a marcação (sem FK: `punches` é append-only e o SQLite não a adiciona por ALTER)
    distance_m: Mapped[int | None] = mapped_column(Integer, default=None)  # distância do aparelho ao posto no momento da batida
    client_key: Mapped[str | None] = mapped_column(String(100), default=None)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ArpEvent(Base):
    """Registros do ARP que não são marcações: tipo 2 (empregador), 5 (empregado) e 6 (eventos do REP-P).

    O tipo 4 (ajuste do relógio) não se aplica: a hora vem do servidor sincronizado, sem ajuste manual.
    """
    __tablename__ = "arp_events"
    __table_args__ = (UniqueConstraint("company_id", "nsr"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    nsr: Mapped[int] = mapped_column(Integer)
    record_type: Mapped[str] = mapped_column(String(1))  # "2" | "5" | "6"
    recorded_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    tz_offset_min: Mapped[int] = mapped_column(Integer)
    actor_cpf: Mapped[str | None] = mapped_column(String(11), default=None)  # responsável pela operação
    data: Mapped[dict] = mapped_column(JSON)


class Adjustment(Base):
    """Tratamento de marcações (AEJ): inclusão manual ou desconsideração. Nunca altera o ARP."""
    __tablename__ = "adjustments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # incluir|desconsiderar
    requested_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    punch_kind: Mapped[str | None] = mapped_column(String(20), default=None)
    target_punch_id: Mapped[int | None] = mapped_column(ForeignKey("punches.id"), default=None)
    reason: Mapped[str] = mapped_column(Text)
    attachment_name: Mapped[str | None] = mapped_column(String(300), default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HourBankEntry(Base):
    """Lançamento manual no banco de horas (RH). Append-only: correção = lançamento contrário."""
    __tablename__ = "hour_bank_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(12))  # credito (soma) | compensacao (subtrai)
    minutes: Mapped[int] = mapped_column(Integer)  # sempre positivo
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Absence(Base):
    """Ausência justificada: atestado, abono, férias, licença ou afastamento. Pode ser cancelada (a trilha fica na auditoria)."""
    __tablename__ = "absences"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # atestado_medico|abono|ferias|licenca|afastamento_inss
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int | None] = mapped_column(Integer, default=None)  # justificativa parcial (um dia); vazio = dia inteiro
    reason: Mapped[str] = mapped_column(Text)  # sem diagnóstico/CID (dado de saúde): só o necessário
    attachment_name: Mapped[str | None] = mapped_column(String(300), default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected|cancelled
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PunchPhoto(Base):
    """Foto opcional da batida, para conferência humana (RH/admin). Não entra no hash nem no AFD.
    Apagada no fechamento do mês (retenção): por isso esta tabela permite DELETE, ao contrário do ARP."""
    __tablename__ = "punch_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    punch_id: Mapped[int] = mapped_column(ForeignKey("punches.id"), unique=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM local da batida: o fechamento desse mês apaga a foto
    storage_key: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Kiosk(Base):
    """Central do Ponto: aparelho compartilhado, pareado com um código de uso único e vinculado a um posto (local fixo)."""
    __tablename__ = "kiosks"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str | None] = mapped_column(String(64), default=None, index=True)  # SHA-256 do token do aparelho
    pairing_hash: Mapped[str | None] = mapped_column(String(64), default=None)  # SHA-256 do código de pareamento (uso único)
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    latitude: Mapped[float | None] = mapped_column(Float, default=None)
    longitude: Mapped[float | None] = mapped_column(Float, default=None)
    radius_m: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KioskTicket(Base):
    """Autorização de 60 s, de uso único, emitida depois que a pessoa se identificou na Central."""
    __tablename__ = "kiosk_tickets"
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kiosk_id: Mapped[int] = mapped_column(ForeignKey("kiosks.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Closing(Base):
    __tablename__ = "closings"
    __table_args__ = (UniqueConstraint("company_id", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    status: Mapped[str] = mapped_column(String(10), default="closed")  # closed|open
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AuditLog(Base):
    """Trilha de auditoria append-only."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    actor_id: Mapped[int | None] = mapped_column(Integer, default=None)
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(50), default=None)
    before: Mapped[dict | None] = mapped_column(JSON, default=None)
    after: Mapped[dict | None] = mapped_column(JSON, default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --- Perfis acumuláveis -----------------------------------------------------
ROLE_ORDER = ("admin", "hr", "manager")  # do mais para o menos poderoso; cada um inclui o poder dos seguintes
MANAGEMENT_FUNCS = ROLE_ORDER + ("auditor",)


def top_role(roles: list[str]) -> str:
    for r in ROLE_ORDER:
        if r in roles:
            return r
    return "auditor" if "auditor" in roles else "employee"


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _sync_roles(mapper, connection, target):
    """`roles` é a fonte; `role` guarda o perfil mais alto (o resto do sistema decide permissões por ele)."""
    listed = target.role_list
    if listed:
        target.role = top_role(listed)
    elif target.role and target.role != "employee":
        target.roles = target.role  # cadastro criado só com `role`


# --- Imutabilidade: guarda no ORM + gatilhos no banco -----------------------
class ImmutableError(RuntimeError):
    pass


def _forbid(mapper, connection, target):
    raise ImmutableError(f"{type(target).__name__} é imutável (append-only)")


for _model in (Punch, ArpEvent, AuditLog, HourBankEntry):
    event.listen(_model, "before_update", _forbid)
    event.listen(_model, "before_delete", _forbid)
    for _dialect in ("sqlite", "postgresql"):
        for _sql in immutability.create_statements(_model.__tablename__, _dialect):
            event.listen(_model.__table__, "after_create", DDL(_sql).execute_if(dialect=_dialect))
