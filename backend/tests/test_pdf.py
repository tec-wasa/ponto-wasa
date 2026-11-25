"""Comprovante em PDF assinado (Art. 80) e Espelho de Ponto oficial (Art. 84)."""
import io
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfReader

from app.config import settings

INPI = "12345678901234567"


def pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


@pytest.fixture(autouse=True)
def base_settings(monkeypatch):
    monkeypatch.setattr(settings, "inpi_number", INPI)
    monkeypatch.setattr(settings, "signing_p12_path", "")
    monkeypatch.setattr(settings, "allow_missing_inpi", False)


@pytest.fixture()
def signing_cert(tmp_path, monkeypatch):
    """Certificado autoassinado de teste (não é ICP-Brasil), com uso de chave para assinatura."""
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
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp_path / "pdf.p12"
    path.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"segredo")))
    monkeypatch.setattr(settings, "signing_p12_path", str(path))
    monkeypatch.setattr(settings, "signing_p12_password", "segredo")
    return cert


def validate(pdf: bytes, cert):
    from asn1crypto import x509 as asn1x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    root = asn1x509.Certificate.load(cert.public_bytes(Encoding.DER))
    sigs = PdfFileReader(io.BytesIO(pdf)).embedded_signatures
    assert len(sigs) == 1
    return sigs[0], validate_pdf_signature(sigs[0], ValidationContext(trust_roots=[root]))


# --- Comprovante -------------------------------------------------------------
def test_receipt_pdf_requires_certificate_outside_test_mode(client, world):
    p = client.post("/punches", headers=world["emp"], json={}).json()
    r = client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["emp"])
    assert r.status_code == 409 and "ICP-Brasil" in r.json()["detail"]


def test_receipt_pdf_in_test_mode_is_flagged_and_has_all_article_79_fields(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)
    p = client.post("/punches", headers=world["emp"], json={}).json()
    r = client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["emp"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert "invalido como comprovante" in r.headers["x-ponto-warning"]
    assert f"comprovante-NSR{p['nsr']}.pdf" in r.headers["content-disposition"]
    text = pdf_text(r.content)
    for expected in ("Comprovante de Registro de Ponto do Trabalhador", f"NSR {p['nsr']}", "Empresa A",
                     "11.111.111/0001-11", "Ana Colab", "Data e hora", INPI, p["hash"]):
        assert expected in text.replace("\n", " ").replace("  ", " "), expected


def test_signed_receipt_pdf_has_a_valid_pades_signature_and_detects_tampering(client, world, signing_cert):
    p = client.post("/punches", headers=world["emp"], json={}).json()
    r = client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["emp"])
    assert r.status_code == 200 and "x-ponto-warning" not in r.headers
    sig, status = validate(r.content, signing_cert)
    assert sig.sig_object["/SubFilter"] == "/ETSI.CAdES.detached"  # PAdES
    assert status.intact and status.valid and status.trusted  # íntegra, assinatura válida, cadeia confiável
    assert "Teste Ponto Ltda" in status.signing_cert.subject.human_friendly

    # adulterar um byte do conteúdo assinado invalida a assinatura
    tampered = r.content.replace(b"Comprovante", b"Comprovanta", 1)
    assert tampered != r.content
    _, bad = validate(tampered, signing_cert)
    assert bad.intact is False  # o resumo do documento não confere mais com o assinado


def test_receipt_pdf_access_control(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)
    p = client.post("/punches", headers=world["emp"], json={}).json()
    assert client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["other"]).status_code == 404
    assert client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["adminB"]).status_code == 404
    assert client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["mgr"]).status_code == 200  # gestor da equipe
    assert client.get(f"/punches/{p['id']}/receipt.pdf").status_code == 401


# --- Espelho de Ponto oficial (Art. 84) ----------------------------------------
def local_utc(day, hhmm):
    from zoneinfo import ZoneInfo
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo("America/Sao_Paulo")).astimezone(UTC).replace(tzinfo=None)


