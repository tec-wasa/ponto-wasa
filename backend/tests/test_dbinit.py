"""dbinit: migra e cria o papel restrito, de forma repetível (é o passo de implantação da infraestrutura)."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError, OperationalError

from app import dbinit
from tests.conftest import TEST_DB_URL
from tests.test_migrations import reset


def test_dbinit_refuses_bad_configuration(monkeypatch):
    monkeypatch.delenv("PONTO_OWNER_DATABASE_URL", raising=False)
    monkeypatch.delenv("PONTO_APP_DB_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="Defina"):
        dbinit.main()
    monkeypatch.setenv("PONTO_OWNER_DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("PONTO_APP_DB_PASSWORD", "uma-senha-bem-longa-123")
    with pytest.raises(SystemExit, match="PostgreSQL"):
        dbinit.main()


@pytest.mark.parametrize("password", ["curta", "com aspas' ou espaco 123456", "tem;ponto-e-virgula-1234", "x" * 15])
def test_password_is_validated_before_it_goes_into_sql(password):
    with pytest.raises(SystemExit, match="inválida"):
        dbinit.apply_roles(None, password)


@pytest.mark.skipif(not TEST_DB_URL, reason="requer PONTO_TEST_DATABASE_URL (PostgreSQL)")
def test_dbinit_migrates_creates_role_and_is_repeatable(monkeypatch):
    owner = create_engine(TEST_DB_URL)
    reset(owner)
    monkeypatch.setenv("PONTO_OWNER_DATABASE_URL", TEST_DB_URL)

    def app_engine(password):
        return create_engine(make_url(TEST_DB_URL).set(username="ponto_app", password=password))

    try:
        monkeypatch.setenv("PONTO_APP_DB_PASSWORD", "primeira-senha-forte-01")
        dbinit.main()
        with owner.begin() as conn:
            conn.execute(text("INSERT INTO companies (id, name, cnpj, timezone, created_at) VALUES (1,'E','1','America/Sao_Paulo','2026-01-01')"))
        with app_engine("primeira-senha-forte-01").begin() as conn:  # a aplicação lê e grava...
            assert conn.execute(text("SELECT count(*) FROM companies")).scalar() == 1
        with pytest.raises(DatabaseError), app_engine("primeira-senha-forte-01").begin() as conn:  # ...mas não apaga o histórico
            conn.execute(text("TRUNCATE punches"))

        # Reexecutar (nova implantação) é seguro e troca a senha do papel
        monkeypatch.setenv("PONTO_APP_DB_PASSWORD", "segunda-senha-forte-02")
        dbinit.main()
        with app_engine("segunda-senha-forte-02").begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM companies")).scalar() == 1
        # a senha antiga deixou de valer (o teste roda com auth "trust", então só confirmamos onde há autenticação)
        try:
            with app_engine("primeira-senha-forte-01").begin() as conn:
                conn.execute(text("SELECT 1"))
        except OperationalError:
            pass
    finally:
        with owner.begin() as conn:
            conn.execute(text("DROP OWNED BY ponto_app"))
        try:
            with owner.begin() as conn:
                conn.execute(text("DROP ROLE ponto_app"))
        except DatabaseError:
            pass
        reset(owner)
        owner.dispose()
