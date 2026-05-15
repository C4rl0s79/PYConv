"""Standalone upload_file() function + post-upload verification workflow."""

from __future__ import annotations
import os
from typing import Callable, Optional

from .copyparty import CopypartyClient
from pyconv.models.encode_result import UploadResult
from pyconv.models.enums import UploadStatus
from pyconv.utils.logging_utils import get_logger

log = get_logger("uploader")


def upload_file(
    local_path: str,
    dest_url: str,
    dir_url: str,
    client: CopypartyClient,
    on_progress: Optional[Callable[[float, float], None]] = None,
    cancel_flag=None,
    max_retries: int = 3,
) -> UploadResult:
    """Upload *local_path* to *dest_url*, then verify remote size.

    Workflow (per requirement):
    1. Upload via PUT
    2. Verify remote_size == local_size via /?ls
    3. Only after verification mark as DONE
    Retries on failure (FAILED or size mismatch), not on STALLED or CANCELLED.
    """
    fname = os.path.basename(local_path)
    local_size = os.path.getsize(local_path)

    for attempt in range(1, max_retries + 1):
        if cancel_flag and cancel_flag.is_set():
            return UploadResult(status=UploadStatus.CANCELLED)

        log.info("Upload attempt %d/%d: %s", attempt, max_retries, fname)
        result = client.upload_file(
            local_path=local_path,
            dest_url=dest_url,
            on_progress=on_progress,
            cancel_flag=cancel_flag,
        )

        if result.status in (UploadStatus.CANCELLED, UploadStatus.STALLED):
            return result

        if result.status == UploadStatus.DONE:
            # Verify remote size before declaring success
            verified = client.verify_upload(dir_url, fname, local_size)
            if verified:
                result.verified = True
                result.remote_size = local_size
                log.info("Upload verified OK: %s", fname)
                return result
            log.warning("Upload size mismatch on attempt %d: %s – retrying", attempt, fname)

    return UploadResult(
        status=UploadStatus.FAILED,
        error_msg=f"Upload failed after {max_retries} attempts",
    )
