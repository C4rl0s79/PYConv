# -*- coding: utf-8 -*-
"""File hashing and credential obfuscation helpers."""
from __future__ import annotations
import hashlib
import base64
import os


def sha256_file(path: str, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    """Return hex SHA-256 digest of a file, reading in *chunk_bytes* chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_bytes), b""):
            h.update(chunk)
    return h.hexdigest()


def _machine_key() -> bytes:
    """Derive a per-machine 32-byte XOR key from hostname + username."""
    import socket

    raw = socket.gethostname() + os.environ.get("USERNAME", os.environ.get("USER", "u"))
    return hashlib.sha256(raw.encode()).digest()


def xor_encrypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encode_credential(value: str) -> str:
    """XOR-encrypt and base64-encode a credential string."""
    key = _machine_key()
    return base64.b64encode(xor_encrypt(value.encode("utf-8"), key)).decode()


def decode_credential(encoded: str) -> str:
    """Base64-decode and XOR-decrypt a credential string."""
    key = _machine_key()
    return xor_encrypt(base64.b64decode(encoded), key).decode("utf-8")
