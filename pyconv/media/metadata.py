"""Scene complexity probe – used by HQ mode to adjust CQ."""

from __future__ import annotations
from pyconv.utils.subprocess_utils import run_cmd


def complexity_probe(path: str, duration: float, sample_secs: int = 20) -> float:
    """
    Quick scene-change sampling to measure video complexity.
    Returns 0.0 (static) → ~1.0+ (heavy action/cuts).
    Uses `select=gt(scene,0.3)` on a 20s mid-file sample.
    """
    if duration < sample_secs * 1.5:
        ss, t = 0, max(5, int(duration * 0.5))
    else:
        ss = max(0, int(duration / 2 - sample_secs / 2))
        t = sample_secs

    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        str(ss),
        "-t",
        str(t),
        "-i",
        path,
        "-vf",
        "select='gt(scene,0.3)',metadata=print:file=-",
        "-an",
        "-sn",
        "-f",
        "null",
        "-",
    ]
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        return 0.0
    cuts = stdout.count("lavfi.scene_score=") + stderr.count("lavfi.scene_score=")
    return cuts / float(t) if t > 0 else 0.0


def hq_cq_adjustment(complexity: float) -> int:
    """Map complexity metric to a CQ delta (lower CQ = higher quality)."""
    if complexity > 0.8:
        return -3
    if complexity > 0.4:
        return -2
    if complexity > 0.15:
        return 0
    if complexity > 0.05:
        return +1
    return +2
