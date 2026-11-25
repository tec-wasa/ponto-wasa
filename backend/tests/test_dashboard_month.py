"""Painel do mês (dashboard): totais, situação por dia, atrasos, pendências e escopo."""


def _treat(client, h, uid, when, kind):
    r = client.post("/adjustments", headers=h, json={"kind": "incluir", "user_id": uid, "requested_at": when,
                                                     "punch_kind": kind, "reason": "Ajuste do teste do painel"})
    assert r.status_code == 201, r.text


def test_month_overview(client, world):
    adm, hr, mgr = world["admin"], world["hr"], world["mgr"]
    emp, other = world["ids"]["emp"], world["ids"]["other"]
    for uid in (emp, other):
        client.patch(f"/users/{uid}", headers=adm, json={"admitted_at": "2026-04-01"})
    _treat(client, hr, emp, "2026-04-06T11:40:00Z", "entrada")  # 08:40 em São Paulo: atraso de 40 min
    _treat(client, hr, emp, "2026-04-06T20:40:00Z", "saida")

    r = client.get("/dashboard/month?month=2026-04", headers=mgr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["people_count"] == 1 and [p["name"] for p in body["people"]] == ["Ana Colab"]  # gestor: só a equipe
    ana = body["people"][0]
    assert ana["late_days"] == 1 and ana["late_minutes"] == 40
    assert ana["absences"] == 21 and ana["worked"] == 540  # 22 dias úteis em abril/2026, um trabalhado
    day = next(d for d in body["days"] if d["date"] == "2026-04-06")
    assert day["ok"] == 1 and day["falta"] == 0
    assert next(d for d in body["days"] if d["date"] == "2026-04-07")["falta"] == 1

    company = client.get("/dashboard/month?month=2026-04", headers=hr).json()
    assert company["people_count"] >= 2 and company["totals"]["absences"] >= 42 and company["totals"]["late_days"] == 1


def test_month_overview_guards(client, world):
    assert client.get("/dashboard/month?month=2026-04", headers=world["emp"]).status_code == 403
    assert client.get("/dashboard/month?month=2099-01", headers=world["admin"]).status_code == 422
    assert client.get("/dashboard/month?month=2026-13", headers=world["admin"]).status_code == 422
