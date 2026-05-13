"""Remote file verification helpers."""
from __future__ import annotations
from .copyparty import CopypartyClient


def verify_remote_size(
    client: CopypartyClient,
    dir_url: str,
    fname: str,
    local_size: int,
) -> bool:
    """Return True if the remote file size equals *local_size*."""
    return client.verify_upload(dir_url, fname, local_size)
