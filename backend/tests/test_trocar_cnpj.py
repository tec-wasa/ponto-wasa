"""Comando de manutenção que corrige o CNPJ da empresa (com registro tipo 2 no REP-P)."""
import sys

import pytest
from sqlalchemy import select

from app import trocar_cnpj
from app.models import ArpEvent, AuditLog, Company


def test_cnpj_validation():
    assert trocar_cnpj.valid_cnpj("07165415000164")
    assert not trocar_cnpj.valid_cnpj("07165415000165")
    assert not trocar_cnpj.valid_cnpj("11111111111111")


def test_changes_cnpj_and_records_type2(world, db, engine, monkeypatch, capsys):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(trocar_cnpj, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    a = db.execute(select(Company).where(Company.name == "Empresa A")).scalar_one()
    monkeypatch.setattr(sys, "argv", ["x", "--cnpj", "07.165.415/0001-64", "--empresa", str(a.id)])
    trocar_cnpj.main()
    assert "SIMULAÇÃO" in capsys.readouterr().out
    db.expire_all()
    assert db.get(Company, a.id).cnpj == "11.111.111/0001-11"
    monkeypatch.setattr(sys, "argv", ["x", "--cnpj", "07.165.415/0001-64", "--empresa", str(a.id), "--aplicar"])
    trocar_cnpj.main()
    db.expire_all()
    assert db.get(Company, a.id).cnpj == "07.165.415/0001-64"
    ev = db.execute(select(ArpEvent).where(ArpEvent.company_id == a.id, ArpEvent.record_type == "2").order_by(ArpEvent.nsr.desc())).scalars().first()
    assert ev.data["id"] == "07165415000164"
    assert db.execute(select(AuditLog).where(AuditLog.company_id == a.id, AuditLog.ip == "manutencao")).scalars().first()
    monkeypatch.setattr(sys, "argv", ["x", "--cnpj", "07165415000165", "--empresa", str(a.id)])
    with pytest.raises(SystemExit):
        trocar_cnpj.main()
