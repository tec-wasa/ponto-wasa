"""Inconsistências da CLT: detecção (pura) e a lista da gestão com "resolvido"."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import AuditLog
from app.services.inconsistencies import detect
from app.services.timecalc import ScheduleRule, compute_month

TZ = "America/Sao_Paulo"  # UTC-3
TODAY = date(2026, 9, 30)
AUG = (date(2026, 8, 1), date(2026, 8, 31))


def utc(d, h, m=0):
    """Hora LOCAL de São Paulo em agosto/2026 -> UTC naive. 03/08/2026 é segunda-feira."""
    return datetime(2026, 8, d) + timedelta(hours=h + 3, minutes=m)


def day_of(d, *pairs):
    """Marcações de um dia a partir de pares ((h, m), (h, m))."""
    out = []
    for (h1, m1), (h2, m2) in pairs:
        out += [(utc(d, h1, m1), "entrada"), (utc(d, h2, m2), "saida")]
    return out


def regular(d):
    return day_of(d, ((8, 0), (12, 0)), ((13, 0), (17, 0)))


def findings(punches, rule=ScheduleRule(), start=AUG[0], end=AUG[1]):
    days = compute_month(punches, rule, TZ, 2026, 8, TODAY)
    return {(f.day.day, f.kind) for f in detect(days, start, end, TODAY)}


def test_regular_week_has_nothing_but_the_absences():
    got = findings(regular(3) + day_of(4, ((8, 0), (12, 0)), ((13, 10), (17, 5))))
    assert {k for d, k in got if d in (3, 4)} == set()
    assert (5, "falta") in got and (6, "falta") in got


def test_short_break_and_long_stretch():
    got = findings(day_of(3, ((8, 0), (12, 0)), ((12, 30), (17, 0)))  # 30 min de intervalo em 8h30
                   + day_of(4, ((7, 0), (14, 0)), ((15, 0), (17, 0)))  # 1 h de intervalo, mas 7 h seguidas
                   + day_of(5, ((8, 0), (12, 30))))  # meio período de 4h30 sem intervalo nenhum
    assert (3, "intervalo") in got
    assert (4, "sem_intervalo") in got and (4, "intervalo") not in got
    assert (5, "intervalo") in got  # acima de 4 h exige 15 min


def test_more_than_two_extra_hours():
    got = findings(day_of(3, ((8, 0), (12, 0)), ((13, 0), (19, 0)))  # exatamente 2 h extras: no limite
                   + day_of(4, ((8, 0), (12, 0)), ((13, 0), (19, 30))))
    assert (3, "horas_extras") not in got and (4, "horas_extras") in got


def test_rest_between_shifts_under_11_hours():
    got = findings(day_of(3, ((8, 0), (12, 0)), ((13, 0), (23, 0))) + regular(4))
    assert (4, "interjornada") in got and (3, "interjornada") not in got


def test_seventh_day_in_a_row():
    punches = [p for d in range(3, 10) for p in regular(d)]  # segunda 03 a domingo 09
    got = findings(punches)
    assert {d for d, k in got if k == "dsr"} == {9}


def test_british_timesheet_and_breaks():
    same = [p for d in range(3, 8) for p in regular(d)]  # 5 dias com os mesmos horários
    got = findings(same + day_of(10, ((8, 1), (12, 0)), ((13, 0), (17, 0))))
    assert {d for d, k in got if k == "britanico"} == {3}  # um item por sequência, no primeiro dia
    days = compute_month(same, ScheduleRule(), TZ, 2026, 8, TODAY)
    (item,) = [f for f in detect(days, *AUG, TODAY) if f.kind == "britanico"]
    assert "5 dias seguidos, de 03/08 a 07/08" in item.detail
    four = [p for d in range(3, 7) for p in regular(d)]  # 4 dias: ainda não
    assert not {d for d, k in findings(four) if k == "britanico"}


def test_only_the_requested_period_is_reported_but_lookback_counts():
    punches = [p for d in range(3, 10) for p in regular(d)]
    got = findings(punches, start=date(2026, 8, 9), end=date(2026, 8, 9))
    assert got == {(9, "dsr"), (9, "britanico")}


# --- API ------------------------------------------------------------------------
def _today_local():
    return (datetime.now(UTC) - timedelta(hours=3)).date()


def test_list_resolve_and_reopen(client, world, db):
    emp, other, mgr, hr = world["ids"]["emp"], world["ids"]["other"], world["mgr"], world["hr"]
    today = _today_local()
    admitted = (today - timedelta(days=20)).isoformat()
    for uid in (emp, other):
        assert client.patch(f"/users/{uid}", headers=world["admin"], json={"admitted_at": admitted}).status_code == 200
    start = (today - timedelta(days=14)).isoformat()
    q = f"/inconsistencies?start={start}&end={today.isoformat()}"

    assert client.get(q, headers=world["emp"]).status_code == 403
    r = client.get(q, headers=mgr)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["can_resolve"] and data["open"] > 0
    assert {i["user_id"] for i in data["items"]} == {emp}  # gestor: só a equipe
    assert {i["user_id"] for i in client.get(q, headers=hr).json()["items"]} >= {emp, other}

    falta = next(i for i in data["items"] if i["kind"] == "falta")
    body = {"user_id": emp, "date": falta["date"], "kind": "falta", "note": "Dispensado pela diretoria"}
    assert client.post("/inconsistencies/resolve", headers=mgr, json=body).status_code == 201
    assert client.post("/inconsistencies/resolve", headers=mgr, json=body).status_code == 409
    assert client.post("/inconsistencies/resolve", headers=mgr, json={**body, "kind": "dsr"}).status_code == 409
    assert client.post("/inconsistencies/resolve", headers=mgr, json={**body, "user_id": other}).status_code == 404
    assert client.post("/inconsistencies/resolve", headers=world["emp"], json=body).status_code == 403

    after = client.get(q, headers=mgr).json()
    assert after["open"] == data["open"] - 1 and after["resolved"] == 1
    assert not any(i["date"] == falta["date"] and i["kind"] == "falta" for i in after["items"])
    shown = client.get(q + "&resolved=true", headers=mgr).json()["items"]
    done = next(i for i in shown if i["date"] == falta["date"] and i["kind"] == "falta")
    assert done["resolved"]["by"] == "Gil Gestor" and done["resolved"]["note"] == "Dispensado pela diretoria"

    reopen = {k: body[k] for k in ("user_id", "date", "kind")}
    assert client.post("/inconsistencies/reopen", headers=mgr, json=reopen).status_code == 204
    assert client.post("/inconsistencies/reopen", headers=mgr, json=reopen).status_code == 404
    assert client.get(q, headers=mgr).json()["open"] == data["open"]
    actions = [a.action for a in db.execute(select(AuditLog).where(AuditLog.entity == "inconsistency")).scalars()]
    assert actions == ["resolve", "reopen"]


def test_filters_and_limits(client, world):
    today = _today_local()
    base = f"/inconsistencies?start={(today - timedelta(days=5)).isoformat()}&end={today.isoformat()}"
    assert client.get(base + "&kind=xyz", headers=world["hr"]).status_code == 422
    assert client.get(base + f"&user_id={world['ids']['other']}", headers=world["mgr"]).status_code == 404
    only = client.get(base + "&kind=falta", headers=world["hr"]).json()["items"]
    assert all(i["kind"] == "falta" for i in only)
    far = f"/inconsistencies?start={(today - timedelta(days=200)).isoformat()}&end={today.isoformat()}"
    assert client.get(far, headers=world["hr"]).status_code == 422
