"""AFD e AEJ conforme a Portaria MTP 671/2021 (Anexos V e VI). Confere posições, tamanhos, CRC e hash."""
import hashlib
import io
import os
import shutil
import subprocess
import zipfile
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.models import User
from app.services import clock
from app.services.arp import fmt_dh
from app.services.cpf import digits, is_valid_cpf
from app.services.layout import alpha, crc16, num
from app.services.punching import register_punch
from tests.conftest import login, make_cpf

INPI = "12345678901234567"
TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture(autouse=True)
def legal_settings(monkeypatch):
    monkeypatch.setattr(settings, "inpi_number", INPI)
    monkeypatch.setattr(settings, "dev_id", "12345678000199")
    monkeypatch.setattr(settings, "dev_name", "Dev Ltda")
    monkeypatch.setattr(settings, "dev_email", "dev@x.com")
    monkeypatch.setattr(settings, "signing_p12_path", "")
    monkeypatch.setattr(settings, "clock_check_enabled", False)


def today_local() -> date:
    return datetime.now(TZ).date()


def utc_of(local_date: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(local_date.year, local_date.month, local_date.day, h, m, tzinfo=TZ).astimezone(UTC).replace(tzinfo=None)


def get_file(client, headers, kind, start, end, **extra):
    q = f"start={start}&end={end}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return client.get(f"/exports/{kind}?{q}", headers=headers)


def lines_of(resp):
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("latin-1")
    assert text.endswith("\r\n"), "cada linha deve terminar em CR LF"
    lines = text.split("\r\n")[:-1]
    assert all(lines), "não pode haver linhas em branco"
    return lines


# --- utilitários de leiaute ---------------------------------------------------
def test_layout_helpers():
    assert crc16("123456789") == "BB3D"  # vetor de teste padrão do CRC-16/ARC
    assert num(7, 3) == "007" and alpha("José", 8) == "José    " and alpha("abcdef", 3) == "abc"
    with pytest.raises(ValueError):
        num(1234, 3)
    assert alpha("emoji 😀", 9) == "emoji ?  "  # o que não existe em ISO 8859-1 vira '?'
    assert fmt_dh(datetime(2026, 9, 24, 19, 18, 59), -180) == "2026-09-24T16:18:00-0300"  # segundos sempre 00
    assert fmt_dh(datetime(2026, 9, 24, 19, 18), 330) == "2026-09-25T00:48:00+0530"


def test_cpf_validation():
    assert is_valid_cpf("529.982.247-25") and digits("529.982.247-25") == "52998224725"
    assert not is_valid_cpf("529.982.247-24") and not is_valid_cpf("00000000000") and not is_valid_cpf("123")
    assert is_valid_cpf(make_cpf(123456789))


# --- AFD ---------------------------------------------------------------------
def test_afd_layout_positions_lengths_crc_and_hash(client, world, db):
    client.post("/users", headers=world["hr"], json={
        "name": "José da Conceição", "email": "jose@a.com", "password": "senha-forte-123", "cpf": make_cpf(500000001)})
    for _ in range(3):
        client.post("/punches", headers=world["emp"], json={"collector": "01"})
    d = today_local()
    resp = get_file(client, world["hr"], "afd", d - timedelta(days=1), d + timedelta(days=1))
    lines = lines_of(resp)
    assert resp.headers["content-disposition"] == f'attachment; filename="AFD{INPI}11111111000111REP_P.txt"'

    # Tipo 1 — cabeçalho (302 posições)
    h = lines[0]
    assert len(h) == 302 and h[:10] == "0000000001"
    assert h[10] == "1" and h[11:25] == "11111111000111" and h[25:39] == "0" * 14
    assert h[39:189] == alpha("Empresa A", 150) and h[189:206] == INPI
    assert h[206:216] == str(d - timedelta(days=1)) and h[216:226] == str(d + timedelta(days=1))
    assert h[226:250].endswith("-0300") and h[250:253] == "003"
    assert h[253] == "1" and h[254:268] == "12345678000199" and h[268:298] == " " * 30
    assert h[298:302] == crc16(h[:298])

    # Tipo 9 — trailer (64 posições)
    t = lines[-1]
    assert len(t) == 64 and t[:9] == "999999999" and t[63] == "9"
    body = lines[1:-1]
    sizes = {"2": 331, "5": 118, "6": 36, "7": 137}
    counts = {k: 0 for k in "234567"}
    prev_hash, seen_nsr = "", []
    for line in body:
        rtype = line[9]
        assert len(line) == sizes[rtype], f"tipo {rtype} deve ter {sizes[rtype]} posições, tem {len(line)}"
        counts[rtype] += 1
        seen_nsr.append(int(line[:9]))
        if rtype in "25":  # CRC-16 só nos tipos 1 a 5
            assert line[-4:] == crc16(line[:-4])
        if rtype == "7":
            nsr, dh, cpf, dh2, col, off, hsh = line[:9], line[10:34], line[34:46], line[46:70], line[70:72], line[72], line[73:]
            assert dh.endswith("-0300") and dh[17:19] == "00" and col == "01" and off == "0" and len(cpf) == 12
            raw = f"{nsr}7{dh}{cpf}{dh2}{col}{off}{prev_hash}"  # hipótese H1, recalculada de forma independente
            assert hashlib.sha256(raw.encode()).hexdigest() == hsh
            prev_hash = hsh
    assert seen_nsr == list(range(1, len(body) + 1))  # NSR único e contínuo, todos os tipos, em ordem
    assert [int(t[9 + 9 * i:18 + 9 * i]) for i in range(6)] == [counts[k] for k in "234567"]
    assert counts["2"] == 1 and counts["5"] == 6 and counts["7"] == 3
    # acentos preservados em ISO 8859-1
    assert any(l[9] == "5" and "José da Conceição" in l for l in body)


def test_afd_type2_and_type5_fields(client, world):
    d = today_local()
    lines = lines_of(get_file(client, world["hr"], "afd", d, d))
    t2 = next(l for l in lines if len(l) == 331 and l[9] == "2")
    assert t2[10:34].endswith("-0300")
    assert t2[34:48] == num(make_cpf(100000001), 14)  # CPF do responsável: o administrador que criou a empresa
    assert t2[48] == "1" and t2[49:63] == "11111111000111" and t2[63:77] == "0" * 14
    assert t2[77:227] == alpha("Empresa A", 150) and t2[227:327] == " " * 100  # local de prestação ainda vazio
    t5 = [l for l in lines if l[9] == "5"]
    assert {l[34] for l in t5} == {"I"} and all(l[103:114].isdigit() for l in t5)  # CPF do responsável (11)


def test_afd_range_and_permissions(client, world):
    d = today_local()
    old = get_file(client, world["hr"], "afd", d - timedelta(days=400), d - timedelta(days=399))
    lines = lines_of(old)
    assert len(lines) == 2 and lines[1][9:] == "0" * 54 + "9"  # só cabeçalho e trailer, contagens zeradas
    assert get_file(client, world["hr"], "afd", d, d - timedelta(days=1)).status_code == 422
    assert get_file(client, world["emp"], "afd", d, d).status_code == 403
    assert get_file(client, world["mgr"], "afd", d, d).status_code == 403
    assert get_file(client, world["adminB"], "afd", d, d).status_code == 200  # cada empresa só vê o seu ARP
    assert client.get(f"/exports/afd?start={d}&end={d}").status_code == 401


def test_auditor_can_export_and_exports_are_audited(client, world):
    client.post("/users", headers=world["admin"], json={
        "name": "Aud Fiscal", "email": "aud@a.com", "password": "senha-forte-123", "cpf": make_cpf(500000002), "role": "auditor", "must_change_password": False})
    d = today_local()
    assert get_file(client, login(client, "aud@a.com"), "afd", d, d).status_code == 200
    trail = client.get("/audit?entity=afd", headers=world["hr"]).json()
    assert trail and trail[0]["action"] == "export"


def test_export_requires_inpi_and_developer_configuration(client, world, monkeypatch):
    d = today_local()
    monkeypatch.setattr(settings, "inpi_number", "")
    r = get_file(client, world["hr"], "afd", d, d)
    assert r.status_code == 409 and "INPI" in r.json()["detail"]
    monkeypatch.setattr(settings, "inpi_number", INPI)
    monkeypatch.setattr(settings, "dev_id", "")
    assert get_file(client, world["hr"], "aej", d, d).status_code == 409
    status = client.get("/exports/status", headers=world["hr"]).json()
    assert status["ready"] is False and any("desenvolvedor" in i for i in status["issues"])


# --- AEJ ---------------------------------------------------------------------
def test_aej_structure_marks_inclusion_and_disregard(client, world, db):
    ana = db.get(User, world["ids"]["emp"])
    day = today_local() - timedelta(days=2)
    original = [("07:00", "entrada"), ("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada")]
    punches = {}
    for hhmm, kind in original:
        punches[hhmm] = register_punch(db, ana, kind=kind, occurred_at=utc_of(day, hhmm), enforce_sequence=False)
    db.commit()
    # Ana desconsidera a marcação das 07:00 e inclui a saída esquecida das 17:00; o gestor aprova as duas.
    a1 = client.post("/adjustments", headers=world["emp"], json={
        "kind": "desconsiderar", "target_punch_id": punches["07:00"].id, "reason": "Marcação por engano"}).json()
    a2 = client.post("/adjustments", headers=world["emp"], json={
        "kind": "incluir", "requested_at": utc_of(day, "17:00").isoformat(), "punch_kind": "saida",
        "reason": "Esqueci a saída"}).json()
    for a in (a1, a2):
        assert client.post(f"/adjustments/{a['id']}/decision", headers=world["mgr"], json={"approve": True}).status_code == 200

    resp = get_file(client, world["hr"], "aej", day, day)
    assert resp.headers["content-disposition"].startswith('attachment; filename="AEJ11111111000111')
    lines = lines_of(resp)
    by = {}
    for l in lines:
        by.setdefault(l.split("|")[0], []).append(l)

    assert by["01"] == [f"01|1|11111111000111|||Empresa A|{day}|{day}|{lines[0].split('|')[8]}|001"]
    assert lines[0].split("|")[8].endswith("-0300")
    assert by["02"] == [f"02|1|3|{INPI}"]
    assert len(by["03"]) == 5 and by["03"][3] == f"03|4|{ana.cpf}|Ana Colab"  # vínculo 4 = Ana
    assert by["04"] == ["04|H1|480|0800|1200|1300|1700"]  # horário contratual derivado da jornada
    d = str(day)
    assert by["05"] == [
        f"05|4|{d}T07:00:00-0300|1|D|000|O||Marcação por engano",  # desconsiderada
        f"05|4|{d}T08:00:00-0300|1|E|001|O|H1|",  # 1ª entrada: código do horário obrigatório
        f"05|4|{d}T12:00:00-0300|1|S|001|O||",
        f"05|4|{d}T13:00:00-0300|1|E|002|O||",
        f"05|4|{d}T17:00:00-0300||S|002|I||Esqueci a saída",  # incluída manualmente: sem REP, com motivo
    ]
    assert "07" not in by  # nenhuma falta no período
    assert by["08"] == [f"08|Ponto|{settings.program_version}|1|12345678000199|Dev Ltda|dev@x.com"]
    assert lines[-1] == "99|1|1|5|1|5|0|0|1"  # contagens por tipo de registro, na ordem 01..08
    for l in by["05"]:
        assert l.count("|") == 8  # 9 campos: delimitador ao final de cada campo, menos o último


def test_aej_lists_absences_as_unjustified_faults(client, world, db):
    emp_id = world["ids"]["emp"]
    client.patch(f"/users/{emp_id}", headers=world["hr"], json={"admitted_at": "2020-01-01"})
    monday, tuesday = date(2026, 8, 3), date(2026, 8, 4)  # dias úteis passados, sem marcações
    lines = lines_of(get_file(client, world["hr"], "aej", monday, tuesday))
    faults = [l for l in lines if l.startswith("07|")]
    assert any(l.startswith("07|") and l.split("|")[2] == "2" and l.split("|")[3] == "2026-08-03" for l in faults)
    assert any(l.split("|")[3] == "2026-08-04" for l in faults)


def test_aej_requires_a_schedule_for_people_with_marks(client, world, db):
    admin = db.query(User).filter(User.email == "admin@a.com").one()  # o administrador do seed não tem jornada
    day = today_local() - timedelta(days=1)
    register_punch(db, admin, kind="entrada", occurred_at=utc_of(day, "08:00"), enforce_sequence=False)
    db.commit()
    r = get_file(client, world["hr"], "aej", day, day)
    assert r.status_code == 409 and "Administrador" in r.json()["detail"]


# --- Assinatura --------------------------------------------------------------
@pytest.fixture()
def p12(tmp_path, monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Teste Ponto Ltda")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256()))
    path = tmp_path / "teste.p12"
    path.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"segredo")))
    monkeypatch.setattr(settings, "signing_p12_path", str(path))
    monkeypatch.setattr(settings, "signing_p12_password", "segredo")
    return cert


