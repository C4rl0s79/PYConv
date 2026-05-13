"""JSON load/save helpers with safe fallback."""
import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path, default: Any = None) -> Any:
    """Load JSON from *path*, returning *default* on any error."""
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default if default is not None else {}


def save_json(path: str | Path, data: Any, indent: int = 2) -> bool:
    """Save *data* as JSON to *path*. Returns True on success."""
    try:
        Path(path).write_text(
            json.dumps(data, indent=indent, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False
