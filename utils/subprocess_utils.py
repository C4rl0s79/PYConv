"""Subprocess helpers – run_cmd (subprocess.run wrapper) and safe_decode."""
import subprocess
import sys
from typing import Optional

# Suppress console windows on Windows when spawning ffmpeg/ffprobe.
_NO_WINDOW: int = 0
if sys.platform == "win32":
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def safe_decode(raw: bytes) -> str:
    """Decode bytes trying UTF-8 first, then fallback codepages."""
    for enc in ("utf-8", "cp1250", "cp852", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def run_cmd(
    args: list[str],
    timeout: Optional[float] = None,
    **kwargs,
) -> tuple[str, str, int]:
    """Run a subprocess and return (stdout, stderr, returncode).

    - Hides console windows on Windows.
    - Returns (-1) on timeout, (-2) on FileNotFoundError, (-3) on OSError.
    """
    if _NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = _NO_WINDOW
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired as e:
        return safe_decode(e.stdout or b""), safe_decode(e.stderr or b""), -1
    except FileNotFoundError:
        return "", f"executable not found: {args[0] if args else '?'}", -2
    except OSError as e:
        return "", str(e), -3
    return safe_decode(result.stdout), safe_decode(result.stderr), result.returncode


def open_popen(
    args: list[str],
    **kwargs,
) -> subprocess.Popen:
    """Open a Popen process with hidden console on Windows.

    Use this instead of subprocess.Popen directly for ffmpeg encode calls
    so that stderr can be read line-by-line for live logging.
    """
    if _NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = _NO_WINDOW
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )
