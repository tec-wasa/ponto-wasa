"""Central do Ponto: identificação das pessoas (código, CPF, QR), PIN opcional, tickets e distância ao posto.

Regras que valem para todos os caminhos:
- Falhas de identificação respondem SEMPRE com a mesma mensagem (não revela se o código existe).
- O PIN é guardado com hash (argon2), com bloqueio temporário depois de várias falhas.
- O QR do crachá impresso é assinado (HMAC) e tem versão: regenerar o crachá invalida os impressos.
- O QR do aplicativo é rotativo (TOTP de 30 s, uso único por janela): foto de tela não vale.
"""
import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Company, Kiosk, KioskTicket, User
from ..security import hash_password, verify_password
from . import totp
from .cpf import digits, is_valid_cpf

GENERIC_FAIL = "Código ou PIN incorreto, ou acesso bloqueado por alguns minutos"
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I
CONSENT_TEXT = (
    "Nesta central, a foto é obrigatória em cada batida. Ela serve só para o RH conferir que foi você, fica guardada com "
    "criptografia, só o RH e o administrador a veem e ela é apagada quando o mês é fechado. Você pode recusar: nesse caso, "
    "registre o ponto pelo aplicativo."
)


class KioskError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- código interno --------------------------------------------------------------
def assign_code(db: Session, user: User) -> str:
    """Código de 6 dígitos, único na empresa, sem relação com o CPF. Idempotente."""
    if user.employee_code:
        return user.employee_code
    taken = set(db.execute(select(User.employee_code).where(User.company_id == user.company_id,
                                                            User.employee_code.is_not(None))).scalars())
    while True:
        code = f"{secrets.randbelow(900000) + 100000}"
        if code not in taken:
            break
    user.employee_code = code
    return code


# --- PIN -------------------------------------------------------------------------
def valid_pin_format(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 6


def set_pin(user: User, pin: str, now: datetime) -> None:
    if not valid_pin_format(pin):
        raise KioskError(422, "O PIN deve ter de 4 a 6 números")
    if pin in ("0000", "1234", "1111", "123456", "000000", "111111") or len(set(pin)) == 1:
        raise KioskError(422, "Escolha um PIN menos óbvio")
    user.pin_hash = hash_password(pin)
    user.pin_set_at, user.pin_fails, user.pin_locked_until = now, 0, None


def check_pin(user: User, pin: str | None, now: datetime) -> bool:
    """Confere o PIN e cuida do bloqueio temporário. Bloqueado ou sem PIN = falso (sem dizer o motivo)."""
    if not user.pin_hash or not pin:
        return False
    if user.pin_locked_until and user.pin_locked_until > now:
        return False
    if verify_password(pin, user.pin_hash):
        user.pin_fails, user.pin_locked_until = 0, None
        return True
    user.pin_fails = (user.pin_fails or 0) + 1
    if user.pin_fails >= settings.kiosk_pin_max_fails:
        user.pin_locked_until = now + timedelta(minutes=settings.kiosk_pin_lock_minutes)
        user.pin_fails = 0
    return False


# --- crachá QR -------------------------------------------------------------------
def _badge_sig(company_id: int, user_id: int, version: int) -> str:
    key = (settings.secret_key + "|badge").encode()
    return hmac.new(key, f"{company_id}.{user_id}.{version}".encode(), hashlib.sha256).hexdigest()[:20]


def static_badge(user: User) -> str:
    return f"PB1.{user.company_id}.{user.id}.{user.badge_version}.{_badge_sig(user.company_id, user.id, user.badge_version)}"


def rotating_badge(user: User, now: float | None = None) -> tuple[str, int]:
    """QR do aplicativo: muda a cada 30 s. Devolve (conteúdo, segundos até trocar)."""
    import time as _time

    if not user.badge_secret:
        user.badge_secret = totp.encrypt(totp.new_secret())
    ts = _time.time() if now is None else now
    secret = totp.decrypt(user.badge_secret)
    return f"PR1.{user.id}.{totp.code_at(secret, ts)}", int(totp.STEP_SECONDS - ts % totp.STEP_SECONDS)


def regenerate_badge(user: User) -> None:
    user.badge_version = (user.badge_version or 1) + 1
    user.badge_secret, user.badge_last_step = None, None


# --- identificação -------------------------------------------------------------
def resolve_user(db: Session, kiosk: Kiosk, method: str, value: str, now: datetime) -> tuple[User, bool]:
    """Acha a pessoa. Devolve (usuário, é_qr_rotativo). Qualquer problema vira a mesma falha genérica."""
    fail = KioskError(401, GENERIC_FAIL)
    value = (value or "").strip()
    user: User | None = None
    rotating = False
    if method == "code" and value.isdigit():
        user = db.execute(select(User).where(User.company_id == kiosk.company_id, User.employee_code == value)).scalar_one_or_none()
    elif method == "cpf":
        d = digits(value)
        if is_valid_cpf(d):
            user = db.execute(select(User).where(User.company_id == kiosk.company_id, User.cpf == d)).scalar_one_or_none()
    elif method == "qr":
        parts = value.split(".")
        try:
            if parts[0] == "PB1" and len(parts) == 5 and int(parts[1]) == kiosk.company_id:
                cand = db.get(User, int(parts[2]))
                if cand and cand.company_id == kiosk.company_id and int(parts[3]) == cand.badge_version and hmac.compare_digest(
                        parts[4], _badge_sig(cand.company_id, cand.id, cand.badge_version)):
                    user = cand
            elif parts[0] == "PR1" and len(parts) == 3:
                cand = db.get(User, int(parts[1]))
                if cand and cand.company_id == kiosk.company_id and cand.badge_secret:
                    step = totp.verify(totp.decrypt(cand.badge_secret), parts[2], cand.badge_last_step)
                    if step is not None:
                        cand.badge_last_step = step
                        user, rotating = cand, True
        except (ValueError, IndexError):
            user = None
    if user is None or not user.active:
        raise fail
    return user, rotating


def issue_ticket(db: Session, kiosk: Kiosk, user: User, now: datetime) -> str:
    nonce = secrets.token_urlsafe(32)
    db.add(KioskTicket(nonce=nonce, company_id=kiosk.company_id, kiosk_id=kiosk.id, user_id=user.id,
                       expires_at=now + timedelta(seconds=settings.kiosk_ticket_seconds)))
    return nonce


def load_ticket(db: Session, kiosk: Kiosk, nonce: str, now: datetime) -> tuple[KioskTicket, User]:
    t = db.get(KioskTicket, nonce or "")
    if not t or t.kiosk_id != kiosk.id or t.used_at is not None or t.expires_at < now:
        raise KioskError(401, "A identificação expirou. Comece de novo.", "ticket_invalid")
    user = db.get(User, t.user_id)
    if not user or not user.active:
        raise KioskError(401, "A identificação expirou. Comece de novo.", "ticket_invalid")
    return t, user


def consume_ticket(db: Session, nonce: str, now: datetime) -> None:
    """Marca como usado de forma atômica: dois envios do mesmo ticket não passam os dois."""
    r = db.execute(update(KioskTicket).where(KioskTicket.nonce == nonce, KioskTicket.used_at.is_(None)).values(used_at=now))
    if r.rowcount != 1:
        raise KioskError(401, "A identificação expirou. Comece de novo.", "ticket_invalid")


def pin_required(company: Company, rotating_qr: bool) -> bool:
    """O PIN é configurável pelo administrador (padrão: não pede). O QR rotativo do aplicativo dispensa: o celular já é a prova."""
    return bool(company.kiosk_pin_required) and not rotating_qr


# --- local -----------------------------------------------------------------------
def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))
