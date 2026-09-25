"""Endurecimento para produção: prontidão, cabeçalhos de segurança, logs estruturados e limite de login."""
import io
import json
import logging

from sqlalchemy import select

from app import observability
from app.config import settings
from app.models import AuditLog
from tests.conftest import PASSWORD


def test_liveness_and_readiness(client, world):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_readiness_reports_unavailable_when_database_fails(client, world):
    from app.db import get_db
    from app.main import app

    class Broken:
        def execute(self, *_):
            raise RuntimeError("banco fora")

    app.dependency_overrides[get_db] = lambda: Broken()
    r = client.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_security_headers_and_request_id(client, world):
    r = client.get("/auth/me", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 401
    assert r.headers["x-request-id"] == "abc-123"  # propagado; gerado quando ausente
    assert client.get("/health").headers["x-request-id"]
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "geolocation=(self)" in r.headers["permissions-policy"] and "camera=(self)" in r.headers["permissions-policy"]


def test_swagger_pages_are_exempt_from_strict_csp(client):
    from starlette.testclient import TestClient

    from app.main import app

    raw = TestClient(app).get("/docs")  # fora do prefixo /api
    assert raw.status_code == 200 and "content-security-policy" not in raw.headers


def test_request_log_is_structured_json_without_secrets(client, world):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(observability.JsonFormatter())
    logger = logging.getLogger("ponto.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD}, headers={"X-Request-ID": "req-1"})
    finally:
        logger.removeHandler(handler)
    entry = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert entry["msg"] == "request" and entry["method"] == "POST" and entry["path"] == "/api/auth/login"
    assert entry["status"] == 200 and entry["request_id"] == "req-1" and entry["ms"] >= 0
    assert PASSWORD not in stream.getvalue() and "ana@a.com" not in stream.getvalue()  # nunca senha nem e-mail


def test_login_is_throttled_per_email_after_repeated_failures(client, world, db):
    for _ in range(settings.login_max_failures):
        assert client.post("/auth/login", json={"email": "ana@a.com", "password": "errada-errada"}).status_code == 401
    # bloqueado, mesmo com a senha correta
    r = client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD})
    assert r.status_code == 429 and "Muitas tentativas" in r.json()["detail"]
    # outro e-mail não é afetado (um escritório inteiro compartilha o IP)
    assert client.post("/auth/login", json={"email": "beto@a.com", "password": PASSWORD}).status_code == 200
    # falhas registradas sem o e-mail em claro; o bloqueio em si não gera novos registros
    rows = db.execute(select(AuditLog).where(AuditLog.action == "login_failed")).scalars().all()
    assert len(rows) == settings.login_max_failures and all("@" not in (r.entity_id or "") for r in rows)


def test_login_block_expires_with_the_window(client, world, monkeypatch):
    for _ in range(settings.login_max_failures):
        client.post("/auth/login", json={"email": "ana@a.com", "password": "errada-errada"})
    assert client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD}).status_code == 429
    monkeypatch.setattr(settings, "login_window_minutes", 0)  # janela vazia: as falhas antigas não contam mais
    assert client.post("/auth/login", json={"email": "ana@a.com", "password": PASSWORD}).status_code == 200


def test_ip_ceiling_is_much_higher_than_the_per_email_limit(client, world, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 8)
    for i in range(8):  # 8 e-mails diferentes, 1 falha cada: nenhum e-mail bloqueia, mas o IP sim
        client.post("/auth/login", json={"email": f"x{i}@a.com", "password": "errada-errada"})
    assert client.post("/auth/login", json={"email": "beto@a.com", "password": PASSWORD}).status_code == 429
