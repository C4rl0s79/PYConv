"""constants.py — stałe globalne projektu."""

from __future__ import annotations

# Wersja
APP_VERSION = "4.12"
APP_TITLE = f"Plex Convert GUI v{APP_VERSION}"

# Progi wolnego miejsca na dysku (GB)
SAFE_FREE_GB: float = 20.0
WARN_FREE_GB: float = 10.0

# Dozwolone rozszerzenia wideo
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mkv",
        ".avi",
        ".mp4",
        ".mov",
        ".ts",
        ".m2ts",
        ".wmv",
        ".flv",
        ".mpg",
        ".mpeg",
        ".webm",
        ".ogv",
    }
)

# Limit czasu pobierania / uploadowania (s)
DOWNLOAD_TIMEOUT: int = 3600
UPLOAD_TIMEOUT: int = 7200
STALL_TIMEOUT: int = 120

# Chunk upload
UPLOAD_CHUNK_SIZE: int = 8 * 1024 * 1024  # 8 MB

# FFprobe / FFmpeg
FFPROBE_TIMEOUT: int = 30
FFMPEG_TIMEOUT: int = 0  # 0 = bez limitu

# Plik sesji
SESSION_FILE = ".pyconv_session.json"
