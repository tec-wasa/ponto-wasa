"""SQL dos gatilhos que tornam `punches` e `audit_log` append-only no banco.

Usado pelos eventos do modelo (create_all) e pelas migrações Alembic, para que as duas
vias criem exatamente o mesmo esquema.
"""

IMMUTABLE_TABLES = ("punches", "arp_events", "audit_log", "hour_bank_entries")

PG_FUNCTION = (
    "CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'registro imutavel'; END; $$ LANGUAGE plpgsql"
)
PG_DROP_FUNCTION = "DROP FUNCTION IF EXISTS forbid_mutation()"


def create_statements(table: str, dialect: str) -> list[str]:
    if dialect == "sqlite":
        return [
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'registro imutavel'); END",
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'registro imutavel'); END",
        ]
    if dialect == "postgresql":
        return [
            PG_FUNCTION,
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        ]
    return []


def drop_statements(table: str, dialect: str) -> list[str]:
    if dialect == "sqlite":
        return [f"DROP TRIGGER IF EXISTS {table}_no_update", f"DROP TRIGGER IF EXISTS {table}_no_delete"]
    if dialect == "postgresql":
        return [
            f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}",
            f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}",
        ]
    return []
