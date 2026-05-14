"""callbacks.py — cała logika biznesowa GUI oddzielona od widgetów."""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import PlexConvertApp

# ---------------------------------------------------------------------------
# Lazy-safe imports — działają zarówno jako pakiet jak i standalone
# ---------------------------------------------------------------------------
def _imp(rel, abs_):
    """Próbuje relative import, przy błędzie wraca do absolutnego."""
    import importlib
    try:
        return importlib.import_module(rel, package="gui")
    except ImportError:
        return importlib.import_module(abs_)

try:
    from ..config.constants import SAFE_FREE_GB, WARN_FREE_GB
    from ..config.profiles  import QSVPROFILES, ENCODER_OPTIONS
    from ..media.probe      import probe_file, scan_dir, cp_probe_via_http
    from ..network.client   import CopypartyClient
    from ..utils.filesystem import free_gb, detect_network_drives
    from ..utils.json_utils import cfg_load, cfg_save
    from ..engine.pipeline  import PipelineWorker, SequentialWorker, PipelineConfig
    from ..engine.progress  import ProgressTracker
    from ..engine.cq_selector import CQSelector
    from ..models.enums     import EncoderType
except ImportError:
    from config.constants   import SAFE_FREE_GB, WARN_FREE_GB      # type: ignore
    from config.profiles    import QSVPROFILES, ENCODER_OPTIONS     # type: ignore
    from media.probe        import probe_file, scan_dir, cp_probe_via_http  # type: ignore
    from network.client     import CopypartyClient                  # type: ignore
    from utils.filesystem   import free_gb, detect_network_drives   # type: ignore
    from utils.json_utils   import cfg_load, cfg_save               # type: ignore
    from engine.pipeline    import PipelineWorker, SequentialWorker, PipelineConfig  # type: ignore
    from engine.progress    import ProgressTracker                  # type: ignore
    from engine.cq_selector import CQSelector                       # type: ignore
    from models.enums       import EncoderType                      # type: ignore


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def start_scan(app: "PlexConvertApp") -> None:
    if app.use_copyparty.get():
        if not app.cp_src_url.get().strip():
            from tkinter import messagebox
            messagebox.showwarning("Copyparty", "Wpisz URL katalogu lub kliknij … aby wybrać z serwera.")
            return
    else:
        src = app.src_var.get().strip()
        if not src:
            from tkinter import messagebox
            messagebox.showwarning("Brak ścieżki", "Wybierz plik lub folder.")
            return
    app.cancel_flag.clear()
    clear(app)
    set_buttons(app, running=True)
    threading.Thread(target=_scan_worker, args=(app,), daemon=True).start()


def _scan_worker(app: "PlexConvertApp") -> None:
    app.cancel_flag.clear()
    if app.use_copyparty.get():
        _scan_copyparty(app)
    else:
        _scan_local(app)


def _scan_copyparty(app: "PlexConvertApp") -> None:
    cp_url  = app.cp_src_url.get().strip()
    cp_pass = app.cp_password.get()
    cp_tmp  = app.tmp_var.get()
    app.log_msg(f"Skanowanie Copyparty: {cp_url}", "INFO")
    try:
        cp_files = CopypartyClient(cp_url, cp_pass).list_files(cp_url, cp_pass)
    except Exception as e:
        app.log_msg(f"BŁĄD listowania copyparty: {e}", "ERROR")
        set_buttons(app, running=False)
        return

    n = len(cp_files)
    app.log_msg(f"Znaleziono {n} plików — analizuję przez HTTP", "INFO")
    app.files.clear()

    for i, cf in enumerate(cp_files):
        if app.cancel_flag.is_set():
            break
        try:
            info = cp_probe_via_http(cf["path_url"], cp_tmp, cp_pass)
            if not info or "error_rc" in info:
                err = info.get("error_msg", "?") if info else "brak wyniku"
                app.log_msg(f"BŁĄD probe {cf['name']}: {err}", "ERROR")
                continue
            info["path"]   = cf["path_url"]
            info["size"]   = cf["size"]
            info["cpname"] = cf["name"]
            info["cpdir"]  = cf["dir_url"]
            info["rowid"]  = str(i)
            app.files.append(info)
            codec = info.get("codec", "?").lower()
            tag, status = _classify(app, info, codec)
            _add_row(app, str(i), cf["name"], codec, info, cf["size"], status, tag)
            set_pb(app, "totalpb", int((i + 1) / n * 100), "totalinfo", f"Skanowanie CP {i+1}/{n}")
        except Exception as e:
            app.log_msg(f"BŁĄD skanowania {cf['name']}: {e}", "ERROR")

    app.log_msg(f"Skanowanie Copyparty gotowe — {len(app.files)} plików.", "DONE")
    app.ui(lambda: app.btn_convert.config(state="normal"))
    set_buttons(app, running=False)
    set_pb(app, "totalpb", 0, "totalinfo", "")


