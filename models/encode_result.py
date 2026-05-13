# -*- coding: utf-8 -*-
"""EncodeResult and UploadResult dataclasses."""
from dataclasses import dataclass
from .enums import UploadStatus


@dataclass
class EncodeResult:
    """Result of a single ffmpeg encode pass."""

    success: bool
    output_path: str = ""
    encoder_used: str = ""
    cq_used: int = 0
    vmaf: float = -1.0
    savings_pct: float = 0.0
    duration_s: float = 0.0
    stderr_tail: str = ""
    error_msg: str = ""
    used_fallback: bool = False
    repair_mode: str = "none"


@dataclass
class UploadResult:
    """Result of a single upload attempt."""

    status: UploadStatus
    remote_path: str = ""
    local_size: int = 0
    remote_size: int = 0
    error_msg: str = ""

    @property
    def size_verified(self) -> bool:
        return (
            self.status == UploadStatus.VERIFIED
            and self.local_size > 0
            and self.local_size == self.remote_size
        )


@dataclass
class GPUInfo:
    """GPU device descriptor."""

    index: int
    label: str            # 'GPU1' / 'GPU2'
    encoder: str          # e.g. 'av1_nvenc'
    cq: int
    enabled: bool = True
    download_lock_id: int = 0  # unique per-GPU download lock id
