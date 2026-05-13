# -*- coding: utf-8 -*-
"""
Subprocess helpers – wrappers around subprocess.run / subprocess.Popen
for running ffmpeg and ffprobe.

All platform-specific handling (Windows CREATE_NO_WINDOW) is centralised here.
"""
from __future__ import annotations
import sys
import subprocess
from typing import Callable, Iterator

# Hide console windows on Windows when spawning child processes.
_NO_WINDOW: int = 0
if sys.platform == "win32":
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _creation_flags(extra: int = 0) -> int:
    return _NO_WINDOW | extra


def run_cmd(
    args: list[str],
    timeout: int | None = None,
    **kwargs,
) -> tuple[str, str, int]:
    """
    Run a command and capture stdout/stderr.

    Returns (stdout_str, stderr_str, returncode).
    returncode is negative for internal errors:
      -1  timeout
      -2  executable not found
      -3  OS error
    """
    from utils.filename import safe_decode  # local import to avoid circular

    if _NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = _creation_flags()
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        return safe_decode(exc.stdout or b""), safe_decode(exc.stderr or b""), -1
    except FileNotFoundError:
        return "", f"executable not found: {args[0] if args else '?'}", -2
    except OSError as exc:
        return "", str(exc), -3
    return safe_decode(result.stdout), safe_decode(result.stderr), result.returncode


def popen_stderr_lines(
    args: list[str],
    cancel_check: Callable[[], bool] | None = None,
    **kwargs,
) -> Iterator[str]:
    """
    Launch a process and yield stderr line-by-line (UTF-8 decoded).

    Use this for long-running ffmpeg encodes where live progress
    logging is needed and blocking on a large stderr blob must be avoided.

    Yields decoded lines (stripped).  Caller is responsible for reading
    stdout if needed – this helper routes stdout to DEVNULL.

    The process is terminated if cancel_check() returns True.
    """
    if _NO_WINDOW and "creationflags" not in kwargs:
        kwargs["creationflags"] = _creation_flags()

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **kwargs,
    )
    try:
        for raw_line in proc.stderr:  # type: ignore[union-attr]
            if cancel_check and cancel_check():
                proc.terminate()
                proc.wait(timeout=5)
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                yield line
    finally:
        proc.wait()


def kill_process(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Terminate a Popen process gracefully, then kill after 3 s."""
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
