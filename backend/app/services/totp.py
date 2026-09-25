"""Verificação em duas etapas (TOTP, RFC 6238) sem dependências além da biblioteca padrão e do `cryptography`.

- O segredo do usuário é guardado **criptografado** (Fernet), com chave derivada de `PONTO_TOTP_KEY` (ou da
  `PONTO_SECRET_KEY`). Trocar a chave invalida os 2FA já cadastrados: cada usuário precisaria configurar de novo.
- Cada código só vale uma vez (guardamos o último passo de 30 s usado): repetir o mesmo código é recusado.
- Códigos de recuperação: 8 de uso único, guardados só como hash.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno
from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # tolera 1 passo (30 s) para trás ou para frente: relógio do celular ligeiramente fora
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sem 0/o/1/l/i


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_for_step(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{value:0{DIGITS}d}"


def code_at(secret_b32: str, timestamp: float) -> str:
    return _code_for_step(secret_b32, int(timestamp // STEP_SECONDS))


def verify(secret_b32: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """Passo (contador) em que o código confere, ou None. Recusa passos já usados (`step <= last_step`)."""
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_code_for_step(secret_b32, step), code):
            return step
    return None


def provisioning_uri(secret_b32: str, account: str, issuer: str = "Ponto") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def qr_data_uri(uri: str) -> str:
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


# --- segredo criptografado -------------------------------------------------------------------------
def _fernet() -> Fernet:
    material = (settings.totp_key or settings.secret_key).encode() + b"|ponto-totp"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def encrypt(secret_b32: str) -> str:
    return _fernet().encrypt(secret_b32.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # chave trocada: o segredo não é mais legível


# --- códigos de recuperação --------------------------------------------------------------------------
def new_recovery_codes(n: int = 8) -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
        return f"{raw[:4]}-{raw[4:]}"

    return [one() for _ in range(n)]


def normalize_recovery(code: str) -> str:
    return "".join(c for c in (code or "").lower() if c.isalnum())


def hash_recovery(code: str) -> str:
    return hashlib.sha256(normalize_recovery(code).encode() + b"|" + settings.secret_key.encode()).hexdigest()


def looks_like_recovery(code: str) -> bool:
    return len(normalize_recovery(code)) == 8 and not normalize_recovery(code).isdigit()
