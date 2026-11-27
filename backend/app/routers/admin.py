import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..config import settings
from ..db import get_db
from ..deps import client_ip, get_current_user, require
from ..models import (
    MANAGEMENT_FUNCS,
    Absence,
    Adjustment,
    Closing,
    Company,
    HourBankEntry,
    InconsistencyResolution,
    KioskTicket,
    Punch,
    PunchPhoto,
    Schedule,
    User,
    top_role,
)
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

NO_PURPOSE = "Quem não registra ponto precisa ter ao menos uma função de gestão (senão o cadastro não serve para nada)"


NEEDS_LOGIN = "Quem tem função de gestão ou não registra ponto precisa entrar no aplicativo"


def _check_manager(db: Session, actor: User, manager_id: int | None, person_id: int | None = None) -> None:
    mgr = _same_company(db, actor, User, manager_id, "Gestor")
    if mgr is None:
        return
    if mgr.id == person_id:
        raise HTTPException(422, "A pessoa não pode ser gestora de si mesma")
    if not mgr.active or not perm.can(mgr, "approvals"):
        raise HTTPException(422, f"{mgr.name} não tem a função Gestor (nem RH ou Administração) para ser gestor de alguém")


def _check_access(app_access: bool, email: str | None, tracks_time: bool, roles: list[str]) -> None:
    if not app_access and (roles or not tracks_time):
        raise HTTPException(422, NEEDS_LOGIN)
    if app_access and not email:
        raise HTTPException(422, "Informe o e-mail: é com ele que a pessoa entra no aplicativo")


def _resolve_roles(actor: User, roles: list[str] | None, role: str | None) -> list[str]:
    """Funções de gestão acumuláveis (admin, hr, manager; auditor sozinho). Lista vazia = colaborador comum."""
    if roles is None:
        if role not in ROLES:
            raise HTTPException(422, "Perfil inválido")
        roles = [] if role == "employee" else [role]
    roles = list(dict.fromkeys(roles))
    if any(r not in MANAGEMENT_FUNCS for r in roles):
        raise HTTPException(422, "Perfil inválido")
    if "auditor" in roles and len(roles) > 1:
        raise HTTPException(422, "O auditor (acesso só de leitura para a fiscalização) não acumula com outras funções")
    if roles and not perm.can(actor, "people.permissions"):
        raise HTTPException(403, "Somente a Administração atribui funções de gestão")
    return sorted(roles, key=lambda r: (MANAGEMENT_FUNCS.index(r)))


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
    body: CompanyPatch, request: Request, actor: User = Depends(require("company.settings")),
    db: Session = Depends(get_db),
):
    company = db.get(Company, actor.company_id)
    before = {"name": company.name, "caepf": company.caepf, "cno": company.cno,
              "timezone": company.timezone, "workplace": company.workplace, "photo_enabled": company.photo_enabled,
              "kiosk_pin_required": company.kiosk_pin_required, "overtime_rule": company.overtime_rule}
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not (data["name"] or "").strip():
        raise HTTPException(422, "Informe a razão social")
    if "timezone" in data:
        try:
            ZoneInfo(data["timezone"] or "")
        except (ValueError, KeyError, ZoneInfoNotFoundError):
            raise HTTPException(422, "Fuso horário inválido") from None
    if data.get("password_login") is False and company.password_login:
        if not actor.google_sub:
            raise HTTPException(409, "Vincule a sua conta Google em Minha conta antes de desligar a senha; senão você perde o acesso.")
        if not settings.google_client_id:
            raise HTTPException(409, "O login com Google não está configurado neste servidor")
    changed = {k: v for k, v in data.items() if getattr(company, k) != v}
    if not changed:
        return company
    for k, v in changed.items():
        setattr(company, k, v)
    if set(changed) & {"name", "caepf", "cno", "workplace"}:
        arp.record_employer(db, company, actor)  # tipo 2: alteração da identificação do empregador
    audit.log(db, actor, "update", "company", company.id, before={k: before.get(k) for k in changed}, after=changed, ip=client_ip(request))
    db.commit()
    return company


