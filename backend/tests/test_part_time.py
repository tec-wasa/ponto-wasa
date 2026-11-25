"""Jornada de meio período (estágio): 4 h sem intervalo."""
from datetime import date

from app.models import Company, Schedule, User
from app.services.aej import contract_hours
from app.services.folha import schedule_periods
from app.services.mirror import month_days
from app.services.punching import has_break, next_kind
from tests.test_bank_panel import punches
from tests.test_pdf import local_utc


def test_four_hours_without_break(client, world, db):
    r = client.post("/schedules", headers=world["hr"], json={"name": "Estágio manhã", "daily_minutes": 240, "break_minutes": 0,
                                                              "start_time": "08:00", "break_start": "07:00"})
    assert r.status_code == 201, r.text  # o início do intervalo não é validado sem intervalo
    sched_id = r.json()["id"]
    emp = world["ids"]["emp"]
    assert client.patch(f"/users/{emp}", headers=world["admin"], json={"schedule_id": sched_id}).status_code == 200
    db.expire_all()
    user, sched = db.get(User, emp), db.get(Schedule, sched_id)

    assert not has_break(db, user)
    assert schedule_periods(sched) == ["08:00 às 12:00"]
    assert contract_hours(sched)[2:] == ["0800", "1200", "", ""]

    day = date(2026, 8, 3)  # segunda-feira
    punches(db, emp, day, [("08:00", "entrada")])
    assert next_kind(db, user, local_utc(day, "09:00")) == "saida"  # sem intervalo: depois da entrada vem a saída
    punches(db, emp, day, [("12:03", "saida")])
    res = next(d for d in month_days(db, user, db.get(Company, user.company_id), 2026, 8) if d.date == day)
    assert (res.expected, res.worked, res.balance, res.status, res.warnings) == (240, 243, 0, "ok", [])
