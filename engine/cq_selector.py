"""CQSelector — autocq(), complexityprobe(), hqcq_adjustment(), vmaf_target_search().

Wyodrębniony z monolitu. Zachowane 1:1:
  - CQBASE per encoder (QSV z QSVPROFILES)
  - SRCCODECFACTOR: h264=1.0, hevc=1.65, av1=2.0, mpeg2=0.55
  - BPP normalizacja do H.264-ekwiwalentu
  - Stara ścieżka: ratio vs ref bitrate gdy brak fps/width
  - Tryb Anime: minimalny GQ
  - complexityprobe: select=gt(scene,0.3) 20s ze środka
  - vmaf_target_search: binary-search 30s sample, lo=cqstart-8, hi=cqstart+10
"""
from __future__ import annotations

from pathlib import Path

from ..models.enums import EncoderType
from ..models.media_info import MediaInfo
from ..utils.filename import safe_filename
from ..utils.hashing import rm_silent
from ..utils.logging_utils import get_logger
from ..utils.subprocess_utils import run_cmd

logger = get_logger(__name__)

CQBASE: dict[str, dict[int, int]] = {
    "av1nvenc":  {2160: 38, 1440: 36, 1080: 34, 720: 32, 0: 30},
    "hevcnvenc": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "av1qsv":    {2160: 20, 1440: 18, 1080: 16, 720: 14, 0: 12},
    "hevcqsv":   {2160: 25, 1440: 23, 1080: 21, 720: 19, 0: 18},
    "av1amf":    {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "hevcamf":   {2160: 26, 1440: 24, 1080: 22, 720: 20, 0: 18},
    "libx265":   {2160: 24, 1440: 22, 1080: 20, 720: 18, 0: 16},
    "libsvtav1": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "libaom-av1":{2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
}
CQMAX: dict[str, int] = {
    "av1nvenc": 51, "hevcnvenc": 51,
    "av1qsv": 51, "hevcqsv": 51,
    "av1amf": 51, "hevcamf": 51,
    "libx265": 51, "libaom-av1": 63, "libsvtav1": 63,
}
SRCCODEC_FACTOR: dict[str, float] = {
    "h264": 1.00, "avc": 1.00, "mpeg4": 0.85,
    "mpeg2video": 0.55, "mpeg1video": 0.45,
    "vc1": 0.95, "wmv3": 0.85,
    "vp8": 1.00, "vp9": 1.55,
    "hevc": 1.65, "h265": 1.65,
    "av1": 2.00,
}
_ANIME_MIN: dict[str, int] = {
    "av1qsv": 14, "hevcqsv": 18,
    "av1nvenc": 32, "hevcnvenc": 24,
}
_REF_BITRATE: dict[int, int] = {
    2160: 12000, 1440: 6000,
    1080: 3000, 720: 1500, 0: 600,
}


class CQSelector:
    """Dobiera CQ / GQ na podstawie danych źródła."""

    def __init__(
        self,
        ffmpeg_engine=None,
        qsv_profile: str = "balanced",
        anime_mode: bool = False,
        qsv_profiles: dict | None = None,
    ):
        self.ffmpeg_engine = ffmpeg_engine
        self.qsv_profile = qsv_profile
        self.anime_mode = anime_mode
        self.qsv_profiles = qsv_profiles or {}

    def auto_cq(
        self,
        encoder: EncoderType,
        height: int,
        bitrate_kbps: float,
        width: int = 0,
        fps: float = 0.0,
        src_codec: str = "h264",
    ) -> int:
        family = encoder.value
        if family in ("av1qsv", "hevcqsv") and self.qsv_profile in self.qsv_profiles:
            table = self.qsv_profiles[self.qsv_profile].get(family, CQBASE[family])
        else:
            table = CQBASE.get(family, CQBASE["libx265"])

        base_cq = table[0]
        for h in sorted(table.keys(), reverse=True):
            if height >= h:
                base_cq = table[h]
                break

        src_factor = SRCCODEC_FACTOR.get(src_codec.lower(), 1.0)
        adjustment = 0

        if width > 0 and fps > 0.0:
            bpp_raw = (bitrate_kbps * 1000.0) / (width * height * fps) if bitrate_kbps > 0 else 0.0
            bpp_eq = bpp_raw * src_factor
            if bpp_eq > 0.20:
                adjustment = -4
            elif bpp_eq > 0.12:
                adjustment = -2
            elif bpp_eq > 0.08:
                adjustment = 0
            elif bpp_eq > 0.05:
                adjustment = 2
            elif bpp_eq > 0.0:
                adjustment = 4
        elif bitrate_kbps > 0:
            ref_b = _REF_BITRATE[0]
            for h in sorted(_REF_BITRATE.keys(), reverse=True):
                if height >= h:
                    ref_b = _REF_BITRATE[h]
                    break
            ratio = bitrate_kbps * src_factor / ref_b
            if ratio > 3.0:
                adjustment = -4
            elif ratio > 2.0:
                adjustment = -3
            elif ratio > 1.3:
                adjustment = -2
            elif ratio > 0.7:
                adjustment = 0
            elif ratio > 0.3:
                adjustment = 2
            else:
                adjustment = 4

        cq_max = CQMAX.get(family, 51)
        result = max(1, min(cq_max, base_cq + adjustment))

        if self.anime_mode:
            anime_min = _ANIME_MIN.get(family, 0)
            if anime_min and result < anime_min:
                result = anime_min

        return result

    def complexity_probe(self, path: Path, duration: float, sample_secs: int = 20) -> float:
        """complexityprobe(): scene change rate (0.0–1.0)."""
        if duration < sample_secs * 1.5:
            ss, t = 0, max(5, int(duration * 0.5))
        else:
            ss = max(0, int(duration / 2) - sample_secs // 2)
            t = sample_secs

        cmd = [
            "ffmpeg", "-v", "error",
            "-ss", str(ss), "-t", str(t),
            "-i", str(path),
            "-vf", r"select=gt(scene\,0.3),metadata=print:file=-",
            "-an", "-sn", "-f", "null", "-",
        ]
        stdout, stderr, rc = run_cmd(cmd)
        if rc != 0:
            return 0.0
        cuts = stdout.count("lavfi.scene_score") + stderr.count("lavfi.scene_score")
        return cuts / float(t) if t > 0 else 0.0

    @staticmethod
    def hq_cq_adjustment(complexity: float) -> int:
        if complexity > 0.8:
            return -3
        if complexity > 0.4:
            return -2
        if complexity > 0.15:
            return 0
        if complexity > 0.05:
            return 1
        return 2

    def vmaf_target_search(
        self,
        src: Path,
        encoder: EncoderType,
        cq_start: int,
        duration: float,
        target: float,
        job_id: str = "",
        tmpdir: Path | None = None,
        info: MediaInfo | None = None,
    ) -> int | None:
        if duration < 60:
            return None
        if not self.ffmpeg_engine:
            logger.warning(f"[{job_id}] vmaf_target_search: brak FFmpegEngine")
            return None

        sample_secs = 30
        ss = max(0, int(duration / 2) - sample_secs // 2)
        tdir = tmpdir or src.parent
        tdir.mkdir(parents=True, exist_ok=True)

        stem = safe_filename(src.stem, maxlen=40)
        sample_ref = tdir / f"vmafref_{job_id}_{stem}.mkv"

        cut_cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(ss), "-t", str(sample_secs),
            "-i", str(src),
            "-map", "0:v:0", "-an", "-sn", "-c:v", "copy",
            str(sample_ref),
        ]
        _, _, rc = run_cmd(cut_cmd, timeout=60)
        if rc != 0 or not sample_ref.exists():
            logger.warning(f"[{job_id}] VMAF: nie można wyciąć sampla")
            return None

        family = encoder.value
        cq_max = CQMAX.get(family, 51)
        lo = max(1, cq_start - 8)
        hi = min(cq_max, cq_start + 10)
        best_cq: int | None = None
        best_diff: float | None = None
        tried: dict[int, float] = {}

        def encode_and_score(cq_val: int) -> float:
            if cq_val in tried:
                return tried[cq_val]
            sample_enc = tdir / f"vmafenc_{job_id}_{stem}_{cq_val}.mkv"
            ok = self.ffmpeg_engine.vmaf_probe_encode(
                sample_ref, sample_enc, encoder, cq_val, job_id, info=info
            )
            if not ok:
                tried[cq_val] = -1.0
                return -1.0
            v = self.ffmpeg_engine.run_vmaf(sample_ref, sample_enc, sample_secs, job_id) or -1.0
            rm_silent(sample_enc)
            tried[cq_val] = v
            logger.info(f"[{job_id}] VMAF probe CQ={cq_val} → {v:.2f}")
            return v

        for _ in range(8):
            mid = (lo + hi) // 2
            score = encode_and_score(mid)
            if score < 0:
                hi = mid - 1
                continue
            diff = abs(score - target)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_cq = mid
            if diff <= 1.5:
                break
            if score < target:
                hi = mid - 1
            else:
                lo = mid + 1

        rm_silent(sample_ref)
        if best_cq is not None:
            logger.info(f"[{job_id}] VMAF target={target:.0f} → CQ={best_cq}")
        return best_cq
