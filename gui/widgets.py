"""widgets.py — build_ui(): buduje całą hierarchię widgetów GUI.

Zachowane 1:1 z monolitu: PanedWindow lewo/prawo, Notebook (3 zakładki),
Canvas progressbary, Treeview plików, log ScrolledText.

Funkcja build_ui(app) przyjmuje instancję PlexConvertApp i tworzy
wszystkie widgety jako atrybuty self.* — bez żadnej logiki biznesowej.
"""
from __future__ import annotations
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog

from .theme import (
    DARKBG, PANELBG, BORDER, TEXTPRI, TEXTSEC, TEXTMUTED,
    ACCENT, ACCENT2, GREEN, BARH,
    HDRGCOLOR := "#f0c060",  # nie ma w theme — alias
    redraw_bar,
)

# Wartości domyślne
ENCODER_OPTIONS = [
    "av1nvenc", "hevcnvenc",
    "av1qsv",   "hevcqsv",
    "av1amf",   "hevcamf",
    "libsvtav1","libx265",
]
QSV_PROFILES = {
    "quality":  {"label": "Quality  VMAF 93–96, savings 15–25%"},
    "balanced": {"label": "Balanced VMAF 88–92, savings 30–40%"},
}
SAFE_FREE_GB  = 20.0
WARN_FREE_GB  = 10.0


def make_scrollable(parent: ttk.Frame) -> ttk.Frame:
    """makescrollable() z monolitu — Canvas + Scrollbar, zwraca inner Frame."""
    canvas = tk.Canvas(parent, bg=DARKBG, highlightthickness=0)
    vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    inner = ttk.Frame(canvas)
    win_id = canvas.create_window(0, 0, window=inner, anchor="nw")

    def on_resize(e):
        canvas.itemconfig(win_id, width=e.width)

    def on_frame_configure(e):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def on_wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    canvas.bind("<Configure>", on_resize)
    inner.bind("<Configure>", on_frame_configure)
    canvas.bind_all("<MouseWheel>", on_wheel)
    return inner


def build_ui(app) -> None:
    """Tworzy całą hierarchię widgetów i przypina do app.*."""
    _build_statusbar(app)
    paned = ttk.PanedWindow(app, orient=tk.HORIZONTAL)
    paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    left  = ttk.Frame(paned, width=360)
    right = ttk.Frame(paned)
    paned.add(left,  weight=0)
    paned.add(right, weight=1)
    _build_left(app, left)
    _build_right(app, right)


def _build_statusbar(app) -> None:
    app.statusbar = ttk.Label(
        app, text="Gotowy", style="Status.TLabel", anchor="w", relief="flat"
    )
    app.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
    ttk.Separator(app, orient=tk.HORIZONTAL).pack(side=tk.BOTTOM, fill=tk.X)


def _build_left(app, parent: ttk.Frame) -> None:
    """Lewa kolumna: Notebook (3 zakładki) + przyciski akcji."""
    nb = ttk.Notebook(parent)
    nb.pack(fill=tk.BOTH, expand=True, padx=2, pady=(2, 0))
    tab_src = ttk.Frame(nb)
    tab_enc = ttk.Frame(nb)
    tab_cp  = ttk.Frame(nb)
    nb.add(tab_src, text=" Źródło ")
    nb.add(tab_enc, text=" Enkodery ")
    nb.add(tab_cp,  text=" Copyparty ")
    _build_tab_src(app, tab_src)
    _build_tab_enc(app, tab_enc)
    _build_tab_cp(app, tab_cp)

    ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=(6, 2))
    bf = ttk.Frame(parent)
    bf.pack(fill=tk.X, padx=4, pady=(0, 4))
    app.btn_scan    = ttk.Button(bf, text="Skanuj",    command=app.start_scan)
    app.btn_convert = ttk.Button(bf, text="Konwertuj", command=app.start_convert, state="disabled")
    app.btn_cancel  = ttk.Button(bf, text="Anuluj",    command=app.cancel,        state="disabled")
    app.btn_clear   = ttk.Button(bf, text="Wyczyść",   command=app.clear)
    app.btn_scan.grid   (row=0, column=0, padx=2, pady=2, sticky="ew")
    app.btn_convert.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
    app.btn_cancel.grid (row=1, column=0, padx=2, pady=2, sticky="ew")
    app.btn_clear.grid  (row=1, column=1, padx=2, pady=2, sticky="ew")
    bf.columnconfigure(0, weight=1)
    bf.columnconfigure(1, weight=1)


