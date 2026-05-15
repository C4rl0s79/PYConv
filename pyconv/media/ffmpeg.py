"""FFmpegEngine — cała wiedza o FFmpeg w jednym miejscu.

Wyodrębniony z monolitu ConverV4.12.py.
Zachowane 1:1:
  - fallback chain NVENC→QSV→AMF→CPU
  - repair AnnexB (2 warianty BSF)
  - repair FOURCC (3 warianty: remux / mpeg4 / libx264-lossless)
  - parametry QSV: bf=8, extbrc=1, lookaheaddepth=40
  - parametry NVENC: p6, spatial-aq, temporal-aq, bref=middle
  - 10-bit pixfmt logic
  - QSV FPS detection (tylko std FPS: 24/25/30/48/50/60)
  - subprocess.Popen z line-buffered stderr (live GUI logging)
  - NAL error detect / rawvideo error detect
  - timeout: probe=15s, repair=300s, encode bez limitu (wielogodzinne)
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional

from ..utils.subprocess_utils import ffmpeg_popen, iter_ffmpeg_lines, run_cmd, NOWINDOW
from ..utils.logging_utils import get_logger
from ..utils.filename import safe_filename
from ..utils.hashing import rm_silent
from ..models.enums import EncoderType
from ..models.job_info import EncodeResult
from ..models.media_info import MediaInfo

logger = get_logger(__name__)

# Tablice CQ/GQ z monolitu — zachowane 1:1
CQBASE: dict[str, dict[int, int]] = {
    "av1_nvenc": {2160: 38, 1440: 36, 1080: 34, 720: 32, 0: 30},
    "hevc_nvenc": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "av1_qsv": {2160: 20, 1440: 18, 1080: 16, 720: 14, 0: 12},
    "hevc_qsv": {2160: 25, 1440: 23, 1080: 21, 720: 19, 0: 18},
    "av1_amf": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "hevc_amf": {2160: 26, 1440: 24, 1080: 22, 720: 20, 0: 18},
    "libx265": {2160: 24, 1440: 22, 1080: 20, 720: 18, 0: 16},
    "libsvtav1": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
    "libaom-av1": {2160: 32, 1440: 30, 1080: 28, 720: 26, 0: 24},
}
CQMAX: dict[str, int] = {
    "av1_nvenc": 51,
    "hevc_nvenc": 51,
    "av1_qsv": 51,
    "hevc_qsv": 51,
    "av1_amf": 51,
    "hevc_amf": 51,
    "libx265": 51,
    "libaom-av1": 63,
    "libsvtav1": 63,
}

# Kody błędów z monolitu
_NAL_ERRORS = [
    "nal",
    "h264",
    "hevc",
    "invalid nalu",
    "error while decoding",
    "sps nal unit",
    "no frame!",
]
_RAWVIDEO_ERRORS = ["decrawvideo", "rawvideo"]

# Chains fallbacków z monolitu — zachowane 1:1
_FALLBACK_CHAINS: dict[str, list[tuple[str, bool]]] = {
    "av1_nvenc": [("av1_nvenc", False), ("av1_nvenc", True), ("av1_qsv", True), ("libsvtav1", False)],
    "av1_qsv": [("av1_qsv", False), ("av1_qsv", True), ("av1_nvenc", True), ("libsvtav1", False)],
    "hevc_nvenc": [("hevc_nvenc", False), ("hevc_nvenc", True), ("hevc_qsv", True), ("libx265", False)],
    "hevc_qsv": [("hevc_qsv", False), ("hevc_qsv", True), ("hevc_nvenc", True), ("libx265", False)],
    "av1_amf": [("av1_amf", False), ("av1_amf", True), ("av1_nvenc", True), ("libsvtav1", False)],
    "hevc_amf": [("hevc_amf", False), ("hevc_amf", True), ("hevc_nvenc", True), ("libx265", False)],
    "libsvtav1": [("libsvtav1", False)],
    "libx265": [("libx265", False)],
}


class FFmpegEngine:
    """Enkapsuluje wszystkie wywołania FFmpeg.

    GUI i Pipeline nigdy nie budują cmd[] samodzielnie.
    """

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        cancel_flag=None,  # threading.Event — opcjonalny
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.cancel_flag = cancel_flag
        self.log_callback = log_callback  # fn(message, level) dla GUI
        self._last_stderr: List[str] = []

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def run_encode_with_fallback(
        self,
        src: Path,
        dst: Path,
        encoder: EncoderType,
        cq: int,
        job_id: str,
        duration: float = 0.0,
        info: Optional[MediaInfo] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> EncodeResult:
        """runffmpegwithfallback() z monolitu — 1:1 logika.

        Próbuje każdy enkoder z _FALLBACK_CHAINS, po błędzie NAL
        uruchamia repair_annexb(), po rawvideo uruchamia repair_fourcc().
        """
        chain = _FALLBACK_CHAINS.get(encoder.value, [(encoder.value, False)])
        n = len(chain)
        last_stderr: list[str] = []

        for attempt, (enc_str, swdec) in enumerate(chain):
            if self.cancel_flag and self.cancel_flag.is_set():
                return EncodeResult(success=False, error="Cancelled")

            enc = EncoderType(enc_str)
            lbl = f"{enc_str}{'(SW)' if swdec else ''}"
            if attempt > 0:
                self._log(f"[{job_id}] Fallback {attempt}/{n - 1}: {lbl}", "WARN")

            ok = self._run_single(
                src,
                dst,
                enc,
                cq,
                job_id,
                duration,
                swdec=swdec,
                info=info,
                on_progress=on_progress,
                stderr_out=last_stderr,
            )
            self._last_stderr = list(last_stderr)

            if ok and dst.exists() and dst.stat().st_size > 100 * 1024:
                if attempt > 0:
                    self._log(f"[{job_id}] Fallback OK: {lbl}", "WARN")
                return EncodeResult(success=True, used_encoder=enc)

            if self.cancel_flag and self.cancel_flag.is_set():
                return EncodeResult(success=False, error="Cancelled")

            # Repair AnnexB
            if self._is_nal_error(last_stderr):
                self._log(f"[{job_id}] Fallback NAL: repair AnnexB", "WARN")
                repaired = self.repair_annexb(src, job_id)
                if repaired:
                    ok2 = self._run_single(
                        repaired,
                        dst,
                        enc,
                        cq,
                        job_id,
                        duration,
                        swdec=swdec,
                        info=info,
                        on_progress=on_progress,
                    )
                    rm_silent(repaired)
                    if ok2 and dst.exists():
                        self._log(f"[{job_id}] AnnexB repair OK with {lbl}", "WARN")
                        return EncodeResult(success=True, used_encoder=enc, used_repair="annexb")
                    if not self._is_nal_error(self._last_stderr):
                        break  # inny błąd — stop

            # Repair FOURCC (AVI rawvideo)
            elif self._is_rawvideo_error(last_stderr):
                self._log(f"[{job_id}] Fallback rawvideo: repair FOURCC", "WARN")
                repaired = self.repair_fourcc(src, job_id)
                if repaired:
                    ok2 = self._run_single(
                        repaired,
                        dst,
                        enc,
                        cq,
                        job_id,
                        duration,
                        swdec=swdec,
                        info=info,
                        on_progress=on_progress,
                    )
                    rm_silent(repaired)
                    if ok2 and dst.exists():
                        self._log(f"[{job_id}] FOURCC repair OK with {lbl}", "WARN")
                        return EncodeResult(success=True, used_encoder=enc, used_repair="fourcc")
                    if not self._is_rawvideo_error(self._last_stderr):
                        break

            last_stderr.clear()

        self._log(f"[{job_id}] All fallbacks exhausted", "ERROR")
        return EncodeResult(success=False, error="All encoders and repairs failed")

    def repair_annexb(self, src: Path, job_id: str) -> Optional[Path]:
        """repairannexb() z monolitu — 2 warianty BSF."""
        tmpdir = src.parent
        stem = safe_filename(src.stem, maxlen=60)

        # Wariant 1: extractextradata (SPSPPS inline per keyframe)
        rep1 = tmpdir / f"{stem}_annexb_rep1_{job_id}.mkv"
        cmd1 = [
            self.ffmpeg_bin,
            "-y",
            "-fflags",
            "genpts+igndts",
            "-i",
            str(src),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            "-bsf:v",
            "extract_annexb",
            "-f",
            "matroska",
            str(rep1),
        ]
        self._log(f"[{job_id}] Repair AnnexB variant 1", "WARN")
        _, _, rc1 = run_cmd(cmd1, timeout=300)
        if rc1 == 0 and rep1.exists() and rep1.stat().st_size > 1024 * 1024:
            return rep1
        rm_silent(rep1)

        # Wariant 2: discardcorrupt + ignore_err
        rep2 = tmpdir / f"{stem}_annexb_rep2_{job_id}.mkv"
        cmd2 = [
            self.ffmpeg_bin,
            "-y",
            "-fflags",
            "genpts+igndts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            str(src),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            "-f",
            "matroska",
            str(rep2),
        ]
        self._log(f"[{job_id}] Repair AnnexB variant 2 (ignore_err)", "WARN")
        _, _, rc2 = run_cmd(cmd2, timeout=300)
        if rc2 == 0 and rep2.exists() and rep2.stat().st_size > 1024 * 1024:
            return rep2
        rm_silent(rep2)

        self._log(f"[{job_id}] AnnexB repair failed", "ERROR")
        return None

    def repair_fourcc(self, src: Path, job_id: str) -> Optional[Path]:
        """repairavifourcc() z monolitu — 3 warianty."""
        tmpdir = src.parent
        stem = safe_filename(src.stem, maxlen=60)

        # Wariant 1: remux AVI → MKV (strip FOURCC, ffmpeg autodetect)
        rep1 = tmpdir / f"{stem}_fourcc_rep1_{job_id}.mkv"
        cmd1 = [
            self.ffmpeg_bin,
            "-y",
            "-fflags",
            "genpts+igndts",
            "-i",
            str(src),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-f",
            "matroska",
            str(rep1),
        ]
        self._log(f"[{job_id}] Repair FOURCC variant 1 (remux)", "WARN")
        _, stderr1, rc1 = run_cmd(cmd1, timeout=300)
        if rc1 == 0 and rep1.exists() and rep1.stat().st_size > 512 * 1024:
            # Sprawdź czy NIE używa rawvideo
            if "rawvideo" not in stderr1.lower():
                return rep1
        rm_silent(rep1)

        # Wariant 2: force mpeg4 decoder
        rep2 = tmpdir / f"{stem}_fourcc_rep2_{job_id}.mkv"
        cmd2 = [
            self.ffmpeg_bin,
            "-y",
            "-fflags",
            "genpts+igndts",
            "-vcodec",
            "mpeg4",
            "-i",
            str(src),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-f",
            "matroska",
            str(rep2),
        ]
        self._log(f"[{job_id}] Repair FOURCC variant 2 (mpeg4 decoder)", "WARN")
        _, _, rc2 = run_cmd(cmd2, timeout=300)
        if rc2 == 0 and rep2.exists() and rep2.stat().st_size > 512 * 1024:
            return rep2
        rm_silent(rep2)

        # Wariant 3: lossless H.264 jako pośrednik
        rep3 = tmpdir / f"{stem}_fourcc_rep3_{job_id}.mkv"
        cmd3 = [
            self.ffmpeg_bin,
            "-y",
            "-fflags",
            "genpts+igndts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-vcodec",
            "mpeg4",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-preset",
            "ultrafast",
            "-c:a",
            "copy",
            "-f",
            "matroska",
            str(rep3),
        ]
        self._log(f"[{job_id}] Repair FOURCC variant 3 (lossless H.264)", "WARN")
        _, _, rc3 = run_cmd(cmd3, timeout=600)
        if rc3 == 0 and rep3.exists() and rep3.stat().st_size > 512 * 1024:
            return rep3
        rm_silent(rep3)

        self._log(f"[{job_id}] FOURCC repair failed — file probably corrupt", "ERROR")
        return None

    def run_vmaf(
        self,
        reference: Path,
        distorted: Path,
        samplesecs: int = 30,
        job_id: str = "",
    ) -> Optional[float]:
        """vmafscore() z monolitu — 1:1 libvmaf filter, JSON parse."""
        import json

        cmd = [
            self.ffmpeg_bin,
            "-v",
            "error",
            "-t",
            str(samplesecs),
            "-i",
            str(distorted),
            "-t",
            str(samplesecs),
            "-i",
            str(reference),
            "-lavfi",
            "[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]libvmaf=log_fmt=json:log_path=-",
            "-f",
            "null",
            "-",
        ]
        stdout, stderr, rc = run_cmd(cmd, timeout=300)
        blob = stdout + stderr

        if rc != 0 and "VMAF score" not in blob and "pooled_metrics" not in blob:
            return None

        # Stary format: 'VMAF score: 94.123'
        for line in blob.splitlines():
            if "VMAF score" in line:
                try:
                    return float(line.split()[-1])
                except ValueError:
                    pass

        # Nowy format JSON: pooled_metrics.vmaf.mean
        try:
            idx = blob.rfind("{")
            if idx >= 0:
                data = json.loads(blob[idx:])
                return float(data["pooled_metrics"]["vmaf"]["mean"])
        except (ValueError, KeyError, json.JSONDecodeError):
            pass

        return None

    def vmaf_probe_encode(
        self,
        src: Path,
        dst: Path,
        encoder: EncoderType,
        cq: int,
        job_id: str,
        info: Optional[MediaInfo] = None,
    ) -> bool:
        """vmafprobeencode() z monolitu — lekki encode dla VMAF search.

        Tylko video stream, bez audio/subs/attachments.
        Timeout 180s (krótki sample 30s).
        """
        info = info or MediaInfo(
            path=src,
            size_bytes=0,
            duration_seconds=0,
            video_codec="",
            bitdepth=8,
        )
        is_10bit = info.is_10bit
        pixfmt_args = self._pixfmt_args(encoder, is_10bit)
        q_args = self._quality_args(encoder, cq, for_probe=True)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-c:v",
            encoder.value,
            *q_args,
            *pixfmt_args,
            str(dst),
        ]
        _, stderr, rc = run_cmd(cmd, timeout=180)
        if rc != 0 and stderr.strip():
            for line in stderr.strip().splitlines()[-3:]:
                self._log(f"[{job_id}] vmaf-probe: {line}", "WARN")
        return rc == 0 and dst.exists() and dst.stat().st_size > 1024

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------

    def _run_single(
        self,
        src: Path,
        dst: Path,
        encoder: EncoderType,
        cq: int,
        job_id: str,
        duration: float,
        swdec: bool = False,
        info: Optional[MediaInfo] = None,
        on_progress: Optional[Callable[[float], None]] = None,
        stderr_out: Optional[list] = None,
    ) -> bool:
        """runffmpeg() z monolitu: Popen + live stderr + progress parsing."""
        info = info or MediaInfo(
            path=src,
            size_bytes=0,
            duration_seconds=duration,
            video_codec="",
            bitdepth=8,
        )
        is_10bit = info.is_10bit
        height = info.height
        pixfmt_args = self._pixfmt_args(encoder, is_10bit)
        q_args = self._quality_args(encoder, cq)
        fps_args = self._fps_args(encoder, src)
        swdec_args = ["-hwaccel", "none"] if swdec else []
        wants_tiles = height >= 1440 and encoder.value in ("av1_nvenc", "libsvtav1")
        if wants_tiles and encoder == EncoderType.AV1NVENC:
            q_args += ["-tile-columns", "2", "-tile-rows", "2"]

        subtitle_codec = "copy"
        if info and any(c in getattr(info, "subtitle_codecs", []) for c in ("mov_text", "tx3g")):
            subtitle_codec = "srt"
        else:
            ffprobe_bin = self.ffmpeg_bin.replace("ffmpeg", "ffprobe")
            cmd_sub = [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(src),
            ]
            stdout, _, rc = run_cmd(cmd_sub, timeout=5)
            if rc == 0 and stdout:
                subs = stdout.strip().split()
                if any(c in subs for c in ("mov_text", "tx3g")):
                    subtitle_codec = "srt"

        cmd = [
            self.ffmpeg_bin,
            "-y",
            *swdec_args,
            "-i",
            str(src),
            "-c:v",
            encoder.value,
            *q_args,
            *pixfmt_args,
            *fps_args,
            "-c:a",
            "copy",
            "-c:s",
            subtitle_codec,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-progress",
            "pipe:1",
            "-nostats",
            str(dst),
        ]
        self._log(f"[{job_id}] CMD: {' '.join(cmd)}", "INFO")

        stderr_lines: list[str] = []

        def read_stderr(proc):
            for line in iter_ffmpeg_lines(proc):
                stderr_lines.append(line)
                self._log(f"  ffmpeg: {line}", "INFO")

        try:
            with ffmpeg_popen(cmd, job_id) as proc:
                t_stderr = threading.Thread(target=read_stderr, args=(proc,), daemon=True)
                t_stderr.start()

                out_us = 0
                cancelled = False
                for raw in proc.stdout or []:
                    if self.cancel_flag and self.cancel_flag.is_set():
                        cancelled = True
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        break
                    line = raw.strip()
                    if "=" in line:
                        k, _, v = line.partition("=")
                        if "out_time_us" in k.strip().lower():
                            try:
                                out_us = int(v.strip())
                            except ValueError:
                                pass
                    if duration > 0 and out_us > 0:
                        pct = min(out_us / 1_000_000 / duration * 100, 99.0)
                        if on_progress:
                            on_progress(pct)

                t_stderr.join(timeout=2)
                proc.wait()

                if stderr_out is not None:
                    stderr_out.extend(stderr_lines)
                self._last_stderr = stderr_lines

                if cancelled:
                    return False
                if proc.returncode != 0:
                    relevant = [
                        l
                        for l in stderr_lines
                        if any(
                            x in l.lower()
                            for x in (
                                "error",
                                "invalid",
                                "failed",
                                "cannot",
                                "no such",
                                "not found",
                                "unknown",
                                "unsupported",
                            )
                        )
                    ]
                    for line in relevant[-8:] if relevant else stderr_lines[-8:]:
                        self._log(f"  ffmpeg ERR: {line}", "ERROR")
                    return False
                if on_progress:
                    on_progress(100.0)
                return True

        except Exception as e:
            self._log(f"[{job_id}] Popen error: {e}", "ERROR")
            return False

    def _quality_args(self, encoder: EncoderType, cq: int, for_probe: bool = False) -> List[str]:
        """Per-encoder parametry jakości z monolitu — 1:1.

        for_probe=True: pomija extra_hw_frames (nieprawidłowa opcja bez hwaccel).
        """
        e = encoder.value
        if e == "av1_nvenc":
            args = [
                "-rc",
                "vbr",
                "-cq",
                str(cq),
                "-b:v",
                "0",
                "-maxrate",
                "0",
                "-preset",
                "p6",
                "-tune",
                "hq",
                "-spatial-aq",
                "1",
                "-temporal-aq",
                "1",
                "-aq-strength",
                "8",
                "-rc-lookahead",
                "32",
            ]
            if not for_probe:
                args += ["-extra_hw_frames", "64"]
            return args
        if e == "hevc_nvenc":
            args = [
                "-rc",
                "vbr",
                "-cq",
                str(cq),
                "-b:v",
                "0",
                "-maxrate",
                "0",
                "-preset",
                "p6",
                "-tune",
                "hq",
                "-spatial-aq",
                "1",
                "-temporal-aq",
                "1",
                "-aq-strength",
                "8",
                "-bf",
                "4",
                "-b_ref_mode",
                "middle",
                "-rc-lookahead",
                "32",
            ]
            if not for_probe:
                args += ["-extra_hw_frames", "64"]
            return args
        if e == "av1_qsv":
            return [
                "-global_quality",
                str(cq),
                "-b:v",
                "0",
                "-preset",
                "slow",
                "-bf",
                "7",
                "-extbrc",
                "1",
                "-look_ahead",
                "1",
                "-look_ahead_depth",
                "40",
                "-max_frame_size",
                "0",
            ]
        if e == "hevc_qsv":
            return [
                "-global_quality",
                str(cq),
                "-b:v",
                "0",
                "-preset",
                "slow",
                "-bf",
                "8",
                "-b_strategy",
                "1",
                "-refs",
                "4",
                "-extbrc",
                "1",
                "-look_ahead",
                "1",
                "-look_ahead_depth",
                "40",
                "-max_frame_size",
                "0",
            ]
        if e in ("av1_amf", "hevc_amf"):
            return ["-rc", "qvbr", "-qvbr_quality_level", str(cq)]
        if e == "libsvtav1":
            return ["-crf", str(cq), "-preset", "8", "-b:v", "0", "-svtav1-params", "tune=0:enable-overlays=1:scd=1"]
        if e == "libx265":
            return [
                "-crf",
                str(cq),
                "-preset",
                "slow",
                "-b:v",
                "0",
                "-x265-params",
                "aq-mode=3:aq-strength=1.0:rd=4:psy-rd=2.0:psy-rdoq=1.0",
            ]
        if e in ("libx264", "libaom-av1"):
            return ["-crf", str(cq), "-preset", "fast", "-b:v", "0"]
        return ["-cq", str(cq)]

    def _pixfmt_args(self, encoder: EncoderType, is_10bit: bool) -> List[str]:
        """10-bit pixfmt logic z monolitu."""
        if not is_10bit:
            return []
        e = encoder.value
        if e in ("hevc_nvenc", "av1_nvenc", "hevc_qsv", "av1_qsv", "hevc_amf", "av1_amf"):
            return ["-pix_fmt", "p010le"]
        if e in ("libx265", "libsvtav1", "libaom-av1"):
            return ["-pix_fmt", "yuv420p10le"]
        return []

    def _fps_args(self, encoder: EncoderType, src: Path) -> List[str]:
        """QSV FPS detection z monolitu — tylko std FPS: 24/25/30/48/50/60."""
        if "qsv" not in encoder.value:
            return []
        try:
            r = subprocess.run(
                [
                    self.ffprobe_bin,
                    "-v",
                    "quiet",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=r_frame_rate",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(src),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=NOWINDOW or 0,
            )
            raw = r.stdout.strip()
            if "/" in raw:
                n, d = raw.split("/")
                fps_val = float(n) / float(d)
                for std in (24, 25, 30, 48, 50, 60):
                    if abs(fps_val - std) < 0.5:
                        return ["-r", str(std)]
        except Exception:
            pass
        return []

    @staticmethod
    def _is_nal_error(lines: List[str]) -> bool:
        blob = " ".join(lines).lower()
        # Never treat "encoder not found" as a NAL error — encoder name
        # strings like 'hevc' or 'h264' appear inside "Unknown encoder 'hevcqsv'"
        if "unknown encoder" in blob or "encoder not found" in blob:
            return False
        return any(x in blob for x in _NAL_ERRORS)

    @staticmethod
    def _is_rawvideo_error(lines: List[str]) -> bool:
        blob = " ".join(lines).lower()
        return any(x in blob for x in _RAWVIDEO_ERRORS)

    def _log(self, msg: str, level: str = "INFO") -> None:
        if self.log_callback:
            self.log_callback(msg, level)
        lvl = getattr(logger, level.lower(), logger.info)
        lvl(msg)
