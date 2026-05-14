"""ProbeParser — parsuje ffprobe JSON → MediaInfo.

Wyodrębniony z probefile() w monolicie.
Zachowana pełna logika: HDR detect, bit-depth, FPS r/avg fallback.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Optional

from ..utils.subprocess_utils import run_cmd, NOWINDOW
from ..models.media_info import MediaInfo, ProbeResult
from ..models.enums import ProbeStatus
from ..utils.logging_utils import get_logger

logger = get_logger(__name__)

_HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}
_HDR_PRIMARIES = {"bt2020"}


class ProbeParser:
    def __init__(self, ffprobe_bin: str = "ffprobe"):
        self.ffprobe_bin = ffprobe_bin

    def probe(self, path: Path) -> ProbeResult:
        """probefile() z monolitu — 1:1 logika, typ zwracany ProbeResult."""
        cmd = [
            self.ffprobe_bin, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(path),
        ]
        stdout, stderr, rc = run_cmd(cmd, timeout=15)
        if rc != 0:
            return ProbeResult(
                status=ProbeStatus.UNREADABLE,
                error=f"ffprobe rc={rc}: {stderr[:200]}",
            )
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ProbeResult(status=ProbeStatus.UNREADABLE, error="JSON decode error")

        info = self._parse(data, path)
        return ProbeResult(status=ProbeStatus.OK, media_info=info, raw=data)

    def _parse(self, data: dict, path: Path) -> MediaInfo:
        size = path.stat().st_size if path.exists() else 0
        hdr = False
        codec = "?"
        width = height = 0
        pix_fmt = ""
        bitdepth = 8
        fps = 0.0
        duration = 0.0
        bitrate_kbps = 0.0
        audio_codec = ""

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                codec = stream.get("codec_name", "?")
                width = stream.get("width", 0)
                height = stream.get("height", 0)
                pix_fmt = stream.get("pix_fmt", "")
                try:
                    bitdepth = int(stream.get("bits_per_raw_sample") or 0) or bitdepth
                except (ValueError, TypeError):
                    pass
                if bitdepth == 8 and "10" in pix_fmt:
                    bitdepth = 10
                elif bitdepth == 8 and "12" in pix_fmt:
                    bitdepth = 12

                # FPS: prefer r_frame_rate, fallback avg_frame_rate
                for key in ("r_frame_rate", "avg_frame_rate"):
                    rf = stream.get(key, "")
                    if rf and "/" in rf:
                        try:
                            n, d = rf.split("/")
                            n, d = float(n), float(d)
                            if d > 0:
                                fps = n / d
                                break
                        except ValueError:
                            pass

                # HDR detection
                ct = stream.get("color_transfer", "")
                cp = stream.get("color_primaries", "")
                cs = stream.get("color_space", "")
                if ct in _HDR_TRANSFERS or cp in _HDR_PRIMARIES or "bt2020" in cs:
                    hdr = True
                for sd in stream.get("side_data_list", []):
                    st = sd.get("side_data_type", "")
                    if any(x in st for x in ("HDR", "Dolby", "SMPTE")):
                        hdr = True
                        break

                # Per-stream bitrate
                try:
                    bitrate_kbps = int(stream.get("bit_rate", 0)) / 1000.0
                except (ValueError, TypeError):
                    pass

            elif stream.get("codec_type") == "audio":
                audio_codec = stream.get("codec_name", "")

        fmt = data.get("format", {})
        try:
            duration = float(fmt.get("duration", 0))
        except (ValueError, TypeError):
            pass
        if not bitrate_kbps:
            try:
                bitrate_kbps = int(fmt.get("bit_rate", 0)) / 1000.0
            except (ValueError, TypeError):
                pass

        container = fmt.get("format_name", "")

        return MediaInfo(
            path=path,
            size_bytes=size,
            duration_seconds=duration,
            video_codec=codec,
            width=width,
            height=height,
            fps=fps,
            bitrate_kbps=bitrate_kbps,
            bitdepth=bitdepth,
            hdr=hdr,
            pix_fmt=pix_fmt,
            audio_codec=audio_codec,
            container=container,
        )