def test_signed_export_returns_txt_and_detached_signature(client, world, p12, tmp_path):
    from cryptography.hazmat.primitives.serialization import pkcs7

    d = today_local()
    resp = get_file(client, world["hr"], "afd", d, d, signed="true")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    txt_name = f"AFD{INPI}11111111000111REP_P.txt"
    assert sorted(z.namelist()) == [txt_name, txt_name + ".p7s"]
    signature = z.read(txt_name + ".p7s")
    assert pkcs7.load_der_pkcs7_certificates(signature)[0].subject == p12.subject

    openssl = shutil.which("openssl")
    if openssl:  # verificação criptográfica independente da assinatura destacada
        (tmp_path / "a.txt").write_bytes(z.read(txt_name))
        (tmp_path / "a.p7s").write_bytes(signature)
        base = [openssl, "smime", "-verify", "-binary", "-inform", "DER", "-noverify", "-in", str(tmp_path / "a.p7s"), "-out", os.devnull]
        assert subprocess.run([*base, "-content", str(tmp_path / "a.txt")], capture_output=True).returncode == 0
        (tmp_path / "b.txt").write_bytes(z.read(txt_name) + b"adulterado")
        assert subprocess.run([*base, "-content", str(tmp_path / "b.txt")], capture_output=True).returncode != 0


