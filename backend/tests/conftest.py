import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.db import Base, get_db, make_engine
from app.main import app
from app.seed import create_company

TEST_DB_URL = os.environ.get("PONTO_TEST_DATABASE_URL")  # ex.: postgresql+psycopg://ponto@127.0.0.1:5544/ponto_test


@pytest.fixture()
def engine():
    """SQLite em memória por padrão; PostgreSQL real quando PONTO_TEST_DATABASE_URL está definida."""
    eng = make_engine(TEST_DB_URL or "sqlite://")
    if TEST_DB_URL:
        Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    if TEST_DB_URL:
        Base.metadata.drop_all(eng)
    eng.dispose()


def drop_immutability_guard(conn, table: str, delete: bool = False):
    """Simula um atacante com acesso ao banco removendo o gatilho (usado só em testes)."""
    if conn.dialect.name == "postgresql":
        conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {table}_immutable"))
    else:
        conn.execute(text(f"DROP TRIGGER {table}_no_{'delete' if delete else 'update'}"))


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture()
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    class ApiClient(TestClient):
        """Prefixa /api em todas as rotas, como o front-end faz."""

        def request(self, method, url, *args, **kwargs):
            if url.startswith("/"):
                url = "/api" + url
            return super().request(method, url, *args, **kwargs)

    app.dependency_overrides[get_db] = override
    yield ApiClient(app)
    app.dependency_overrides.clear()


PASSWORD = "senha-forte-123"


def make_cpf(n: int) -> str:
    """CPF válido e determinístico a partir de um número (só dígitos)."""
    base = [int(c) for c in f"{n:09d}"]
    for size in (9, 10):
        total = sum(base[i] * (size + 1 - i) for i in range(size))
        base.append((total * 10) % 11 % 10)
    return "".join(map(str, base))


def login(client, email, password=PASSWORD):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def world(client, db):
    """Empresa A: admin, RH, gestor, dois colaboradores. Empresa B: admin."""
    create_company(db, "Empresa A", "11.111.111/0001-11", "admin@a.com", PASSWORD, make_cpf(100000001))
    create_company(db, "Empresa B", "22.222.222/0001-22", "admin@b.com", PASSWORD, make_cpf(100000002))
    admin = login(client, "admin@a.com")

    sched = client.post("/schedules", headers=admin, json={"name": "Comercial"}).json()

    cpfs = iter(range(200000001, 200000100))

    def mk(name, email, role="employee", manager_id=None):
        r = client.post("/users", headers=admin, json={
            "name": name, "email": email, "password": PASSWORD, "role": role, "cpf": make_cpf(next(cpfs)),
            "must_change_password": False,
            "manager_id": manager_id, "schedule_id": sched["id"],
        })
        assert r.status_code == 201, r.text
        return r.json()

    hr = mk("Rita RH", "hr@a.com", "hr")
    mgr = mk("Gil Gestor", "gestor@a.com", "manager")
    emp = mk("Ana Colab", "ana@a.com", "employee", mgr["id"])
    other = mk("Beto Sem Gestor", "beto@a.com", "employee")
    return {
        "admin": admin, "hr": login(client, "hr@a.com"), "mgr": login(client, "gestor@a.com"),
        "emp": login(client, "ana@a.com"), "other": login(client, "beto@a.com"),
        "adminB": login(client, "admin@b.com"),
        "ids": {"hr": hr["id"], "mgr": mgr["id"], "emp": emp["id"], "other": other["id"]},
        "sched": sched,
    }
