"""app.py — PlexConvertApp: główna klasa aplikacji Tkinter.

Łączy gui/widgets.py (layout), gui/callbacks.py (logika),
gui/theme.py (styl) i media/FFmpegEngine.

Zasada: __init__ tylko inicjuje zmienne i woła build_ui().
Cała logika biznesowa jest w callbacks.py — metody klasy
są cienkimi wrapperami delegującymi do modułu callbacks.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional

from .theme import apply_theme, DARKBG, PANELBG, TEXTPRI, TEXTSEC, TEXTMUTED, ACCENT, ACCENT2, GREEN
from .widgets import build_ui
from . import callbacks as cb
from ..media.ffmpeg import FFmpegEngine
from ..network.client import CopypartyClient


class PlexConvertApp(tk.Tk):
    """Główne okno aplikacji — v4.12 refactored."""

    APP_TITLE   = "Plex Convert GUI v4.12 — Copyparty"
    APP_VERSION = "4.12"

    def __init__(self):
        super().__init__()
        self.title(self.APP_TITLE)
        self.geometry("1400x900")
        self.minsize(1100, 700)
        self.resizable(True, True)

        # --- Stan aplikacji ---
        self.files:       list[dict] = []
        self.cancel_flag: threading.Event = threading.Event()
        self.ui_queue:    list = []

        # --- Blokady sieciowe ---
        self.net_copy_lock:     threading.Lock = threading.Lock()
        self.net_download_lock: threading.Lock = threading.Lock()
        self.net_upload_lock:   threading.Lock = threading.Lock()

        # --- Progress bars: canvas + wartości + kolory + tekst ---
        self.bar_colors: dict[str, str] = {
            "copycv":   "#8b5cf6",
            "uploadcv": "#e879f9",
            "file1cv":  GREEN,
            "file2cv":  ACCENT,
            "totalcv":  ACCENT2,
        }
        self.bar_text: dict[str, str] = {
            "copycv": "", "uploadcv": "",
            "file1cv": "", "file2cv": "", "totalcv": "",
        }
        # pct atrybuty (copypct, uploadpct, ...)
        for attr in ("copypct", "uploadpct", "file1pct", "file2pct", "totalpct"):
            setattr(self, attr, 0.0)

        # --- Paleta kolorów dla callbacks ---
        self.theme_colors = {
            "DARKBG":    DARKBG,
            "PANELBG":   PANELBG,
            "TEXTPRI":   TEXTPRI,
            "TEXTSEC":   TEXTSEC,
            "TEXTMUTED": TEXTMUTED,
            "ACCENT":    ACCENT,
        }

        # --- Backend ---
        self.ffmpeg:    FFmpegEngine    = FFmpegEngine()
        self.cp_client: Optional[CopypartyClient] = None

        # --- Załaduj theme i zbuduj UI ---
        apply_theme(self)
        build_ui(self)

        # --- Wczytaj sesję + uruchom poll ---
        cb.session_load(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_ui()

    # ------------------------------------------------------------------
    # UI thread-safe dispatcher
    # ------------------------------------------------------------------

    def ui(self, fn, *args, **kwargs) -> None:
        """Enqueue callable do wykonania w wątku GUI (przez _poll_ui)."""
        self.ui_queue.append((fn, args, kwargs))

    def _poll_ui(self) -> None:
        """Opróżnia ui_queue co 40ms — identyczny mechanizm jak w monolicie."""
        while self.ui_queue:
            try:
                fn, args, kwargs = self.ui_queue.pop(0)
                fn(*args, **kwargs)
            except Exception:
                pass
        self.after(40, self._poll_ui)

    # ------------------------------------------------------------------
    # Logowanie
    # ------------------------------------------------------------------

    def log_msg(self, msg: str, level: str = "INFO") -> None:
        """Wątek-bezpieczne logowanie do ScrolledText."""
        from datetime import datetime
        ts   = datetime.now().strftime("%H:%M:%S")
        full = f"{ts}  {msg}\n"

        def do():
            try:
                self.log.configure(state="normal")
                self.log.insert(tk.END, full, level)
                self.log.see(tk.END)
                self.log.configure(state="disabled")
            except Exception:
                pass
        self.ui(do)

    # ------------------------------------------------------------------
    # Cienkiewrappery → callbacks.py
    # ------------------------------------------------------------------

    def start_scan(self)    -> None: cb.start_scan(self)
    def start_convert(self) -> None: cb.start_convert(self)
    def cancel(self)        -> None: cb.cancel(self)
    def clear(self)         -> None: cb.clear(self)
    def browse_src(self)    -> None: cb.browse_src(self)
    def refresh_free(self)  -> None: cb.refresh_free(self)
    def select_all(self)    -> None: cb.select_all(self)
    def deselect_all(self)  -> None: cb.deselect_all(self)
    def sort_tree(self, col)-> None: cb.sort_tree(self, col)
    def on_tree_click(self, event) -> None: cb.on_tree_click(self, event)

    def on_gpu2_toggle(self)       -> None: cb.on_gpu2_toggle(self)
    def on_auto_cq_toggle(self)    -> None: cb.on_auto_cq_toggle(self)
    def on_hq_toggle(self)         -> None: cb.on_hq_toggle(self)
    def on_vmaf_toggle(self)       -> None: cb.on_vmaf_toggle(self)
    def on_network_toggle(self)    -> None: cb.on_network_toggle(self)
    def on_qsv_profile_change(self)-> None: cb.on_qsv_profile_change(self)
    def on_anime_mode_change(self) -> None: cb.on_anime_mode_change(self)
    def on_copyparty_toggle(self)  -> None: cb.on_copyparty_toggle(self)

    def cp_do_login(self)         -> None: self._cp_do_login()
    def cp_browse(self)           -> None: self._cp_browse()
    def cp_refresh_cf(self)       -> None: self._cp_refresh_cf()
    def cp_browser_fallback_login(self) -> None: self._cp_browser_fallback_login()

    # ------------------------------------------------------------------
    # Copyparty login helpers (GUI-specificzne, zostają w app)
    # ------------------------------------------------------------------

    def _cp_do_login(self) -> None:
        url  = getattr(self, "cp_src_url", None)
        pw   = getattr(self, "cp_password", None)
        if not url or not pw:
            return
        self.cp_client = CopypartyClient(url.get().strip(), pw.get())
        try:
            ok = self.cp_client.login()
            status = "OK — zalogowano" if ok else "BŁĄD logowania"
        except Exception as e:
            status = f"BŁĄD: {e}"
        try:
            self.cp_login_status.set(status)
        except Exception:
            pass
        self.log_msg(f"Copyparty login: {status}", "INFO")
        if ok and getattr(self, "cp_remember", None) and self.cp_remember.get():
            from ..utils.json_utils import cfg_save, cfg_load
            d = cfg_load() or {}
            d["cppassword"] = pw.get()
            cfg_save(d)

    def _cp_browse(self) -> None:
        from .dialogs import CopypartyBrowserDialog
        base = getattr(self, "cp_src_url", None)
        pw   = getattr(self, "cp_password", None)
        if not base:
            return
        chosen = CopypartyBrowserDialog.ask(self, base.get().strip(), pw.get() if pw else "")
        if chosen:
            base.set(chosen)
            try:
                self.src_var.set(chosen)
            except Exception:
                pass
            self.log_msg(f"Copyparty URL ustawiony: {chosen}", "INFO")

    def _cp_refresh_cf(self) -> None:
        """Odświeżenie tokenu cfclearance — dialog jak w monolicie."""
        import tkinter as tk2
        from tkinter import ttk as ttk2
        dlg = tk2.Toplevel(self)
        dlg.title("Odśwież cfclearance")
        dlg.geometry("480x160")
        dlg.transient(self)
        dlg.grab_set()
        info = (
            "Cloudflare zablokował request — wymagany nowy cfclearance\n"
            "1. W otwartej przeglądarce F12 → Application → Cookies\n"
            "2. Skopiuj wartość cfclearance\n"
            "3. Wklej poniżej"
        )
        tk2.Label(dlg, text=info, justify=tk2.LEFT, padx=12, pady=8).pack()
        cf_var = tk2.StringVar()
        ttk2.Entry(dlg, textvariable=cf_var, width=48).pack(padx=12, pady=0)

        def confirm():
            cf = cf_var.get().strip()
            if cf and self.cp_client:
                self.cp_client.set_cf_clearance(cf)
                self.log_msg(f"CF odświeżony.", "INFO")
            dlg.destroy()

        btn_row = ttk2.Frame(dlg)
        btn_row.pack(pady=(0, 8))
        ttk2.Button(btn_row, text="OK",     command=confirm).pack(side=tk2.LEFT, padx=4)
        ttk2.Button(btn_row, text="Anuluj", command=dlg.destroy).pack(side=tk2.LEFT, padx=4)

    def _cp_browser_fallback_login(self) -> None:
        import webbrowser
        url = getattr(self, "cp_src_url", None)
        if url:
            webbrowser.open(url.get().strip())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        cb.session_save(self)
        self.destroy()
