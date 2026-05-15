"""Centralny logger z RotatingFileHandler + GUI log buffer.

Zastępuje print() w całym projekcie. Każdy moduł wołuje get_logger(__name__).
"""

from __future__ import annotations
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path("logs")
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def setup_logger(
    name: str,
    log_dir: Path = _LOG_DIR,
    level: int = logging.DEBUG,
    console: bool = True,
) -> logging.Logger:
    """Tworzy lub zwraca istniejący logger z rotating file + optional console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    fh = RotatingFileHandler(
        log_dir / "pyconv.log",
        maxBytes=50 * 1024 * 1024,  # 50 MB per plik
        backupCount=10,
        encoding="utf-8",
    )
    fh.setFormatter(_FORMATTER)
    logger.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(_FORMATTER)
        ch.setLevel(logging.INFO)
        logger.addHandler(ch)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Shortcut — setup_logger z domyślnymi parametrami."""
    return setup_logger(name)
