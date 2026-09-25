"""Ausências justificadas (RF-13): atestados, abonos, férias, licenças e afastamentos."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, User
from app.services.punching import register_punch
from tests.test_pdf import local_utc

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)  # AEJ e PDFs sem INPI/certificado (modo de teste)


def today() -> date:
    return datetime.now(TZ).date()


def weekday_before(n: int, ref: date | None = None) -> date:
    """Dia útil (seg-sex) mais recente que esteja pelo menos `n` dias no passado."""
    d = (ref or today()) - timedelta(days=n)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def full_week_in_one_month(ref: date | None = None) -> date:
    """Segunda-feira de uma semana passada (seg a dom) que não cruza a virada do mês."""
    ref = ref or today()
    monday = ref - timedelta(days=ref.weekday()) - timedelta(days=14)
    while (monday + timedelta(days=6)).month != monday.month:
        monday -= timedelta(days=7)
    return monday


def request(client, headers, kind="atestado_medico", start=None, end=None, **extra):
    start = start or weekday_before(7)
    body = {"kind": kind, "start_date": str(start), "end_date": str(end or start), "reason": "Consulta médica", **extra}
    return client.post("/absences", headers=headers, json=body)


def day_of(client, headers, d: date, user_id=None):
    q = f"/mirror?month={d:%Y-%m}" + (f"&user_id={user_id}" if user_id else "")
    body = client.get(q, headers=headers).json()
    return next(x for x in body["days"] if x["date"] == d.isoformat()), body["totals"]


@pytest.fixture()
def ana(client, world):
    """Ana com admissão antiga: dias úteis passados sem marcação são falta, a menos que justificados."""
    uid = world["ids"]["emp"]
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"admitted_at": "2020-01-01"}).status_code == 200
    return uid


def punches(db, uid, d, marks):
    user = db.get(User, uid)
    for hhmm, kind in marks:
        register_punch(db, user, kind=kind, occurred_at=local_utc(d, hhmm), enforce_sequence=False)
    db.commit()


# ------------------------------- fluxo básico ---------------------------------
def test_medical_certificate_request_approval_and_effect_on_the_mirror(client, world, ana):
    d = weekday_before(7)
    other_day = prev_weekday(d)
    assert day_of(client, world["emp"], d)[0]["status"] == "falta"  # antes: falta

    r = request(client, world["emp"])
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["kind_label"] == "Atestado médico"
    assert day_of(client, world["emp"], d)[0]["status"] == "falta"  # pendente ainda não justifica

    a = r.json()
    ok = client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True, "note": "Recebido"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"

    day, totals = day_of(client, world["emp"], d)
    assert day["status"] == "justificada" and day["justification"] == "Atestado médico" and day["balance"] == 0
    assert totals["justified_days"] >= 1
    assert day_of(client, world["emp"], other_day)[0]["status"] == "falta"  # os outros dias continuam sendo falta

    # a falta justificada não vai para o AEJ como falta não justificada
    aej = client.get(f"/exports/aej?start={d}&end={d}", headers=world["hr"])
    assert aej.status_code == 200 and f"|2|{d}||" not in aej.content.decode("latin-1")


def test_rejected_request_does_not_justify(client, world, ana):
    d = weekday_before(7)
    a = request(client, world["emp"], "abono").json()
    r = client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": False, "note": "Sem comprovação"})
    assert r.json()["status"] == "rejected" and r.json()["decision_note"] == "Sem comprovação"
    assert day_of(client, world["emp"], d)[0]["status"] == "falta"
    assert client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True}).status_code == 409  # já decidida


def test_multi_day_hr_registration_is_approved_immediately_and_skips_weekends(client, world, ana):
    monday = full_week_in_one_month()
    sunday = monday + timedelta(days=6)
    r = request(client, world["hr"], "ferias", monday, sunday, user_id=ana)
    assert r.status_code == 201 and r.json()["status"] == "approved"
    days = client.get(f"/mirror?month={monday:%Y-%m}", headers=world["emp"]).json()["days"]
    week = [d for d in days if monday.isoformat() <= d["date"] <= sunday.isoformat()]
    assert [d["status"] for d in week] == ["justificada"] * 5 + ["folga"] * 2  # fim de semana continua folga
    assert all(d["justification"] == "Férias" for d in week[:5])


# ------------------------------- permissões ----------------------------------
def test_who_can_request_register_and_decide(client, world, ana):
    d = weekday_before(7)
    assert request(client, world["emp"], "ferias").status_code == 403  # tipos do RH
    assert request(client, world["emp"], "licenca").status_code == 403
    assert request(client, world["emp"], "afastamento_inss").status_code == 403
    assert request(client, world["mgr"], "abono", user_id=ana).status_code == 403  # gestor não registra por outro
    assert request(client, world["emp"], "abono", user_id=world["ids"]["other"]).status_code == 403
    assert request(client, world["hr"], "ferias", user_id=99999).status_code == 404
    assert request(client, world["hr"], "ferias", user_id=ana).status_code == 201
    a = request(client, world["other"], "abono", d).json()
    assert client.post(f"/absences/{a['id']}/decision", headers=world["other"], json={"approve": True}).status_code == 403  # a própria
    assert client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True}).status_code == 403  # não é a equipe
    assert client.post(f"/absences/{a['id']}/decision", headers=world["adminB"], json={"approve": True}).status_code == 404
    assert client.post(f"/absences/{a['id']}/decision", headers=world["hr"], json={"approve": True}).status_code == 200
    assert client.get("/absences").status_code == 401


def test_visibility_of_lists(client, world, ana):
    request(client, world["emp"], "abono", weekday_before(7))
    request(client, world["other"], "abono", weekday_before(8))
    names = lambda h, **q: sorted({a["user_name"] for a in client.get("/absences", headers=h, params=q).json()})  # noqa: E731
    assert names(world["emp"]) == ["Ana Colab"]  # cada um vê as suas
    assert names(world["mgr"]) == ["Ana Colab"]  # o gestor vê a equipe (Beto não é dele)
    assert names(world["hr"]) == ["Ana Colab", "Beto Sem Gestor"]
    assert names(world["adminB"]) == []
    assert names(world["hr"], user_id=ana) == ["Ana Colab"] and names(world["hr"], status="approved") == []


def test_manager_never_sees_health_details(client, world, ana):
    d1 = weekday_before(7)
    d2 = prev_weekday(d1)
    sick = request(client, world["emp"], "atestado_medico", d1, reason="Cirurgia de joelho, CID M23").json()
    plain = request(client, world["emp"], "abono", d2, reason="Mudança de casa").json()
    seen = {a["id"]: a for a in client.get("/absences", headers=world["mgr"]).json()}
    assert seen[sick["id"]]["restricted"] is True and seen[sick["id"]]["reason"] is None and seen[sick["id"]]["attachment_name"] is None
    assert seen[sick["id"]]["kind_label"] == "Atestado médico" and seen[sick["id"]]["start_date"] == d1.isoformat()  # o fato e o período, sim
    assert seen[plain["id"]]["reason"] == "Mudança de casa"  # abono comum não é dado de saúde
    for h in (world["emp"], world["hr"]):  # dono e RH veem o detalhe
        got = {a["id"]: a for a in client.get("/absences", headers=h).json()}
        assert got[sick["id"]]["reason"] == "Cirurgia de joelho, CID M23" and got[sick["id"]]["restricted"] is False
    # a decisão do gestor também não devolve o motivo
    decided = client.post(f"/absences/{sick['id']}/decision", headers=world["mgr"], json={"approve": True}).json()
    assert decided["reason"] is None and decided["restricted"] is True


def test_health_reason_is_kept_out_of_the_audit_trail(client, world, ana, db):
    a = request(client, world["emp"], "atestado_medico", reason="Diagnóstico sigiloso XYZ").json()
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    rows = db.execute(select(AuditLog).where(AuditLog.entity == "absence")).scalars().all()
    assert [r.action for r in rows] == ["create", "approve"]
    assert "sigiloso" not in str([(r.before, r.after) for r in rows])


# ------------------------------- validações ------------------------------------
def test_period_validation(client, world, ana):
    d = weekday_before(7)
    assert request(client, world["emp"], "sorteio").status_code == 422
    assert request(client, world["emp"], "abono", d, d - timedelta(days=1)).status_code == 422  # fim antes do início
    assert request(client, world["emp"], "abono", d, d + timedelta(days=1), minutes=60).status_code == 422  # parcial em vários dias
    assert request(client, world["hr"], "ferias", d, d, minutes=60, user_id=ana).status_code == 422  # férias não são parciais
    assert request(client, world["emp"], "abono", d, minutes=0).status_code == 422
    assert request(client, world["emp"], "abono", d, minutes=13 * 60).status_code == 422
    assert request(client, world["hr"], "licenca", d, d + timedelta(days=400), user_id=ana).status_code == 422  # mais de 366 dias
    assert request(client, world["hr"], "ferias", d, today() + timedelta(days=800), user_id=ana).status_code == 422  # futuro demais
    assert request(client, world["emp"], "abono", today() - timedelta(days=120)).status_code == 422  # colaborador: até 90 dias atrás
    assert request(client, world["hr"], "abono", today() - timedelta(days=120), user_id=ana).status_code == 201  # o RH pode
    assert request(client, world["emp"], "abono", reason="ab").status_code == 422  # motivo obrigatório


def test_overlaps_are_refused_but_cancelled_or_rejected_free_the_period(client, world, ana):
    d = weekday_before(7)
    first = request(client, world["emp"], "abono", d).json()
    assert request(client, world["emp"], "atestado_medico", d - timedelta(days=1), d).status_code == 409  # sobrepõe
    assert request(client, world["hr"], "ferias", d, d, user_id=ana).status_code == 409
    assert client.post(f"/absences/{first['id']}/cancel", headers=world["emp"]).status_code == 200
    assert request(client, world["emp"], "atestado_medico", d).status_code == 201  # período liberado


def test_cancel_rules(client, world, ana):
    d = weekday_before(7)
    a = request(client, world["emp"], "abono", d).json()
    assert client.post(f"/absences/{a['id']}/cancel", headers=world["other"]).status_code == 403
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    assert client.post(f"/absences/{a['id']}/cancel", headers=world["emp"]).status_code == 403  # aprovada: só o RH cancela
    assert day_of(client, world["emp"], d)[0]["status"] == "justificada"
    assert client.post(f"/absences/{a['id']}/cancel", headers=world["hr"]).status_code == 200
    assert day_of(client, world["emp"], d)[0]["status"] == "falta"  # voltou a ser falta
    assert client.post(f"/absences/{a['id']}/cancel", headers=world["hr"]).status_code == 409  # já cancelada


# ------------------------------- efeito na jornada ---------------------------
def test_partial_justification_reduces_the_expected_hours(client, world, ana, db):
    d = weekday_before(7)
    punches(db, ana, d, [("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("15:00", "saida")])  # 6 h de 8 h
    assert day_of(client, world["emp"], d)[0]["balance"] == -120  # sem justificativa: 2 h a menos
    a = request(client, world["emp"], "atestado_medico", d, minutes=120, reason="Consulta às 15h").json()
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    day, _ = day_of(client, world["emp"], d)
    assert day["balance"] == 0 and day["status"] == "ok" and day["justification"] == "Atestado médico"  # 6 h + 2 h justificadas = 8 h


def test_partial_justification_without_punches_is_still_an_absence(client, world, ana):
    d = weekday_before(7)
    a = request(client, world["emp"], "abono", d, minutes=120).json()
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    day, _ = day_of(client, world["emp"], d)
    assert day["status"] == "falta" and day["balance"] == -480  # ninguém apareceu: 2 h justificadas não cobrem o dia todo


def test_working_on_a_justified_day_counts_as_extra(client, world, ana, db):
    d = weekday_before(7)
    punches(db, ana, d, [("08:00", "entrada"), ("12:00", "saida")])  # 4 h numa folga justificada
    a = request(client, world["hr"], "ferias", d, user_id=ana).json()
    assert a["status"] == "approved"
    day, _ = day_of(client, world["emp"], d)
    assert day["status"] == "ok" and day["balance"] == 240  # jornada esperada é zero: tudo é saldo


def test_bank_uses_the_reduced_expectation(client, world, ana, db):
    d = weekday_before(7)
    client.patch(f"/users/{ana}", headers=world["hr"], json={"hour_bank_enabled": True, "hour_bank_start": str(d - timedelta(days=3))})
    punches(db, ana, d, [("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada"), ("15:00", "saida")])
    assert client.get("/hour-bank", headers=world["emp"]).json()["automatic"] == -120
    a = request(client, world["emp"], "atestado_medico", d, minutes=120).json()
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    assert client.get("/hour-bank", headers=world["emp"]).json()["automatic"] == 0  # a justificativa evita a dívida no banco


# ------------------------------- painel e fechamento --------------------------
def test_dashboard_shows_justified_absence_instead_of_missing_punch(client, world, ana):
    d = weekday_before(7)
    at = local_utc(d, "10:00").isoformat() + "Z"
    assert next(p for p in client.get(f"/dashboard?at={at}", headers=world["mgr"]).json()["people"])["state"] == "sem_marcacao"
    a = request(client, world["emp"], "atestado_medico", d).json()
    client.post(f"/absences/{a['id']}/decision", headers=world["mgr"], json={"approve": True})
    body = client.get(f"/dashboard?at={at}", headers=world["mgr"]).json()
    assert body["people"][0]["state"] == "justificada" and body["people"][0]["state_label"] == "Ausência justificada"
    assert body["summary"]["justificada"] == 1 and body["summary"]["sem_marcacao"] == 0


def test_espelho_pdf_shows_the_justification(client, world, ana):
    d = weekday_before(7)
    a = request(client, world["hr"], "licenca", d, d, user_id=ana, reason="Casamento").json()
    assert a["status"] == "approved"
    import io

    from pypdf import PdfReader
    pdf = client.get(f"/mirror/official.pdf?month={d:%Y-%m}", headers=world["emp"])
    text = " ".join("\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages).split())
    assert "Ausência justificada (Licença)" in text


def test_closed_month_and_pending_requests_block_each_other(client, world, ana):
    first = today().replace(day=1)
    d = first - timedelta(days=1)  # último dia do mês passado
    while d.weekday() > 4:
        d -= timedelta(days=1)
    month = f"{d:%Y-%m}"
    pending = request(client, world["emp"], "abono", d).json()
    r = client.post(f"/closings/{month}", headers=world["hr"])
    assert r.status_code == 409 and "ausência(s) pendente(s)" in r.json()["detail"]  # pendente impede fechar
    client.post(f"/absences/{pending['id']}/decision", headers=world["mgr"], json={"approve": True})
    assert client.post(f"/closings/{month}", headers=world["hr"]).status_code == 200

    assert request(client, world["hr"], "abono", d - timedelta(days=1) if (d - timedelta(days=1)).month == d.month else d, user_id=world["ids"]["other"]).status_code == 409  # mês fechado
    assert client.post(f"/absences/{pending['id']}/cancel", headers=world["hr"]).status_code == 409  # nem cancelar
    assert client.post(f"/closings/{month}/reopen", headers=world["hr"]).status_code == 200
    assert client.post(f"/absences/{pending['id']}/cancel", headers=world["hr"]).status_code == 200  # reaberto: pode


def test_date_helpers_hold_for_every_day_of_two_years():
    """Os testes acima dependem da data em que rodam; isto garante que os dias escolhidos são sempre válidos."""
    for offset in range(730):
        ref = date(2026, 1, 1) + timedelta(days=offset)
        d1 = weekday_before(7, ref)
        assert d1.weekday() <= 4 and (ref - d1).days >= 7 and (ref - d1).days <= 10
        d2 = prev_weekday(d1)
        assert d2 != d1 and d2.weekday() <= 4 and d2 < d1
        monday = full_week_in_one_month(ref)
        assert monday.weekday() == 0 and (monday + timedelta(days=6)).month == monday.month and monday < ref - timedelta(days=8)
        assert (ref - monday).days <= 50 and (ref - d1).days < 90  # dentro do limite de 90 dias do pedido do colaborador