@pytest.fixture()
def treated_day(client, world, db):
    """Ana: entrada 07:00 (por engano), 08:00, saída 12:00, entrada 13:00; a das 07:00 é desconsiderada e a saída das 17:00, incluída."""
    from zoneinfo import ZoneInfo

    from app.models import User
    from app.services.punching import register_punch

    client.patch(f"/users/{world['ids']['emp']}", headers=world["hr"], json={"job_title": "Analista de Sistemas", "admitted_at": "2020-01-01"})
    ana = db.get(User, world["ids"]["emp"])
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=3)
    punches = {}
    for hhmm, kind in (("07:00", "entrada"), ("08:00", "entrada"), ("12:00", "saida"), ("13:00", "entrada")):
        punches[hhmm] = register_punch(db, ana, kind=kind, occurred_at=local_utc(day, hhmm), enforce_sequence=False)
    db.commit()
    a1 = client.post("/adjustments", headers=world["emp"], json={
        "kind": "desconsiderar", "target_punch_id": punches["07:00"].id, "reason": "Marcação por engano"}).json()
    a2 = client.post("/adjustments", headers=world["emp"], json={
        "kind": "incluir", "requested_at": local_utc(day, "17:00").isoformat(), "punch_kind": "saida", "reason": "Esqueci a saída"}).json()
    for a in (a1, a2):
        assert client.post(f"/adjustments/{a['id']}/decision", headers=world["mgr"], json={"approve": True}).status_code == 200
    return day, punches


def test_espelho_contains_everything_article_84_requires(client, world, db, treated_day):
    from app.models import Company, User
    from app.services.espelho import build_espelho

    day, punches = treated_day
    e = build_espelho(db, db.get(Company, 1), db.get(User, world["ids"]["emp"]), day.year, day.month)

    assert e["employer"]["name"] == "Empresa A" and e["employer"]["id"] == "11.111.111/0001-11"  # I
    assert e["worker"]["name"] == "Ana Colab" and len(e["worker"]["cpf"]) == 11  # II
    assert e["worker"]["admitted_at"] == "2020-01-01" and e["worker"]["job_title"] == "Analista de Sistemas"
    assert e["issued_at"] and e["period"] == {"start": f"{day:%Y-%m}-01", "end": e["period"]["end"]}  # III
    assert e["contract"]["periods"] == "08:00-12:00 e 13:00-17:00" and e["contract"]["daily_minutes"] == 480  # IV

    row = next(r for r in e["rows"] if r["date"] == day.isoformat())
    assert [m[:5] for m in row["rep"]] == ["07:00", "08:00", "12:00", "13:00"]  # V: tudo o que o REP registrou
    assert all("NSR" in m for m in row["rep"])
    assert row["treated"] == [
        "07:00 Entrada: desconsiderada - Marcação por engano",
        "17:00 Saída: incluída manualmente - Esqueci a saída",
    ]
    assert row["worked"] == 480 and row["night"] == 0 and row["reduced"] == 480  # VI
    assert e["totals"]["worked"] >= 480


def test_espelho_shows_missing_job_title_instead_of_hiding_it(client, world, db):
    from datetime import datetime as dt

    from app.models import Company, User
    from app.services.espelho import build_espelho
    e = build_espelho(db, db.get(Company, 1), db.get(User, world["ids"]["other"]), dt.now().year, dt.now().month)
    assert e["worker"]["job_title"] == "Não informado"


