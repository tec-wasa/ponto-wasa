"""Relatórios gerenciais em CSV e PDF (RF-19). Cada emissão vai para a trilha de auditoria."""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, require
from ..models import Company, User
from ..services import audit, reports

router = APIRouter(prefix="/reports", tags=["relatórios"])

FORMATS = {"csv": ("text/csv; charset=utf-8", "csv"), "pdf": ("application/pdf", "pdf")}


def _deliver(kind: str, name: str, fmt: str, csv_builder, pdf_builder, data: dict, request: Request, actor: User,
             db: Session, params: dict) -> Response:
    if fmt not in FORMATS:
        raise HTTPException(422, "Formato deve ser csv ou pdf")
    content = csv_builder(data) if fmt == "csv" else pdf_builder(data)
    audit.log(db, actor, "export", f"report_{kind}", 0, after={**params, "format": fmt, "rows": len(data["rows"])},
              ip=client_ip(request))
    db.commit()
    return Response(content, media_type=FORMATS[fmt][0],
                    headers={"Content-Disposition": f'attachment; filename="{name}.{FORMATS[fmt][1]}"'})


def _run(builder):
    try:
        return builder()
    except reports.ReportError as e:
        raise HTTPException(e.status, e.message) from None


@router.get("/monthly")
def monthly(
    request: Request, month: str = Query(..., description="YYYY-MM"), format: str = "csv",
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Consolidado do mês por colaborador: horas, saldo, faltas, justificativas e banco de horas."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.monthly(db, company, actor, int(month[:4]), int(month[5:])))
    return _deliver("monthly", f"fechamento-{month}", format, reports.monthly_csv, reports.monthly_pdf, data, request,
                    actor, db, {"month": month})


@router.get("/overtime")
def overtime_report(
    request: Request, month: str = Query(..., description="YYYY-MM"), format: str = "csv",
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Horas extras pagas do mês por colaborador, por percentual e por tipo de dia (quem não usa banco de horas)."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.overtime_report(db, company, actor, int(month[:4]), int(month[5:])))
    return _deliver("overtime", f"horas-extras-{month}", format, reports.overtime_csv, reports.overtime_pdf, data, request,
                    actor, db, {"month": month})


@router.get("/hour-bank")
def hour_bank(
    request: Request, format: str = "csv",
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Posição atual do banco de horas de quem o utiliza."""
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.bank_report(db, company, actor))
    return _deliver("hour_bank", f"banco-de-horas-{date.today():%Y%m%d}", format, reports.bank_csv, reports.bank_pdf,
                    data, request, actor, db, {})


@router.get("/absences")
def absences(
    request: Request, start: date = Query(...), end: date = Query(...), status: str | None = None, format: str = "csv",
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Ausências que tocam o período. O motivo de atestado e afastamento só aparece para RH e administrador."""
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.absences_report(db, company, actor, start, end, status))
    return _deliver("absences", f"ausencias-{start}-{end}", format, reports.absences_csv, reports.absences_pdf, data,
                    request, actor, db, {"start": str(start), "end": str(end), "status": status})


@router.get("/punches")
def punches_by_origin(
    request: Request, start: date = Query(...), end: date = Query(...), origin: str = "all", format: str = "csv",
    actor: User = Depends(require("team.view")), db: Session = Depends(get_db),
):
    """Batidas do período no escopo do emitente, filtráveis por origem (all, app ou central)."""
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.punches_report(db, company, actor, start, end, origin))
    return _deliver("punches", f"batidas-{start}-{end}", format, reports.punches_csv, reports.punches_pdf, data, request,
                    actor, db, {"start": str(start), "end": str(end), "origin": origin})


@router.get("/kiosk-divergences")
def kiosk_divergences(
    request: Request, start: date = Query(...), end: date = Query(...), format: str = "csv",
    actor: User = Depends(require("reports.company")), db: Session = Depends(get_db),
):
    """Central: batidas fora do posto ou sem localização, falhas de identificação e aparelhos sem sinal."""
    company = db.get(Company, actor.company_id)
    data = _run(lambda: reports.kiosk_divergences(db, company, actor, start, end))
    return _deliver("kiosk_divergences", f"divergencias-central-{start}-{end}", format, reports.divergences_csv,
                    reports.divergences_pdf, data, request, actor, db, {"start": str(start), "end": str(end)})
