"""Inicialização do banco em PostgreSQL: migra o esquema e cria/atualiza o papel restrito da aplicação.

Roda como o DONO do banco (uma vez por implantação, antes de a aplicação subir). A aplicação em si
conecta depois com o papel `ponto_app`, que não pode alterar nem apagar marcações e auditoria.

Variáveis de ambiente:
  PONTO_OWNER_DATABASE_URL  URL do dono do banco (ex.: postgresql+psycopg://ponto_owner:senha@db/ponto)
  PONTO_APP_DB_PASSWORD     senha do papel ponto_app (mínimo 16 caracteres: letras, números, '-', '_' ou '.')
"""
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]  # .../backend
ROLES_SQL = ROOT.parent / "deploy" / "postgres-roles.sql"
PASSWORD_RE = re.compile(r"^[A-Za-z0-9_.\-]{16,}$")  # sem aspas nem barras: vai dentro de SQL literal


def apply_roles(engine, password: str) -> None:
    if not PASSWORD_RE.match(password):
        raise SystemExit("PONTO_APP_DB_PASSWORD inválida: use ao menos 16 caracteres entre letras, números, '-', '_' e '.'")
    sql = ROLES_SQL.read_text(encoding="utf-8").replace("CHANGE_ME", password)
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
        conn.execute(text(f"ALTER ROLE ponto_app PASSWORD '{password}'"))  # mantém a senha em dia em reexecuções


def main() -> None:
    owner_url = os.environ.get("PONTO_OWNER_DATABASE_URL")
    password = os.environ.get("PONTO_APP_DB_PASSWORD")
    if not owner_url or not password:
        raise SystemExit("Defina PONTO_OWNER_DATABASE_URL e PONTO_APP_DB_PASSWORD")
    if not owner_url.startswith("postgresql"):
        raise SystemExit("dbinit é só para PostgreSQL (em SQLite/dev o esquema é criado automaticamente)")

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", owner_url)
    command.upgrade(cfg, "head")
    print("migrações aplicadas", flush=True)

    engine = create_engine(owner_url)
    try:
        apply_roles(engine, password)
    finally:
        engine.dispose()
    print("papel ponto_app configurado", flush=True)


if __name__ == "__main__":
    sys.exit(main())
