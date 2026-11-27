"""Ausências em lote: abono (ponte, recesso) e férias coletivas para várias pessoas, conferir antes, cancelar o lote."""
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog
from tests.test_absences import day_of, request, weekday_before


@pytest.fixture(autouse=True)
def _test_mode(monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)


@pytest.fixture()
def ana(client, world):
    """Admissão antiga: dias úteis passados sem marcação são falta, a menos que justificados."""
    uid = world["ids"]["emp"]
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"admitted_at": "2020-01-01"}).status_code == 200
    return uid


def batch(client, headers, ids, **extra):
    d = extra.pop("day", None) or weekday_before(7)
    body = {"kind": "abono", "start_date": str(d), "end_date": str(d), "reason": "Ponte de feriado", "user_ids": ids, **extra}
    return client.post("/absences/batch", headers=headers, json=body)


@pytest.fixture()
def beto(client, world):
    uid = world["ids"]["other"]
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"admitted_at": "2020-01-01"}).status_code == 200
    return uid


def test_dry_run_then_create_and_effect_on_the_mirror(client, world, ana, beto):
    d = weekday_before(7)
    hr = world["hr"]
    # Ana já tem atestado nesse dia: é pulada; Beto entra
    assert request(client, hr, "atestado_medico", d, d, user_id=ana).status_code == 201
    preview = batch(client, hr, [ana, beto, beto, 99999], day=d, dry_run=True)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["dry_run"] and p["batch_id"] is None
    assert [c["user_id"] for c in p["created"]] == [beto]  # repetido entra uma vez
    reasons = {s["user_id"]: s["reason"] for s in p["skipped"]}
    assert reasons[ana].startswith("Já tem atestado médico") and reasons[99999] == "Colaborador não encontrado"
    assert day_of(client, hr, d, beto)[0]["status"] == "falta"  # conferir não grava nada

    r = batch(client, hr, [ana, beto], day=d)
    assert r.status_code == 200 and r.json()["batch_id"]
    day = day_of(client, hr, d, beto)[0]
    assert day["status"] == "justificada" and day["justification"] == "Abono"


def test_partial_abono_and_validation(client, world, ana, beto):
    hr = world["hr"]
    r = batch(client, hr, [ana, beto], minutes=120)  # queda de energia: 2 h abonadas
    assert r.status_code == 200 and len(r.json()["created"]) == 2
    d = weekday_before(14)
    assert batch(client, hr, [ana], day=d, kind="licenca").status_code == 422  # em lote: só abono e férias
    assert batch(client, hr, [ana], day=d, kind="ferias", minutes=60).status_code == 422  # férias não são parciais
    assert batch(client, hr, [], day=d).status_code == 422


def test_who_can_launch(client, world, ana):
    for who in ("mgr", "emp"):
        assert batch(client, world[who], [ana]).status_code == 403
    r = batch(client, world["adminB"], [ana])  # outra empresa: a pessoa não existe para ela
    assert r.status_code == 200 and r.json()["created"] == [] and r.json()["skipped"][0]["reason"] == "Colaborador não encontrado"


def test_list_and_cancel_the_whole_batch(client, world, ana, beto, db):
    hr = world["hr"]
    d = weekday_before(7)
    bid = batch(client, hr, [ana, beto], day=d).json()["batch_id"]
    (b,) = client.get("/absences/batches", headers=hr).json()
    assert b["batch_id"] == bid and b["kind_label"] == "Abono" and len(b["active"]) == 2 and b["created_by"] == "Rita RH"
    assert client.get("/absences/batches", headers=world["mgr"]).status_code == 403

    r = client.post(f"/absences/batch/{bid}/cancel", headers=hr)
    assert r.status_code == 200 and r.json()["cancelled"] == 2
    assert day_of(client, hr, d, ana)[0]["status"] == "falta"
    assert client.post(f"/absences/batch/{bid}/cancel", headers=hr).status_code == 404
    (b,) = client.get("/absences/batches", headers=hr).json()
    assert b["active"] == [] and b["cancelled"] == 2
    assert client.post(f"/absences/batch/{bid}/cancel", headers=world["adminB"]).status_code == 404  # outra empresa

    actions = [a.action for a in db.execute(select(AuditLog).where(AuditLog.entity == "absence_batch")).scalars()]
    assert actions == ["create_batch", "cancel_batch"]


def test_closed_month_blocks_launch_and_cancel(client, world, ana):
    hr, admin = world["hr"], world["admin"]
    d = weekday_before(40)
    bid = batch(client, hr, [ana], day=d).json()["batch_id"]
    r = client.post(f"/closings/{d:%Y-%m}", headers=admin)  # 40 dias atrás: sempre um mês já encerrado
    assert r.status_code == 200, r.text
    assert batch(client, hr, [ana], day=d).status_code == 409
    assert client.post(f"/absences/batch/{bid}/cancel", headers=hr).status_code == 409
