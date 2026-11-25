"""Importação de marcações de outro sistema (CSV) como inclusões aprovadas."""
import base64
from datetime import date, datetime

from app.models import Adjustment, AuditLog, Company, User
from app.services.mirror import month_days
from app.services.punch_import import kinds_for
from tests.test_bank_panel import punches

NOW = datetime(2026, 11, 25, 15, 0)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8-sig")).decode()


def cpf(db, uid):
    return db.get(User, uid).cpf


def send(client, headers, text, dry=True, reason="Migração do sistema anterior (RFP)"):
    return client.post(f"/imports/punches?dry_run={str(dry).lower()}", headers=headers, json={"content_base64": b64(text), "reason": reason})


def test_kinds_for():
    assert kinds_for(2) == ["entrada", "saida"]
    assert kinds_for(4) == ["entrada", "inicio_intervalo", "fim_intervalo", "saida"]
    assert kinds_for(3) == ["entrada", "inicio_intervalo", "fim_intervalo"]


def test_import_validates_then_writes_inclusions(client, world, db, monkeypatch):
    monkeypatch.setattr("app.routers.imports._now", lambda: NOW)
    emp, other = world["ids"]["emp"], world["ids"]["other"]
    punches(db, other, date(2026, 11, 4), [("08:00", "entrada")])  # já tem marcação no app: o dia é pulado
    csv = (
        "nome;cpf;data;batida_1;batida_2;batida_3;batida_4;ocorrencia\n"
        f"Ana;{cpf(db, emp)};03/11/2026;07:49;12:40;13:38;(m)18:08;\n"
        f"Ana;{cpf(db, emp)};02/11/2026;;;;;FERIADO: Finados\n"
        f"Beto;{cpf(db, other)};03/11/2026;08:00;12:00;;;\n"
        f"Beto;{cpf(db, other)};04/11/2026;08:00;12:00;13:00;17:00;\n"
    )
    r = send(client, world["hr"], csv)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["total"], j["empty"], j["days"], j["marks"], j["errors"], len(j["skipped"])) == (4, 1, 2, 6, [], 1)
    assert db.query(Adjustment).count() == 0  # a validação não grava nada

    assert send(client, world["hr"], csv, dry=False, reason="curto").status_code == 422
    r = send(client, world["hr"], csv, dry=False)
    assert r.status_code == 200 and r.json()["imported"], r.text
    batch = r.json()["batch"]
    adjs = db.query(Adjustment).filter(Adjustment.decision_note == batch).all()
    assert len(adjs) == 6 and {a.status for a in adjs} == {"approved"}
    assert db.query(AuditLog).filter(AuditLog.action == "import").count() == 1

    ana = db.get(User, emp)
    day = next(d for d in month_days(db, ana, db.get(Company, ana.company_id), 2026, 11) if d.date == date(2026, 11, 3))
    assert day.worked == 291 + 270  # 07:49–12:40 e 13:38–18:08

    # importar de novo: os dias já existem e são pulados
    again = send(client, world["hr"], csv).json()
    assert again["days"] == 0 and len(again["skipped"]) == 3

    lst = client.get("/imports/punches", headers=world["hr"]).json()
    assert lst[0]["batch"] == batch and lst[0]["active"] == 6
    assert client.post(f"/imports/punches/{batch}/undo", headers=world["hr"]).json()["revoked"] == 6
    db.expire_all()
    assert {a.status for a in db.query(Adjustment).filter(Adjustment.decision_note == batch)} == {"revoked"}
    assert client.post(f"/imports/punches/{batch}/undo", headers=world["hr"]).status_code == 404


def test_import_errors_are_all_or_nothing(client, world, db, monkeypatch):
    monkeypatch.setattr("app.routers.imports._now", lambda: NOW)
    emp = world["ids"]["emp"]
    csv = (
        "cpf;data;batidas\n"
        f"{cpf(db, emp)};05/11/2026;08:00 12:00\n"
        "00000000000;05/11/2026;08:00 12:00\n"
        f"{cpf(db, emp)};32/11/2026;08:00\n"
        f"{cpf(db, emp)};06/11/2026;12:00 08:00\n"
        f"{cpf(db, emp)};05/11/2026;09:00 10:00\n"
        f"{cpf(db, emp)};26/11/2026;08:00 12:00\n"
        f"{cpf(db, emp)};07/11/2026;8h\n"
    )
    j = send(client, world["hr"], csv).json()
    assert [e["line"] for e in j["errors"]] == [3, 4, 5, 6, 7, 8]
    assert send(client, world["hr"], csv, dry=False).status_code == 422
    assert db.query(Adjustment).count() == 0


def test_import_accepts_excel_time_formats(client, world, db, monkeypatch):
    monkeypatch.setattr("app.routers.imports._now", lambda: NOW)
    csv = f"cpf;data;batida_1;batida_2\n{cpf(db, world['ids']['emp'])};05/11/2026;8:25;12:43:00\n"
    j = send(client, world["hr"], csv).json()
    assert j["errors"] == [] and j["marks"] == 2


def test_import_permissions_and_closed_month(client, world, db, monkeypatch):
    monkeypatch.setattr("app.routers.imports._now", lambda: NOW)
    csv = f"cpf;data;batida_1;batida_2\n{cpf(db, world['ids']['emp'])};03/10/2026;08:00;12:00\n"
    assert send(client, world["mgr"], csv).status_code == 403
    assert send(client, world["emp"], csv).status_code == 403
    assert client.post("/closings/2026-10", headers=world["hr"]).status_code in (200, 201)
    j = send(client, world["hr"], csv).json()
    assert "fechado" in j["errors"][0]["message"]
    assert send(client, world["hr"], "nome;data\nx;01/11/2026\n").json()["errors"][0]["line"] == 1
