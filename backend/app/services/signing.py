"""Assinatura eletrônica dos arquivos (AFD/AEJ) com certificado ICP-Brasil (Portaria 671, arts. 86 e 88).

# H5. A Portaria não define o formato da assinatura dos arquivos. Geramos uma assinatura CMS/PKCS#7
#     destacada (arquivo .p7s, DER, SHA-256), o padrão usual de mercado. Não inclui atributos de
#     política CAdES/ICP-Brasil; validar na homologação.
"""
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12

from ..config import settings


class SigningNotConfigured(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.signing_p12_path) and Path(settings.signing_p12_path).is_file()


def sign_detached(data: bytes) -> bytes:
    if not is_configured():
        raise SigningNotConfigured("Certificado de assinatura não configurado (PONTO_SIGNING_P12_PATH)")
    password = settings.signing_p12_password.encode() or None
    key, cert, extra = pkcs12.load_key_and_certificates(Path(settings.signing_p12_path).read_bytes(), password)
    builder = pkcs7.PKCS7SignatureBuilder().set_data(data).add_signer(cert, key, hashes.SHA256())
    for c in extra or []:
        builder = builder.add_certificate(c)
    return builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
