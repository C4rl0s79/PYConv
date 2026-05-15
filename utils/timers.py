"""Prosty timer kontekstowy do mierzenia czasu enkodu/uploadu."""

from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass
class Timer:
    """Context manager mierzący czas elapsed w sekundach."""

    _start: float = field(default_factory=time.monotonic, init=False)
    elapsed: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_) -> None:
        self.elapsed = time.monotonic() - self._start

    def __str__(self) -> str:
        s = self.elapsed
        if s < 60:
            return f"{s:.1f}s"
        m, s = divmod(int(s), 60)
        return f"{m}m{s:02d}s"
