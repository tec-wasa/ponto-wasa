"""A demonstração (run-local.ps1 -Demo) precisa gerar dados consistentes: NSR contínuo, cadeia de hashes íntegra, logins que funcionam."""
import pytest
from sqlalchemy.orm import sessionmaker

from app import seed_demo
from app.config import settings
from app.models import Absence, Adjustment, Punch
from tests.conftest import login


@pytest.fixture()
def demo(engine, monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)
    monkeypatch.setattr(seed_demo, "init_schema", lambda: None)
    monkeypatch.setattr(seed_demo, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))
    assert seed_demo.main() == 0


def test_demo_creates_people_punches_and_pendings(demo, client, db):
    assert db.query(Punch).count() > 100
    assert db.query(Adjustment).filter_by(status="pending").count() == 1
    assert db.query(Absence).count() == 2
    admin = login(client, "admin@demo.com", seed_demo.PASSWORD)
    assert client.get("/punches-integrity", headers=admin).json()["ok"]  # NSR contínuo e hashes íntegros
    gil = login(client, "gil@demo.com", seed_demo.PASSWORD)
    team = client.get("/dashboard?bank=true", headers=gil).json()
    assert team["summary"]["total"] == 3 and team["summary"]["pending_adjustments"] == 1
    ana = login(client, "ana@demo.com", seed_demo.PASSWORD)
    assert client.get("/hour-bank", headers=ana).json()["enabled"] is True


def test_demo_refuses_a_database_that_already_has_data(demo, capsys):
    assert seed_demo.main() == 1
    assert "banco vazio" in capsys.readouterr().out
