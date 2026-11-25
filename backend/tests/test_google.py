"""Entrar com Google: sem cadastro aberto, vínculo da conta, senha desligável por empresa e sessão em cookie HttpOnly."""
import pytest

from app.config import settings
from app.services import google_auth
from tests.conftest import PASSWORD, login, make_cpf

TOKENS = {  # credencial (o que o navegador receberia do Google) -> conteúdo já verificado
    "ana": {"sub": "g-ana", "email": "ana@a.com", "email_verified": True, "name": "Ana"},
    "ana-outro-email": {"sub": "g-ana", "email": "ana.pessoal@gmail.com", "email_verified": True, "name": "Ana"},
    "estranho": {"sub": "g-x", "email": "x@gmail.com", "email_verified": True, "name": "X"},
    "nao-verificado": {"sub": "g-nv", "email": "beto@a.com", "email_verified": False, "name": "B"},
    "admin": {"sub": "g-admin", "email": "admin@a.com", "email_verified": True, "name": "Admin"},
    "beto-pessoal": {"sub": "g-beto", "email": "beto.casa@gmail.com", "email_verified": True, "name": "Beto"},
}


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "teste.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "cookie_secure", False)  # o cliente de teste fala HTTP

    def verify(credential):
        if credential not in TOKENS:
            raise google_auth.GoogleAuthError("Não foi possível confirmar o login com o Google. Tente de novo.")
        return TOKENS[credential]

    monkeypatch.setattr(google_auth, "verify", verify)


def g(client, cred):
    return client.post("/auth/google", json={"credential": cred})


def test_config_is_public(client):
    assert client.get("/auth/config").json()["google_client_id"] == "teste.apps.googleusercontent.com"


def test_google_login_matches_registered_email_and_links_the_account(client, world):
    r = g(client, "ana")
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/auth/me", headers=h).json()
    assert me["email"] == "ana@a.com" and me["google_linked"] and me["login_method"] == "google" and me["restriction"] is None
    # depois de vinculada, a conta Google vale mesmo com outro e-mail no Google
    assert g(client, "ana-outro-email").status_code == 200


def test_no_open_signup_and_unverified_email_refused(client, world):
    r = g(client, "estranho")
    assert r.status_code == 401 and "não está cadastrada" in r.json()["detail"]
    assert g(client, "nao-verificado").status_code == 401
    assert g(client, "invalido").status_code == 401


def test_link_from_account_with_another_email(client, world):
    beto = login(client, "beto@a.com")
    assert g(client, "beto-pessoal").status_code == 401  # e-mail do Google diferente do cadastro
    r = client.post("/auth/google/link", headers=beto, json={"credential": "beto-pessoal"})
    assert r.status_code == 200 and r.json()["google_linked"]
    assert g(client, "beto-pessoal").status_code == 200
    # a mesma conta Google não serve para dois cadastros
    ana = login(client, "ana@a.com")
    assert client.post("/auth/google/link", headers=ana, json={"credential": "beto-pessoal"}).status_code == 409
    assert client.post("/auth/google/unlink", headers=beto).json()["google_linked"] is False


def test_inactive_or_kiosk_only_person_cannot_enter(client, world):
    adm = world["admin"]
    client.patch(f"/users/{world['ids']['emp']}", headers=adm, json={"active": False})
    assert g(client, "ana").status_code == 401


def test_google_session_skips_password_restrictions(client, world):
    adm = world["admin"]
    r = client.post("/users", headers=adm, json={"name": "Nova Pessoa", "email": "nova@a.com", "cpf": make_cpf(600000001),
                                                 "password": PASSWORD})  # senha temporária: troca obrigatória
    assert r.status_code == 201
    TOKENS["nova"] = {"sub": "g-nova", "email": "nova@a.com", "email_verified": True, "name": "Nova"}
    tok = g(client, "nova").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/auth/me", headers=h).json()["restriction"] is None
    assert client.get("/punches/next", headers=h).status_code == 200  # nada bloqueado
    # com senha, a pendência continua
    r = client.post("/auth/login", json={"email": "nova@a.com", "password": PASSWORD})
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=h2).json()["restriction"] == "password_change_required"


def test_company_can_turn_off_password_login(client, world):
    adm = world["admin"]
    r = client.patch("/company", headers=adm, json={"password_login": False})
    assert r.status_code == 409 and "Vincule" in r.json()["detail"]  # o admin ainda não tem Google
    assert client.post("/auth/google/link", headers=adm, json={"credential": "admin"}).status_code == 200
    assert client.patch("/company", headers=adm, json={"password_login": False}).json()["password_login"] is False
    r = client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_login_disabled"
    assert g(client, "ana").status_code == 200
    # não dá para desvincular quando só o Google entra
    gadm = {"Authorization": f"Bearer {g(client, 'admin').json()['access_token']}"}
    assert client.post("/auth/google/unlink", headers=gadm).status_code == 409


def test_refresh_uses_httponly_cookie_and_logout_clears_it(client, world):
    r = g(client, "ana")
    cookie = r.headers["set-cookie"]
    assert "ponto_refresh=" in cookie and "HttpOnly" in cookie and "samesite=strict" in cookie.lower() and "Path=/api/auth" in cookie
    r2 = client.post("/auth/refresh")  # sem corpo: vale o cookie
    assert r2.status_code == 200
    h = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert client.get("/auth/me", headers=h).json()["login_method"] == "google"  # a renovação mantém a forma de entrada
    client.post("/auth/logout")
    assert client.post("/auth/refresh").status_code == 401
