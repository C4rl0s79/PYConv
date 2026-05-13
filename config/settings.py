"""Session persistence: load/save user settings to conver_session.json."""
from __future__ import annotations
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from utils.json_utils import load_json, save_json

_CFG_PATH = Path(__file__).parent.parent / "conver_session.json"


@dataclass
class SessionSettings:
    """All persisted GUI/pipeline settings."""
    src_path: str = ""
    mode: str = "folder"            # "folder" | "file"
    is_network: bool = False
    tmp_dir: str = "C:\\" if sys.platform == "win32" else "/tmp"

    enc1: str = "av1_nvenc (NVIDIA AV1)"
    enc2: str = "av1_qsv (Intel Arc AV1)"
    gpu2_enabled: bool = False

    auto_cq: bool = True
    cq1: int = 32
    cq2: int = 28
    min_save: int = 10
    hq_mode: bool = False
    vmaf_enabled: bool = False
    vmaf_target: float = 93.0
    qsv_profile: str = "quality"
    anime_mode: bool = False

    skip_hdr: bool = False
    skip_av1: bool = False
    skip_hevc: bool = False
    keep_orig: bool = False
    test_mode: bool = False

    cp_use: bool = False
    cp_url: str = "https://emucloud.org/filmy/"
    cp_password: str = ""
    cp_remember: bool = False


def load_session(path: Path = _CFG_PATH) -> SessionSettings:
    """Load session settings from JSON; fall back to defaults on any error."""
    data = load_json(path, default={})
    s = SessionSettings()
    for f in s.__dataclass_fields__:
        if f in data:
            setattr(s, f, data[f])
    return s


def save_session(settings: SessionSettings, path: Path = _CFG_PATH) -> None:
    """Persist session settings to JSON."""
    data = asdict(settings)
    if not settings.cp_remember:
        data["cp_password"] = ""
    save_json(path, data)
