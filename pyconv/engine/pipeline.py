"""PipelineWorker i SequentialWorker — logika przetwarzania plików.

Wyodrębniony z monolitu: worker() i workerpipeline().

Architektura PipelineWorker (tryb sieć):

  PREFETCH ──encodeq(max=1)──► ENCODE ──uploadq(max=2)──► UPLOAD
                 ◄──────prefetchsem(1)───◄

Semafor zapewnia że pobieramy następny plik DOPIERO gdy encoder
zwalnia slot → maks. 2 pliki lokalne na raz (1 pobrany + 1 enkodowany).

Dwa GPU: wspólny workqueue, każdy ma własny downloadlock (równoległe
pobieranie), wspólny upload_lock (serializacja — serwer nie przeciążony).
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..models.enums import EncoderType, UploadStatus
from ..models.media_info import MediaInfo
from ..utils.filename import safe_filename
from ..utils.hashing import rm_silent, sha256_file
from ..utils.logging_utils import get_logger
from .cq_selector import CQMAX, CQSelector
from .progress import ProgressTracker

logger = get_logger(__name__)

TMPSUFFIX = "__PYCONVTMP"


@dataclass
class PipelineConfig:
    """Konfiguracja pipeline — jeden per GPU."""

    encoder: EncoderType
    gpu_label: str
    cq: Optional[int]
    tmpdir: Path
    min_savings: float
    keep_orig: bool = False
    hq_mode: bool = False
    vmaf_target: float = 0.0
    test_mode: bool = False
    use_copyparty: bool = False
    cp_src_url: str = ""
    cp_password: str = ""
    download_lock: Optional[threading.Lock] = None
    upload_lock: Optional[threading.Lock] = None
    copy_lock: Optional[threading.Lock] = None
    cancel_flag: Optional[threading.Event] = None
    # Phase-specific progress callbacks (set by gui)
    on_copy_progress: Optional[Callable] = None    # (pct, label) → Kopiowanie bar
    on_encode_progress: Optional[Callable] = None  # (pct, label) → GPU1/GPU2 bar
    on_upload_progress: Optional[Callable] = None  # (pct, label) → Upload bar
    on_file_done: Optional[Callable] = None        # (done_n, total_n) → Łącznie bar


class _WorkerBase:
    """Wspólna logika CQ resolution dla obu workerów."""

    cq_selector: CQSelector
    on_row_update: Callable

    def _resolve_cq(
        self,
        cfg: PipelineConfig,
        info: dict,
        local_src: Path,
        label: str,
        duration: float,
    ) -> int:
        """Dobierz CQ: auto → HQ complexity → VMAF target search.

        Wspólna implementacja dla SequentialWorker i PipelineWorker.
        """
        file_cq = cfg.cq
        if file_cq is None:
            src_size = info.get("size", 0)
            mi = MediaInfo(
                path=local_src,
                size_bytes=src_size,
                duration_seconds=duration,
                video_codec=info.get("codec", "h264"),
                height=info.get("height", 1080),
                width=info.get("width", 0),
                fps=info.get("fps", 0.0),
                bitrate_kbps=info.get("bitratekbps", 0.0),
                bitdepth=info.get("bitdepth", 8),
            )
            file_cq = self.cq_selector.auto_cq(
                cfg.encoder,
                mi.height,
                mi.bitrate_kbps,
                mi.width,
                mi.fps,
                mi.video_codec,
            )

        # HQ: complexity probe (scene change rate)
        if cfg.hq_mode and cfg.cq is None:
            try:
                cmplx = self.cq_selector.complexity_probe(local_src, duration)
                adj = 0 if "qsv" in cfg.encoder.value else CQSelector.hq_cq_adjustment(cmplx)
                file_cq = max(1, min(CQMAX.get(cfg.encoder.value, 51), file_cq + adj))
                logger.info(f"[{label}] HQ complexity={cmplx:.2f} adj={adj} CQ={file_cq}")
            except Exception as e:
                logger.warning(f"[{label}] HQ probe błąd: {e}")

        # HQ: VMAF binary search (działa zarówno z auto CQ jak i ręcznym CQ)
        if cfg.hq_mode and cfg.vmaf_target > 0 and duration >= 60:
            try:
                logger.info(f"[{label}] VMAF target search start: target={cfg.vmaf_target:.0f} cq_start={file_cq}")
                found = self.cq_selector.vmaf_target_search(
                    local_src,
                    cfg.encoder,
                    file_cq,
                    duration,
                    cfg.vmaf_target,
                    label,
                    cfg.tmpdir,
                )
                if found:
                    file_cq = found
                    self.on_row_update(
                        info.get("rowid"),
                        status=f"{label} CQ={file_cq} VMAF={cfg.vmaf_target:.0f}",
                    )
                else:
                    logger.warning(f"[{label}] VMAF search nie znalazł CQ — używam CQ={file_cq}")
            except Exception as e:
                logger.warning(f"[{label}] VMAF search błąd: {e}")
        elif cfg.vmaf_target > 0 and duration < 60:
            logger.info(f"[{label}] VMAF search pominięty: plik za krótki ({duration:.0f}s < 60s)")

        return file_cq


class SequentialWorker(_WorkerBase):
    """worker() z monolitu — tryb lokalny / zamontowany dysk sieciowy."""

    def __init__(
        self,
        config: PipelineConfig,
        ffmpeg,
        cq_selector: CQSelector,
        tracker: ProgressTracker,
        total: int,
        on_row_update: Optional[Callable] = None,
        on_progress_update: Optional[Callable] = None,
    ):
        self.cfg = config
        self.ffmpeg = ffmpeg
        self.cq_selector = cq_selector
        self.tracker = tracker
        self.total = total
        self.on_row_update = on_row_update or (lambda *a, **kw: None)
        self.on_progress_update = on_progress_update or (lambda *a, **kw: None)
        self.on_encode_progress = config.on_encode_progress or (lambda *a, **kw: None)
        self._on_file_done = config.on_file_done  # (done_n, total_n)
        self._done_count = 0
        self._done_lock = threading.Lock()

    def _file_done(self) -> None:
        """Thread-safe: increment done counter and push to Łącznie bar."""
        with self._done_lock:
            self._done_count += 1
            n = self._done_count
        if self._on_file_done:
            self._on_file_done(n, self.total)

    def run(self, work_queue: queue.Queue) -> None:
        cfg = self.cfg
        label = cfg.gpu_label

        while not (cfg.cancel_flag and cfg.cancel_flag.is_set()):
            try:
                idx, info = work_queue.get_nowait()
            except queue.Empty:
                break

            src_path = Path(info["path"])
            fname = src_path.name
            stem_safe = safe_filename(src_path.stem, maxlen=80)
            src_size = info.get("size", src_path.stat().st_size)
            duration = info.get("duration", 0.0)

            tmp_out: Optional[Path] = None
            local_src = src_path
            _tmp_out_ref: list = [None]
            _local_src_ref: list = [local_src]

            def cleanup_tmp(
                restore_original: bool = False,
                _t=_tmp_out_ref,
                _l=_local_src_ref,
                _sp=src_path,
                _fn=fname,
                _lb=label,
                _cfg=cfg,
            ):
                for p in [_t[0], (_l[0] if _l[0] != _sp else None)]:
                    if p and p.exists():
                        if restore_original and p == _l[0] and _cfg.use_copyparty:
                            try:
                                shutil.move(str(_l[0]), str(_sp))
                                logger.warning(f"[{_lb}] Oryginał przywrócony: {_fn}")
                            except Exception as e:
                                logger.error(f"[{_lb}] Nie można przywrócić! {e}")
                        else:
                            rm_silent(p)

            # --- CQ resolution (wspólna logika) ---
            file_cq = self._resolve_cq(cfg, info, local_src, label, duration)
            logger.info(f"[{label}] CQ={file_cq} {fname}")
            self.on_row_update(info.get("rowid"), status=f"{label} CQ={file_cq}", gpu=label)

            _idx = idx
            _total = self.total

            def upd_convert(pct: float, _i=_idx, _tot=_total):
                if self.on_encode_progress:
                    self.on_encode_progress(pct, f"Plik {_i + 1}/{_tot} konwersja {pct:.0f}%")

            tmp_out = cfg.tmpdir / f"{stem_safe}{TMPSUFFIX}{label}.mkv"
            _tmp_out_ref[0] = tmp_out

            result = self.ffmpeg.run_encode_with_fallback(
                local_src,
                tmp_out,
                cfg.encoder,
                file_cq,
                job_id=label,
                duration=duration,
                on_progress=upd_convert,
            )

            if result.used_encoder and result.used_encoder != cfg.encoder:
                self.on_row_update(info.get("rowid"), gpu=f"{label}/{result.used_encoder.value}")

            if not result.success or not tmp_out.exists() or tmp_out.stat().st_size < 100 * 1024:
                logger.error(f"[{label}] Wszystkie fallbacki wyczerpane: {fname}")
                self.on_row_update(info.get("rowid"), status="Błąd — fallbacki wyczerpane", tag="error")
                cleanup_tmp(restore_original=True)
                self._file_done()
                work_queue.task_done()
                continue

            new_size = tmp_out.stat().st_size
            savings = 1.0 - new_size / src_size if src_size > 0 else 0.0

            if new_size > src_size:
                grow = int((new_size - src_size) / src_size * 100)
                logger.info(f"[{label}] Pominięto BIGGER +{grow}%: {fname}")
                self.on_row_update(
                    info.get("rowid"), status=f"Pominięto +{grow}% większy", tag="skip", savings=f"+{grow}%"
                )
                cleanup_tmp()
                self._file_done()
                work_queue.task_done()
                continue

            if savings < cfg.min_savings:
                pcts = int(savings * 100)
                logger.info(f"[{label}] Pominięto oszczędność {pcts}% < min={int(cfg.min_savings * 100)}%: {fname}")
                self.on_row_update(info.get("rowid"), status=f"Pominięto {pcts}%", tag="skip", savings=f"{pcts}%")
                cleanup_tmp()
                self._file_done()
                work_queue.task_done()
                continue

            final = src_path.with_suffix(".mkv")
            ok_mv, mv_result = self._safe_copy_verified(tmp_out, final)
            if not ok_mv:
                logger.error(f"[{label}] Weryfikacja lokalna nieudana: {mv_result}")
                self.on_row_update(info.get("rowid"), status="Błąd zapisu/weryfikacji", tag="error")
                rm_silent(tmp_out)
                self._file_done()
                work_queue.task_done()
                continue

            logger.info(f"[{label}] SHA-256 OK: {mv_result[:16]}")
            rm_silent(tmp_out)

            if src_path != final:
                if cfg.keep_orig:
                    try:
                        shutil.move(str(src_path), str(src_path.with_suffix(".orig")))
                    except Exception as e:
                        logger.warning(f"[{label}] Nie można zachować oryginału: {e}")
                else:
                    rm_silent(src_path)

            pcts = int(savings * 100)
            logger.info(f"[{label}] Gotowe -{pcts}%: {fname}")
            self.on_row_update(info.get("rowid"), status="Gotowe", tag="done", savings=f"-{pcts}%", gpu=label)
            self._file_done()
            work_queue.task_done()

    @staticmethod
    def _safe_copy_verified(src: Path, dst: Path) -> tuple:
        """Kopiuj → weryfikuj SHA-256 → replace."""
        tmp = dst.with_suffix(".part")
        try:
            shutil.copy2(str(src), str(tmp))
            sha = sha256_file(tmp)
            sha_src = sha256_file(src)
            if sha != sha_src:
                rm_silent(tmp)
                return False, f"SHA mismatch: {sha[:16]} vs {sha_src[:16]}"
            tmp.replace(dst)
            return True, sha
        except Exception as e:
            rm_silent(tmp)
            return False, str(e)


class PipelineWorker(_WorkerBase):
    """workerpipeline() z monolitu — tryb sieciowy (Copyparty lub SMB).

    Trzy wątki: PREFETCH → ENCODE → UPLOAD.
    Flow control przez prefetchsem(1):
      - prefetch acquire PRZED pobraniem
      - encode release gdy bierze item z encodeq
    """

    def __init__(
        self,
        config: PipelineConfig,
        ffmpeg,
        cq_selector: CQSelector,
        copyparty,
        tracker: ProgressTracker,
        total: int,
        on_row_update: Optional[Callable] = None,
        on_progress_update: Optional[Callable] = None,
    ):
        self.cfg = config
        self.ffmpeg = ffmpeg
        self.cq_selector = cq_selector
        self.cp = copyparty
        self.tracker = tracker
        self.total = total
        self.on_row_update = on_row_update or (lambda *a, **kw: None)
        self.on_progress_update = on_progress_update or (lambda *a, **kw: None)
        self.test_results: list = []
        self._test_lock = threading.Lock()
        self._on_file_done = config.on_file_done  # (done_n, total_n)
        self._done_count = 0
        self._done_lock = threading.Lock()

    def _file_done(self) -> None:
        """Thread-safe: increment done counter and push to Łącznie bar."""
        with self._done_lock:
            self._done_count += 1
            n = self._done_count
        if self._on_file_done:
            self._on_file_done(n, self.total)

    # ------------------------------------------------------------------
    # Prywatne metody wątków — testowalność > nested functions
    # ------------------------------------------------------------------

    def _prefetch_thread(
        self,
        work_queue: queue.Queue,
        encode_q: queue.Queue,
        prefetch_sem: threading.Semaphore,
    ) -> None:
        cfg = self.cfg
        label = cfg.gpu_label

        while not (cfg.cancel_flag and cfg.cancel_flag.is_set()):
            try:
                idx, info = work_queue.get_nowait()
            except queue.Empty:
                break

            src_path = Path(info["path"])
            fname = src_path.name
            stem_safe = safe_filename(src_path.stem, maxlen=80)
            src_ext = src_path.suffix
            src_size = info.get("size", 0)
            local_src = cfg.tmpdir / f"{stem_safe}__work{label}{src_ext}"

            _idx, _tot = idx, self.total

            def upd_copy(pct: float, spd: float = 0.0, _i=_idx, _t=_tot):
                if cfg.on_copy_progress:
                    cfg.on_copy_progress(pct, f"Plik {_i + 1}/{_t} pobieranie {pct:.0f}%")

            prefetch_sem.acquire()
            if cfg.cancel_flag and cfg.cancel_flag.is_set():
                work_queue.task_done()
                break

            ok = False
            if cfg.use_copyparty and self.cp:
                logger.info(f"[{label}] Pobieranie HTTP pipeline: {fname}")
                self.on_row_update(info.get("rowid"), status="Pobieranie HTTP")
                with cfg.download_lock or threading.Lock():
                    ok = self.cp.download_file(src_path, local_src, src_size, label, on_progress=upd_copy)
            else:
                with cfg.copy_lock or threading.Lock():
                    logger.info(f"[{label}] Kopiowanie pipeline: {fname}")
                    ok = self._copy_with_progress(src_path, local_src, src_size, upd_copy)

            if not ok:
                self.on_row_update(info.get("rowid"), status="Błąd pobierania", tag="error")
                work_queue.task_done()
                prefetch_sem.release()
                continue

            encode_q.put((idx, info, local_src))

        encode_q.put(None)  # sentinel

    def _encode_thread(
        self,
        work_queue: queue.Queue,
        encode_q: queue.Queue,
        upload_q: queue.Queue,
        prefetch_sem: threading.Semaphore,
    ) -> None:
        cfg = self.cfg
        label = cfg.gpu_label

        while not (cfg.cancel_flag and cfg.cancel_flag.is_set()):
            item = encode_q.get()
            if item is None:
                break

            prefetch_sem.release()  # encoder gotowy — pozwól prefetchowi pobrać następny

            idx, info, local_src = item
            src_path = Path(info["path"])
            fname = src_path.name
            stem_safe = safe_filename(src_path.stem, maxlen=80)
            src_size = info.get("size", 0)
            duration = info.get("duration", 0.0)
            tmp_out = cfg.tmpdir / f"{stem_safe}{TMPSUFFIX}{label}.mkv"

            _idx, _tot = idx, self.total

            def upd_convert(pct: float, _i=_idx, _t=_tot):
                if cfg.on_encode_progress:
                    cfg.on_encode_progress(pct, f"Plik {_i + 1}/{_t} konwersja {pct:.0f}%")

            # --- CQ resolution (wspólna logika z _WorkerBase) ---
            file_cq = self._resolve_cq(cfg, info, local_src, label, duration)
            logger.info(f"[{label}] CQ={file_cq} {fname}")
            self.on_row_update(info.get("rowid"), status=f"{label} CQ={file_cq}", gpu=label)

            result = self.ffmpeg.run_encode_with_fallback(
                local_src,
                tmp_out,
                cfg.encoder,
                file_cq,
                job_id=label,
                duration=duration,
                on_progress=upd_convert,
            )

            if result.used_encoder and result.used_encoder != cfg.encoder:
                self.on_row_update(info.get("rowid"), gpu=f"{label}/{result.used_encoder.value}")

            if not result.success or not tmp_out.exists() or tmp_out.stat().st_size < 100 * 1024:
                logger.error(f"[{label}] Wszystkie fallbacki wyczerpane: {fname}")
                self.on_row_update(info.get("rowid"), status="Błąd — fallbacki wyczerpane", tag="error")
                rm_silent(tmp_out)
                rm_silent(local_src)
                self._file_done()
                work_queue.task_done()
                continue

            new_size = tmp_out.stat().st_size
            savings = 1.0 - new_size / src_size if src_size > 0 else 0.0

            if new_size > src_size:
                grow = int((new_size - src_size) / src_size * 100)
                logger.info(f"[{label}] Pominięto BIGGER +{grow}%: {fname}")
                self.on_row_update(
                    info.get("rowid"), status=f"Pominięto +{grow}% większy", tag="skip", savings=f"+{grow}%"
                )
                rm_silent(tmp_out)
                rm_silent(local_src)
                self._file_done()
                work_queue.task_done()
                continue

            if savings < cfg.min_savings:
                pcts = int(savings * 100)
                logger.info(f"[{label}] Pominięto oszcz. {pcts}%: {fname}")
                self.on_row_update(info.get("rowid"), status=f"Pominięto {pcts}%", tag="skip", savings=f"{pcts}%")
                rm_silent(tmp_out)
                rm_silent(local_src)
                self._file_done()
                work_queue.task_done()
                continue

            _idx2, _tot2 = idx, self.total

            def upd_out(pct: float, spd: float = 0.0, _i=_idx2, _t=_tot2):
                if cfg.on_upload_progress:
                    cfg.on_upload_progress(pct, f"Plik {_i + 1}/{_t} upload {pct:.0f}%")

            upload_q.put((idx, info, tmp_out, local_src, src_path, fname, new_size, savings, file_cq, upd_out))

        upload_q.put(None)  # sentinel

    def _upload_thread(
        self,
        work_queue: queue.Queue,
        upload_q: queue.Queue,
    ) -> None:
        cfg = self.cfg
        label = cfg.gpu_label

        while True:
            item = upload_q.get()
            if item is None:
                break

            idx, info, tmp_out, local_src, src_path, fname, new_size, savings, file_cq, upd_out = item

            if cfg.test_mode:
                try:
                    vmaf_val = self.ffmpeg.run_vmaf(local_src, tmp_out, 60, label) or 0.0
                except Exception:
                    vmaf_val = 0.0
                entry = {
                    "fname": fname,
                    "encoder": cfg.encoder.value,
                    "gpu": label,
                    "cq": file_cq,
                    "srcsizemb": round(info.get("size", 0) / 1024 / 1024, 2),
                    "outsizemb": round(new_size / 1024 / 1024, 2),
                    "savingspct": int(savings * 100),
                    "vmaf": round(vmaf_val, 4),
                }
                with self._test_lock:
                    self.test_results.append(entry)
                pcts = int(savings * 100)
                logger.info(f"[{label}] TEST VMAF={vmaf_val:.2f} -{pcts}% CQ={file_cq}: {fname}")
                self.on_row_update(
                    info.get("rowid"), status=f"VMAF={vmaf_val:.2f} -{pcts}%", tag="done", savings=f"-{pcts}%"
                )
                upd_out(100)
                self._file_done()
                work_queue.task_done()
                continue

            if cfg.use_copyparty and self.cp:
                cp_name = info.get("cpname", fname)
                out_fname = Path(cp_name).stem + ".mkv"
                dir_url = info.get("cpdir", cfg.cp_src_url).rstrip("/")
                logger.info(f"[{label}] Upload HTTP pipeline: {dir_url}/{out_fname}")
                self.on_row_update(info.get("rowid"), status="Upload HTTP")

                with cfg.upload_lock or threading.Lock():
                    file_url = f"{dir_url}/{out_fname}"
                    up_result = self.cp.upload_file(tmp_out, file_url, label, on_progress=upd_out)
                if up_result.status not in (UploadStatus.VERIFIED, UploadStatus.IN_PROGRESS):
                    logger.warning(f"[{label}] Błąd upload: {out_fname}")
                    self.on_row_update(info.get("rowid"), status="Błąd upload", tag="error")
                    self._file_done()
                    work_queue.task_done()
                    continue

                # Signal SHA check on upload bar
                self.on_row_update(info.get("rowid"), status="SHA-256 sprawdzanie...")
                if cfg.on_upload_progress:
                    cfg.on_upload_progress(100, f"Plik {idx + 1}/{self.total} SHA-256...")

                verify = self.cp.verify_upload(tmp_out, dir_url, out_fname, label)
                if not verify.ok:
                    logger.error(f"[{label}] Weryfikacja nieudana: {verify.error}")
                    self.on_row_update(info.get("rowid"), status=f"Błąd: {verify.error}", tag="error")
                    self._file_done()
                    work_queue.task_done()
                    continue

                logger.info(f"[{label}] SHA-256 upload OK: {verify.local_sha256[:16]}")
                if cfg.on_upload_progress:
                    cfg.on_upload_progress(100, f"Plik {idx + 1}/{self.total} SHA-256 OK ✓")
                if not cfg.keep_orig:
                    self.cp.delete_file(str(src_path), label)
                    logger.info(f"[{label}] Usunięto oryginał: {cp_name}")
                else:
                    logger.info(f"[{label}] Zachowano oryginał: {cp_name}")
                for p in [tmp_out, local_src]:
                    rm_silent(p)

            else:
                # SMB / mounted — kopia z weryfikacją SHA-256
                dest_net = src_path.with_suffix(".mkv")
                in_place = src_path.resolve() == dest_net.resolve()
                if cfg.on_upload_progress:
                    cfg.on_upload_progress(99, f"Plik {idx + 1}/{self.total} SHA-256...")
                self.on_row_update(info.get("rowid"), status="SHA-256 sprawdzanie...")
                with cfg.copy_lock or threading.Lock():
                    ok = self._copy_with_progress(tmp_out, dest_net, new_size, upd_out, verify_sha=True)

                if not ok or not dest_net.exists():
                    logger.error(f"[{label}] Błąd wysyłania/weryfikacji: {fname}")
                    self.on_row_update(info.get("rowid"), status="Błąd wysyłania", tag="error")
                    self._file_done()
                    work_queue.task_done()
                    continue

                if not in_place:
                    if cfg.keep_orig:
                        try:
                            shutil.move(str(src_path), str(src_path.with_suffix(".orig")))
                        except Exception as e:
                            logger.warning(f"[{label}] Nie można zachować oryginału: {e}")
                    else:
                        rm_silent(src_path)
                else:
                    logger.info(f"[{label}] In-place: oryginał zastąpiony")

                for p in [tmp_out, local_src]:
                    rm_silent(p)

            pcts = int(savings * 100)
            logger.info(f"[{label}] Gotowe -{pcts}%: {fname}")
            self.on_row_update(info.get("rowid"), status="Gotowe", tag="done", savings=f"-{pcts}%", gpu=label)
            self._file_done()
            work_queue.task_done()

    # ------------------------------------------------------------------

    def run(self, work_queue: queue.Queue) -> None:
        """Uruchamia 3 wątki pipeline i czeka na zakończenie UPLOAD."""
        cfg = self.cfg
        label = cfg.gpu_label

        prefetch_sem = threading.Semaphore(1)
        encode_q: queue.Queue = queue.Queue(maxsize=1)
        upload_q: queue.Queue = queue.Queue(maxsize=2)

        t_fetch = threading.Thread(
            target=self._prefetch_thread,
            args=(work_queue, encode_q, prefetch_sem),
            daemon=True,
            name=f"prefetch-{label}",
        )
        t_encode = threading.Thread(
            target=self._encode_thread,
            args=(work_queue, encode_q, upload_q, prefetch_sem),
            daemon=True,
            name=f"encode-{label}",
        )
        t_upload = threading.Thread(
            target=self._upload_thread,
            args=(work_queue, upload_q),
            daemon=True,
            name=f"upload-{label}",
        )
        t_fetch.start()
        t_encode.start()
        t_upload.start()
        t_upload.join()

        if self.cfg.test_mode and self.test_results:
            self._save_test_report(label)

    def _save_test_report(self, label: str) -> None:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        json_path = self.cfg.tmpdir / f"testvmaf_{label}_{ts}.json"
        vmaf_vals = [r["vmaf"] for r in self.test_results if r["vmaf"] > 0]
        sav_vals = [r["savingspct"] for r in self.test_results]
        payload = {
            "runid": ts,
            "gpu_label": label,
            "encoder": self.cfg.encoder.value,
            "total_files": len(self.test_results),
            "summary": {
                "vmaf_min": round(min(vmaf_vals), 4) if vmaf_vals else 0,
                "vmaf_max": round(max(vmaf_vals), 4) if vmaf_vals else 0,
                "vmaf_avg": round(sum(vmaf_vals) / len(vmaf_vals), 4) if vmaf_vals else 0,
                "savings_avg": round(sum(sav_vals) / len(sav_vals), 1) if sav_vals else 0,
            },
            "files": self.test_results,
        }
        try:
            json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            smry = payload["summary"]
            logger.info(
                f"[{label}] Raport: {json_path} "
                f"VMAF avg={smry['vmaf_avg']:.2f} min={smry['vmaf_min']:.2f} "
                f"savings avg={smry['savings_avg']:.1f}%"
            )
        except Exception as e:
            logger.warning(f"[{label}] Błąd zapisu JSON: {e}")

    @staticmethod
    def _copy_with_progress(
        src: Path,
        dst: Path,
        total_size: int,
        on_progress: Optional[Callable] = None,
        verify_sha: bool = False,
    ) -> bool:
        """Kopiowanie z progress callback, opcjonalną weryfikacją SHA-256.

        verify_sha=True: po skopiowaniu weryfikuje SHA-256 src vs dst.
        Używane dla SMB upload aby mieć równoważną jakość z Copyparty.
        """
        CHUNK = 8 * 1024 * 1024
        STALL = 120
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        try:
            copied = 0
            t0 = time.time()
            t_last = time.time()
            with open(src, "rb") as fin, open(tmp, "wb") as fout:
                while True:
                    if time.time() - t_last > STALL:
                        rm_silent(tmp)
                        return False
                    chunk = fin.read(CHUNK)
                    if not chunk:
                        break
                    fout.write(chunk)
                    copied += len(chunk)
                    t_last = time.time()
                    elapsed = max(time.time() - t0, 0.001)
                    speed = copied / elapsed / 1024 / 1024
                    pct = copied / total_size * 100 if total_size else 100.0
                    if on_progress:
                        on_progress(pct, speed)
            if verify_sha:
                sha_src = sha256_file(src)
                sha_dst = sha256_file(tmp)
                if sha_src != sha_dst:
                    logger.error(f"SHA-256 mismatch SMB: {sha_src[:16]} vs {sha_dst[:16]}")
                    rm_silent(tmp)
                    return False
            tmp.replace(dst)
            return True
        except Exception as e:
            logger.error(f"copy_with_progress error: {e}")
            rm_silent(tmp)
            return False
