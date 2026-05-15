"""Output file validation helpers."""

from __future__ import annotations
import os
from pyconv.utils.subprocess_utils import run_cmd


def validate_output(path: str, min_size: int = 1024 * 1024) -> bool:
    """Return True if *path* is a valid, non-trivial video file."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < min_size:
        return False
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1",
        path,
    ]
    _, _, rc = run_cmd(cmd, timeout=15)
    return rc == 0

