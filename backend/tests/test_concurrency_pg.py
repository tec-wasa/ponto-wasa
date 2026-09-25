"""NSR sem lacunas sob concorrência. Só faz sentido em PostgreSQL (SELECT ... FOR UPDATE)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import ArpEvent, Company, Punch, User
from app.security import hash_password
from app.seed import create_company
from app.services import arp
from app.services.punching import register_punch, verify_chain
from tests.conftest import TEST_DB_URL, make_cpf

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="requer PONTO_TEST_DATABASE_URL (PostgreSQL)")

USERS, PUNCHES_EACH = 8, 10


def test_nsr_is_gapless_and_chain_intact_under_concurrency(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        admin = create_company(s, "Empresa C", "33.333.333/0001-33", "admin@c.com", "senha-forte-123", make_cpf(700000001))
        company_id = admin.company_id
        for i in range(USERS):
            s.add(User(company_id=company_id, name=f"U{i}", email=f"u{i}@c.com", cpf=make_cpf(700000010 + i),
                       password_hash=hash_password("senha-forte-123")))
        s.commit()
        user_ids = [u.id for u in s.execute(select(User).where(User.email.like("u%@c.com"))).scalars()]

    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=12)

    def worker(uid: int):
        for n in range(PUNCHES_EACH):
            with Session() as s:  # sessão própria por marcação: contenção real no banco
                user = s.get(User, uid)
                register_punch(s, user, kind=None, occurred_at=base + timedelta(days=n // 2, minutes=n % 2),
                               enforce_sequence=True)  # sem jornada = 2 batidas por dia
                if n % 5 == 0:  # eventos de outros tipos disputam a mesma sequência de NSR
                    arp.record_service_event(s, s.get(Company, company_id), arp.EVENT_AVAILABLE)
                s.commit()

    with ThreadPoolExecutor(max_workers=USERS) as pool:
        list(pool.map(worker, user_ids))

    with Session() as s:
        nsrs = sorted(
            list(s.execute(select(Punch.nsr).where(Punch.company_id == company_id)).scalars())
            + list(s.execute(select(ArpEvent.nsr).where(ArpEvent.company_id == company_id)).scalars())
        )
        assert nsrs == list(range(1, len(nsrs) + 1))  # sem lacunas nem repetição, entre todos os tipos
        # empresa e admin (2) + marcações (80) + 2 eventos de serviço por trabalhador (16); nada se perdeu
        assert len(nsrs) == 2 + USERS * PUNCHES_EACH + USERS * 2
        result = verify_chain(s, company_id)
        assert result["ok"], result["problems"]
        assert result["checked"] == len(nsrs)
