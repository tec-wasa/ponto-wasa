"""As migrações Alembic criam o mesmo esquema do modelo, com os gatilhos de imutabilidade."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app import immutability
from app.db import Base
from tests.conftest import TEST_DB_URL

ROOT = Path(__file__).resolve().parents[1]
TABLES = {"companies", "users", "schedules", "nsr_counters", "punches", "arp_events", "adjustments", "closings", "audit_log", "hour_bank_entries", "absences"}


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def reset(engine):
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        for t in ("alembic_version",):
            conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
        if engine.dialect.name == "postgresql":
            conn.execute(text(immutability.PG_DROP_FUNCTION.replace("()", "() CASCADE")))


def seed_rows(conn):
    conn.execute(text("INSERT INTO companies (id, name, cnpj, timezone, created_at) VALUES (1, 'E', '1', 'America/Sao_Paulo', '2026-01-01')"))
    conn.execute(text("INSERT INTO users (id, company_id, name, email, cpf, password_hash, role, active, created_at) "
                      "VALUES (1, 1, 'U', 'u@x.com', '52998224725', 'h', 'employee', true, '2026-01-01')"))
    conn.execute(text("INSERT INTO punches (company_id, user_id, cpf, nsr, kind, occurred_at, recorded_at, tz_offset_min, collector, "
                      "offline, prev_hash, hash, created_at) VALUES (1, 1, '52998224725', 1, 'entrada', '2026-01-01 10:00', "
                      "'2026-01-01 10:00', -180, '02', false, '', 'h1', '2026-01-01')"))
    conn.execute(text("INSERT INTO arp_events (company_id, nsr, record_type, recorded_at, tz_offset_min, data) "
                      "VALUES (1, 2, '6', '2026-01-01 10:01', -180, '{\"event\": \"07\"}')"))
    conn.execute(text("INSERT INTO audit_log (company_id, action, entity, at) VALUES (1, 'login', 'user', '2026-01-01')"))
    conn.execute(text("INSERT INTO hour_bank_entries (company_id, user_id, entry_date, kind, minutes, reason, created_by, created_at) "
                      "VALUES (1, 1, '2026-01-02', 'credito', 30, 'teste', 1, '2026-01-02')"))


@pytest.fixture(params=["sqlite", "postgresql"])
def url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'mig.db'}"
    if not TEST_DB_URL:
        pytest.skip("requer PONTO_TEST_DATABASE_URL (PostgreSQL)")
    return TEST_DB_URL


def test_upgrade_matches_models_and_enforces_immutability(url):
    engine = create_engine(url)
    reset(engine)
    cfg = alembic_cfg(url)

    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(engine).get_table_names())
    command.check(cfg)  # falha se o modelo divergir das migrações (esquema sem migração)

    with engine.begin() as conn:
        seed_rows(conn)
    for sql in ("UPDATE punches SET kind = 'saida'", "DELETE FROM punches", "DELETE FROM audit_log",
                "UPDATE arp_events SET record_type = '5'", "DELETE FROM arp_events",
                "UPDATE hour_bank_entries SET minutes = 1", "DELETE FROM hour_bank_entries"):
        with pytest.raises(DatabaseError), engine.begin() as conn:
            conn.execute(text(sql))
    if engine.dialect.name == "postgresql":
        for table in ("punches", "arp_events", "audit_log", "hour_bank_entries"):
            with pytest.raises(DatabaseError), engine.begin() as conn:
                conn.execute(text(f"TRUNCATE {table}"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM punches")).scalar() == 1

    command.downgrade(cfg, "base")
    assert not (TABLES & set(inspect(engine).get_table_names()))
    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'forbid_mutation'")).scalar() == 0
    engine.dispose()


def test_upgrade_is_repeatable(url):
    engine = create_engine(url)
    reset(engine)
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # sem efeito, sem erro
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # ciclo completo
    assert TABLES <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "base")
    engine.dispose()
