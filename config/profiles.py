# -*- coding: utf-8 -*-
"""
Encoder CQ/GQ tables and QSV quality profiles.

All values are empirically tuned to hit VMAF ~93–95 at typical
stream bitrates for each encoder/resolution combination.
"""
from typing import Dict

# ── Per-encoder CQ base tables ────────────────────────────────────────────────
# Key: encoder id, Value: {resolution_threshold: cq_value}
# Resolution thresholds are lower bounds; the highest matching key is used.
CQ_BASE: Dict[str, Dict[int, int]] = {
    # NVIDIA NVENC – -rc vbr -cq N (scale 0–51, lower = higher quality)
    # av1_nvenc: -spatial-aq -temporal-aq -aq-strength 8 -rc-lookahead 32
    "av1_nvenc":  {2160: 38, 1440: 36, 1080: 34, 720: 32, 0: 30},
    # hevc_nvenc: -bf 4 -b_ref_mode middle -spatial-aq -temporal-aq
    "hevc_nvenc": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},

    # Intel QSV – ICQ -global_quality N (scale 1–51, lower = higher quality)
    # IMPORTANT: av1_qsv and hevc_qsv scales are DIFFERENT – do not compare!
    # av1_qsv: -bf 7 -extbrc 1 -look_ahead 1 -look_ahead_depth 40
    # Gradient: ~1.2 VMAF pts/GQ unit (Punisher S01, 1080p H.264 source)
    "av1_qsv":   {2160: 20, 1440: 18, 1080: 16, 720: 14, 0: 12},
    # hevc_qsv: -bf 8 -b_strategy 1 -refs 4 -extbrc 1 -look_ahead 1 -look_ahead_depth 40
    # Working range: GQ 18–22 for 1080p. GQ<18 = file grows above source.
    "hevc_qsv":  {2160: 25, 1440: 23, 1080: 21, 720: 19, 0: 18},

    # AMD AMF – -rc qvbr -qvbr_quality_level N (scale 0–51)
    "av1_amf":   {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "hevc_amf":  {2160: 26, 1440: 24, 1080: 22, 720: 20, 0: 18},

    # CPU software encoders – -crf N
    "libx265":     {2160: 24, 1440: 22, 1080: 20, 720: 18, 0: 16},
    "libaom-av1":  {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "libsvtav1":   {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
}

# Maximum allowed CQ per encoder (API range limits)
CQ_MAX: Dict[str, int] = {
    "av1_nvenc": 51, "hevc_nvenc": 51,
    "av1_qsv": 51,   "hevc_qsv": 51,
    "av1_amf": 51,   "hevc_amf": 51,
    "libx265": 51,   "libaom-av1": 63, "libsvtav1": 63,
}

# ── QSV quality profiles (GUI-selectable) ─────────────────────────────────────
# Two named profiles per QSV encoder, chosen from the GUI.
# Data from VMAF test: GQ=22→VMAF=81.9, GQ=24→VMAF=84.3 (Punisher S01, 1080p)
# Gradient ~1.2 pts VMAF/GQ unit → GQ=12 ≈ VMAF≈94–95
QSV_PROFILES: Dict[str, Dict[str, Dict[int, int]]] = {
    # Balanced: ~30–40 % savings, slightly lower VMAF
    "balanced": {
        "av1_qsv":  {2160: 22, 1440: 20, 1080: 18, 720: 16, 0: 14},
        "hevc_qsv": {2160: 24, 1440: 23, 1080: 22, 720: 20, 0: 18},
    },
    # Quality-first: ~15–25 % savings, VMAF ~93–95
    "quality": {
        "av1_qsv":  {2160: 16, 1440: 14, 1080: 12, 720: 10, 0: 8},
        "hevc_qsv": {2160: 23, 1440: 22, 1080: 21, 720: 19, 0: 18},
    },
}

DEFAULT_QSV_PROFILE: str = "quality"

# ── Anime mode minimum GQ floor ───────────────────────────────────────────────
# Animation has static backgrounds and low detail — a higher GQ floor
# avoids wasting bits while still delivering good VMAF.
ANIME_MIN_GQ: Dict[str, int] = {
    "av1_qsv": 14,
    "hevc_qsv": 18,
    "av1_nvenc": 32,
    "hevc_nvenc": 24,
}
