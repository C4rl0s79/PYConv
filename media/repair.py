"""RepairChain – orchestrates the full fallback repair sequence.

Original fallback order (preserved 1:1):
  encoder_primary → encoder_sw_fallback → encoder_alt_sw → cpu_encoder
  → annexb_repair → retry_full_chain
  → fourcc_v1 → fourcc_v2 → fourcc_v3 → retry_full_chain

This module does NOT change the logic; it only names and isolates it.
"""

from __future__ import annotations
import os

from utils.logging_utils import get_logger
from .ffmpeg import FFmpegEngine

log = get_logger("repair")


class RepairChain:
    """Wraps the multi-stage repair/fallback logic for broken source files."""

    def __init__(self, ffmpeg: FFmpegEngine) -> None:
        self.ffmpeg = ffmpeg

    def try_annexb(self, src: str, tmp_dir: str, stem: str, gpu_label: str) -> str | None:
        """Try Annex B → AVCC remux. Returns repaired path or None."""
        log.info("[%s] Attempting AnnexB repair on: %s", gpu_label, os.path.basename(src))
        fixed = self.ffmpeg.repair_annexb(src, tmp_dir, stem, gpu_label)
        if fixed:
            log.info("[%s] AnnexB repair OK → %s", gpu_label, os.path.basename(fixed))
        else:
            log.warning("[%s] AnnexB repair FAILED", gpu_label)
        return fixed

    def try_fourcc(self, src: str, tmp_dir: str, stem: str, gpu_label: str) -> str | None:
        """Try AVI FOURCC repair (variants 1, 2, 3). Returns repaired path or None."""
        for variant in (1, 2, 3):
            log.info("[%s] FOURCC repair variant %d: %s", gpu_label, variant, os.path.basename(src))
            fixed = self.ffmpeg.repair_fourcc(src, tmp_dir, stem, variant)
            if fixed:
                log.info("[%s] FOURCC repair v%d OK → %s", gpu_label, variant, os.path.basename(fixed))
                return fixed
            log.warning("[%s] FOURCC repair v%d FAILED", gpu_label, variant)
        return None
