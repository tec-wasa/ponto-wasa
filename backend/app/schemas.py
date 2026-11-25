from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .services.cpf import digits, is_valid_cpf

ROLES = ("employee", "manager", "hr", "admin", "auditor")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = None  # código do app autenticador ou de recuperação (quando o 2FA está ativo)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    cpf: str  # obrigatório: identifica o trabalhador nos registros do REP-P
    password: str = Field(min_length=8)
    role: str = "employee"  # legado: um só perfil; prefira `roles`
    roles: list[str] | None = None  # funções de gestão acumuláveis: admin, hr, manager (ou só auditor)
    tracks_time: bool = True  # False: só gere, não bate ponto (sem espelho, banco de horas, ajustes)
    manager_id: int | None = None
    schedule_id: int | None = None
    admitted_at: date | None = None
    job_title: str | None = Field(None, max_length=100)
    must_change_password: bool = True  # a senha inicial é temporária: troca obrigatória no primeiro acesso

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, v: str) -> str:
        if not is_valid_cpf(v):
            raise ValueError("CPF inválido")
        return digits(v)


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    email: EmailStr | None = None
    cpf: str | None = None  # só enquanto a pessoa não tem marcações (correção de cadastro)
    admitted_at: date | None = None
    job_title: str | None = Field(None, max_length=100)
    hour_bank_enabled: bool | None = None
    hour_bank_start: date | None = None
    role: str | None = None
    roles: list[str] | None = None
    tracks_time: bool | None = None
    manager_id: int | None = None
    schedule_id: int | None = None
    active: bool | None = None
    punch_policy: Literal["both", "kiosk"] | None = None

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not is_valid_cpf(v):
            raise ValueError("CPF inválido")
        return digits(v)


class UserOut(ORM):
    id: int
    name: str
    email: str
    cpf: str
    role: str
    roles: list[str] = []
    tracks_time: bool = True
    manager_id: int | None
    schedule_id: int | None
    active: bool
    gps_consent_at: datetime | None
    photo_consent_at: datetime | None = None
    punch_policy: str = "both"
    admitted_at: date | None
    job_title: str | None
    hour_bank_enabled: bool
    hour_bank_start: date | None
    must_change_password: bool
    totp_enabled: bool

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, v):
        return [r for r in v.split(",") if r] if isinstance(v, str) else (v or [])


class MeOut(UserOut):
    permissions: list[str] = []  # ações permitidas (ver app/permissions.py)
    scope: str = "self"  # alcance na gestão: self | team | company


class CompanyOut(ORM):
    id: int
    name: str
    cnpj: str
    caepf: str | None
    cno: str | None
    bank_max_minutes: int | None
    bank_expiry_months: int
    timezone: str
    workplace: str | None
    photo_enabled: bool = False
    kiosk_pin_required: bool = False


class CompanyPatch(BaseModel):
    name: str | None = None
    caepf: str | None = None
    cno: str | None = None
    bank_max_minutes: int | None = Field(None, ge=0, le=100000)
    bank_expiry_months: int | None = Field(None, ge=1, le=12)
    timezone: str | None = None
    workplace: str | None = None
    photo_enabled: bool | None = None
    kiosk_pin_required: bool | None = None


class ScheduleIn(BaseModel):
    name: str
    weekdays: list[int] = [0, 1, 2, 3, 4]
    daily_minutes: int = Field(480, ge=0, le=720)
    break_minutes: int = Field(60, ge=0, le=240)
    tolerance_minutes: int = Field(10, ge=0, le=10)  # limite legal: 10 min/dia
    start_time: str = Field("08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    break_start: str = Field("12:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    crosses_midnight: bool = False  # turno que começa num dia e termina no outro


class SchedulePatch(BaseModel):
    """Qualquer campo pode ser editado; mudar a regra de cálculo (tudo menos o nome) é recusado se um mês fechado tiver
    marcações de pessoas desta jornada, porque o Espelho é calculado da jornada vigente."""
    name: str | None = Field(None, min_length=2, max_length=100)
    weekdays: list[int] | None = None
    daily_minutes: int | None = Field(None, ge=0, le=720)
    break_minutes: int | None = Field(None, ge=0, le=240)
    tolerance_minutes: int | None = Field(None, ge=0, le=10)
    start_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    break_start: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    crosses_midnight: bool | None = None


class ScheduleOut(ORM):
    id: int
    name: str
    weekdays: str
    daily_minutes: int
    break_minutes: int
    tolerance_minutes: int
    start_time: str
    break_start: str
    crosses_midnight: bool = False


class PunchIn(BaseModel):
    kind: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)
    device_id: str | None = None
    client_key: str | None = Field(None, max_length=100)
    collector: str = "02"  # 01 app mobile (PWA instalado), 02 browser
    # Só para marcação off-line (o servidor ignora a hora do aparelho nas online):
    offline: bool = False
    occurred_at: datetime | None = Field(None, description="Instante da marcação (UTC): hora do aparelho corrigida pelo desvio medido")
    device_time: datetime | None = Field(None, description="Hora crua do relógio do aparelho, para a trilha de auditoria")
    skew_ms: int | None = Field(None, description="Desvio (servidor - aparelho) medido na última sincronização")


class PunchOut(ORM):
    id: int
    nsr: int
    kind: str
    occurred_at: datetime
    collector: str
    offline: bool
    latitude: float | None
    longitude: float | None
    accuracy_m: float | None
    device_id: str | None
    hash: str
    origin: str = "Aplicativo"  # "Aplicativo" ou o nome da Central


class ReceiptOut(BaseModel):
    """Comprovante de Registro de Ponto do Trabalhador (Art. 79). O PDF assinado (Art. 80) ainda é pendente."""
    title: str
    employer: str
    cnpj: str
    caepf_cno: str | None
    workplace: str | None
    inpi: str
    employee: str
    cpf: str
    nsr: int
    kind: str
    occurred_at_local: str
    hash: str


class AdjustmentIn(BaseModel):
    kind: str  # incluir|desconsiderar
    requested_at: datetime | None = None  # UTC; obrigatório em 'incluir'
    punch_kind: str | None = None
    target_punch_id: int | None = None
    reason: str = Field(min_length=5)
    attachment_name: str | None = None
    user_id: int | None = None  # RH pode abrir em nome de outro colaborador


class AdjustmentOut(ORM):
    id: int
    user_id: int
    kind: str
    requested_at: datetime | None
    punch_kind: str | None
    target_punch_id: int | None
    reason: str
    status: str
    decided_by: int | None
    decision_note: str | None
    # só na listagem: quem pediu e qual marcação seria desconsiderada (para o aprovador decidir sem abrir outra tela)
    user_name: str | None = None
    target_kind: str | None = None
    target_at: datetime | None = None


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


class HourBankEntryIn(BaseModel):
    user_id: int
    kind: str = Field(pattern="^(credito|compensacao)$")
    minutes: int = Field(gt=0, le=24 * 60)
    entry_date: date
    reason: str = Field(min_length=5, max_length=500)


class HourBankEntryOut(ORM):
    id: int
    user_id: int
    entry_date: date
    kind: str
    minutes: int
    reason: str
    created_by: int
