"""Exportação para a folha: verbas, matrículas, eventos do mês e os leiautes Domínio, Alterdata e CSV."""
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models import AuditLog, User
from app.services import payroll
from app.services.payroll import PersonEvents
from app.services.punching import register_punch
from app.services.timecalc import ScheduleRule, compute_month
from tests.test_pdf import local_utc

TZ = "America/Sao_Paulo"
EVS = [{"key": "he_50", "label": "Horas extras 50%", "unit": "horas"}, {"key": "faltas", "label": "Faltas", "unit": "dias"},
       {"key": "dsr", "label": "DSR perdido por falta", "unit": "dias"}, {"key": "noturno", "label": "Noturno", "unit": "horas"}]


def _pe(code="123"):
    pe = PersonEvents(SimpleNamespace(payroll_code=code, name="Ana", cpf="12345678909"))
    pe.minutes = {"he_50": 90, "noturno": 0}
    pe.days = {"faltas": 1, "dsr": 1}
    pe.falta_dates, pe.dsr_dates = [date(2026, 8, 4)], [date(2026, 8, 9)]
    return pe


def test_lost_dsr_is_the_sunday_of_the_week_with_an_absence():
    days = compute_month([], ScheduleRule(), TZ, 2026, 8, date(2026, 9, 30))
    # 02/08 (domingo) fecha a semana de julho; a semana de 31/08 termina em setembro
    assert payroll.lost_dsr(days) == [date(2026, 8, 9), date(2026, 8, 16), date(2026, 8, 23), date(2026, 8, 30)]


def test_night_hours_use_the_reduced_hour():
    assert payroll.night_reduced(7 * 60) == 8 * 60


def test_dominio_layout():
    cfg = {"system": "dominio", "company_code": "45", "process": "11", "codes": {"he_50": "201", "faltas": "300"}}
    lines = payroll.dominio_txt([_pe(), _pe(code=None)], cfg, EVS, 2026, 8).decode("ascii").split("\r\n")
    assert lines == [
        "10" + "0000000123" + "202608" + "000000201" + "11" + "000000150" + "0000000045",
        "10" + "0000000123" + "202608" + "000000300" + "11" + "000000100" + "0000000045",
        "11202608041", "11202608092", "",
    ]  # sem matrícula e verba sem código (DSR) ficam de fora
    assert len(lines[0]) == 48


def test_alterdata_layout():
    company = SimpleNamespace(cnpj="11.111.111/0001-11")
    cfg = {"system": "alterdata", "company_code": "7", "process": "M", "codes": {"he_50": "21", "dsr": "45"}}
    lines = payroll.alterdata_txt([_pe()], cfg, EVS, company, 2026, 8).decode("ascii").split("\r\n")[:-1]
    assert [len(x) for x in lines] == [90, 90]
    he = lines[0]
    assert he[0:6] == "000001" and he[6:11] == "00007" and he[11:17] == "010826" and he[17:23] == "310826"
    assert he[23:37] == "0" * 14 and he[37:40] == "021" and he[40:54] == "00000000000150"
    assert he[54:60] == "000123" and he[60] == "M" and he[61:75] == "11111111000111" and he[75:90] == "0" * 15
    assert lines[1][0:6] == "000002" and lines[1][37:40] == "045" and lines[1][40:54] == "00000000000100"


def test_config_validation():
    ok = payroll.validate_config({"system": "alterdata", "company_code": "12", "codes": {"he_50": "21", "faltas": ""}})
    assert ok == {"system": "alterdata", "company_code": "12", "process": "M", "codes": {"he_50": "21"}}
    for bad in ({"system": "sap"}, {"system": "alterdata", "company_code": "123456"}, {"system": "alterdata", "codes": {"he_50": "1234"}},
                {"system": "dominio", "process": "M"}, {"system": "csv", "codes": {"bonus": "1"}}):
        try:
            payroll.validate_config(bad)
        except payroll.PayrollError:
            continue
        raise AssertionError(bad)


# --- API ------------------------------------------------------------------------
def _last_monday():
    d = date.today() - timedelta(days=7)
    while d.weekday() != 0:
        d -= timedelta(days=1)
    return d


def test_config_codes_preview_and_export(client, world, db):
    admin, hr, emp = world["admin"], world["hr"], world["ids"]["emp"]
    assert client.get("/payroll/config", headers=world["mgr"]).status_code == 403
    cfg = client.get("/payroll/config", headers=hr).json()
    assert cfg["config"]["system"] == "csv" and [e["key"] for e in cfg["events"]][:2] == ["he_50", "he_100"]

    d = _last_monday()
    user = db.get(User, emp)
    for hhmm, kind in (("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("19:00", "saida")):
        register_punch(db, user, kind=kind, occurred_at=local_utc(d, hhmm), enforce_sequence=False)
    db.commit()
    month = f"{d:%Y-%m}"

    p = client.get(f"/payroll/preview?month={month}", headers=hr).json()
    row = next(r for r in p["rows"] if r["user_id"] == emp)
    assert row["values"]["he_50"] == 2.0  # 10 h num dia de 8 h
    assert "Ana Colab" in p["pending"]["people_without_code"] and "Horas extras 50%" in p["pending"]["events_without_code"]

    # sem código da empresa não sai o TXT; a matrícula repetida é recusada
    body = {"system": "dominio", "company_code": "", "codes": {"he_50": "201"}}
    assert client.put("/payroll/config", headers=hr, json=body).status_code == 200
    assert client.get(f"/payroll/export?month={month}&format=dominio", headers=hr).status_code == 422
    assert client.put("/payroll/config", headers=hr, json={**body, "company_code": "45"}).status_code == 200
    assert client.get(f"/payroll/export?month={month}&format=alterdata", headers=hr).status_code == 422  # outro sistema
    other = world["ids"]["other"]
    dup = {"items": [{"user_id": emp, "code": "77"}, {"user_id": other, "code": "77"}]}
    assert client.put("/payroll/codes", headers=hr, json=dup).status_code == 409
    assert db.get(User, emp).payroll_code is None
    assert client.put("/payroll/codes", headers=hr, json={"items": [{"user_id": emp, "code": "77a"}]}).status_code == 422
    assert client.put("/payroll/codes", headers=hr, json={"items": [{"user_id": emp, "code": "77"}]}).json() == {"changed": 1}

    txt = client.get(f"/payroll/export?month={month}&format=dominio", headers=hr)
    assert txt.status_code == 200 and txt.headers["content-type"].startswith("text/plain")
    assert "10" + "0000000077" + f"{d:%Y%m}" + "000000201" + "11" + "000000200" + "0000000045" in txt.text.split("\r\n")

    csv = client.get(f"/payroll/export?month={month}&format=csv", headers=admin).content.decode("utf-8-sig")
    assert f"{d:%m/%Y};77;Ana Colab;" in csv and ";201;Horas extras 50%;2,00;horas;" in csv

    actions = {(a.entity, a.action) for a in db.execute(select(AuditLog)).scalars()}
    assert {("payroll_config", "update"), ("user_payroll_code", "update"), ("payroll", "export")} <= actions

    # quem usa banco de horas: a hora extra vai para o banco, não para a folha
    assert client.patch(f"/users/{emp}", headers=admin, json={"hour_bank_enabled": True}).status_code == 200
    p = client.get(f"/payroll/preview?month={month}", headers=hr).json()
    assert "he_50" not in next(r for r in p["rows"] if r["user_id"] == emp)["values"]
