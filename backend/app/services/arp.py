"""ARP — Armazenamento de Registro de Ponto (Portaria MTP 671/2021, Anexo IX).

Concentra o que é comum a todos os registros: NSR único por estabelecimento, formatação de data e
hora, cálculo do hash da marcação e os registros de empregador (tipo 2), empregado (tipo 5) e
eventos do REP-P (tipo 6). As marcações (tipo 7) são gravadas em `punching.register_punch`.
"""
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ArpEvent, Company, NsrCounter, Punch, User, utcnow

# --- Hipóteses de interpretação (a Portaria não especifica; validar na homologação) ------------
# H1. Hash da marcação = SHA-256 (hex minúsculo) da concatenação, sem separadores, dos campos como
#     aparecem no AFD: NSR(9) + "7" + DH marcação(24) + CPF(12) + DH gravação(24) + coletor(2) +
#     off-line(1) + hash do registro de marcação anterior ("" na primeira).
# H2. "Registro anterior" = a marcação (tipo 7) anterior do mesmo estabelecimento, pois só ela tem hash.
GENESIS = ""

EVENT_AVAILABLE = "07"  # disponibilidade de serviço (REP-P)
EVENT_UNAVAILABLE = "08"  # indisponibilidade de serviço (REP-P)


def digits_only(value: str | None) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def offset_minutes(tz: str, utc_naive: datetime) -> int:
    local = utc_naive.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz))
    return int(local.utcoffset().total_seconds() // 60)


def fmt_dh(utc_naive: datetime, offset_min: int) -> str:
    """Tipo DH da Portaria: AAAA-MM-ddThh:mm:00±ZZZZ (segundos sempre 00)."""
    local = utc_naive + timedelta(minutes=offset_min)
    sign = "-" if offset_min < 0 else "+"
    hh, mm = divmod(abs(offset_min), 60)
    return f"{local:%Y-%m-%dT%H:%M}:00{sign}{hh:02d}{mm:02d}"


def punch_hash(nsr: int, cpf: str, occurred_at: datetime, recorded_at: datetime, offset_min: int,
               collector: str, offline: bool, prev_hash: str) -> str:
    raw = (
        f"{nsr:09d}" "7" f"{fmt_dh(occurred_at, offset_min)}" f"{int(cpf):012d}"
        f"{fmt_dh(recorded_at, offset_min)}" f"{collector}" f"{1 if offline else 0}" f"{prev_hash}"
    )
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def lock_counter(db: Session, company_id: int) -> NsrCounter:
    """Trava a linha do contador: serializa a geração de NSR entre conexões concorrentes."""
    counter = db.execute(
        select(NsrCounter).where(NsrCounter.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if counter is None:
        counter = NsrCounter(company_id=company_id, last_nsr=0, last_hash=GENESIS)
        db.add(counter)
        db.flush()
    return counter


def _add_event(db: Session, company: Company, record_type: str, actor: User | None, data: dict) -> ArpEvent:
    counter = lock_counter(db, company.id)
    now = utcnow()
    counter.last_nsr += 1
    row = ArpEvent(
        company_id=company.id, nsr=counter.last_nsr, record_type=record_type, recorded_at=now,
        tz_offset_min=offset_minutes(company.timezone, now),
        actor_cpf=digits_only(actor.cpf) if actor else None, data=data,
    )
    db.add(row)
    db.flush()
    return row


def record_employer(db: Session, company: Company, actor: User | None) -> ArpEvent:
    """Tipo 2: inclusão ou alteração da identificação do empregador."""
    return _add_event(db, company, "2", actor, {
        "id": digits_only(company.cnpj), "caepf": digits_only(company.caepf), "cno": digits_only(company.cno),
        "name": company.name, "workplace": company.workplace or "",
    })


def record_employee(db: Session, company: Company, op: str, user: User, actor: User | None) -> ArpEvent:
    """Tipo 5: inclusão (I), alteração (A) ou exclusão (E) de empregado."""
    assert op in ("I", "A", "E")
    return _add_event(db, company, "5", actor, {"op": op, "cpf": digits_only(user.cpf), "name": user.name})


def record_service_event(db: Session, company: Company, code: str) -> ArpEvent:
    """Tipo 6: eventos sensíveis do REP-P (07 disponível, 08 indisponível)."""
    return _add_event(db, company, "6", None, {"event": code})


def record_service_event_all(db: Session, code: str) -> int:
    n = 0
    for company in db.execute(select(Company)).scalars():
        record_service_event(db, company, code)
        n += 1
    db.commit()
    return n


def verify_chain(db: Session, company_id: int) -> dict:
    """Confere o NSR (contínuo, todos os tipos) e a cadeia de hashes das marcações do estabelecimento."""
    punches = db.execute(select(Punch).where(Punch.company_id == company_id)).scalars().all()
    events = db.execute(select(ArpEvent).where(ArpEvent.company_id == company_id)).scalars().all()
    problems: list[str] = []

    nsrs = sorted([p.nsr for p in punches] + [e.nsr for e in events])
    for expected, got in enumerate(nsrs, start=1):
        if got != expected:
            problems.append(f"NSR {expected} ausente (encontrado {got})")
            break  # uma lacuna desloca todo o resto; um aviso basta
    if len(nsrs) != len(set(nsrs)):
        problems.append("NSR repetido")

    prev = GENESIS
    for p in sorted(punches, key=lambda x: x.nsr):
        if p.prev_hash != prev:
            problems.append(f"NSR {p.nsr}: hash anterior não confere")
        expected_hash = punch_hash(p.nsr, p.cpf, p.occurred_at, p.recorded_at, p.tz_offset_min,
                                   p.collector, p.offline, p.prev_hash)
        if expected_hash != p.hash:
            problems.append(f"NSR {p.nsr}: hash não confere")
        prev = p.hash

    counter = db.get(NsrCounter, company_id)
    if counter and (counter.last_nsr != len(nsrs) or counter.last_hash != prev):
        problems.append("Contador de NSR diverge dos registros")
    return {"ok": not problems, "checked": len(nsrs), "problems": problems}
