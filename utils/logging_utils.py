"""Centralised logging setup for PYConv."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_rotating_logger(
    name: str = "pyconv",
    log_dir: str | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """Create (or retrieve) a logger with rotating file handler + stderr handler."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Rotating file handler
    if log_dir:
        log_path = Path(log_dir) / f"{name}.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                str(log_path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as exc:
            logger.warning("Could not create log file %s: %s", log_path, exc)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'pyconv' hierarchy."""
    return logging.getLogger(f"pyconv.{name}")
