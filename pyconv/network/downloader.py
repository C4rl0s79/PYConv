"""Standalone download_file() function – thin wrapper around CopypartyClient."""

from __future__ import annotations
from typing import Callable, Optional
from .copyparty import CopypartyClient


def download_file(
    url: str,
    local_path: str,
    total_size: int,
    client: CopypartyClient,
    on_progress: Optional[Callable[[float, float], None]] = None,
    cancel_flag=None,
) -> bool:
    """Convenience wrapper: download *url* → *local_path* using *client*."""
    return client.download_file(
        url=url,
        local_path=local_path,
        total_size=total_size,
        on_progress=on_progress,
        cancel_flag=cancel_flag,
    )
