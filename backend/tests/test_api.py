import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.models import ArpEvent, ImmutableError, Punch, User
from app.services.punching import register_punch
from tests.conftest import drop_immutability_guard, login, make_cpf


def past(days, hour=12):
    d = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0) - timedelta(days=days)
    return d.replace(hour=hour)


def base_nsr(client, headers) -> int:
    """Quantos registros (todos os tipos) o ARP da empresa já tem: o próximo NSR é este + 1."""
    return client.get("/punches-integrity", headers=headers).json()["checked"]


# --- Autenticação e permissões ----------------------------------------------
def test_login_wrong_password(client, world):
    r = client.post("/auth/login", json={"email": "ana@a.com", "password": "errada-errada"})
    assert r.status_code == 401


def test_requires_token(client, world):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/punches", json={}).status_code == 401


def test_refresh_token_flow(client, world):
    r = client.post("/auth/login", json={"email": "ana@a.com", "password": "senha-forte-123"}).json()
    assert client.post("/auth/refresh", json={"refresh_token": r["refresh_token"]}).status_code == 200
    # access token não serve como refresh
    assert client.post("/auth/refresh", json={"refresh_token": r["access_token"]}).status_code == 401


def test_employee_cannot_manage_users(client, world):
    r = client.post("/users", headers=world["emp"], json={
        "name": "X Y", "email": "x@a.com", "password": "senha-forte-123", "cpf": make_cpf(300000001)})
    assert r.status_code == 403


def test_hr_cannot_create_privileged_roles(client, world):
    r = client.post("/users", headers=world["hr"], json={
        "name": "X Y", "email": "x@a.com", "password": "senha-forte-123", "role": "admin", "cpf": make_cpf(300000001)})
    assert r.status_code == 403


def test_tenant_isolation(client, world):
    assert client.get("/users", headers=world["adminB"]).json()[0]["email"] == "admin@b.com"
    r = client.get(f"/mirror?month=2026-08&user_id={world['ids']['emp']}", headers=world["adminB"])
    assert r.status_code == 404


def test_manager_sees_only_team(client, world):
    ids = world["ids"]
    assert client.get(f"/mirror?month=2026-08&user_id={ids['emp']}", headers=world["mgr"]).status_code == 200
    assert client.get(f"/mirror?month=2026-08&user_id={ids['other']}", headers=world["mgr"]).status_code == 404
    assert client.get(f"/mirror?month=2026-08&user_id={ids['mgr']}", headers=world["emp"]).status_code == 404


# --- CPF ---------------------------------------------------------------------
def test_cpf_is_required_valid_and_unique(client, world):
    base = {"name": "Novo Nome", "email": "novo@a.com", "password": "senha-forte-123"}
    assert client.post("/users", headers=world["hr"], json=base).status_code == 422  # sem CPF
    assert client.post("/users", headers=world["hr"], json={**base, "cpf": "123.456.789-00"}).status_code == 422
    assert client.post("/users", headers=world["hr"], json={**base, "cpf": "111.111.111-11"}).status_code == 422
    ok = client.post("/users", headers=world["hr"], json={**base, "cpf": "529.982.247-25"})
    assert ok.status_code == 201 and ok.json()["cpf"] == "52998224725"  # normalizado para dígitos
    dup = client.post("/users", headers=world["hr"], json={**base, "email": "outro@a.com", "cpf": "52998224725"})
    assert dup.status_code == 409


# --- Registro de ponto, NSR e imutabilidade ---------------------------------
def test_punch_sequence_and_nsr(client, world):
    h = world["emp"]
    first = base_nsr(client, world["hr"]) + 1
    a = client.post("/punches", headers=h, json={}).json()
    b = client.post("/punches", headers=h, json={}).json()
    assert (a["kind"], b["kind"]) == ("entrada", "inicio_intervalo")  # a jornada tem intervalo: a ordem decide o tipo
    assert (a["nsr"], b["nsr"]) == (first, first + 1)
    assert client.post("/punches", headers=h, json={"kind": "saida"}).status_code == 409  # esperado: entrada


