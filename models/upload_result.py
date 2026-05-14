"""UploadResult dataclass — replace cpuploadfile bool return with full context."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .enums import UploadStatus


@dataclass
class UploadResult:
    """Result of a Copyparty upload + verification sequence."""
    status: UploadStatus
    local_size: int = 0
    remote_size: int = 0
    local_sha256: str = ""
    remote_sha256: str = ""
    error: Optional[str] = None

    @property
    def size_verified(self) -> bool:
        """True gdy remote_size >= local_size * 0.99 (z monolitu)."""
        if self.local_size == 0:
            return False
        return self.remote_size >= self.local_size * 0.99

    @property
    def sha_verified(self) -> bool:
        """True gdy oba SHA-256 dostępne i zgodne."""
        if not self.local_sha256 or not self.remote_sha256:
            return False
        return self.local_sha256 == self.remote_sha256

    @property
    def ok(self) -> bool:
        return self.status == UploadStatus.VERIFIED