# --- Usuários ----------------------------------------------------------------
@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserIn, request: Request, actor: User = Depends(require("people.manage")),
    db: Session = Depends(get_db),
):
    roles = _resolve_roles(actor, body.roles, body.role)
    if not body.tracks_time and not roles:
        raise HTTPException(422, NO_PURPOSE)
    _check_access(body.app_access, body.email, body.tracks_time, roles)
    if body.app_access and not body.password:
        raise HTTPException(422, "Informe a senha inicial (a pessoa troca no primeiro acesso)")
    _check_manager(db, actor, body.manager_id)
    _same_company(db, actor, Schedule, body.schedule_id, "Jornada")
    if db.execute(select(User.id).where(User.company_id == actor.company_id, User.cpf == body.cpf)).first():
        raise HTTPException(409, "CPF já cadastrado nesta empresa")
    user = User(
        company_id=actor.company_id, name=body.name, email=body.email.lower() if body.email else None, cpf=body.cpf,
        # sem acesso ao app: senha aleatória que ninguém conhece (o login também é recusado por app_access)
        password_hash=hash_password(body.password if body.app_access else secrets.token_urlsafe(32)),
        role=top_role(roles), roles=",".join(roles), tracks_time=body.tracks_time, app_access=body.app_access,
        punch_policy=body.punch_policy if body.app_access else "kiosk",
        hour_bank_enabled=body.hour_bank_enabled and body.tracks_time,
        manager_id=body.manager_id, schedule_id=body.schedule_id, admitted_at=body.admitted_at,
        job_title=body.job_title, must_change_password=body.must_change_password and body.app_access,
    )
    db.add(user)
    kiosk_svc.assign_code(db, user)  # código interno para a Central
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail já cadastrado") from None
    company = db.get(Company, actor.company_id)
    if user.hour_bank_enabled:
        user.hour_bank_start = datetime.now(ZoneInfo(company.timezone)).date()
    if arp.in_rep(user):
        arp.record_employee(db, company, "I", user, actor)  # tipo 5: inclusão
    audit.log(db, actor, "create", "user", user.id, after={"email": user.email, "roles": user.roles, "tracks_time": user.tracks_time},
              ip=client_ip(request))
    db.commit()
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(actor: User = Depends(require("people.list")), db: Session = Depends(get_db)):
    q = select(User).where(perm.scope_condition(actor)).order_by(User.name)
    return db.execute(q).scalars().all()


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int, body: UserPatch, request: Request,
    actor: User = Depends(require("people.manage")), db: Session = Depends(get_db),
):
    user = _same_company(db, actor, User, user_id, "Usuário")
    data = body.model_dump(exclude_unset=True)
    if perm.is_privileged(user) and not perm.can(actor, "people.permissions"):
        raise HTTPException(403, "Somente a Administração altera quem tem função de gestão")
    if "roles" in data or "role" in data:
        new_roles, legacy = data.pop("roles", None), data.pop("role", None)
        roles = _resolve_roles(actor, new_roles, legacy if new_roles is None else None)
        if user.id == actor.id and perm.ADMIN not in roles:
            raise HTTPException(409, "Você não pode tirar de si mesmo a função de administrador")
        data["roles"], data["role"] = ",".join(roles), top_role(roles)
    final_roles = data["roles"].split(",") if "roles" in data else user.role_list
    if not data.get("tracks_time", user.tracks_time) and not [r for r in final_roles if r]:
        raise HTTPException(422, NO_PURPOSE)
    if data.get("hour_bank_enabled") and not data.get("tracks_time", user.tracks_time):
        raise HTTPException(422, "Esta pessoa não registra ponto, então não tem banco de horas")
    if data.get("tracks_time") is False and user.hour_bank_enabled:
        data["hour_bank_enabled"] = False
    final_access = data.get("app_access", user.app_access)
    if "app_access" in data or "roles" in data or "tracks_time" in data or "email" in data:
        _check_access(final_access, data.get("email") or user.email, data.get("tracks_time", user.tracks_time), [r for r in final_roles if r])
    if data.get("app_access") is False:
        if user.id == actor.id:
            raise HTTPException(409, "Você não pode tirar o seu próprio acesso ao aplicativo")
        data["punch_policy"] = "kiosk"  # sem login, só a Central registra o ponto
    if data.get("punch_policy") == "both" and not final_access:
        raise HTTPException(422, "Sem acesso ao aplicativo a pessoa só bate ponto na Central")
    if "manager_id" in data:
        _check_manager(db, actor, data["manager_id"], user.id)
    if data.get("email"):
        data["email"] = data["email"].lower()
    if data.get("cpf") is not None and data["cpf"] != user.cpf:
        if db.execute(select(Punch.id).where(Punch.user_id == user.id).limit(1)).first():
            raise HTTPException(409, "Não é possível alterar o CPF de quem já tem marcações (o CPF faz parte do registro de cada marcação). "
                                     "Desative esta pessoa e cadastre outra, se o CPF estava errado desde o início, com apoio do jurídico.")
        if db.execute(select(User.id).where(User.company_id == user.company_id, User.cpf == data["cpf"], User.id != user.id)).first():
            raise HTTPException(409, "CPF já cadastrado nesta empresa")
    data = {k: v for k, v in data.items() if not (k in ("email", "cpf") and v is None)}
    if "schedule_id" in data:
        _same_company(db, actor, Schedule, data["schedule_id"], "Jornada")
        if data["schedule_id"] != user.schedule_id:
            month = _closed_month_with_punches(db, user.company_id, [user.id])
            if month:
                raise HTTPException(409, f"Não é possível trocar a jornada: o mês {month} está fechado e tem marcações desta pessoa. "
                                         "Reabra o mês (RH ou administrador) antes de trocar.")
    before = {k: getattr(user, k) for k in data}
    was_in_rep = arp.in_rep(user)
    for k, v in data.items():
        setattr(user, k, v)
    if before.get("app_access") and data.get("app_access") is False:
        user.token_version += 1  # derruba as sessões abertas
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail já cadastrado") from None
    company = db.get(Company, actor.company_id)
    if data.get("hour_bank_enabled") and not user.hour_bank_start:
        user.hour_bank_start = datetime.now(ZoneInfo(company.timezone)).date()  # o saldo passa a contar a partir de hoje
        data["hour_bank_start"] = user.hour_bank_start
    # tipo 5: entra/sai do REP-P quando passa a (ou deixa de) estar ativa e registrando ponto; alteração de nome/CPF de quem consta
    if arp.in_rep(user) != was_in_rep:
        arp.record_employee(db, company, "I" if arp.in_rep(user) else "E", user, actor)
    elif arp.in_rep(user) and (("name" in data and before["name"] != data["name"]) or ("cpf" in data and before["cpf"] != data["cpf"])):
        arp.record_employee(db, company, "A", user, actor)
    audit.log(db, actor, "update", "user", user.id, before=before, after=data, ip=client_ip(request))
    db.commit()
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, actor: User = Depends(require("people.manage")), db: Session = Depends(get_db)):
    """Exclui o cadastro de quem NUNCA teve movimentação (cadastro por engano). Quem já tem marcações, ajustes, ausências ou banco de
    horas não pode ser apagado (são registros trabalhistas, imutáveis por desenho): use "Desativar", que mantém o histórico."""
    user = _same_company(db, actor, User, user_id, "Usuário")
    if user.id == actor.id:
        raise HTTPException(409, "Você não pode excluir o seu próprio cadastro")
    if perm.is_privileged(user) and not perm.can(actor, "people.permissions"):
        raise HTTPException(403, "Somente a Administração exclui quem tem função de gestão")
    for model, label in ((Punch, "marcações"), (Adjustment, "ajustes"), (Absence, "ausências"), (HourBankEntry, "lançamentos de banco de horas"),
                         (PunchPhoto, "fotos")):
        if db.execute(select(model.id).where(model.user_id == user.id).limit(1)).first():
            raise HTTPException(409, f"Não é possível excluir: esta pessoa tem {label}. Use Desativar, que mantém o histórico.")
    if db.execute(select(User.id).where(User.manager_id == user.id).limit(1)).first():
        raise HTTPException(409, "Esta pessoa é gestora de outras. Troque o gestor delas antes de excluir.")
    snapshot = {"name": user.name, "email": user.email, "role": user.role}
    db.query(KioskTicket).filter(KioskTicket.user_id == user.id).delete()
    db.query(InconsistencyResolution).filter(InconsistencyResolution.user_id == user.id).delete()  # só "resolvido" de faltas
    db.query(InconsistencyResolution).filter(InconsistencyResolution.resolved_by == user.id).update({"resolved_by": None})
    if arp.in_rep(user):  # quem já foi desativado (ou não registra ponto) já está fora do REP-P
        arp.record_employee(db, db.get(Company, actor.company_id), "E", user, actor)  # tipo 5: exclusão
    audit.log(db, actor, "delete", "user", user.id, before=snapshot, ip=client_ip(request))
    db.delete(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Esta pessoa ainda é referenciada por outros registros (ex.: fechamentos, lançamentos). Use Desativar.") from None
    return Response(status_code=204)


# --- Jornadas ----------------------------------------------------------------
@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(
    body: ScheduleIn, request: Request, actor: User = Depends(require("schedules.manage")),
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
    schedule_id: int, body: SchedulePatch, request: Request, actor: User = Depends(require("schedules.manage")),
    db: Session = Depends(get_db),
):
    """Edita a jornada. O nome é livre; as demais regras mudam o cálculo do Espelho (inclusive de dias já passados e ainda abertos):
    ficam na auditoria com o antes e o depois, e são recusadas se um mês fechado tiver marcações de pessoas desta jornada."""
    sched = db.get(Schedule, schedule_id)
    if not sched or sched.company_id != actor.company_id:
        raise HTTPException(404, "Jornada não encontrada")
    data = body.model_dump(exclude_unset=True)
    data = {k: v for k, v in data.items() if v is not None}
    if "weekdays" in data:
        if not data["weekdays"] or any(d < 0 or d > 6 for d in data["weekdays"]):
            raise HTTPException(422, "Dias da semana devem estar entre 0 (segunda) e 6 (domingo), com ao menos um dia")
        data["weekdays"] = ",".join(str(d) for d in sorted(set(data["weekdays"])))
    before = {k: getattr(sched, k) for k in data}
    changes = {k: v for k, v in data.items() if before[k] != v}
    if not changes:
        return sched
    final = {c: changes.get(c, getattr(sched, c)) for c in ("break_minutes", "break_start", "start_time", "crosses_midnight")}
    if final["break_minutes"] > 0 and not final["crosses_midnight"] and final["break_start"] <= final["start_time"]:
        raise HTTPException(422, "O início do intervalo deve ser posterior ao início da jornada (exceto em turno que vira a meia-noite)")
    if set(changes) - {"name"}:
        month = _closed_month_with_punches(
            db, sched.company_id, list(db.execute(select(User.id).where(User.schedule_id == sched.id)).scalars()))
        if month:
            raise HTTPException(409, f"Não é possível alterar: o mês {month} está fechado e tem marcações de pessoas desta jornada. "
                                     "Reabra o mês (RH ou administrador) ou crie uma jornada nova e troque as pessoas a partir de agora.")
    for k, v in changes.items():
        setattr(sched, k, v)
    audit.log(db, actor, "update", "schedule", sched.id, before={k: before[k] for k in changes}, after=changes, ip=client_ip(request))
    db.commit()
    return sched


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, request: Request, actor: User = Depends(require("schedules.manage")),
                    db: Session = Depends(get_db)):
    """Exclui uma jornada que ninguém usa. Em uso: troque a jornada das pessoas antes."""
    sched = db.get(Schedule, schedule_id)
    if not sched or sched.company_id != actor.company_id:
        raise HTTPException(404, "Jornada não encontrada")
    n = db.execute(select(User.id).where(User.schedule_id == sched.id)).scalars().all()
    if n:
        raise HTTPException(409, f"Esta jornada está em uso por {len(n)} pessoa(s). Troque a jornada delas em Pessoas e tente de novo.")
    audit.log(db, actor, "delete", "schedule", sched.id, before={"name": sched.name}, ip=client_ip(request))
    db.delete(sched)
    db.commit()
    return Response(status_code=204)


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(select(Schedule).where(Schedule.company_id == actor.company_id)).scalars().all()


