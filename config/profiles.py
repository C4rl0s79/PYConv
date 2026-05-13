"""CQ/GQ tables, QSV profiles and auto_cq() logic – all encoder quality knowledge here."""
from __future__ import annotations

# ── QSV quality profiles (selected in GUI) ────────────────────────────────────
# av1_qsv gradient: ~1.2 VMAF pts/GQ unit  (Punisher S01 test data)
# hevc_qsv working range: GQ 18–22  (GQ<18 → file grows; GQ>22 → −80% savings = overcompressed)
QSV_PROFILES: dict[str, dict[str, dict[int, int]]] = {
    "balanced": {
        "av1_qsv":  {2160: 22, 1440: 20, 1080: 18, 720: 16, 0: 14},
        "hevc_qsv": {2160: 24, 1440: 23, 1080: 22, 720: 20, 0: 18},
    },
    "quality": {
        "av1_qsv":  {2160: 16, 1440: 14, 1080: 12, 720: 10, 0: 8},
        "hevc_qsv": {2160: 23, 1440: 22, 1080: 21, 720: 19, 0: 18},
    },
}

# ── Base CQ per encoder × resolution ─────────────────────────────────────────
CQ_BASE: dict[str, dict[int, int]] = {
    # NVENC VBR mode (-rc vbr -cq N), scale 0–51
    "av1_nvenc":  {2160: 38, 1440: 36, 1080: 34, 720: 32, 0: 30},
    "hevc_nvenc": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    # QSV ICQ mode (-global_quality N), scale 1–51
    "av1_qsv":    {2160: 20, 1440: 18, 1080: 16, 720: 14, 0: 12},
    "hevc_qsv":   {2160: 25, 1440: 23, 1080: 21, 720: 19, 0: 18},
    # AMD QVBR mode (-rc qvbr -qvbr_quality_level N)
    "av1_amf":    {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "hevc_amf":   {2160: 26, 1440: 24, 1080: 22, 720: 20, 0: 18},
    # CPU CRF mode
    "libx265":    {2160: 24, 1440: 22, 1080: 20, 720: 18, 0: 16},
    "libaom-av1": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "libsvtav1":  {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
}

CQ_MAX: dict[str, int] = {
    "av1_nvenc": 51, "hevc_nvenc": 51,
    "av1_qsv": 51, "hevc_qsv": 51,
    "av1_amf": 51, "hevc_amf": 51,
    "libx265": 51, "libaom-av1": 63, "libsvtav1": 63,
}

# ── Source codec efficiency relative to H.264 ─────────────────────────────────
SRC_CODEC_FACTOR: dict[str, float] = {
    "h264": 1.00, "avc": 1.00, "mpeg4": 0.85,
    "mpeg2video": 0.55, "mpeg1video": 0.45,
    "vc1": 0.95, "wmv3": 0.85, "vp8": 1.00,
    "hevc": 1.65, "h265": 1.65, "vp9": 1.55,
    "av1": 2.00,
}


def encoder_family(encoder: str) -> str:
    """Map an encoder label to a CQ_BASE key."""
    if encoder in CQ_BASE:
        return encoder
    if "av1" in encoder and "nvenc" in encoder:
        return "av1_nvenc"
    if "av1" in encoder and "qsv" in encoder:
        return "av1_qsv"
    if "av1" in encoder and "amf" in encoder:
        return "av1_amf"
    if "nvenc" in encoder:
        return "hevc_nvenc"
    if "qsv" in encoder:
        return "hevc_qsv"
    if "amf" in encoder:
        return "hevc_amf"
    return "libx265"


def bpp(
    bitrate_kbps: float,
    width: int,
    height: int,
    fps: float,
) -> float:
    """Bits-per-pixel-per-frame: normalised bitrate density metric."""
    if bitrate_kbps > 0 and width > 0 and height > 0 and fps > 0:
        return (bitrate_kbps * 1000.0) / (width * height * fps)
    return 0.0


def auto_cq(
    encoder: str,
    height: int,
    orig_bitrate_kbps: float,
    width: int = 0,
    fps: float = 0.0,
    src_codec: str = "h264",
    qsv_profile: str = "quality",
    anime_mode: bool = False,
) -> int:
    """
    Select CQ/GQ value based on encoder, resolution, source BPP and codec.

    BPP adjustment thresholds (after normalisation to H.264 equivalent):
    - > 0.20  : lavish source, can compress harder  (CQ −4)
    - 0.12–0.20: excellent quality, compress lightly (CQ −2)
    - 0.08–0.12: standard                            (CQ ±0)
    - 0.05–0.08: already lean, be careful            (CQ +2)
    - < 0.05  : near artifact limit                  (CQ +4)
    """
    family = encoder_family(encoder)

    # QSV: use active quality profile
    if family in ("av1_qsv", "hevc_qsv") and qsv_profile in QSV_PROFILES:
        table = QSV_PROFILES[qsv_profile].get(family, CQ_BASE[family])
    else:
        table = CQ_BASE[family]

    base_cq = table[0]
    for h in sorted(table.keys(), reverse=True):
        if height >= h:
            base_cq = table[h]
            break

    src_factor = SRC_CODEC_FACTOR.get((src_codec or "h264").lower(), 1.0)
    adjustment = 0

    if width > 0 and fps > 0:
        bpp_raw = bpp(orig_bitrate_kbps, width, height, fps)
        bpp_eq = bpp_raw * src_factor
        if bpp_eq > 0.20:
            adjustment = -4
        elif bpp_eq > 0.12:
            adjustment = -2
        elif bpp_eq > 0.08:
            adjustment = 0
        elif bpp_eq > 0.05:
            adjustment = +2
        elif bpp_eq > 0.0:
            adjustment = +4
    elif orig_bitrate_kbps > 0:
        ref = {2160: 12000, 1440: 6000, 1080: 3000, 720: 1500, 0: 600}
        ref_b = ref[0]
        for h in sorted(ref.keys(), reverse=True):
            if height >= h:
                ref_b = ref[h]
                break
        ratio = (orig_bitrate_kbps * src_factor) / ref_b
        if ratio > 3.0:
            adjustment = -4
        elif ratio > 2.0:
            adjustment = -3
        elif ratio > 1.3:
            adjustment = -2
        elif ratio > 0.7:
            adjustment = 0
        elif ratio > 0.3:
            adjustment = +2
        else:
            adjustment = +4

    cq_max = CQ_MAX.get(family, 51)
    result = max(1, min(cq_max, base_cq + adjustment))

    if anime_mode:
        anime_min = {
            "av1_qsv": 14, "hevc_qsv": 18,
            "av1_nvenc": 32, "hevc_nvenc": 24,
        }.get(family, 0)
        if anime_min and result < anime_min:
            result = anime_min

    return result
