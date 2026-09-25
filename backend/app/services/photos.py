"""Fotos opcionais das batidas: conferência humana pelo RH, apagadas no fechamento do mês.

- A foto NÃO entra no hash da marcação nem no AFD: a marcação vale sem ela e nunca é bloqueada por causa dela.
- Guardada criptografada (Fernet). O armazenamento é uma interface pequena (`put/get/delete`): hoje uma pasta local;
  na nuvem basta trocar `store()` por um bucket (S3, Azure Blob, GCS) mantendo a criptografia no lado da aplicação.
- Só JPEG, até `photo_max_bytes`. Sem reconhecimento facial: a foto é evidência para uma pessoa olhar.
"""
import base64
import hashlib
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Closing, Punch, PunchPhoto


class PhotoError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class PhotoStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


def _fernet() -> Fernet:
    material = (settings.totp_key or settings.secret_key).encode() + b"|ponto-photo"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


class LocalEncryptedStore:
    """Uma pasta local; cada arquivo é criptografado. Serve para testes e para um servidor único."""

    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise PhotoError(400, "Chave de armazenamento inválida")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_fernet().encrypt(data))

    def get(self, key: str) -> bytes:
        try:
            return _fernet().decrypt(self._path(key).read_bytes())
        except (FileNotFoundError, InvalidToken):
            raise PhotoError(404, "Foto não encontrada") from None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3EncryptedStore:
    """Bucket S3-compatível (privado). A foto já vai criptografada pela aplicação (Fernet); `ServerSideEncryption` é uma
    segunda camada, opcional. Nenhuma URL pública: a leitura passa sempre pela API, que confere quem pode ver."""

    def __init__(self, client, bucket: str, prefix: str, sse: str):
        self.client, self.bucket, self.prefix, self.sse = client, bucket, prefix, sse

    def _key(self, key: str) -> str:
        if ".." in key.split("/"):
            raise PhotoError(400, "Chave de armazenamento inválida")
        return f"{self.prefix}{key}"

    def put(self, key: str, data: bytes) -> None:
        extra = {"ServerSideEncryption": self.sse} if self.sse else {}
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=_fernet().encrypt(data),
                                   ContentType="application/octet-stream", **extra)
        except Exception as e:  # noqa: BLE001 (falha do provedor vira erro de armazenamento, sem vazar credenciais)
            raise PhotoError(503, f"Armazenamento de fotos indisponível ({type(e).__name__})") from None

    def get(self, key: str) -> bytes:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
            return _fernet().decrypt(body)
        except InvalidToken:
            raise PhotoError(404, "Foto não encontrada") from None
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise PhotoError(404, "Foto não encontrada") from None
            raise PhotoError(503, f"Armazenamento de fotos indisponível ({type(e).__name__})") from None

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))  # idempotente
        except Exception as e:  # noqa: BLE001
            raise PhotoError(503, f"Não foi possível apagar a foto ({type(e).__name__})") from None


@lru_cache(maxsize=4)
def _s3_client(endpoint: str, region: str, key_id: str, secret: str, path_style: bool):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=endpoint or None, region_name=region or None,
        aws_access_key_id=key_id or None, aws_secret_access_key=secret or None,
        config=Config(s3={"addressing_style": "path" if path_style else "auto"}, retries={"max_attempts": 3, "mode": "standard"},
                      connect_timeout=5, read_timeout=15),
    )


def store() -> PhotoStore:
    if settings.photo_store == "s3":
        if not settings.s3_bucket:
            raise PhotoError(503, "Armazenamento S3 sem bucket configurado (PONTO_S3_BUCKET)")
        client = _s3_client(settings.s3_endpoint_url, settings.s3_region, settings.s3_access_key_id,
                            settings.s3_secret_access_key, settings.s3_path_style)
        return S3EncryptedStore(client, settings.s3_bucket, settings.s3_prefix, settings.s3_sse)
    return LocalEncryptedStore(settings.photo_dir)


def self_test() -> list[str]:
    """Grava, lê e apaga um objeto de teste. Devolve os problemas (lista vazia = configuração boa)."""
    problems: list[str] = []
    key = f"_teste/{uuid.uuid4().hex}.bin"
    payload = b"ponto-self-test"
    try:
        backend = store()
        backend.put(key, payload)
        if backend.get(key) != payload:
            problems.append("O objeto lido não é igual ao gravado")
        backend.delete(key)
    except PhotoError as e:
        problems.append(e.message)
    return problems


def decode_jpeg(image_base64: str) -> bytes:
    try:
        data = base64.b64decode(image_base64.split(",", 1)[-1], validate=True)
    except ValueError:
        raise PhotoError(422, "Imagem inválida") from None
    if not data.startswith(b"\xff\xd8\xff"):
        raise PhotoError(422, "A foto deve ser JPEG")
    if len(data) > settings.photo_max_bytes:
        raise PhotoError(413, f"Foto grande demais (máximo {settings.photo_max_bytes // 1000} KB)")
    return data


def exists(db: Session, punch: Punch) -> bool:
    return db.execute(select(PunchPhoto.id).where(PunchPhoto.punch_id == punch.id)).first() is not None


def save(db: Session, punch: Punch, month: str, data: bytes) -> PunchPhoto:
    if db.execute(select(PunchPhoto.id).where(PunchPhoto.punch_id == punch.id)).first():
        raise PhotoError(409, "Esta batida já tem foto")
    key = f"{punch.company_id}/{month}/{uuid.uuid4().hex}.jpg.enc"
    store().put(key, data)
    photo = PunchPhoto(company_id=punch.company_id, user_id=punch.user_id, punch_id=punch.id, month=month, storage_key=key,
                       sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    db.add(photo)
    db.flush()
    return photo


def purge_closed(db: Session, company_id: int) -> tuple[int, int]:
    """Retenção: apaga as fotos de todo mês FECHADO (arquivo e registro). Se o armazenamento falhar para alguma foto, o
    registro dela é mantido e a próxima varredura (a cada fechamento) tenta de novo. Devolve (apagadas, pendentes)."""
    rows = db.execute(
        select(PunchPhoto).join(Closing, (Closing.company_id == PunchPhoto.company_id) & (Closing.month == PunchPhoto.month))
        .where(PunchPhoto.company_id == company_id, Closing.status == "closed")
    ).scalars().all()
    deleted = failed = 0
    backend = store()
    for p in rows:
        try:
            backend.delete(p.storage_key)
        except PhotoError:
            failed += 1
            continue
        db.delete(p)
        deleted += 1
    return deleted, failed