def _build_tab_src(app, parent: ttk.Frame) -> None:
    """Zakładka źródło: tryb, ścieżka, sieć, tmp, wolne miejsce."""
    inner = make_scrollable(parent)

    # Tryb + ścieżka
    sf = ttk.LabelFrame(inner, text="Źródło")
    sf.pack(fill=tk.X, padx=6, pady=(6, 4))
    app.mode = tk.StringVar(value="folder")
    mode_row = ttk.Frame(sf)
    mode_row.pack(fill=tk.X, padx=4, pady=(4, 2))
    ttk.Radiobutton(mode_row, text="Folder batch",     variable=app.mode, value="folder").pack(side=tk.LEFT)
    ttk.Radiobutton(mode_row, text="Pojedynczy plik",  variable=app.mode, value="file").pack(side=tk.LEFT, padx=(12, 0))
    path_row = ttk.Frame(sf)
    path_row.pack(fill=tk.X, padx=4, pady=(0, 4))
    app.src_var = tk.StringVar()
    ttk.Entry(path_row, textvariable=app.src_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
    ttk.Button(path_row, text="…", width=3, command=app.browse_src).pack(side=tk.LEFT, padx=(2, 0))

    # Sieć
    nf = ttk.LabelFrame(inner, text="Udział sieciowy")
    nf.pack(fill=tk.X, padx=6, pady=4)
    app.is_network = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        nf, text="Katalog to udział sieciowy",
        variable=app.is_network, command=app.on_network_toggle,
    ).pack(anchor="w", padx=4, pady=(4, 2))
    app.net_drives_var = tk.StringVar()
    ttk.Label(nf, text="Wykryte dyski sieciowe").pack(anchor="w", padx=4)
    ttk.Entry(nf, textvariable=app.net_drives_var, state="readonly").pack(fill=tk.X, padx=4, pady=(0, 4))

    # Folder tymczasowy
    tf2 = ttk.LabelFrame(inner, text="Folder tymczasowy (lokalny)")
    tf2.pack(fill=tk.X, padx=6, pady=4)
    default_tmp = "C:\\" if sys.platform == "win32" else "/tmp"
    app.tmp_var = tk.StringVar(value=default_tmp)
    tmp_row = ttk.Frame(tf2)
    tmp_row.pack(fill=tk.X, padx=4, pady=4)
    ttk.Entry(tmp_row, textvariable=app.tmp_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
    ttk.Button(
        tmp_row, text="…", width=3,
        command=lambda: app.tmp_var.set(filedialog.askdirectory() or app.tmp_var.get()),
    ).pack(side=tk.LEFT, padx=(2, 0))
    free_row = ttk.Frame(tf2)
    free_row.pack(fill=tk.X, padx=4, pady=(0, 4))
    app.free_label = ttk.Label(free_row, text="Wolne miejsce —", foreground=TEXTSEC)
    app.free_label.pack(side=tk.LEFT, expand=True, anchor="w")
    ttk.Button(free_row, text="Odśwież", command=app.refresh_free).pack(side=tk.RIGHT)


def _build_tab_enc(app, parent: ttk.Frame) -> None:
    """Zakładka Enkodery: GPU, CQ, HQ, QSV, Anime, Filtry."""
    inner = make_scrollable(parent)

    # Enkodery
    gf = ttk.LabelFrame(inner, text="Enkodery GPU")
    gf.pack(fill=tk.X, padx=6, pady=(6, 4))
    ttk.Label(gf, text="GPU 1", width=7, anchor="w").grid(row=0, column=0, sticky="w", padx=4, pady=3)
    app.enc1_var = tk.StringVar(value=ENCODER_OPTIONS[0])
    ttk.Combobox(gf, textvariable=app.enc1_var, values=ENCODER_OPTIONS, state="readonly", width=28).grid(
        row=0, column=1, columnspan=2, padx=4, pady=3, sticky="ew"
    )
    app.gpu2_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(gf, text="GPU 2", variable=app.gpu2_enabled, command=app.on_gpu2_toggle).grid(
        row=1, column=0, sticky="w", padx=4, pady=3
    )
    app.enc2_var = tk.StringVar(value=ENCODER_OPTIONS[2])
    app.enc2_cb = ttk.Combobox(gf, textvariable=app.enc2_var, values=ENCODER_OPTIONS, state="disabled", width=28)
    app.enc2_cb.grid(row=1, column=1, columnspan=2, padx=4, pady=3, sticky="ew")
    gf.columnconfigure(1, weight=1)

    # CQ
    cqf = ttk.LabelFrame(inner, text="Jakość CQ / GQ")
    cqf.pack(fill=tk.X, padx=6, pady=4)
    app.auto_cq = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        cqf, text="Auto CQ (per rozdzielczość + złożoność sceny)",
        variable=app.auto_cq, command=app.on_auto_cq_toggle,
    ).grid(row=0, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 6))

    app.cq1_lbl = ttk.Label(cqf, text="CQ GPU 1", width=10, anchor="w")
    app.cq1_lbl.grid(row=1, column=0, sticky="w", padx=4, pady=2)
    app.cq1_var = tk.IntVar(value=32)
    app.cq1_val_lbl = ttk.Label(cqf, text="32", width=3, foreground=ACCENT)
    app.cq1_val_lbl.grid(row=1, column=2, sticky="w")
    app.cq1_scale = ttk.Scale(
        cqf, from_=1, to=63, variable=app.cq1_var, orient=tk.HORIZONTAL,
        command=lambda v: app.cq1_val_lbl.config(text=str(int(float(v)))),
    )
    app.cq1_scale.grid(row=1, column=1, sticky="ew", padx=4)

    app.cq2_lbl = ttk.Label(cqf, text="CQ GPU 2", width=10, anchor="w")
    app.cq2_lbl.grid(row=2, column=0, sticky="w", padx=4, pady=2)
    app.cq2_var = tk.IntVar(value=28)
    app.cq2_val_lbl = ttk.Label(cqf, text="28", width=3, foreground=ACCENT)
    app.cq2_val_lbl.grid(row=2, column=2, sticky="w")
    app.cq2_scale = ttk.Scale(
        cqf, from_=1, to=63, variable=app.cq2_var, orient=tk.HORIZONTAL,
        command=lambda v: app.cq2_val_lbl.config(text=str(int(float(v)))),
    )
    app.cq2_scale.grid(row=2, column=1, sticky="ew", padx=4)
    ttk.Label(
        cqf, text="NVENC AV1 28–36  QSV AV1 12–22  QSV HEVC 20–28  x265 16–24",
        font=("TkDefaultFont", 8), foreground="#555",
    ).grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 2))
    app.cq1_scale.config(state="disabled")
    app.cq2_scale.config(state="disabled")
    cqf.columnconfigure(1, weight=1)

    # Min. oszczędność
    ms_row = ttk.Frame(cqf)
    ms_row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 6))
    ttk.Label(ms_row, text="Min. oszczędność", width=16, anchor="w").pack(side=tk.LEFT)
    app.min_save_var = tk.IntVar(value=10)
    app.ms_lbl = ttk.Label(ms_row, text="10", width=4, foreground=ACCENT)
    ttk.Scale(
        ms_row, from_=0, to=50, variable=app.min_save_var, orient=tk.HORIZONTAL,
        command=lambda v: app.ms_lbl.config(text=f"{int(float(v))}"),
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)
    app.ms_lbl.pack(side=tk.LEFT)

    # HQ
    hqf = ttk.LabelFrame(inner, text="Tryb High Quality")
    hqf.pack(fill=tk.X, padx=6, pady=4)
    app.hq_mode = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        hqf, text="Analiza złożoności sceny (wolniej)",
        variable=app.hq_mode, command=app.on_hq_toggle,
    ).pack(anchor="w", padx=4, pady=(4, 2))
    vmaf_sub = ttk.Frame(hqf)
    vmaf_sub.pack(fill=tk.X, padx=16, pady=(0, 4))
    app.vmaf_enabled = tk.BooleanVar(value=False)
    app.vmaf_chk = ttk.Checkbutton(
        vmaf_sub, text="VMAF-target CRF search (BARDZO wolne)",
        variable=app.vmaf_enabled, state="disabled", command=app.on_vmaf_toggle,
    )
    app.vmaf_chk.grid(row=0, column=0, columnspan=3, sticky="w")
    app.vmaf_lbl = ttk.Label(vmaf_sub, text="Cel VMAF", state="disabled", width=10, anchor="w")
    app.vmaf_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))
    app.vmaf_target = tk.DoubleVar(value=93.0)
    app.vmaf_val_lbl = ttk.Label(vmaf_sub, text="93", width=3, foreground=ACCENT)
    app.vmaf_val_lbl.grid(row=1, column=2, sticky="w")
    app.vmaf_scale = ttk.Scale(
        vmaf_sub, from_=85, to=98, variable=app.vmaf_target, orient=tk.HORIZONTAL,
        state="disabled",
        command=lambda v: app.vmaf_val_lbl.config(text=f"{int(float(v))}"),
    )
    app.vmaf_scale.grid(row=1, column=1, sticky="ew", padx=4)
    vmaf_sub.columnconfigure(1, weight=1)

    # QSV Prof