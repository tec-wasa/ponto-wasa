"""Dados de demonstração para testar o app: empresa, pessoas com perfis diferentes e cerca de três semanas de marcações.

Uso (banco VAZIO; só para testes, nunca em produção):  python -m app.seed_demo
Todos entram com a senha `senha-forte-123`. Os dias são relativos a hoje, então a demonstração sempre parece recente.
"""
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .db import SessionLocal, init_schema
from .models import Absence, Adjustment, Company, Schedule, User
from .security import hash_password
from .seed import create_company
from .services import arp, kiosk
from .services.punching import register_punch

PASSWORD = "senha-forte-123"
TZ = ZoneInfo("America/Sao_Paulo")

PEOPLE = [  # nome, e-mail, cpf, perfil, cargo
    ("Rita RH", "rita@demo.com", "39053344705", "hr", "Analista de RH"),
    ("Gil Gestor", "gil@demo.com", "16899535009", "manager", "Coordenador"),
    ("Ana Souza", "ana@demo.com", "45317828791", "employee", "Analista Contábil"),
    ("Beto Lima", "beto@demo.com", "11144477735", "employee", "Auxiliar"),
    ("Carla Dias", "carla@demo.com", "12345678909", "employee", "Assistente"),
]


def _utc(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _workdays(today: date, count: int) -> list[date]:
    days, d = [], today - timedelta(days=1)
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def main() -> int:
    init_schema()
    with SessionLocal() as db:
        if db.query(Company).count():
            print("O banco já tem empresa; a demonstração só roda em banco vazio (use -Reset).")
            return 1
        admin = create_company(db, "Empresa Demo Ltda", "12.345.678/0001-90", "admin@demo.com", PASSWORD, "529.982.247-25")
        company = db.get(Company, admin.company_id)
        sched = Schedule(company_id=company.id, name="Comercial 8h")
        db.add(sched)
        db.flush()

        today = datetime.now(TZ).date()
        bank_start = today - timedelta(days=30)
        users: dict[str, User] = {}
        for name, email, cpf, role, title in PEOPLE:
            manager = users["gil@demo.com"].id if role == "employee" else None
            u = User(company_id=company.id, name=name, email=email, cpf=cpf, role=role, manager_id=manager, schedule_id=sched.id,
                     password_hash=hash_password(PASSWORD), admitted_at=today - timedelta(days=200), job_title=title,
                     hour_bank_enabled=email in ("ana@demo.com", "carla@demo.com"), hour_bank_start=bank_start
                     if email in ("ana@demo.com", "carla@demo.com") else None)
            db.add(u)
            kiosk.assign_code(db, u)
            db.flush()
            arp.record_employee(db, company, "I", u, admin)
            users[email] = u
        db.commit()

        def day(u: User, d: date, marks: list[tuple[str, str]]):
            now = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
            for hhmm, kind in marks:
                when = _utc(d, hhmm)
                if when <= now:  # nunca cria marcação no futuro (rodando de madrugada, o "hoje" ainda não tem batidas)
                    register_punch(db, u, kind=kind, occurred_at=when, enforce_sequence=False)

        def full(start: str, end: str, lunch=("12:00", "13:00")):
            return [(start, "entrada"), (lunch[0], "inicio_intervalo"), (lunch[1], "fim_intervalo"), (end, "saida")]

        days = _workdays(today, 15)
        for i, d in enumerate(days):
            day(users["beto@demo.com"], d, full("07:55", "17:00"))                            # pontual
            if i % 5 != 3:                                                                     # Ana: 1 falta por semana
                day(users["ana@demo.com"], d, full("08:00", "18:00" if i % 4 == 0 else "17:05"))  # extras de vez em quando
            if i % 6 == 2:
                day(users["carla@demo.com"], d, full("08:10", "16:30"))                         # sai mais cedo
            else:
                day(users["carla@demo.com"], d, full("08:00", "17:00"))

        # Hoje: cada um em uma situação diferente (o painel do gestor mostra as quatro)
        if today.weekday() < 5:
            day(users["ana@demo.com"], today, [("08:20", "entrada")])                                        # trabalhando, atrasada
            day(users["beto@demo.com"], today, [("07:55", "entrada"), ("12:00", "inicio_intervalo")])         # em intervalo
            # Carla ainda não bateu: aparece como "sem marcação"
        db.commit()

        # Pendências para exercitar as telas de aprovação
        missed = days[-2]
        db.add(Adjustment(company_id=company.id, user_id=users["ana@demo.com"].id, kind="incluir", requested_at=_utc(missed, "17:00"),
                          punch_kind="saida", reason="Esqueci de bater a saída", status="pending"))
        db.add(Absence(company_id=company.id, user_id=users["carla@demo.com"].id, kind="abono", start_date=days[-1], end_date=days[-1],
                       reason="Consulta de rotina", status="pending", created_by=users["carla@demo.com"].id))
        db.add(Absence(company_id=company.id, user_id=users["beto@demo.com"].id, kind="ferias", start_date=today + timedelta(days=30),
                       end_date=today + timedelta(days=44), reason="Férias programadas", status="approved",
                       created_by=users["rita@demo.com"].id, decided_by=users["rita@demo.com"].id))
        db.commit()
    print("Demonstração criada. Logins (senha " + PASSWORD + "): admin@demo.com, rita@demo.com (RH), gil@demo.com (gestor), "
          "ana@demo.com, beto@demo.com, carla@demo.com (colaboradores).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
