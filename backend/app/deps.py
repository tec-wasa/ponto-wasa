from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import permissions
from .db import get_db
from .models import User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)

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
    if permissions.requires_2fa(user) and not user.totp_enabled:
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


def require(action: str):
    """Dependência: a pessoa autenticada precisa ter a permissão `action` (ver permissions.ACTIONS)."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if not permissions.can(user, action):
            raise HTTPException(403, "Sem permissão para esta operação")
        return user

    return checker


def require_punch(user: User) -> None:
    """Rotas do "Meu ponto": recusa quem não registra ponto (cadastro só de gestão)."""
    if not permissions.can(user, "punch"):
        raise HTTPException(403, "Este cadastro é só de gestão: não registra ponto")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def can_view_user(db: Session, actor: User, target: User) -> bool:
    """A própria pessoa; a equipe, para o gestor; a empresa, para RH, administração e auditor."""
    return permissions.in_scope(actor, target)


def authorize_decision(db: Session, actor: User, owner: User, note: str | None, what: str) -> bool:
    """Quem pode aprovar ou rejeitar o pedido (ajuste/ausência) de `owner`. Devolve True quando é autoaprovação: permitida só à
    Administração, quando ninguém mais poderia decidir, e com justificativa (registrada em destaque na auditoria)."""
    if permissions.can_approve(actor, owner):
        return False
    if permissions.self_approval_allowed(db, actor, owner):
        if not note or len(note.strip()) < 10:
            raise HTTPException(422, f"Você é a única pessoa que pode decidir este {what}. Para decidir o seu próprio pedido, escreva "
                                     "uma justificativa (ao menos 10 caracteres); ela fica registrada em destaque na auditoria.")
        return True
    if actor.id == owner.id:
        raise HTTPException(403, f"Não é permitido decidir o próprio {what}")
    raise HTTPException(403, f"Sem permissão para decidir este {what}")
