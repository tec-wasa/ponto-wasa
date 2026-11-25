"""Feriados no cálculo (nacionais, opcionais e da empresa) e folhas de ponto de todos num PDF."""
import io
from datetime import date

import pytest
from pypdf import PdfReader

from app.services import holidays

pytestmark = pytest.mark.usefixtures("real_holidays")


def test_national_holidays_and_easter():
    assert holidays.easter(2026) == date(2026, 4, 5) and holidays.easter(2027) == date(2027, 3, 28)
    n = holidays.national(2026)
    assert n[date(2026, 4, 3)] == "Sexta-feira Santa" and date(2026, 11, 20) in n and date(2026, 12, 25) in n
    assert date(2026, 2, 16) not in n  # Carnaval é ponto facultativo: só se a empresa marcar
    opt = holidays.optional(2026, True, True)
    assert opt[date(2026, 2, 16)] == "Carnaval" and opt[date(2026, 2, 17)] == "Carnaval" and opt[date(2026, 6, 4)] == "Corpus Christi"


def _days(client, h, month):
    return {d["date"]: d for d in client.get(f"/mirror?month={month}", headers=h).json()["days"]}


def test_holiday_is_not_an_absence(client, world):
    client.patch(f"/users/{world['ids']['emp']}", headers=world["admin"], json={"admitted_at": "2026-01-01"})
    days = _days(client, world["emp"], "2026-04")
    assert days["2026-04-03"]["status"] == "feriado" and days["2026-04-03"]["holiday"] == "Sexta-feira Santa"
    assert days["2026-04-03"]["balance"] == 0 and days["2026-04-21"]["status"] == "feriado"
    assert days["2026-04-06"]["status"] == "falta"  # dia útil comum continua falta


def test_company_holidays_and_options(client, world):
    adm, hr = world["admin"], world["hr"]
    client.patch(f"/users/{world['ids']['emp']}", headers=adm, json={"admitted_at": "2026-01-01"})
    body = {"date": "2026-07-02", "name": "Independência da Bahia", "recurring": True}
    assert client.post("/holidays", headers=hr, json=body).status_code == 403
    r = client.post("/holidays", headers=adm, json=body)
    assert r.status_code == 201
    assert client.post("/holidays", headers=adm, json=body).status_code == 409  # já é feriado
    assert _days(client, world["emp"], "2026-07")["2026-07-02"]["status"] == "feriado"
    cal = client.get("/holidays?year=2027", headers=world["emp"]).json()
    assert any(h["date"] == "2027-07-02" and h["source"] == "empresa" for h in cal["holidays"])  # repete todo ano
    assert client.patch("/holidays/options", headers=adm, json={"carnaval": True}).json()["carnaval"] is True
    assert _days(client, world["emp"], "2026-02")["2026-02-16"]["status"] == "feriado"
    assert client.delete(f"/holidays/{r.json()['id']}", headers=adm).status_code == 204
    assert _days(client, world["emp"], "2026-07")["2026-07-02"]["status"] == "falta"


def test_closed_month_blocks_holiday_changes(client, world, db):
    from app.models import Closing, Company
    company = db.query(Company).filter(Company.name == "Empresa A").one()
    db.add(Closing(company_id=company.id, month="2026-03", status="closed"))
    db.commit()
    r = client.post("/holidays", headers=world["admin"], json={"date": "2026-03-19", "name": "São José", "recurring": False})
    assert r.status_code == 409 and "fechado" in r.json()["detail"]


def test_all_folhas_in_one_pdf_follow_scope(client, world):
    r = client.get("/mirror/folhas.pdf?month=2026-04", headers=world["hr"])
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('folhas-de-ponto-2026-04.pdf"')
    company_pages = len(PdfReader(io.BytesIO(r.content)).pages)
    assert company_pages >= 3  # a empresa toda (sem a própria pessoa)
    mgr = client.get("/mirror/folhas.pdf?month=2026-04", headers=world["mgr"])
    assert len(PdfReader(io.BytesIO(mgr.content)).pages) == 1  # só a equipe do gestor
    assert client.get("/mirror/folhas.pdf?month=2026-04", headers=world["emp"]).status_code == 403
