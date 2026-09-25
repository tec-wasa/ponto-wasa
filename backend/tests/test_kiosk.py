"""Central do Ponto (fase 1): pareamento, identificação (código, CPF, QR, PIN opcional), tickets e batida com foto obrigatória."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Kiosk, KioskTicket, Punch, PunchPhoto, User
from app.services import kiosk as svc
from app.services import totp
from tests.test_photos import B64, JPEG  # noqa: F401

GENERIC = svc.GENERIC_FAIL


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photo_dir", str(tmp_path / "photos"))
    monkeypatch.setattr(settings, "allow_missing_inpi", True)


def new_kiosk(client, world, name="CT-01", **extra):
    r = client.post("/kiosks", headers=world["admin"], json={"name": name, "latitude": -23.5505, "longitude": -46.6333, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def paired(client, world, name="CT-01", **extra):
    k = new_kiosk(client, world, name, **extra)
    r = client.post("/kiosk/pair", json={"pairing_code": k["pairing_code"]})
    assert r.status_code == 200, r.text
    return {"X-Kiosk-Token": r.json()["token"]}, k


def code_of(client, headers):
    return client.get("/auth/badge", headers=headers).json()["employee_code"]


def identify(client, kh, method="code", value=None, pin=None):
    body = {"method": method, "value": value}
    if pin is not None:
        body["pin"] = pin
    return client.post("/kiosk/identify", headers=kh, json=body)


def punch(client, kh, ticket, **extra):
    return client.post("/kiosk/punch", headers=kh, json={"ticket": ticket, "photo": B64, **extra})


def consent_and_punch(client, kh, ticket, **extra):
    assert client.post("/kiosk/consent-photo", headers=kh, json={"ticket": ticket}).status_code == 200
    return punch(client, kh, ticket, **extra)


# --- pareamento ----------------------------------------------------------------------
def test_pairing_is_single_use_admin_only_and_limited(client, world, db):
    assert client.post("/kiosks", headers=world["hr"], json={"name": "X1"}).status_code == 403  # só o administrador
    k = new_kiosk(client, world)
    assert len(k["pairing_code"]) == 8 and k["paired"] is False and k["pairing_pending"] is True

    bad = client.post("/kiosk/pair", json={"pairing_code": "ZZZZZZZZ"})
    assert bad.status_code == 401
    ok = client.post("/kiosk/pair", json={"pairing_code": k["pairing_code"].lower()})  # o código não diferencia maiúsculas
    assert ok.status_code == 200 and ok.json()["kiosk"]["name"] == "CT-01"
    again = client.post("/kiosk/pair", json={"pairing_code": k["pairing_code"]})
    assert again.status_code == 401  # uso único
    row = db.get(Kiosk, k["id"])
    assert row.token_hash and row.token_hash != ok.json()["token"] and row.pairing_hash is None  # só o hash fica guardado

    for i in range(settings.kiosk_max_per_company - 1):
        new_kiosk(client, world, f"CT-{i + 2}")
    assert client.post("/kiosks", headers=world["admin"], json={"name": "excedente"}).status_code == 409


def test_expired_pairing_code_is_refused(client, world, db):
    k = new_kiosk(client, world)
    row = db.get(Kiosk, k["id"])
    row.pairing_expires_at = row.pairing_expires_at - timedelta(hours=1)
    db.commit()
    assert client.post("/kiosk/pair", json={"pairing_code": k["pairing_code"]}).status_code == 401


def test_state_needs_a_valid_device_and_revocation_is_immediate(client, world):
    assert client.get("/kiosk/state").status_code == 401
    assert client.get("/kiosk/state", headers={"X-Kiosk-Token": "inventado"}).status_code == 401
    kh, k = paired(client, world)
    st = client.get("/kiosk/state", headers=kh).json()
    assert st["company"] == "Empresa A" and st["photo_required"] is True and st["pin_required"] is False
    assert "foto é obrigatória" in st["consent_text"] and st["kiosk"]["radius_m"] == 100
    assert client.post(f"/kiosks/{k['id']}/revoke", headers=world["admin"]).status_code == 200
    assert client.get("/kiosk/state", headers=kh).status_code == 401
    assert client.post(f"/kiosks/{k['id']}/pairing", headers=world["admin"]).status_code == 409  # revogada: cadastre outra


def test_repairing_cuts_access_of_the_old_device(client, world):
    kh, k = paired(client, world)
    r = client.post(f"/kiosks/{k['id']}/pairing", headers=world["admin"])
    assert client.get("/kiosk/state", headers=kh).status_code == 401  # o aparelho antigo perdeu o acesso
    new = client.post("/kiosk/pair", json={"pairing_code": r.json()["pairing_code"]}).json()["token"]
    assert client.get("/kiosk/state", headers={"X-Kiosk-Token": new}).status_code == 200


def test_kiosks_are_isolated_between_companies(client, world):
    kh, k = paired(client, world)
    assert client.get("/kiosks", headers=world["adminB"]).json() == []
    assert client.post(f"/kiosks/{k['id']}/revoke", headers=world["adminB"]).status_code == 404
    other_code = code_of(client, world["adminB"])
    assert identify(client, kh, "code", other_code).status_code == 401  # código de outra empresa: falha genérica


# --- identificação ---------------------------------------------------------------------
def test_identify_by_code_cpf_and_badge_and_generic_failures(client, world, db):
    kh, _ = paired(client, world)
    code = code_of(client, world["emp"])
    assert len(code) == 6 and code.isdigit()
    r = identify(client, kh, "code", code)
    assert r.status_code == 200
    body = r.json()
    assert body["first_name"] == "Ana" and body["next_kind"] == "entrada" and body["sequence"] == 1 and body["needs_consent"] is True
    assert "ticket" in body and body["expires_in"] == 60

    emp = db.get(User, world["ids"]["emp"])
    assert identify(client, kh, "cpf", emp.cpf).json()["first_name"] == "Ana"
    assert identify(client, kh, "cpf", f"{emp.cpf[:3]}.{emp.cpf[3:6]}.{emp.cpf[6:9]}-{emp.cpf[9:]}").status_code == 200  # com máscara

    qr = client.get(f"/users/{emp.id}/badge", headers=world["hr"]).json()["qr"]
    assert identify(client, kh, "qr", qr).status_code == 200
    assert identify(client, kh, "qr", qr[:-1] + ("0" if qr[-1] != "0" else "1")).status_code == 401  # assinatura adulterada

    # mensagens idênticas: código inexistente, CPF inexistente, QR inválido, pessoa inativa
    emp.active = False
    db.commit()
    fails = [identify(client, kh, "code", "999999"), identify(client, kh, "cpf", "11144477735"), identify(client, kh, "qr", "lixo"),
             identify(client, kh, "code", code)]
    assert {(f.status_code, f.json()["detail"]) for f in fails} == {(401, GENERIC)}


def test_regenerating_the_badge_invalidates_printed_ones(client, world, db):
    kh, _ = paired(client, world)
    emp_id = world["ids"]["emp"]
    old = client.get(f"/users/{emp_id}/badge", headers=world["hr"]).json()["qr"]
    assert identify(client, kh, "qr", old).status_code == 200
    new = client.post(f"/users/{emp_id}/badge/regenerate", headers=world["hr"]).json()["qr"]
    assert new != old
    assert identify(client, kh, "qr", old).status_code == 401
    assert identify(client, kh, "qr", new).status_code == 200
    assert client.get(f"/users/{emp_id}/badge", headers=world["mgr"]).status_code == 403  # gestor não vê crachá
    assert client.get(f"/users/{world['ids']['hr']}/badge", headers=world["hr"]).status_code == 403  # RH não mexe em conta de RH


def test_pin_is_optional_by_default_and_configurable_by_the_admin(client, world, db):
    kh, _ = paired(client, world)
    code = code_of(client, world["emp"])
    assert identify(client, kh, "code", code).status_code == 200  # padrão: não pede PIN
    assert client.patch("/company", headers=world["hr"], json={"kiosk_pin_required": True}).status_code == 403
    assert client.patch("/company", headers=world["admin"], json={"kiosk_pin_required": True}).json()["kiosk_pin_required"] is True
    assert client.get("/kiosk/state", headers=kh).json()["pin_required"] is True

    # sem PIN cadastrado ou sem digitar: falha genérica (por código/CPF) ou "falta o PIN" (por QR, sem revelar nome)
    assert identify(client, kh, "code", code).json()["detail"] == GENERIC
    assert identify(client, kh, "code", code, pin="4821").json()["detail"] == GENERIC  # não tem PIN ainda
    qr = client.get(f"/users/{world['ids']['emp']}/badge", headers=world["hr"]).json()["qr"]
    r = identify(client, kh, "qr", qr)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "pin_required" and "first_name" not in r.text

    # a pessoa define o PIN (com a senha atual; PIN óbvio é recusado)
    assert client.post("/auth/pin", headers=world["emp"], json={"password": "errada", "pin": "4821"}).status_code == 403
    assert client.post("/auth/pin", headers=world["emp"], json={"password": "senha-forte-123", "pin": "1234"}).status_code == 422
    assert client.post("/auth/pin", headers=world["emp"], json={"password": "senha-forte-123", "pin": "48a1"}).status_code == 422
    assert client.post("/auth/pin", headers=world["emp"], json={"password": "senha-forte-123", "pin": "4821"}).status_code == 200
    assert db.get(User, world["ids"]["emp"]).pin_hash.startswith("$argon2")  # só o hash

    assert identify(client, kh, "code", code, pin="4821").json()["first_name"] == "Ana"
    assert identify(client, kh, "qr", qr, pin="4821").status_code == 200


def test_pin_lockout_and_admin_reset(client, world, db):
    kh, _ = paired(client, world)
    client.patch("/company", headers=world["admin"], json={"kiosk_pin_required": True})
    client.post("/auth/pin", headers=world["emp"], json={"password": "senha-forte-123", "pin": "4821"})
    code = code_of(client, world["emp"])
    for _ in range(settings.kiosk_pin_max_fails):
        assert identify(client, kh, "code", code, pin="0007").json()["detail"] == GENERIC
    assert identify(client, kh, "code", code, pin="4821").status_code == 401  # bloqueado, mesmo com o PIN certo
    emp = db.get(User, world["ids"]["emp"])
    assert emp.pin_locked_until is not None

    emp.pin_locked_until = emp.pin_locked_until - timedelta(minutes=10)  # o tempo passou
    db.commit()
    assert identify(client, kh, "code", code, pin="4821").status_code == 200

    assert client.post(f"/users/{emp.id}/pin-reset", headers=world["mgr"]).status_code == 403
    assert client.post(f"/users/{emp.id}/pin-reset", headers=world["hr"]).json()["has_pin"] is False
    assert identify(client, kh, "code", code, pin="4821").status_code == 401  # sem PIN de novo


def test_rotating_qr_from_the_app_skips_the_pin_and_cannot_be_replayed(client, world, monkeypatch):
    kh, _ = paired(client, world)
    client.patch("/company", headers=world["admin"], json={"kiosk_pin_required": True})
    r = client.get("/auth/badge-qr", headers=world["emp"]).json()
    if r["expires_in"] <= 3:  # fim de janela: espera a próxima para não depender do relógio
        import time
        time.sleep(r["expires_in"] + 1)
        r = client.get("/auth/badge-qr", headers=world["emp"]).json()
    assert r["qr"].startswith("PR1.") and 0 < r["expires_in"] <= 30
    assert identify(client, kh, "qr", r["qr"]).status_code == 200  # o celular é a prova: sem PIN
    assert identify(client, kh, "qr", r["qr"]).status_code == 401  # a mesma janela não vale duas vezes
    assert identify(client, kh, "qr", f"PR1.{world['ids']['emp']}.000000").status_code == 401


def test_too_many_failures_slow_the_whole_device(client, world):
    kh, _ = paired(client, world)
    for i in range(30):
        assert identify(client, kh, "code", f"9000{i:02d}").status_code == 401
    r = identify(client, kh, "code", code_of(client, world["emp"]))
    assert r.status_code == 429  # até a pessoa certa espera: o aparelho está sob tentativa em série


# --- batida ----------------------------------------------------------------------------
def test_punch_requires_consent_photo_and_a_valid_single_use_ticket(client, world, db):
    kh, k = paired(client, world)
    code = code_of(client, world["emp"])
    t = identify(client, kh, "code", code).json()["ticket"]

    r = punch(client, kh, t)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"  # foto exige consentimento
    assert client.post("/kiosk/consent-photo", headers=kh, json={"ticket": t}).status_code == 200
    assert db.get(User, world["ids"]["emp"]).photo_consent_at is not None

    assert client.post("/kiosk/punch", headers=kh, json={"ticket": t, "photo": ""}).status_code == 422  # a foto é obrigatória
    assert punch(client, kh, t, photo="!!!").status_code == 422
    assert client.post("/kiosk/punch", headers=kh, json={"ticket": t}).status_code == 422
    assert db.query(Punch).count() == 0  # nada gravado nas tentativas inválidas

    ok = punch(client, kh, t, latitude=-23.5505, longitude=-46.6333)
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["label"] == "Entrada" and body["nsr"] > 0 and body["distance_m"] == 0 and body["outside_radius"] is False
    p = db.get(Punch, db.query(Punch).one().id)
    assert (p.collector, p.kiosk_id, p.device_id, p.offline) == ("04", k["id"], f"kiosk:{k['id']}", False)
    assert p.latitude == -23.5505  # posição do APARELHO guardada mesmo sem consentimento de GPS da pessoa
    assert db.query(PunchPhoto).filter_by(punch_id=p.id).count() == 1
    img = client.get(f"/punches/{p.id}/photo", headers=world["hr"])
    assert img.status_code == 200 and img.content == JPEG  # o RH vê a foto
    assert client.get("/punches-integrity", headers=world["hr"]).json()["ok"]

    assert punch(client, kh, t).status_code == 401  # o ticket é de uso único
    assert db.execute(select(AuditLog).where(AuditLog.action == "kiosk_punch")).scalars().one().after["kiosk"] == k["id"]


def test_expired_ticket_and_ticket_of_another_kiosk_do_not_work(client, world, db):
    kh, _ = paired(client, world)
    kh2, _ = paired(client, world, "CT-02")
    code = code_of(client, world["emp"])
    t = identify(client, kh, "code", code).json()["ticket"]
    client.post("/kiosk/consent-photo", headers=kh, json={"ticket": t})
    assert punch(client, kh2, t).status_code == 401  # ticket de outro aparelho

    row = db.get(KioskTicket, t)
    row.expires_at = row.expires_at - timedelta(minutes=5)
    db.commit()
    assert punch(client, kh, t).status_code == 401  # expirou
    assert client.post("/kiosk/consent-photo", headers=kh, json={"ticket": "inventado"}).status_code == 401


def test_distance_outside_radius_is_flagged_but_never_blocks(client, world, db):
    kh, _ = paired(client, world)
    code = code_of(client, world["emp"])
    t = identify(client, kh, "code", code).json()["ticket"]
    r = consent_and_punch(client, kh, t, latitude=-23.5605, longitude=-46.6333)  # ~1,1 km ao sul
    assert r.status_code == 201 and r.json()["outside_radius"] is True and 900 < r.json()["distance_m"] < 1300
    t2 = identify(client, kh, "code", code).json()["ticket"]
    r = punch(client, kh, t2)  # sem GPS: registra, sem distância
    assert r.status_code == 201 and r.json()["distance_m"] is None and r.json()["outside_radius"] is None


def test_full_day_through_the_kiosk_follows_the_order_and_closes_the_day(client, world, db):
    kh, _ = paired(client, world)
    code = code_of(client, world["emp"])
    labels = []
    for _ in range(4):
        info = identify(client, kh, "code", code).json()
        labels.append(info["next_label"])
        assert consent_and_punch(client, kh, info["ticket"]).status_code == 201
    assert labels == ["Entrada", "Intervalo", "Retorno do intervalo", "Saída"]
    r = identify(client, kh, "code", code)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "day_closed"  # a quarta batida é definitiva
    assert db.query(PunchPhoto).count() == 4


def test_storage_failure_rolls_back_the_punch_because_the_photo_is_mandatory(client, world, db, monkeypatch):
    kh, _ = paired(client, world)
    t = identify(client, kh, "code", code_of(client, world["emp"])).json()["ticket"]
    client.post("/kiosk/consent-photo", headers=kh, json={"ticket": t})

    from app.services import photos as svc_photos

    original = svc_photos.save

    def boom(*_a, **_k):
        raise svc_photos.PhotoError(503, "Armazenamento de fotos indisponível (teste)")

    monkeypatch.setattr(svc_photos, "save", boom)
    r = punch(client, kh, t)
    assert r.status_code == 503
    assert db.query(Punch).count() == 0  # sem foto não há batida na Central
    monkeypatch.setattr(svc_photos, "save", original)
    assert punch(client, kh, t).status_code == 201  # o ticket não foi gasto: a pessoa tenta de novo


def test_personal_app_punch_is_unaffected_and_codes_exist_for_new_users(client, world, db):
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    p = db.query(Punch).one()
    assert p.collector == "02" and p.kiosk_id is None and p.distance_m is None
    assert all(u.employee_code for u in db.query(User).all())  # todos os criados pela API já têm código
    codes = [u.employee_code for u in db.query(User).filter_by(company_id=db.get(User, world["ids"]["emp"]).company_id)]
    assert len(codes) == len(set(codes))
    assert totp.STEP_SECONDS == 30


def test_badge_pdf_single_and_batch_respect_permissions(client, world, db):
    import io

    from pypdf import PdfReader

    emp_id = world["ids"]["emp"]
    code = code_of(client, world["emp"])
    r = client.get(f"/users/{emp_id}/badge.pdf", headers=world["hr"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    assert "Ana Colab" in text and code in text and "Empresa A" in text
    assert client.get(f"/users/{emp_id}/badge.pdf", headers=world["mgr"]).status_code == 403
    assert client.get(f"/users/{emp_id}/badge.pdf", headers=world["adminB"]).status_code == 404

    hr_batch = PdfReader(io.BytesIO(client.get("/badges.pdf", headers=world["hr"]).content)).pages[0].extract_text()
    assert "Ana Colab" in hr_batch and "Beto Sem Gestor" in hr_batch
    assert "Rita RH" not in hr_batch and "Administrador" not in hr_batch  # RH não imprime crachá de RH/admin
    admin_batch = PdfReader(io.BytesIO(client.get("/badges.pdf", headers=world["admin"]).content)).pages[0].extract_text()
    assert "Rita RH" in admin_batch
    only = PdfReader(io.BytesIO(client.get(f"/badges.pdf?ids={emp_id}", headers=world["hr"]).content)).pages[0].extract_text()
    assert "Ana Colab" in only and "Beto" not in only
    assert db.execute(select(AuditLog).where(AuditLog.action == "badge_print")).scalars().all()


def test_kiosk_list_counts_todays_punches(client, world):
    kh, k = paired(client, world)
    code = code_of(client, world["emp"])
    t = identify(client, kh, "code", code).json()["ticket"]
    assert consent_and_punch(client, kh, t).status_code == 201
    row = client.get("/kiosks", headers=world["hr"]).json()[0]
    assert row["id"] == k["id"] and row["punches_today"] == 1 and row["paired"] is True and row["last_seen_at"]
    assert client.get("/kiosks", headers=world["emp"]).status_code == 403


# --- fase 4: origem da batida e política "só Central" ---------------------------------
def test_my_punches_show_the_origin_app_or_central(client, world):
    kh, _ = paired(client, world, "CT-01 Recepção")
    t = identify(client, kh, "code", code_of(client, world["emp"])).json()["ticket"]
    assert consent_and_punch(client, kh, t).status_code == 201
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    origins = [p["origin"] for p in client.get("/punches", headers=world["emp"]).json()]
    assert origins == ["Aplicativo", "Central CT-01 Recepção"]  # da mais recente para a mais antiga


def test_kiosk_only_policy_blocks_the_app_but_not_the_central(client, world, db):
    uid = client.get("/auth/me", headers=world["emp"]).json()["id"]
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"punch_policy": "nope"}).status_code == 422
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"punch_policy": "kiosk"}).status_code == 200
    r = client.post("/punches", headers=world["emp"], json={})
    assert r.status_code == 403 and "Central" in r.json()["detail"]
    assert client.get("/punches/next", headers=world["emp"]).json()["app_blocked"] is True
    kh, _ = paired(client, world)
    t = identify(client, kh, "code", code_of(client, world["emp"])).json()["ticket"]
    assert consent_and_punch(client, kh, t).status_code == 201  # a Central continua valendo
    assert client.patch(f"/users/{uid}", headers=world["hr"], json={"punch_policy": "both"}).status_code == 200
    assert client.get("/punches/next", headers=world["emp"]).json()["app_blocked"] is False


# --- fase 5: relatórios por origem, divergências e código no CSV ---------------------
def _day_range():
    from datetime import date
    d = date.today()
    return f"start={d - timedelta(days=1)}&end={d + timedelta(days=1)}"


def test_punch_report_filters_by_origin_and_divergences_flag_far_or_missing_location(client, world, db):
    kh, k = paired(client, world, "CT-01")
    code = code_of(client, world["emp"])
    t = identify(client, kh, "code", code).json()["ticket"]
    assert consent_and_punch(client, kh, t, latitude=-23.5505, longitude=-46.6333).status_code == 201  # no posto
    t = identify(client, kh, "code", code).json()["ticket"]
    assert punch(client, kh, t, latitude=-23.60, longitude=-46.70).status_code == 201  # longe
    t = identify(client, kh, "code", code).json()["ticket"]
    assert punch(client, kh, t).status_code == 201  # sem GPS
    assert identify(client, kh, "code", "000001").status_code in (401, 404)  # falha de identificação
    assert client.post("/punches", headers=world["emp"], json={}).status_code in (201, 409)

    q = _day_range()
    def lines(url):
        r = client.get(url, headers=world["hr"])
        assert r.status_code == 200, r.text
        return [ln for ln in r.content.decode("utf-8-sig").split("\r\n") if ln]
    assert len(lines(f"/reports/punches?{q}&origin=central")) - 1 == 3
    assert all("Central CT-01" in ln for ln in lines(f"/reports/punches?{q}&origin=central")[1:])
    assert all("Aplicativo" in ln for ln in lines(f"/reports/punches?{q}&origin=app")[1:])
    assert client.get(f"/reports/punches?{q}&origin=xx", headers=world["hr"]).status_code == 422
    assert client.get(f"/reports/punches?{q}&format=pdf", headers=world["hr"]).headers["content-type"] == "application/pdf"

    div = "\n".join(lines(f"/reports/kiosk-divergences?{q}"))
    assert "Fora do posto" in div and "Sem localização" in div and "Falhas de identificação" in div
    assert client.get(f"/reports/kiosk-divergences?{q}", headers=world["emp"]).status_code == 403
    assert client.get(f"/reports/kiosk-divergences?{q}&format=pdf", headers=world["hr"]).status_code == 200


def test_csv_import_accepts_optional_internal_code(client, world, db):
    from tests.test_csv_import import cpf, post
    head = "nome;email;cpf;codigo\n"
    r = post(client, world["hr"], head + f"Zé Um;ze1@x.com;{cpf(901)};445566\nZé Dois;ze2@x.com;{cpf(902)};\n", dry_run=False)
    assert r.status_code in (200, 201), r.text
    codes = {u.email: u.employee_code for u in db.execute(select(User).where(User.email.in_(["ze1@x.com", "ze2@x.com"]))).scalars()}
    assert codes["ze1@x.com"] == "445566" and len(codes["ze2@x.com"]) == 6  # o vazio é gerado
    dup = post(client, world["hr"], head + f"Zé Três;ze3@x.com;{cpf(903)};445566\n")
    assert "Código já usado" in dup.text and dup.json()["valid"] == 0
    bad = post(client, world["hr"], head + f"Zé Q;ze4@x.com;{cpf(904)};12\n")
    assert "Código inválido" in bad.text and bad.json()["valid"] == 0


# --- Central sem internet (opção C): só o QR do crachá impresso, conferido no envio -----
def _offline(client, kh, qr, key="k-0000001", minutes_ago=30, **extra):
    from datetime import UTC, datetime
    at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return client.post("/kiosk/offline-punch", headers=kh, json={"qr": qr, "photo": B64, "client_key": key, "occurred_at": at, **extra})


def test_offline_punch_is_verified_on_sync_and_is_idempotent(client, world, db):
    kh, _ = paired(client, world)
    emp = world["ids"]["emp"]
    qr = client.get(f"/users/{emp}/badge", headers=world["hr"]).json()["qr"]
    assert client.get("/kiosk/state", headers=kh).json()["offline"]["enabled"] is True
    assert _offline(client, kh, qr).status_code == 422  # ainda sem consentimento da foto
    assert client.post("/auth/consent-photo", headers=world["emp"]).status_code == 200

    r = _offline(client, kh, qr, latitude=-23.5505, longitude=-46.6333)
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "Entrada"  # o tipo vem do servidor, pela sequência
    again = _offline(client, kh, qr, latitude=-23.5505, longitude=-46.6333)
    assert again.status_code == 201 and again.json()["nsr"] == r.json()["nsr"]  # reenvio: mesma batida
    p = db.execute(select(Punch).where(Punch.client_key == "k-0000001")).scalar_one()
    assert p.offline and p.collector == "04" and p.kiosk_id and db.query(PunchPhoto).count() == 1
    assert p.occurred_at < p.recorded_at  # a hora é a da batida, não a do envio


def test_offline_punch_rejections_are_audited_and_never_recorded(client, world, db):
    kh, _ = paired(client, world)
    emp = world["ids"]["emp"]
    client.post("/auth/consent-photo", headers=world["emp"])
    qr = client.get(f"/users/{emp}/badge", headers=world["hr"]).json()["qr"]
    rot = client.get("/auth/badge-qr", headers=world["emp"]).json()["qr"]
    assert _offline(client, kh, rot, key="k-0000002").status_code == 422  # QR rotativo não vale offline
    assert _offline(client, kh, qr[:-1] + ("0" if qr[-1] != "0" else "1"), key="k-0000003").status_code == 422  # adulterado
    assert _offline(client, kh, qr, key="k-0000004", minutes_ago=-30).status_code == 422  # no futuro
    assert _offline(client, kh, qr, key="k-0000005", minutes_ago=60 * (settings.offline_max_hours + 1)).status_code == 422  # vencida
    client.post(f"/users/{emp}/badge/regenerate", headers=world["hr"])
    assert _offline(client, kh, qr, key="k-0000006").status_code == 422  # crachá regenerado depois de guardado
    assert db.query(Punch).count() == 0
    reasons = [a.action for a in db.execute(select(AuditLog).where(AuditLog.action == "kiosk_offline_rejected")).scalars()]
    assert len(reasons) >= 5


def test_offline_is_disabled_when_the_company_requires_pin(client, world, db):
    kh, _ = paired(client, world)
    qr = client.get(f"/users/{world['ids']['emp']}/badge", headers=world["hr"]).json()["qr"]
    client.post("/auth/consent-photo", headers=world["emp"])
    client.patch("/company", headers=world["admin"], json={"kiosk_pin_required": True})
    assert client.get("/kiosk/state", headers=kh).json()["offline"]["enabled"] is False
    assert _offline(client, kh, qr, key="k-0000007").status_code == 422


def test_offline_punch_older_than_an_existing_punch_is_rejected(client, world, db):
    kh, _ = paired(client, world)
    emp = world["ids"]["emp"]
    client.post("/auth/consent-photo", headers=world["emp"])
    qr = client.get(f"/users/{emp}/badge", headers=world["hr"]).json()["qr"]
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201  # batida online, agora
    r = _offline(client, kh, qr, key="k-0000009", minutes_ago=20)  # a do tablet é mais velha que a já registrada
    assert r.status_code == 422 and "posterior" in r.text
    assert db.query(Punch).count() == 1


def test_app_badge_qr_is_a_standard_qr_not_a_micro_qr(client, world):
    """Micro QR (que o segno escolhe sozinho para textos curtos) não é lido por câmeras de celular nem por jsQR/BarcodeDetector."""
    import re
    from urllib.parse import unquote
    r = client.get("/auth/badge-qr", headers=world["emp"]).json()
    svg = unquote(r["image"].split(",", 1)[1])
    width = int(re.search(r"width=.([\d.]+)", svg).group(1))
    assert width >= (21 + 8) * 8  # versão 1 (21 módulos) + 4 de margem de cada lado, 8 px por módulo
