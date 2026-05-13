"""Thin compatibility shim – probe_file() returns legacy dict OR ProbeResult."""
from __future__ import annotations
import os
from .ffprobe import FFprobeEngine
from models.probe_result import ProbeResult

_engine = FFprobeEngine()


def probe_file(path: str) -> dict:
    """Legacy probe – returns dict compatible with original code."""
    result = _engine.probe(path)
    if not result.ok:
        return {"_error_rc": result.error_rc, "_error_msg": result.error_msg}
    m = result.media_info
    return {
        "path": m.path,
        "size": m.size,
        "hdr": m.hdr,
        "codec": m.codec,
        "width": m.width,
        "height": m.height,
        "pix_fmt": m.pix_fmt,
        "duration": m.duration,
        "fps": m.fps,
        "bit_depth": m.bit_depth,
        "bitrate_kbps": m.bitrate_kbps,
    }


def probe_file_result(path: str) -> ProbeResult:
    """New-style probe returning typed ProbeResult."""
    return _engine.probe(path)