def test_signed_export_without_certificate_is_refused(client, world):
    d = today_local()
    r = get_file(client, world["hr"], "afd", d, d, signed="true")
    assert r.status_code == 409 and "Certificado" in r.json()["detail"]
    assert get_file(client, world["hr"], "afd", d, d).status_code == 200  # sem assinatura continua disponível


# --- Sincronismo com a Hora Legal Brasileira -----------------------------------
def test_punch_is_refused_when_clock_drift_exceeds_30_seconds(client, world, monkeypatch):
    monkeypatch.setattr(settings, "clock_check_enabled", True)
    monkeypatch.setattr(clock, "_cache", None)
    monkeypatch.setattr(clock, "query_ntp_offset", lambda server, timeout=3.0: 45.0)
    r = client.post("/punches", headers=world["emp"], json={})
    assert r.status_code == 503 and "sincronismo" in r.json()["detail"]
    assert client.get("/exports/status", headers=world["hr"]).json()["ready"] is False

    monkeypatch.setattr(clock, "_cache", None)
    monkeypatch.setattr(clock, "query_ntp_offset", lambda server, timeout=3.0: 5.0)
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201


def test_punch_is_allowed_but_flagged_when_ntp_is_unreachable(client, world, monkeypatch):
    def down(server, timeout=3.0):
        raise OSError("sem rede")

    monkeypatch.setattr(settings, "clock_check_enabled", True)
    monkeypatch.setattr(clock, "_cache", None)
    monkeypatch.setattr(clock, "query_ntp_offset", down)
    assert client.post("/punches", headers=world["emp"], json={}).status_code == 201  # não derruba o registro
    status = client.get("/exports/status", headers=world["hr"]).json()
    assert any("NTP" in i for i in status["issues"])


