"""EncodeJob and EncodeResult dataclasses — replace queue tuple packing."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from .enums import JobStatus, EncoderType


@dataclass
class EncodeJob:
    """Represents a single video encode task through the pipeline."""

    job_id: str
    source_path: Path  # oryginalne źródło (sieć lub local)
    temp_input: Path  # lokalny plik roboczy pobrany do tmp
    temp_output: Path  # lokalny plik po enkodzie w tmp
    dest_dir_url: str  # Copyparty destination directory URL
    dest_filename: str  # docelowa nazwa pliku (stem + .mkv)
    encoder: EncoderType
    cq: int
    source_size: int = 0
    duration: float = 0.0
    status: JobStatus = JobStatus.PENDING
    retry_count: int = 0
    savings_pct: float = 0.0
    vmaf_score: Optional[float] = None
    used_encoder: Optional[EncoderType] = None  # po fallbacku
    extra: dict = field(default_factory=dict)

    @property
    def dest_url(self) -> str:
        return self.dest_dir_url.rstrip("/") + "/" + self.dest_filename


@dataclass
class EncodeResult:
    """Outcome of a single encode attempt (single encoder + forceswdec)."""

    success: bool
    used_encoder: Optional[EncoderType] = None
    output_size: int = 0
    savings_pct: float = 0.0
    vmaf_score: Optional[float] = None
    error: Optional[str] = None
    used_repair: Optional[str] = None  # annexb / fourcc wariant
