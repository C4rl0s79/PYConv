# -*- coding: utf-8 -*-
"""MediaInfo dataclass – result of ffprobe analysis."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MediaInfo:
    """Parsed video stream metadata from ffprobe."""

    path: str
    size: int = 0
    codec: str = "?"
    width: int = 0
    height: int = 0
    pix_fmt: str = ""
    bit_depth: int = 8
    duration: float = 0.0
    fps: float = 0.0
    bitrate_kbps: float = 0.0
    hdr: bool = False

    # Raw ffprobe error fields (populated when probe fails)
    error_rc: int = 0
    error_msg: str = ""

    @property
    def is_error(self) -> bool:
        return self.error_rc != 0

    @property
    def resolution_label(self) -> str:
        """Human-readable resolution string, e.g. '1920x1080'."""
        return f"{self.width}x{self.height}" if self.width else "?"

    @property
    def size_gb(self) -> float:
        return self.size / (1024 ** 3)

    @classmethod
    def from_probe_dict(cls, d: dict) -> "MediaInfo":
        """Convert legacy probe_file() dict to MediaInfo."""
        return cls(
            path=d.get("path", ""),
            size=d.get("size", 0),
            codec=d.get("codec", "?"),
            width=d.get("width", 0),
            height=d.get("height", 0),
            pix_fmt=d.get("pix_fmt", ""),
            bit_depth=d.get("bit_depth", 8),
            duration=d.get("duration", 0.0),
            fps=d.get("fps", 0.0),
            bitrate_kbps=d.get("bitrate_kbps", 0.0),
            hdr=d.get("hdr", False),
            error_rc=d.get("_error_rc", 0),
            error_msg=d.get("_error_msg", ""),
        )
