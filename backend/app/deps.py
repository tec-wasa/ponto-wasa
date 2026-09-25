from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)

MANAGEMENT_ROLES = ("hr", "admin")

# Enquanto a conta tem uma pendência de segurança, só estas rotas funcionam (o suficiente para resolvê-la).
ALLOWED_WHEN_RESTRICTED = {
    "/api/auth/me", "/api/auth/change-password", "/api/auth/2fa", "/api/auth/2fa/setup", "/api/auth/2fa/enable",
}
RESTRICTION_MESSAGE = {
    "password_change_required": "Troque a senha temporária para continuar",
    "two_factor_required": "Seu perfil exige verificação em duas etapas: ative o 2FA para continuar",
}


def restriction_of(user: User) -> str | None:
    if user.must_change_password:
        return "password_change_required"
    if user.role in settings.require_2fa_role_set and not user.totp_enabled:
        return "two_factor_required"
    return None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    decoded = decode_token(creds.credentials, "access") if creds else None
    user = db.get(User, decoded[0]) if decoded else None
    # A versão do token precisa bater: trocar senha, redefinir ou mudar o 2FA derruba as sessões anteriores.
    if user is None or not user.active or decoded[1] != user.token_version:
        raise HTTPException(401, "Não autenticado")
    restriction = restriction_of(user)
    if restriction and request.url.path not in ALLOWED_WHEN_RESTRICTED:
        raise HTTPException(403, {"code": restriction, "message": RESTRICTION_MESSAGE[restriction]})
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Sem permissão para esta operação")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def can_view_user(db: Session, actor: User, target: User) -> bool:
    """Colaborador vê a si mesmo; gestor vê sua equipe; RH/admin/auditor veem a empresa."""
    if target.company_id != actor.company_id:
        return False
    if actor.id == target.id or actor.role in (*MANAGEMENT_ROLES, "auditor"):
        return True
    return actor.role == "manager" and target.manager_id == actor.id
