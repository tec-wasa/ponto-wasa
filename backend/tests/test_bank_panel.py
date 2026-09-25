"""Banco de horas (RF-15) e painel do gestor (RF-18)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.config import settings
from app.models import HourBankEntry, User
from app.services.hourbank import months_ago
from app.services.punching import register_punch
from tests.conftest import make_cpf
from tests.test_pdf import local_utc

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)  # AEJ sem INPI (modo de teste)


def punches(db, user_id, day, marks):
    user = db.get(User, user_id)
    for hhmm, kind in marks:
        register_punch(db, user, kind=kind, occurred_at=local_utc(day, hhmm), enforce_sequence=False)
    db.commit()


def iso(day, hhmm) -> str:
    return local_utc(day, hhmm).isoformat() + "Z"


# ============================ banco de horas ================================
AUG = {d: date(2026, 8, d) for d in range(3, 12)}  # 3/8/2026 é segunda-feira


@pytest.fixture()
def bank(client, world, db):
    """Ana com banco desde 03/08. Seg +60, ter -30, qua 0 (tolerância), qui falta, sex incompleto."""
    uid = world["ids"]["emp"]
    r = client.patch(f"/users/{uid}", headers=world["hr"], json={
        "admitted_at": "2026-01-01", "hour_bank_enabled": True, "hour_bank_start": "2026-08-03"})
    assert r.status_code == 200 and r.json()["hour_bank_enabled"] is True
    punches(db, uid, AUG[3], [("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("18:00", "saida")])  # 9 h
    punches(db, uid, AUG[4], [("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("16:30", "saida")])  # 7,5 h
    punches(db, uid, AUG[5], [("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("17:05", "saida")])  # +5 min: tolerância
    punches(db, uid, AUG[7], [("08:00", "entrada")])  # sexta sem saída: incompleto
    return uid


def entry(client, headers, uid, kind, minutes, day, reason="Ajuste combinado com o colaborador"):
    return client.post("/hour-bank/entries", headers=headers, json={
        "user_id": uid, "kind": kind, "minutes": minutes, "entry_date": str(day), "reason": reason})


def test_balance_counts_only_finished_days_after_tolerance_and_ignores_absences(client, world, bank):
    s = client.get("/hour-bank", headers=world["emp"]).json()
    assert s["enabled"] and s["since"] == "2026-08-03"
    # +60 (seg) -30 (ter) = +30; quarta (dentro da tolerância) 0; quinta é falta e sexta é incompleta: fora do banco
    assert s["balance"] == 30 and s["automatic"] == 30 and s["credits"] == 0 and s["compensations"] == 0
    # os dias seguintes (todos faltas) também não drenam o banco sozinhos
    stmt = client.get("/hour-bank/statement?start=2026-08-01&end=2026-09-30", headers=world["emp"]).json()
    assert [(l["date"], l["minutes"]) for l in stmt["lines"]] == [("2026-08-03", 60), ("2026-08-04", -30)]


def test_manual_entries_credit_and_compensate_with_running_statement(client, world, bank):
    assert entry(client, world["hr"], bank, "credito", 45, AUG[10]).status_code == 201
    assert entry(client, world["hr"], bank, "compensacao", 60, AUG[11], "Folga compensatória de 12/08").status_code == 201
    s = client.get("/hour-bank", headers=world["emp"]).json()
    assert (s["balance"], s["credits"], s["compensations"]) == (15, 45, 60)
    stmt = client.get("/hour-bank/statement?start=2026-08-04&end=2026-08-31", headers=world["emp"]).json()
    assert stmt["opening"] == 60  # saldo antes de 04/08 (só a segunda)
    assert [(l["date"], l["minutes"], l["balance"], l["source"]) for l in stmt["lines"]] == [
        ("2026-08-04", -30, 30, "automatico"), ("2026-08-10", 45, 75, "lancamento"), ("2026-08-11", -60, 15, "lancamento")]
    assert stmt["closing"] == 15
    assert "Folga compensatória" in stmt["lines"][-1]["description"]
    assert len(client.get("/hour-bank/entries", headers=world["emp"]).json()) == 2


def test_entry_rules(client, world, bank, db):
    other = world["ids"]["other"]  # não usa banco
    assert entry(client, world["hr"], other, "credito", 30, AUG[10]).status_code == 409
    assert entry(client, world["hr"], bank, "credito", 30, date.today() + timedelta(days=2)).status_code == 422  # futura
    assert entry(client, world["hr"], bank, "credito", 30, date(2026, 7, 1)).status_code == 422  # antes do início do banco
    assert entry(client, world["hr"], bank, "compensacao", 31, AUG[10]).status_code == 409  # saldo é 30: insuficiente
    assert entry(client, world["hr"], bank, "credito", 0, AUG[10]).status_code == 422
    assert entry(client, world["hr"], bank, "sorteio", 10, AUG[10]).status_code == 422
    assert entry(client, world["hr"], bank, "credito", 10, AUG[10], "ruim").status_code == 422  # motivo obrigatório
    assert entry(client, world["mgr"], bank, "credito", 10, AUG[10]).status_code == 403  # só RH/admin lançam
    assert entry(client, world["emp"], bank, "credito", 10, AUG[10]).status_code == 403
    assert entry(client, world["adminB"], bank, "credito", 10, AUG[10]).status_code == 404  # outra empresa
    assert db.query(HourBankEntry).count() == 0  # nenhuma tentativa inválida gravou algo

    # mês fechado não recebe lançamento
    assert client.post("/closings/2026-08", headers=world["hr"]).status_code == 200
    assert entry(client, world["hr"], bank, "credito", 10, AUG[10]).status_code == 409


def test_entries_are_append_only_and_audited(client, world, bank, db, engine):
    assert entry(client, world["hr"], bank, "credito", 45, AUG[10]).status_code == 201
    row = db.execute(select(HourBankEntry)).scalar_one()
    row.minutes = 999
    from app.models import ImmutableError
    with pytest.raises(ImmutableError):
        db.flush()
    db.rollback()
    for sql in ("UPDATE hour_bank_entries SET minutes = 1", "DELETE FROM hour_bank_entries"):
        with engine.begin() as conn, pytest.raises(DatabaseError):
            conn.execute(text(sql))
    trail = client.get("/audit?entity=hour_bank_entry", headers=world["hr"]).json()
    assert trail and trail[0]["action"] == "create" and trail[0]["after"]["minutes"] == 45
    # corrigir = lançar o contrário
    assert entry(client, world["hr"], bank, "compensacao", 45, AUG[11], "Estorno do crédito lançado por engano").status_code == 201
    assert client.get("/hour-bank", headers=world["emp"]).json()["balance"] == 30


def test_alerts_limit_and_compensation_deadline(client, world, bank):
    assert client.get("/hour-bank", headers=world["emp"]).json()["alerts"] == []
    r = client.patch("/company", headers=world["admin"], json={"bank_max_minutes": 20})
    assert r.status_code == 200 and r.json()["bank_max_minutes"] == 20
    codes = [a["code"] for a in client.get("/hour-bank", headers=world["emp"]).json()["alerts"]]
    assert codes == ["acima_do_limite"]  # saldo 30 > limite 20

    client.patch("/company", headers=world["admin"], json={"bank_max_minutes": 1000, "bank_expiry_months": 1})
    s = client.get("/hour-bank", headers=world["emp"]).json()
    assert s["at_risk_minutes"] == 30 and [a["code"] for a in s["alerts"]] == ["prazo_de_compensacao"]  # 30 min com mais de 1 mês

    # compensar tudo resolve o alerta
    assert entry(client, world["hr"], bank, "compensacao", 30, AUG[10]).status_code == 201
    assert client.get("/hour-bank", headers=world["emp"]).json()["alerts"] == []
    assert client.patch("/company", headers=world["admin"], json={"bank_expiry_months": 99}).status_code == 422
    assert client.patch("/company", headers=world["hr"], json={"bank_max_minutes": 5}).status_code == 403  # só o administrador


def test_hour_bank_permissions_and_disabled_users(client, world, bank):
    ids = world["ids"]
    assert client.get("/hour-bank", headers=world["other"]).json() == {"user_id": ids["other"], "enabled": False, "balance": 0, "alerts": []}
    assert client.get(f"/hour-bank?user_id={bank}", headers=world["mgr"]).status_code == 200  # gestor vê a equipe
    assert client.get(f"/hour-bank?user_id={bank}", headers=world["other"]).status_code == 404  # colega não
    assert client.get(f"/hour-bank?user_id={bank}", headers=world["adminB"]).status_code == 404  # outra empresa não
    assert client.get("/hour-bank/statement?start=2026-09-01&end=2026-08-01", headers=world["emp"]).status_code == 422
    team = client.get("/hour-bank/team", headers=world["mgr"]).json()
    assert [t["name"] for t in team] == ["Ana Colab"] and team[0]["balance"] == 30
    assert client.get("/hour-bank/team", headers=world["emp"]).status_code == 403
    assert client.get("/hour-bank/team", headers=world["hr"]).status_code == 200


def test_enabling_the_bank_defaults_the_start_to_today(client, world):
    r = client.patch(f"/users/{world['ids']['other']}", headers=world["hr"], json={"hour_bank_enabled": True})
    assert r.json()["hour_bank_start"] == datetime.now(TZ).date().isoformat()
    assert client.get("/hour-bank", headers=world["other"]).json()["balance"] == 0  # começa zerado


def test_months_ago_handles_month_ends_and_years():
    assert months_ago(date(2026, 9, 24), 6) == date(2026, 3, 24)
    assert months_ago(date(2026, 3, 31), 1) == date(2026, 2, 28)  # sem 31/02
    assert months_ago(date(2028, 3, 31), 1) == date(2028, 2, 29)  # ano bissexto
    assert months_ago(date(2026, 1, 15), 3) == date(2025, 10, 15)


def test_aej_reports_bank_movements_and_absences(client, world, bank):
    entry(client, world["hr"], bank, "credito", 45, AUG[10])
    entry(client, world["hr"], bank, "compensacao", 60, AUG[11])
    r = client.get("/exports/aej?start=2026-08-03&end=2026-08-11", headers=world["hr"])
    assert r.status_code == 200 and "x-ponto-warning" in r.headers
    lines = r.content.decode("latin-1").split("\r\n")
    idt = next(l.split("|")[1] for l in lines if l.startswith("03|") and "Ana Colab" in l)
    moves = [l for l in lines if l.startswith(f"07|{idt}|3|")]
    assert moves == [f"07|{idt}|3|2026-08-03|60|1", f"07|{idt}|3|2026-08-04|30|2",
                     f"07|{idt}|3|2026-08-10|45|1", f"07|{idt}|3|2026-08-11|60|2"]
    assert f"07|{idt}|2|2026-08-06||" in lines  # a falta de quinta continua como falta não justificada
    assert lines[-2].startswith("99|") and lines[-2].split("|")[7] == str(len([l for l in lines if l.startswith("07|")]))


# ============================ painel do gestor ==============================
MON, SAT = date(2026, 8, 17), date(2026, 8, 22)


def dash(client, headers, at, **params):
    q = f"at={at}" + "".join(f"&{k}={v}" for k, v in params.items())
    return client.get(f"/dashboard?{q}", headers=headers)


def states(resp):
    return {p["name"]: p["state"] for p in resp.json()["people"]}


def test_dashboard_states_for_the_team(client, world, db):
    ids = world["ids"]
    punches(db, ids["emp"], MON, [("08:20", "entrada")])  # atrasada 20 min
    r = dash(client, world["mgr"], iso(MON, "09:30"))
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == "2026-08-17T09:30" and body["date"] == "2026-08-17"
    assert [p["name"] for p in body["people"]] == ["Ana Colab"]  # o gestor vê só a equipe
    ana = body["people"][0]
    assert (ana["state"], ana["first_entry"], ana["late_minutes"], ana["worked_minutes"]) == ("presente", "08:20", 20, 70)
    assert body["summary"]["total"] == 1 and body["summary"]["presente"] == 1 and body["summary"]["late"] == 1


def test_dashboard_all_states_for_hr(client, world, db):
    ids = world["ids"]
    mk = lambda name, email: client.post("/users", headers=world["hr"], json={  # noqa: E731
        "name": name, "email": email, "password": "senha-forte-123", "cpf": make_cpf(900000000 + len(email)), "schedule_id": world["sched"]["id"]}).json()["id"]
    carla, dani, edu = mk("Carla Intervalo", "carla@a.com"), mk("Dani Noturna", "dani@a.com"), mk("Edu Esqueceu", "edu@a.com")
    night = client.post("/schedules", headers=world["hr"], json={"name": "Noite", "start_time": "22:00", "break_minutes": 0,
                                                                 "crosses_midnight": True}).json()["id"]
    client.patch(f"/users/{dani}", headers=world["hr"], json={"schedule_id": night})  # turno que vira a meia-noite
    punches(db, ids["emp"], MON, [("08:00", "entrada")])  # Ana presente
    punches(db, ids["other"], MON, [("07:55", "entrada"), ("09:00", "saida")])  # Beto saiu
    punches(db, carla, MON, [("08:00", "entrada"), ("12:00", "inicio_intervalo")])  # em intervalo às 12:30
    punches(db, dani, MON - timedelta(days=1), [("22:00", "entrada")])  # turno noturno: presente à 01:00 do dia seguinte
    punches(db, edu, MON - timedelta(days=2), [("08:00", "entrada")])  # entrada esquecida há mais de 16 h

    at_noon = states(dash(client, world["hr"], iso(MON, "12:30")))
    assert at_noon == {
        "Administrador": "sem_marcacao", "Gil Gestor": "sem_marcacao",  # dia útil, já passou do início e não marcaram
        "Ana Colab": "presente", "Beto Sem Gestor": "saiu", "Carla Intervalo": "em_intervalo",
        "Dani Noturna": "presente",  # entrada de domingo 22:00, 14h30 antes: dentro do limite de 16 h
        "Edu Esqueceu": "incompleto"}  # entrada de sábado, 3 dias sem saída: sinalizada, não escondida
    body = dash(client, world["hr"], iso(MON, "12:30")).json()
    assert [p["state"] for p in body["people"]] == [  # ordenado por necessidade de atenção
        "sem_marcacao", "sem_marcacao", "incompleto", "presente", "presente", "em_intervalo", "saiu"]
    assert body["summary"]["sem_marcacao"] == 2 and body["summary"]["incompleto"] == 1 and body["summary"]["total"] == 7
    assert next(p for p in body["people"] if p["name"] == "Administrador")["no_schedule"] is True  # sinalizado, não escondido
    # 16h30 depois da entrada, a Dani passa a "saída não registrada"
    assert states(dash(client, world["hr"], iso(MON, "14:30")))["Dani Noturna"] == "incompleto"

    # às 01:00 de segunda, a Dani está no turno noturno iniciado no domingo às 22:00
    assert states(dash(client, world["hr"], iso(MON, "01:00")))["Dani Noturna"] == "presente"
    # cedo demais para cobrar: ninguém "sem marcação" antes do início da jornada
    early = states(dash(client, world["hr"], iso(MON, "07:30")))
    assert early["Gil Gestor"] == "aguardando"
    # sábado: quem não trabalha fica de folga
    assert states(dash(client, world["hr"], iso(SAT, "10:00")))["Gil Gestor"] == "folga"


def test_dashboard_orders_by_attention_and_counts_pending_adjustments(client, world, db):
    ids = world["ids"]
    punches(db, ids["emp"], MON, [("08:00", "entrada"), ("17:00", "saida")])
    a = client.post("/adjustments", headers=world["emp"], json={
        "kind": "incluir", "requested_at": iso(MON, "12:00"), "punch_kind": "saida", "reason": "Esqueci de bater"})
    assert a.status_code == 201
    body = dash(client, world["mgr"], iso(MON, "18:00")).json()
    assert body["summary"]["pending_adjustments"] == 1 and body["summary"]["saiu"] == 1
    assert [p["state"] for p in dash(client, world["hr"], iso(MON, "18:00")).json()["people"]][0] == "sem_marcacao"  # atenção primeiro


def test_dashboard_bank_and_access_rules(client, world, db, bank):
    body = dash(client, world["mgr"], iso(MON, "10:00"), bank="true").json()
    ana = next(p for p in body["people"] if p["name"] == "Ana Colab")
    assert ana["bank_balance"] == 30 and ana["bank_alerts"] == []
    client.patch("/company", headers=world["admin"], json={"bank_max_minutes": 10})
    body = dash(client, world["mgr"], iso(MON, "10:00"), bank="true").json()
    assert body["summary"]["bank_alerts"] == 1
    assert "bank_balance" not in dash(client, world["mgr"], iso(MON, "10:00")).json()["people"][0]  # só com ?bank=true

    assert dash(client, world["emp"], iso(MON, "10:00")).status_code == 403  # colaborador não vê o painel
    assert client.get("/dashboard").status_code == 401
    future = (datetime.now(TZ) + timedelta(days=1)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert dash(client, world["mgr"], future).status_code == 422  # só presente ou passado
    now = client.get("/dashboard", headers=world["mgr"])  # sem `at`: agora
    assert now.status_code == 200 and now.json()["people"][0]["name"] == "Ana Colab"


def test_dashboard_ignores_disregarded_punches(client, world, db):
    ana = world["ids"]["emp"]
    punches(db, ana, MON, [("08:00", "entrada")])
    from sqlalchemy import select as sel

    from app.models import Punch
    pid = db.execute(sel(Punch.id).where(Punch.user_id == ana)).scalar_one()
    adj = client.post("/adjustments", headers=world["emp"], json={"kind": "desconsiderar", "target_punch_id": pid, "reason": "Marcação por engano"}).json()
    client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": True})
    assert states(dash(client, world["mgr"], iso(MON, "10:00")))["Ana Colab"] == "sem_marcacao"  # a entrada desconsiderada não conta
