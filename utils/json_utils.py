"""JSON config helpers — cfgload() i cfgsave() z monolitu."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict


def cfg_load(path: Path) -> Dict[str, Any]:
    """Wczytuje JSON config. Zwraca {} gdy plik nie istnieje lub błąd."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def cfg_save(path: Path, data: Dict[str, Any]) -> None:
    """Zapisuje JSON config atomowo (przez .tmp)."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
