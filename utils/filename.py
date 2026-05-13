"""Filename sanitisation utilities for temporary and output file naming."""
import os
import re
import unicodedata

# Unicode typographic characters → ASCII replacements.
_UNI_REPL: dict[str, str] = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2026": "...", "\u00a0": " ", "\u2022": "-", "\u00b7": "-",
    "\u2122": "TM", "\u00ae": "R", "\u00a9": "C",
    "\u0141": "L", "\u0142": "l",
    "\u00d8": "O", "\u00f8": "o",
    "\u00c6": "AE", "\u00e6": "ae",
    "\u00df": "ss",
    "\u0110": "D", "\u0111": "d",
    "\u0126": "H", "\u0127": "h",
    "\u0166": "T", "\u0167": "t",
}

_FORBIDDEN_RX = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_len: int = 80) -> str:
    """Return a safe ASCII filename for temp files (Windows + ffmpeg compatible)."""
    if not name:
        return "file"
    for k, v in _UNI_REPL.items():
        name = name.replace(k, v)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = _FORBIDDEN_RX.sub("_", name)
    name = name.replace(" ", "_")
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = name[:max_len].strip("._-")
    return name or "file"


def norm_path(path: str) -> str:
    """Normalise path separators (eliminates mixed C:/foo\\bar style)."""
    return os.path.normpath(path)