def test_official_mirror_pdf_endpoint(client, world, treated_day):
    day, _ = treated_day
    month = f"{day:%Y-%m}"
    r = client.get(f"/mirror/official.pdf?month={month}", headers=world["emp"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert f"-{month}.pdf" in r.headers["content-disposition"]
    text = " ".join(pdf_text(r.content).split())
    for expected in ("Espelho de Ponto Eletrônico", "Empresa A", "Ana Colab", "Admissão 01/01/2020",
                     "Cargo/função: Analista de Sistemas", "08:00-12:00 e 13:00-17:00", "desconsiderada",
                     "incluída manualmente", "Esqueci a saída", "hora noturna reduzida"):
        assert expected in text, expected

    # gestor vê a equipe; outro colaborador e outra empresa não
    uid = world["ids"]["emp"]
    assert client.get(f"/mirror/official.pdf?month={month}&user_id={uid}", headers=world["mgr"]).status_code == 200
    assert client.get(f"/mirror/official.pdf?month={month}&user_id={uid}", headers=world["other"]).status_code == 404
    assert client.get(f"/mirror/official.pdf?month={month}&user_id={uid}", headers=world["adminB"]).status_code == 404
    assert client.get("/mirror/official.pdf?month=2026-13", headers=world["emp"]).status_code == 422
    assert client.get(f"/mirror/official.pdf?month={month}").status_code == 401
    trail = client.get("/audit?entity=espelho", headers=world["admin"]).json()
    assert trail and trail[0]["action"] == "export"


def test_job_title_is_stored_and_returned(client, world):
    r = client.patch(f"/users/{world['ids']['emp']}", headers=world["hr"], json={"job_title": "Contadora"})
    assert r.status_code == 200 and r.json()["job_title"] == "Contadora"
    made = client.post("/users", headers=world["hr"], json={
        "name": "Nova Pessoa", "email": "np@a.com", "password": "senha-forte-123", "cpf": "529.982.247-25", "job_title": "Analista"})
    assert made.status_code == 201 and made.json()["job_title"] == "Analista"


def test_espelho_pdf_puts_each_mark_on_its_own_line_and_signals_signature(client, world, treated_day, signing_cert):
    day, _ = treated_day
    r = client.get(f"/mirror/official.pdf?month={day:%Y-%m}", headers=world["emp"])
    lines = [l.strip() for l in pdf_text(r.content).splitlines()]
    for mark in ("07:00 Entrada (NSR", "08:00 Entrada (NSR", "12:00 Saída (NSR", "13:00 Entrada (NSR"):
        assert any(l.startswith(mark) for l in lines), f"linha própria para {mark}"  # nada de marcas coladas

    p = client.post("/punches", headers=world["emp"], json={}).json()
    receipt = client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["emp"])
    assert "assinado eletronicamente" in " ".join(pdf_text(receipt.content).split())


def test_unsigned_test_receipt_is_visibly_marked_as_invalid(client, world, monkeypatch):
    monkeypatch.setattr(settings, "allow_missing_inpi", True)
    p = client.post("/punches", headers=world["emp"], json={}).json()
    text = " ".join(pdf_text(client.get(f"/punches/{p['id']}/receipt.pdf", headers=world["emp"]).content).split())
    assert "DOCUMENTO DE TESTE" in text and "Inválido como comprovante" in text


def test_night_shift_is_shown_on_the_day_it_started(client, world, db):
    from zoneinfo import ZoneInfo

    from app.models import Company, Schedule, User
    from app.services.espelho import build_espelho
    from app.services.punching import register_punch

    ana = db.get(User, world["ids"]["emp"])
    db.get(Schedule, ana.schedule_id).crosses_midnight = True  # jornada do turno da noite
    db.commit()
    client.patch(f"/users/{ana.id}", headers=world["hr"], json={"admitted_at": "2020-01-01"})
    start = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=4)
    register_punch(db, ana, kind="entrada", occurred_at=local_utc(start, "22:00"), enforce_sequence=False)
    register_punch(db, ana, kind="saida", occurred_at=local_utc(start + timedelta(days=1), "06:00"), enforce_sequence=False)
    db.commit()
    e = build_espelho(db, db.get(Company, 1), db.get(User, ana.id), start.year, start.month)
    rows = {r["date"]: r for r in e["rows"]}
    first, second = rows[start.isoformat()], rows[(start + timedelta(days=1)).isoformat()]
    assert first["rep"][0].startswith("22:00 Entrada")
    assert first["rep"][1].startswith("06:00 Saída") and first["rep"][1].endswith("(dia seguinte)")
    assert not any("06:00" in m for m in second["rep"])  # a saída não aparece solta no dia seguinte
    assert first["worked"] == 480 and first["night"] == 420 and first["reduced"] == 540  # 7 h noturnas viram 8 h
