"""Relatórios gerenciais em CSV e PDF (RF-19)."""
import io

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, User
from app.services import reports
from app.services.punching import register_punch
from tests.test_absences import today, weekday_before
from tests.test_api import past


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)


def rows_of(response):
    assert response.status_code == 200, response.text
    text = response.content.decode("utf-8-sig")
    return [line.split(";") for line in text.split("\r\n") if line]


def pdf_text(response) -> str:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)


def worked_day(db, world):
    emp = db.get(User, world["ids"]["emp"])
    d = past(3, 0)
    for h, kind in ((8, "entrada"), (12, "saida"), (13, "entrada"), (18, "saida")):
        register_punch(db, emp, kind=kind, occurred_at=d.replace(hour=h + 3), enforce_sequence=False)
    db.commit()
    return d.strftime("%Y-%m")


def test_monthly_csv_scope_and_totals(client, world, db):
    month = worked_day(db, world)
    rows = rows_of(client.get(f"/reports/monthly?month={month}", headers=world["mgr"]))
    assert rows[0][0] == "Nome" and len(rows) == 2  # o gestor só vê a equipe: Ana
    ana = rows[1]
    assert ana[0] == "Ana Colab" and ana[3] == "540" and ana[4] == "9h00"

    everyone = rows_of(client.get(f"/reports/monthly?month={month}", headers=world["hr"]))
    assert {"Gil Gestor", "Ana Colab", "Beto Sem Gestor"} <= {r[0] for r in everyone[1:]}


def test_monthly_pdf_and_audit(client, world, db):
    month = worked_day(db, world)
    text = pdf_text(client.get(f"/reports/monthly?month={month}&format=pdf", headers=world["hr"]))
    assert "Fechamento mensal" in text and "Ana Colab" in text and "9h00" in text
    entry = db.execute(select(AuditLog).where(AuditLog.entity == "report_monthly")).scalars().one()
    assert entry.action == "export"


def test_isolation_and_permissions(client, world, db):
    month = worked_day(db, world)
    assert client.get(f"/reports/monthly?month={month}", headers=world["emp"]).status_code == 403
    assert client.get(f"/reports/monthly?month={month}").status_code in (401, 403)
    other = rows_of(client.get(f"/reports/monthly?month={month}", headers=world["adminB"]))
    assert len(other) == 1  # empresa B não tem colaboradores nem enxerga os da A
    assert client.get("/reports/monthly?month=2026-13", headers=world["hr"]).status_code == 422
    assert client.get(f"/reports/monthly?month={month}&format=xls", headers=world["hr"]).status_code == 422


def test_absences_report_hides_health_reason_from_manager(client, world):
    start = weekday_before(7)
    r = client.post("/absences", headers=world["hr"], json={
        "kind": "atestado_medico", "start_date": str(start), "end_date": str(start), "reason": "Consulta de rotina",
        "user_id": world["ids"]["emp"]})
    assert r.status_code == 201, r.text
    client.post("/absences", headers=world["hr"], json={
        "kind": "abono", "start_date": str(start), "end_date": str(start), "reason": "Casamento",
        "user_id": world["ids"]["other"]})
    q = f"/reports/absences?start={start}&end={today()}"

    hr = rows_of(client.get(q, headers=world["hr"]))
    assert len(hr) == 3
    assert any("Consulta de rotina" in r[8] for r in hr[1:])

    mgr = rows_of(client.get(q, headers=world["mgr"]))
    assert len(mgr) == 2 and mgr[1][0] == "Ana Colab"  # só a equipe
    assert mgr[1][8] == "(restrito)" and "Consulta" not in ";".join(mgr[1])

    text = pdf_text(client.get(q + "&format=pdf", headers=world["mgr"]))
    assert "Ana Colab" in text and "Consulta de rotina" not in text
    assert client.get(f"/reports/absences?start={today()}&end={start}", headers=world["hr"]).status_code == 422
    assert client.get(q + "&status=xx", headers=world["hr"]).status_code == 422
    assert client.get(q, headers=world["emp"]).status_code == 403


def test_hour_bank_report(client, world, db):
    emp = world["ids"]["emp"]
    client.patch(f"/users/{emp}", headers=world["hr"], json={"hour_bank_enabled": True, "hour_bank_start": str(weekday_before(20))})
    rows = rows_of(client.get("/reports/hour-bank", headers=world["hr"]))
    assert rows[0][0] == "Nome"
    assert [r[0] for r in rows[1:]] == ["Ana Colab"]
    assert "Banco de horas" in pdf_text(client.get("/reports/hour-bank?format=pdf", headers=world["hr"]))


def test_csv_formula_injection_is_neutralised():
    out = reports.to_csv(["a", "b", "c", "d"], [["=1+1", "+cmd", "-5", "@x"]]).decode("utf-8-sig").split("\r\n")[1]
    assert out == "'=1+1;'+cmd;-5;'@x"  # números negativos continuam números
