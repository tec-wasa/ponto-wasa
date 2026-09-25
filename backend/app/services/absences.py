"""Ausências justificadas (RF-13): regras de quem pode pedir/registrar/aprovar e como se visualizam."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Absence, Company, User
from .mirror import ABSENCE_LABEL
from .punching import month_is_closed

# O que o próprio colaborador pode pedir (depois aprovado pelo gestor ou pelo RH).
EMPLOYEE_KINDS = ("atestado_medico", "abono")
# Só o RH/admin registra (já entram aprovados): dependem de documento e de regra da empresa.
HR_ONLY_KINDS = ("ferias", "licenca", "afastamento_inss")
ALL_KINDS = EMPLOYEE_KINDS + HR_ONLY_KINDS
# Podem ser parciais (em minutos, num único dia): consulta, comparecimento, saída antecipada.
PARTIAL_KINDS = ("atestado_medico", "abono")
# Dado de saúde (LGPD, art. 11): o motivo e o anexo só o dono e o RH veem; o gestor vê que existe e o período.
SENSITIVE_KINDS = ("atestado_medico", "afastamento_inss")

MAX_DAYS = 366
EMPLOYEE_LOOKBACK_DAYS = 90  # o colaborador não abre pedido de mais de 90 dias atrás


def months_of(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def touches_closed_month(db: Session, company: Company, start: date, end: date) -> str | None:
    """Primeiro mês fechado que o período atinge, se houver."""
    for month in months_of(start, end):
        if month_is_closed(db, company.id, month):
            return month
    return None


def overlapping(db: Session, user_id: int, start: date, end: date, exclude_id: int | None = None) -> list[Absence]:
    q = select(Absence).where(
        Absence.user_id == user_id, Absence.status.in_(("pending", "approved")),
        Absence.start_date <= end, Absence.end_date >= start,
    )
    if exclude_id:
        q = q.where(Absence.id != exclude_id)
    return list(db.execute(q).scalars())


def validate_period(kind: str, start: date, end: date, minutes: int | None) -> str | None:
    if kind not in ALL_KINDS:
        return "Tipo de ausência inválido"
    if end < start:
        return "A data final é anterior à inicial"
    if (end - start).days + 1 > MAX_DAYS:
        return f"O período não pode passar de {MAX_DAYS} dias"
    if minutes is not None:
        if kind not in PARTIAL_KINDS:
            return "Só atestado e abono podem ser parciais (em horas)"
        if start != end:
            return "Ausência parcial vale para um único dia"
        if not 1 <= minutes <= 12 * 60:
            return "Informe de 1 minuto a 12 horas"
    return None


def can_view_detail(actor: User, absence: Absence) -> bool:
    """Motivo e anexo de dado sensível: o dono e o RH/admin. Gestor e demais só veem o fato e o período."""
    if absence.kind not in SENSITIVE_KINDS:
        return True
    return actor.id == absence.user_id or actor.role in ("hr", "admin")


def serialize(actor: User, a: Absence, owner_name: str | None = None) -> dict:
    detail = can_view_detail(actor, a)
    return {
        "id": a.id, "user_id": a.user_id, "user_name": owner_name, "kind": a.kind, "kind_label": ABSENCE_LABEL[a.kind],
        "start_date": a.start_date.isoformat(), "end_date": a.end_date.isoformat(), "minutes": a.minutes,
        "reason": a.reason if detail else None, "attachment_name": a.attachment_name if detail else None,
        "restricted": not detail, "status": a.status, "decided_by": a.decided_by, "decision_note": a.decision_note,
        "created_by": a.created_by,
    }


def days_between(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
