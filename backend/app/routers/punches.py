import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import can_view_user, client_ip, get_current_user, require, require_punch
from ..models import Company, Kiosk, Punch, User
from ..schemas import PunchIn, PunchOut, ReceiptOut
from ..services import audit, clock, folha, pdfsign, signing
from ..services import pdf as pdf_service
from ..services.espelho import build_espelho
from ..services.mirror import month_days, summarize
from ..services.punching import KIND_LABEL, PunchError, _crosses, day_closed, has_break, next_kind, register_punch, verify_chain

router = APIRouter(tags=["ponto"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


FUTURE_TOLERANCE = timedelta(minutes=2)


def _offline_moment(body: PunchIn, now: datetime) -> datetime:
    """Valida uma marcação off-line e devolve o instante em que ela ocorreu (UTC)."""
    if not settings.offline_punch_enabled:
        raise PunchError(403, "O registro off-line está desativado")
    if not body.client_key:
        raise PunchError(422, "Marcação off-line exige a chave de idempotência (client_key)")
    if body.occurred_at is None:
        raise PunchError(422, "Marcação off-line exige a hora da marcação")
    if body.kind is None:
        raise PunchError(422, "Marcação off-line exige o tipo (o aparelho não sabe o estado do servidor)")
    moment = _naive_utc(body.occurred_at)
    if moment > now + FUTURE_TOLERANCE:
        raise PunchError(422, "A hora da marcação está no futuro: o relógio do aparelho está errado")
    if now - moment > timedelta(hours=settings.offline_max_hours):
        raise PunchError(422, f"Marcação com mais de {settings.offline_max_hours} h: fora do prazo de envio. "
                              "Peça a inclusão por ajuste ao seu gestor")
    return moment


@router.post("/punches", response_model=PunchOut, status_code=201)
def punch(body: PunchIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Registra uma marcação usando a hora do servidor. Só a marcação off-line usa a hora do aparelho, com limites."""
    if user.punch_policy == "kiosk":
        raise HTTPException(403, "Você registra o ponto na Central do Ponto. O aplicativo não registra batidas para o seu cadastro.")
    try:
        if settings.clock_check_enabled:  # Anexo IX, item 2: relógio em sincronismo com a Hora Legal Brasileira
            status = clock.clock_status()
            if status.drift_seconds is not None and not status.ok:
                raise PunchError(503, "Relógio do servidor fora de sincronismo com a Hora Legal Brasileira")
        if body.client_key:  # repetição do mesmo toque (ou reenvio off-line já aceito): devolve o que existe, sem revalidar prazos
            again = db.execute(select(Punch).where(Punch.user_id == user.id, Punch.client_key == body.client_key)).scalar_one_or_none()
            if again:
                return again
        now = _now()
        moment = _offline_moment(body, now) if body.offline else now
        p = register_punch(
            db, user, kind=body.kind, occurred_at=moment, collector=body.collector, latitude=body.latitude,
            longitude=body.longitude, accuracy_m=body.accuracy_m, device_id=body.device_id,
            client_key=body.client_key, offline=body.offline,
        )
        after = {"nsr": p.nsr, "kind": p.kind}
        if body.offline:  # trilha para conferir depois: hora crua do aparelho, desvio usado e atraso do envio
            after |= {"offline": True, "device_time": body.device_time.isoformat() if body.device_time else None,
                      "skew_ms": body.skew_ms, "delay_s": int((p.recorded_at - p.occurred_at).total_seconds())}
        audit.log(db, user, "punch", "punch", p.id, after=after, ip=client_ip(request))
        db.commit()
    except PunchError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflito ao registrar; tente novamente") from None
    return p


@router.get("/punches/next")
def next_punch(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Qual é a próxima marcação (pela ordem) e se a jornada tem intervalo. É só uma dica para a tela."""
    require_punch(user)
    kind = next_kind(db, user, _now())
    with_break = has_break(db, user)
    closed = day_closed(db, user, db.get(Company, user.company_id), _now())
    return {"kind": kind, "label": KIND_LABEL[kind], "has_break": with_break, "closed": closed, "app_blocked": user.punch_policy == "kiosk", "crosses_midnight": _crosses(db, user),
            "can_skip_break": with_break and kind == "inicio_intervalo"}


@router.get("/punches", response_model=list[PunchOut])
def my_punches(
    start: datetime | None = None, end: datetime | None = None, limit: int = Query(100, le=500),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    q = select(Punch).where(Punch.user_id == user.id)
    if start:
        q = q.where(Punch.occurred_at >= start)
    if end:
        q = q.where(Punch.occurred_at <= end)
    rows = db.execute(q.order_by(Punch.occurred_at.desc()).limit(limit)).scalars().all()
    names = {k.id: k.name for k in db.execute(select(Kiosk).where(Kiosk.company_id == user.company_id)).scalars()}
    out = []
    for p in rows:
        item = PunchOut.model_validate(p)
        item.origin = f"Central {names.get(p.kiosk_id, '')}".strip() if p.kiosk_id else "Aplicativo"
        out.append(item)
    return out


def _receipt(company: Company, owner: User, p: Punch) -> ReceiptOut:
    local = p.occurred_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(company.timezone))
    return ReceiptOut(
        title="Comprovante de Registro de Ponto do Trabalhador", employer=company.name, cnpj=company.cnpj,
        caepf_cno=company.caepf or company.cno, workplace=company.workplace, inpi=settings.inpi_number,
        employee=owner.name, cpf=p.cpf, nsr=p.nsr, kind=p.kind,
        occurred_at_local=local.strftime("%d/%m/%Y %H:%M:%S"), hash=p.hash,
    )


@router.get("/punches/{punch_id}/receipt", response_model=ReceiptOut)
def receipt(punch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.get(Punch, punch_id)
    owner = db.get(User, p.user_id) if p else None
    if not p or not can_view_user(db, user, owner):
        raise HTTPException(404, "Marcação não encontrada")
    return _receipt(db.get(Company, p.company_id), owner, p)


TEST_WARNING = "Documento de teste: PDF sem assinatura ICP-Brasil (modo de teste); invalido como comprovante"


@router.get("/punches/{punch_id}/receipt.pdf")
def receipt_pdf(punch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Comprovante em PDF assinado eletronicamente (Art. 80, I). Sem certificado, só em modo de teste."""
    p = db.get(Punch, punch_id)
    owner = db.get(User, p.user_id) if p else None
    if not p or not can_view_user(db, user, owner):
        raise HTTPException(404, "Marcação não encontrada")
    data = _receipt(db.get(Company, p.company_id), owner, p).model_dump()
    document = pdf_service.receipt_pdf(data, signed=signing.is_configured())
    headers = {"Content-Disposition": f'attachment; filename="comprovante-NSR{p.nsr}.pdf"'}
    try:
        document = pdfsign.sign_pdf(document)
    except signing.SigningNotConfigured as e:
        if not settings.allow_missing_inpi:
            raise HTTPException(409, f"{e}. O comprovante em PDF deve ser assinado com certificado ICP-Brasil (Art. 80).") from None
        headers["X-Ponto-Warning"] = TEST_WARNING
    return Response(document, media_type="application/pdf", headers=headers)


@router.get("/receipts", response_model=list[ReceiptOut])
def recent_receipts(hours: int = Query(48, ge=1, le=720), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Comprovantes das marcações recentes do próprio trabalhador (Art. 80, III: no mínimo 48 h)."""
    company = db.get(Company, user.company_id)
    since = _now() - timedelta(hours=hours)
    rows = db.execute(
        select(Punch).where(Punch.user_id == user.id, Punch.occurred_at >= since).order_by(Punch.nsr.desc())
    ).scalars().all()
    return [_receipt(company, user, p) for p in rows]


@router.get("/time")
def server_time():
    """Hora do servidor (UTC), para o coletor exibir um relógio coerente com o registrado."""
    return {"utc": _now().isoformat() + "Z",
            "offline": {"enabled": settings.offline_punch_enabled, "max_hours": settings.offline_max_hours}}


@router.get("/punches-integrity")
def integrity(user: User = Depends(require("integrity.view")), db: Session = Depends(get_db)):
    """Verifica NSR contínuo (todos os tipos de registro) e a cadeia de hashes das marcações (RF-29)."""
    return verify_chain(db, user.company_id)


@router.get("/mirror")
def mirror(
    month: str = Query(..., description="YYYY-MM"), user_id: int | None = None,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Espelho de ponto mensal: horas trabalhadas, extras, faltas e alertas."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    target = db.get(User, user_id) if user_id else actor
    if not target or not can_view_user(db, actor, target):
        raise HTTPException(404, "Colaborador não encontrado")

    days = month_days(db, target, db.get(Company, target.company_id), int(month[:4]), int(month[5:]))
    return {"user_id": target.id, "month": month, **summarize(days)}


@router.get("/mirror/official.pdf")
def official_mirror(
    request: Request, month: str = Query(..., description="YYYY-MM"), user_id: int | None = None,
    modelo: str = Query("folha", pattern="^(folha|detalhado)$", description="folha: uma página para assinatura; detalhado: com NSR"),
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Folha de ponto do mês para assinatura (uma página A4) ou o espelho detalhado (Portaria 671, Art. 84), em PDF."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    target = db.get(User, user_id) if user_id else actor
    if not target or not can_view_user(db, actor, target):
        raise HTTPException(404, "Colaborador não encontrado")
    company = db.get(Company, target.company_id)
    if modelo == "folha":
        document, name = folha.folha_pdf(folha.build_folha(db, company, target, int(month[:4]), int(month[5:]))), "folha-de-ponto"
    else:
        document = pdf_service.espelho_pdf(build_espelho(db, company, target, int(month[:4]), int(month[5:])))
        name = "espelho"
    audit.log(db, actor, "export", "espelho", target.id, after={"month": month, "modelo": modelo}, ip=client_ip(request))
    db.commit()
    return Response(document, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}-{target.cpf}-{month}.pdf"'})
