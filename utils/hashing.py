"""File hashing and silent deletion helpers."""
import hashlib
import os


def sha256_file(path: str) -> str:
    """Return hex SHA-256 of a file, reading in 8 MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rm_silent(path: str) -> None:
    """Delete a file without raising an exception."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
