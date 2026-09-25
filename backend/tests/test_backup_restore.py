"""Backup e restauração de ponta a ponta: o histórico restaurado mantém NSR, cadeia de hashes e imutabilidade."""
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from app import dbinit
from app.models import User
from app.security import hash_password
from app.seed import create_company
from app.services.arp import verify_chain
from app.services.punching import register_punch
from tests.conftest import TEST_DB_URL, make_cpf

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BACKUP_SH, RESTORE_SH = ROOT / "deploy" / "backup" / "backup.sh", ROOT / "deploy" / "backup" / "restore.sh"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="requer PONTO_TEST_DATABASE_URL (PostgreSQL)")

SRC, RESTORED = "ponto_bk_src", "ponto_bk_restored"


def _tools_available() -> bool:
    return all(shutil.which(t) for t in ("bash", "pg_dump", "pg_restore", "psql", "createdb", "dropdb", "sha256sum"))


@pytest.fixture()
def env():
    if not _tools_available():
        if os.environ.get("REQUIRE_BACKUP_TESTS"):
            pytest.fail("ferramentas do PostgreSQL/bash ausentes e REQUIRE_BACKUP_TESTS está ligado")
        pytest.skip("pg_dump/pg_restore/psql/bash não estão no PATH")
    u = make_url(TEST_DB_URL)
    e = {**os.environ, "PGHOST": u.host or "127.0.0.1", "PGPORT": str(u.port or 5432), "PGUSER": u.username or "postgres"}
    if u.password:
        e["PGPASSWORD"] = u.password
    return e


@pytest.fixture()
def databases(env):
    u = make_url(TEST_DB_URL)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")

    def drop_all_dbs():
        with admin.connect() as conn:
            for name in (SRC, RESTORED):
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))

    drop_all_dbs()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{SRC}"'))
    yield u, admin
    drop_all_dbs()
    with admin.connect() as conn:
        try:
            conn.execute(text("DROP ROLE IF EXISTS ponto_app"))
        except DatabaseError:
            pass  # outro banco do cluster ainda usa o papel
    admin.dispose()


