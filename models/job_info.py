# -*- coding: utf-8 -*-
"""EncodeJob dataclass – represents a single file in the pipeline."""
from dataclasses import dataclass, field
from typing import Optional
from .enums import JobStatus


@dataclass
class EncodeJob:
    """All parameters needed to process one file through the pipeline."""

    # Identification
    job_id: int
    source_path: str           # local path or URL
    dest_dir_url: str          # destination dir URL (copyparty) or local dir
    filename: str              # original filename

    # Encoding parameters
    encoder: str               # e.g. 'av1_nvenc'
    cq: int = 0                # CQ / GQ value (0 = auto)
    gpu_label: str = "GPU1"    # 'GPU1' or 'GPU2'
    gpu_index: int = 0

    # Pipeline flags
    is_network: bool = False
    use_copyparty: bool = False
    keep_orig: bool = False
    test_mode: bool = False
    hq_mode: bool = False
    vmaf_enabled: bool = False
    vmaf_target: float = 93.0
    min_save_pct: int = 5
    auto_cq: bool = True
    anime_mode: bool = False
    qsv_profile: str = "quality"

    # Runtime state
    status: JobStatus = JobStatus.PENDING
    error_msg: str = ""
    savings_pct: float = 0.0
    vmaf_score: float = -1.0

    # Paths populated during execution
    local_src: str = ""        # local temp file (after download)
    local_out: str = ""        # encoded output temp file
    cp_password: str = ""