# --- Modo de teste (sem INPI) --------------------------------------------------
def test_test_mode_generates_flagged_files_without_inpi(client, world, monkeypatch):
    d = today_local()
    monkeypatch.setattr(settings, "inpi_number", "")
    monkeypatch.setattr(settings, "dev_id", "")
    assert get_file(client, world["hr"], "afd", d, d).status_code == 409  # padrão: estrito, como em produção

    monkeypatch.setattr(settings, "allow_missing_inpi", True)
    for kind in ("afd", "aej"):
        r = get_file(client, world["hr"], kind, d, d)
        assert r.status_code == 200 and "invalido para fiscalizacao" in r.headers["x-ponto-warning"]
    lines = lines_of(get_file(client, world["hr"], "afd", d, d))
    assert len(lines[0]) == 302 and lines[0][189:206] == "0" * 17 and lines[0][254:268] == "0" * 14  # placeholders zerados
    assert lines[0][298:302] == crc16(lines[0][:298])  # o leiaute continua íntegro
    status = client.get("/exports/status", headers=world["hr"]).json()
    assert status["ready"] is False and any("MODO DE TESTE" in i for i in status["issues"])


def test_configured_inpi_is_never_flagged_as_test(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)  # ligado, mas com INPI e desenvolvedor configurados
    d = today_local()
    assert "x-ponto-warning" not in get_file(client, world["hr"], "afd", d, d).headers
