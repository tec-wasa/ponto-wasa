"""Editar e excluir cadastros: pessoas, jornadas e centrais (com as proteções de histórico)."""
from sqlalchemy import select

from app.models import AuditLog, Kiosk, User
from tests.conftest import make_cpf


def new_sched(client, world, name="Extra"):
    return client.post("/schedules", headers=world["admin"], json={"name": name}).json()


def test_schedule_can_be_fully_edited_and_audited(client, world, db):
    s = new_sched(client, world)
    r = client.patch(f"/schedules/{s['id']}", headers=world["hr"], json={
        "name": "Comercial 6h", "weekdays": [0, 1, 2, 3, 4, 5], "daily_minutes": 360, "break_minutes": 15,
        "tolerance_minutes": 5, "start_time": "09:00", "break_start": "12:30"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["name"] == "Comercial 6h" and b["weekdays"] == "0,1,2,3,4,5" and b["daily_minutes"] == 360 and b["start_time"] == "09:00"
    log = db.execute(select(AuditLog).where(AuditLog.entity == "schedule", AuditLog.entity_id == str(s["id"]), AuditLog.action == "update")).scalars().all()
    assert log and log[-1].before["daily_minutes"] == 480 and log[-1].after["daily_minutes"] == 360
    assert client.patch(f"/schedules/{s['id']}", headers=world["hr"], json={"break_start": "07:00"}).status_code == 422  # intervalo antes da entrada
    assert client.patch(f"/schedules/{s['id']}", headers=world["hr"], json={"weekdays": []}).status_code == 422
    assert client.patch(f"/schedules/{s['id']}", headers=world["emp"], json={"name": "X1"}).status_code == 403


def test_schedule_delete_only_when_unused(client, world):
    s = new_sched(client, world)
    emp = world["ids"]["emp"]
    client.patch(f"/users/{emp}", headers=world["hr"], json={"schedule_id": s["id"]})
    r = client.delete(f"/schedules/{s['id']}", headers=world["hr"])
    assert r.status_code == 409 and "em uso" in r.json()["detail"]
    client.patch(f"/users/{emp}", headers=world["hr"], json={"schedule_id": world["sched"]["id"]})
    assert client.delete(f"/schedules/{s['id']}", headers=world["hr"]).status_code == 204
    assert client.delete(f"/schedules/{s['id']}", headers=world["hr"]).status_code == 404
    assert client.delete(f"/schedules/{world['sched']['id']}", headers=world["emp"]).status_code == 403


def test_user_email_and_cpf_edit_rules(client, world, db):
    emp, other = world["ids"]["emp"], world["ids"]["other"]
    # novo usuário sem marcações: CPF e e-mail editáveis
    u = client.post("/users", headers=world["hr"], json={"name": "Novo Teste", "email": "novo@x.com", "cpf": make_cpf(900000001),
                                                         "password": "senha-forte-123"}).json()
    r = client.patch(f"/users/{u['id']}", headers=world["hr"], json={"email": "Novo2@X.com", "cpf": make_cpf(900000002), "name": "Novo Teste 2"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "novo2@x.com" and r.json()["cpf"] == make_cpf(900000002)
    assert client.patch(f"/users/{u['id']}", headers=world["hr"], json={"email": "gestor@a.com"}).status_code == 409  # e-mail já usado
    assert client.patch(f"/users/{u['id']}", headers=world["hr"], json={"cpf": "111.111.111-11"}).status_code == 422
    assert client.patch(f"/users/{u['id']}", headers=world["hr"], json={"manager_id": u["id"]}).status_code == 422
    # quem tem marcações: CPF travado, e-mail livre
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    assert client.patch(f"/users/{emp}", headers=world["hr"], json={"cpf": make_cpf(900000003)}).status_code == 409
    assert client.patch(f"/users/{emp}", headers=world["hr"], json={"email": "ana.nova@a.com"}).status_code == 200
    assert client.patch(f"/users/{other}", headers=world["hr"], json={"cpf": db.get(User, emp).cpf}).status_code == 409  # CPF já usado


def test_user_delete_only_without_history(client, world, db):
    hr_id = world["ids"]["hr"]
    u = client.post("/users", headers=world["hr"], json={"name": "Por Engano", "email": "engano@x.com", "cpf": make_cpf(900000010),
                                                         "password": "senha-forte-123"}).json()
    assert client.delete(f"/users/{u['id']}", headers=world["emp"]).status_code == 403
    assert client.delete(f"/users/{hr_id}", headers=world["hr"]).status_code == 409  # a si mesmo
    assert client.delete(f"/users/{u['id']}", headers=world["hr"]).status_code == 204
    assert db.get(User, u["id"]) is None
    assert client.delete(f"/users/{u['id']}", headers=world["hr"]).status_code == 422  # já não existe
    # com marcação: só inativar
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    r = client.delete(f"/users/{world['ids']['emp']}", headers=world["hr"])
    assert r.status_code == 409 and "Desativar" in r.json()["detail"]
    # gestor de outras pessoas
    assert client.delete(f"/users/{world['ids']['mgr']}", headers=world["hr"]).status_code == 409
    # RH não exclui perfil privilegiado
    assert client.delete(f"/users/{world['ids']['hr']}", headers=world["hr"]).status_code == 409  # a si mesmo


def test_kiosk_delete_requires_revocation_and_keeps_punches(client, world, db):
    from tests.test_kiosk import code_of, consent_and_punch, identify, paired
    kh, k = paired(client, world)
    assert client.delete(f"/kiosks/{k['id']}", headers=world["admin"]).status_code == 409  # ainda ativa
    t = identify(client, kh, "code", code_of(client, world["emp"])).json()["ticket"]
    assert consent_and_punch(client, kh, t).status_code == 201
    assert client.post(f"/kiosks/{k['id']}/revoke", headers=world["admin"]).status_code == 200
    assert client.delete(f"/kiosks/{k['id']}", headers=world["hr"]).status_code == 403  # só o administrador
    assert client.delete(f"/kiosks/{k['id']}", headers=world["admin"]).status_code == 204
    assert db.get(Kiosk, k["id"]) is None
    assert any("Central" in p["origin"] for p in client.get("/punches", headers=world["emp"]).json())  # histórico preservado
