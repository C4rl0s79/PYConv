"""FFprobeEngine – all ffprobe knowledge in one place."""
from __future__ import annotations
import json
import os
from pathlib import Path

from utils.subprocess_utils import run_cmd
from utils.logging_utils import get_logger
from config.constants import HDR_TRANSFERS, HDR_PRIMARIES
from models.media_info import MediaInfo
from models.probe_result import ProbeResult
from models.enums import ProbeStatus

log = get_logger("ffprobe")


class FFprobeEngine:
    """Wraps ffprobe calls; returns typed ProbeResult / MediaInfo objects."""

    TIMEOUT: int = 15

    def probe(self, path: str) -> ProbeResult:
        """Run ffprobe on *path* and return a ProbeResult."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ]
        stdout, stderr, rc = run_cmd(cmd, timeout=self.TIMEOUT)
        if rc == -1:
            return ProbeResult(status=ProbeStatus.TIMEOUT, error_msg="ffprobe timeout", error_rc=rc)
        if rc != 0:
            return ProbeResult(status=ProbeStatus.ERROR, error_msg=stderr or "ffprobe failed", error_rc=rc)
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ProbeResult(status=ProbeStatus.ERROR, error_msg="JSON decode error", error_rc=-4)

        media = self._parse(path, data)
        return ProbeResult(status=ProbeStatus.OK, media_info=media)

    # ── internal ─────────────────────────────────────────────────────────────

    def _parse(self, path: str, data: dict) -> MediaInfo:
        info = MediaInfo(
            path=path,
            size=os.path.getsize(path) if os.path.exists(path) else 0,
        )
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info.codec = stream.get("codec_name", "?")
                info.width = stream.get("width", 0)
                info.height = stream.get("height", 0)
                info.pix_fmt = stream.get("pix_fmt", "")
                info.bit_depth = self._bit_depth(stream, info.pix_fmt)
                info.fps = self._fps(stream)
                info.hdr = self._is_hdr(stream)
                if stream.get("codec_type") == "video":
                    try:
                        info.bitrate_kbps = int(stream.get("bit_rate", 0)) / 1000.0
                    except (ValueError, TypeError):
                        pass
                break
        fmt = data.get("format", {})
        try:
            info.duration = float(fmt.get("duration", 0))
        except (ValueError, TypeError):
            pass
        if not info.bitrate_kbps:
            try:
                info.bitrate_kbps = int(fmt.get("bit_rate", 0)) / 1000.0
            except (ValueError, TypeError):
                pass
        return info

    @staticmethod
    def _bit_depth(stream: dict, pix_fmt: str) -> int:
        try:
            bd = int(stream.get("bits_per_raw_sample") or 0)
        except (ValueError, TypeError):
            bd = 0
        if not bd:
            if "10" in pix_fmt:
                return 10
            if "12" in pix_fmt:
                return 12
            return 8
        return bd

    @staticmethod
    def _fps(stream: dict) -> float:
        for key in ("r_frame_rate", "avg_frame_rate"):
            rf = stream.get(key, "")
            if rf and "/" in rf:
                try:
                    n, d = rf.split("/")
                    n, d = float(n), float(d)
                    if d > 0:
                        return n / d
                except ValueError:
                    pass
        return 0.0

    @staticmethod
    def _is_hdr(stream: dict) -> bool:
        ct = stream.get("color_transfer", "")
        cp = stream.get("color_primaries", "")
        cs = stream.get("color_space", "")
        if ct in HDR_TRANSFERS or cp in HDR_PRIMARIES or "bt2020" in cs:
            return True
        for sd in stream.get("side_data_list", []):
            st = sd.get("side_data_type", "")
            if any(x in st for x in ("HDR", "Dolby", "SMPTE")):
                return True
        return False
