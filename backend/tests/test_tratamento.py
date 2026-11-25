"""Tratamento mensal pela gestão: incluir e desconsiderar marcações por conta própria, desfazer e ver o mês dia a dia."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import AuditLog


def yesterday_noon():
    return (datetime.now(UTC) - timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)


def test_manager_treats_team_member_directly(client, world, db):
    emp, mgr = world["ids"]["emp"], world["mgr"]
    when = yesterday_noon()
    admitted = (when - timedelta(days=40)).date().isoformat()
    assert client.patch(f"/users/{emp}", headers=world["admin"], json={"admitted_at": admitted}).status_code == 200
    r = client.post("/adjustments", headers=mgr, json={"kind": "incluir", "user_id": emp, "requested_at": when.isoformat(),
                                                       "punch_kind": "entrada", "reason": "Esqueceu de bater, confirmado"})
    assert r.status_code == 201 and r.json()["status"] == "approved", r.text
    inc = r.json()["id"]
    month = when.strftime("%Y-%m")
    t = client.get(f"/treatment?month={month}&user_id={emp}", headers=mgr).json()
    assert t["can_treat"] and not t["closed"]
    day = next(d for d in t["days"] if any(m["type"] == "inclusao" for m in d["marks"]))
    assert any("entrada" in p for p in day["punches"])  # o espelho já considera a inclusão
    log = db.execute(select(AuditLog).where(AuditLog.entity == "adjustment", AuditLog.entity_id == str(inc))).scalars().first()
    assert log.action == "treat" and log.after["reason"]
    # desfazer
    assert client.post(f"/adjustments/{inc}/revoke", headers=mgr).json()["status"] == "revoked"
    t = client.get(f"/treatment?month={month}&user_id={emp}", headers=mgr).json()
    assert not any(m["type"] == "inclusao" for d in t["days"] for m in d["marks"])


def test_void_an_original_punch_and_no_duplicates(client, world):
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    emp, hr = world["ids"]["emp"], world["hr"]
    month = datetime.now(UTC).strftime("%Y-%m")
    t = client.get(f"/treatment?month={month}&user_id={emp}", headers=hr).json()
    mark = next(m for d in t["days"] for m in d["marks"] if m["type"] == "original")
    body = {"kind": "desconsiderar", "user_id": emp, "target_punch_id": mark["punch_id"], "reason": "Batida duplicada"}
    assert client.post("/adjustments", headers=hr, json=body).json()["status"] == "approved"
    assert client.post("/adjustments", headers=hr, json=body).status_code == 409
    t = client.get(f"/treatment?month={month}&user_id={emp}", headers=hr).json()
    m = next(m for d in t["days"] for m in d["marks"] if m["punch_id"] == mark["punch_id"])
    assert m["voided"] and m["note"] == "Batida duplicada" and m["by"] == "Rita RH"


def test_treatment_scope(client, world):
    other, emp = world["ids"]["other"], world["ids"]["emp"]
    month = datetime.now(UTC).strftime("%Y-%m")
    assert client.get(f"/treatment?month={month}&user_id={other}", headers=world["mgr"]).status_code == 404  # fora da equipe
    assert client.get(f"/treatment?month={month}&user_id={emp}", headers=world["emp"]).status_code == 403
    r = client.post("/adjustments", headers=world["mgr"], json={"kind": "incluir", "user_id": other,
                                                                "requested_at": yesterday_noon().isoformat(), "punch_kind": "entrada",
                                                                "reason": "teste teste"})
    assert r.status_code == 403
    # quem só acompanha não trata: o pedido do próprio colaborador continua pendente
    r = client.post("/adjustments", headers=world["emp"], json={"kind": "incluir", "requested_at": yesterday_noon().isoformat(),
                                                                "punch_kind": "entrada", "reason": "Esqueci de bater"})
    assert r.json()["status"] == "pending"
    assert client.post(f"/adjustments/{r.json()['id']}/revoke", headers=world["mgr"]).status_code == 409
