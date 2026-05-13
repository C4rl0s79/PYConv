"""CopypartyClient – single class owning ALL Copyparty HTTP logic.

Pipeline workers call methods on this object.
They never build HTTP requests themselves.
"""
from __future__ import annotations
import os
import json
import gzip
import time
import socket
import hashlib
import base64
import http.client
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
from pathlib import Path
from typing import Callable, Optional

from utils.logging_utils import get_logger
from utils.hashing import rm_silent
from models.encode_result import UploadResult
from models.enums import UploadStatus

log = get_logger("copyparty")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


class CopypartyClient:
    """HTTP client for Copyparty: upload, download, verify, delete, list."""

    CHUNK_SIZE: int = 4 * 1024 * 1024      # 4 MB read/write chunks
    DOWNLOAD_STALL_TIMEOUT: int = 120       # seconds without data → abort download
    UPLOAD_STALL_TIMEOUT: int = 120         # seconds without send progress → abort upload
    SOCKET_TIMEOUT: int = 30               # per-chunk socket timeout
    CONNECT_TIMEOUT: int = 60              # urllib.urlopen connection timeout

    def __init__(
        self,
        session: dict | None = None,
        password: str = "",
    ) -> None:
        self._session: dict = session or {}
        self._password = password

    # ── Session management ───────────────────────────────────────────────────────

    def login(self, base_url: str, password: str, timeout: int = 15) -> bool:
        """POST login to Copyparty. Updates internal session on success."""
        if not password:
            return False
        parsed = urllib.parse.urlparse(base_url)
        login_url = f"{parsed.scheme}://{parsed.netloc}/"
        bnd = "----CopypartyLoginBnd"
        body = (
            f"--{bnd}\r\n"
            f'Content-Disposition: form-data; name="cppwd"\r\n\r\n'
            f"{password}\r\n"
            f"--{bnd}--\r\n"
        ).encode("utf-8")
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(
            login_url, data=body, method="POST",
            headers={
                "User-Agent": _UA,
                "Content-Type": f"multipart/form-data; boundary={bnd}",
                "Accept": "*/*",
            },
        )
        try:
            opener.open(req, timeout=timeout)
            result: dict = {}
            for cookie in cj:
                if cookie.name in ("cppws", "cppwd", "cf_clearance"):
                    result[cookie.name] = cookie.value
            if result.get("cppws") or result.get("cppwd"):
                self._session = result
                self._password = password
                log.info("Copyparty login OK: %s", base_url)
                return True
        except Exception as exc:
            log.warning("Copyparty login failed: %s", exc)
        return False

    # ── Download ───────────────────────────────────────────────────────────────────

    def download_file(
        self,
        url: str,
        local_path: str,
        total_size: int,
        on_progress: Optional[Callable[[float, float], None]] = None,
        cancel_flag=None,
    ) -> bool:
        """Download file from Copyparty with stall detection.

        - Writes to local_path + '.part'; renames on success.
        - stall watchdog: no data for DOWNLOAD_STALL_TIMEOUT seconds → abort.
        - socket.settimeout(30) per-chunk so resp.read() never hangs forever.
        Returns True on success.
        """
        hdrs = self._headers()
        tmp_path = local_path + ".part"
        copied = 0
        t0 = time.time()
        t_last_data = time.time()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=self.CONNECT_TIMEOUT) as resp, \
                    open(tmp_path, "wb") as fout:
                try:
                    resp.fp.raw._sock.settimeout(self.SOCKET_TIMEOUT)
                except Exception:
                    pass
                while True:
                    if cancel_flag and cancel_flag.is_set():
                        fout.close()
                        rm_silent(tmp_path)
                        return False
                    if time.time() - t_last_data > self.DOWNLOAD_STALL_TIMEOUT:
                        fout.close()
                        rm_silent(tmp_path)
                        log.error(
                            "Download STALL (%ds): %s",
                            self.DOWNLOAD_STALL_TIMEOUT,
                            os.path.basename(local_path),
                        )
                        return False
                    try:
                        chunk = resp.read(self.CHUNK_SIZE)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    fout.write(chunk)
                    copied += len(chunk)
                    t_last_data = time.time()
                    if on_progress:
                        elapsed = max(time.time() - t0, 0.001)
                        speed = copied / elapsed / 1024 / 1024
                        pct = copied / total_size * 100 if total_size else 100.0
                        on_progress(pct, speed)
            os.replace(tmp_path, local_path)
            return True
        except Exception as exc:
            rm_silent(tmp_path)
            log.error("Download error: %s", exc)
            return False

    # ── Upload ────────────────────────────────────────────────────────────────────

    def upload_file(
        self,
        local_path: str,
        dest_url: str,
        on_progress: Optional[Callable[[float, float], None]] = None,
        cancel_flag=None,
    ) -> UploadResult:
        """Upload file via HTTP PUT with stall detection.

        Returns UploadResult; call verify_upload() afterwards before deleting local file.
        """
        file_size = os.path.getsize(local_path)
        hdrs = self._headers()
        hdrs["Content-Type"] = "application/octet-stream"
        hdrs["Content-Length"] = str(file_size)
        sent = 0
        t0 = time.time()
        t_last_sent = time.time()
        last_sent_pos = 0

        try:
            parsed = urllib.parse.urlparse(dest_url)
            use_ssl = parsed.scheme == "https"
            host = parsed.netloc
            path = parsed.path
            if parsed.query:
                path += "?" + parsed.query

            conn = (
                http.client.HTTPSConnection(host, timeout=300)
                if use_ssl
                else http.client.HTTPConnection(host, timeout=300)
            )
            conn.connect()
            conn.putrequest("PUT", path)
            for k, v in hdrs.items():
                conn.putheader(k, v)
            conn.endheaders()

            with open(local_path, "rb") as fin:
                while True:
                    if cancel_flag and cancel_flag.is_set():
                        conn.close()
                        return UploadResult(status=UploadStatus.CANCELLED)
                    if sent == last_sent_pos and time.time() - t_last_sent > self.UPLOAD_STALL_TIMEOUT:
                        conn.close()
                        log.error(
                            "Upload STALL (%ds): %s",
                            self.UPLOAD_STALL_TIMEOUT,
                            os.path.basename(local_path),
                        )
                        return UploadResult(status=UploadStatus.STALLED)
                    chunk = fin.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    conn.send(chunk)
                    if sent != last_sent_pos:
                        t_last_sent = time.time()
                        last_sent_pos = sent
                    sent += len(chunk)
                    t_last_sent = time.time()
                    last_sent_pos = sent
                    if on_progress:
                        elapsed = max(time.time() - t0, 0.001)
                        speed = sent / elapsed / 1024 / 1024
                        pct = sent / file_size * 100 if file_size else 100.0
                        on_progress(pct, speed)

            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status in (200, 201, 204):
                return UploadResult(
                    status=UploadStatus.DONE,
                    local_size=file_size,
                    dest_url=dest_url,
                )
            return UploadResult(
                status=UploadStatus.FAILED,
                error_msg=f"HTTP {resp.status}",
            )
        except Exception as exc:
            log.error("Upload error: %s", exc)
            return UploadResult(status=UploadStatus.FAILED, error_msg=str(exc))

    # ── Verify ────────────────────────────────────────────────────────────────────

    def verify_upload(
        self,
        dir_url: str,
        fname: str,
        local_size: int,
    ) -> bool:
        """Verify uploaded file size via /?ls. Returns True if remote_size == local_size."""
        remote_size = self.get_remote_size(dir_url, fname)
        if remote_size == local_size:
            return True
        log.warning(
            "Size mismatch after upload: local=%d remote=%d fname=%s",
            local_size, remote_size, fname,
        )
        return False

    def get_remote_size(self, dir_url: str, fname: str) -> int:
        """Query /?ls and return the 'sz' field for *fname*. Returns 0 on error."""
        ls_url = dir_url.rstrip("/") + "/?ls"
        req = urllib.request.Request(ls_url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = self._read_json(r)
            for f in data.get("files", []):
                if not isinstance(f, dict):
                    continue
                href_f = f.get("href", "")
                fn = urllib.parse.unquote(href_f.split("?")[0])
                if fn == fname:
                    return f.get("sz", 0)
        except Exception as exc:
            log.warning("get_remote_size error: %s", exc)
        return 0

    # ── Delete ───────────────────────────────────────────────────────────────────

    def delete_file(self, url: str) -> bool:
        """Delete a remote file via POST ?delete."""
        del_url = url.rstrip("/") + "?delete"
        req = urllib.request.Request(
            del_url, data=b"", method="POST", headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status in (200, 204)
        except Exception as exc:
            log.warning("delete_file error: %s", exc)
            return False

    # ── List ────────────────────────────────────────────────────────────────────

    def list_files(self, base_url: str) -> list[dict]:
        """Recursively list all supported media files under *base_url*."""
        from config.constants import SUPPORTED_EXTS
        results: list[dict] = []

        def _recurse(url: str) -> None:
            ls_url = url.rstrip("/") + "/?ls"
            req = urllib.request.Request(ls_url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = self._read_json(r)
            except Exception as exc:
                log.warning("list_files error at %s: %s", ls_url, exc)
                return
            for d in data.get("dirs", []):
                if not isinstance(d, dict):
                    continue
                href = d.get("href", "")
                dn = urllib.parse.unquote(href).rstrip("/")
                if not dn or dn.startswith("."):
                    continue
                sub_url = url.rstrip("/") + "/" + urllib.parse.quote(dn, safe="")
                _recurse(sub_url)
            for f in data.get("files", []):
                if not isinstance(f, dict):
                    continue
                href_f = f.get("href", "")
                if not href_f:
                    continue
                fn = urllib.parse.unquote(href_f.split("?")[0])
                if not fn:
                    continue
                from pathlib import Path as _Path
                if _Path(fn).suffix.lower() not in SUPPORTED_EXTS:
                    continue
                file_url = href_f if href_f.startswith("http") else url.rstrip("/") + "/" + href_f
                results.append({
                    "path_url": file_url,
                    "dir_url": url.rstrip("/") + "/",
                    "name": fn,
                    "size": f.get("sz", 0),
                })

        _recurse(base_url)
        return results

    # ── Credentials ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cred_key() -> bytes:
        import socket as _s
        import os as _os
        raw = _s.gethostname() + _os.environ.get("USERNAME", _os.environ.get("USER", "u"))
        return hashlib.sha256(raw.encode()).digest()

    @staticmethod
    def _cred_file() -> str:
        return os.path.join(os.path.expanduser("~"), ".converv_creds")

    def save_credentials(self, url: str) -> None:
        """Persist URL + password + session tokens to ~/.converv_creds."""
        key = self._cred_key()

        def _xor(data: bytes) -> bytes:
            return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

        data: dict = {
            "url": url,
            "password_enc": base64.b64encode(_xor(self._password.encode())).decode(),
            "version": 3,
        }
        for k in ("cppws", "cppwd"):
            if self._session.get(k):
                data[f"{k}_enc"] = base64.b64encode(
                    _xor(self._session[k].encode())
                ).decode()
        try:
            with open(self._cred_file(), "w", encoding="utf-8") as f:
                json.dump(data, f)
            try:
                os.chmod(self._cred_file(), 0o600)
            except Exception:
                pass
        except Exception as exc:
            log.warning("save_credentials error: %s", exc)

    def load_credentials(self) -> tuple[str, str, dict]:
        """Load URL + password + session from ~/.converv_creds."""
        path = self._cred_file()
        if not os.path.exists(path):
            return "", "", {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = self._cred_key()

            def _xor(data_b: bytes) -> bytes:
                return bytes(b ^ key[i % len(key)] for i, b in enumerate(data_b))

            pw = ""
            if data.get("password_enc"):
                pw = _xor(base64.b64decode(data["password_enc"])).decode("utf-8")
            session: dict = {}
            for k in ("cppws", "cppwd"):
                enc_k = f"{k}_enc"
                if data.get(enc_k):
                    session[k] = _xor(base64.b64decode(data[enc_k])).decode("utf-8")
            return data.get("url", ""), pw, session
        except Exception as exc:
            log.warning("load_credentials error: %s", exc)
            return "", "", {}

    def delete_credentials(self) -> None:
        try:
            os.remove(self._cred_file())
        except Exception:
            pass

    # ── Internals ─────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {"User-Agent": _UA, "Accept": "*/*"}
        if self._session:
            parts = []
            for k in ("cppws", "cppwd"):
                if self._session.get(k):
                    parts.append(f"{k}={self._session[k]}")
            if self._session.get("cf_clearance"):
                parts.append(f"cf_clearance={self._session['cf_clearance']}")
            if parts:
                h["Cookie"] = "; ".join(parts)
        if self._password:
            h["PW"] = self._password
        return h

    @staticmethod
    def _read_json(response) -> dict:
        raw = response.read()
        enc = (response.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
