# -*- coding: utf-8 -*-
"""
Runtime settings container – loaded from conver_session.json and updated
by the GUI. Passed as a frozen/mutable config object through the pipeline.

Does NOT import Tkinter – fully decoupled from GUI.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from .constants import SESSION_FILE


@dataclass
class AppSettings:
    """Mutable settings snapshot shared between GUI and pipeline."""

    # ─ Source
    src: str = ""
    mode: str = "folder"           # 'folder' | 'file'
    is_network: bool = False
    tmp: str = ""

    # ─ Encoders
    enc1: str = "av1_nvenc (NVIDIA AV1)"
    gpu2_enabled: bool = False
    enc2: str = "av1_nvenc (NVIDIA AV1)"
    auto_cq: bool = True
    cq1: int = 28
    cq2: int = 28
    min_save: int = 5
    hq_mode: bool = False
    vmaf_enabled: bool = False
    vmaf_target: float = 93.0
    qsv_profile: str = "quality"
    anime_mode: bool = False

    # ─ Filters
    skip_hdr: bool = True
    skip_av1: bool = True
    skip_hevc: bool = False
    keep_orig: bool = False
    test_mode: bool = False

    # ─ Copyparty
    cp_use: bool = False
    cp_url: str = "https://emucloud.org/filmy/"
    cp_remember: bool = False
    cp_password: str = ""

    def save(self, path: Path = SESSION_FILE) -> None:
        try:
            data = asdict(self)
            if not self.cp_remember:
                data.pop("cp_password", None)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            # Non-fatal – session persistence should never crash the app
            print(f"[settings] save error: {exc}")

    @classmethod
    def load(cls, path: Path = SESSION_FILE) -> "AppSettings":
        inst = cls()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for f_name, f_val in data.items():
                    if hasattr(inst, f_name):
                        try:
                            setattr(inst, f_name, f_val)
                        except Exception:
                            pass
        except Exception as exc:
            print(f"[settings] load error: {exc}")
        return inst
