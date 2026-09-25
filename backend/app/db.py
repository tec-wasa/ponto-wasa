from sqlalchemy import Boolean, Integer, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def sync_sqlite_columns(eng) -> list[str]:
    """Só para o SQLite de desenvolvimento: `create_all` não altera tabelas que já existem, então um banco criado por uma
    versão anterior ficaria sem as colunas novas. Acrescenta as que faltam, preservando os dados. Devolve `tabela.coluna`.
    (Em PostgreSQL/produção isso é papel do Alembic, nunca desta função.)"""
    added: list[str] = []
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(eng.dialect)}'
                if not col.nullable:  # SQLite exige um DEFAULT para acrescentar coluna NOT NULL
                    ddl += " DEFAULT " + ("0" if isinstance(col.type, (Boolean, Integer)) else "''")
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added


def init_schema() -> None:
    """Cria as tabelas só quando configurado (SQLite em dev); nos demais casos, vale o Alembic."""
    if settings.create_tables:
        Base.metadata.create_all(engine)
        if engine.dialect.name == "sqlite":
            sync_sqlite_columns(engine)  # banco local de uma versão anterior: acrescenta colunas novas sem apagar nada


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
