"""EncodeResult, UploadResult, GPUInfo dataclasses."""
from dataclasses import dataclass, field
from .enums import UploadStatus


@dataclass
class EncodeResult:
    """Result of a single ffmpeg encode pass."""
    success: bool = False
    output_path: str = ""
    output_size: int = 0
    source_size: int = 0
    savings_pct: float = 0.0
    encoder_used: str = ""
    cq_used: int = 0
    vmaf_score: float = -1.0
    error_msg: str = ""
    stderr_tail: str = ""       # last N lines of ffmpeg stderr for diagnostics

    @property
    def size_ratio(self) -> float:
        if self.source_size > 0:
            return self.output_size / self.source_size
        return 1.0


@dataclass
class UploadResult:
    """Result of a Copyparty upload."""
    status: UploadStatus = UploadStatus.PENDING
    remote_size: int = 0
    local_size: int = 0
    verified: bool = False
    error_msg: str = ""
    dest_url: str = ""

    @property
    def ok(self) -> bool:
        return self.status == UploadStatus.DONE and self.verified


@dataclass
class GPUInfo:
    """Describes a single GPU worker slot."""
    index: int = 0
    label: str = "GPU1"
    encoder: str = "av1_nvenc"
    cq: int = 32
    download_lock_id: int = 0   # id() of the per-GPU download threading.Lock
    active: bool = True
