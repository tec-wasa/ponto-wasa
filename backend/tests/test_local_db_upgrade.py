"""O banco local (SQLite de teste) criado por uma versão anterior deve continuar valendo depois de uma atualização."""
from sqlalchemy import create_engine, inspect, text

from app.db import Base, sync_sqlite_columns


def test_new_columns_are_added_without_losing_data(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO companies (name, cnpj, timezone, bank_expiry_months, photo_enabled, kiosk_pin_required, created_at) VALUES ('Antiga', '1', 'America/Sao_Paulo', 6, 1, 0, '2026-01-01')"))
        conn.execute(text("ALTER TABLE companies DROP COLUMN photo_enabled"))   # simula a versão anterior (NOT NULL)
        conn.execute(text("ALTER TABLE users DROP COLUMN photo_consent_at"))     # e uma coluna anulável
    assert "photo_enabled" not in {c["name"] for c in inspect(eng).get_columns("companies")}

    added = sync_sqlite_columns(eng)
    assert {"companies.photo_enabled", "users.photo_consent_at"} <= set(added)
    with eng.connect() as conn:
        row = conn.execute(text("SELECT name, photo_enabled FROM companies")).one()
    assert tuple(row) == ("Antiga", 0)  # o dado antigo ficou; a coluna nova entra com o padrão (0)
    assert sync_sqlite_columns(eng) == []  # idempotente
