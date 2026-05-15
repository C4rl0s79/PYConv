"""theme.py — stałe kolorystyczne i apply_theme().

Zachowane 1:1 z monolitu: Dark GitHub-style palette, ttk.Style 'clam'.
Progressbary Canvas (nie TProgressbar) — redraw_bar() tu także.
"""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk

# Paleta
DARKBG = "#0d1117"
PANELBG = "#161b22"
BORDER = "#30363d"
TEXTPRI = "#e6edf3"
TEXTSEC = "#8b949e"
TEXTMUTED = "#484f58"
ACCENT = "#58a6ff"
ACCENT2 = "#79c0ff"
GREEN = "#3fb950"
BLUE = "#388bfd"
YELLOW = "#d29922"
RED = "#f85149"
HDRCOLOR = "#f0c060"
DONECOLOR = GREEN
ERRORCOLOR = RED
SKIPCOLOR = TEXTSEC

# Progressbar: canvas-height
BARH = 22


def apply_theme(root: tk.Tk) -> None:
    """Aplikuje ciemny motyw do wszystkich ttk.Style."""
    root.configure(bg=DARKBG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        ".",
        background=DARKBG,
        foreground=TEXTPRI,
        fieldbackground=PANELBG,
        bordercolor=BORDER,
        troughcolor=PANELBG,
        selectbackground=ACCENT,
        selectforeground=DARKBG,
        font=("Segoe UI", 9),
    )
    for widget, opts in [
        ("TFrame", {"background": DARKBG}),
        ("TLabel", {"background": DARKBG, "foreground": TEXTPRI}),
        ("TLabelframe", {"background": DARKBG, "foreground": ACCENT, "bordercolor": BORDER}),
        ("TLabelframe.Label", {"background": DARKBG, "foreground": ACCENT, "font": ("Segoe UI", 9, "bold")}),
        ("TButton", {"background": PANELBG, "foreground": TEXTPRI, "bordercolor": BORDER, "padding": 4}),
        ("TCheckbutton", {"background": DARKBG, "foreground": TEXTPRI}),
        ("TRadiobutton", {"background": DARKBG, "foreground": TEXTPRI}),
        (
            "TCombobox",
            {
                "fieldbackground": PANELBG,
                "background": PANELBG,
                "foreground": TEXTPRI,
                "arrowcolor": ACCENT,
                "bordercolor": BORDER,
            },
        ),
        ("TEntry", {"fieldbackground": PANELBG, "foreground": TEXTPRI, "insertcolor": TEXTPRI, "bordercolor": BORDER}),
        ("TScrollbar", {"background": PANELBG, "troughcolor": DARKBG, "arrowcolor": TEXTSEC, "bordercolor": BORDER}),
        ("TPanedwindow", {"background": DARKBG}),
        ("TSeparator", {"background": BORDER}),
        ("TNotebook", {"background": DARKBG, "bordercolor": BORDER}),
        ("TNotebook.Tab", {"background": PANELBG, "foreground": TEXTSEC, "padding": (10, 4), "bordercolor": BORDER}),
        (
            "Treeview",
            {
                "background": PANELBG,
                "foreground": TEXTPRI,
                "fieldbackground": PANELBG,
                "bordercolor": BORDER,
                "rowheight": 22,
            },
        ),
        (
            "Treeview.Heading",
            {
                "background": DARKBG,
                "foreground": ACCENT,
                "bordercolor": BORDER,
                "font": ("Segoe UI", 9, "bold"),
            },
        ),
        (
            "Status.TLabel",
            {
                "background": "#0d1117",
                "foreground": TEXTSEC,
                "font": ("Consolas", 8),
                "padding": (4, 2),
            },
        ),
    ]:
        style.configure(widget, **opts)

    style.map(
        "TButton",
        background=[("active", BORDER), ("disabled", DARKBG)],
        foreground=[("disabled", TEXTMUTED)],
    )
    style.map("TCheckbutton", background=[("active", DARKBG)])
    style.map("TRadiobutton", background=[("active", DARKBG)])
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PANELBG)],
        selectbackground=[("readonly", PANELBG)],
        selectforeground=[("readonly", TEXTPRI)],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", DARKBG)],
        foreground=[("selected", ACCENT)],
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", DARKBG)],
    )

    # Progressbary (Canvas) — per-name style
    for name, fill in [
        ("copy", "#8b5cf6"),
        ("gpu1", GREEN),
        ("gpu2", ACCENT),
        ("total", ACCENT2),
        ("grey", TEXTMUTED),
    ]:
        style.configure(
            f"{name}.Horizontal.TProgressbar",
            troughcolor=PANELBG,
            background=fill,
            bordercolor=BORDER,
            darkcolor=fill,
            lightcolor=fill,
        )


def redraw_bar(app, cv_attr: str) -> None:
    """redrawbar() z monolitu — Canvas progressbar.

    Rysuje tło (PANELBG) + wypełnienie (color) + tekst wycentrowany.
    """
    canvas = getattr(app, cv_attr, None)
    if not canvas:
        return

    pct_attr = cv_attr.replace("cv", "pct")
    pct = getattr(app, pct_attr, 0.0)
    text = app.bar_text.get(cv_attr, "")
    color = app.bar_colors.get(cv_attr, ACCENT)

    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 2:
        return
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=PANELBG, outline="")
    fill_w = int(w * pct / 100)
    if fill_w > 0:
        canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
    canvas.create_text(
        w // 2,
        h // 2,
        text=text,
        fill=TEXTPRI,
        font=("Segoe UI", 9),
        anchor="center",
    )
