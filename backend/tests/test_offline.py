"""Registro off-line: o aparelho guarda a marcação e a envia depois, com limites de hora e idempotência."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Company, Punch, User
from app.services.espelho import build_espelho


def ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def send(client, who, kind, when, key, **extra):
    return client.post("/punches", headers=who, json={
        "kind": kind, "offline": True, "occurred_at": when, "client_key": key, "collector": "01",
        "device_time": when, "skew_ms": 1200, **extra})


def test_offline_punch_uses_device_time_and_is_flagged(client, world, db):
    when = ago(hours=2)
    r = send(client, world["emp"], "entrada", when, "k1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["offline"] is True and body["kind"] == "entrada"
    assert abs(datetime.fromisoformat(body["occurred_at"]) - (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2))) < timedelta(seconds=5)
    p = db.get(Punch, body["id"])
    assert p.recorded_at > p.occurred_at + timedelta(hours=1)  # gravado (NSR) na hora do envio
    log = db.execute(select(AuditLog).where(AuditLog.entity == "punch", AuditLog.entity_id == str(p.id))).scalars().one()
    assert log.after["offline"] is True and log.after["skew_ms"] == 1200 and log.after["delay_s"] >= 7100
    assert client.get("/punches-integrity", headers=world["hr"]).json()["ok"]


def test_resend_is_idempotent_even_after_deadline(client, world, monkeypatch):
    a = send(client, world["emp"], "entrada", ago(hours=1), "dup").json()
    b = send(client, world["emp"], "entrada", ago(hours=1), "dup")
    assert b.status_code == 201 and b.json()["id"] == a["id"]
    monkeypatch.setattr(settings, "offline_max_hours", 0)  # o mesmo envio, depois do prazo: continua o mesmo registro
    c = send(client, world["emp"], "entrada", ago(hours=1), "dup")
    assert c.status_code == 201 and c.json()["id"] == a["id"]
    assert len(client.get("/punches", headers=world["emp"]).json()) == 1


def test_offline_limits(client, world, monkeypatch):
    emp = world["emp"]
    assert "futuro" in send(client, emp, "entrada", ago(hours=-1), "f").json()["detail"]
    assert send(client, emp, "entrada", ago(hours=73), "old").status_code == 422
    assert send(client, emp, "entrada", ago(hours=71), "ok71").status_code == 201
    assert client.post("/punches", headers=emp, json={"offline": True, "kind": "saida", "occurred_at": ago(minutes=5)}).status_code == 422  # sem client_key
    assert client.post("/punches", headers=emp, json={"offline": True, "kind": "saida", "client_key": "x"}).status_code == 422  # sem hora
    assert client.post("/punches", headers=emp, json={"offline": True, "occurred_at": ago(minutes=5), "client_key": "y"}).status_code == 422  # sem tipo
    monkeypatch.setattr(settings, "offline_punch_enabled", False)
    assert send(client, emp, "saida", ago(minutes=5), "off").status_code == 403


def crossing(db, world):
    """Estes testes não são sobre a meia-noite: com a jornada que vira a noite, o resultado não depende da hora em que rodam."""
    from app.models import Schedule
    db.get(Schedule, world["sched"]["id"]).crosses_midnight = True
    db.commit()


def test_offline_sequence_and_hours_are_computed(client, world, db):
    crossing(db, world)
    emp = world["emp"]
    assert send(client, emp, "entrada", ago(hours=9), "s1").status_code == 201
    dup = send(client, emp, "entrada", ago(hours=8), "s2")
    assert dup.status_code == 409  # duas entradas seguidas: o servidor recusa e o aparelho mostra o motivo
    assert send(client, emp, "saida", ago(hours=1), "s3").status_code == 201

    user = db.get(User, world["ids"]["emp"])
    when = datetime.now(UTC) - timedelta(hours=1)
    espelho = build_espelho(db, db.get(Company, user.company_id), user, when.year, when.month)
    lines = [line for row in espelho["rows"] for line in row["rep"]]
    assert sum("(off-line)" in x for x in lines) == 2
    assert client.get("/punches-integrity", headers=world["hr"]).json()["ok"]


def test_online_punch_ignores_client_time(client, world):
    r = client.post("/punches", headers=world["emp"], json={"kind": "entrada", "occurred_at": ago(hours=5), "client_key": "n1"})
    assert r.status_code == 201 and r.json()["offline"] is False
    assert abs(datetime.fromisoformat(r.json()["occurred_at"]) - datetime.now(UTC).replace(tzinfo=None)) < timedelta(seconds=5)


def test_time_endpoint_announces_offline_policy(client):
    body = client.get("/time").json()
    assert body["offline"] == {"enabled": True, "max_hours": 72}


def test_late_upload_is_checked_against_the_punch_before_it_not_the_latest(client, world, db):
    crossing(db, world)
    emp = world["emp"]
    assert send(client, emp, "entrada", ago(hours=5), "l1").status_code == 201
    assert send(client, emp, "saida", ago(hours=1), "l2").status_code == 201
    # Chega tarde uma "entrada" das 3 h atrás: antes dela vem uma entrada (5 h), então não pode ser outra entrada.
    assert send(client, emp, "entrada", ago(hours=3), "l3").status_code == 409
    assert send(client, emp, "saida", ago(hours=3), "l4").status_code == 201
