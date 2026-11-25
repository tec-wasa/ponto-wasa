"""Confere o token de identidade do "Entrar com Google" (Google Identity Services).

O navegador recebe do Google um JWT assinado (RS256). Aqui conferimos a assinatura com as chaves públicas do Google, o
destinatário (o nosso Client ID), o emissor e a validade. Não usamos segredo: o Client ID é público.
"""
import jwt
from jwt import PyJWKClient

from ..config import settings

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
_jwks: PyJWKClient | None = None


class GoogleAuthError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.google_client_id)


def verify(credential: str) -> dict:
    """{"sub", "email", "email_verified", "name"} do token, ou GoogleAuthError."""
    global _jwks
    if not enabled():
        raise GoogleAuthError("O login com Google não está configurado neste servidor")
    if not credential or len(credential) > 4096:
        raise GoogleAuthError("Credencial do Google inválida")
    try:
        if _jwks is None:
            _jwks = PyJWKClient(CERTS_URL, cache_keys=True, lifespan=3600)
        key = _jwks.get_signing_key_from_jwt(credential).key
        data = jwt.decode(credential, key, algorithms=["RS256"], audience=settings.google_client_id, issuer=ISSUERS, leeway=60)
    except (jwt.PyJWTError, OSError) as e:
        raise GoogleAuthError("Não foi possível confirmar o login com o Google. Tente de novo.") from e
    if not data.get("sub"):
        raise GoogleAuthError("Credencial do Google sem identificador")
    return {"sub": str(data["sub"]), "email": str(data.get("email", "")).lower(), "email_verified": bool(data.get("email_verified")),
            "name": data.get("name")}
