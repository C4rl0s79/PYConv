"""MediaInfo and ProbeResult dataclasses — replace probefile() dict returns."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
from .enums import ProbeStatus


@dataclass
class MediaInfo:
    """Parsed metadata for a single video file (from ffprobe JSON)."""

    path: Path
    size_bytes: int
    duration_seconds: float
    video_codec: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate_kbps: float = 0.0
    bitdepth: int = 8
    hdr: bool = False
    pix_fmt: str = ""
    audio_codec: str = ""
    container: str = ""
    complexity: float = 0.0  # scene change rate z complexityprobe()
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024

    @property
    def is_10bit(self) -> bool:
        return self.bitdepth >= 10

    @property
    def resolution_label(self) -> str:
        if self.height >= 2160:
            return "2160p"
        elif self.height >= 1440:
            return "1440p"
        elif self.height >= 1080:
            return "1080p"
        elif self.height >= 720:
            return "720p"
        return f"{self.height}p"


@dataclass
class ProbeResult:
    """Result of ffprobe execution — wraps MediaInfo or error."""

    status: ProbeStatus
    media_info: Optional[MediaInfo] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None  # raw ffprobe JSON

    @property
    def ok(self) -> bool:
        return self.status == ProbeStatus.OK and self.media_info is not None
