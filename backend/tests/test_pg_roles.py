"""Papel de mínimo privilégio: a aplicação funciona, mas o banco a impede de mutar marcações e auditoria."""
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services.punching import register_punch, verify_chain
from tests.conftest import TEST_DB_URL
from tests.test_migrations import alembic_cfg, reset

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="requer PONTO_TEST_DATABASE_URL (PostgreSQL)")
SQL = (Path(__file__).resolve().parents[2] / "deploy" / "postgres-roles.sql").read_text(encoding="utf-8")


def test_app_role_can_work_but_cannot_mutate_immutable_tables():
    owner = create_engine(TEST_DB_URL)
    reset(owner)
    command.upgrade(alembic_cfg(TEST_DB_URL), "head")
    with owner.begin() as conn:
        conn.exec_driver_sql(SQL)
        conn.execute(text("ALTER ROLE ponto_app PASSWORD 'CHANGE_ME'"))  # papel é global no cluster: fixa a senha
        conn.execute(text("INSERT INTO companies (id, name, cnpj, timezone, created_at) VALUES (1,'E','1','America/Sao_Paulo','2026-01-01')"))
        conn.execute(text("INSERT INTO nsr_counters (company_id, last_nsr, last_hash) VALUES (1, 0, '')"))
        conn.execute(text("INSERT INTO users (id, company_id, name, email, cpf, password_hash, role, active, created_at) "
                          "VALUES (1,1,'U','u@x.com','52998224725','h','employee',true,'2026-01-01')"))

    app_url = make_url(TEST_DB_URL).set(username="ponto_app", password="CHANGE_ME")
    app = create_engine(app_url)
    Session = sessionmaker(bind=app, expire_on_commit=False)
    try:
        # A aplicação funciona normalmente com o papel restrito...
        with Session() as s:
            user = s.get(User, 1)
            for day in (1, 2, 3):  # um dia por batida: sem jornada só cabem 2 batidas por dia
                register_punch(s, user, kind=None, occurred_at=datetime(2026, 1, day, 10, 0))
            s.commit()
            assert verify_chain(s, 1)["ok"]

        # ausências são mutáveis (aprovação, cancelamento), mas nunca apagadas
        with app.begin() as conn:
            conn.execute(text("INSERT INTO absences (company_id, user_id, kind, start_date, end_date, reason, status, created_by, created_at) "
                              "VALUES (1, 1, 'abono', '2026-01-05', '2026-01-05', 'teste', 'pending', 1, '2026-01-05')"))
            conn.execute(text("UPDATE absences SET status = 'approved'"))

        # ...mas o banco nega, por privilégio, qualquer mutação das tabelas imutáveis,
        # e ela não consegue desativar os gatilhos.
        for sql in ("UPDATE punches SET kind = 'saida'", "DELETE FROM punches", "TRUNCATE punches",
                    "DELETE FROM audit_log", "TRUNCATE arp_events", "UPDATE arp_events SET record_type = '5'",
                    "DELETE FROM absences", "UPDATE hour_bank_entries SET minutes = 1", "DELETE FROM hour_bank_entries", "TRUNCATE hour_bank_entries",
                    "ALTER TABLE punches DISABLE TRIGGER punches_immutable",
                    "DROP TRIGGER punches_immutable ON punches"):
            with pytest.raises((ProgrammingError, DatabaseError)) as err, app.begin() as conn:
                conn.execute(text(sql))
            assert "permission denied" in str(err.value) or "must be owner" in str(err.value), sql
    finally:
        app.dispose()
        with owner.begin() as conn:
            conn.execute(text("DROP OWNED BY ponto_app"))
        try:  # o papel é global; se outro banco ainda depender dele, apenas o mantém
            with owner.begin() as conn:
                conn.execute(text("DROP ROLE ponto_app"))
        except DatabaseError:
            pass
        command.downgrade(alembic_cfg(TEST_DB_URL), "base")
        owner.dispose()