def test_nsr_is_shared_across_users_and_record_types_without_gaps(client, world):
    before = base_nsr(client, world["hr"])
    assert before >= 6  # empresa (2), admin (5) e 4 usuários (5) já ocuparam NSR: a sequência é única
    for h in (world["emp"], world["other"], world["emp"], world["other"]):
        client.post("/punches", headers=h, json={})
    nsrs = sorted(p["nsr"] for p in client.get("/punches", headers=world["emp"]).json())
    assert nsrs == [before + 1, before + 3]
    assert client.get("/punches-integrity", headers=world["hr"]).json() == {
        "ok": True, "checked": before + 4, "problems": []}


def test_nsr_is_independent_per_company(client, world):
    client.post("/users", headers=world["adminB"], json={
        "name": "Carla B", "email": "c@b.com", "password": "senha-forte-123", "cpf": make_cpf(400000001),
        "must_change_password": False})
    hb = login(client, "c@b.com")
    first_b = base_nsr(client, world["adminB"]) + 1
    assert client.post("/punches", headers=hb, json={}).json()["nsr"] == first_b
    assert first_b < base_nsr(client, world["hr"])  # a sequência da empresa A é outra


def test_idempotency_key_prevents_duplicate(client, world):
    h = world["emp"]
    a = client.post("/punches", headers=h, json={"client_key": "abc"}).json()
    b = client.post("/punches", headers=h, json={"client_key": "abc"}).json()
    assert a["id"] == b["id"]
    assert len(client.get("/punches", headers=h).json()) == 1


def test_collector_is_recorded_and_validated(client, world):
    h = world["emp"]
    assert client.post("/punches", headers=h, json={"collector": "01"}).json()["collector"] == "01"
    assert client.post("/punches", headers=h, json={"collector": "99"}).status_code == 422
    assert client.post("/punches", headers=h, json={}).json()["collector"] == "02"


def test_gps_only_stored_with_consent(client, world):
    h = world["emp"]
    a = client.post("/punches", headers=h, json={"latitude": -23.5, "longitude": -46.6}).json()
    assert a["latitude"] is None
    client.post("/auth/consent-gps", headers=h)
    b = client.post("/punches", headers=h, json={"latitude": -23.5, "longitude": -46.6, "accuracy_m": 12}).json()
    assert b["latitude"] == -23.5 and b["accuracy_m"] == 12


def test_receipt_has_required_fields_and_access_control(client, world, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "inpi_number", "12345678901234567")
    p = client.post("/punches", headers=world["emp"], json={}).json()
    r = client.get(f"/punches/{p['id']}/receipt", headers=world["emp"]).json()
    assert r["title"] == "Comprovante de Registro de Ponto do Trabalhador"  # Art. 79, I
    assert r["nsr"] == p["nsr"] and r["hash"] == p["hash"] and len(r["hash"]) == 64
    assert r["employer"] == "Empresa A" and r["cnpj"] == "11.111.111/0001-11"
    assert r["employee"] == "Ana Colab" and len(r["cpf"]) == 11 and r["inpi"] == "12345678901234567"
    assert client.get(f"/punches/{p['id']}/receipt", headers=world["other"]).status_code == 404
    assert client.get(f"/punches/{p['id']}/receipt", headers=world["adminB"]).status_code == 404


def test_recent_receipts_cover_last_48_hours(client, world, db):
    client.post("/punches", headers=world["emp"], json={})
    emp = db.get(User, world["ids"]["emp"])
    register_punch(db, emp, kind="saida", occurred_at=past(3), enforce_sequence=False)  # 72 h atrás
    db.commit()
    assert len(client.get("/receipts", headers=world["emp"]).json()) == 1
    assert len(client.get("/receipts?hours=120", headers=world["emp"]).json()) == 2


def test_server_time_endpoint(client, world):
    r = client.get("/time")
    assert r.status_code == 200 and r.json()["utc"].endswith("Z")