# --- Importação em lote e recuperação de acesso ---------------------------------------------------
class ImportIn(BaseModel):
    content_base64: str = Field(max_length=int(csv_import.MAX_BYTES * 1.4))


@router.get("/users/import/template")
def import_template(actor: User = Depends(require("people.manage"))):
    """Modelo do CSV (separador ';', UTF-8), com uma linha de exemplo."""
    return Response(csv_import.TEMPLATE.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="modelo-colaboradores.csv"'})


@router.post("/users/import")
def import_users(
    body: ImportIn, request: Request, dry_run: bool = True,
    actor: User = Depends(require("people.manage")), db: Session = Depends(get_db),
):
    """Importa colaboradores de um CSV. Por padrão só **valida** (`dry_run=true`); com `dry_run=false` grava tudo ou nada.

    Cada usuário nasce com uma senha temporária (mostrada só na resposta) e troca obrigatória no primeiro acesso.
    """
    allowed = ("employee", "manager", "hr", "admin", "auditor") if perm.can(actor, "people.permissions") else ("employee",)
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
    if perm.is_privileged(user) and not perm.can(actor, "people.permissions"):
        raise HTTPException(403, "Somente a Administração altera quem tem função de gestão")
    if not user.app_access:
        raise HTTPException(409, "Esta pessoa não entra no aplicativo (só bate ponto na Central). Libere o acesso no cadastro antes.")
    return user


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int, request: Request, actor: User = Depends(require("people.manage")), db: Session = Depends(get_db),
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
    user_id: int, request: Request, actor: User = Depends(require("people.manage")), db: Session = Depends(get_db),
):
    """Para quem perdeu o celular e os códigos de recuperação: remove o 2FA (a pessoa configura de novo)."""
    user = _target_for_recovery(db, actor, user_id)
    user.totp_enabled, user.totp_secret, user.totp_recovery, user.totp_last_step = False, None, None, None
    user.token_version += 1
    audit.log(db, actor, "reset_2fa", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"user_id": user.id, "name": user.name, "totp_enabled": False}
