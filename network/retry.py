"""Generic retry decorator / helper."""
from __future__ import annotations
import time
from typing import Callable, TypeVar
from functools import wraps

T = TypeVar("T")


def with_retry(
    fn: Callable[..., T],
    *args,
    retries: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """Call *fn* with *args*/*kwargs*, retrying up to *retries* times on *exceptions*."""
    last_exc: Exception = RuntimeError("no attempts made")
    wait = delay
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(wait)
                wait *= backoff
    raise last_exc
