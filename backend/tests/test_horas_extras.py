"""Horas extras pagas: faixas e percentuais por tipo de dia, regra da empresa, espelho e relatório."""
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models import AuditLog, User
from app.services import overtime
from app.services.punching import register_punch
from app.services.timecalc import ScheduleRule, compute_month
from tests.test_pdf import local_utc

TZ = "America/Sao_Paulo"
TODAY = date(2026, 9, 30)
RULE = {
    "util": {"limit": 120, "first": 50, "excess": 100},
    "sabado": {"limit": None, "first": 60, "excess": 60},
    "domingo": {"limit": None, "first": 100, "excess": 100},
    "feriado": {"limit": None, "first": 100, "excess": 100},
}


def utc(d, h, m=0):
    return datetime(2026, 8, d) + timedelta(hours=h + 3, minutes=m)  # agosto/2026; 03/08 é segunda


def worked(d, start, end):
    return [(utc(d, *start), "entrada"), (utc(d, 12), "saida"), (utc(d, 13), "entrada"), (utc(d, *end), "saida")]


def test_split_by_band():
    band = {"limit": 120, "first": 50, "excess": 100}
    assert overtime.split(0, band) == []
    assert overtime.split(90, band) == [(50, 90)]
    assert overtime.split(200, band) == [(50, 120), (100, 80)]
    assert overtime.split(200, {"limit": None, "first": 50, "excess": 100}) == [(50, 200)]
    assert overtime.split(30, {"limit": 0, "first": 50, "excess": 100}) == [(100, 30)]


def test_month_by_percent_and_day_type():
    punches = (worked(3, (8, 0), (20, 0))  # segunda: 11 h -> 3 h extras = 2 h a 50 % + 1 h a 100 %
               + worked(4, (8, 0), (18, 0))  # terça: 1 h extra a 50 %
               + worked(8, (8, 0), (12, 0))[:2]  # sábado (folga): 4 h, tudo extra a 60 %
               + worked(9, (9, 0), (13, 0))[:2])  # domingo: 3 h a 100 %
    days = compute_month(punches, ScheduleRule(), TZ, 2026, 8, TODAY, holidays={date(2026, 8, 4): "Feriado teste"})
    ot = overtime.compute(days, RULE)
    # a terça vira feriado: as 9 h trabalhadas são extras a 100 %
    assert ot.by_type == {"util": 180, "sabado": 240, "domingo": 180, "feriado": 540}
    assert ot.by_percent == {50: 120, 60: 240, 100: 60 + 180 + 540}
    assert ot.total == 180 + 240 + 180 + 540
    assert overtime.day_type(next(d for d in days if d.date == date(2026, 8, 4))) == "feriado"


def test_tolerance_and_negative_days_do_not_count():
    punches = worked(3, (8, 0), (17, 8)) + worked(4, (8, 0), (16, 0))  # +8 min (tolerância) e -1 h
    ot = overtime.compute(compute_month(punches, ScheduleRule(), TZ, 2026, 8, TODAY), RULE)
    assert ot.total == 0 and ot.by_percent == {}


# --- API ------------------------------------------------------------------------
def test_company_rule_defaults_validation_and_audit(client, world, db):
    admin = world["admin"]
    c = client.get("/company", headers=admin).json()
    assert c["overtime_rule"]["util"] == {"limit": None, "first": 50, "excess": 50}
    assert c["overtime_rule"]["domingo"]["first"] == 100
    bad = {**RULE, "util": {"limit": 60, "first": 40, "excess": 100}}  # abaixo do mínimo legal
    assert client.patch("/company", headers=admin, json={"overtime_rule": bad}).status_code == 422
    assert client.patch("/company", headers=world["hr"], json={"overtime_rule": RULE}).status_code == 403
    r = client.patch("/company", headers=admin, json={"overtime_rule": RULE})
    assert r.status_code == 200 and r.json()["overtime_rule"]["util"] == RULE["util"]
    log = db.execute(select(AuditLog).where(AuditLog.entity == "company").order_by(AuditLog.id.desc())).scalars().first()
    assert log.after["overtime_rule"]["util"]["limit"] == 120
    assert client.patch("/company", headers=admin, json={"overtime_rule": None}).json()["overtime_rule"]["util"]["limit"] is None


def _last_monday():
    d = date.today() - timedelta(days=7)
    while d.weekday() != 0:
        d -= timedelta(days=1)
    return d


def test_mirror_and_report(client, world, db):
    admin, emp = world["admin"], world["ids"]["emp"]
    assert client.patch("/company", headers=admin, json={"overtime_rule": RULE}).status_code == 200
    d = _last_monday()
    user = db.get(User, emp)
    for hhmm, kind in (("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("20:00", "saida")):
        register_punch(db, user, kind=kind, occurred_at=local_utc(d, hhmm), enforce_sequence=False)
    db.commit()
    month = f"{d:%Y-%m}"

    m = client.get(f"/mirror?month={month}&user_id={emp}", headers=world["hr"]).json()
    assert m["overtime"]["total"] == 180
    assert m["overtime"]["by_percent"] == [{"percent": 50, "minutes": 120}, {"percent": 100, "minutes": 60}]

    csv = client.get(f"/reports/overtime?month={month}&format=csv", headers=world["hr"])
    assert csv.status_code == 200
    text = csv.content.decode("utf-8-sig")
    assert "HE 50% (min)" in text and "HE 100% (min)" in text
    line = next(x for x in text.splitlines() if x.startswith("Ana Colab"))
    assert ";180;3h00;120;0;60;" in line  # 50 %, 60 % (sábado, sem uso) e 100 %
    assert client.get(f"/reports/overtime?month={month}&format=pdf", headers=world["mgr"]).status_code == 200
    assert client.get(f"/reports/overtime?month={month}", headers=world["emp"]).status_code == 403

    # quem usa banco de horas: nada pago, o crédito aparece à parte
    assert client.patch(f"/users/{emp}", headers=admin, json={"hour_bank_enabled": True}).status_code == 200
    assert client.get(f"/mirror?month={month}&user_id={emp}", headers=world["hr"]).json()["overtime"] is None
    text = client.get(f"/reports/overtime?month={month}&format=csv", headers=world["hr"]).content.decode("utf-8-sig")
    assert "Banco de horas: crédito do mês (não pago)" in text
