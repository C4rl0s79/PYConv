"""EncodeJob dataclass – describes a single file to be processed."""
from dataclasses import dataclass, field
from pathlib import Path
from .enums import JobStatus
from .media_info import MediaInfo


@dataclass
class EncodeJob:
    """One unit of work in the pipeline (one source file)."""
    # Identity
    index: int = 0
    source_path: str = ""       # local path OR copyparty URL
    source_url: str = ""        # copyparty URL (network mode)
    dir_url: str = ""           # copyparty directory URL
    filename: str = ""

    # Media info (filled after probe)
    media_info: MediaInfo | None = None

    # Encode settings
    encoder: str = "av1_nvenc"
    cq: int = 32
    gpu_label: str = "GPU1"     # "GPU1" | "GPU2"
    gpu_index: int = 0

    # Pipeline flags
    selected: bool = True
    skip_hdr: bool = False
    skip_av1: bool = False
    skip_hevc: bool = False
    keep_orig: bool = False
    test_mode: bool = False
    hq_mode: bool = False
    vmaf_enabled: bool = False
    vmaf_target: float = 93.0
    min_save_pct: int = 10
    anime_mode: bool = False

    # Runtime state
    status: JobStatus = JobStatus.PENDING
    savings_pct: float = 0.0
    error_msg: str = ""
    output_path: str = ""       # local temp output path
    output_size: int = 0

    @property
    def display_name(self) -> str:
        return self.filename or Path(self.source_path).name
