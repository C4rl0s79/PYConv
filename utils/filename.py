# -*- coding: utf-8 -*-
"""
Filename sanitisation helpers.

Sanitises Unicode / Windows-forbidden characters in temporary filenames
so that ffmpeg and OS calls don't choke on em-dashes, smart quotes, etc.
"""
from __future__ import annotations
import os
import re
import unicodedata

# ── Unicode → ASCII substitution map ───────────────────────────────────────────
_UNI_REPL: dict[str, str] = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-",  # hyphens
    "\u2013": "-", "\u2014": "-", "\u2015": "-",  # en/em/horizontal dash
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",  # smart single quotes
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',  # smart double quotes
    "\u2026": "...", "\u00a0": " ", "\u2022": "-", "\u00b7": "-",
    "\u2122": "TM", "\u00ae": "R", "\u00a9": "C",
    "\u0141": "L",  "\u0142": "l",   # Ł ł
    "\u00d8": "O",  "\u00f8": "o",   # Ø ø
    "\u00c6": "AE", "\u00e6": "ae",  # Æ æ
    "\u00df": "ss",                   # ß
    "\u0110": "D",  "\u0111": "d",   # Đ đ
    "\u0126": "H",  "\u0127": "h",   # Ħ ħ
    "\u0166": "T",  "\u0167": "t",   # Ŧ ŧ
}

_FORBIDDEN_RX: re.Pattern[str] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_len: int = 80) -> str:
    """
    Return a safe ASCII filename usable on Windows and in ffmpeg arguments:
    - smart quotes / dashes / ellipsis → ASCII equivalents
    - strip combining accents (NFKD normalisation)
    - remove Windows-forbidden characters and control codes
    - spaces → underscores
    - truncate to *max_len* characters
    """
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
    """Normalise path separators (eliminates mixed C:/foo\\bar patterns)."""
    return os.path.normpath(path)


def safe_decode(raw: bytes) -> str:
    """
    Decode bytes to str trying common encodings in priority order.
    ffmpeg/ffprobe always emit UTF-8; locale codepages are fallback only.
    """
    for enc in ("utf-8", "cp1250", "cp852", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")
