"""Senha, sessões e verificação em duas etapas (TOTP)."""
import os

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, User
from app.services import passwords, totp
from tests.conftest import PASSWORD, login, make_cpf

NEW_PASSWORD = "outra-senha-forte-77"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login_raw(client, email, password=PASSWORD, otp=None):
    body = {"email": email, "password": password}
    if otp is not None:
        body["otp"] = otp
    return client.post("/auth/login", json=body)


# Relógio do TOTP congelado: com o relógio real, um teste que cruza a virada de um passo de 30 s (entre ativar e
# logar, por exemplo) muda de resultado de vez em quando. TEST_TOTP_NOW permite provar a estabilidade em qualquer
# ponto do passo (ex.: 1700000029.99 = último instante do passo; 1700000030 = primeiro do seguinte).
FROZEN_NOW = float(os.environ.get("TEST_TOTP_NOW", "1700000015"))


class _FrozenTime:
    @staticmethod
    def time() -> float:
        return FROZEN_NOW


@pytest.fixture(autouse=True)
def frozen_totp_clock(monkeypatch):
    monkeypatch.setattr(totp, "time", _FrozenTime)


def now_code(secret: str, shift: int = 0) -> str:
    return totp.code_at(secret, FROZEN_NOW + shift * totp.STEP_SECONDS)


def enable_2fa(client, headers):
    """Configura o 2FA da conta; devolve (segredo, códigos de recuperação, novos cabeçalhos)."""
    setup = client.post("/auth/2fa/setup", headers=headers).json()
    r = client.post("/auth/2fa/enable", headers=headers, json={"code": now_code(setup["secret"])})
    assert r.status_code == 200, r.text
    body = r.json()
    return setup["secret"], body["recovery_codes"], auth(body["access_token"])


# ============================== TOTP (RFC 6238) ==============================
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890" em base32 (SHA-1)


@pytest.mark.parametrize("timestamp,expected", [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037"),
])
def test_totp_matches_the_rfc_6238_test_vectors(timestamp, expected):
    assert totp.code_at(RFC_SECRET, timestamp) == expected  # os oito dígitos da RFC terminam nestes seis


