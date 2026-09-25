"""Arquivos legais para a fiscalização: AFD (Anexo V) e AEJ (Anexo VI), com assinatura opcional."""
import io
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import MANAGEMENT_ROLES, client_ip, require_roles
from ..models import Company, User
from ..services import aej, afd, audit, clock, signing

router = APIRouter(prefix="/exports", tags=["fiscalização"])

ROLES = (*MANAGEMENT_ROLES, "auditor")  # Art. 81 §2 e Art. 85: entrega ao Auditor-Fiscal do Trabalho


TEST_WARNING = "Arquivo de teste: sem registro no INPI e sem identificacao do desenvolvedor; invalido para fiscalizacao"


def _deliver(name: str, content: bytes, signed: bool, test_mode: bool = False) -> Response:
    extra = {"X-Ponto-Warning": TEST_WARNING} if test_mode else {}
    if not signed:
        return Response(content, media_type="text/plain; charset=iso-8859-1",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', **extra})
    try:
        signature = signing.sign_detached(content)
    except signing.SigningNotConfigured as e:
        raise HTTPException(409, str(e)) from None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, content)
        z.writestr(name + ".p7s", signature)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}.zip"', **extra})


def _generate(kind: str, builder, request: Request, actor: User, db: Session, start: date, end: date, signed: bool):
    company = db.get(Company, actor.company_id)
    try:
        name, content = builder(db, company, start, end)
    except afd.ExportError as e:
        raise HTTPException(e.status, e.message) from None
    audit.log(db, actor, "export", kind, name, after={"start": str(start), "end": str(end), "signed": signed,
                                                       "bytes": len(content)}, ip=client_ip(request))
    db.commit()
    test_mode = afd.resolve_identity(company).test_mode
    return _deliver(name, content, signed, test_mode)


@router.get("/afd")
def export_afd(
    request: Request, start: date = Query(...), end: date = Query(...), signed: bool = False,
    actor: User = Depends(require_roles(*ROLES)), db: Session = Depends(get_db),
):
    """Arquivo Fonte de Dados do período (datas no fuso da empresa). `signed=true` devolve .zip com o .p7s."""
    return _generate("afd", afd.build_afd, request, actor, db, start, end, signed)


@router.get("/aej")
def export_aej(
    request: Request, start: date = Query(...), end: date = Query(...), signed: bool = False,
    actor: User = Depends(require_roles(*ROLES)), db: Session = Depends(get_db),
):
    """Arquivo Eletrônico de Jornada do período."""
    return _generate("aej", aej.build_aej, request, actor, db, start, end, signed)


@router.get("/status")
def export_status(actor: User = Depends(require_roles(*ROLES)), db: Session = Depends(get_db)):
    """Pré-requisitos para gerar arquivos conformes: o que falta configurar."""
    from ..config import settings

    issues = []
    try:
        if afd.resolve_identity(db.get(Company, actor.company_id)).test_mode:
            issues.append("MODO DE TESTE: sem INPI/desenvolvedor, os arquivos gerados não valem para fiscalização")
    except afd.ExportError as e:
        issues.append(e.message)
    if not signing.is_configured():
        issues.append("Certificado ICP-Brasil não configurado: arquivos saem sem assinatura")
    c = clock.clock_status(force=True) if settings.clock_check_enabled else None
    if c and c.drift_seconds is None:
        issues.append("Não foi possível consultar o servidor de hora (NTP)")
    elif c and not c.ok:
        issues.append(f"Relógio do servidor fora de sincronismo ({c.drift_seconds:+.1f} s)")
    return {"ready": not issues, "issues": issues, "signing_configured": signing.is_configured(),
            "clock_check_enabled": settings.clock_check_enabled,
            "clock_drift_seconds": c.drift_seconds if c else None}
