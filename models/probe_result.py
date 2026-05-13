# -*- coding: utf-8 -*-
"""ProbeResult dataclass – wraps MediaInfo with probe status."""
from dataclasses import dataclass
from .media_info import MediaInfo
from .enums import ProbeStatus


@dataclass
class ProbeResult:
    status: ProbeStatus
    media: MediaInfo | None = None
    raw_stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.status == ProbeStatus.OK and self.media is not None
