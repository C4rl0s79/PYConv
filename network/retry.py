"""Retry policy — hermetyzuje logikę ponownych prób.

Pipeline i CopypartyClient nie muszą znać szczegółów backoff.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from ..utils.logging_utils import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    delay_seconds: float = 5.0
    backoff_factor: float = 2.0  # delay * factor per attempt


def with_retry(
    fn: Callable[[], T],
    policy: Optional[RetryPolicy] = None,
    job_id: str = "",
    label: str = "",
) -> Optional[T]:
    """Wykonuje fn() z retry wg policy. Zwraca wynik lub None po wyczerpaniu."""
    p = policy or RetryPolicy()
    delay = p.delay_seconds
    for attempt in range(1, p.max_attempts + 1):
        result = fn()
        if result:
            return result
        if attempt < p.max_attempts:
            logger.warning(f"[{job_id}] {label} attempt {attempt}/{p.max_attempts} failed, retry in {delay:.0f}s")
            time.sleep(delay)
            delay *= p.backoff_factor
    logger.error(f"[{job_id}] {label} exhausted {p.max_attempts} attempts")
    return None
