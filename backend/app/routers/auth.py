import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import permissions
from ..config import settings
from ..db import get_db
from ..deps import client_ip, get_current_user
from ..models import AuditLog, User
from ..schemas import LoginIn, MeOut, RefreshIn, TokenOut, UserOut
from ..security import create_token, decode_token, hash_password, verify_password
from ..services import audit, passwords, totp

router = APIRouter(prefix="/auth", tags=["auth"])


def _email_key(email: str) -> str:
    """Identificador estável do e-mail na trilha de falhas, sem gravar o e-mail (dado pessoal) em claro."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def _is_throttled(db: Session, ip: str | None, email_key: str) -> bool:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=settings.login_window_minutes)

    def failures(condition) -> int:
        return db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "login_failed", AuditLog.at >= since, condition)
        ).scalar_one()

    if failures(AuditLog.entity_id == email_key) >= settings.login_max_failures:
        return True
    return bool(ip) and failures(AuditLog.ip == ip) >= settings.login_max_failures_per_ip


def _tokens(user: User) -> TokenOut:
    return TokenOut(access_token=create_token(user.id, "access", user.token_version),
                    refresh_token=create_token(user.id, "refresh", user.token_version))


def _fail(db: Session, ip: str | None, key: str, status: int, detail) -> HTTPException:
    audit.log(db, None, "login_failed", "login", key, ip=ip)  # conta para o limite de tentativas
    db.commit()
    return HTTPException(status, detail)


def _second_factor_ok(db: Session, user: User, code: str) -> bool:
    """Confere o código do app (uso único) ou um código de recuperação (consumido). Não faz commit."""
    if totp.looks_like_recovery(code):
        digest = totp.hash_recovery(code)
        if digest in (user.totp_recovery or []):
            user.totp_recovery = [h for h in user.totp_recovery if h != digest]  # nova lista: o JSON detecta a mudança
            audit.log(db, user, "recovery_code_used", "user", user.id)
            return True
        return False
    secret = totp.decrypt(user.totp_secret) if user.totp_secret else None
    step = totp.verify(secret, code, user.totp_last_step) if secret else None
    if step is None:
        return False
    user.totp_last_step = step
    return True


# --- login e sessão ----------------------------------------------------------------------------------
@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip, key = client_ip(request), _email_key(body.email)
    # Limite por IP e por e-mail, contado na trilha de auditoria (vale entre processos e reinícios).
    if _is_throttled(db, ip, key):
        raise HTTPException(429, "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise _fail(db, ip, key, 401, "E-mail ou senha inválidos")

    used_2fa = False
    if user.totp_enabled:
        if not body.otp:  # a senha estava certa: pede o segundo fator (não conta como falha)
            raise HTTPException(401, {"code": "otp_required", "message": "Informe o código do aplicativo autenticador"})
        if not _second_factor_ok(db, user, body.otp):
            db.rollback()
            raise _fail(db, ip, key, 401, {"code": "otp_invalid", "message": "Código inválido ou já utilizado"})
        used_2fa = True
    audit.log(db, user, "login", "user", user.id, ip=ip, after={"2fa": used_2fa})
    db.commit()
    return _tokens(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    decoded = decode_token(body.refresh_token, "refresh")
    user = db.get(User, decoded[0]) if decoded else None
    if not user or not user.active or decoded[1] != user.token_version:
        raise HTTPException(401, "Token inválido")
    return _tokens(user)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    """A pessoa autenticada e o que ela pode fazer (a tela decide o que mostrar só por `permissions`)."""
    out = MeOut.model_validate(user)
    out.permissions, out.scope = permissions.allowed_actions(user), permissions.scope(user)
    return out


@router.post("/consent-photo", response_model=UserOut)
def consent_photo(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Consentimento LGPD para tirar foto na batida (opcional; a foto só é vista pelo RH e apagada no fechamento do mês)."""
    if user.photo_consent_at is None:
        user.photo_consent_at = datetime.now(UTC).replace(tzinfo=None)
        audit.log(db, user, "consent_photo", "user", user.id, ip=client_ip(request))
        db.commit()
    return user


