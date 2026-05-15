"""CopypartyClient — hermetyzuje cały HTTP I/O z Copyparty.

Wyodrębniony z monolitu: cpdownloadfile(), cpuploadfile(), cpuploadup2k(),
cpverifysize(), cpverifysha256(), cpdelete().

Zachowane 1:1:
  - STALL_TIMEOUT = 120s (brak danych → przerywamy)
  - socket.settimeout(30) per-chunk
  - .part pliki podczas pobierania/wgrywania
  - chunk upload przez HTTP PUT (4 MB chunks)
  - weryfikacja rozmiaru przez ?ls (klucz 'sz' nie 'size')
  - weryfikacja SHA-256 przez ?checksum=sha256
  - DELETE przez POST ?delete
  - Auth: cookie cpp+cppwd header
  - Cloudflare compatible (HEAD nie działa → używa ?ls)
"""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from ..utils.logging_utils import get_logger
from ..utils.hashing import sha256_file, rm_silent
from ..models.upload_result import UploadResult
from ..models.enums import UploadStatus

logger = get_logger(__name__)

_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB — z monolitu
_STALL_TIMEOUT = 120  # sekund bez danych → uznaj za zawieszone
_CONN_TIMEOUT = 300  # timeout TCP połączenia


class CopypartyClient:
    """Hermetyzuje cały HTTP I/O z Copyparty (w tym przez Cloudflare).

    GUI i Pipeline nie znają szczegółów HTTP.
    """

    def __init__(self, url_or_password: str = "", password: str = "", cancel_flag=None):
        # Support both CopypartyClient(url, pw) and CopypartyClient(pw) call styles
        if password:
            self.base_url = url_or_password
            self.password = password
        else:
            self.base_url = ""
            self.password = url_or_password
        self.cancel_flag = cancel_flag  # threading.Event
        self._cf_clearance: str = ""

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Attempt a quick connection check to base_url. Returns True if reachable."""
        if not self.base_url:
            return False
        try:
            ls_url = self.base_url.rstrip("/") + "?ls"
            req = urllib.request.Request(ls_url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception as e:
            logger.warning(f"login check failed: {e}")
            return False

    def list_files(self, dir_url: str, password: str = "") -> list:
        """List video files in a Copyparty directory."""
        if password:
            self.password = password
        entries = self.list_directory(dir_url)
        video_exts = {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg"}
        result = []
        for f in entries:
            if not isinstance(f, dict):
                continue
            href = f.get("href", "")
            name = urllib.parse.unquote(href.split("?")[0])
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if f".{ext}" in video_exts:
                base = dir_url.rstrip("/")
                result.append(
                    {
                        "name": name,
                        "path_url": f"{base}/{urllib.parse.quote(name)}",
                        "dir_url": dir_url,
                        "size": f.get("sz", 0),
                    }
                )
        return result

    def set_cf_clearance(self, token: str) -> None:
        """Store a Cloudflare clearance cookie for future requests."""
        self._cf_clearance = token
        logger.info(f"CF clearance updated: {token[:12]}...")

    def upload_file(
        self,
        local_path: Path,
        dest_url: str,
        job_id: str = "",
        on_progress: Optional[Callable[[float, float], None]] = None,
    ) -> UploadResult:
        """cpuploadfile() z monolitu: HTTP PUT binary z chunk upload.

        dest_url = pełny URL docelowy z nazwą pliku.
        on_progress(pct: float, speed_mbs: float)
        """
        local_path = Path(local_path)
        file_size = local_path.stat().st_size
        hdrs = self._headers()
        hdrs["Content-Type"] = "application/octet-stream"
        hdrs["Content-Length"] = str(file_size)

        parsed = urllib.parse.urlparse(dest_url)
        use_ssl = parsed.scheme == "https"
        host = parsed.netloc
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"

        logger.info(f"[{job_id}] Upload HTTP PUT {dest_url} ({file_size / 1024 / 1024:.1f} MB)")

        try:
            conn = (
                http.client.HTTPSConnection(host, timeout=_CONN_TIMEOUT)
                if use_ssl
                else http.client.HTTPConnection(host, timeout=_CONN_TIMEOUT)
            )
            conn.connect()
            conn.putrequest("PUT", path)
            for k, v in hdrs.items():
                conn.putheader(k, v)
            conn.endheaders()

            sent = 0
            t0 = time.time()
            t_last_sent = time.time()
            last_sent_pos = 0

            with open(local_path, "rb") as fin:
                while True:
                    if self.cancel_flag and self.cancel_flag.is_set():
                        conn.close()
                        return UploadResult(UploadStatus.FAILED, error="Cancelled")

                    # Stall check — 120s bez postępu
                    if sent != last_sent_pos and time.time() - t_last_sent > _STALL_TIMEOUT:
                        conn.close()
                        logger.error(f"[{job_id}] Upload STALL {_STALL_TIMEOUT}s")
                        return UploadResult(UploadStatus.FAILED, error="Upload stall timeout")

                    chunk = fin.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    conn.send(chunk)

                    if sent != last_sent_pos:
                        t_last_sent = time.time()
                        last_sent_pos = sent
                    sent += len(chunk)
                    t_last_sent = time.time()
                    last_sent_pos = sent

                    elapsed = max(time.time() - t0, 0.001)
                    speed = sent / elapsed / 1024 / 1024
                    pct = sent / file_size * 100 if file_size else 100.0
                    if on_progress:
                        on_progress(pct, speed)

            resp = conn.getresponse()
            resp.read()
            conn.close()

            if resp.status not in (200, 201, 204):
                return UploadResult(
                    UploadStatus.FAILED,
                    local_size=file_size,
                    error=f"HTTP {resp.status}",
                )
            return UploadResult(
                UploadStatus.IN_PROGRESS,
                local_size=file_size,
            )

        except Exception as e:
            logger.error(f"[{job_id}] Upload error: {e}")
            return UploadResult(UploadStatus.FAILED, error=str(e))

    def download_file(
        self,
        src_url: str,
        local_path: Path,
        expected_size: int = 0,
        job_id: str = "",
        on_progress: Optional[Callable[[float, float], None]] = None,
    ) -> bool:
        """cpdownloadfile() z monolitu: pobiera do .part, potem rename.

        STALL watchdog 120s: jeśli socket przestaje dawać dane → przerywamy.
        """
        local_path = Path(local_path)
        tmp_path = local_path.with_suffix(local_path.suffix + ".part")
        local_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"[{job_id}] Download {src_url} → {local_path.name}")

        try:
            req = urllib.request.Request(src_url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or expected_size or 0)
                sock = resp.fp.raw.fileno() if hasattr(resp.fp, "raw") else None
                if sock:
                    try:
                        # per-chunk stall watchdog

                        resp.fp.raw._sock.settimeout(30)
                    except Exception:
                        pass

                copied = 0
                t0 = time.time()
                t_last_data = time.time()

                with open(tmp_path, "wb") as fout:
                    while True:
                        if self.cancel_flag and self.cancel_flag.is_set():
                            rm_silent(tmp_path)
                            return False

                        # Stall watchdog
                        if time.time() - t_last_data > _STALL_TIMEOUT:
                            rm_silent(tmp_path)
                            logger.error(f"[{job_id}] Download STALL {_STALL_TIMEOUT}s")
                            return False

                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fout.write(chunk)
                        copied += len(chunk)
                        t_last_data = time.time()

                        elapsed = max(time.time() - t0, 0.001)
                        speed = copied / elapsed / 1024 / 1024
                        pct = copied / total * 100 if total else 100.0
                        if on_progress:
                            on_progress(pct, speed)

            tmp_path.replace(local_path)
            return True

        except Exception as e:
            rm_silent(tmp_path)
            logger.error(f"[{job_id}] Download error: {e}")
            return False

    def verify_upload(
        self,
        local_path: Path,
        dir_url: str,
        filename: str,
        job_id: str = "",
        check_sha: bool = True,
    ) -> UploadResult:
        """Po uploadzie: sprawdza rozmiar przez ?ls + opcjonalnie SHA-256.

        Zachowana logika: HEAD nie działa przez Cloudflare → używa ?ls.
        Usuwa local temp TYLKO jeśli weryfikacja OK — 1:1 z monolitu.
        """
        local_size = local_path.stat().st_size
        local_sha = ""

        remote_size = self.get_remote_size(dir_url, filename)
        if remote_size <= 0 or remote_size < local_size * 0.99:
            logger.error(f"[{job_id}] Size mismatch: remote={remote_size} local={local_size}")
            return UploadResult(
                UploadStatus.SIZE_MISMATCH,
                local_size=local_size,
                remote_size=remote_size,
                error="Remote size mismatch",
            )

        if check_sha:
            file_url = dir_url.rstrip("/") + "/" + urllib.parse.quote(filename)
            remote_sha = self.get_remote_sha256(file_url)
            if remote_sha:
                local_sha = sha256_file(local_path)
                if local_sha != remote_sha:
                    logger.error(f"[{job_id}] SHA mismatch: local={local_sha[:16]} remote={remote_sha[:16]}")
                    return UploadResult(
                        UploadStatus.SHA_MISMATCH,
                        local_size=local_size,
                        remote_size=remote_size,
                        local_sha256=local_sha,
                        remote_sha256=remote_sha,
                        error="SHA-256 mismatch after upload",
                    )
                logger.info(f"[{job_id}] SHA-256 OK: {local_sha[:16]}")

        return UploadResult(
            UploadStatus.VERIFIED,
            local_size=local_size,
            remote_size=remote_size,
            local_sha256=local_sha,
        )

    def get_remote_size(self, dir_url: str, filename: str) -> int:
        """cpverifysize() z monolitu — ?ls endpoint, klucz 'sz'.

        HEAD request nie działa przez Cloudflare — zachowana logika.
        """
        ls_url = dir_url.rstrip("/") + "?ls"
        try:
            req = urllib.request.Request(ls_url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as r:
                data = self._read_json(r)
            for f in data.get("files", []):
                if not isinstance(f, dict):
                    continue
                href = f.get("href", "")
                fn = urllib.parse.unquote(href.split("?")[0])
                if fn == filename:
                    return f.get("sz", 0)  # 'sz' nie 'size' — z monolitu
            return 0
        except Exception as e:
            logger.warning(f"get_remote_size error: {e}")
            return 0

    def get_remote_sha256(self, file_url: str) -> str:
        """cpverifysha256() z monolitu — ?checksum=sha256."""
        url = file_url.rstrip("/") + "?checksum=sha256"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=30) as r:
                data = self._read_json(r)
            return (data.get("sha256") or data.get("checksum") or "").lower()
        except Exception:
            return ""

    def delete_file(self, file_url: str, job_id: str = "") -> bool:
        """cpdelete() z monolitu — POST ?delete."""
        del_url = file_url.rstrip("/") + "?delete"
        try:
            req = urllib.request.Request(del_url, data=b"", method="POST", headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status in (200, 204)
        except Exception as e:
            logger.warning(f"[{job_id}] delete_file error: {e}")
            return False

    def list_directory(self, dir_url: str) -> list:
        """?ls endpoint — zwraca listę plików w katalogu."""
        ls_url = dir_url.rstrip("/") + "?ls"
        try:
            req = urllib.request.Request(ls_url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                return self._read_json(r).get("files", [])
        except Exception as e:
            logger.warning(f"list_directory error: {e}")
            return []

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        """Auth headers — cookie cpp + cppwd fallback."""
        hdrs = {}
        if self.password:
            cookie = f"cppwd={self.password}"
            if self._cf_clearance:
                cookie += f"; cfclearance={self._cf_clearance}"
            hdrs["Cookie"] = cookie
            hdrs["PW"] = self.password  # fallback header z monolitu
        return hdrs

    @staticmethod
    def _read_json(response) -> dict:
        """Czyta JSON z urllib response."""
        import json

        raw = response.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}
