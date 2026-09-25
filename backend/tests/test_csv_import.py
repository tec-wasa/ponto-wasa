"""Importação de colaboradores por CSV."""
import base64
import time

import pytest
from sqlalchemy import func, select

from app.models import ArpEvent, AuditLog, User
from app.services import csv_import
from app.services.arp import verify_chain
from tests.conftest import PASSWORD, make_cpf

HEADER = "nome;email;cpf;cargo;gestor;jornada;perfil;admissao"


def b64(text: str, encoding: str = "utf-8") -> str:
    return base64.b64encode(text.encode(encoding)).decode()


def post(client, headers, text, dry_run=True, encoding="utf-8"):
    return client.post(f"/users/import?dry_run={'true' if dry_run else 'false'}", headers=headers,
                       json={"content_base64": b64(text, encoding)})


def cpf(n: int) -> str:
    c = make_cpf(n)
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


def count_users(db) -> int:
    return db.execute(select(func.count()).select_from(User)).scalar_one()


def errors_of(resp):
    return [(e["line"], e["field"]) for e in resp.json()["errors"]]


def good_csv(*extra_rows: str) -> str:
    rows = [f"Ana Nova;ana.nova@a.com;{cpf(710000001)};Analista;gestor@a.com;Comercial;colaborador;15/03/2024",
            f"Bia Nova;bia.nova@a.com;{cpf(710000002)};Assistente;;;;", *extra_rows]
    return HEADER + "\n" + "\n".join(rows) + "\n"


# ------------------------------- validação (simulação) ----------------------
def test_dry_run_validates_without_writing_anything(client, world, db):
    before, arp_before = count_users(db), db.query(ArpEvent).count()
    r = post(client, world["hr"], good_csv())
    body = r.json()
    assert r.status_code == 200 and body["dry_run"] is True and body["errors"] == []
    assert body["total"] == 2 and body["valid"] == 2 and body["imported"] is False and body["credentials"] == []
    assert [p["email"] for p in body["preview"]] == ["ana.nova@a.com", "bia.nova@a.com"]
    assert body["preview"][0]["manager"] == "gestor@a.com" and body["preview"][1]["role"] == "employee"
    assert count_users(db) == before and db.query(ArpEvent).count() == arp_before  # nada gravado


def test_default_is_dry_run(client, world, db):
    before = count_users(db)
    r = client.post("/users/import", headers=world["hr"], json={"content_base64": b64(good_csv())})
    assert r.json()["dry_run"] is True and count_users(db) == before


def test_template_is_a_valid_import_file_with_bom(client, world):
    r = client.get("/users/import/template", headers=world["hr"])
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf") and "modelo-colaboradores.csv" in r.headers["content-disposition"]
    # o exemplo referencia gestor e jornada que não existem: a validação explica o que falta (e nada mais)
    fields = {e["field"] for e in post(client, world["hr"], r.content.decode("utf-8-sig")).json()["errors"]}
    assert fields <= {"gestor", "jornada"}


@pytest.mark.parametrize("text,encoding", [
    (f"nome;email;cpf\nJosé Conceição;jose.c@a.com;{cpf(710000010)}\n", "utf-8"),
    (f"nome;email;cpf\nJosé Conceição;jose.c@a.com;{cpf(710000010)}\n", "utf-8-sig"),  # com BOM
    (f"nome;email;cpf\nJosé Conceição;jose.c@a.com;{cpf(710000010)}\n", "cp1252"),  # Excel em português
    (f"nome,email,cpf\nJosé Conceição,jose.c@a.com,{cpf(710000010)}\n", "utf-8"),  # vírgula
    (f"Nome Completo;E-mail;CPF\r\nJosé Conceição;JOSE.C@A.COM;{cpf(710000010)}\r\n\r\n", "cp1252"),  # títulos, CRLF, linha em branco
])
def test_accepts_the_usual_excel_variations(client, world, text, encoding):
    body = post(client, world["hr"], text, encoding=encoding).json()
    assert body["errors"] == [] and body["valid"] == 1 and body["preview"][0]["name"] == "José Conceição"
    assert body["preview"][0]["email"] == "jose.c@a.com"


def test_header_aliases_are_understood(client, world):
    text = (f"Nome;E-mail;CPF;Cargo/Função;E-mail do Gestor;Jornada;Perfil;Data de Admissão\n"
            f"Ana;ana.x@a.com;{cpf(710000020)};Analista;gestor@a.com;COMERCIAL;Gestor;2024-03-15\n")
    body = post(client, world["hr"], text).json()
    assert body["errors"] == [] and body["preview"][0]["role"] == "manager"  # jornada sem diferenciar maiúsculas


