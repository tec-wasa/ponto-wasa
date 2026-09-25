"""Confere NSR contínuo e cadeia de hashes de TODAS as empresas. Sai com código 1 se houver qualquer problema.

Uso: python -m app.integrity    (usa PONTO_DATABASE_URL)
Serve para validar uma restauração de backup e pode rodar como verificação periódica (cron).
"""
import json
import sys

from sqlalchemy import select

from .db import SessionLocal
from .models import Company
from .services.arp import verify_chain


def main() -> int:
    ok = True
    with SessionLocal() as db:
        for company in db.execute(select(Company).order_by(Company.id)).scalars():
            result = verify_chain(db, company.id)
            ok = ok and result["ok"]
            print(json.dumps({"company_id": company.id, "name": company.name, **result}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
