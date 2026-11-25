"""Regra única de permissões: quem pode fazer o quê, e sobre quem.

Toda rota pergunta aqui (`can`, `in_scope`, `can_approve`), em vez de comparar perfis. O campo `User.role` (perfil mais
alto) fica só por compatibilidade e exibição: não decide nada.

Dois eixos independentes na pessoa:
- `tracks_time`: registra ponto (área "Meu ponto");
- funções de gestão acumuláveis em `roles`: admin (mestre: inclui RH e gestão de equipe), hr, manager; auditor = só
  leitura, sem acumular.
"""
from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.orm import Session

from .config import settings
from .models import User

ADMIN, HR, MANAGER, AUDITOR = "admin", "hr", "manager", "auditor"

# ação -> funções que a permitem. As ações sobre pessoas valem dentro do alcance (`scope`) de quem age.
ACTIONS: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in {
    "company.settings": {ADMIN},  # dados da empresa, banco de horas, foto, Central
    "people.permissions": {ADMIN},  # atribuir funções de gestão; mexer em quem tem funções
    "people.manage": {ADMIN, HR},  # cadastrar, editar, desativar, excluir, senha, 2FA, importar
    "people.list": {ADMIN, HR, MANAGER, AUDITOR},
    "schedules.manage": {ADMIN, HR},
    "kiosks.manage": {ADMIN},
    "kiosks.view": {ADMIN, HR, AUDITOR},
    "badges.manage": {ADMIN, HR},  # crachás e PIN
    "absences.register": {ADMIN, HR},  # qualquer tipo, em nome de outra pessoa (já aprovada); cancelar as aprovadas
    "hourbank.entries": {ADMIN, HR},
    "approvals": {ADMIN, HR, MANAGER},  # ajustes e ausências pendentes, dentro do alcance
    "team.view": {ADMIN, HR, MANAGER, AUDITOR},  # painel, espelhos, banco de horas e relatórios, dentro do alcance
    "closing.manage": {ADMIN, HR},
    "closing.view": {ADMIN, HR, AUDITOR},
    "fiscal.export": {ADMIN, HR, AUDITOR},  # AFD/AEJ (Art. 81 §2 e Art. 85)
    "integrity.view": {ADMIN, HR, AUDITOR},
    "photos.view": {ADMIN, HR},
    "reports.company": {ADMIN, HR, AUDITOR},  # relatórios que só fazem sentido para a empresa toda
    "audit.view": {ADMIN, AUDITOR},
}.items()}


def funcs(user: User) -> frozenset[str]:
    """Funções efetivas: o administrador inclui RH e gestão de equipe."""
    rs = set(user.role_list) or ({user.role} if user.role and user.role != "employee" else set())
    if ADMIN in rs:
        rs |= {HR, MANAGER}
    return frozenset(rs)


def can(user: User, action: str) -> bool:
    if action == "punch":
        return bool(user.tracks_time and user.active)
    allowed = ACTIONS.get(action)
    if allowed is None:
        raise KeyError(f"ação desconhecida: {action}")
    return bool(funcs(user) & allowed)


def allowed_actions(user: User) -> list[str]:
    """O que a tela pode mostrar para esta pessoa (devolvido em /auth/me)."""
    out = [a for a, fs in ACTIONS.items() if funcs(user) & fs]
    if can(user, "punch"):
        out.append("punch")
    return sorted(out)


def scope(user: User) -> str:
    """Sobre quem a pessoa age na gestão: a empresa toda, a própria equipe ou só ela mesma."""
    fs = funcs(user)
    if fs & {ADMIN, HR, AUDITOR}:
        return "company"
    if MANAGER in fs:
        return "team"
    return "self"


def in_scope(actor: User, target: User) -> bool:
    if target.company_id != actor.company_id:
        return False
    if actor.id == target.id:
        return True
    s = scope(actor)
    return s == "company" or (s == "team" and target.manager_id == actor.id)


def scope_condition(actor: User, include_self: bool = True):
    """Filtro SQL de `User` equivalente a `in_scope` (para listas)."""
    same = User.company_id == actor.company_id
    s = scope(actor)
    if s == "company":
        return and_(same, true() if include_self else User.id != actor.id)
    me = User.id == actor.id if include_self else false()
    if s == "team":
        return and_(same, or_(User.manager_id == actor.id, me))
    return and_(same, me)


def is_privileged(user: User) -> bool:
    """Quem tem função de gestão ou de auditoria: só a Administração altera, exclui ou imprime o crachá dessa pessoa."""
    return bool(funcs(user))


def can_approve(actor: User, owner: User) -> bool:
    """Aprovar ajuste/ausência de `owner` (a autoaprovação é tratada à parte em `self_approval_allowed`)."""
    return actor.id != owner.id and can(actor, "approvals") and in_scope(actor, owner)


def other_approvers(db: Session, owner: User) -> bool:
    """Existe alguém além do próprio dono que poderia aprovar o pedido?"""
    people = db.execute(select(User).where(User.company_id == owner.company_id, User.active.is_(True),
                                           User.id != owner.id)).scalars()
    return any(can_approve(p, owner) for p in people)


def self_approval_allowed(db: Session, actor: User, owner: User) -> bool:
    """Exceção para empresa pequena: a Administração aprova o próprio pedido só se ninguém mais puder aprová-lo
    (com justificativa obrigatória e registro destacado na auditoria)."""
    return actor.id == owner.id and ADMIN in funcs(actor) and not other_approvers(db, owner)


def decision_mode(db: Session, actor: User, owner: User) -> str | None:
    """Para a caixa de aprovações: "approve" (decide normalmente), "self" (autoaprovação com justificativa) ou None."""
    if can_approve(actor, owner):
        return "approve"
    if self_approval_allowed(db, actor, owner):
        return "self"
    return None


def requires_2fa(user: User) -> bool:
    return bool(funcs(user) & settings.require_2fa_role_set)
