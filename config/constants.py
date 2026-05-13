"""Compile-time constants: colour palette, file extensions, thresholds."""
from pathlib import Path

# ── Colour palette ────────────────────────────────────────────────────────────
DARK_BG = "#0e1117"
PANEL_BG = "#161b22"
BORDER = "#30363d"
ACCENT = "#00d4aa"
ACCENT2 = "#f0b429"
TEXT_PRI = "#e6edf3"
TEXT_SEC = "#8b949e"
TEXT_MUTED = "#484f58"
RED = "#ff6b6b"
GREEN = "#3fb950"
YELLOW = "#d29922"
BLUE = "#388bfd"
HDR_COLOR = "#bf8700"
SKIP_COLOR = "#8b949e"
DONE_COLOR = "#3fb950"
ERROR_COLOR = "#ff6b6b"

# ── Media ──────────────────────────────────────────────────────────────────────
SUPPORTED_EXTS: frozenset[str] = frozenset({
    ".mkv", ".avi", ".mp4", ".mov", ".ts", ".m2ts",
    ".wmv", ".flv", ".mpg", ".mpeg",
})

ENCODER_OPTIONS: list[str] = [
    "av1_nvenc (NVIDIA AV1)",
    "hevc_nvenc (NVIDIA H.265)",
    "av1_qsv (Intel Arc AV1)",
    "hevc_qsv (Intel H.265)",
    "av1_amf (AMD AV1)",
    "hevc_amf (AMD H.265)",
    "libx265 (CPU H.265 – wolny)",
    "libaom-av1 (CPU AV1 – bardzo wolny)",
]

# ── HDR detection ─────────────────────────────────────────────────────────────
HDR_TRANSFERS: frozenset[str] = frozenset({"smpte2084", "arib-std-b67", "smpte428"})
HDR_PRIMARIES: frozenset[str] = frozenset({"bt2020"})

# ── Storage thresholds (GB) ───────────────────────────────────────────────────
SAFE_FREE_GB: int = 150
WARN_FREE_GB: int = 80

# ── Temp file suffix ──────────────────────────────────────────────────────────
TMP_SUFFIX: str = "_converting_tmp"
