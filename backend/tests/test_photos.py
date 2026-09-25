"""Foto opcional da batida: consentimento, acesso restrito, retenção até o fechamento do mês."""
import base64

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Punch, PunchPhoto, User
from app.services.punching import register_punch
from tests.test_api import past

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000
B64 = base64.b64encode(JPEG).decode()


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photo_dir", str(tmp_path / "photos"))
    monkeypatch.setattr(settings, "allow_missing_inpi", True)


def enable(client, world, consent=True):
    assert client.patch("/company", headers=world["admin"], json={"photo_enabled": True}).status_code == 200
    if consent:
        assert client.post("/auth/consent-photo", headers=world["emp"]).json()["photo_consent_at"]


def punch(client, world):
    return client.post("/punches", headers=world["emp"], json={}).json()["id"]


def test_photo_requires_company_switch_and_consent(client, world):
    pid = punch(client, world)
    r = client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": B64})
    assert r.status_code == 403 and "ativada" in r.json()["detail"]
    enable(client, world, consent=False)
    r = client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": B64})
    assert r.status_code == 403 and "consentimento" in r.json()["detail"]


def test_upload_view_and_access_control(client, world, db):
    enable(client, world)
    pid = punch(client, world)  # a batida existe sem a foto: ela nunca depende dela
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 201
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 409  # uma por batida

    img = client.get(f"/punches/{pid}/photo", headers=world["hr"])
    assert img.status_code == 200 and img.content == JPEG and img.headers["cache-control"] == "no-store"
    assert client.get(f"/punches/{pid}/photo", headers=world["mgr"]).status_code == 403  # gestor e colaborador não veem
    assert client.get(f"/punches/{pid}/photo", headers=world["emp"]).status_code == 403
    assert client.get(f"/punches/{pid}/photo", headers=world["adminB"]).status_code == 404  # outra empresa

    photo = db.execute(select(PunchPhoto)).scalars().one()
    from pathlib import Path
    assert JPEG not in Path(settings.photo_dir, photo.storage_key).read_bytes()  # criptografada em disco
    assert db.execute(select(AuditLog).where(AuditLog.action == "view_photo")).scalars().one().actor_id
    month = past(0, 12).strftime("%Y-%m")
    rows = client.get(f"/photos?user_id={world['ids']['emp']}&month={month}", headers=world["hr"]).json()
    assert [r["punch_id"] for r in rows] == [pid]


def test_only_owner_uploads_and_bad_files_are_rejected(client, world):
    enable(client, world)
    pid = punch(client, world)
    assert client.post(f"/punches/{pid}/photo", headers=world["other"], json={"image_base64": B64}).status_code == 404
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": base64.b64encode(b"GIF89a").decode()}).status_code == 422
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": "!!!"}).status_code == 422
    big = base64.b64encode(b"\xff\xd8\xff" + b"0" * (settings.photo_max_bytes + 1)).decode()
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": big}).status_code == 413


def test_photos_are_deleted_when_the_month_is_closed(client, world, db):
    enable(client, world)
    emp = db.get(User, world["ids"]["emp"])
    when = past(40, 15)  # mês anterior
    p = register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)
    db.commit()
    month = when.strftime("%Y-%m")
    assert client.post(f"/punches/{p.id}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 201
    from pathlib import Path
    key = db.execute(select(PunchPhoto.storage_key)).scalar_one()
    assert Path(settings.photo_dir, key).exists()

    closed = client.post(f"/closings/{month}", headers=world["hr"])
    assert closed.status_code == 200 and closed.json()["photos_deleted"] == 1
    assert client.get(f"/punches/{p.id}/photo", headers=world["hr"]).status_code == 404
    assert not Path(settings.photo_dir, key).exists()
    assert db.query(PunchPhoto).count() == 0
    assert db.query(Punch).filter_by(id=p.id).count() == 1  # a marcação em si nunca é apagada
    assert client.post(f"/punches/{p.id}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 409  # mês fechado
    assert db.execute(select(AuditLog).where(AuditLog.action == "purge_photos")).scalars().one()


def test_company_photo_flag_is_admin_only(client, world):
    assert client.patch("/company", headers=world["hr"], json={"photo_enabled": True}).status_code == 403
    assert client.get("/company", headers=world["emp"]).json()["photo_enabled"] is False