def _scan_local(app: "PlexConvertApp") -> None:
    src = app.src_var.get().strip()
    app.log_msg(f"Skanowanie: {src}", "INFO")
    paths = [src] if os.path.isfile(src) else scan_dir(src)
    app.log_msg(f"Znaleziono {len(paths)} plików — analizuję", "INFO")
    app.files.clear()

    for i, path in enumerate(paths):
        if app.cancel_flag.is_set():
            break
        try:
            info = probe_file(path)
            if not info or "error_rc" in info:
                err = info.get("error_msg", "nieznany błąd") if info else "brak wyniku"
                app.log_msg(f"BŁĄD ffprobe {os.path.basename(path)}: {err}", "ERROR")
                continue
            info["rowid"] = str(i)
            app.files.append(info)
            codec = info.get("codec", "?").lower()
            tag, status = _classify(app, info, codec)
            fname = os.path.basename(path)
            _add_row(app, str(i), fname, codec, info, info["size"], status, tag)
            set_pb(app, "totalpb", int((i + 1) / len(paths) * 100), "totalinfo", f"Skanowanie {i+1}/{len(paths)}")
        except Exception as e:
            app.log_msg(f"BŁĄD skanowania {os.path.basename(path)}: {e}", "ERROR")

    app.log_msg(f"Skanowanie gotowe — {len(app.files)} plików.", "DONE")
    app.ui(lambda: app.btn_convert.config(state="normal"))
    set_buttons(app, running=False)
    set_pb(app, "totalpb", 0, "totalinfo", "")


def _classify(app, info: dict, codec: str) -> tuple[str, str]:
    if info.get("hdr") and app.skip_hdr.get():
        return "hdr", "HDR — pomijany"
    if codec == "av1" and app.skip_av1.get():
        return "skip2", "Już AV1"
    if codec in ("hevc", "h265") and app.skip_hevc.get():
        return "skip2", "Już H.265/HEVC"
    return "", "Oczekuje"


def _add_row(app, iid: str, fname: str, codec: str, info: dict, size: int, status: str, tag: str) -> None:
    res   = f"{info.get('width', 0)}x{info.get('height', 0)}" if info.get("width") else "?"
    fsize = f"{size / 1024**3:.2f} GB"
    hdrs  = "TAK" if info.get("hdr") else "nie"

    def add():
        app.tree.insert(
            "", "end", iid=iid,
            values=("", fname, codec, res, fsize, hdrs, status, "", ""),
            tags=(tag,),
        )
    app.ui(add)


# ---------------------------------------------------------------------------
# Convert
# ---------------------------------------------------------------------------

