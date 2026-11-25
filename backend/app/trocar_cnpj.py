"""Manutenção: corrige o CNPJ (ou CPF, para empregador pessoa física) da empresa e grava o registro tipo 2 do REP-P.

    python -m app.trocar_cnpj --cnpj 07.165.415/0001-64             # simulação (mostra o que muda)
    python -m app.trocar_cnpj --cnpj 07.165.415/0001-64 --aplicar   # grava

Pela tela o CNPJ não muda, porque ele identifica o estabelecimento em cada arquivo entregue à fiscalização. Use isto para
corrigir um CNPJ cadastrado errado (por exemplo, o de teste da criação da empresa). A troca fica no REP-P (tipo 2) e na
auditoria. Com várias empresas no banco, informe --empresa <id>.
"""
import argparse
import sys

from sqlalchemy import func, select

from .db import SessionLocal
from .models import Company, Punch
from .services import arp, audit


def digits(v: str) -> str:
    return "".join(c for c in v if c.isdigit())


def valid_cnpj(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    nums = [int(c) for c in d]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        check = sum(n * w for n, w in zip(nums[:size], weights, strict=True)) % 11
        if nums[size] != (0 if check < 2 else 11 - check):
            return False
    return True


def valid_cpf(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    nums = [int(c) for c in d]
    for size in (9, 10):
        if (sum(nums[i] * (size + 1 - i) for i in range(size)) * 10) % 11 % 10 != nums[size]:
            return False
    return True


def fmt(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cnpj", required=True, help="CNPJ (14 dígitos) ou CPF (11), com ou sem máscara")
    ap.add_argument("--empresa", type=int, help="id da empresa (obrigatório se houver mais de uma)")
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isto é só simulação)")
    args = ap.parse_args()

    new = digits(args.cnpj)
    if not (valid_cnpj(new) if len(new) == 14 else valid_cpf(new)):
        sys.exit(f"{args.cnpj} não é um CNPJ (nem CPF) válido.")
    with SessionLocal() as db:
        companies = db.execute(select(Company).order_by(Company.id)).scalars().all()
        if args.empresa:
            company = next((c for c in companies if c.id == args.empresa), None)
        elif len(companies) == 1:
            company = companies[0]
        else:
            sys.exit("Há mais de uma empresa: informe --empresa. " + "; ".join(f"#{c.id} {c.name} ({c.cnpj})" for c in companies))
        if company is None:
            sys.exit("Empresa não encontrada.")
        if digits(company.cnpj) == new:
            sys.exit(f"A empresa #{company.id} já está com o CNPJ {fmt(new)}. Nada a fazer.")
        other = next((c for c in companies if c.id != company.id and digits(c.cnpj) == new), None)
        if other:
            sys.exit(f"O CNPJ {fmt(new)} já pertence à empresa #{other.id} ({other.name}).")
        punches = db.execute(select(func.count()).select_from(Punch).where(Punch.company_id == company.id)).scalar_one()

        print(f"Empresa #{company.id}: {company.name}")
        print(f"  CNPJ atual: {company.cnpj}")
        print(f"  CNPJ novo:  {fmt(new)}")
        if punches:
            print(f"  ATENÇÃO: já há {punches} marcação(ões). Elas continuam valendo; o AFD passa a sair com o CNPJ novo e o registro "
                  "tipo 2 documenta a troca. Confirme com o jurídico se é correção de cadastro e não mudança de estabelecimento.")
        if not args.aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Repita com --aplicar para gravar.")
            return
        before = company.cnpj
        company.cnpj = fmt(new)
        db.flush()
        arp.record_employer(db, company, None)  # tipo 2: alteração da identificação do empregador
        audit.log(db, None, "update", "company", company.id, before={"cnpj": before}, after={"cnpj": company.cnpj}, ip="manutencao",
                  company_id=company.id)
        db.commit()
        print(f"\nAPLICADO: CNPJ da empresa #{company.id} agora é {company.cnpj} (registro tipo 2 gravado no REP-P).")


if __name__ == "__main__":
    main()
