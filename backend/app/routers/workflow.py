"""Ajustes com aprovação, fechamento mensal e consulta da trilha de auditoria."""
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..db import get_db
from ..deps import authorize_decision, client_ip, get_current_user, require, require_punch
from ..models import Absence, Adjustment, AuditLog, Closing, Company, Kiosk, Punch, User
from ..schemas import AdjustmentIn, AdjustmentOut, DecisionIn
from ..services import absences as absence_svc
from ..services import audit, photos
from ..services.mirror import ABSENCE_LABEL, month_days, summarize
from ..services.punching import ALL_KINDS, KIND_LABEL, month_is_closed, month_of

router = APIRouter(tags=["fluxo"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _adjustment_month(db: Session, company: Company, adj: Adjustment) -> str:
    if adj.kind == "incluir":
        return month_of(company, adj.requested_at)
    return month_of(company, db.get(Punch, adj.target_punch_id).occurred_at)


# --- Ajustes -----------------------------------------------------------------
@router.post("/adjustments", response_model=AdjustmentOut, status_code=201)
def create_adjustment(
    body: AdjustmentIn, request: Request, actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_user = actor
    if body.user_id and body.user_id != actor.id:
        target_user = db.get(User, body.user_id)
        if not target_user or not perm.can(actor, "approvals") or not perm.in_scope(actor, target_user):
            raise HTTPException(403, "Sem permissão para abrir ajuste para este colaborador")
    require_punch(target_user)
    company = db.get(Company, actor.company_id)

    if body.kind == "incluir":
        if body.requested_at is None or body.punch_kind not in ALL_KINDS:
            raise HTTPException(422, "Informe requested_at e punch_kind válidos")
        when = body.requested_at
        if when.tzinfo is not None:
            when = when.astimezone(UTC).replace(tzinfo=None)
        if when > _now():
            raise HTTPException(422, "Não é possível incluir marcação no futuro")
        body.requested_at = when
        month = month_of(company, when)
    elif body.kind == "desconsiderar":
        target = db.get(Punch, body.target_punch_id) if body.target_punch_id else None
        if not target or target.user_id != target_user.id:
            raise HTTPException(422, "Marcação alvo inválida")
        month = month_of(company, target.occurred_at)
    else:
        raise HTTPException(422, "Tipo de ajuste inválido")

    if month_is_closed(db, company.id, month):
        raise HTTPException(409, "O mês do ajuste está fechado")

    # Tratamento direto: quem pode decidir os pedidos desta pessoa corrige o ponto dela por conta própria (Gestão > Tratamento).
    # A marcação original nunca muda; o ajuste nasce aprovado, com o motivo, e entra no AEJ como qualquer tratamento.
    direct = target_user.id != actor.id and perm.can_approve(actor, target_user)
    if body.kind == "desconsiderar" and _voided_by(db, body.target_punch_id):
        raise HTTPException(409, "Esta marcação já está desconsiderada")
    adj = Adjustment(
        company_id=company.id, user_id=target_user.id, kind=body.kind, requested_at=body.requested_at,
        punch_kind=body.punch_kind, target_punch_id=body.target_punch_id, reason=body.reason,
        attachment_name=body.attachment_name,
    )
    if direct:
        adj.status, adj.decided_by, adj.decided_at = "approved", actor.id, _now()
    db.add(adj)
    db.flush()
    audit.log(db, actor, "treat" if direct else "create", "adjustment", adj.id,
              after={"kind": adj.kind, "user_id": adj.user_id, "status": adj.status, "reason": adj.reason if direct else None},
              ip=client_ip(request))
    db.commit()
    return adj


@router.get("/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    status: str | None = None, mine: bool = False, actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Adjustment).where(Adjustment.company_id == actor.company_id)
    if mine or not perm.can(actor, "team.view"):
        q = q.where(Adjustment.user_id == actor.id)
    else:
        q = q.where(Adjustment.user_id.in_(select(User.id).where(perm.scope_condition(actor))))
    if status:
        q = q.where(Adjustment.status == status)
    rows = db.execute(q.order_by(Adjustment.id.desc())).scalars().all()
    names = {u.id: u.name for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    targets = {p.id: p for p in db.execute(
        select(Punch).where(Punch.id.in_([a.target_punch_id for a in rows if a.target_punch_id]))).scalars()} if rows else {}
    owners = {u.id: u for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    out = []
    for a in rows:
        item = AdjustmentOut.model_validate(a)
        item.user_name = names.get(a.user_id)
        if a.status == "pending":
            mode = perm.decision_mode(db, actor, owners[a.user_id])
            item.can_decide, item.self_decision = mode is not None, mode == "self"
        t = targets.get(a.target_punch_id)
        if t:
            item.target_kind, item.target_at = t.kind, t.occurred_at
        out.append(item)
    return out


@router.post("/adjustments/{adj_id}/decision", response_model=AdjustmentOut)
def decide(
    adj_id: int, body: DecisionIn, request: Request, actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    adj = db.get(Adjustment, adj_id)
    if not adj or adj.company_id != actor.company_id:
        raise HTTPException(404, "Ajuste não encontrado")
    owner = db.get(User, adj.user_id)
    own = authorize_decision(db, actor, owner, body.note, "ajuste")
    if adj.status != "pending":
        raise HTTPException(409, "Ajuste já decidido")

    company = db.get(Company, adj.company_id)
    if body.approve:
        if month_is_closed(db, company.id, _adjustment_month(db, company, adj)):
            raise HTTPException(409, "O mês do ajuste está fechado")
        if adj.kind == "incluir":
            pass  # a inclusão é tratamento (AEJ, fonte "I"): não cria registro no ARP nem consome NSR
        else:
            already = db.execute(
                select(Adjustment.id).where(
                    Adjustment.kind == "desconsiderar", Adjustment.status == "approved",
                    Adjustment.target_punch_id == adj.target_punch_id,
                )
            ).first()
            if already:
                raise HTTPException(409, "Marcação já desconsiderada")
    adj.status = "approved" if body.approve else "rejected"
    adj.decided_by, adj.decided_at, adj.decision_note = actor.id, _now(), body.note
    audit.log(db, actor, ("self_" if own else "") + ("approve" if body.approve else "reject"), "adjustment", adj.id,
              before={"status": "pending"}, after={"status": adj.status, "note": body.note, "self_approval": own},
              ip=client_ip(request))
    db.commit()
    return adj


def _voided_by(db: Session, punch_id: int | None) -> Adjustment | None:
    if not punch_id:
        return None
    return db.execute(select(Adjustment).where(
        Adjustment.kind == "desconsiderar", Adjustment.status == "approved", Adjustment.target_punch_id == punch_id)).scalars().first()


@router.post("/adjustments/{adj_id}/revoke", response_model=AdjustmentOut)
def revoke_adjustment(adj_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Desfaz um tratamento aprovado (inclusão ou desconsideração) enquanto o mês estiver aberto. Fica na auditoria."""
    adj = db.get(Adjustment, adj_id)
    if not adj or adj.company_id != actor.company_id:
        raise HTTPException(404, "Ajuste não encontrado")
    owner = db.get(User, adj.user_id)
    if not perm.can_approve(actor, owner):
        raise HTTPException(403, "Sem permissão para desfazer este ajuste")
    if adj.status != "approved":
        raise HTTPException(409, "Só um ajuste aprovado pode ser desfeito")
    company = db.get(Company, adj.company_id)
    if month_is_closed(db, company.id, _adjustment_month(db, company, adj)):
        raise HTTPException(409, "O mês do ajuste está fechado")
    adj.status = "revoked"
    audit.log(db, actor, "revoke", "adjustment", adj.id, before={"status": "approved"}, after={"status": "revoked"}, ip=client_ip(request))
    db.commit()
    return adj


# --- Tratamento mensal ---------------------------------------------------------
@router.get("/treatment")
def treatment(month: str, user_id: int, actor: User = Depends(require("team.view")), db: Session = Depends(get_db)):
    """O mês de uma pessoa, dia a dia, para a gestão tratar o ponto: cada marcação original (e se está desconsiderada),
    as inclusões, os pedidos pendentes e as ausências, além do cálculo do espelho."""
    _valid_month(month)
    target = db.get(User, user_id)
    if not target or target.id == actor.id or not perm.in_scope(actor, target) or not target.tracks_time:
        raise HTTPException(404, "Colaborador não encontrado")
    company = db.get(Company, target.company_id)
    year, mon = int(month[:4]), int(month[5:])
    zone = ZoneInfo(company.timezone)
    lo = datetime(year, mon, 1) - timedelta(days=1)
    hi = datetime(year + (mon == 12), mon % 12 + 1, 1) + timedelta(days=1)

    def local_day(at: datetime) -> str:
        return at.replace(tzinfo=UTC).astimezone(zone).date().isoformat()

    adjs = db.execute(select(Adjustment).where(Adjustment.user_id == target.id)).scalars().all()
    voids = {a.target_punch_id: a for a in adjs if a.kind == "desconsiderar" and a.status == "approved"}
    names = {u.id: u.name for u in db.execute(select(User).where(User.company_id == company.id)).scalars()}
    kiosks = {k.id: k.name for k in db.execute(select(Kiosk).where(Kiosk.company_id == company.id)).scalars()}
    punches = db.execute(select(Punch).where(Punch.user_id == target.id, Punch.occurred_at >= lo, Punch.occurred_at < hi)
                         .order_by(Punch.occurred_at)).scalars().all()
    by_id = {p.id: p for p in punches}
    marks: dict[str, list] = {}
    for p in punches:
        v = voids.get(p.id)
        marks.setdefault(local_day(p.occurred_at), []).append({
            "type": "original", "punch_id": p.id, "nsr": p.nsr, "at": p.occurred_at, "kind": p.kind, "label": KIND_LABEL[p.kind],
            "origin": f"Central {kiosks.get(p.kiosk_id, '')}".strip() if p.kiosk_id else "Aplicativo", "offline": p.offline,
            "voided": v is not None, "adjustment_id": v.id if v else None, "note": v.reason if v else None,
            "by": names.get(v.decided_by) if v else None})
    pending: dict[str, list] = {}
    for a in adjs:
        at = a.requested_at if a.kind == "incluir" else (by_id[a.target_punch_id].occurred_at if a.target_punch_id in by_id else None)
        if at is None or not (lo <= at < hi):
            continue
        if a.kind == "incluir" and a.status == "approved":
            marks.setdefault(local_day(at), []).append({
                "type": "inclusao", "adjustment_id": a.id, "at": at, "kind": a.punch_kind, "label": KIND_LABEL.get(a.punch_kind, ""),
                "note": a.reason, "by": names.get(a.decided_by)})
        elif a.status == "pending":
            pending.setdefault(local_day(at), []).append({
                "adjustment_id": a.id, "kind": a.kind, "at": at, "label": KIND_LABEL.get(a.punch_kind or (by_id[a.target_punch_id].kind
                                                                                               if a.target_punch_id in by_id else ""), ""),
                "reason": a.reason})
    for day in marks.values():
        day.sort(key=lambda m: m["at"])

    absences: dict[str, list] = {}
    first, last = datetime(year, mon, 1).date(), (hi - timedelta(days=2)).date()
    for a in db.execute(select(Absence).where(Absence.user_id == target.id, Absence.status.in_(("approved", "pending")),
                                              Absence.start_date <= last, Absence.end_date >= first)).scalars():
        d = max(a.start_date, first)
        while d <= min(a.end_date, last):
            absences.setdefault(d.isoformat(), []).append({"absence_id": a.id, "label": ABSENCE_LABEL[a.kind], "status": a.status,
                                                           "minutes": a.minutes})
            d += timedelta(days=1)

    summary = summarize(month_days(db, target, company, year, mon))
    for d in summary["days"]:
        d["marks"], d["pending"], d["absences"] = marks.get(d["date"], []), pending.get(d["date"], []), absences.get(d["date"], [])
    return {
        "user": {"id": target.id, "name": target.name, "job_title": target.job_title},
        "month": month, "closed": month_is_closed(db, company.id, month),
        "can_treat": perm.can_approve(actor, target), "can_justify": perm.can(actor, "absences.register"),
        **summary,
    }


# --- Fechamento mensal -------------------------------------------------------
def _valid_month(month: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês deve estar no formato YYYY-MM")
    return month


@router.get("/closings")
def list_closings(actor: User = Depends(require("closing.view")), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Closing).where(Closing.company_id == actor.company_id).order_by(Closing.month.desc())
    ).scalars()
    return [{"month": c.month, "status": c.status, "closed_at": c.closed_at} for c in rows]


@router.post("/closings/{month}")
def close_month(
    month: str, request: Request, actor: User = Depends(require("closing.manage")),
    db: Session = Depends(get_db),
):
    _valid_month(month)
    company = db.get(Company, actor.company_id)
    current = datetime.now(ZoneInfo(company.timezone)).strftime("%Y-%m")
    if month >= current:
        raise HTTPException(409, "Só é possível fechar meses já encerrados")
    pending = [
        a for a in db.execute(
            select(Adjustment).where(Adjustment.company_id == company.id, Adjustment.status == "pending")
        ).scalars()
        if _adjustment_month(db, company, a) == month
    ]
    if pending:
        raise HTTPException(409, f"Há {len(pending)} ajuste(s) pendente(s) neste mês")
    pending_absences = [
        a for a in db.execute(
            select(Absence).where(Absence.company_id == company.id, Absence.status == "pending")
        ).scalars()
        if month in absence_svc.months_of(a.start_date, a.end_date)
    ]
    if pending_absences:
        raise HTTPException(409, f"Há {len(pending_absences)} ausência(s) pendente(s) neste mês")
    row = db.execute(select(Closing).where(Closing.company_id == company.id, Closing.month == month)).scalar_one_or_none()
    if row and row.status == "closed":
        raise HTTPException(409, "Mês já está fechado")
    if row is None:
        row = Closing(company_id=company.id, month=month)
        db.add(row)
    row.status, row.closed_by, row.closed_at = "closed", actor.id, _now()
    audit.log(db, actor, "close", "closing", month, after={"status": "closed"}, ip=client_ip(request))
    db.flush()
    try:
        purged, pending = photos.purge_closed(db, company.id)  # retenção: as fotos do mês não ficam depois do fechamento
    except photos.PhotoError:
        purged, pending = 0, -1  # armazenamento indisponível: o fechamento vale; a varredura seguinte apaga
    if purged or pending:
        audit.log(db, actor, "purge_photos", "closing", month, after={"photos": purged, "pending": pending}, ip=client_ip(request))
    db.commit()
    return {"month": month, "status": "closed", "photos_deleted": purged, "photos_pending": max(pending, 0)}


@router.post("/closings/{month}/reopen")
def reopen_month(
    month: str, request: Request, actor: User = Depends(require("closing.manage")),
    db: Session = Depends(get_db),
):
    _valid_month(month)
    row = db.execute(
        select(Closing).where(Closing.company_id == actor.company_id, Closing.month == month)
    ).scalar_one_or_none()
    if not row or row.status != "closed":
        raise HTTPException(409, "Mês não está fechado")
    row.status = "open"
    audit.log(db, actor, "reopen", "closing", month, before={"status": "closed"}, after={"status": "open"},
              ip=client_ip(request))
    db.commit()
    return {"month": month, "status": "open"}


# --- Auditoria ---------------------------------------------------------------
@router.get("/audit")
def audit_trail(
    entity: str | None = None, limit: int = Query(100, le=500),
    actor: User = Depends(require("audit.view")), db: Session = Depends(get_db),
):
    q = select(AuditLog).where(AuditLog.company_id == actor.company_id)
    if entity:
        q = q.where(AuditLog.entity == entity)
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(limit)).scalars()
    return [
        {"id": r.id, "at": r.at, "actor_id": r.actor_id, "action": r.action, "entity": r.entity,
         "entity_id": r.entity_id, "before": r.before, "after": r.after, "ip": r.ip}
        for r in rows
    ]