def start_convert(app: "PlexConvertApp") -> None:
    if not app.files:
        from tkinter import messagebox
        messagebox.showwarning("Brak plików", "Najpierw wykonaj skanowanie.")
        return

    app.cancel_flag.clear()
    set_buttons(app, running=True)

    is_net = app.is_network.get()
    if not is_net:
        app.bar_colors["copycv"]  = app.theme_colors.get("TEXTMUTED", "#666")
        app.bar_colors["uploadcv"] = app.theme_colors.get("TEXTMUTED", "#666")
        set_pb(app, "copypb",   100, "copyinfo",   "Nieaktywne — tryb lokalny")
        set_pb(app, "uploadpb", 100, "uploadinfo", "Nieaktywne — tryb lokalny")
    else:
        app.bar_colors["copycv"]  = "#8b5cf6"
        app.bar_colors["uploadcv"] = "#e879f9"
        set_pb(app, "copypb",   0, "copyinfo",   "")
        set_pb(app, "uploadpb", 0, "uploadinfo", "")

    skip_av1  = app.skip_av1.get()
    skip_hevc = app.skip_hevc.get()
    to_convert = [
        f for f in app.files
        if _is_row_selected(app, f)
        and not (f.get("hdr") and app.skip_hdr.get())
        and not (f.get("codec", "").lower() == "av1"  and skip_av1)
        and not (f.get("codec", "").lower() in ("hevc", "h265") and skip_hevc)
    ]
    total = len(to_convert)
    if total == 0:
        app.log_msg("Brak plików do konwersji.", "WARN")
        set_buttons(app, running=False)
        return

    work_queue: queue.Queue = queue.Queue()
    for idx, info in enumerate(to_convert):
        work_queue.put((idx, info))

    tracker  = ProgressTracker(total, is_net)
    enc1     = EncoderType(app.enc1_var.get())
    enc2     = EncoderType(app.enc2_var.get()) if app.gpu2_enabled.get() else None
    cq1      = None if app.auto_cq.get() else app.cq1_var.get()
    cq2      = None if app.auto_cq.get() else (app.cq2_var.get() if app.gpu2_enabled.get() else None)
    min_sav  = app.min_save_var.get() / 100.0
    tmp_dir  = Path(app.tmp_var.get())
    keep     = app.keep_orig.get()
    test     = app.test_mode.get()
    hq       = app.hq_mode.get()
    vmaf_t   = float(app.vmaf_target.get()) if hq and app.vmaf_enabled.get() else 0.0
    qsv_prof = app.qsv_profile.get()
    anime    = app.anime_mode.get()

    cq_sel = CQSelector(
        ffmpeg_engine=app.ffmpeg,
        qsv_profile=qsv_prof,
        anime_mode=anime,
        qsv_profiles=QSVPROFILES,
    )

    cq1_str = "auto" if cq1 is None else str(cq1)
    cq2_str = "auto" if cq2 is None else str(cq2)
    hq_str  = (" HQ" if hq else "") + (f" VMAF={vmaf_t:.0f}" if vmaf_t > 0 else "")
    app.log_msg(
        f"Konwersja {total} plików  GPU1={enc1.value} CQ={cq1_str}"
        f"  GPU2={enc2.value if enc2 else 'wyłączone'} CQ={cq2_str}"
        f"{hq_str}{'  TEST' if test else ''}",
        "INFO",
    )
    set_pb(app, "totalpb", 0, "totalinfo", f"0/{total}")

    dl_lock1 = threading.Lock()
    dl_lock2 = threading.Lock()
    ul_lock  = threading.Lock()
    cp_lock  = threading.Lock()

    configs = [(enc1, "file1pb", "file1info", "GPU1", 1, cq1, dl_lock1)]
    if enc2:
        configs.append((enc2, "file2pb", "file2info", "GPU2", 2, cq2, dl_lock2))

    set_pb(app, "file1pb", 0, "file1info", "Oczekiwanie")
    if enc2:
        set_pb(app, "file2pb", 0, "file2info", "Oczekiwanie")
    else:
        set_pb(app, "file2pb", 0, "file2info", "GPU2 wyłączony")

    workers = []
    for enc, pb, pb_info, log_tag, gpu_label, gpu_cq, dl_lock in configs:
        cfg = PipelineConfig(
            encoder=enc, gpu_label=log_tag, cq=gpu_cq,
            tmpdir=tmp_dir, min_savings=min_sav,
            keep_orig=keep, hq_mode=hq, vmaf_target=vmaf_t,
            test_mode=test,
            use_copyparty=app.use_copyparty.get(),
            cp_src_url=app.cp_src_url.get().strip(),
            cp_password=app.cp_password.get(),
            download_lock=dl_lock,
            upload_lock=ul_lock,
            copy_lock=cp_lock,
            cancel_flag=app.cancel_flag,
        )

        def make_row_cb(a=app):
            def cb(rowid, **kw): update_row(a, rowid, **kw)
            return cb

        def make_pb_cb(pb_=pb, pbi_=pb_info, a=app):
            def cb(val, label=""):
                set_pb(a, pb_, val, pbi_, label)
            return cb

        if is_net:
            w = PipelineWorker(
                config=cfg, ffmpeg=app.ffmpeg, cq_selector=cq_sel,
                copyparty=app.cp_client if app.use_copyparty.get() else None,
                tracker=tracker, total=total,
                on_row_update=make_row_cb(),
                on_progress_update=make_pb_cb(),
            )
        else:
            w = SequentialWorker(
                config=cfg, ffmpeg=app.ffmpeg, cq_selector=cq_sel,
                tracker=tracker, total=total,
                on_row_update=make_row_cb(),
                on_progress_update=make_pb_cb(),
            )

        t = threading.Thread(target=w.run, args=(work_queue,), daemon=True)
        workers.append(t)
        t.start()

    def watch():
        for wt in workers:
            wt.join()
        set_pb(app, "totalpb", 100, "totalinfo", f"{total}/{total} gotowe")
        app.log_msg("Konwersja zakończona.", "DONE")
        set_buttons(app, running=False)

    threading.Thread(target=watch, daemon=True).start()


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def cancel(app: "PlexConvertApp") -> None:
    app.cancel_flag.set()
    app.log_msg("Anulowanie — nowe pliki nie będą już startować.", "WARN")


