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


def create_token(user_id: int, kind: str, version: int = 0) -> str:
    delta = (
        timedelta(minutes=settings.access_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_days)
    )
    payload = {"sub": str(user_id), "typ": kind, "ver": version, "exp": datetime.now(UTC) + delta}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, kind: str) -> tuple[int, int] | None:
    """(id do usuário, versão da sessão) ou None. A versão precisa bater com a do usuário (ver deps)."""
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if data.get("typ") != kind:
        return None
    return int(data["sub"]), int(data.get("ver", 0))
