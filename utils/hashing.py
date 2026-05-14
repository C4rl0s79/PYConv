"""SHA-256 i operacje na plikach — sha256file() + rmsilent() z monolitu."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Union

_CHUNK = 8 * 1024 * 1024  # 8 MB chunks — dobre dla 100 GB


def sha256_file(path: Union[str, Path]) -> str:
    """Zwraca hex SHA-256 pliku (8 MB chunks)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def rm_silent(path: Union[str, Path, None]) -> None:
    """Usuwa plik bez wyjątku — rmsilent() z monolitu."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
