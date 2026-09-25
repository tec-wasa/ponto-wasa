"""Cria uma empresa e o primeiro administrador.

Uso: python -m app.seed --name "Empresa" --cnpj 00.000.000/0001-00 --email admin@x.com --password '...'
"""
import argparse

from .db import SessionLocal, init_schema
from .models import Company, NsrCounter, User
from .security import hash_password
from .services import arp, kiosk
from .services.cpf import digits, is_valid_cpf


def create_company(db, name: str, cnpj: str, email: str, password: str, cpf: str, tz: str = "America/Sao_Paulo") -> User:
    if not is_valid_cpf(cpf):
        raise ValueError("CPF do administrador inválido")
    company = Company(name=name, cnpj=cnpj, timezone=tz)
    db.add(company)
    db.flush()
    db.add(NsrCounter(company_id=company.id, last_nsr=0, last_hash=""))
    admin = User(
        company_id=company.id, name="Administrador", email=email.lower(), cpf=digits(cpf),
        password_hash=hash_password(password), role="admin",
    )
    db.add(admin)
    kiosk.assign_code(db, admin)
    db.flush()
    arp.record_employer(db, company, admin)  # ARP tipo 2
    arp.record_employee(db, company, "I", admin, admin)  # ARP tipo 5
    db.commit()
    return admin


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--cnpj", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--cpf", required=True, help="CPF do administrador (identifica o responsável nos registros do ARP)")
    a = p.parse_args()
    init_schema()
    with SessionLocal() as db:
        u = create_company(db, a.name, a.cnpj, a.email, a.password, a.cpf)
    print(f"Empresa criada; administrador: {u.email}")
