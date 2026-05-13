# -*- coding: utf-8 -*-
"""Simple wall-clock timer utilities."""
from __future__ import annotations
import time


class Stopwatch:
    """Context-manager and manual wall-clock timer."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0

    def start(self) -> "Stopwatch":
        self._start = time.monotonic()
        return self

    def stop(self) -> float:
        self._end = time.monotonic()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        """Elapsed seconds (from start to stop, or now if still running)."""
        end = self._end if self._end else time.monotonic()
        return max(end - self._start, 0.0)

    def __enter__(self) -> "Stopwatch":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()

    def __repr__(self) -> str:
        return f"Stopwatch({self.elapsed:.2f}s)"
