"""Timing utilities."""
import time
from typing import Callable


def format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


class Stopwatch:
    """Simple elapsed-time tracker."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def reset(self) -> None:
        self._start = time.monotonic()
