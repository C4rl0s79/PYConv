# -*- coding: utf-8 -*-
"""Project-wide constants."""
from pathlib import Path

# ── File handling ────────────────────────────────────────────────────────────
SUPPORTED_EXTS: frozenset[str] = frozenset(
    {".mkv", ".avi", ".mp4", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg"}
)

TMP_SUFFIX = "_converting_tmp"

# ── Disk space thresholds (GB) ───────────────────────────────────────────────
SAFE_FREE_GB: float = 150.0
WARN_FREE_GB: float = 80.0

# ── HDR detection metadata values ───────────────────────────────────────────
HDR_TRANSFERS: frozenset[str] = frozenset({"smpte2084", "arib-std-b67", "smpte428"})
HDR_PRIMARIES: frozenset[str] = frozenset({"bt2020"})

# ── Network / HTTP ───────────────────────────────────────────────────────────
DOWNLOAD_CHUNK_BYTES: int = 4 * 1024 * 1024   # 4 MB
UPLOAD_CHUNK_BYTES: int = 4 * 1024 * 1024     # 4 MB
STALL_TIMEOUT_S: int = 120                     # seconds without progress → abort
SOCKET_TIMEOUT_S: int = 30                     # per-read socket timeout
CONNECT_TIMEOUT_S: int = 60                    # urllib connect timeout

# ── ffprobe / ffmpeg timeouts (seconds) ─────────────────────────────────────
PROBE_TIMEOUT_S: int = 15
CUT_TIMEOUT_S: int = 60
PROBE_ENCODE_TIMEOUT_S: int = 180

# ── VMAF ─────────────────────────────────────────────────────────────────────
VMAF_SAMPLE_SECS: int = 30
VMAF_BINARY_SEARCH_ITERS: int = 8

# ── Source codec BPP normalisation factors ───────────────────────────────────
# Efficiency of each codec relative to H.264 @ same perceptual quality.
# H.264 baseline = 1.00; higher value means codec is more efficient
# (same perceived quality at lower bitrate → "equivalent" bitrate is higher).
SRC_CODEC_FACTOR: dict[str, float] = {
    "h264": 1.00, "avc": 1.00, "mpeg4": 0.85,
    "mpeg2video": 0.55, "mpeg1video": 0.45,
    "vc1": 0.95, "wmv3": 0.85, "vp8": 1.00,
    "hevc": 1.65, "h265": 1.65, "vp9": 1.55,
    "av1": 2.00,
}

# ── Session file ─────────────────────────────────────────────────────────────
SESSION_FILE: Path = Path(__file__).parent.parent / "conver_session.json"

# ── Credentials file ─────────────────────────────────────────────────────────
CREDS_FILE: Path = Path.home() / ".converv_creds"

# ── HTTP User-Agent ──────────────────────────────────────────────────────────
HTTP_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)
