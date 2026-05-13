# -*- coding: utf-8 -*-
"""JSON read/write helpers with graceful error handling."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read JSON from *path*; return *default* on any error."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: str | Path, data: Any, indent: int = 2) -> bool:
    """Write *data* as JSON to *path*. Returns True on success."""
    try:
        Path(path).write_text(
            json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except Exception:
        return False
