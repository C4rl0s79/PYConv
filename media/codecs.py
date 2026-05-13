"""Encoder flag builders – returns the per-encoder ffmpeg flag lists.

All codec-specific knowledge (pixel formats, encoder flags, FPS args)
belongs here. FFmpegEngine uses these helpers to assemble command lines.
"""
from __future__ import annotations

# Standard FPS values for which we allow -r passthrough.
_STD_FPS = {24.0, 25.0, 30.0, 48.0, 50.0, 60.0,
            23.976, 29.97, 59.94}


def get_pixel_fmt(encoder: str, bit_depth: int) -> str:
    """Return correct -pix_fmt for encoder + source bit depth."""
    is_10bit = bit_depth >= 10
    if "nvenc" in encoder:
        return "p010le" if is_10bit else "yuv420p"
    if "qsv" in encoder:
        return "p010le" if is_10bit else "nv12"
    if "amf" in encoder:
        return "p010le" if is_10bit else "yuv420p"
    # CPU encoders
    return "yuv420p10le" if is_10bit else "yuv420p"


def get_fps_args(fps: float) -> list[str]:
    """Return -r fps_args only for standard FPS values."""
    for std in _STD_FPS:
        if abs(fps - std) < 0.01:
            return ["-r", f"{fps:.3f}"]
    return []


def get_encoder_flags(encoder: str, cq: int, height: int) -> list[str]:
    """Build the encoder-specific flag list (quality, rate-control, etc.)."""
    flags: list[str] = []
    tile = height >= 1440

    if encoder == "av1_nvenc":
        flags = [
            "-rc", "vbr", "-cq", str(cq),
            "-preset", "p6",
            "-spatial-aq", "1", "-temporal-aq", "1",
            "-aq-strength", "8",
            "-rc-lookahead", "32",
            "-b_ref_mode", "middle",
        ]
        if tile:
            flags += ["-tile-columns", "2", "-tile-rows", "1"]

    elif encoder == "hevc_nvenc":
        flags = [
            "-rc", "vbr", "-cq", str(cq),
            "-preset", "p6",
            "-bf", "4", "-b_ref_mode", "middle",
            "-spatial-aq", "1", "-temporal-aq", "1",
        ]

    elif encoder == "av1_qsv":
        flags = [
            "-global_quality", str(cq), "-b:v", "0",
            "-preset", "slow",
            "-extbrc", "1",
            "-look_ahead", "1", "-look_ahead_depth", "40",
            "-bf", "7",
            "-max_frame_size", "0",
        ]

    elif encoder == "hevc_qsv":
        flags = [
            "-global_quality", str(cq), "-b:v", "0",
            "-preset", "slow",
            "-extbrc", "1",
            "-look_ahead", "1", "-look_ahead_depth", "40",
            "-bf", "8", "-b_strategy", "1", "-refs", "4",
            "-max_frame_size", "0",
        ]

    elif encoder in ("av1_amf", "hevc_amf"):
        flags = [
            "-rc", "qvbr", "-qvbr_quality_level", str(cq),
            "-quality", "quality",
        ]

    elif encoder == "libx265":
        flags = [
            "-crf", str(cq),
            "-preset", "slow",
            "-x265-params",
            "aq-mode=3:aq-strength=1.0:rd=4:psy-rd=2.0",
        ]

    elif encoder in ("libaom-av1", "libsvtav1"):
        flags = ["-crf", str(cq), "-b:v", "0"]
        if encoder == "libsvtav1":
            flags += ["-svtav1-params", "tune=0"]

    return flags
