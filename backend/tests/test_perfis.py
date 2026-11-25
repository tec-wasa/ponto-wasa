"""Perfis acumuláveis (administrador + RH + gestor) e cadastros que só gerem (não registram ponto)."""
from tests.conftest import login, make_cpf


def new_user(client, world, **extra):
    n = extra.pop("n", "x")
    body = {"name": f"Pessoa {n}", "email": f"{n}@a.com", "cpf": make_cpf(701), "password": "senha-forte-123", "must_change_password": False, **extra}
    r = client.post("/users", headers=world["admin"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_roles_accumulate_and_top_role_is_derived(client, world):
    u = new_user(client, world, n="glei", roles=["manager", "hr", "admin"])
    assert u["roles"] == ["admin", "hr", "manager"] and u["role"] == "admin" and u["tracks_time"] is True
    h = login(client, "glei@a.com")
    assert client.get("/users", headers=h).status_code == 200
    assert client.post("/users", headers=h, json={"name": "Nova", "email": "nova@a.com", "cpf": make_cpf(702), "password": "senha-forte-123"}).status_code == 201
    # rebaixar para só gestor e voltar a colaborador
    r = client.patch(f"/users/{u['id']}", headers=world["admin"], json={"roles": ["manager"]})
    assert r.json()["role"] == "manager" and r.json()["roles"] == ["manager"]
    r = client.patch(f"/users/{u['id']}", headers=world["admin"], json={"roles": []})
    assert r.json()["role"] == "employee" and r.json()["roles"] == []
    # campo legado "role" continua valendo
    assert client.patch(f"/users/{u['id']}", headers=world["admin"], json={"role": "hr"}).json()["roles"] == ["hr"]


def test_role_rules(client, world):
    assert client.post("/users", headers=world["admin"], json={"name": "Aud Itor", "email": "au@a.com", "cpf": make_cpf(703), "password": "senha-forte-123",
                                                                "roles": ["auditor", "hr"]}).status_code == 422
    assert client.post("/users", headers=world["admin"], json={"name": "Xis Yz", "email": "xy@a.com", "cpf": make_cpf(704), "password": "senha-forte-123",
                                                                "roles": ["rei"]}).status_code == 422
    # RH não atribui funções de gestão
    assert client.post("/users", headers=world["hr"], json={"name": "Xis Yz", "email": "xy@a.com", "cpf": make_cpf(705), "password": "senha-forte-123",
                                                             "roles": ["manager"]}).status_code == 403
    me = client.get("/auth/me", headers=world["admin"]).json()["id"]
    assert client.patch(f"/users/{me}", headers=world["admin"], json={"roles": ["hr"]}).status_code == 409  # não tira o próprio admin


def test_management_only_account_does_not_punch(client, world):
    u = new_user(client, world, n="gest", roles=["admin"], tracks_time=False)
    assert u["tracks_time"] is False
    h = login(client, "gest@a.com")
    r = client.post("/punches", headers=h, json={})
    assert r.status_code == 403 and "só de gestão" in r.json()["detail"]
    # banco de horas não se aplica
    assert client.patch(f"/users/{u['id']}", headers=world["admin"], json={"hour_bank_enabled": True}).status_code == 422
    # fora das listas de equipe e crachás
    dash = client.get("/dashboard", headers=world["admin"])
    assert dash.status_code == 200 and u["id"] not in [p["user_id"] for p in dash.json()["people"]]
    assert client.get("/hour-bank/team", headers=world["admin"]).status_code == 200


def test_rep_type5_only_for_people_who_track_time(client, world, db):
    from sqlalchemy import select

    from app.models import ArpEvent

    def ops(cpf):
        db.expire_all()
        return [e.data["op"] for e in db.execute(select(ArpEvent).where(ArpEvent.record_type == "5").order_by(ArpEvent.nsr)).scalars()
                if e.data["cpf"] == cpf]

    u = new_user(client, world, n="sogestao", roles=["admin"], tracks_time=False)
    assert ops(u["cpf"]) == []  # cadastro só de gestão não entra no REP-P
    client.patch(f"/users/{u['id']}", headers=world["admin"], json={"name": "Outro Nome"})
    assert ops(u["cpf"]) == []
    client.patch(f"/users/{u['id']}", headers=world["admin"], json={"tracks_time": True})
    assert ops(u["cpf"]) == ["I"]  # passou a registrar ponto: inclusão
    client.patch(f"/users/{u['id']}", headers=world["admin"], json={"active": False})
    assert ops(u["cpf"]) == ["I", "E"]
    client.patch(f"/users/{u['id']}", headers=world["admin"], json={"tracks_time": False, "active": True})
    assert ops(u["cpf"]) == ["I", "E"]  # voltou ativa, mas só de gestão: continua fora
