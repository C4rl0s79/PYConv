"""dialogs.py — CopypartyBrowserDialog i pomocnicze dialogi.

Zachowane 1:1 z monolitu: drzewo katalogów, lazy-load przez HTTP,
populate_root / populate_node, on_select / on_expand, ok / ask classmethod.
"""

from __future__ import annotations

import hashlib
import threading
import urllib.parse
import urllib.request
import tkinter as tk
from tkinter import ttk
from typing import Optional

from ..network.client import cp_headers, cp_read_json


class CopypartyBrowserDialog(tk.Toplevel):
    """Przeglądarka katalogów Copyparty — popup z drzewem."""

    def __init__(self, parent, base_url: str, password: str, title: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("640x460")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.password = password
        self.result_url: Optional[str] = None
        self.node_urls: dict[str, str] = {}
        self.loading: set[str] = set()

        # --- Pasek adresu ---
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(top, text="Serwer:").pack(side=tk.LEFT)
        self.addr_var = tk.StringVar(value=base_url)
        ttk.Entry(top, textvariable=self.addr_var, width=40).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(top, text="Odśwież", command=self.reload_root).pack(side=tk.LEFT, padx=2)

        # --- Wybrany URL ---
        sel_row = ttk.Frame(self)
        sel_row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(sel_row, text="Wybrany URL:").pack(side=tk.LEFT)
        self.sel_var = tk.StringVar(value=base_url)
        ttk.Entry(sel_row, textvariable=self.sel_var, state="readonly").pack(
            side=tk.LEFT, padx=4, fill=tk.X, expand=True
        )

        # --- Drzewo ---
        tf = ttk.Frame(self)
        tf.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.tree = ttk.Treeview(tf, selectmode="browse", show="tree")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<<TreeviewOpen>>", self.on_expand)

        # --- Przyciski ---
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, padx=6, pady=(2, 6))
        ttk.Button(btn_row, text="OK", command=self.ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Anuluj", command=self.destroy).pack(side=tk.LEFT)
        self.status = ttk.Label(btn_row, text="ładowanie…", foreground="#8b949e")
        self.status.pack(side=tk.LEFT, padx=10)

        self.after(50, self.reload_root)

    # ------------------------------------------------------------------

    def set_status(self, msg: str) -> None:
        self.after(0, lambda: self.status.config(text=msg))

    def reload_root(self) -> None:
        base = self.addr_var.get().strip()
        if not base:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.node_urls.clear()
        self.loading.clear()
        self.set_status("ładowanie…")

        def load():
            hdrs = cp_headers(self.password)
            try:
                ls_url = base.rstrip("/") + "?ls"
                req = urllib.request.Request(ls_url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = cp_read_json(r)
                raw_dirs = data.get("dirs", [])
                dirs = [
                    urllib.parse.unquote(d["href"]).rstrip("/")
                    for d in raw_dirs
                    if isinstance(d, dict)
                    and d.get("href")
                    and not urllib.parse.unquote(d["href"]).rstrip("/").startswith(".")
                ]
                if not dirs and raw_dirs:
                    dirs = [
                        str(d.get("name", ""))
                        for d in raw_dirs
                        if isinstance(d, dict) and d.get("name") and not str(d.get("name", "")).startswith(".")
                    ]
                self.after(0, lambda: self._populate_root(base, dirs))
            except Exception:
                self.after(0, lambda: self.set_status(f"Błąd: {e}"))

        threading.Thread(target=load, daemon=True).start()

    def _populate_root(self, base_url: str, dirs: list) -> None:
        root_iid = "root"
        self.node_urls[root_iid] = base_url.rstrip("/")
        label = base_url.rstrip("/").rsplit("/", 1)[-1] or base_url
        self.tree.insert("", "end", iid=root_iid, text=f"📁 {label}", open=True)
        for d in sorted(dirs):
            child_url = base_url.rstrip("/") + "/" + urllib.parse.quote(d, safe="")
            iid = self._make_iid(child_url)
            self.node_urls[iid] = child_url
            self.tree.insert(root_iid, "end", iid=iid, text=f"📁 {d}")
            self.tree.insert(iid, "end", iid=iid + "_ph", text="")  # placeholder
        self.set_status(f"Załadowano {len(dirs)} podkatalogów.")
        self.tree.selection_set(root_iid)
        self.sel_var.set(self.node_urls[root_iid])

    def _make_iid(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    def on_select(self, event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        url = self.node_urls.get(sel[0], "")
        if url:
            self.sel_var.set(url)

    def on_expand(self, event=None) -> None:
        sel = self.tree.focus()
        if not sel or sel not in self.node_urls:
            return
        if sel in self.loading:
            return
        children = self.tree.get_children(sel)
        if not children or not children[0].endswith("_ph"):
            return
        self.tree.delete(children[0])
        self.loading.add(sel)
        url = self.node_urls[sel]
        self.set_status(f"Ładowanie {url}…")

        def load(node_iid=sel, node_url=url):
            hdrs = cp_headers(self.password)
            try:
                ls_url = node_url.rstrip("/") + "?ls"
                req = urllib.request.Request(ls_url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = cp_read_json(r)
                raw_dirs = data.get("dirs", [])
                dirs = [
                    urllib.parse.unquote(d["href"]).rstrip("/")
                    for d in raw_dirs
                    if isinstance(d, dict)
                    and d.get("href")
                    and not urllib.parse.unquote(d["href"]).rstrip("/").startswith(".")
                ]
                self.after(0, lambda: self._populate_node(node_iid, node_url, dirs))
            except Exception:
                self.after(0, lambda: self.set_status(f"Błąd: {e}"))
            finally:
                self.loading.discard(node_iid)

        threading.Thread(target=load, daemon=True).start()

    def _populate_node(self, parent_iid: str, parent_url: str, dirs: list) -> None:
        for d in sorted(dirs):
            child_url = parent_url.rstrip("/") + "/" + urllib.parse.quote(d, safe="")
            iid = self._make_iid(child_url)
            self.node_urls[iid] = child_url
            if not self.tree.exists(iid):
                self.tree.insert(parent_iid, "end", iid=iid, text=f"📁 {d}")
                self.tree.insert(iid, "end", iid=iid + "_ph", text="")
        self.set_status(f"Załadowano {len(dirs)} podkatalogów." if dirs else "Brak podkatalogów.")

    def ok(self) -> None:
        self.result_url = self.sel_var.get().strip()
        self.destroy()

    @classmethod
    def ask(cls, parent, base_url: str, password: str, title: str = "Wybierz katalog") -> str:
        dlg = cls(parent, base_url, password, title)
        parent.wait_window(dlg)
        return dlg.result_url or ""