def test_punch_hash_follows_portaria_fields(client, world, db):
    """Recalcula o SHA-256 de forma independente, a partir dos campos do registro tipo 7 do AFD."""
    h = world["emp"]
    p1 = client.post("/punches", headers=h, json={"collector": "01"}).json()
    p2 = client.post("/punches", headers=h, json={"collector": "02"}).json()

    def dh(dt):  # AAAA-MM-ddThh:mm:00-0300 (sem segundos)
        return (dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M") + ":00-0300"

    rows = {p.nsr: p for p in db.execute(select(Punch)).scalars()}
    prev = ""
    for out in (p1, p2):
        row = rows[out["nsr"]]
        raw = (f"{row.nsr:09d}7{dh(row.occurred_at)}{int(row.cpf):012d}{dh(row.recorded_at)}"
               f"{row.collector}{int(row.offline)}{prev}")
        assert hashlib.sha256(raw.encode()).hexdigest() == row.hash == out["hash"]
        prev = row.hash
    assert rows[p2["nsr"]].prev_hash == rows[p1["nsr"]].hash


def test_records_are_immutable_orm_and_db(client, world, db, engine):
    client.post("/punches", headers=world["emp"], json={})
    punch = db.query(Punch).first()
    punch.collector = "01"
    with pytest.raises(ImmutableError):
        db.flush()
    db.rollback()
    event = db.query(ArpEvent).first()
    event.data = {}
    with pytest.raises(ImmutableError):
        db.flush()
    db.rollback()
    for sql in ("UPDATE punches SET collector = '01'", "DELETE FROM punches", "DELETE FROM audit_log",
                "UPDATE arp_events SET record_type = '6'", "DELETE FROM arp_events"):
        with engine.begin() as conn, pytest.raises(DatabaseError):
            conn.execute(text(sql))


def test_tampering_is_detected_by_integrity_check(client, world, db, engine):
    for _ in range(3):
        client.post("/punches", headers=world["emp"], json={})
    target_nsr = sorted(p["nsr"] for p in client.get("/punches", headers=world["emp"]).json())[1]
    with engine.begin() as conn:  # atacante com acesso direto remove o gatilho e altera o dado
        drop_immutability_guard(conn, "punches")
        conn.execute(text(f"UPDATE punches SET collector = '01' WHERE nsr = {target_nsr}"))
    r = client.get("/punches-integrity", headers=world["hr"]).json()
    assert r["ok"] is False and any(f"NSR {target_nsr}" in p for p in r["problems"])


def test_deleting_a_record_leaves_a_gap_that_is_detected(client, world, db, engine):
    for _ in range(3):
        client.post("/punches", headers=world["emp"], json={})
    nsr = sorted(p["nsr"] for p in client.get("/punches", headers=world["emp"]).json())[1]
    with engine.begin() as conn:
        drop_immutability_guard(conn, "punches", delete=True)
        conn.execute(text(f"DELETE FROM punches WHERE nsr = {nsr}"))
    r = client.get("/punches-integrity", headers=world["hr"]).json()
    assert r["ok"] is False and any("ausente" in p for p in r["problems"])


# --- Eventos do ARP (tipos 2, 5 e 6 do AFD) -----------------------------------
def events(db, record_type=None):
    q = select(ArpEvent).order_by(ArpEvent.nsr)
    rows = db.execute(q).scalars().all()
    return [e for e in rows if record_type is None or e.record_type == record_type]


def test_employee_and_employer_changes_are_recorded_in_the_arp(client, world, db):
    before = len(events(db))
    ids = world["ids"]
    client.patch(f"/users/{ids['emp']}", headers=world["hr"], json={"name": "Ana Renomeada"})
    client.patch(f"/users/{ids['emp']}", headers=world["hr"], json={"active": False})
    client.patch(f"/users/{ids['emp']}", headers=world["hr"], json={"active": True})
    client.patch("/company", headers=world["admin"], json={"workplace": "Rua A, 1 - São Paulo"})
    new = events(db)[before:]
    assert [(e.record_type, e.data.get("op")) for e in new] == [("5", "A"), ("5", "E"), ("5", "I"), ("2", None)]
    hr_cpf = db.get(User, ids["hr"]).cpf
    assert new[0].actor_cpf == hr_cpf and new[0].data["cpf"] == db.get(User, ids["emp"]).cpf
    assert new[3].data["workplace"] == "Rua A, 1 - São Paulo"
    assert client.get("/punches-integrity", headers=world["hr"]).json()["ok"]


def test_service_availability_events(db, world):
    from app.services import arp
    before = len(events(db, "6"))
    assert arp.record_service_event_all(db, arp.EVENT_AVAILABLE) == 2  # uma por empresa
    assert arp.record_service_event_all(db, arp.EVENT_UNAVAILABLE) == 2
    codes = [e.data["event"] for e in events(db, "6")[before:]]
    assert sorted(codes) == ["07", "07", "08", "08"]


# --- Espelho -----------------------------------------------------------------
def test_mirror_totals(client, world, db):
    emp = db.get(User, world["ids"]["emp"])
    d = past(3, 0)
    for h, kind in ((8, "entrada"), (12, "saida"), (13, "entrada"), (18, "saida")):
        register_punch(db, emp, kind=kind, occurred_at=d.replace(hour=h + 3), enforce_sequence=False)
    db.commit()
    month = d.strftime("%Y-%m")
    body = client.get(f"/mirror?month={month}", headers=world["emp"]).json()
    assert body["totals"]["worked_minutes"] == 540
    assert client.get("/mirror?month=2026-13", headers=world["emp"]).status_code == 422


def test_new_employee_has_no_absences_before_creation(client, world):
    month = datetime.now(UTC).strftime("%Y-%m")
    t = client.get(f"/mirror?month={month}", headers=world["emp"]).json()["totals"]
    assert t["absences"] == 0 and t["balance_minutes"] == 0


def test_admission_date_can_be_set_backwards(client, world):
    r = client.patch(f"/users/{world['ids']['emp']}", headers=world["hr"], json={"admitted_at": "2020-01-01"})
    assert r.status_code == 200 and r.json()["admitted_at"] == "2020-01-01"
    t = client.get("/mirror?month=2026-08", headers=world["emp"]).json()["totals"]
    assert t["absences"] > 0  # agora conta as faltas desde a admissão


# --- Ajustes (tratamento: nunca alteram o ARP) ---------------------------------
def _request_inclusion(client, headers, when):
    return client.post("/adjustments", headers=headers, json={
        "kind": "incluir", "requested_at": when.isoformat(), "punch_kind": "entrada",
        "reason": "Esqueci de bater o ponto"})


def test_approved_inclusion_is_treatment_not_an_arp_record(client, world):
    before = base_nsr(client, world["hr"])
    when = past(2)
    adj = _request_inclusion(client, world["emp"], when).json()
    assert adj["status"] == "pending"
    r = client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": True, "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    assert client.get("/punches", headers=world["emp"]).json() == []  # nenhuma marcação nova no REP
    assert base_nsr(client, world["hr"]) == before  # nenhum NSR consumido
    month = when.strftime("%Y-%m")
    days = client.get(f"/mirror?month={month}", headers=world["emp"]).json()["days"]
    day = next(d for d in days if d["date"] == (when - timedelta(hours=3)).strftime("%Y-%m-%d"))
    assert any("entrada" in p for p in day["punches"])  # mas o espelho considera a inclusão
    trail = client.get("/audit?entity=adjustment", headers=world["hr"]).json()
    assert {t["action"] for t in trail} == {"create", "approve"}


def test_cannot_self_approve_or_decide_twice_or_by_other_manager(client, world):
    adj = _request_inclusion(client, world["emp"], past(2)).json()
    assert client.post(f"/adjustments/{adj['id']}/decision", headers=world["emp"], json={"approve": True}).status_code == 403
    assert client.post(f"/adjustments/{adj['id']}/decision", headers=world["other"], json={"approve": True}).status_code == 403
    assert client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": False}).status_code == 200
    assert client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": True}).status_code == 409


def test_adjustment_rejects_future_and_invalid(client, world):
    future = datetime.now(UTC) + timedelta(hours=2)
    assert _request_inclusion(client, world["emp"], future).status_code == 422
    r = client.post("/adjustments", headers=world["emp"], json={"kind": "incluir", "reason": "sem horário"})
    assert r.status_code == 422


def test_disregard_punch_removes_it_from_mirror_but_keeps_it_in_the_arp(client, world, db):
    emp = db.get(User, world["ids"]["emp"])
    when = past(2, 12)
    p = register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)
    db.commit()
    adj = client.post("/adjustments", headers=world["emp"], json={
        "kind": "desconsiderar", "target_punch_id": p.id, "reason": "Marcação feita por engano"}).json()
    client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": True})
    again = client.post("/adjustments", headers=world["emp"], json={
        "kind": "desconsiderar", "target_punch_id": p.id, "reason": "Marcação feita por engano"}).json()
    r = client.post(f"/adjustments/{again['id']}/decision", headers=world["mgr"], json={"approve": True})
    assert r.status_code == 409
    month = when.strftime("%Y-%m")
    days = client.get(f"/mirror?month={month}", headers=world["emp"]).json()["days"]
    assert all(not d["punches"] for d in days if d["date"] == (when - timedelta(hours=3)).strftime("%Y-%m-%d"))
    assert db.get(Punch, p.id) is not None  # a marcação original segue no ARP (imutável)


