from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import MANAGEMENT_ROLES, client_ip, get_current_user, require_roles
from ..models import Closing, Company, Punch, Schedule, User
from ..schemas import (
    ROLES,
    CompanyOut,
    CompanyPatch,
    ScheduleIn,
    ScheduleOut,
    SchedulePatch,
    UserIn,
    UserOut,
    UserPatch,
)
from ..security import hash_password
from ..services import arp, audit, csv_import, passwords
from ..services import kiosk as kiosk_svc

router = APIRouter(tags=["cadastros"])

PRIVILEGED = ("hr", "admin")


def _check_role_change(actor: User, role: str) -> None:
    if role not in ROLES:
        raise HTTPException(422, "Perfil inválido")
    if role in PRIVILEGED + ("auditor",) and actor.role != "admin":
        raise HTTPException(403, "Somente o administrador atribui este perfil")


def _same_company(db: Session, actor: User, model, obj_id: int | None, label: str):
    if obj_id is None:
        return None
    obj = db.get(model, obj_id)
    if obj is None or obj.company_id != actor.company_id:
        raise HTTPException(422, f"{label} inválido")
    return obj


# --- Empresa -----------------------------------------------------------------
@router.get("/company", response_model=CompanyOut)
def get_company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.get(Company, user.company_id)


@router.patch("/company", response_model=CompanyOut)
def patch_company(
    body: CompanyPatch, request: Request, actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    company = db.get(Company, actor.company_id)
    before = {"name": company.name, "caepf": company.caepf, "cno": company.cno,
              "timezone": company.timezone, "workplace": company.workplace, "photo_enabled": company.photo_enabled,
              "kiosk_pin_required": company.kiosk_pin_required}
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(company, k, v)
    if set(data) & {"name", "caepf", "cno", "workplace"}:
        arp.record_employer(db, company, actor)  # tipo 2: alteração da identificação do empregador
    audit.log(db, actor, "update", "company", company.id, before=before, after=data, ip=client_ip(request))
    db.commit()
    return company


# --- Usuários ----------------------------------------------------------------
@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserIn, request: Request, actor: User = Depends(require_roles(*MANAGEMENT_ROLES)),
    db: Session = Depends(get_db),
):
    _check_role_change(actor, body.role)
    _same_company(db, actor, User, body.manager_id, "Gestor")
    _same_company(db, actor, Schedule, body.schedule_id, "Jornada")
    if db.execute(select(User.id).where(User.company_id == actor.company_id, User.cpf == body.cpf)).first():
        raise HTTPException(409, "CPF já cadastrado nesta empresa")
    user = User(
        company_id=actor.company_id, name=body.name, email=body.email.lower(), cpf=body.cpf,
        password_hash=hash_password(body.password), role=body.role,
        manager_id=body.manager_id, schedule_id=body.schedule_id, admitted_at=body.admitted_at,
        job_title=body.job_title, must_change_password=body.must_change_password,
    )
    db.add(user)
    kiosk_svc.assign_code(db, user)  # código interno para a Central
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail já cadastrado") from None
    arp.record_employee(db, db.get(Company, actor.company_id), "I", user, actor)  # tipo 5: inclusão
    audit.log(db, actor, "create", "user", user.id, after={"email": user.email, "role": user.role},
              ip=client_ip(request))
    db.commit()
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(actor: User = Depends(require_roles("manager", "hr", "admin", "auditor")), db: Session = Depends(get_db)):
    q = select(User).where(User.company_id == actor.company_id).order_by(User.name)
    if actor.role == "manager":
        q = q.where(User.manager_id == actor.id)
    return db.execute(q).scalars().all()


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int, body: UserPatch, request: Request,
    actor: User = Depends(require_roles(*MANAGEMENT_ROLES)), db: Session = Depends(get_db),
):
    user = _same_company(db, actor, User, user_id, "Usuário")
    data = body.model_dump(exclude_unset=True)
    if "role" in data:
        _check_role_change(actor, data["role"])
    if user.role in PRIVILEGED and actor.role != "admin":
        raise HTTPException(403, "Somente o administrador altera este usuário")
    if "manager_id" in data:
        _same_company(db, actor, User, data["manager_id"], "Gestor")
    if "schedule_id" in data:
        _same_company(db, actor, Schedule, data["schedule_id"], "Jornada")
        if data["schedule_id"] != user.schedule_id:
            month = _closed_month_with_punches(db, user.company_id, [user.id])
            if month:
                raise HTTPException(409, f"Não é possível trocar a jornada: o mês {month} está fechado e tem marcações desta pessoa. "
                                         "Reabra o mês (RH ou administrador) antes de trocar.")
    before = {k: getattr(user, k) for k in data}
    for k, v in data.items():
        setattr(user, k, v)
    company = db.get(Company, actor.company_id)
    if data.get("hour_bank_enabled") and not user.hour_bank_start:
        user.hour_bank_start = datetime.now(ZoneInfo(company.timezone)).date()  # o saldo passa a contar a partir de hoje
        data["hour_bank_start"] = user.hour_bank_start
    if "active" in data and before["active"] != data["active"]:
        arp.record_employee(db, company, "I" if data["active"] else "E", user, actor)  # tipo 5: inclusão/exclusão
    elif "name" in data and before["name"] != data["name"]:
        arp.record_employee(db, company, "A", user, actor)  # tipo 5: alteração
    audit.log(db, actor, "update", "user", user.id, before=before, after=data, ip=client_ip(request))
    db.commit()
    return user


