"""settings.py — AppSettings dataclass z persist przez JSON."""
from __future__ import annotations

from dataclasses import dataclass, field  # noqa: F401 (field używany pośrednio przez podklasy)
from pathlib import Path
from typing import Optional

from .constants import SAFE_FREE_GB, SESSION_FILE, WARN_FREE_GB


@dataclass
class AppSettings:
    """Wszystkie ustawienia aplikacji — odpowiednik cfg_* z monolitu."""

    # Źródło
    src_path:    str  = ""
    mode:        str  = "folder"     # "folder" | "file"
    is_network:  bool = False
    tmp_dir:     str  = "C:\\\\"

    # Enkodery
    encoder1:    str  = "av1nvenc"
    encoder2:    str  = "av1qsv"
    gpu2_enabled:bool = False

    # CQ
    auto_cq:     bool = True
    cq1:         int  = 32
    cq2:         int  = 28
    min_savings: int  = 10

    # HQ
    hq_mode:     bool  = False
    vmaf_enabled:bool  = False
    vmaf_target: float = 93.0

    # QSV
    qsv_profile: str  = "quality"
    anime_mode:  bool = False

    # Filtry
    skip_hdr:    bool = True
    skip_av1:    bool = True
    skip_hevc:   bool = False
    keep_orig:   bool = False
    test_mode:   bool = False

    # Copyparty
    use_copyparty: bool = False
    cp_src_url:    str  = ""
    cp_remember:   bool = False

    # Progi
    safe_free_gb:  float = SAFE_FREE_GB
    warn_free_gb:  float = WARN_FREE_GB

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppSettings":
        import json
        p = path or Path(SESSION_FILE)
        if not p.exists():
            return cls()
        try:
            with p.open(encoding="utf-8") as f:
                d = json.load(f)
            obj = cls()
            for k, v in d.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            return obj
        except Exception:
            return cls()

    def save(self, path: Optional[Path] = None) -> None:
        import json
        import dataclasses
        p = path or Path(SESSION_FILE)
        with p.open("w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(self), f, indent=2, ensure_ascii=False)