# --- Fechamento --------------------------------------------------------------
def _prev_month_moment():
    first = datetime.now(UTC).replace(day=1, hour=15, minute=0, second=0, microsecond=0, tzinfo=None)
    return first - timedelta(days=10), (first - timedelta(days=10)).strftime("%Y-%m")


def test_closing_blocks_pending_then_blocks_changes_and_reopens(client, world):
    when, month = _prev_month_moment()
    adj = _request_inclusion(client, world["emp"], when).json()
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 409  # ajuste pendente
    client.post(f"/adjustments/{adj['id']}/decision", headers=world["mgr"], json={"approve": True})

    assert client.post(f"/closings/{month}", headers=world["emp"]).status_code == 403
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 200
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 409  # já fechado
    assert _request_inclusion(client, world["emp"], when).status_code == 409  # mês fechado

    assert client.post(f"/closings/{month}/reopen", headers=world["hr"]).status_code == 200
    assert _request_inclusion(client, world["emp"], when).status_code == 201
    actions = [t["action"] for t in client.get("/audit?entity=closing", headers=world["hr"]).json()]
    assert set(actions) == {"close", "reopen"}


def test_cannot_close_current_month(client, world):
    current = datetime.now(UTC).strftime("%Y-%m")
    assert client.post(f"/closings/{current}", headers=world["hr"]).status_code == 409