@router.post("/consent-gps", response_model=UserOut)
def consent_gps(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Registra o consentimento LGPD para captura de geolocalização."""
    if user.gps_consent_at is None:
        user.gps_consent_at = datetime.now(UTC).replace(tzinfo=None)
        audit.log(db, user, "consent_gps", "user", user.id, ip=client_ip(request))
        db.commit()
    return user


# --- senha -------------------------------------------------------------------------------------------
class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)


@router.post("/change-password", response_model=TokenOut)
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ip, key = client_ip(request), _email_key(user.email)
    if _is_throttled(db, ip, key):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos e tente novamente.")
    if not verify_password(body.current_password, user.password_hash):
        raise _fail(db, ip, key, 400, "A senha atual está incorreta")
    problem = passwords.check_policy(body.new_password, body.current_password, user.email, user.cpf)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # derruba as demais sessões
    audit.log(db, user, "change_password", "user", user.id, ip=ip)
    db.commit()
    return _tokens(user)


# --- verificação em duas etapas (TOTP) -----------------------------------------------------------------
class OtpIn(BaseModel):
    code: str


class SecondFactorIn(BaseModel):
    password: str
    code: str  # código do app ou de recuperação


@router.get("/2fa")
def two_factor_status(user: User = Depends(get_current_user)):
    return {"enabled": user.totp_enabled, "recovery_codes_left": len(user.totp_recovery or []),
            "required": permissions.requires_2fa(user)}


@router.post("/2fa/setup")
def two_factor_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Gera o segredo para o aplicativo autenticador. Só passa a valer depois de confirmado em /2fa/enable."""
    if user.totp_enabled:
        raise HTTPException(409, "A verificação em duas etapas já está ativa; desative-a antes de configurar de novo")
    secret = totp.new_secret()
    user.totp_secret, user.totp_last_step = totp.encrypt(secret), None
    db.commit()
    uri = totp.provisioning_uri(secret, user.email)
    return {"secret": secret, "uri": uri, "qr": totp.qr_data_uri(uri)}


@router.post("/2fa/enable")
def two_factor_enable(body: OtpIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.totp_enabled:
        raise HTTPException(409, "A verificação em duas etapas já está ativa")
    secret = totp.decrypt(user.totp_secret) if user.totp_secret else None
    if not secret:
        raise HTTPException(409, "Gere o segredo primeiro (passo 1)")
    step = totp.verify(secret, body.code)
    if step is None:
        raise HTTPException(422, "Código incorreto. Confira a hora do celular e tente de novo")
    codes = totp.new_recovery_codes()
    user.totp_enabled, user.totp_last_step = True, step
    user.totp_recovery = [totp.hash_recovery(c) for c in codes]
    user.token_version += 1
    audit.log(db, user, "2fa_enabled", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"recovery_codes": codes, **_tokens(user).model_dump()}  # os códigos aparecem só agora


def _require_password_and_factor(db: Session, user: User, body: SecondFactorIn, request: Request) -> None:
    ip, key = client_ip(request), _email_key(user.email)
    if _is_throttled(db, ip, key):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos e tente novamente.")
    if not verify_password(body.password, user.password_hash):
        raise _fail(db, ip, key, 400, "A senha está incorreta")
    if not _second_factor_ok(db, user, body.code):
        db.rollback()
        raise _fail(db, ip, key, 400, "Código inválido ou já utilizado")


@router.post("/2fa/disable")
def two_factor_disable(body: SecondFactorIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.totp_enabled:
        raise HTTPException(409, "A verificação em duas etapas não está ativa")
    _require_password_and_factor(db, user, body, request)
    user.totp_enabled, user.totp_secret, user.totp_recovery, user.totp_last_step = False, None, None, None
    user.token_version += 1
    audit.log(db, user, "2fa_disabled", "user", user.id, ip=client_ip(request))
    db.commit()
    return _tokens(user)


@router.post("/2fa/recovery-codes")
def two_factor_new_recovery_codes(body: SecondFactorIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Gera 8 códigos novos (os antigos deixam de valer). Exige senha e um código válido."""
    if not user.totp_enabled:
        raise HTTPException(409, "A verificação em duas etapas não está ativa")
    _require_password_and_factor(db, user, body, request)
    codes = totp.new_recovery_codes()
    user.totp_recovery = [totp.hash_recovery(c) for c in codes]
    audit.log(db, user, "2fa_recovery_regenerated", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"recovery_codes": codes}
