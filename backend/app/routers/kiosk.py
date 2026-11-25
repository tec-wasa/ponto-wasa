"""Central do Ponto: aparelho compartilhado onde cada pessoa se identifica (QR, código ou CPF; PIN opcional) e registra o
ponto com foto obrigatória. O aparelho se autentica por token (pareamento); a pessoa recebe só um ticket de uso único."""
import secrets
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import segno
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..config import settings
from ..db import get_db
from ..deps import client_ip, get_current_user, require, require_punch
from ..models import AuditLog, Company, Kiosk, KioskTicket, Punch, User
from ..security import verify_password
from ..services import audit, badges, clock, photos
from ..services import kiosk as svc
from ..services.punching import KIND_LABEL, PunchError, day_closed, has_break, month_of, next_kind, register_punch

router = APIRouter(tags=["central do ponto"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fail(e: svc.KioskError):
    detail = {"code": e.code, "message": e.message} if e.code else e.message
    return HTTPException(e.status, detail)


# ============================ Aparelho (Central) ====================================
def get_kiosk(x_kiosk_token: str | None = Header(None), db: Session = Depends(get_db)) -> Kiosk:
    if not x_kiosk_token:
        raise HTTPException(401, "Aparelho não autenticado")
    kiosk = db.execute(select(Kiosk).where(Kiosk.token_hash == svc.sha256(x_kiosk_token))).scalar_one_or_none()
    if not kiosk or not kiosk.active:
        raise HTTPException(401, "Aparelho não autorizado. Peça um novo pareamento ao administrador.")
    now = _now()
    if not kiosk.last_seen_at or now - kiosk.last_seen_at > timedelta(seconds=60):
        kiosk.last_seen_at = now  # no máximo uma escrita por minuto
        db.commit()
    return kiosk


class PairIn(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=16)


@router.post("/kiosk/pair")
def pair(body: PairIn, request: Request, db: Session = Depends(get_db)):
    """Troca o código de pareamento (uso único, curto) pelo token do aparelho. O token só aparece aqui, uma vez."""
    ip = client_ip(request) or "?"
    since = _now() - timedelta(minutes=10)
    failures = db.execute(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "kiosk_pair_failed", AuditLog.entity_id == ip, AuditLog.at >= since)).scalar_one()
    if failures >= 10:
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    code = body.pairing_code.strip().upper()
    now = _now()
    kiosk = db.execute(select(Kiosk).where(Kiosk.pairing_hash == svc.sha256(code), Kiosk.active.is_(True))).scalar_one_or_none()
    if not kiosk or not kiosk.pairing_expires_at or kiosk.pairing_expires_at < now:
        audit.log(db, None, "kiosk_pair_failed", "kiosk", ip, ip=ip, company_id=kiosk.company_id if kiosk else None)
        db.commit()
        raise HTTPException(401, "Código de pareamento inválido ou expirado")
    token = secrets.token_urlsafe(32)
    kiosk.token_hash, kiosk.pairing_hash, kiosk.pairing_expires_at, kiosk.last_seen_at = svc.sha256(token), None, None, now
    audit.log(db, None, "kiosk_paired", "kiosk", kiosk.id, ip=ip, company_id=kiosk.company_id)
    db.commit()
    return {"token": token, "kiosk": {"id": kiosk.id, "name": kiosk.name}}


@router.get("/kiosk/state")
def state(kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    company = db.get(Company, kiosk.company_id)
    return {
        "company": company.name, "timezone": company.timezone, "server_time": _now().isoformat() + "Z",
        "kiosk": {"id": kiosk.id, "name": kiosk.name, "latitude": kiosk.latitude, "longitude": kiosk.longitude,
                  "radius_m": kiosk.radius_m},
        "pin_required": bool(company.kiosk_pin_required), "photo_required": True, "consent_text": svc.CONSENT_TEXT,
        # sem internet só vale o QR do crachá impresso, e nunca quando a empresa exige PIN (não dá para conferir o PIN offline)
        "offline": {"enabled": settings.offline_punch_enabled and not company.kiosk_pin_required, "max_hours": settings.offline_max_hours},
    }


class IdentifyIn(BaseModel):
    method: str = Field(pattern="^(qr|code|cpf)$")
    value: str = Field(min_length=1, max_length=200)
    pin: str | None = Field(None, max_length=12)


def _identify_throttled(db: Session, kiosk: Kiosk) -> bool:
    since = _now() - timedelta(minutes=5)
    n = db.execute(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "kiosk_identify_failed", AuditLog.entity == "kiosk", AuditLog.entity_id == str(kiosk.id),
        AuditLog.at >= since)).scalar_one()
    return n >= 30


def _next_info(db: Session, user: User, now: datetime) -> dict:
    kind = next_kind(db, user, now)
    with_break = has_break(db, user)
    seq = (["entrada", "inicio_intervalo", "fim_intervalo", "saida"] if with_break else ["entrada", "saida"]).index(kind) + 1
    return {"next_kind": kind, "next_label": KIND_LABEL[kind], "sequence": seq, "has_break": with_break}


@router.post("/kiosk/identify")
def identify(body: IdentifyIn, request: Request, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """Identifica a pessoa e devolve um ticket de uso único. Toda falha responde igual (não revela se o código existe)."""
    now = _now()
    if _identify_throttled(db, kiosk):
        raise HTTPException(429, "Muitas tentativas nesta central. Aguarde alguns minutos.")
    company = db.get(Company, kiosk.company_id)

    def deny():
        audit.log(db, None, "kiosk_identify_failed", "kiosk", kiosk.id, after={"method": body.method}, ip=client_ip(request),
                  company_id=kiosk.company_id)
        db.commit()
        return HTTPException(401, svc.GENERIC_FAIL)

    try:
        user, rotating = svc.resolve_user(db, kiosk, body.method, body.value, now)
    except svc.KioskError:
        raise deny() from None

    if svc.pin_required(company, rotating):
        if not body.pin:
            if body.method == "qr":  # o QR já é segredo: pode dizer que falta o PIN (sem revelar nome)
                raise HTTPException(403, {"code": "pin_required", "message": "Digite seu PIN"})
            raise deny()
        if not svc.check_pin(user, body.pin, now):
            db.commit()  # guarda a contagem de falhas / bloqueio
            raise deny()

    try:
        if day_closed(db, user, company, now):
            raise HTTPException(409, {"code": "day_closed", "message": "Jornada encerrada: a saída de hoje já foi registrada."})
    except PunchError as e:  # pragma: no cover
        raise HTTPException(e.status, e.message) from None

    ticket = svc.issue_ticket(db, kiosk, user, now)
    audit.log(db, user, "kiosk_identify", "kiosk", kiosk.id, after={"method": body.method}, ip=client_ip(request))
    db.commit()
    return {"ticket": ticket, "expires_in": settings.kiosk_ticket_seconds, "first_name": user.name.strip().split()[0],
            "needs_consent": user.photo_consent_at is None, "photo_required": True, **_next_info(db, user, now)}


class TicketIn(BaseModel):
    ticket: str


@router.post("/kiosk/consent-photo")
def consent_photo(body: TicketIn, request: Request, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """Consentimento LGPD dado na própria Central (mesmo efeito do consentimento no aplicativo). Não consome o ticket."""
    try:
        _, user = svc.load_ticket(db, kiosk, body.ticket, _now())
    except svc.KioskError as e:
        raise _fail(e) from None
    if user.photo_consent_at is None:
        user.photo_consent_at = _now()
        audit.log(db, user, "consent_photo", "user", user.id, after={"via": f"kiosk:{kiosk.id}"}, ip=client_ip(request))
        db.commit()
    return {"ok": True}


class KioskPunchIn(BaseModel):
    ticket: str
    photo: str = Field(min_length=1, description="JPEG em base64: obrigatória na Central")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    client_key: str | None = Field(None, max_length=100)


@router.post("/kiosk/punch", status_code=201)
def punch(body: KioskPunchIn, request: Request, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """Registra a batida da pessoa identificada, com a hora do servidor, a ordem das batidas e a foto (obrigatória)."""
    now = _now()
    try:
        ticket, user = svc.load_ticket(db, kiosk, body.ticket, now)
    except svc.KioskError as e:
        raise _fail(e) from None
    company = db.get(Company, kiosk.company_id)
    if user.photo_consent_at is None:
        raise HTTPException(403, {"code": "consent_required", "message": "É preciso autorizar a foto para bater ponto nesta central"})
    try:
        data = photos.decode_jpeg(body.photo)
    except photos.PhotoError as e:
        raise HTTPException(e.status, e.message) from None

    try:
        if settings.clock_check_enabled:
            status = clock.clock_status()
            if status.drift_seconds is not None and not status.ok:
                raise PunchError(503, "Relógio do servidor fora de sincronismo com a Hora Legal Brasileira")
        if day_closed(db, user, company, now):
            raise HTTPException(409, {"code": "day_closed", "message": "Jornada encerrada: a saída de hoje já foi registrada."})
        svc.consume_ticket(db, ticket.nonce, now)
        dist = None
        if body.latitude is not None and body.longitude is not None and kiosk.latitude is not None and kiosk.longitude is not None:
            dist = svc.distance_m(body.latitude, body.longitude, kiosk.latitude, kiosk.longitude)
        p = register_punch(
            db, user, kind=None, occurred_at=now, collector="04", device_id=f"kiosk:{kiosk.id}", client_key=body.client_key,
            latitude=body.latitude, longitude=body.longitude, kiosk_id=kiosk.id, distance_m=dist, keep_location=True,
        )
        photos.save(db, p, month_of(company, p.occurred_at), data)  # foto obrigatória: sem ela, nada é gravado
        outside = None if dist is None else dist > kiosk.radius_m
        audit.log(db, user, "kiosk_punch", "punch", p.id, ip=client_ip(request),
                  after={"nsr": p.nsr, "kind": p.kind, "kiosk": kiosk.id, "distance_m": dist, "outside_radius": outside})
        db.commit()
    except PunchError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    except svc.KioskError as e:
        db.rollback()
        raise _fail(e) from None
    except photos.PhotoError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    except HTTPException:
        db.rollback()
        raise
    local = p.occurred_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(company.timezone))
    return {"nsr": p.nsr, "kind": p.kind, "label": KIND_LABEL[p.kind], "occurred_at": p.occurred_at.isoformat() + "Z",
            "time_local": local.strftime("%H:%M"), "hash_short": f"{p.hash[:4]}…{p.hash[-4:]}", "first_name": user.name.strip().split()[0],
            "distance_m": dist, "outside_radius": outside, "photo": True}


class OfflinePunchIn(BaseModel):
    qr: str = Field(min_length=1, max_length=200)
    photo: str = Field(min_length=1)
    client_key: str = Field(min_length=8, max_length=100)
    occurred_at: datetime = Field(description="Instante da batida (UTC): hora do aparelho corrigida pelo desvio medido")
    device_time: datetime | None = None
    skew_ms: int | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


@router.post("/kiosk/offline-punch", status_code=201)
def offline_punch(body: OfflinePunchIn, request: Request, kiosk: Kiosk = Depends(get_kiosk), db: Session = Depends(get_db)):
    """Batida feita pela Central SEM internet: o aparelho só guardou o QR do crachá impresso (PB1), a foto e a hora.
    A pessoa é identificada e a assinatura do QR conferida AGORA, no envio. Crachá regenerado, pessoa inativa, consentimento
    ausente, hora futura ou fora do prazo, sequência inválida: a batida é recusada (com registro na auditoria) e vai para ajuste."""
    now = _now()
    company = db.get(Company, kiosk.company_id)

    def reject(message: str, user: User | None = None, status: int = 422):
        db.rollback()
        audit.log(db, user, "kiosk_offline_rejected", "kiosk", kiosk.id, ip=client_ip(request), company_id=kiosk.company_id,
                  after={"reason": message, "client_key": body.client_key, "occurred_at": body.occurred_at.isoformat()})
        db.commit()
        return HTTPException(status, {"code": "offline_rejected", "message": message})

    if _identify_throttled(db, kiosk):
        raise HTTPException(429, "Muitas tentativas nesta central. Aguarde alguns minutos.")
    if not settings.offline_punch_enabled or company.kiosk_pin_required:
        raise reject("A batida sem internet não está habilitada para esta empresa")
    if not body.qr.strip().startswith("PB1."):  # o QR rotativo do aplicativo não pode ser conferido depois
        raise reject("Só o QR do crachá impresso vale sem internet")
    try:
        user, _ = svc.resolve_user(db, kiosk, "qr", body.qr, now)
    except svc.KioskError:
        audit.log(db, None, "kiosk_identify_failed", "kiosk", kiosk.id, after={"method": "qr", "offline": True},
                  ip=client_ip(request), company_id=kiosk.company_id)
        raise reject("QR de crachá inválido, regenerado ou de pessoa inativa") from None

    moment = body.occurred_at.astimezone(UTC).replace(tzinfo=None) if body.occurred_at.tzinfo else body.occurred_at
    if moment > now + timedelta(minutes=2):
        raise reject("A hora da batida está no futuro: o relógio do aparelho estava errado", user)
    if now - moment > timedelta(hours=settings.offline_max_hours):
        raise reject(f"Batida com mais de {settings.offline_max_hours} h: fora do prazo. Peça a inclusão por ajuste", user)
    if user.photo_consent_at is None:
        raise reject("A pessoa ainda não autorizou a foto (faça o consentimento no aplicativo ou na Central com internet)", user)
    try:
        data = photos.decode_jpeg(body.photo)
    except photos.PhotoError as e:
        raise reject(e.message, user) from None

    dist = None
    if body.latitude is not None and body.longitude is not None and kiosk.latitude is not None and kiosk.longitude is not None:
        dist = svc.distance_m(body.latitude, body.longitude, kiosk.latitude, kiosk.longitude)
    if db.execute(select(Punch.id).where(Punch.user_id == user.id, Punch.occurred_at > moment,
                                         or_(Punch.client_key.is_(None), Punch.client_key != body.client_key)).limit(1)).first():
        # o tipo é decidido pelo servidor pela ordem: com batida mais nova já registrada, a ordem não se decide sozinha
        raise reject("Já existe uma batida posterior a esta. Peça a inclusão por ajuste", user)
    try:
        p = register_punch(
            db, user, kind=None, occurred_at=moment, collector="04", offline=True, device_id=f"kiosk:{kiosk.id}",
            client_key=body.client_key, latitude=body.latitude, longitude=body.longitude, kiosk_id=kiosk.id, distance_m=dist,
            keep_location=True,
        )
        if not photos.exists(db, p):  # reenvio da mesma batida não duplica a foto
            photos.save(db, p, month_of(company, p.occurred_at), data)
        audit.log(db, user, "kiosk_punch", "punch", p.id, ip=client_ip(request),
                  after={"nsr": p.nsr, "kind": p.kind, "kiosk": kiosk.id, "distance_m": dist, "offline": True,
                         "device_time": body.device_time.isoformat() if body.device_time else None, "skew_ms": body.skew_ms,
                         "delay_s": int((p.recorded_at - p.occurred_at).total_seconds())})
        db.commit()
    except PunchError as e:
        raise reject(e.message, user) from None
    except photos.PhotoError as e:
        db.rollback()
        raise HTTPException(e.status, e.message) from None
    return {"nsr": p.nsr, "kind": p.kind, "label": KIND_LABEL[p.kind]}


# ============================ Administração dos aparelhos ============================
class KioskIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_m: int = Field(default=settings.kiosk_default_radius_m, ge=10, le=5000)


class KioskPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_m: int | None = Field(None, ge=10, le=5000)


def _out(k: Kiosk) -> dict:
    return {"id": k.id, "name": k.name, "latitude": k.latitude, "longitude": k.longitude, "radius_m": k.radius_m,
            "active": k.active, "paired": bool(k.token_hash), "last_seen_at": k.last_seen_at, "revoked_at": k.revoked_at,
            "pairing_pending": bool(k.pairing_hash and k.pairing_expires_at and k.pairing_expires_at > _now())}


def _new_pairing(k: Kiosk) -> str:
    code = "".join(secrets.choice(svc.PAIRING_ALPHABET) for _ in range(8))
    k.pairing_hash = svc.sha256(code)
    k.pairing_expires_at = _now() + timedelta(minutes=settings.kiosk_pairing_minutes)
    return code


def _own(db: Session, actor: User, kiosk_id: int) -> Kiosk:
    k = db.get(Kiosk, kiosk_id)
    if not k or k.company_id != actor.company_id:
        raise HTTPException(404, "Central não encontrada")
    return k


@router.post("/kiosks", status_code=201)
def create_kiosk(body: KioskIn, request: Request, actor: User = Depends(require("kiosks.manage")), db: Session = Depends(get_db)):
    active = db.execute(select(func.count()).select_from(Kiosk).where(Kiosk.company_id == actor.company_id, Kiosk.active.is_(True))).scalar_one()
    if active >= settings.kiosk_max_per_company:
        raise HTTPException(409, f"Limite de {settings.kiosk_max_per_company} centrais ativas. Revogue uma para cadastrar outra.")
    k = Kiosk(company_id=actor.company_id, name=body.name.strip(), latitude=body.latitude, longitude=body.longitude,
              radius_m=body.radius_m, created_by=actor.id)
    db.add(k)
    db.flush()
    code = _new_pairing(k)
    audit.log(db, actor, "create", "kiosk", k.id, after={"name": k.name, "radius_m": k.radius_m}, ip=client_ip(request))
    db.commit()
    return {**_out(k), "pairing_code": code, "pairing_expires_in": settings.kiosk_pairing_minutes * 60}


@router.get("/kiosks")
def list_kiosks(actor: User = Depends(require("kiosks.view")), db: Session = Depends(get_db)):
    company = db.get(Company, actor.company_id)
    zone = ZoneInfo(company.timezone)
    day = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    since = day.astimezone(UTC).replace(tzinfo=None)  # começo do dia local, em UTC
    rows = db.execute(select(Kiosk).where(Kiosk.company_id == actor.company_id).order_by(Kiosk.id)).scalars().all()
    counts = dict(db.execute(select(Punch.kiosk_id, func.count()).where(
        Punch.company_id == actor.company_id, Punch.kiosk_id.is_not(None), Punch.occurred_at >= since).group_by(Punch.kiosk_id)).all())
    return [{**_out(k), "punches_today": counts.get(k.id, 0)} for k in rows]


@router.patch("/kiosks/{kiosk_id}")
def patch_kiosk(kiosk_id: int, body: KioskPatch, request: Request, actor: User = Depends(require("kiosks.manage")),
                db: Session = Depends(get_db)):
    k = _own(db, actor, kiosk_id)
    data = body.model_dump(exclude_unset=True)
    before = {key: getattr(k, key) for key in data}
    for key, value in data.items():
        setattr(k, key, value)
    audit.log(db, actor, "update", "kiosk", k.id, before=before, after=data, ip=client_ip(request))
    db.commit()
    return _out(k)


@router.delete("/kiosks/{kiosk_id}", status_code=204)
def delete_kiosk(kiosk_id: int, request: Request, actor: User = Depends(require("kiosks.manage")), db: Session = Depends(get_db)):
    """Remove da lista uma central JÁ REVOGADA. As batidas feitas nela continuam (aparecem como "Central <número>")."""
    k = _own(db, actor, kiosk_id)
    if k.active:
        raise HTTPException(409, "Revogue a central antes de excluí-la")
    n = db.execute(select(func.count()).select_from(Punch).where(Punch.kiosk_id == k.id)).scalar_one()
    db.query(KioskTicket).filter(KioskTicket.kiosk_id == k.id).delete()
    audit.log(db, actor, "delete", "kiosk", k.id, before={"name": k.name}, after={"punches_kept": n}, ip=client_ip(request))
    db.delete(k)
    db.commit()
    return Response(status_code=204)


@router.post("/kiosks/{kiosk_id}/pairing")
def repair_kiosk(kiosk_id: int, request: Request, actor: User = Depends(require("kiosks.manage")), db: Session = Depends(get_db)):
    """Novo código de pareamento: o aparelho atual perde o acesso (útil se o tablet for trocado)."""
    k = _own(db, actor, kiosk_id)
    if not k.active:
        raise HTTPException(409, "Esta central foi revogada")
    k.token_hash = None
    code = _new_pairing(k)
    audit.log(db, actor, "repair", "kiosk", k.id, ip=client_ip(request))
    db.commit()
    return {**_out(k), "pairing_code": code, "pairing_expires_in": settings.kiosk_pairing_minutes * 60}


@router.post("/kiosks/{kiosk_id}/revoke")
def revoke_kiosk(kiosk_id: int, request: Request, actor: User = Depends(require("kiosks.manage")), db: Session = Depends(get_db)):
    k = _own(db, actor, kiosk_id)
    k.active, k.token_hash, k.pairing_hash, k.pairing_expires_at, k.revoked_at = False, None, None, None, _now()
    audit.log(db, actor, "revoke", "kiosk", k.id, ip=client_ip(request))
    db.commit()
    return _out(k)


# ============================ Pessoas: código, PIN e crachá ============================
def _target(db: Session, actor: User, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u or u.company_id != actor.company_id:
        raise HTTPException(404, "Usuário não encontrado")
    if perm.is_privileged(u) and not perm.can(actor, "people.permissions"):
        raise HTTPException(403, "Somente a Administração altera quem tem função de gestão")
    if not u.tracks_time:
        raise HTTPException(422, "Esta pessoa não registra ponto: não tem crachá nem PIN")
    return u


@router.get("/users/{user_id}/badge")
def user_badge(user_id: int, actor: User = Depends(require("badges.manage")), db: Session = Depends(get_db)):
    """Código interno e conteúdo do QR do crachá impresso (o PDF/impressão vem na tela de Gestão)."""
    u = _target(db, actor, user_id)
    code = svc.assign_code(db, u)
    db.commit()
    return {"user_id": u.id, "name": u.name, "employee_code": code, "qr": svc.static_badge(u), "has_pin": u.has_pin}


def _badge_person(db: Session, u: User) -> dict:
    return {"name": u.name, "job_title": u.job_title, "code": svc.assign_code(db, u), "qr": svc.static_badge(u)}


@router.get("/users/{user_id}/badge.pdf")
def user_badge_pdf(user_id: int, request: Request, actor: User = Depends(require("badges.manage")),
                   db: Session = Depends(get_db)):
    u = _target(db, actor, user_id)
    company = db.get(Company, actor.company_id)
    data = badges.badges_pdf(company.name, [_badge_person(db, u)])
    audit.log(db, actor, "badge_print", "user", u.id, ip=client_ip(request))
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="cracha.pdf"'})


@router.get("/badges.pdf")
def all_badges_pdf(request: Request, ids: list[int] | None = Query(None), actor: User = Depends(require("badges.manage")),
                   db: Session = Depends(get_db)):
    """Crachás de várias pessoas de uma vez (todas as ativas, ou as de `ids`). RH não imprime os de RH, admin e auditor."""
    q = select(User).where(User.company_id == actor.company_id, User.active.is_(True), User.tracks_time.is_(True)).order_by(User.name)
    if ids:
        q = q.where(User.id.in_(ids))
    people = [u for u in db.execute(q).scalars() if not perm.is_privileged(u) or perm.can(actor, "people.permissions")]
    company = db.get(Company, actor.company_id)
    data = badges.badges_pdf(company.name, [_badge_person(db, u) for u in people])
    audit.log(db, actor, "badge_print", "user", "lote", after={"count": len(people)}, ip=client_ip(request))
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="crachas.pdf"'})


@router.post("/users/{user_id}/badge/regenerate")
def regenerate(user_id: int, request: Request, actor: User = Depends(require("badges.manage")), db: Session = Depends(get_db)):
    u = _target(db, actor, user_id)
    svc.regenerate_badge(u)
    audit.log(db, actor, "badge_regenerate", "user", u.id, ip=client_ip(request))
    db.commit()
    return {"user_id": u.id, "qr": svc.static_badge(u)}


@router.post("/users/{user_id}/pin-reset")
def pin_reset(user_id: int, request: Request, actor: User = Depends(require("badges.manage")), db: Session = Depends(get_db)):
    u = _target(db, actor, user_id)
    u.pin_hash, u.pin_set_at, u.pin_fails, u.pin_locked_until = None, None, 0, None
    audit.log(db, actor, "pin_reset", "user", u.id, ip=client_ip(request))
    db.commit()
    return {"user_id": u.id, "has_pin": False}


@router.get("/auth/badge")
def my_badge(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Meu código interno e se tenho PIN. O código não é segredo por si só quando a empresa não exige PIN: trate como senha."""
    require_punch(user)
    code = svc.assign_code(db, user)
    db.commit()
    company = db.get(Company, user.company_id)
    return {"employee_code": code, "has_pin": user.has_pin, "pin_required": bool(company.kiosk_pin_required)}


@router.get("/auth/badge-qr")
def my_rotating_badge(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """QR do aplicativo: muda a cada 30 s e vale uma única vez por janela."""
    require_punch(user)
    svc.assign_code(db, user)
    payload, expires_in = svc.rotating_badge(user)
    db.commit()
    return {"qr": payload, "expires_in": expires_in, "image": segno.make(payload, error="m", micro=False).svg_data_uri(scale=8, border=4)}


class PinIn(BaseModel):
    password: str | None = None  # exigida para quem entrou com senha
    pin: str = Field(min_length=4, max_length=6)


@router.post("/auth/pin")
def set_my_pin(body: PinIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Define ou troca o PIN. Pede a senha atual (quem pegar a sessão aberta não consegue trocar o PIN); para quem entrou pelo
    Google, que não tem senha do app, vale ter entrado há pouco (até 15 minutos)."""
    require_punch(user)
    if getattr(request.state, "amr", "pwd") == "google":
        if time.time() - getattr(request.state, "token_iat", 0) > 15 * 60:
            raise HTTPException(403, {"code": "reauth_required", "message": "Por segurança, saia e entre de novo com o Google para trocar o PIN."})
    elif not verify_password(body.password or "", user.password_hash):
        raise HTTPException(403, "Senha atual incorreta")
    try:
        svc.set_pin(user, body.pin, _now())
    except svc.KioskError as e:
        raise HTTPException(e.status, e.message) from None
    audit.log(db, user, "pin_set", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"has_pin": True}



