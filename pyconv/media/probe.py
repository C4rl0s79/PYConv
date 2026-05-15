"""ProbeParser — parsuje ffprobe JSON → MediaInfo.

Wyodrębniony z probefile() w monolicie.
Zachowana pełna logika: HDR detect, bit-depth, FPS r/avg fallback.
"""

from __future__ import annotations
import json
from pathlib import Path

from ..utils.subprocess_utils import run_cmd
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
            self.ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
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
        subtitle_codecs = []

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
            elif stream.get("codec_type") == "subtitle":
                scodec = stream.get("codec_name")
                if scodec:
                    subtitle_codecs.append(scodec)

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
            subtitle_codecs=subtitle_codecs,
            container=container,
        )


def scan_dir(src: str) -> list[str]:
    import os

    exts = {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg"}
    res = []
    for root, _, files in os.walk(src):
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                res.append(os.path.join(root, f))
    return res


def probe_file(path: str) -> dict:
    parser = ProbeParser()
    res = parser.probe(Path(path))
    if not res.ok:
        return {"error_rc": -1, "error_msg": res.error or "Unknown error"}
    mi = res.media_info
    return {
        "codec": mi.video_codec,
        "width": mi.width,
        "height": mi.height,
        "size": mi.size_bytes,
        "hdr": mi.hdr,
        "duration": mi.duration_seconds,
        "fps": mi.fps,
        "bitrate_kbps": mi.bitrate_kbps,
        "pix_fmt": mi.pix_fmt,
        "bitdepth": mi.bitdepth,
        "path": path,
    }


def cp_probe_via_http(url: str, tmp_dir: str, password: str) -> dict:
    import json
    import urllib.parse

    if password:
        url += f"?pw={urllib.parse.quote(password)}"

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        url,
    ]
    stdout, stderr, rc = run_cmd(cmd, timeout=15)
    if rc != 0:
        return {"error_rc": rc, "error_msg": f"ffprobe rc={rc}: {stderr[:200]}"}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"error_rc": -1, "error_msg": "JSON decode error"}

    parser = ProbeParser()
    # Dummy Path since we just use it for name logic
    mi = parser._parse(data, Path("cp_http.mkv"))
    return {
        "codec": mi.video_codec,
        "width": mi.width,
        "height": mi.height,
        "size": 0,  # Size will be set by caller
        "hdr": mi.hdr,
        "duration": mi.duration_seconds,
        "fps": mi.fps,
        "bitrate_kbps": mi.bitrate_kbps,
        "pix_fmt": mi.pix_fmt,
        "bitdepth": mi.bitdepth,
    }