def clear(app: "PlexConvertApp") -> None:
    app.tree.delete(*app.tree.get_children())
    app.files.clear()
    app.btn_convert.config(state="disabled")
    for attr in ("copypb", "uploadpb", "file1pb", "file2pb", "totalpb"):
        set_pb(app, attr, 0)


def set_buttons(app: "PlexConvertApp", running: bool) -> None:
    s = "disabled" if running else "normal"
    def do():
        app.btn_scan.config(state=s)
        app.btn_convert.config(state=s)
        app.btn_clear.config(state=s)
        app.btn_cancel.config(state="normal" if running else "disabled")
    app.ui(do)


def update_row(app: "PlexConvertApp", rowid, status=None, tag=None, savings=None, gpu=None) -> None:
    def do():
        if not rowid or not app.tree.exists(rowid):
            return
        if status:  app.tree.set(rowid, "status",  status)
        if savings: app.tree.set(rowid, "savings", savings)
        if gpu:     app.tree.set(rowid, "gpu",     gpu)
        if tag:     app.tree.item(rowid, tags=(tag,))
    app.ui(do)


def set_pb(app: "PlexConvertApp", pb_attr: str, value: float,
           info_attr: str = None, info_text: str = None) -> None:
    PB_MAP = {
        "copypb":   ("copycv",   "copypct"),
        "uploadpb": ("uploadcv", "uploadpct"),
        "file1pb":  ("file1cv",  "file1pct"),
        "file2pb":  ("file2cv",  "file2pct"),
        "totalpb":  ("totalcv",  "totalpct"),
    }
    if pb_attr not in PB_MAP:
        return
    cv_attr, pct_attr = PB_MAP[pb_attr]

    def do():
        setattr(app, pct_attr, round(value, 2))
        if info_text is not None:
            app.bar_text[cv_attr] = info_text
        elif value == 0:
            app.bar_text[cv_attr] = ""
        try:
            from gui.theme import redraw_bar
        except ImportError:
            from theme import redraw_bar  # type: ignore
        redraw_bar(app, cv_attr)
    app.ui(do)


def _is_row_selected(app, info: dict) -> bool:
    rowid = info.get("rowid")
    try:
        return bool(app.tree.set(rowid, "sel"))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

def sort_tree(app: "PlexConvertApp", col: str) -> None:
    def key_fn(item_id):
        val = app.tree.set(item_id, col)
        if col == "size":
            try:
                return float(val.split()[0].replace(",", ".").replace("GB", "").strip())
            except Exception:
                return 0.0
        if col == "savings":
            try:
                return int(val.replace("%", "").replace("+", "").replace("-", "").strip())
            except Exception:
                return 0
        return val.lower()

    data = [(key_fn(k), k) for k in app.tree.get_children()]
    data.sort()
    for i, (_, k) in enumerate(data):
        app.tree.move(k, "", i)