def run(cmd, env, **kw):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def populate(src_url) -> int:
    """Empresa, usuários e marcações reais (com NSR e hashes) no banco de origem."""
    engine = create_engine(src_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        admin = create_company(s, "Empresa Backup", "44.444.444/0001-44", "admin@bk.com", "senha-forte-123", make_cpf(800000001))
        users = []
        for i in range(3):
            u = User(company_id=admin.company_id, name=f"Pessoa {i}", email=f"p{i}@bk.com", cpf=make_cpf(800000010 + i),
                     password_hash=hash_password("senha-forte-123"))
            s.add(u)
            users.append(u)
        s.commit()
        base = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
        for n in range(4):
            for u in users:
                register_punch(s, u, kind=None, occurred_at=base + timedelta(days=n // 2, minutes=(n % 2) * 60),
                              enforce_sequence=True)  # sem jornada = 2 batidas por dia
        s.commit()
        checked = verify_chain(s, admin.company_id)
    engine.dispose()
    assert checked["ok"]
    return checked["checked"]


def test_backup_restore_preserves_the_immutable_history(env, databases, tmp_path, monkeypatch):
    u, admin = databases
    src_url = u.set(database=SRC).render_as_string(hide_password=False)
    monkeypatch.setenv("PONTO_OWNER_DATABASE_URL", src_url)
    monkeypatch.setenv("PONTO_APP_DB_PASSWORD", "senha-do-papel-app-0001")
    dbinit.main()
    total = populate(src_url)  # 2 (empresa e admin) + 3 usuários... + 12 marcações

    backups = tmp_path / "backups"
    benv = {**env, "PGDATABASE": SRC, "BACKUP_DIR": str(backups), "BACKUP_ONCE": "true", "BACKUP_KEEP": "3"}

    # ---- retenção: 5 dumps antigos + 1 novo, mantendo só os 3 mais recentes
    backups.mkdir()
    for day in range(1, 6):
        (backups / f"ponto-2020010{day}T000000Z.dump").write_bytes(b"antigo")
        (backups / f"ponto-2020010{day}T000000Z.dump.sha256").write_text("x")
    done = run(["bash", str(BACKUP_SH)], benv)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1])["msg"].startswith("backup ok: ponto-")
    dumps = sorted(p.name for p in backups.glob("ponto-*.dump"))
    assert len(dumps) == 3 and dumps[:2] == ["ponto-20200104T000000Z.dump", "ponto-20200105T000000Z.dump"]
    assert not (backups / "ponto-20200101T000000Z.dump.sha256").exists()  # o checksum vai junto com o dump
    assert (backups / "last_success").read_text().strip().isdigit()
    dump = backups / dumps[-1]
    assert (backups / (dump.name + ".sha256")).exists() and not list(backups.glob(".*.partial"))

    # o dump carrega os gatilhos de imutabilidade
    listing = run(["pg_restore", "--list", str(dump)], env).stdout
    assert "punches_immutable" in listing and "arp_events_no_truncate" in listing and "forbid_mutation" in listing

    # ---- restauração num banco novo
    rdb = run(["bash", str(RESTORE_SH), str(dump), RESTORED], env)
    assert rdb.returncode == 0, rdb.stdout + rdb.stderr
    assert "checksum ok" in rdb.stdout

    restored_url = u.set(database=RESTORED).render_as_string(hide_password=False)
    restored = create_engine(restored_url)
    with sessionmaker(bind=restored)() as s:
        result = verify_chain(s, 1)
    assert result == {"ok": True, "checked": total, "problems": []}  # mesmo NSR, mesmos hashes

    # a CLI de integridade (usada após restaurar e em verificações periódicas) confirma e sai com 0
    cli = run([sys.executable, "-m", "app.integrity"], {**env, "PONTO_DATABASE_URL": restored_url}, cwd=BACKEND)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout.strip().splitlines()[-1])["ok"] is True

    # passo do roteiro de restauração: reaplicar o papel restrito (o dump não leva privilégios) sobre o banco restaurado
    monkeypatch.setenv("PONTO_OWNER_DATABASE_URL", restored_url)
    monkeypatch.setenv("PONTO_APP_DB_PASSWORD", "senha-do-papel-app-0002")
    dbinit.main()  # migrações já aplicadas no dump: não faz nada no esquema; só recria os privilégios
    app_restored = create_engine(u.set(database=RESTORED, username="ponto_app", password="senha-do-papel-app-0002"))
    with app_restored.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM punches")).scalar() == 12  # a aplicação lê o histórico restaurado
    with app_restored.begin() as conn, pytest.raises(DatabaseError):
        conn.execute(text("DELETE FROM punches"))  # e continua sem poder apagá-lo
    app_restored.dispose()

    # o banco restaurado continua imutável
    with restored.begin() as conn, pytest.raises(DatabaseError):
        conn.execute(text("UPDATE punches SET collector = '01'"))

    # ---- e detecta adulteração feita por quem tem acesso direto ao banco
    with restored.begin() as conn:
        conn.execute(text("ALTER TABLE punches DISABLE TRIGGER punches_immutable"))
        conn.execute(text("UPDATE punches SET collector = '01' WHERE nsr = (SELECT min(nsr) FROM punches)"))
    bad = run([sys.executable, "-m", "app.integrity"], {**env, "PONTO_DATABASE_URL": restored_url}, cwd=BACKEND)
    assert bad.returncode == 1 and '"ok": false' in bad.stdout
    restored.dispose()

    # ---- recusas seguras do restore.sh
    again = run(["bash", str(RESTORE_SH), str(dump), RESTORED], env)
    assert again.returncode == 4 and "já existe" in again.stderr  # nunca sobrescreve um banco existente

    corrupt = tmp_path / "corrupto.dump"
    corrupt.write_bytes(dump.read_bytes()[:-20] + b"X" * 20)
    shutil.copy(backups / (dump.name + ".sha256"), tmp_path / "corrupto.dump.sha256")
    (tmp_path / "corrupto.dump.sha256").write_text((backups / (dump.name + ".sha256")).read_text().replace(dump.name, "corrupto.dump"))
    broken = run(["bash", str(RESTORE_SH), str(corrupt), "ponto_bk_never"], env)
    assert broken.returncode == 3 and "checksum" in broken.stderr
    exists = run(["psql", "-d", "postgres", "-Atc", "SELECT 1 FROM pg_database WHERE datname='ponto_bk_never'"], env)
    assert exists.stdout.strip() == ""  # nenhum banco foi criado a partir do arquivo corrompido

    assert run(["bash", str(RESTORE_SH)], env).returncode == 2  # uso incorreto
