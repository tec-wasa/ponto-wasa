"""Confere o armazenamento das fotos (pasta local ou bucket S3): grava, lê e apaga um objeto de teste.

Uso: python -m app.photos_check   (sai com código 1 se algo estiver errado)
"""
import sys

from .config import settings
from .services import photos


def main() -> int:
    where = f"s3://{settings.s3_bucket}/{settings.s3_prefix}" if settings.photo_store == "s3" else settings.photo_dir
    problems = photos.self_test()
    if problems:
        print(f"PROBLEMA no armazenamento de fotos ({where}): " + "; ".join(problems))
        return 1
    print(f"OK: armazenamento de fotos funcionando ({where})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
