"""Manutenção: apaga do banco TODAS as pessoas (e o histórico delas) exceto as indicadas. Só para ambiente de ensaio.

    python -m app.limpar_pessoas --manter Gleiciane --manter Stefane            # simulação (não grava nada)
    python -m app.limpar_pessoas --manter Gleiciane --manter Stefane --aplicar  # apaga de verdade

Roda como DONO do banco (PONTO_OWNER_DATABASE_URL, ou PONTO_DATABASE_URL em SQLite), porque o papel da aplicação não pode apagar
marcações. Numa única transação: desliga os gatilhos de imutabilidade, apaga o histórico das pessoas removidas, renumera o NSR dos
registros que sobram, refaz a cadeia de hashes, ajusta o contador e religa os gatilhos. A trilha de auditoria (audit_log) é mantida e
recebe um registro desta limpeza. FAÇA BACKUP ANTES: não há como desfazer.
"""
import argparse
import os
import sys
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.orm import Session

from . import immutability
from .models import (Absence, Adjustment, ArpEvent, AuditLog, Closing, HourBankEntry, Kiosk, KioskTicket, NsrCounter, Punch, PunchPhoto,
                     User)
from .services.arp import GENESIS, punch_hash


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _set_triggers(conn, enabled: bool) -> None:
    dialect = conn.dialect.name
    for table in immutability.IMMUTABLE_TABLES:
        if dialect == "postgresql":
            conn.execute(text(f"ALTER TABLE {table} {'ENABLE' if enabled else 'DISABLE'} TRIGGER {table}_immutable"))
        elif dialect == "sqlite":
            stmts = immutability.create_statements(table, "sqlite") if enabled else immutability.drop_statements(table, "sqlite")
            for s in stmts:
                conn.execute(text(s))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manter", action="append", required=True, help="parte do nome da pessoa a manter (repita para várias)")
    ap.add_argument("--aplicar", action="store_true", help="grava as alterações (sem isto é só simulação)")
    ap.add_argument("--sem-admin", action="store_true", help="permite terminar sem nenhum administrador/RH ativo entre os mantidos")
    args = ap.parse_args()

    url = os.environ.get("PONTO_OWNER_DATABASE_URL") or os.environ.get("PONTO_DATABASE_URL")
    if not url:
        sys.exit("Defina PONTO_OWNER_DATABASE_URL (dono do banco)")
    engine = create_engine(url)

    with engine.connect() as conn:
        tx = conn.begin()
        db = Session(bind=conn)
        users = db.execute(select(User).order_by(User.id)).scalars().all()
        keep, drop = [], []
        for u in users:
            (keep if any(_norm(k) in _norm(u.name) for k in args.manter) else drop).append(u)
        for k in args.manter:
            hits = [u for u in keep if _norm(k) in _norm(u.name)]
            if len(hits) != 1:
                sys.exit(f"'{k}' casou com {len(hits)} pessoas ({', '.join(u.name for u in hits) or 'nenhuma'}); seja mais específico.")
        print("MANTER:")
        for u in keep:
            print(f"  #{u.id} {u.name} <{u.email}> perfil={u.role} ativo={u.active}")
        print(f"APAGAR ({len(drop)}):")
        for u in drop:
            print(f"  #{u.id} {u.name} <{u.email}> perfil={u.role}")
        admins = [u for u in keep if u.role in ("admin", "hr") and u.active]
        if not admins and not args.sem_admin:
            sys.exit("\nNenhuma das pessoas mantidas é administrador/RH ativo: ninguém conseguiria entrar para gerir o sistema.\n"
                     "Mantenha também o administrador (--manter <nome>) ou, se for de propósito, use --sem-admin.")
        if not drop:
            sys.exit("Nada a apagar.")

        keep_ids = [u.id for u in keep]
        drop_ids = [u.id for u in drop]
        owner = next((u for u in keep if u.role == "admin"), admins[0] if admins else keep[0])
        photo_rows = db.execute(select(PunchPhoto.storage_key).where(PunchPhoto.user_id.in_(drop_ids))).scalars().all()

        _set_triggers(conn, False)
        try:
            dropped_punches = db.execute(select(Punch.id).where(Punch.user_id.in_(drop_ids))).scalars().all()
            # referências das pessoas mantidas a quem vai sair: anuláveis viram NULL; obrigatórias passam para o responsável mantido
            conn.execute(update(User).where(User.manager_id.in_(drop_ids)).values(manager_id=None))
            conn.execute(update(Closing).where(Closing.closed_by.in_(drop_ids)).values(closed_by=None))
            conn.execute(update(Kiosk).where(Kiosk.created_by.in_(drop_ids)).values(created_by=None))
            conn.execute(update(Adjustment).where(Adjustment.decided_by.in_(drop_ids)).values(decided_by=None))
            conn.execute(update(Absence).where(Absence.decided_by.in_(drop_ids)).values(decided_by=None))
            conn.execute(update(Absence).where(Absence.created_by.in_(drop_ids)).values(created_by=owner.id))
            conn.execute(update(HourBankEntry).where(HourBankEntry.created_by.in_(drop_ids)).values(created_by=owner.id))
            # histórico das pessoas removidas (filhos antes dos pais)
            conn.execute(delete(PunchPhoto).where(PunchPhoto.user_id.in_(drop_ids)))
            conn.execute(delete(Adjustment).where((Adjustment.user_id.in_(drop_ids)) | (Adjustment.target_punch_id.in_(dropped_punches))))
            conn.execute(delete(Absence).where(Absence.user_id.in_(drop_ids)))
            conn.execute(delete(HourBankEntry).where(HourBankEntry.user_id.in_(drop_ids)))
            conn.execute(delete(KioskTicket).where(KioskTicket.user_id.in_(drop_ids)))
            conn.execute(delete(Punch).where(Punch.user_id.in_(drop_ids)))
            conn.execute(delete(User).where(User.id.in_(drop_ids)))

            # renumera o NSR (contínuo entre marcações e eventos) e refaz a cadeia de hashes
            company_ids = db.execute(select(User.company_id).distinct()).scalars().all() or []
            for company_id in company_ids:
                punches = db.execute(select(Punch).where(Punch.company_id == company_id).order_by(Punch.nsr)).scalars().all()
                events = db.execute(select(ArpEvent).where(ArpEvent.company_id == company_id).order_by(ArpEvent.nsr)).scalars().all()
                seq = sorted([("p", p.nsr, p) for p in punches] + [("e", e.nsr, e) for e in events], key=lambda t: t[1])
                prev = GENESIS
                for new_nsr, (kind, _old, row) in enumerate(seq, start=1):
                    if kind == "e":
                        conn.execute(update(ArpEvent).where(ArpEvent.id == row.id).values(nsr=new_nsr))
                        continue
                    digest = punch_hash(new_nsr, row.cpf, row.occurred_at, row.recorded_at, row.tz_offset_min, row.collector,
                                        row.offline, prev)
                    conn.execute(update(Punch).where(Punch.id == row.id).values(nsr=new_nsr, prev_hash=prev, hash=digest))
                    prev = digest
                conn.execute(update(NsrCounter).where(NsrCounter.company_id == company_id).values(last_nsr=len(seq), last_hash=prev))
                conn.execute(AuditLog.__table__.insert().values(
                    company_id=company_id, actor_id=None, action="cleanup", entity="users", entity_id=None,
                    before={"removidos": [{"id": u.id, "name": u.name} for u in drop]},
                    after={"mantidos": [u.name for u in keep], "nsr_renumerado": len(seq)}, ip="manutencao",
                    at=datetime.now(timezone.utc).replace(tzinfo=None)))
        finally:
            _set_triggers(conn, True)

        if args.aplicar:
            tx.commit()
            photo_dir = os.environ.get("PONTO_PHOTO_DIR")
            removed_files = 0
            if photo_dir:
                for key in photo_rows:
                    try:
                        os.remove(os.path.join(photo_dir, key))
                        removed_files += 1
                    except OSError:
                        pass
            print(f"\nAPLICADO: {len(drop)} pessoa(s) e o histórico delas apagados; NSR renumerado; {removed_files} foto(s) removida(s).")
            print("Confira com: python -m app.integrity")
        else:
            tx.rollback()
            print("\nSIMULAÇÃO: nada foi gravado. Repita com --aplicar para apagar de verdade (faça backup antes).")


if __name__ == "__main__":
    main()