def on_tree_click(app: "PlexConvertApp", event) -> None:
    region = app.tree.identify_region(event.x, event.y)
    if region != "cell":
        return
    col = app.tree.identify_column(event.x)
    if col != "#1":
        return
    rowid = app.tree.identify_row(event.y)
    if not rowid:
        return
    cur = app.tree.set(rowid, "sel")
    app.tree.set(rowid, "sel", "" if cur else "✓")


def select_all(app: "PlexConvertApp") -> None:
    for rowid in app.tree.get_children():
        app.tree.set(rowid, "sel", "✓")


def deselect_all(app: "PlexConvertApp") -> None:
    for rowid in app.tree.get_children():
        app.tree.set(rowid, "sel", "")


# ---------------------------------------------------------------------------
# Toggle handlers
# ---------------------------------------------------------------------------

def on_gpu2_toggle(app: "PlexConvertApp") -> None:
    enabled = app.gpu2_enabled.get()
    app.enc2_cb.config(state="readonly" if enabled else "disabled")
    manual = not app.auto_cq.get()
    app.cq2_scale.config(state="normal" if enabled and manual else "disabled")
    fg = "#7c3aed" if enabled else app.theme_colors.get("TEXTMUTED", "#666")
    try:
        app.cq2_lbl.config(foreground=fg)
        app.cq2_val_lbl.config(foreground=fg)
    except Exception:
        pass
    update_statusbar(app)


def on_auto_cq_toggle(app: "PlexConvertApp") -> None:
    manual = not app.auto_cq.get()
    s1 = "normal" if manual else "disabled"
    s2 = "normal" if manual and app.gpu2_enabled.get() else "disabled"
    app.cq1_scale.config(state=s1)
    app.cq2_scale.config(state=s2)


def on_hq_toggle(app: "PlexConvertApp") -> None:
    enabled = app.hq_mode.get()
    app.vmaf_chk.config(state="normal" if enabled else "disabled")
    if not enabled:
        app.vmaf_enabled.set(False)
        app.vmaf_scale.config(state="disabled")
        app.vmaf_lbl.config(state="disabled")


def on_vmaf_toggle(app: "PlexConvertApp") -> None:
    enabled = app.vmaf_enabled.get()
    s = "normal" if enabled else "disabled"
    app.vmaf_scale.config(state=s)
    app.vmaf_lbl.config(state=s)


def on_network_toggle(app: "PlexConvertApp") -> None:
    try:
        from utils.filesystem import detect_network_drives as _dnd
    except ImportError:
        from utils.filesystem import detect_network_drives as _dnd  # type: ignore
    if app.is_network.get():
        drives = detect_network_drives()
        app.net_drives_var.set(", ".join(drives) if drives else "brak wykrytych")
        refresh_free(app)
        app.bar_colors["copycv"]  = "#8b5cf6"
        app.bar_colors["uploadcv"] = "#e879f9"
        set_pb(app, "copypb",   0, "copyinfo",   "")
        set_pb(app, "uploadpb", 0, "uploadinfo", "")
    else:
        app.bar_colors["copycv"]  = app.theme_colors.get("TEXTMUTED", "#666")
        app.bar_colors["uploadcv"] = app.theme_colors.get("TEXTMUTED", "#666")
        set_pb(app, "copypb",   100, "copyinfo",   "Nieaktywne — tryb lokalny")
        set_pb(app, "uploadpb", 100, "uploadinfo", "Nieaktywne — tryb lokalny")


def on_qsv_profile_change(app: "PlexConvertApp") -> None:
    p = app.qsv_profile.get()
    prof = QSVPROFILES.get(p, {})
    gq_av1  = prof.get("av1qsv",  {}).get(1080, "?")
    gq_hevc = prof.get("hevcqsv", {}).get(1080, "?")
    try:
        app.qsv_profile_lbl.config(
            text=f"GQ 1080p  av1qsv={gq_av1}  hevcqsv={gq_hevc}  [{p}]"
        )
    except Exception:
        pass
    update_statusbar(app)


def on_anime_mode_change(app: "PlexConvertApp") -> None:
    update_statusbar(app)


