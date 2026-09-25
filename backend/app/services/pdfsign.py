"""Assinatura eletrônica de PDF com certificado ICP-Brasil (Portaria 671, arts. 80, I e 88).

# H6. A Portaria exige PDF "assinado eletronicamente" com certificado ICP-Brasil, sem fixar o perfil.
#     Usamos assinatura PAdES (ETSI.CAdES.detached) incremental via pyHanko, SHA-256. A política de
#     assinatura ICP-Brasil (DOC-ICP-15) e o carimbo do tempo não são aplicados; validar na homologação.
"""
import io
from pathlib import Path

from pyhanko.sign import fields, signers

from ..config import settings
from .signing import SigningNotConfigured, is_configured


def sign_pdf(pdf: bytes, field_name: str = "AssinaturaPonto") -> bytes:
    if not is_configured():
        raise SigningNotConfigured("Certificado de assinatura não configurado (PONTO_SIGNING_P12_PATH)")
    signer = signers.SimpleSigner.load_pkcs12(
        pfx_file=str(Path(settings.signing_p12_path)),
        passphrase=settings.signing_p12_password.encode() or None,
    )
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    meta = signers.PdfSignatureMetadata(field_name=field_name, subfilter=fields.SigSeedSubFilter.PADES, md_algorithm="sha256")
    out = signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)), meta, signer=signer)
    return out.getvalue()
