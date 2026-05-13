# -*- coding: utf-8 -*-
"""
Centralised logging configuration for PYConv.

Sets up:
  - A rotating file handler  → logs/pyconv.log
  - A console handler        → stderr
  - A queue-based GUI handler (populated externally by the GUI layer)

Usage:
    from utils.logging_utils import get_logger
    logger = get_logger(__name__)
    logger.info("message")
"""
from __future__ import annotations
import logging
import logging.handlers
import queue
import threading
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "pyconv.log"
_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per log file
_BACKUP_COUNT = 3

_gui_queue: queue.Queue[tuple[str, str]] | None = None  # (level, message)
_gui_queue_lock = threading.Lock()


class _GUIHandler(logging.Handler):
    """Forwards log records to a thread-safe queue consumed by the GUI."""

    def emit(self, record: logging.LogRecord) -> None:
        global _gui_queue
        if _gui_queue is None:
            return
        level = record.levelname  # 'INFO', 'WARNING', 'ERROR', ...
        msg = self.format(record)
        try:
            _gui_queue.put_nowait((level, msg))
        except queue.Full:
            pass  # Drop silently – GUI log is non-critical


def configure_logging(level: int = logging.DEBUG) -> None:
    """Call once at application startup."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("pyconv")
    root.setLevel(level)

    if root.handlers:
        return  # Already configured

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # GUI handler
    gh = _GUIHandler()
    gh.setLevel(logging.INFO)
    gh.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(gh)


def set_gui_queue(q: queue.Queue[tuple[str, str]]) -> None:
    """Register the GUI log queue (called by the GUI layer on startup)."""
    global _gui_queue
    with _gui_queue_lock:
        _gui_queue = q


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'pyconv' namespace."""
    return logging.getLogger(f"pyconv.{name}")