def test_every_kind_of_row_error_is_reported_with_its_line(client, world):
    text = HEADER + "\n" + "\n".join([
        f"A;a1@a.com;{cpf(710000030)};;;;;",  # 2: nome curto
        f"Boa Pessoa;email-invalido;{cpf(710000031)};;;;;",  # 3: e-mail
        "Cpf Ruim;cpf.ruim@a.com;123.456.789-00;;;;;",  # 4: CPF
        f"Repetida;hr@a.com;{cpf(710000032)};;;;;",  # 5: e-mail já existe no sistema
        f"Outra;outra@a.com;{make_cpf(200000001)};;;;;",  # 6: CPF já existe na empresa (é o do RH)
        f"Igual Um;igual@a.com;{cpf(710000033)};;;;;",  # 7: ok
        f"Igual Dois;igual@a.com;{cpf(710000034)};;;;;",  # 8: e-mail repetido no arquivo
        f"Igual Tres;igual3@a.com;{cpf(710000033)};;;;;",  # 9: CPF repetido no arquivo
        f"Sem Jornada;sj@a.com;{cpf(710000035)};;;Inexistente;;",  # 10: jornada
        f"Perfil Errado;pe@a.com;{cpf(710000036)};;;;chefe;",  # 11: perfil desconhecido
        f"Quer Ser Admin;qa@a.com;{cpf(710000037)};;;;admin;",  # 12: RH não cria admin
        f"Data Ruim;dr@a.com;{cpf(710000038)};;;;;31/02/2024",  # 13: data
    ]) + "\n"
    body = post(client, world["hr"], text).json()
    got = {(e["line"], e["field"]) for e in body["errors"]}
    assert got == {(2, "nome"), (3, "email"), (4, "cpf"), (5, "email"), (6, "cpf"), (8, "email"), (9, "cpf"),
                   (10, "jornada"), (11, "perfil"), (12, "perfil"), (13, "admissão")}
    assert body["valid"] == 1 and body["preview"][0]["email"] == "igual@a.com"  # só a linha 7 é válida
    assert any("linha 7" in e["message"] for e in body["errors"] if e["line"] == 8)  # aponta a linha original


def test_manager_column_rules(client, world):
    text = (HEADER + "\n"
            f"Chefe Novo;chefe@a.com;{cpf(710000040)};;;;gestor;\n"
            f"Sub Um;sub1@a.com;{cpf(710000041)};;chefe@a.com;;;\n"  # o gestor está no próprio arquivo (e vem antes)
            f"Sub Dois;sub2@a.com;{cpf(710000042)};;ana@a.com;;;\n"  # ana é colaboradora, não gestora
            f"Sub Tres;sub3@a.com;{cpf(710000043)};;fantasma@a.com;;;\n")  # não existe
    body = post(client, world["hr"], text).json()
    assert {(e["line"], e["field"]) for e in body["errors"]} == {(4, "gestor"), (5, "gestor")}


def test_file_level_errors(client, world):
    assert errors_of(post(client, world["hr"], "")) == [(1, "arquivo")]
    assert errors_of(post(client, world["hr"], "nome;email\nA;a@a.com\n")) == [(1, "cabeçalho")]  # falta cpf
    assert errors_of(post(client, world["hr"], HEADER + "\n")) == [(1, "arquivo")]  # só o cabeçalho
    rows = "\n".join(f"P{i};p{i}@x.com;{cpf(720000000 + i)}" for i in range(csv_import.MAX_ROWS + 1))
    too_many = post(client, world["hr"], "nome;email;cpf\n" + rows)
    assert errors_of(too_many) == [(1, "arquivo")] and "201" in too_many.json()["errors"][0]["message"]
    exactly = "\n".join(f"P{i};p{i}@x.com;{cpf(720000000 + i)}" for i in range(csv_import.MAX_ROWS))
    assert post(client, world["hr"], "nome;email;cpf\n" + exactly).json()["valid"] == csv_import.MAX_ROWS  # o limite é 200
    bad = client.post("/users/import", headers=world["hr"], json={"content_base64": "isto-nao-e-base64!!"})
    assert bad.status_code == 422
    huge = client.post("/users/import", headers=world["hr"], json={"content_base64": "A" * 1_500_000})
    assert huge.status_code == 422  # excede o tamanho máximo do corpo