def on_copyparty_toggle(app: "PlexConvertApp") -> None:
    pass


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def browse_src(app: "PlexConvertApp") -> None:
    from tkinter import filedialog
    if app.mode.get() == "folder":
        path = filedialog.askdirectory(title="Wybierz folder biblioteki")
    else:
        path = filedialog.askopenfilename(
            title="Wybierz plik wideo",
            filetypes=[("Video", ".mkv .avi .mp4 .mov .ts .m2ts .wmv .flv .mpg .mpeg"), ("All", ".*")],
        )
    if path:
        app.src_var.set(path)


def refresh_free(app: "PlexConvertApp") -> None:
    gb = free_gb(app.tmp_var.get())
    if gb < 0:
        text, fg = "błąd odczytu", "red"
    elif gb >= SAFE_FREE_GB:
        text, fg = f"{gb:.1f} GB wolne", "green"
    elif gb >= WARN_FREE_GB:
        text, fg = f"{gb:.1f} GB wolne", "orange"
    else:
        text, fg = f"{gb:.1f} GB — ZA MAŁO!", "red"
    app.free_label.config(text=f"Wolne miejsce: {text}", foreground=fg)


def update_statusbar(app: "PlexConvertApp") -> None:
    try:
        p    = app.qsv_profile.get()
        a    = " Anime" if app.anime_mode.get() else ""
        enc1 = app.enc1_var.get()
        enc2 = app.enc2_var.get() if app.gpu2_enabled.get() else "—"
        prof = QSVPROFILES.get(p, {})
        gq_av1  = prof.get("av1qsv",  {}).get(1080, "?")
        gq_hevc = prof.get("hevcqsv", {}).get(1080, "?")
        txt = (
            f"QSV {p.upper()}{a}  "
            f"av1qsv GQ={gq_av1}  hevcqsv GQ={gq_hevc}  "
            f"GPU1={enc1}  GPU2={enc2}"
        )
        app.statusbar.config(text=txt)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

SESSION_FIELDS = [
    ("src_var",       "src",         None),
    ("mode",          "mode",        None),
    ("is_network",    "isnetwork",   None),
    ("tmp_var",       "tmp",         None),
    ("enc1_var",      "enc1",        None),
    ("gpu2_enabled",  "gpu2enabled", None),
    ("enc2_var",      "enc2",        None),
    ("auto_cq",       "autocq",      None),
    ("cq1_var",       "cq1",         int),
    ("cq2_var",       "cq2",         int),
    ("min_save_var",  "minsave",     int),
    ("hq_mode",       "hqmode",      None),
    ("vmaf_enabled",  "vmafenabled", None),
    ("vmaf_target",   "vmaftarget",  float),
    ("qsv_profile",   "qsvprofile",  None),
    ("anime_mode",    "animemode",   None),
    ("skip_hdr",      "skiphdr",     None),
    ("skip_av1",      "skipav1",     None),
    ("skip_hevc",     "skiphevc",    None),
    ("keep_orig",     "keeporig",    None),
    ("test_mode",     "testmode",    None),
    ("use_copyparty", "cpuse",       None),
    ("cp_src_url",    "cpurl",       None),
    ("cp_remember",   "cpremember",  None),
]


def session_save(app: "PlexConvertApp") -> None:
    data = {key: getattr(app, attr).get() for attr, key, _ in SESSION_FIELDS}
    if app.cp_remember.get():
        data["cppassword"] = app.cp_password.get()
    cfg_save(data)


def session_load(app: "PlexConvertApp") -> None:
    d = cfg_load()
    if not d:
        return
    for attr, key, cast in SESSION_FIELDS:
        if key in d:
            try:
                val = cast(d[key]) if cast else d[key]
                getattr(app, attr).set(val)
            except Exception:
                pass
    if d.get("cpremember") and "cppassword" in d:
        app.cp_password.set(d["cppassword"])

    on_gpu2_toggle(app)
    on_auto_cq_toggle(app)
    on_hq_toggle(app)
    on_qsv_profile_change(app)
    try:
        app.cq1_val_lbl.config(text=str(app.cq1_var.get()))
        app.cq2_val_lbl.config(text=str(app.cq2_var.get()))
        app.ms_lbl.config(text=str(app.min_save_var.get()))
        app.vmaf_val_lbl.config(text=str(int(app.vmaf_target.get())))
    except Exception:
        pass
    update_statusbar(app)