# --- Jornadas ----------------------------------------------------------------
@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(
    body: ScheduleIn, request: Request, actor: User = Depends(require_roles(*MANAGEMENT_ROLES)),
    db: Session = Depends(get_db),
):
    if any(d < 0 or d > 6 for d in body.weekdays):
        raise HTTPException(422, "Dias da semana devem estar entre 0 (segunda) e 6 (domingo)")
    if body.break_minutes > 0 and not body.crosses_midnight and body.break_start <= body.start_time:
        raise HTTPException(422, "O início do intervalo deve ser posterior ao início da jornada")
    sched = Schedule(
        company_id=actor.company_id, name=body.name, start_time=body.start_time, break_start=body.break_start,
        weekdays=",".join(str(d) for d in sorted(set(body.weekdays))),
        daily_minutes=body.daily_minutes, break_minutes=body.break_minutes,
        tolerance_minutes=body.tolerance_minutes, crosses_midnight=body.crosses_midnight,
    )
    db.add(sched)
    db.flush()
    audit.log(db, actor, "create", "schedule", sched.id, after=body.model_dump(), ip=client_ip(request))
    db.commit()
    return sched


def _closed_month_with_punches(db: Session, company_id: int, user_ids: list[int]) -> str | None:
    """Primeiro mês FECHADO que tem marcações de alguma dessas pessoas: mudar a jornada ou a regra dela recalcularia um mês
    já apurado (o Espelho é calculado das marcações e da jornada vigente)."""
    company = db.get(Company, company_id)
    zone = ZoneInfo(company.timezone)
    if not user_ids:
        return None
    for closing in db.execute(select(Closing).where(Closing.company_id == company_id, Closing.status == "closed")
                              .order_by(Closing.month)).scalars():
        y, m = int(closing.month[:4]), int(closing.month[5:])
        lo = datetime(y, m, 1, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
        hi = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
        if db.execute(select(Punch.id).where(Punch.user_id.in_(user_ids), Punch.occurred_at >= lo, Punch.occurred_at < hi).limit(1)).first():
            return closing.month
    return None


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def patch_schedule(
    schedule_id: int, body: SchedulePatch, request: Request, actor: User = Depends(require_roles(*MANAGEMENT_ROLES)),
    db: Session = Depends(get_db),
):
    """Liga/desliga "a jornada pode terminar no dia seguinte". O Espelho é calculado a partir das marcações, então a mudança
    vale também para dias já passados: fica na auditoria, com o antes e o depois."""
    sched = db.get(Schedule, schedule_id)
    if not sched or sched.company_id != actor.company_id:
        raise HTTPException(404, "Jornada não encontrada")
    if not body.crosses_midnight and sched.break_minutes > 0 and sched.break_start <= sched.start_time:
        raise HTTPException(422, "O início do intervalo é anterior ao início da jornada: só faz sentido em turno que vira a meia-noite")
    if sched.crosses_midnight != body.crosses_midnight:
        month = _closed_month_with_punches(
            db, sched.company_id, list(db.execute(select(User.id).where(User.schedule_id == sched.id)).scalars()))
        if month:
            raise HTTPException(409, f"Não é possível alterar: o mês {month} está fechado e tem marcações de pessoas desta jornada. "
                                     "Reabra o mês (RH ou administrador) antes de mudar a opção.")
        before = {"crosses_midnight": sched.crosses_midnight}
        sched.crosses_midnight = body.crosses_midnight
        audit.log(db, actor, "update", "schedule", sched.id, before=before, after={"crosses_midnight": body.crosses_midnight},
                  ip=client_ip(request))
        db.commit()
    return sched


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(select(Schedule).where(Schedule.company_id == actor.company_id)).scalars().all()


# --- Importação em lote e recuperação de acesso ---------------------------------------------------
class ImportIn(BaseModel):
    content_base64: str = Field(max_length=int(csv_import.MAX_BYTES * 1.4))


@router.get("/users/import/template")
def import_template(actor: User = Depends(require_roles(*MANAGEMENT_ROLES))):
    """Modelo do CSV (separador ';', UTF-8), com uma linha de exemplo."""
    return Response(csv_import.TEMPLATE.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="modelo-colaboradores.csv"'})


@router.post("/users/import")
def import_users(
    body: ImportIn, request: Request, dry_run: bool = True,
    actor: User = Depends(require_roles(*MANAGEMENT_ROLES)), db: Session = Depends(get_db),
):
    """Importa colaboradores de um CSV. Por padrão só **valida** (`dry_run=true`); com `dry_run=false` grava tudo ou nada.

    Cada usuário nasce com uma senha temporária (mostrada só na resposta) e troca obrigatória no primeiro acesso.
    """
    allowed = ("employee", "manager") if actor.role == "hr" else ("employee", "manager", "hr", "admin", "auditor")
    try:
        text = csv_import.decode_payload(body.content_base64)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    result = csv_import.parse(db, actor.company_id, text, allowed)
    errors = [{"line": e.line, "field": e.field, "message": e.message} for e in result.errors]
    preview = [{"line": r.line, "name": r.name, "email": r.email, "role": r.role, "manager": r.manager_email} for r in result.rows]
    payload = {"dry_run": dry_run, "total": result.total, "valid": len(result.rows), "errors": errors, "preview": preview,
               "imported": False, "created": 0, "credentials": []}
    if dry_run:
        return payload
    if errors or not result.rows:  # tudo ou nada: com qualquer erro, nada é gravado
        return JSONResponse(payload, status_code=422)

    company = db.get(Company, actor.company_id)
    created: dict[str, User] = {}
    credentials = []
    for r in result.rows:
        temp = passwords.generate_temp()
        user = User(
            company_id=actor.company_id, name=r.name, email=r.email, cpf=r.cpf, role=r.role, job_title=r.job_title,
            schedule_id=r.schedule_id, admitted_at=r.admitted_at, password_hash=hash_password(temp), must_change_password=True,
        )
        user.employee_code = r.code  # vindo do arquivo (opcional); senão é gerado
        db.add(user)
        kiosk_svc.assign_code(db, user)
        db.flush()
        arp.record_employee(db, company, "I", user, actor)  # tipo 5: inclusão
        created[user.email] = user
        credentials.append({"name": user.name, "email": user.email, "password": temp})
    known = {u.email: u.id for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    for r in result.rows:
        if r.manager_email:
            created[r.email].manager_id = known[r.manager_email]
    audit.log(db, actor, "import", "user", None, ip=client_ip(request), after={"created": len(created)})
    db.commit()
    return {**payload, "imported": True, "created": len(created), "credentials": credentials}


def _target_for_recovery(db: Session, actor: User, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.company_id != actor.company_id:
        raise HTTPException(404, "Usuário não encontrado")  # outra empresa: não revela que existe
    if user.id == actor.id:
        raise HTTPException(409, "Para a sua própria conta use Minha conta")
    if user.role in PRIVILEGED + ("auditor",) and actor.role != "admin":
        raise HTTPException(403, "Somente o administrador altera este usuário")
    return user


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int, request: Request, actor: User = Depends(require_roles(*MANAGEMENT_ROLES)), db: Session = Depends(get_db),
):
    """Gera uma senha temporária (mostrada só aqui), exige troca no próximo acesso e derruba as sessões abertas."""
    user = _target_for_recovery(db, actor, user_id)
    temp = passwords.generate_temp()
    user.password_hash, user.must_change_password = hash_password(temp), True
    user.token_version += 1
    audit.log(db, actor, "reset_password", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"user_id": user.id, "name": user.name, "password": temp}


@router.post("/users/{user_id}/reset-2fa")
def reset_two_factor(
    user_id: int, request: Request, actor: User = Depends(require_roles(*MANAGEMENT_ROLES)), db: Session = Depends(get_db),
):
    """Para quem perdeu o celular e os códigos de recuperação: remove o 2FA (a pessoa configura de novo)."""
    user = _target_for_recovery(db, actor, user_id)
    user.totp_enabled, user.totp_secret, user.totp_recovery, user.totp_last_step = False, None, None, None
    user.token_version += 1
    audit.log(db, actor, "reset_2fa", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"user_id": user.id, "name": user.name, "totp_enabled": False}
