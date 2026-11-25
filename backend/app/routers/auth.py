import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import permissions
from ..config import settings
from ..db import get_db
from ..deps import client_ip, get_current_user, restriction_of
from ..models import AuditLog, Company, User
from ..schemas import LoginIn, MeOut, RefreshIn, TokenOut, UserOut
from ..security import create_token, decode_token, hash_password, verify_password
from ..services import audit, google_auth, passwords, totp

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


REFRESH_COOKIE = "ponto_refresh"


def _tokens(user: User, response: Response | None = None, amr: str = "pwd") -> TokenOut:
    """Abre (ou renova) a sessão. O token de renovação vai num cookie HttpOnly, fora do alcance de scripts da página;
    o corpo ainda o devolve para clientes que não são o navegador."""
    refresh = create_token(user.id, "refresh", user.token_version, amr)
    if response is not None:
        response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_days * 86400, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/api/auth")
    return TokenOut(access_token=create_token(user.id, "access", user.token_version, amr), refresh_token=refresh)


def _amr(request: Request) -> str:
    return getattr(request.state, "amr", "pwd")


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
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip, key = client_ip(request), _email_key(body.email)
    # Limite por IP e por e-mail, contado na trilha de auditoria (vale entre processos e reinícios).
    if _is_throttled(db, ip, key):
        raise HTTPException(429, "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if not user or not user.active or not user.app_access or not verify_password(body.password, user.password_hash):
        raise _fail(db, ip, key, 401, "E-mail ou senha inválidos")
    if not db.get(Company, user.company_id).password_login:
        raise HTTPException(403, {"code": "password_login_disabled", "message": "Nesta empresa o acesso é pelo botão Entrar com Google."})

    used_2fa = False
    if user.totp_enabled:
        if not body.otp:  # a senha estava certa: pede o segundo fator (não conta como falha)
            raise HTTPException(401, {"code": "otp_required", "message": "Informe o código do aplicativo autenticador"})
        if not _second_factor_ok(db, user, body.otp):
            db.rollback()
            raise _fail(db, ip, key, 401, {"code": "otp_invalid", "message": "Código inválido ou já utilizado"})
        used_2fa = True
    audit.log(db, user, "login", "user", user.id, ip=ip, after={"2fa": used_2fa, "method": "password"})
    db.commit()
    return _tokens(user, response)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    decoded = decode_token(token, "refresh") if token else None
    user = db.get(User, decoded[0]) if decoded else None
    if not user or not user.active or not user.app_access or decoded[1] != user.token_version:
        raise HTTPException(401, "Token inválido")
    if decoded[2] == "pwd" and not db.get(Company, user.company_id).password_login:
        raise HTTPException(401, "Sessão encerrada: nesta empresa o acesso é pelo Google")
    return _tokens(user, response, decoded[2])


@router.post("/logout", status_code=204)
def logout():
    """Apaga o cookie da sessão neste aparelho."""
    r = Response(status_code=204)
    r.delete_cookie(REFRESH_COOKIE, path="/api/auth", secure=settings.cookie_secure, httponly=True, samesite="strict")
    return r


@router.get("/config")
def public_config():
    """O que a tela de login (e as páginas de privacidade e termos) precisam saber antes de alguém entrar."""
    return {"google_client_id": settings.google_client_id or None, "provider_name": settings.dev_name or None,
            "provider_email": settings.dev_email or None}


# --- Entrar com Google ----------------------------------------------------------------------------------
class GoogleIn(BaseModel):
    credential: str = Field(max_length=4096)


@router.post("/google", response_model=TokenOut)
def login_google(body: GoogleIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Entra com a conta Google. Não há cadastro aberto: só entra quem a empresa cadastrou com o mesmo e-mail (ou quem já
    vinculou a conta Google em Minha conta). Na primeira vez, a conta Google fica vinculada à pessoa."""
    ip = client_ip(request)
    gkey = f"google-{ip}"  # falhas do Google contam por IP, nunca de todos juntos
    if _is_throttled(db, ip, gkey):
        raise HTTPException(429, "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")
    try:
        g = google_auth.verify(body.credential)
    except google_auth.GoogleAuthError as e:
        raise _fail(db, ip, gkey, 401, str(e)) from None
    user = db.execute(select(User).where(User.google_sub == g["sub"])).scalar_one_or_none()
    if user is None and g["email"] and g["email_verified"]:
        user = db.execute(select(User).where(User.email == g["email"])).scalar_one_or_none()
        if user is not None and user.google_sub and user.google_sub != g["sub"]:
            user = None  # este cadastro já está vinculado a outra conta Google
    if user is None or not user.active or not user.app_access:
        who = g["email"] or "usada"
        raise _fail(db, ip, gkey, 401, f"A conta Google {who} não está cadastrada para usar o Ponto. "
                                           "Peça a quem cuida dos cadastros na sua empresa para cadastrar este e-mail.")
    first = user.google_sub is None
    user.google_sub = g["sub"]
    audit.log(db, user, "login", "user", user.id, ip=ip, after={"method": "google", "linked_now": first})
    db.commit()
    return _tokens(user, response, "google")


@router.post("/google/link", response_model=MeOut)
def link_google(body: GoogleIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vincula uma conta Google à pessoa já autenticada (vale mesmo se o e-mail do Google for outro)."""
    try:
        g = google_auth.verify(body.credential)
    except google_auth.GoogleAuthError as e:
        raise HTTPException(422, str(e)) from None
    other = db.execute(select(User).where(User.google_sub == g["sub"], User.id != user.id)).scalar_one_or_none()
    if other:
        raise HTTPException(409, "Esta conta Google já está vinculada a outro cadastro")
    user.google_sub = g["sub"]
    audit.log(db, user, "google_link", "user", user.id, ip=client_ip(request), after={"google_email": g["email"]})
    db.commit()
    return me(request, user)


@router.post("/google/unlink", response_model=MeOut)
def unlink_google(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Company, user.company_id).password_login:
        raise HTTPException(409, "Nesta empresa o acesso é só pelo Google: desvincular deixaria você sem acesso")
    user.google_sub = None
    audit.log(db, user, "google_unlink", "user", user.id, ip=client_ip(request))
    db.commit()
    return me(request, user)


@router.get("/me", response_model=MeOut)
def me(request: Request, user: User = Depends(get_current_user)):
    """A pessoa autenticada e o que ela pode fazer (a tela decide o que mostrar só por `permissions`)."""
    amr = _amr(request)
    out = MeOut.model_validate(user)
    out.permissions, out.scope = permissions.allowed_actions(user), permissions.scope(user)
    out.google_linked, out.login_method, out.restriction = bool(user.google_sub), amr, restriction_of(user, amr)
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
def change_password(body: ChangePasswordIn, request: Request, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
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
    return _tokens(user, response, _amr(request))


# --- verificação em duas etapas (TOTP) -----------------------------------------------------------------
class OtpIn(BaseModel):
    code: str


class SecondFactorIn(BaseModel):
    password: str
    code: str  # código do app ou de recuperação


@router.get("/2fa")
def two_factor_status(request: Request, user: User = Depends(get_current_user)):
    return {"enabled": user.totp_enabled, "recovery_codes_left": len(user.totp_recovery or []),
            "required": permissions.requires_2fa(user) and _amr(request) == "pwd"}


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
def two_factor_enable(body: OtpIn, request: Request, response: Response, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
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
    return {"recovery_codes": codes, **_tokens(user, response, _amr(request)).model_dump()}  # os códigos aparecem só agora


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
def two_factor_disable(body: SecondFactorIn, request: Request, response: Response, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    if not user.totp_enabled:
        raise HTTPException(409, "A verificação em duas etapas não está ativa")
    _require_password_and_factor(db, user, body, request)
    user.totp_enabled, user.totp_secret, user.totp_recovery, user.totp_last_step = False, None, None, None
    user.token_version += 1
    audit.log(db, user, "2fa_disabled", "user", user.id, ip=client_ip(request))
    db.commit()
    return _tokens(user, response, _amr(request))


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