def test_verify_window_replay_and_bad_input():
    t = 1234567890
    assert totp.verify(RFC_SECRET, "005924", now=t) == t // 30
    assert totp.verify(RFC_SECRET, "005 924", now=t) == t // 30  # espaços são ignorados
    assert totp.verify(RFC_SECRET, "005924", now=t + 25) == t // 30  # um passo à frente: tolerado (relógio do celular)
    assert totp.verify(RFC_SECRET, "005924", now=t + 95) is None  # três passos depois: expirou
    assert totp.verify(RFC_SECRET, "005924", last_step=t // 30, now=t) is None  # o mesmo código não vale duas vezes
    for bad in ("", "12345", "1234567", "abcdef", None):
        assert totp.verify(RFC_SECRET, bad, now=t) is None


def test_secret_is_encrypted_and_recovery_codes_are_well_formed(monkeypatch):
    secret = totp.new_secret()
    token = totp.encrypt(secret)
    assert secret not in token and totp.decrypt(token) == secret
    monkeypatch.setattr(settings, "totp_key", "outra-chave-de-teste-com-32-caracteres!!")
    assert totp.decrypt(token) is None  # chave trocada: ilegível, não quebra
    codes = totp.new_recovery_codes()
    assert len(codes) == len(set(codes)) == 8 and all(len(c) == 9 and c[4] == "-" for c in codes)
    assert totp.hash_recovery(codes[0]) == totp.hash_recovery(codes[0].upper().replace("-", " "))  # tolera a digitação
    assert totp.looks_like_recovery(codes[0]) and not totp.looks_like_recovery("123456")


def test_password_policy():
    check = passwords.check_policy
    assert check("curta1") and check("somente-letras-aqui") and check("1234567890123")
    assert check("aaaaaaaaaa1") == "A senha é simples demais"
    assert check("ana@a.com", email="ana@a.com") and check("ana", email="ana@a.com") is not None
    assert check("minha52998224725senha", cpf="52998224725")
    assert check("mesma-senha-123", current="mesma-senha-123")
    assert check("uma-senha-boa-42") is None
    temp = passwords.generate_temp()
    assert len(temp) == 12 and check(temp) is None and not set(temp) & set("0O1lI")


# ============================== troca de senha e sessões ======================
def test_change_password_rules_and_session_revocation(client, world):
    old = client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD}).json()
    h = auth(old["access_token"])
    assert client.post("/auth/change-password", headers=h, json={"current_password": "errada-errada", "new_password": NEW_PASSWORD}).status_code == 400
    for weak in ("curta", "so-letras-sem-numero", PASSWORD):
        assert client.post("/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": weak}).status_code == 422
    r = client.post("/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    fresh = auth(r.json()["access_token"])
    assert client.get("/auth/me", headers=fresh).status_code == 200  # a sessão que trocou continua
    assert client.get("/auth/me", headers=h).status_code == 401  # as outras caem
    assert client.post("/auth/refresh", json={"refresh_token": old["refresh_token"]}).status_code == 401
    assert login_raw(client, "ana@a.com", PASSWORD).status_code == 401 and login_raw(client, "ana@a.com", NEW_PASSWORD).status_code == 200


def test_temporary_password_forces_a_change_before_anything_else(client, world):
    made = client.post("/users", headers=world["hr"], json={  # padrão da API: senha inicial é temporária
        "name": "Nova Pessoa", "email": "nova@a.com", "password": "senha-inicial-12", "cpf": make_cpf(600000001)})
    assert made.status_code == 201 and made.json()["must_change_password"] is True
    h = auth(login_raw(client, "nova@a.com", "senha-inicial-12").json()["access_token"])
    assert client.get("/auth/me", headers=h).json()["must_change_password"] is True  # o front descobre por aqui
    blocked = client.get("/mirror?month=2026-08", headers=h)
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"
    assert client.post("/punches", headers=h, json={}).status_code == 403  # nem registrar ponto
    r = client.post("/auth/change-password", headers=h, json={"current_password": "senha-inicial-12", "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    assert client.post("/punches", headers=auth(r.json()["access_token"]), json={}).status_code == 201


def test_hr_reset_password_and_reset_2fa_permissions(client, world):
    ids = world["ids"]
    # permissões (antes do reset, que derruba a sessão da própria colaboradora)
    assert client.post(f"/users/{ids['emp']}/reset-password", headers=world["mgr"]).status_code == 403
    assert client.post(f"/users/{ids['emp']}/reset-password", headers=world["emp"]).status_code == 403
    assert client.post(f"/users/{ids['emp']}/reset-password", headers=world["adminB"]).status_code == 404  # outra empresa
    assert client.post(f"/users/{ids['hr']}/reset-password", headers=world["hr"]).status_code == 409  # a própria: Minha conta
    admin_id = client.get("/users", headers=world["admin"]).json()[0]["id"]
    assert client.post(f"/users/{admin_id}/reset-password", headers=world["hr"]).status_code == 403  # RH não mexe no administrador
    assert client.post(f"/users/{admin_id}/reset-2fa", headers=world["hr"]).status_code == 403

    old_session = world["emp"]
    r = client.post(f"/users/{ids['emp']}/reset-password", headers=world["hr"])
    assert r.status_code == 200
    temp = r.json()["password"]
    assert passwords.check_policy(temp) is None and login_raw(client, "ana@a.com", PASSWORD).status_code == 401  # a antiga morreu
    assert client.get("/auth/me", headers=old_session).status_code == 401  # a sessão aberta caiu
    h = auth(login_raw(client, "ana@a.com", temp).json()["access_token"])
    assert client.get("/mirror?month=2026-08", headers=h).status_code == 403  # troca obrigatória
    assert client.post(f"/users/{ids['hr']}/reset-2fa", headers=world["admin"]).status_code == 200


# ============================== 2FA no login ==================================
def test_two_factor_setup_enable_and_login(client, world, db):
    h = login(client, "ana@a.com")
    secret, codes, fresh = enable_2fa(client, h)
    assert client.get("/auth/me", headers=h).status_code == 401  # ativar derruba as outras sessões
    me = client.get("/auth/me", headers=fresh).json()
    assert me["totp_enabled"] is True and len(codes) == 8
    assert client.get("/auth/2fa", headers=fresh).json() == {"enabled": True, "recovery_codes_left": 8, "required": False}

    # o segredo não fica legível no banco
    row = db.execute(select(User).where(User.email == "ana@a.com")).scalar_one()
    assert secret not in row.totp_secret and all(c not in str(row.totp_recovery) for c in codes)

    # login: senha certa sem código -> pede o código; código certo -> entra; o mesmo código não repete
    ask = login_raw(client, "ana@a.com")
    assert ask.status_code == 401 and ask.json()["detail"]["code"] == "otp_required"
    assert login_raw(client, "ana@a.com", otp=now_code(secret)).status_code == 401  # o código usado para ativar já foi consumido
    ok = login_raw(client, "ana@a.com", otp=now_code(secret, shift=1))  # o passo seguinte vale
    assert ok.status_code == 200
    replay = login_raw(client, "ana@a.com", otp=now_code(secret, shift=1))
    assert replay.status_code == 401 and replay.json()["detail"]["code"] == "otp_invalid"  # e não vale duas vezes


def test_setup_and_enable_edge_cases(client, world):
    h = login(client, "ana@a.com")
    assert client.post("/auth/2fa/enable", headers=h, json={"code": "123456"}).status_code == 409  # sem setup
    setup = client.post("/auth/2fa/setup", headers=h).json()
    assert setup["uri"].startswith("otpauth://totp/Ponto:ana%40a.com?secret=") and setup["qr"].startswith("data:image/svg+xml")
    assert client.post("/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 422
    assert client.post("/auth/2fa/enable", headers=h, json={"code": now_code(setup["secret"])}).status_code == 200
    h2 = login_raw(client, "ana@a.com", otp=now_code(setup["secret"], shift=1)).json()["access_token"]
    assert client.post("/auth/2fa/setup", headers=auth(h2)).status_code == 409  # já ativo
    assert client.post("/auth/2fa/enable", headers=auth(h2), json={"code": "123456"}).status_code == 409


def test_wrong_codes_count_toward_the_login_throttle(client, world):
    secret, _, _ = enable_2fa(client, login(client, "ana@a.com"))
    for _ in range(settings.login_max_failures):
        assert login_raw(client, "ana@a.com", otp="000000").status_code == 401
    blocked = login_raw(client, "ana@a.com", otp=now_code(secret))
    assert blocked.status_code == 429  # nem o código certo passa enquanto bloqueado


def test_recovery_codes_work_once(client, world):
    _, codes, fresh = enable_2fa(client, login(client, "ana@a.com"))
    assert login_raw(client, "ana@a.com", otp=codes[0]).status_code == 200
    again = login_raw(client, "ana@a.com", otp=codes[0])
    assert again.status_code == 401 and again.json()["detail"]["code"] == "otp_invalid"  # consumido
    assert login_raw(client, "ana@a.com", otp=codes[1].upper().replace("-", " ")).status_code == 200  # tolera a digitação
    assert client.get("/auth/2fa", headers=fresh).status_code == 200


def test_disable_and_regenerate_recovery_codes_need_password_and_code(client, world):
    secret, codes, fresh = enable_2fa(client, login(client, "ana@a.com"))
    body = {"password": PASSWORD, "code": now_code(secret, shift=1)}
    assert client.post("/auth/2fa/disable", headers=fresh, json={**body, "password": "errada-errada"}).status_code == 400
    assert client.post("/auth/2fa/disable", headers=fresh, json={**body, "code": "000000"}).status_code == 400
    regen = client.post("/auth/2fa/recovery-codes", headers=fresh, json=body)
    assert regen.status_code == 200 and len(regen.json()["recovery_codes"]) == 8
    assert login_raw(client, "ana@a.com", otp=codes[0]).status_code == 401  # os códigos antigos morreram
    off = client.post("/auth/2fa/disable", headers=fresh, json={"password": PASSWORD, "code": regen.json()["recovery_codes"][0]})
    assert off.status_code == 200  # um código de recuperação também autoriza desativar
    assert login_raw(client, "ana@a.com").status_code == 200  # agora entra só com a senha
    assert client.post("/auth/2fa/disable", headers=auth(off.json()["access_token"]), json=body).status_code == 409


def test_admin_can_reset_2fa_for_someone_who_lost_the_phone(client, world):
    enable_2fa(client, login(client, "ana@a.com"))
    assert login_raw(client, "ana@a.com").status_code == 401
    assert client.post(f"/users/{world['ids']['emp']}/reset-2fa", headers=world["hr"]).status_code == 200
    assert login_raw(client, "ana@a.com").status_code == 200  # sem 2FA de novo; ela configura outra vez


def test_2fa_can_be_required_for_some_roles(client, world, monkeypatch):
    monkeypatch.setattr(settings, "require_2fa_roles", "hr, admin")
    h = world["hr"]
    blocked = client.get("/users", headers=h)
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "two_factor_required"
    assert client.get("/auth/2fa", headers=h).json()["required"] is True  # ainda dá para configurar
    secret, _, fresh = enable_2fa(client, h)
    assert client.get("/users", headers=fresh).status_code == 200  # cumprida a exigência, libera
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201
    # desativar não é permitido "por fora": ao desativar, o perfil volta a ser barrado
    off = client.post("/auth/2fa/disable", headers=fresh, json={"password": PASSWORD, "code": now_code(secret, shift=1)})
    assert client.get("/users", headers=auth(off.json()["access_token"])).status_code == 403


def test_security_events_are_audited_without_secrets(client, world, db):
    secret, codes, fresh = enable_2fa(client, login(client, "ana@a.com"))
    client.post("/auth/change-password", headers=fresh, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    rows = db.execute(select(AuditLog).where(AuditLog.entity == "user")).scalars().all()
    actions = [r.action for r in rows]
    assert "2fa_enabled" in actions and "change_password" in actions
    dump = str([(r.before, r.after, r.entity_id) for r in rows])
    assert secret not in dump and NEW_PASSWORD not in dump and not any(c in dump for c in codes)


def test_generated_temporary_passwords_always_satisfy_the_policy():
    for _ in range(3000):  # antes, ~11% saíam sem número e a própria política os recusava
        assert passwords.check_policy(passwords.generate_temp()) is None
