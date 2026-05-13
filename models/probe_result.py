"""ProbeResult dataclass – wrapper around ffprobe output with status."""
from dataclasses import dataclass, field
from .enums import ProbeStatus
from .media_info import MediaInfo


@dataclass
class ProbeResult:
    status: ProbeStatus = ProbeStatus.OK
    media_info: MediaInfo | None = None
    error_msg: str = ""
    error_rc: int = 0

    @property
    def ok(self) -> bool:
        return self.status == ProbeStatus.OK and self.media_info is not None

    @classmethod
    def from_probe_dict(cls, d: dict) -> "ProbeResult":
        """Construct from legacy probe_file() return dict."""
        if "_error_rc" in d:
            return cls(
                status=ProbeStatus.ERROR,
                error_msg=d.get("_error_msg", "ffprobe failed"),
                error_rc=d.get("_error_rc", -1),
            )
        return cls(
            status=ProbeStatus.OK,
            media_info=MediaInfo.from_probe_dict(d),
        )