def test_audit_is_restricted(client, world):
    assert client.get("/audit", headers=world["emp"]).status_code == 403
    assert client.get("/audit", headers=world["hr"]).status_code == 200


def test_single_button_sequence_follows_order_and_the_fourth_punch_closes_the_day(client, world, db):
    h = world["emp"]
    kinds = [client.post("/punches", headers=h, json={}).json()["kind"] for _ in range(4)]
    assert kinds == ["entrada", "inicio_intervalo", "fim_intervalo", "saida"]
    nxt = client.get("/punches/next", headers=h).json()
    assert nxt["closed"] is True
    r = client.post("/punches", headers=h, json={})
    assert r.status_code == 409 and "Jornada encerrada" in r.json()["detail"]  # não existe quinta batida
    assert client.post("/punches", headers=h, json={"kind": "entrada"}).status_code == 409


def test_leaving_without_the_break_also_closes_the_day(client, world):
    h = world["emp"]
    assert client.post("/punches", headers=h, json={}).json()["kind"] == "entrada"
    assert client.get("/punches/next", headers=h).json()["can_skip_break"] is True
    assert client.post("/punches", headers=h, json={"kind": "saida"}).json()["kind"] == "saida"
    assert client.get("/punches/next", headers=h).json()["closed"] is True
    assert client.post("/punches", headers=h, json={}).status_code == 409


def test_night_shift_that_started_yesterday_does_not_close_today(db, world):
    from app.models import Company, Schedule
    from app.services.punching import day_closed
    emp = db.get(User, world["ids"]["emp"])
    db.get(Schedule, emp.schedule_id).crosses_midnight = True  # jornada que pode terminar no dia seguinte
    db.commit()
    company = db.get(Company, emp.company_id)  # America/Sao_Paulo (UTC-3)
    # turno da noite: entrada 10/03 23:00 local, saída 11/03 07:00 local
    register_punch(db, emp, kind="entrada", occurred_at=datetime(2026, 3, 11, 2, 0), enforce_sequence=False)
    register_punch(db, emp, kind="saida", occurred_at=datetime(2026, 3, 11, 10, 0), enforce_sequence=False)
    db.commit()
    assert day_closed(db, emp, company, datetime(2026, 3, 11, 15, 0)) is False  # o turno começou ontem: hoje pode começar outro
    # jornada comum: entrada e saída no mesmo dia local
    register_punch(db, emp, kind="entrada", occurred_at=datetime(2026, 3, 11, 22, 0), enforce_sequence=False)
    register_punch(db, emp, kind="saida", occurred_at=datetime(2026, 3, 12, 1, 0), enforce_sequence=False)  # 11/03 22:00 local
    db.commit()
    assert day_closed(db, emp, company, datetime(2026, 3, 12, 2, 0)) is True


