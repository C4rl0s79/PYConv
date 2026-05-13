"""MediaInfo dataclass – raw ffprobe results for a single file."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MediaInfo:
    """Stores all media metadata extracted by ffprobe."""
    path: str
    size: int = 0
    codec: str = "?"
    width: int = 0
    height: int = 0
    pix_fmt: str = ""
    duration: float = 0.0
    fps: float = 0.0
    bit_depth: int = 8
    bitrate_kbps: float = 0.0
    hdr: bool = False

    # Human-friendly helpers
    @property
    def resolution_label(self) -> str:
        if self.height >= 2160:
            return "4K"
        if self.height >= 1440:
            return "1440p"
        if self.height >= 1080:
            return "1080p"
        if self.height >= 720:
            return "720p"
        return f"{self.height}p" if self.height else "?"

    @property
    def size_gb(self) -> float:
        return self.size / (1024 ** 3)

    @property
    def filename(self) -> str:
        return Path(self.path).name

    @classmethod
    def from_probe_dict(cls, d: dict) -> "MediaInfo":
        """Construct from legacy probe_file() dict."""
        return cls(
            path=d.get("path", ""),
            size=d.get("size", 0),
            codec=d.get("codec", "?"),
            width=d.get("width", 0),
            height=d.get("height", 0),
            pix_fmt=d.get("pix_fmt", ""),
            duration=d.get("duration", 0.0),
            fps=d.get("fps", 0.0),
            bit_depth=d.get("bit_depth", 8),
            bitrate_kbps=d.get("bitrate_kbps", 0.0),
            hdr=d.get("hdr", False),
        )
