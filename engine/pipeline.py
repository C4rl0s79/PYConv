"""PipelineWorker i SequentialWorker — logika przetwarzania plików.

Wyodrębniony z monolitu: worker() i workerpipeline().

Architektura PipelineWorker (tryb sieć):

  PREFETCH ──encodeq(max=1)──► ENCODE ──uploadq(max=2)──► UPLOAD
                 ◄──────prefetchsem(1)───◄

Semafor zapewnia że pobieramy następny plik DOPIERO gdy encoder
zwalnia slot → maks. 2 pliki lokalne na raz (1 pobrany + 1 enkodowany).

Dwa GPU: wspólny workqueue, każdy ma własny downloadlock (równoległe
pobieranie), wspólny upload_lock (serializacja — serwer nie przeciążony).

Zachowane 1:1 z monolitu:
  - minsav check (skip jeśli plik większy lub oszczędność < min)
  - keeporig: rename .orig zamiast kasowania
  - testmode: brak uploadu, VMAF JSON raport
  - in-place: src == dest (ta sama ścieżka .mkv)
  - SHA-256 + size verify przed kasowaniem źródła
  - cleanuptmp / restore_original przy błędzie
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from ..utils.logging_utils import get_logger
from ..utils.filename import safe_filename, norm_path
from ..utils.hashing import sha256_file, rm_silent
from ..models.enums import EncoderType, JobStatus
from ..models.job_info import EncodeJob, EncodeResult
from ..models.media_info import MediaInfo
from .progress import ProgressTracker
from .cq_selector import CQSelector

logger = get_logger(__name__)

TMPSUFFIX = "__PYCONVTMP"


@dataclass
class PipelineConfig:
    """Konfiguracja pipeline — jeden per GPU."""
    encoder: EncoderType
    gpu_label: str          # 'GPU1' / 'GPU2'
    cq: Optional[int]       # None = auto
    tmpdir: Path
    min_savings: float      # 0.0 – 1.0 (np. 0.05 = 5%)
    keep_orig: bool = False
    hq_mode: bool = False
    vmaf_target: float = 0.0
    test_mode: bool = False
    use_copyparty: bool = False  # True = HTTP upload, False = local/SMB copy
    cp_src_url: str = ""
    cp_password: str = ""
    download_lock: Optional[threading.Lock] = None   # per-GPU
    upload_lock: Optional[threading.Lock] = None     # wspólny
    copy_lock: Optional[threading.Lock] = None       # dla SMB copy
    cancel_flag: Optional[threading.Event] = None


class SequentialWorker:
    """worker() z monolitu — tryb lokalny / zamontowany dysk sieciowy.

    Przetwarza plik po pliku sekwencyjnie (bez pipeline).
    Używany gdy is_network=False lub is_network=True + nie-Copyparty.
    """

    def __init__(
        self,
        config: PipelineConfig,
        ffmpeg,          # FFmpegEngine
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

    def run(self, work_queue: queue.Queue) -> None:
        """Pętla główna workera — 1:1 z monolitu."""
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

            def cleanup_tmp(restore_original: bool = False):
                for p in [tmp_out, (local_src if local_src != src_path else None)]:
                    if p and p.exists():
                        if restore_original and p == local_src and cfg.use_copyparty:
                            try:
                                shutil.move(str(local_src), str(src_path))
                                logger.warning(f"[{label}] Oryginał przywrócony: {fname}")
                            except Exception as e:
                                logger.error(f"[{label}] Nie można przywrócić! {e}")
                        else:
                            rm_silent(p)

            # --- Wyznacz CQ ---
            file_cq = cfg.cq
            if file_cq is None:
                mi = MediaInfo(
                    path=src_path, size_bytes=src_size, duration_seconds=duration,
                    video_codec=info.get("codec", "h264"),
                    height=info.get("height", 1080), width=info.get("width", 0),
                    fps=info.get("fps", 0.0), bitrate_kbps=info.get("bitratekbps", 0.0),
                    bitdepth=info.get("bitdepth", 8),
                )
                file_cq = self.cq_selector.auto_cq(
                    cfg.encoder, mi.height, mi.bitrate_kbps,
                    mi.width, mi.fps, mi.video_codec,
                )
            logger.info(f"[{label}] CQ={file_cq} {fname}")
            self.on_row_update(info.get("rowid"), status=f"{label} CQ={file_cq}", gpu=label)

            def upd_convert(pct: float):
                t = self.tracker.update(idx, "convert", pct)
                self.on_progress_update(t, f"Plik {idx+1}/{self.total} konwersja {pct:.0f}%")

            # --- HQ: complexity probe ---
            if cfg.hq_mode and cfg.cq is None:
                try:
                    cmplx = self.cq_selector.complexity_probe(local_src, duration)
                    adj = 0 if "qsv" in cfg.encoder.value else CQSelector.hq_cq_adjustment(cmplx)
                    file_cq = max(1, min(CQSelector.CQMAX.get(cfg.encoder.value, 51), file_cq + adj))
                    logger.info(f"[{label}] HQ complexity={cmplx:.2f} adj={adj} CQ={file_cq}")
                except Exception as e:
                    logger.warning(f"[{label}] HQ probe błąd: {e}")

            # --- HQ: VMAF-target search ---
            if cfg.hq_mode and cfg.vmaf_target > 0 and cfg.cq is None and duration >= 60:
                try:
                    found = self.cq_selector.vmaf_target_search(
                        local_src, cfg.encoder, file_cq, duration,
                        cfg.vmaf_target, label, cfg.tmpdir,
                    )
                    if found:
                        file_cq = found
                        self.on_row_update(
                            info.get("rowid"),
                            status=f"{label} CQ={file_cq} VMAF={cfg.vmaf_target:.0f}"
                        )
                except Exception as e:
                    logger.warning(f"[{label}] VMAF search błąd: {e}")

            # --- Enkodowanie ---
            tmp_out = cfg.tmpdir / f"{stem_safe}{TMPSUFFIX}{label}.mkv"
            result: EncodeResult = self.ffmpeg.run_encode_with_fallback(
                local_src, tmp_out, cfg.encoder, file_cq,
                job_id=label, duration=duration,
                on_progress=upd_convert,
            )

            if result.used_encoder and result.used_encoder != cfg.encoder:
                self.on_row_update(info.get("rowid"), gpu=f"{label}/{result.used_encoder.value}")

            if not result.success or not tmp_out.exists() or tmp_out.stat().st_size < 100 * 1024:
                logger.error(f"[{label}] Wszystkie fallbacki wyczerpane: {fname}")
                self.on_row_update(info.get("rowid"), status="Błąd — fallbacki wyczerpane", tag="error")
                cleanup_tmp(restore_original=True)
                upd_convert(100)
                work_queue.task_done()
                continue

            new_size = tmp_out.stat().st_size
            savings = 1.0 - new_size / src_size if src_size > 0 else 0.0

            # --- Skip: plik większy ---
            if new_size > src_size:
                grow = int((new_size - src_size) / src_size * 100)
                logger.info(f"[{label}] Pominięto BIGGER +{grow}%: {fname}")
                self.on_row_update(info.get("rowid"), status=f"Pominięto +{grow}% większy", tag="skip", savings=f"+{grow}%")
                cleanup_tmp()
                work_queue.task_done()
                continue

            # --- Skip: za małe oszczędności ---
            if savings < cfg.min_savings:
                pcts = int(savings * 100)
                logger.info(f"[{label}] Pominięto oszczędność {pcts}% < min={int(cfg.min_savings*100)}%: {fname}")
                self.on_row_update(info.get("rowid"), status=f"Pominięto {pcts}%", tag="skip", savings=f"{pcts}%")
                cleanup_tmp()
                work_queue.task_done()
                continue

            # --- Przesuń / zweryfikuj SHA-256 ---
            final = src_path.with_suffix(".mkv")
            ok_mv, mv_result = self._safe_copy_verified(tmp_out, final)
            if not ok_mv:
                logger.error(f"[{label}] Weryfikacja lokalna nieudana: {mv_result}")
                self.on_row_update(info.get("rowid"), status="Błąd zapisu/weryfikacji", tag="error")
                rm_silent(tmp_out)
                work_queue.task_done()
                continue

            logger.info(f"[{label}] SHA-256 OK: {mv_result[:16]}")
            rm_silent(tmp_out)

            if src_path != final:
                if cfg.keep_orig:
                    try:
                        shutil.move(str(src_path), str(src_path.with_suffix(".orig")))
                    except Exception as e:
                        logger.warning(f"[{label}] Nie można zachować oryginau: {e}")
                else:
                    rm_silent(src_path)

            pcts = int(savings * 100)
            logger.info(f"[{label}] Gotowe -{pcts}%: {fname}")
            self.on_row_update(info.get("rowid"), status="Gotowe", tag="done", savings=f"-{pcts}%", gpu=label)
            upd_convert(100)
            work_queue.task_done()

    @staticmethod
    def _safe_copy_verified(src: Path, dst: Path) -> tuple[bool, str]:
        """safecopyverified() z monolitu: kopiuj → verify SHA-256 → replace."""
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


class PipelineWorker:
    """workerpipeline() z monolitu — tryb sieciowy (Copyparty lub SMB).

    Trzy wątki: PREFETCH → ENCODE → UPLOAD.
    Flow control przez prefetchsem(1):
      - prefetch acquire PRZED pobraniem
      - encode release gdy bierze item z encodeq (encoder gotowy na następny)
    """

    def __init__(
        self,
        config: PipelineConfig,
        ffmpeg,
        cq_selector: CQSelector,
        copyparty,        # CopypartyClient (może być None dla SMB)
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

    def run(self, work_queue: queue.Queue) -> None:
        """Uruchamia 3 wątki pipeline i czeka na zakończenie UPLOAD."""
        cfg = self.cfg
        label = cfg.gpu_label

        prefetch_sem = threading.Semaphore(1)
        encode_q: queue.Queue = queue.Queue(maxsize=1)
        upload_q: queue.Queue = queue.Queue(maxsize=2)  # encoder nie czeka na upload

        def prefetch():
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

                def upd_copy(pct: float, spd: float = 0.0):
                    t = self.tracker.update(idx, "copyin", pct)
                    self.on_progress_update(t, f"Plik {idx+1}/{self.total} pobieranie {pct:.0f}%")

                # Semafor: acquire PRZED pobraniem — blokuje gdy encoder zajęty
                prefetch_sem.acquire()
                if cfg.cancel_flag and cfg.cancel_flag.is_set():
                    work_queue.task_done()
                    break

                ok = False
                if cfg.use_copyparty and self.cp:
                    logger.info(f"[{label}] Pobieranie HTTP pipeline: {fname}")
                    self.on_row_update(info.get("rowid"), status="Pobieranie HTTP")
                    dl_lock = cfg.download_lock or threading.Lock()
                    with dl_lock:
                        ok = self.cp.download_file(
                            src_path, local_src, src_size, label, on_progress=upd_copy
                        )
                else:
                    copy_lock = cfg.copy_lock or threading.Lock()
                    with copy_lock:
                        logger.info(f"[{label}] Kopiowanie pipeline: {fname}")
                        ok = self._copy_with_progress(src_path, local_src, src_size, upd_copy)

                if not ok:
                    self.on_row_update(info.get("rowid"), status="Błąd pobierania", tag="error")
                    work_queue.task_done()
                    prefetch_sem.release()  # nie blokuj całości
                    continue

                encode_q.put((idx, info, local_src))

            encode_q.put(None)  # sentinel

        def encode():
            while not (cfg.cancel_flag and cfg.cancel_flag.is_set()):
                item = encode_q.get()
                if item is None:
                    break

                # Encoder gotowy — release pozwala prefetch pobrać następny
                prefetch_sem.release()

                idx, info, local_src = item
                src_path = Path(info["path"])
                fname = src_path.name
                stem_safe = safe_filename(src_path.stem, maxlen=80)
                src_size = info.get("size", 0)
                duration = info.get("duration", 0.0)

                tmp_out = cfg.tmpdir / f"{stem_safe}{TMPSUFFIX}{label}.mkv"

                def upd_convert(pct: float):
                    t = self.tracker.update(idx, "convert", pct)
                    self.on_progress_update(t, f"Plik {idx+1}/{self.total} konwersja {pct:.0f}%")

                # Wyznacz CQ
                file_cq = cfg.cq
                if file_cq is None:
                    mi = MediaInfo(
                        path=local_src, size_bytes=src_size, duration_seconds=duration,
                        video_codec=info.get("codec", "h264"),
                        height=info.get("height", 1080), width=info.get("width", 0),
                        fps=info.get("fps", 0.0), bitrate_kbps=info.get("bitratekbps", 0.0),
                        bitdepth=info.get("bitdepth", 8),
                    )
                    file_cq = self.cq_selector.auto_cq(
                        cfg.encoder, mi.height, mi.bitrate_kbps,
                        mi.width, mi.fps, mi.video_codec,
                    )
                logger.info(f"[{label}] CQ={file_cq} {fname}")
                self.on_row_update(info.get("rowid"), status=f"{label} CQ={file_cq}", gpu=label)

                # HQ: complexity
                if cfg.hq_mode and cfg.cq is None:
                    try:
                        cmplx = self.cq_selector.complexity_probe(local_src, duration)
                        if "qsv" not in cfg.encoder.value:
                            adj = CQSelector.hq_cq_adjustment(cmplx)
                            from .cq_selector import CQMAX
                            file_cq = max(1, min(CQMAX.get(cfg.encoder.value, 51), file_cq + adj))
                    except Exception as e:
                        logger.warning(f"[{label}] HQ probe błąd: {e}")

                # HQ: VMAF-target
                if cfg.hq_mode and cfg.vmaf_target > 0 and cfg.cq is None and duration >= 60:
                    try:
                        found = self.cq_selector.vmaf_target_search(
                            local_src, cfg.encoder, file_cq, duration,
                            cfg.vmaf_target, label, cfg.tmpdir,
                        )
                        if found:
                            file_cq = found
                    except Exception as e:
                        logger.warning(f"[{label}] VMAF search błąd: {e}")

                # Enkodowanie z fallbackiem
                result: EncodeResult = self.ffmpeg.run_encode_with_fallback(
                    local_src, tmp_out, cfg.encoder, file_cq,
                    job_id=label, duration=duration,
                    on_progress=upd_convert,
                )

                if result.used_encoder and result.used_encoder != cfg.encoder:
                    self.on_row_update(info.get("rowid"), gpu=f"{label}/{result.used_encoder.value}")

                if not result.success or not tmp_out.exists() or tmp_out.stat().st_size < 100 * 1024:
                    logger.error(f"[{label}] Wszystkie fallbacki wyczerpane: {fname}")
                    self.on_row_update(info.get("rowid"), status="Błąd — fallbacki wyczerpane", tag="error")
                    rm_silent(tmp_out)
                    rm_silent(local_src)
                    upd_convert(100)
                    work_queue.task_done()
                    continue

                new_size = tmp_out.stat().st_size
                savings = 1.0 - new_size / src_size if src_size > 0 else 0.0

                if new_size > src_size:
                    grow = int((new_size - src_size) / src_size * 100)
                    logger.info(f"[{label}] Pominięto BIGGER +{grow}%: {fname}")
                    self.on_row_update(info.get("rowid"), status=f"Pominięto +{grow}% większy", tag="skip", savings=f"+{grow}%")
                    rm_silent(tmp_out)
                    rm_silent(local_src)
                    work_queue.task_done()
                    continue

                if savings < cfg.min_savings:
                    pcts = int(savings * 100)
                    logger.info(f"[{label}] Pominięto oszcz. {pcts}%: {fname}")
                    self.on_row_update(info.get("rowid"), status=f"Pominięto {pcts}%", tag="skip", savings=f"{pcts}%")
                    rm_silent(tmp_out)
                    rm_silent(local_src)
                    work_queue.task_done()
                    continue

                def upd_out(pct: float, spd: float = 0.0):
                    t = self.tracker.update(idx, "copyout", pct)
                    self.on_progress_update(t, f"Plik {idx+1}/{self.total} upload {pct:.0f}%")

                upload_q.put((idx, info, tmp_out, local_src, src_path, fname, new_size, savings, file_cq, upd_out))

            upload_q.put(None)  # sentinel

        def upload():
            while True:
                item = upload_q.get()
                if item is None:
                    break

                idx, info, tmp_out, local_src, src_path, fname, new_size, savings, file_cq, upd_out = item

                # --- TRYB TESTOWY ---
                if cfg.test_mode:
                    try:
                        vmaf_val = self.ffmpeg.run_vmaf(local_src, tmp_out, 60, label) or 0.0
                    except Exception:
                        vmaf_val = 0.0
                    entry = {
                        "fname": fname, "encoder": cfg.encoder.value,
                        "gpu": label, "cq": file_cq,
                        "srcsizemb": round(info.get("size", 0) / 1024 / 1024, 2),
                        "outsizemb": round(new_size / 1024 / 1024, 2),
                        "savingspct": int(savings * 100),
                        "vmaf": round(vmaf_val, 4),
                    }
                    with self._test_lock:
                        self.test_results.append(entry)
                    pcts = int(savings * 100)
                    logger.info(f"[{label}] TEST VMAF={vmaf_val:.2f} -{pcts}% CQ={file_cq}: {fname}")
                    self.on_row_update(info.get("rowid"), status=f"VMAF={vmaf_val:.2f} -{pcts}%", tag="done", savings=f"-{pcts}%")
                    upd_out(100)
                    work_queue.task_done()
                    continue  # pliki tmp zostają (dla debug)

                # --- Upload Copyparty HTTP ---
                if cfg.use_copyparty and self.cp:
                    cp_name = info.get("cpname", fname)
                    out_fname = Path(cp_name).stem + ".mkv"
                    dir_url = info.get("cpdir", cfg.cp_src_url).rstrip("/")

                    logger.info(f"[{label}] Upload HTTP pipeline: {dir_url}/{out_fname}")
                    self.on_row_update(info.get("rowid"), status="Upload HTTP")

                    ul_lock = cfg.upload_lock or threading.Lock()
                    with ul_lock:  # max 1 upload HTTP naraz
                        file_url = f"{dir_url}/{out_fname}"
                        up_result = self.cp.upload_file(
                            tmp_out, file_url, label, on_progress=upd_out
                        )
                    if not up_result.ok and up_result.status.value != "in_progress":
                        logger.warning(f"[{label}] Błąd upload: {out_fname}")
                        self.on_row_update(info.get("rowid"), status="Błąd upload", tag="error")
                        work_queue.task_done()
                        continue

                    # Weryfikacja po uploadzie
                    verify = self.cp.verify_upload(tmp_out, dir_url, out_fname, label)
                    if not verify.ok:
                        logger.error(f"[{label}] Weryfikacja nieudana: {verify.error}")
                        self.on_row_update(info.get("rowid"), status=f"Błąd: {verify.error}", tag="error")
                        work_queue.task_done()
                        continue

                    logger.info(f"[{label}] SHA-256 upload OK: {verify.local_sha256[:16]}")

                    # Usuń oryginał ze źródła
                    if not cfg.keep_orig:
                        self.cp.delete_file(str(src_path), label)
                        logger.info(f"[{label}] Usunięto oryginał: {cp_name}")
                    else:
                        logger.info(f"[{label}] Zachowano oryginał: {cp_name}")

                    for p in [tmp_out, local_src]:
                        rm_silent(p)

                else:
                    # --- Kopia na sieć (SMB / mounted) ---
                    dest_net = src_path.with_suffix(".mkv")
                    in_place = src_path.resolve() == dest_net.resolve()
                    copy_lock = cfg.copy_lock or threading.Lock()
                    with copy_lock:
                        ok = self._copy_with_progress(tmp_out, dest_net, new_size, upd_out)

                    if not ok or not dest_net.exists():
                        logger.error(f"[{label}] Błąd wysyania: {fname}")
                        self.on_row_update(info.get("rowid"), status="Błąd wysyania", tag="error")
                        work_queue.task_done()
                        continue

                    dest_size = dest_net.stat().st_size
                    if dest_size < new_size * 0.99:
                        logger.error(f"[{label}] Za mały destsize={dest_size} vs {new_size}")
                        self.on_row_update(info.get("rowid"), status="Błąd weryfikacji", tag="error")
                        work_queue.task_done()
                        continue

                    if not in_place:
                        if cfg.keep_orig:
                            try:
                                shutil.move(str(src_path), str(src_path.with_suffix(".orig")))
                            except Exception as e:
                                logger.warning(f"[{label}] Nie można zachować oryginau: {e}")
                        else:
                            rm_silent(src_path)
                    else:
                        logger.info(f"[{label}] In-place: oryginał zastąpiony")

                    for p in [tmp_out, local_src]:
                        rm_silent(p)

                pcts = int(savings * 100)
                logger.info(f"[{label}] Gotowe -{pcts}%: {fname}")
                self.on_row_update(info.get("rowid"), status="Gotowe", tag="done", savings=f"-{pcts}%", gpu=label)
                upd_out(100)
                work_queue.task_done()

        # Uruchom 3 wątki
        t_fetch = threading.Thread(target=prefetch, daemon=True, name=f"prefetch-{label}")
        t_encode = threading.Thread(target=encode, daemon=True, name=f"encode-{label}")
        t_upload = threading.Thread(target=upload, daemon=True, name=f"upload-{label}")
        t_fetch.start()
        t_encode.start()
        t_upload.start()
        t_upload.join()  # czekamy na upload — 1:1 z monolitu

        # Testmode: zapisz raport JSON
        if cfg.test_mode and self.test_results:
            self._save_test_report(label)

    def _save_test_report(self, label: str) -> None:
        """Zapis raportu JSON po zakończeniu pipeline — 1:1 z monolitu."""
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        json_path = cfg.tmpdir / f"testvmaf_{label}_{ts}.json"
        vmaf_vals = [r["vmaf"] for r in self.test_results if r["vmaf"] > 0]
        sav_vals = [r["savingspct"] for r in self.test_results]
        payload = {
            "runid": ts, "gpu_label": label,
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
            json_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
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
    ) -> bool:
        """copywithprogress() dla SMB/mounted — 8MB chunks, stall watchdog."""
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
            tmp.replace(dst)
            return True
        except Exception as e:
            logger.error(f"copy_with_progress error: {e}")
            rm_silent(tmp)
            return False