def test_schedule_without_break_is_entrada_saida(client, world, db):
    from app.models import Schedule
    db.get(Schedule, world["sched"]["id"]).break_minutes = 0
    db.commit()
    h = world["emp"]
    kinds = [client.post("/punches", headers=h, json={}).json()["kind"] for _ in range(2)]
    assert kinds == ["entrada", "saida"]
    assert client.post("/punches", headers=h, json={}).status_code == 409  # a saída encerra a jornada
    assert client.get("/punches/next", headers=h).json()["has_break"] is False


def test_adjustment_list_tells_the_approver_who_asked_and_which_punch(client, world, db):
    emp = db.get(User, world["ids"]["emp"])
    p = register_punch(db, emp, kind="entrada", occurred_at=past(2, 12), enforce_sequence=False)
    db.commit()
    client.post("/adjustments", headers=world["emp"], json={
        "kind": "desconsiderar", "target_punch_id": p.id, "reason": "Marcação feita por engano"})
    row = client.get("/adjustments?status=pending", headers=world["mgr"]).json()[0]
    assert row["user_name"] == "Ana Colab" and row["target_kind"] == "entrada"
    assert row["target_at"].startswith(p.occurred_at.strftime("%Y-%m-%dT%H:%M"))


def test_by_default_a_forgotten_entry_does_not_carry_over_midnight(db, world):
    from app.models import Company, Schedule
    from app.services.punching import day_closed, expected_next_class, next_kind
    emp = db.get(User, world["ids"]["emp"])
    company = db.get(Company, emp.company_id)  # America/Sao_Paulo (UTC-3)
    register_punch(db, emp, kind="entrada", occurred_at=datetime(2026, 3, 11, 2, 0), enforce_sequence=False)  # 10/03 23:00 local, sem saída
    db.commit()
    morning = datetime(2026, 3, 11, 11, 0)  # 11/03 08:00 local: 9 h depois (dentro das 16 h), mas já é outro dia
    assert next_kind(db, emp, morning) == "entrada"            # padrão: a jornada se encerrou à meia-noite
    assert expected_next_class(db, emp, morning) == "in"
    db.get(Schedule, emp.schedule_id).crosses_midnight = True  # com a opção ligada, o turno continua
    db.commit()
    assert next_kind(db, emp, morning) == "inicio_intervalo"
    assert expected_next_class(db, emp, morning) == "out"

    db.get(Schedule, emp.schedule_id).crosses_midnight = False
    register_punch(db, emp, kind="saida", occurred_at=datetime(2026, 3, 11, 10, 0), enforce_sequence=False)  # 11/03 07:00 local
    db.commit()
    assert day_closed(db, emp, company, datetime(2026, 3, 11, 15, 0)) is True  # padrão: saída do mesmo dia encerra o dia


def test_schedule_can_be_created_with_the_cross_midnight_option(client, world):
    r = client.post("/schedules", headers=world["hr"], json={"name": "Noite", "start_time": "22:00", "break_start": "02:00",
                                                             "crosses_midnight": True})
    assert r.status_code == 201 and r.json()["crosses_midnight"] is True  # intervalo "antes" do início vale: já é do dia seguinte
    assert client.post("/schedules", headers=world["hr"], json={"name": "X", "start_time": "22:00", "break_start": "02:00"}).status_code == 422
    assert client.get("/schedules", headers=world["hr"]).json()[0]["crosses_midnight"] is False  # padrão