# ------------------------------- importação real -----------------------------
def test_real_import_creates_users_with_temporary_passwords_and_records_the_arp(client, world, db):
    from app.models import Schedule
    sched = db.execute(select(Schedule)).scalars().first()
    text = (HEADER + "\n"
            f"Filha Um;filha1@a.com;{cpf(730000001)};Analista;chefe.novo@a.com;{sched.name};colaborador;15/03/2024\n"  # gestor vem depois
            f"Chefe Novo;chefe.novo@a.com;{cpf(730000002)};Coordenador;;{sched.name};gestor;01/02/2023\n"
            f"Sem Nada;sem.nada@a.com;{cpf(730000003)};;;;;\n")
    arp_before = db.query(ArpEvent).filter(ArpEvent.record_type == "5").count()
    r = post(client, world["hr"], text, dry_run=False)
    body = r.json()
    assert r.status_code == 200 and body["imported"] is True and body["created"] == 3 and body["dry_run"] is False

    users = {u.email: u for u in db.execute(select(User)).scalars()}
    filha, chefe = users["filha1@a.com"], users["chefe.novo@a.com"]
    assert filha.manager_id == chefe.id  # referência para frente resolvida
    assert filha.job_title == "Analista" and str(filha.admitted_at) == "2024-03-15" and filha.schedule_id == sched.id
    assert chefe.role == "manager" and users["sem.nada@a.com"].role == "employee" and filha.cpf == make_cpf(730000001)
    assert all(u.must_change_password for u in (filha, chefe, users["sem.nada@a.com"]))

    # credenciais: aparecem só nesta resposta, cada uma diferente, e realmente funcionam (com troca obrigatória)
    creds = {c["email"]: c["password"] for c in body["credentials"]}
    assert len(creds) == 3 and len(set(creds.values())) == 3 and all(len(p) == 12 for p in creds.values())
    assert PASSWORD not in creds.values()
    r1 = client.post("/auth/login", json={"email": "filha1@a.com", "password": creds["filha1@a.com"]})
    assert r1.status_code == 200
    gate = client.get("/mirror?month=2026-08", headers={"Authorization": f"Bearer {r1.json()['access_token']}"})
    assert gate.status_code == 403 and gate.json()["detail"]["code"] == "password_change_required"

    # o ARP registrou as três inclusões (tipo 5) e a cadeia está íntegra; a trilha não guarda senha nem CPF
    assert db.query(ArpEvent).filter(ArpEvent.record_type == "5").count() == arp_before + 3
    assert verify_chain(db, 1)["ok"]
    trail = db.execute(select(AuditLog).where(AuditLog.action == "import")).scalar_one()
    assert trail.after == {"created": 3} and not any(p in str(trail.after) for p in creds.values())
    # importar de novo o mesmo arquivo falha por duplicidade e não cria nada
    again = post(client, world["hr"], text, dry_run=False)
    assert again.status_code == 422 and again.json()["created"] == 0 and count_users(db) == len(users)


def test_all_or_nothing_when_any_row_is_invalid(client, world, db):
    before, arp_before = count_users(db), db.query(ArpEvent).count()
    r = post(client, world["hr"], good_csv("Ruim;ruim@a.com;123.456.789-00;;;;;"), dry_run=False)
    assert r.status_code == 422 and r.json()["imported"] is False and r.json()["credentials"] == []
    assert errors_of(r) == [(4, "cpf")]
    assert count_users(db) == before and db.query(ArpEvent).count() == arp_before  # as duas linhas boas também não entraram


def test_only_admin_can_create_privileged_roles(client, world, db):
    text = f"nome;email;cpf;perfil\nNovo RH;novo.rh@a.com;{cpf(740000001)};rh\n"
    assert post(client, world["hr"], text).json()["errors"][0]["field"] == "perfil"
    assert post(client, world["admin"], text, dry_run=False).json()["imported"] is True
    assert db.execute(select(User.role).where(User.email == "novo.rh@a.com")).scalar_one() == "hr"


def test_permissions_and_tenant_isolation(client, world, db):
    for who in ("emp", "mgr", "other"):
        assert post(client, world[who], good_csv()).status_code == 403
        assert client.get("/users/import/template", headers=world[who]).status_code == 403
    assert client.post("/users/import", json={"content_base64": b64(good_csv())}).status_code == 401
    # a empresa B não enxerga jornadas nem gestores da empresa A: a referência é recusada
    other = post(client, world["adminB"], good_csv()).json()
    assert {e["field"] for e in other["errors"]} == {"gestor", "jornada"}
    ok = post(client, world["adminB"], f"nome;email;cpf\nDe B;de.b@b.com;{cpf(750000001)}\n", dry_run=False)
    assert ok.json()["created"] == 1
    assert db.execute(select(User.company_id).where(User.email == "de.b@b.com")).scalar_one() != 1


def test_import_time_is_reasonable(client, world):
    rows = "\n".join(f"P{i};imp{i}@a.com;{cpf(760000000 + i)}" for i in range(8))
    started = time.perf_counter()
    r = post(client, world["hr"], "nome;email;cpf\n" + rows, dry_run=False)
    elapsed = time.perf_counter() - started
    assert r.json()["created"] == 8
    assert elapsed < 30  # 8 hashes de senha (argon2), com folga para máquina carregada; o limite de 200 linhas vem daí
    print(f"\nimportação de 8 linhas: {elapsed:.2f}s")
