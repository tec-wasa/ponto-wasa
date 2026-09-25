"""Fotos em bucket S3-compatível (moto simula o protocolo S3 de verdade, inclusive assinatura e criptografia no servidor)."""
import boto3
import pytest
from moto import mock_aws

from app import photos_check
from app.config import settings
from app.models import User
from app.services import photos
from app.services.punching import register_punch
from tests.test_api import past
from tests.test_photos import B64, JPEG, enable, punch

BUCKET = "ponto-fotos-teste"


@pytest.fixture(autouse=True)
def s3(monkeypatch, tmp_path):
    with mock_aws():
        monkeypatch.setattr(settings, "allow_missing_inpi", True)
        monkeypatch.setattr(settings, "photo_store", "s3")
        monkeypatch.setattr(settings, "s3_bucket", BUCKET)
        monkeypatch.setattr(settings, "s3_region", "sa-east-1")
        monkeypatch.setattr(settings, "s3_access_key_id", "teste")
        monkeypatch.setattr(settings, "s3_secret_access_key", "teste")
        monkeypatch.setattr(settings, "photo_dir", str(tmp_path / "nao-deve-usar"))
        photos._s3_client.cache_clear()
        client = boto3.client("s3", region_name="sa-east-1", aws_access_key_id="teste", aws_secret_access_key="teste")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "sa-east-1"})
        yield client
        photos._s3_client.cache_clear()


def objects(client):
    return client.list_objects_v2(Bucket=BUCKET).get("Contents", [])


def test_upload_view_and_purge_go_through_the_bucket(client, world, db, s3):
    enable(client, world)
    emp = db.get(User, world["ids"]["emp"])
    when = past(40, 15)
    p = register_punch(db, emp, kind="entrada", occurred_at=when, enforce_sequence=False)
    db.commit()
    assert client.post(f"/punches/{p.id}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 201

    (obj,) = objects(s3)
    assert obj["Key"].startswith("fotos/")
    assert s3.head_object(Bucket=BUCKET, Key=obj["Key"])["ServerSideEncryption"] == "AES256"  # camada do servidor
    raw = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
    assert JPEG not in raw and raw != JPEG  # camada da aplicação: o bucket nunca vê a foto pura

    img = client.get(f"/punches/{p.id}/photo", headers=world["hr"])
    assert img.status_code == 200 and img.content == JPEG

    month = when.strftime("%Y-%m")
    assert client.post(f"/closings/{month}", headers=world["hr"]).json()["photos_deleted"] == 1
    assert objects(s3) == []  # retenção: o fechamento apaga do bucket
    assert client.get(f"/punches/{p.id}/photo", headers=world["hr"]).status_code == 404


def test_missing_object_and_broken_bucket_never_break_the_punch(client, world, s3, monkeypatch):
    enable(client, world)
    pid = punch(client, world)
    assert client.post(f"/punches/{pid}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 201
    (obj,) = objects(s3)
    s3.delete_object(Bucket=BUCKET, Key=obj["Key"])  # sumiu do bucket por fora
    assert client.get(f"/punches/{pid}/photo", headers=world["hr"]).status_code == 404

    monkeypatch.setattr(settings, "s3_bucket", "bucket-que-nao-existe")
    assert client.post("/punches", headers=world["other"], json={}).status_code == 201  # a batida nunca depende do bucket
    other_pid = client.get("/punches", headers=world["other"]).json()[0]["id"]
    client.post("/auth/consent-photo", headers=world["other"])
    r = client.post(f"/punches/{other_pid}/photo", headers=world["other"], json={"image_base64": B64})
    assert r.status_code == 503 and "indisponível" in r.json()["detail"]  # erro limpo, nunca 500


def test_self_check_reports_ok_and_problems(s3, monkeypatch, capsys):
    assert photos_check.main() == 0 and "OK" in capsys.readouterr().out
    assert objects(s3) == []  # o objeto de teste é apagado
    monkeypatch.setattr(settings, "s3_bucket", "nao-existe")
    assert photos_check.main() == 1 and "PROBLEMA" in capsys.readouterr().out
    monkeypatch.setattr(settings, "s3_bucket", "")
    assert photos_check.main() == 1


def test_closing_survives_a_broken_bucket_and_the_next_closing_finishes_the_purge(client, world, db, s3, monkeypatch):
    enable(client, world)
    emp = db.get(User, world["ids"]["emp"])
    a, b = past(40, 15), past(75, 15)
    pa = register_punch(db, emp, kind="entrada", occurred_at=a, enforce_sequence=False)
    register_punch(db, emp, kind="entrada", occurred_at=b, enforce_sequence=False)
    db.commit()
    assert client.post(f"/punches/{pa.id}/photo", headers=world["emp"], json={"image_base64": B64}).status_code == 201

    monkeypatch.setattr(settings, "s3_bucket", "bucket-fora-do-ar")
    r = client.post(f"/closings/{a.strftime('%Y-%m')}", headers=world["hr"])
    assert r.status_code == 200 and r.json()["photos_deleted"] == 0  # o fechamento vale mesmo com o bucket fora
    assert len(objects(s3)) == 1  # a foto ainda está lá: será apagada na próxima varredura

    monkeypatch.setattr(settings, "s3_bucket", BUCKET)
    r = client.post(f"/closings/{b.strftime('%Y-%m')}", headers=world["hr"])
    assert r.status_code == 200 and r.json()["photos_deleted"] == 1
    assert objects(s3) == []
