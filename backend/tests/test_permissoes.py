"""Matriz de permissões por persona (regra única em app/permissions.py).

Personas: colaborador (ana, tem gestor), colaborador sem gestor (beto), gestor que bate ponto (gil), RH que bate ponto (rita),
administradora que só gere (gleici, não registra ponto) e auditor.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import PASSWORD, login, make_cpf


@pytest.fixture()
def people(client, world):
    def mk(email, n, **extra):
        r = client.post("/users", headers=world["admin"], json={
            "name": email.split("@")[0].title(), "email": email, "password": PASSWORD, "cpf": make_cpf(n),
            "must_change_password": False, **extra})
        assert r.status_code == 201, r.text
        return r.json()

    gleici = mk("gleici@a.com", 300000001, roles=["admin", "hr", "manager"], tracks_time=False)
    aud = mk("aud@a.com", 300000002, roles=["auditor"], tracks_time=False)
    return {**world, "gleici": login(client, "gleici@a.com"), "aud": login(client, "aud@a.com"),
            "ids": {**world["ids"], "gleici": gleici["id"], "aud": aud["id"]}}


def me(client, h):
    return client.get("/auth/me", headers=h).json()


def test_me_lists_permissions_per_persona(client, people):
    emp = me(client, people["emp"])
    assert emp["permissions"] == ["punch"] and emp["scope"] == "self"
    mgr = me(client, people["mgr"])
    assert {"approvals", "team.view", "people.list", "punch"} <= set(mgr["permissions"]) and mgr["scope"] == "team"
    assert "people.manage" not in mgr["permissions"]
    hr = me(client, people["hr"])
    assert {"people.manage", "absences.register", "closing.manage", "fiscal.export", "punch"} <= set(hr["permissions"])
    assert not {"company.settings", "people.permissions", "kiosks.manage", "audit.view"} & set(hr["permissions"])
    g = me(client, people["gleici"])
    assert {"company.settings", "people.permissions", "kiosks.manage", "audit.view", "approvals"} <= set(g["permissions"])
    assert "punch" not in g["permissions"] and g["scope"] == "company"
    aud = me(client, people["aud"])
    assert set(aud["permissions"]) == {"people.list", "team.view", "kiosks.view", "closing.view", "fiscal.export",
                                       "integrity.view", "reports.company", "audit.view"}


# (método, rota, corpo) -> personas que podem; as demais recebem 403
MATRIX = [
    ("patch", "/company", {"workplace": "Rua A"}, {"admin", "gleici"}),
    ("get", "/audit", None, {"admin", "gleici", "aud"}),
    ("get", "/closings", None, {"admin", "gleici", "hr", "aud"}),
    ("get", "/exports/status", None, {"admin", "gleici", "hr", "aud"}),
    ("get", "/kiosks", None, {"admin", "gleici", "hr", "aud"}),
    ("get", "/dashboard", None, {"admin", "gleici", "hr", "mgr", "aud"}),
    ("get", "/hour-bank/team", None, {"admin", "gleici", "hr", "mgr", "aud"}),
    ("get", "/users", None, {"admin", "gleici", "hr", "mgr", "aud"}),
    ("get", "/punches-integrity", None, {"admin", "gleici", "hr", "aud"}),
    ("post", "/schedules", {"name": "Teste matriz"}, {"admin", "gleici", "hr"}),
]


@pytest.mark.parametrize("method,path,body,allowed", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_route_matrix(client, people, method, path, body, allowed):
    for who in ("admin", "gleici", "hr", "mgr", "emp", "aud"):
        kw = {"json": body} if body is not None else {}
        r = getattr(client, method)(path, headers=people[who], **kw)
        if who in allowed:
            assert r.status_code < 400, (who, r.status_code, r.text)
        else:
            assert r.status_code == 403, (who, r.status_code, r.text)


def test_manager_scope_is_the_team(client, people):
    ids = people["ids"]
    names = {u["id"] for u in client.get("/users", headers=people["mgr"]).json()}
    assert names == {ids["mgr"], ids["emp"]}  # ele mesmo e a equipe
    assert client.get(f"/mirror?month=2026-01&user_id={ids['emp']}", headers=people["mgr"]).status_code == 200
    assert client.get(f"/mirror?month=2026-01&user_id={ids['other']}", headers=people["mgr"]).status_code == 404
    dash = client.get("/dashboard", headers=people["mgr"]).json()
    assert [p["user_id"] for p in dash["people"]] == [ids["emp"]]


def _adjust(client, h):
    when = (datetime.now(UTC) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    r = client.post("/adjustments", headers=h, json={"kind": "incluir", "requested_at": when.isoformat(), "punch_kind": "entrada",
                                                     "reason": "Esqueci de bater o ponto"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_approvals_follow_scope(client, people):
    a_emp, a_other = _adjust(client, people["emp"]), _adjust(client, people["other"])
    assert client.post(f"/adjustments/{a_other}/decision", headers=people["mgr"], json={"approve": True}).status_code == 403
    assert client.post(f"/adjustments/{a_emp}/decision", headers=people["mgr"], json={"approve": True}).status_code == 200
    assert client.post(f"/adjustments/{a_other}/decision", headers=people["gleici"], json={"approve": True}).status_code == 200
    pend = client.get("/adjustments?status=pending", headers=people["mgr"]).json()
    assert all(a["user_id"] in (people["ids"]["emp"], people["ids"]["mgr"]) for a in pend)


def test_hr_cannot_touch_people_with_management_functions(client, people):
    ids = people["ids"]
    assert client.patch(f"/users/{ids['mgr']}", headers=people["hr"], json={"job_title": "X"}).status_code == 403
    assert client.patch(f"/users/{ids['emp']}", headers=people["hr"], json={"job_title": "Vendas"}).status_code == 200
    assert client.patch(f"/users/{ids['emp']}", headers=people["hr"], json={"roles": ["manager"]}).status_code == 403
    assert client.patch(f"/users/{ids['mgr']}", headers=people["gleici"], json={"job_title": "Coordenador"}).status_code == 200


def test_management_only_account_has_no_personal_area(client, people):
    g = people["gleici"]
    when = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert client.post("/adjustments", headers=g, json={"kind": "incluir", "requested_at": when, "punch_kind": "entrada",
                                                        "reason": "teste teste"}).status_code == 403
    today = datetime.now(UTC).date().isoformat()
    assert client.post("/absences", headers=g, json={"kind": "abono", "start_date": today, "end_date": today,
                                                     "reason": "teste"}).status_code == 403
    assert client.get("/auth/badge", headers=g).status_code == 403
    assert client.get("/punches/next", headers=g).status_code == 403
    assert client.post("/punches", headers=g, json={}).status_code == 403
    # e ninguém registra ausência ou crachá para ela
    gid = people["ids"]["gleici"]
    assert client.post("/absences", headers=people["admin"], json={"kind": "ferias", "start_date": today, "end_date": today,
                                                                   "reason": "teste", "user_id": gid}).status_code == 422
    assert client.get(f"/users/{gid}/badge", headers=people["admin"]).status_code == 422


def test_account_without_purpose_is_refused(client, people):
    r = client.post("/users", headers=people["admin"], json={"name": "Ninguem", "email": "n@a.com", "password": PASSWORD,
                                                             "cpf": make_cpf(300000009), "tracks_time": False})
    assert r.status_code == 422
    assert client.patch(f"/users/{people['ids']['emp']}", headers=people["admin"], json={"tracks_time": False}).status_code == 422


def test_self_approval_only_when_nobody_else_can(client, people, db):
    # Empresa A tem RH: o administrador não decide o próprio ajuste
    own = _adjust(client, people["admin"])
    r = client.post(f"/adjustments/{own}/decision", headers=people["admin"], json={"approve": True, "note": "justificativa longa"})
    assert r.status_code == 403
    # Empresa B: o administrador é a única pessoa; decide com justificativa
    b = people["adminB"]
    mine = _adjust(client, b)
    r = client.post(f"/adjustments/{mine}/decision", headers=b, json={"approve": True})
    assert r.status_code == 422 and "justificativa" in r.json()["detail"]
    r = client.post(f"/adjustments/{mine}/decision", headers=b, json={"approve": True, "note": "Sou a única administradora"})
    assert r.status_code == 200, r.text
    log = db.execute(select(AuditLog).where(AuditLog.entity == "adjustment", AuditLog.entity_id == str(mine))
                     .order_by(AuditLog.id.desc())).scalars().first()
    assert log.action == "self_approve" and log.after["self_approval"] is True