def test_schedule_cross_midnight_option_can_be_edited_and_is_audited(client, world, db):
    from app.models import AuditLog
    sid = world["sched"]["id"]
    assert client.get("/schedules", headers=world["hr"]).json()[0]["crosses_midnight"] is False
    r = client.patch(f"/schedules/{sid}", headers=world["hr"], json={"crosses_midnight": True})
    assert r.status_code == 200 and r.json()["crosses_midnight"] is True
    log = db.query(AuditLog).filter(AuditLog.entity == "schedule", AuditLog.action == "update").one()
    assert log.before == {"crosses_midnight": False} and log.after == {"crosses_midnight": True}
    assert client.patch(f"/schedules/{sid}", headers=world["hr"], json={"crosses_midnight": True}).status_code == 200  # sem mudança: sem nova auditoria
    assert db.query(AuditLog).filter(AuditLog.entity == "schedule", AuditLog.action == "update").count() == 1

    assert client.patch(f"/schedules/{sid}", headers=world["emp"], json={"crosses_midnight": False}).status_code == 403
    assert client.patch(f"/schedules/{sid}", headers=world["adminB"], json={"crosses_midnight": False}).status_code == 404  # outra empresa
    # jornada noturna com intervalo "antes" do início (02:00 < 22:00): não pode voltar ao padrão sem quebrar a regra
    night = client.post("/schedules", headers=world["hr"], json={"name": "Noite", "start_time": "22:00", "break_start": "02:00",
                                                                 "crosses_midnight": True}).json()["id"]
    assert client.patch(f"/schedules/{night}", headers=world["hr"], json={"crosses_midnight": False}).status_code == 422


def test_schedule_option_cannot_change_when_a_closed_month_has_punches_of_that_schedule(client, world, db):
    sid = world["sched"]["id"]
    emp = db.get(User, world["ids"]["emp"])
    when = past(40, 15)  # mês anterior
    register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)
    db.commit()
    month = when.strftime("%Y-%m")

    # mês ainda aberto: a mudança é permitida
    assert client.patch(f"/schedules/{sid}", headers=world["hr"], json={"crosses_midnight": True}).status_code == 200
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 200
    r = client.patch(f"/schedules/{sid}", headers=world["hr"], json={"crosses_midnight": False})
    assert r.status_code == 409 and month in r.json()["detail"] and "Reabra" in r.json()["detail"]
    assert client.get("/schedules", headers=world["hr"]).json()[0]["crosses_midnight"] is True  # nada mudou

    # reabrindo o mês, volta a valer
    assert client.post(f"/closings/{month}/reopen", headers=world["hr"]).status_code == 200
    assert client.patch(f"/schedules/{sid}", headers=world["hr"], json={"crosses_midnight": False}).status_code == 200


def test_closed_month_of_another_schedule_or_without_punches_does_not_block(client, world, db):
    emp = db.get(User, world["ids"]["emp"])
    when = past(40, 15)
    register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)
    db.commit()
    assert client.post(f"/closings/{when.strftime('%Y-%m')}", headers=world["hr"]).status_code == 200
    other = client.post("/schedules", headers=world["hr"], json={"name": "Outra"}).json()["id"]  # ninguém usa esta jornada
    assert client.patch(f"/schedules/{other}", headers=world["hr"], json={"crosses_midnight": True}).status_code == 200


def test_changing_a_persons_schedule_is_blocked_when_a_closed_month_has_their_punches(client, world, db):
    emp_id, other_id = world["ids"]["emp"], world["ids"]["other"]
    emp = db.get(User, emp_id)
    when = past(40, 15)
    register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)  # só a Ana tem marcação no mês
    db.commit()
    month = when.strftime("%Y-%m")
    new = client.post("/schedules", headers=world["hr"], json={"name": "Nova"}).json()["id"]

    assert client.patch(f"/users/{emp_id}", headers=world["hr"], json={"schedule_id": new}).status_code == 200  # mês aberto: pode
    assert client.patch(f"/users/{emp_id}", headers=world["hr"], json={"schedule_id": world["sched"]["id"]}).status_code == 200
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 200

    r = client.patch(f"/users/{emp_id}", headers=world["hr"], json={"schedule_id": new})
    assert r.status_code == 409 and month in r.json()["detail"] and "Reabra" in r.json()["detail"]
    assert db.get(User, emp_id).schedule_id == world["sched"]["id"]  # nada mudou
    # outros campos da própria pessoa não são afetados; repetir a mesma jornada não é troca
    assert client.patch(f"/users/{emp_id}", headers=world["hr"], json={"job_title": "Analista", "schedule_id": world["sched"]["id"]}).status_code == 200
    # quem não tem marcação em mês fechado troca à vontade
    assert client.patch(f"/users/{other_id}", headers=world["hr"], json={"schedule_id": new}).status_code == 200

    client.post(f"/closings/{month}/reopen", headers=world["hr"])
    assert client.patch(f"/users/{emp_id}", headers=world["hr"], json={"schedule_id": new}).status_code == 200  # reaberto: volta a valer
