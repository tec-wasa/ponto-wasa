from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import settings

_ph = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


def create_token(user_id: int, kind: str, version: int = 0, amr: str = "pwd") -> str:
    """`amr`: como a pessoa entrou ("pwd" senha, "google"); vale para a sessão inteira, inclusive nas renovações."""
    delta = (
        timedelta(minutes=settings.access_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_days)
    )
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "typ": kind, "ver": version, "amr": amr, "iat": now, "exp": now + delta}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, kind: str) -> tuple[int, int, str, int] | None:
    """(id do usuário, versão da sessão, forma de entrada, emitido em) ou None. A versão precisa bater com a do usuário (ver deps)."""
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if data.get("typ") != kind:
        return None
    return int(data["sub"]), int(data.get("ver", 0)), str(data.get("amr", "pwd")), int(data.get("iat", 0))
