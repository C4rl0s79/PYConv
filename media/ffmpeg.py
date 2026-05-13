"""FFmpegEngine – all ffmpeg encode, VMAF and repair knowledge in one class.

This module is the ONLY place that constructs ffmpeg command lines.
Pipeline workers call methods here; they never build ffmpeg args themselves.
"""
from __future__ import annotations
import os
import json
import subprocess
import threading
import sys
from pathlib import Path
from typing import Callable, Optional

from utils.subprocess_utils import run_cmd, open_popen, safe_decode
from utils.logging_utils import get_logger
from models.encode_result import EncodeResult

log = get_logger("ffmpeg")

# Hide console on Windows
_NO_WINDOW: int = 0
if sys.platform == "win32":
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# Errors that indicate a HW-decode NAL/stream issue → trigger SW-decode fallback
_NAL_ERRORS = (
    "Invalid NAL unit", "decode_slice_header error",
    "no frame!", "non monotonous", "invalid data found",
    "Error splitting the input", "Invalid data found",
    "SEI type", "mmco: unref", "concealing",
    "NVDEC_ERR", "NvDecCreateDecoder",
)

# Errors that indicate AVI raw-video / bad FOURCC
_RAWVIDEO_ERRORS = (
    "[dec:rawvideo]", "rawvideo @ ", "Unrecognized option 'rawvideo'",
)


class FFmpegEngine:
    """All ffmpeg command construction and execution."""

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        cancel_flag: Optional[threading.Event] = None,
    ) -> None:
        self.on_log = on_log or (lambda msg: log.info(msg))
        self.cancel_flag = cancel_flag or threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._procs_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────────────

    def run_encode(
        self,
        cmd: list[str],
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> tuple[str, str, int]:
        """Execute an ffmpeg encode via Popen with live stderr reading.

        Returns (stdout, stderr_full, returncode).
        Reads stderr line-by-line so GUI gets live progress without large blobs.
        """
        kwargs: dict = {}
        if _NO_WINDOW:
            kwargs["creationflags"] = _NO_WINDOW
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )
        except FileNotFoundError:
            return "", "ffmpeg not found", -2
        except OSError as exc:
            return "", str(exc), -3

        with self._procs_lock:
            self._procs.append(proc)

        stderr_lines: list[str] = []
        try:
            assert proc.stderr is not None
            for raw_line in proc.stderr:
                if self.cancel_flag.is_set():
                    proc.kill()
                    break
                line = safe_decode(raw_line).rstrip()
                stderr_lines.append(line)
                self.on_log(line)
            proc.wait()
        finally:
            with self._procs_lock:
                self._procs.discard(proc) if hasattr(self._procs, "discard") else None
            try:
                self._procs.remove(proc)
            except ValueError:
                pass

        stdout = safe_decode(proc.stdout.read()) if proc.stdout else ""
        return stdout, "\n".join(stderr_lines), proc.returncode

    def run_probe(self, path: str, timeout: int = 15) -> tuple[str, str, int]:
        """Run ffprobe on *path* and return raw (stdout, stderr, rc)."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ]
        return run_cmd(cmd, timeout=timeout)

    def run_vmaf(
        self,
        reference: str,
        distorted: str,
        sample_secs: int = 30,
    ) -> float:
        """Compute VMAF for the first *sample_secs* seconds. Returns 0–100 or -1 on error."""
        cmd = [
            "ffmpeg", "-v", "error",
            "-t", str(sample_secs), "-i", distorted,
            "-t", str(sample_secs), "-i", reference,
            "-lavfi",
            "[0:v]setpts=PTS-STARTPTS[d];"
            "[1:v]setpts=PTS-STARTPTS[r];"
            "[d][r]libvmaf=log_fmt=json:log_path=-",
            "-f", "null", "-",
        ]
        stdout, stderr, rc = run_cmd(cmd)
        blob = stdout + "\n" + stderr
        # Try new JSON format first
        try:
            idx = blob.find("{")
            if idx >= 0:
                j = json.loads(blob[idx: blob.rfind("}") + 1])
                val = float(j.get("pooled_metrics", {}).get("vmaf", {}).get("mean", -1.0))
                if val >= 0:
                    return val
        except (ValueError, json.JSONDecodeError):
            pass
        # Fallback: old "VMAF score: N" line in stderr
        for line in blob.splitlines():
            if "VMAF score" in line:
                try:
                    return float(line.split(":")[-1].strip())
                except ValueError:
                    pass
        return -1.0

    def repair_annexb(self, src: str, tmp_dir: str, stem: str, gpu_label: str) -> str | None:
        """Attempt Annex B → AVCC remux repair. Returns fixed path or None."""
        out1 = os.path.join(tmp_dir, f"{stem}_annexb_fix.mkv")
        # Variant 1: extract_extradata bitstream filter
        cmd1 = [
            "ffmpeg", "-y", "-v", "error",
            "-i", src,
            "-c:v", "copy", "-bsf:v", "extract_extradata",
            "-c:a", "copy", "-c:s", "copy",
            out1,
        ]
        _, _, rc = run_cmd(cmd1)
        if rc == 0 and os.path.exists(out1) and os.path.getsize(out1) > 1024:
            return out1
        # Variant 2: discard corrupt
        cmd2 = [
            "ffmpeg", "-y", "-v", "error",
            "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
            "-i", src,
            "-c:v", "copy", "-c:a", "copy",
            out1,
        ]
        _, _, rc = run_cmd(cmd2)
        if rc == 0 and os.path.exists(out1) and os.path.getsize(out1) > 1024:
            return out1
        return None

    def repair_fourcc(
        self, src: str, tmp_dir: str, stem: str, variant: int = 1
    ) -> str | None:
        """Repair AVI with bad FOURCC.  variant=1/2/3 (remux/force-decoder/lossless)."""
        out = os.path.join(tmp_dir, f"{stem}_fourcc_fix_v{variant}.mkv")
        if variant == 1:
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-c:v", "copy", out]
        elif variant == 2:
            cmd = ["ffmpeg", "-y", "-v", "error", "-vcodec", "mpeg4", "-i", src,
                   "-c:v", "copy", out]
        else:
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
                   "-c:v", "libx264", "-crf", "0", "-preset", "ultrafast",
                   "-c:a", "copy", out]
        _, _, rc = run_cmd(cmd)
        if rc == 0 and os.path.exists(out) and os.path.getsize(out) > 1024:
            return out
        return None

    def validate_output(self, path: str, min_size: int = 1024 * 1024) -> bool:
        """Basic output validation: file exists, non-trivial size, ffprobe OK."""
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) < min_size:
            return False
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1",
            path,
        ]
        _, _, rc = run_cmd(cmd, timeout=15)
        return rc == 0

    def kill_all(self) -> None:
        """Kill all running ffmpeg processes (Cancel button handler)."""
        with self._procs_lock:
            for proc in list(self._procs):
                try:
                    proc.kill()
                except Exception:
                    pass

    # ── Error pattern helpers ─────────────────────────────────────────────────────

    @staticmethod
    def is_nal_error(stderr: str) -> bool:
        """Return True if stderr contains NAL / HW-decode error patterns."""
        return any(pat in stderr for pat in _NAL_ERRORS)

    @staticmethod
    def is_rawvideo_error(stderr: str) -> bool:
        """Return True if stderr indicates bad AVI FOURCC (rawvideo decoder)."""
        return any(pat in stderr for pat in _RAWVIDEO_ERRORS)
