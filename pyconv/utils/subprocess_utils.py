"""Subprocess helpers z Popen line-buffered stderr dla FFmpeg.

Zastępuje subprocess.run() wszędzie tam gdzie FFmpeg generuje duże stderr/stdout.
Kluczowe: bufsize=1 = line-buffered, zero ryzyka ogromnych stderr blobów.
"""

from __future__ import annotations
import subprocess
import sys
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

# Windows: ukryj czarne okno konsoli
NOWINDOW: int = 0
if sys.platform == "win32":
    NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


@contextmanager
def ffmpeg_popen(cmd: List[str], job_id: str = "") -> Iterator[subprocess.Popen]:
    """Context manager: Popen z line-buffered stdout+stderr dla FFmpeg.

    FFmpeg pisze progress na stdout (-progress pipe:1 -nostats),
    logi/błędy na stderr. Łączymy oba przez stderr=STDOUT.
    """
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,  # line-buffered — kluczowe dla live GUI
        "universal_newlines": True,
    }
    if NOWINDOW:
        kwargs["creationflags"] = NOWINDOW
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait()


def iter_ffmpeg_lines(proc: subprocess.Popen) -> Iterator[str]:
    """Yields linie stderr z ffmpeg live — bez blokowania."""
    if proc.stderr:
        for raw in proc.stderr:
            line = raw.strip()
            if line:
                yield line


def run_cmd(
    args: List[str],
    timeout: Optional[int] = None,
    **kwargs,
) -> Tuple[str, str, int]:
    """Zastępuje runcmd() z monolitu: (stdout, stderr, returncode).

    Używać TYLKO dla krótkich komend (ffprobe, md5sum).
    Dla długich encode'ów zawsze ffmpeg_popen().
    """
    extra: dict = {"capture_output": True, "encoding": "utf-8", "errors": "replace"}
    if timeout:
        extra["timeout"] = timeout
    if NOWINDOW:
        extra["creationflags"] = NOWINDOW
    extra.update(kwargs)
    try:
        r = subprocess.run(args, **extra)
        return _safe_decode(r.stdout), _safe_decode(r.stderr), r.returncode
    except subprocess.TimeoutExpired as e:
        return _safe_decode(e.stdout or b""), _safe_decode(e.stderr or b""), -1
    except FileNotFoundError:
        return "", f"Executable not found: {args[0]}", -2
    except OSError as e:
        return "", str(e), -3


def _safe_decode(raw) -> str:
    if isinstance(raw, bytes):
        for enc in ("utf-8", "cp1250", "cp852", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")
    return raw or ""
