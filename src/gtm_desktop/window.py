"""Main window, opened by a left click on the tray icon. Laid out like Windows 11 Settings.

Pages: Overview, Processes, History, Settings, About. Closing the window only
hides it: the app keeps running in the tray. Only the visible page is redrawn
on each frame, and nothing is redrawn while the window is hidden.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import art, autostart, brand
from .charts import LineChart, StackedBar
from .fluent import ICON, Choice, ScrollFrame, Switch, level_color, style_window
from .i18n import LANGUAGE_NAMES, _
from .model import (Frame, Proc, describe, describe_text, device_load, fmt_bytes, fmt_mhz, fmt_pct,
                    fmt_temp, fmt_watts, shown_inside)
from .settings import INTERVALS, TEMP_ALERTS, VRAM_ALERTS, data_dir

log = logging.getLogger(__name__)
PAGES = ("overview", "processes", "history", "settings", "about")


def resource_dir() -> Path:
    """Install folder when frozen, repository root in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def open_path(path: Path | str) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - local folder or file chosen by us
    else:
        subprocess.Popen(["xdg-open", str(path)])


class MainWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.c, self.s, self.f = app.theme, app.scale, app.fonts
        c = self.c
        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.title(brand.APP_NAME)
        self.top.configure(bg=c["surface"])
        self.top.minsize(self._p(880), self._p(560))
        self.top.protocol("WM_DELETE_WINDOW", self.hide)
        if app.icon_path:
            try:
                self.top.iconbitmap(default=str(app.icon_path))
            except tk.TclError:
                pass
        self._caption_hicon = None  # padded title-bar icon (Windows), set on first show
        geometry = app.settings.window_geometry
        self.top.geometry(geometry or f"{self._p(1080)}x{self._p(700)}")
        self.page = "overview"
        self.sort_key, self.sort_desc = "vram", True
        self.selected_key: str | None = None
        self._style()
        self._build()

    def _p(self, v):
        return round(v * self.s)

    # ------------------------------------------------------------ style
    def _style(self) -> None:
        c, f = self.c, self.f
        st = ttk.Style(self.top)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("GTM.Treeview", background=c["card"], fieldbackground=c["card"], foreground=c["text"],
                     bordercolor=c["line"], lightcolor=c["card"], darkcolor=c["card"], rowheight=self._p(30),
                     font=f["body"])
        st.map("GTM.Treeview", background=[("selected", c["hover"])], foreground=[("selected", c["text"])])
        st.configure("GTM.Treeview.Heading", background=c["raised"], foreground=c["muted"], font=f["small_b"],
                     bordercolor=c["line"], lightcolor=c["raised"], darkcolor=c["raised"], relief="flat",
                     padding=(self._p(6), self._p(6)))
        st.map("GTM.Treeview.Heading", background=[("active", c["hover"])])
        st.configure("GTM.Vertical.TScrollbar", background=c["raised"], troughcolor=c["card"],
                     bordercolor=c["card"], arrowcolor=c["muted"], lightcolor=c["raised"], darkcolor=c["raised"])

    # ------------------------------------------------------------ skeleton
    def _build(self) -> None:
        c, f = self.c, self.f
        side = tk.Frame(self.top, bg=c["sidebar"], width=self._p(232))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand_row = tk.Frame(side, bg=c["sidebar"], padx=self._p(16), pady=self._p(18))
        brand_row.pack(fill="x")
        tk.Label(brand_row, text=ICON["chip"], font=f["icon_l"], bg=c["sidebar"], fg=c["accent"]).pack(side="left")
        tk.Label(brand_row, text=brand.APP_NAME, font=f["body_b"], bg=c["sidebar"], fg=c["text"]).pack(
            side="left", padx=(self._p(10), 0))

        self.nav = {}
        for key, glyph, label in (("overview", ICON["home"], _("Overview")),
                                  ("processes", ICON["list"], _("Processes")),
                                  ("history", ICON["chart"], _("History")),
                                  ("settings", ICON["settings"], _("Settings")),
                                  ("about", ICON["info"], _("About"))):
            item = tk.Frame(side, bg=c["sidebar"], padx=self._p(10), pady=self._p(2), cursor="hand2")
            item.pack(fill="x")
            inner = tk.Frame(item, bg=c["sidebar"], padx=self._p(10), pady=self._p(8))
            inner.pack(fill="x")
            bar = tk.Frame(inner, bg=c["sidebar"], width=self._p(3))
            bar.pack(side="left", fill="y", padx=(0, self._p(10)))
            g = tk.Label(inner, text=glyph, font=f["icon_s"], bg=c["sidebar"], fg=c["text"])
            g.pack(side="left")
            t = tk.Label(inner, text=label, font=f["body"], bg=c["sidebar"], fg=c["text"])
            t.pack(side="left", padx=(self._p(12), 0))
            for w in (item, inner, g, t, bar):
                w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            self.nav[key] = (inner, bar, g, t)

        self.pause_lbl = tk.Label(side, text="", font=f["small"], bg=c["sidebar"], fg=c["muted"], cursor="hand2",
                                  padx=self._p(20), pady=self._p(14), anchor="w")
        self.pause_lbl.pack(side="bottom", fill="x")
        self.pause_lbl.bind("<Button-1>", lambda e: self.app.toggle_pause())

        self.content = tk.Frame(self.top, bg=c["surface"])
        self.content.pack(side="left", fill="both", expand=True)
        self.pages = {
            "overview": self._build_overview(),
            "processes": self._build_processes(),
            "history": self._build_history(),
            "settings": self._build_settings(),
            "about": self._build_about(),
        }

    def _page(self, title):
        c, f = self.c, self.f
        page = tk.Frame(self.content, bg=c["surface"], padx=self._p(28), pady=self._p(20))
        tk.Label(page, text=title, font=f["display"], bg=c["surface"], fg=c["text"], anchor="w").pack(fill="x")
        return page

    def _card(self, parent, pady=(16, 0), **pack):
        c = self.c
        card = tk.Frame(parent, bg=c["card"], padx=self._p(18), pady=self._p(14),
                        highlightthickness=1, highlightbackground=c["line"])
        card.pack(fill=pack.pop("fill", "x"), pady=(self._p(pady[0]), self._p(pady[1])), **pack)
        return card

    def _button(self, parent, glyph, text, command, primary=False):
        c, f = self.c, self.f
        bg = c["accent"] if primary else c["raised"]
        fg = c["on"] if primary else c["text"]
        b = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=c["accent"] if primary else c["line"],
                     cursor="hand2", takefocus=1)
        g = tk.Label(b, text=glyph, font=f["icon_s"], bg=bg, fg=fg, padx=self._p(8), pady=self._p(6))
        g.pack(side="left")
        t = tk.Label(b, text=text, font=f["body"], bg=bg, fg=fg, padx=self._p(2))
        t.pack(side="left", padx=(0, self._p(12)))
        for w in (b, g, t):
            w.bind("<Button-1>", lambda e: command())
        b.bind("<Return>", lambda e: command())
        if not primary:
            for w in (b, g, t):
                w.bind("<Enter>", lambda e: [x.configure(bg=c["hover"]) for x in (b, g, t)])
                w.bind("<Leave>", lambda e: [x.configure(bg=bg) for x in (b, g, t)])
        return b

    # ------------------------------------------------------------ overview
    def _build_overview(self):
        c, f = self.c, self.f
        page = self._page(_("Overview"))
        head = self._card(page)
        self.ov_name = tk.Label(head, text=_("Starting…"), font=f["title"], bg=c["card"], fg=c["text"], anchor="w")
        self.ov_name.pack(fill="x")
        self.ov_sub = tk.Label(head, text="", font=f["small"], bg=c["card"], fg=c["subtle"], anchor="w")
        self.ov_sub.pack(fill="x")
        self.ov_status = tk.Label(head, text="", font=f["small"], bg=c["card"], fg=c["warn"], anchor="w",
                                  wraplength=self._p(700), justify="left")

        mem = self._card(page)
        row = tk.Frame(mem, bg=c["card"])
        row.pack(fill="x")
        tk.Label(row, text=_("GPU memory"), font=f["body_b"], bg=c["card"], fg=c["text"]).pack(side="left")
        self.ov_vram = tk.Label(row, text="", font=f["body_b"], bg=c["card"], fg=c["text"])
        self.ov_vram.pack(side="right")
        self.ov_bar = StackedBar(mem, c, self.s, height=16)
        self.ov_bar.canvas.configure(bg=c["card"])
        self.ov_bar.canvas.pack(fill="x", pady=(self._p(10), self._p(8)))
        # Flow layout: entries wrap onto a new row instead of running past the card edge.
        self.ov_legend = tk.Frame(mem, bg=c["card"], height=1)
        self.ov_legend.pack(fill="x")
        self.ov_legend.bind("<Configure>", lambda _e: self._flow_legend())

        grid = tk.Frame(page, bg=c["surface"])
        grid.pack(fill="x", pady=(self._p(8), 0))
        self.ov_tiles = {}
        specs = (("gpu", ICON["speed"], _("GPU load")), ("memact", ICON["memory"], _("Memory activity")),
                 ("temp", ICON["temp"], _("Temperature")), ("power", ICON["bolt"], _("Power")),
                 ("clock", ICON["chip"], _("Clock")), ("fan", ICON["fan"], _("Fan")),
                 ("video", ICON["play"], f"{_('Encoder')} / {_('Decoder')}"), ("pcie", ICON["open"], "PCIe rx / tx"))
        for i, (key, glyph, label) in enumerate(specs):
            tile = tk.Frame(grid, bg=c["card"], padx=self._p(14), pady=self._p(12),
                            highlightthickness=1, highlightbackground=c["line"])
            tile.grid(row=i // 4, column=i % 4, sticky="nsew", padx=self._p(4), pady=self._p(4))
            top = tk.Frame(tile, bg=c["card"])
            top.pack(fill="x")
            tk.Label(top, text=glyph, font=f["icon_s"], bg=c["card"], fg=c["subtle"]).pack(side="left")
            tk.Label(top, text=label, font=f["small"], bg=c["card"], fg=c["subtle"]).pack(side="left",
                                                                                       padx=(self._p(6), 0))
            v = tk.Label(tile, text="—", font=f["metric"], bg=c["card"], fg=c["text"], anchor="w")
            v.pack(fill="x", pady=(self._p(4), 0))
            self.ov_tiles[key] = v
        for col in range(4):
            grid.columnconfigure(col, weight=1, uniform="ov")

        trend = self._card(page, pady=(12, 0), fill="both", expand=True)
        legend = tk.Frame(trend, bg=c["card"])
        legend.pack(fill="x")
        tk.Label(legend, text=_("History"), font=f["body_b"], bg=c["card"], fg=c["text"]).pack(side="left")
        for text, colour in ((_("VRAM"), c["series2"]), (_("GPU load"), c["accent"])):
            tk.Label(legend, text=text, font=f["small"], bg=c["card"], fg=c["muted"]).pack(side="right",
                                                                                        padx=(2, self._p(12)))
            tk.Label(legend, text="●", font=f["small"], bg=c["card"], fg=colour).pack(side="right")
        self.ov_chart = LineChart(trend, c, self.s, height=120, slots=self.app.history.maxlen)
        self.ov_chart.canvas.pack(fill="both", expand=True, pady=(self._p(8), 0))
        return page

    def _render_overview(self, fr: Frame) -> None:
        c = self.c
        d = fr.device
        self.ov_name.configure(text=d.name)
        bits = [d.vendor, f"{_('Driver')} {d.driver}" if d.driver else "", f"CUDA {d.cuda}" if d.cuda else "",
                d.backend.upper() if d.backend else ""]
        self.ov_sub.configure(text="   ·   ".join(b for b in bits if b))
        if d.status:
            self.ov_status.configure(text=d.status)
            self.ov_status.pack(fill="x", pady=(self._p(6), 0))
        else:
            self.ov_status.pack_forget()

        pct = d.vram_pct
        self.ov_vram.configure(text=f"{fmt_bytes(d.vram_used)} / {fmt_bytes(d.vram_total)}   ({fmt_pct(pct)})",
                               fg=level_color(c, pct))
        palette = [c["accent"], c["series2"], c["series3"], c["series4"]]
        with_vram = [p for p in fr.procs if p.vram]
        top = with_vram[:len(palette)]
        parts = [(p.vram, col) for p, col in zip(top, palette)]
        # The rest is two different things: smaller processes, and memory Windows charges to no process
        # (driver and kernel allocations, display buffers, NVIDIA's reserve).
        rest = sum(p.vram for p in with_vram[len(palette):])
        unattributed = max(0.0, (d.vram_used or 0) - sum(x for x, _c in parts) - rest)
        parts += [(rest, c["subtle"]), (unattributed, c["unattributed"])]
        self.ov_bar.update(parts, d.vram_total or 1)
        entries = [(p.name, p.vram, col) for p, col in zip(top, palette)]
        if rest:
            entries.append((_("Other processes"), rest, c["subtle"]))
        if unattributed >= 1024 ** 2:
            entries.append((_("Not attributed"), unattributed, c["unattributed"]))
        if d.shared_used:
            entries.append((_("Spill to RAM"), d.shared_used, c["warn"]))
        if not hasattr(self, "_legend_pool"):  # fixed set of chips, reconfigured: no flicker
            self._legend_pool = []
            for _i in range(7):
                chip = tk.Frame(self.ov_legend, bg=c["card"])
                dot = tk.Label(chip, text="●", font=self.f["small"], bg=c["card"])
                txt = tk.Label(chip, font=self.f["small"], bg=c["card"], fg=c["muted"])
                dot.pack(side="left")
                txt.pack(side="left", padx=(2, 0))
                self._legend_pool.append((chip, dot, txt))
        self._legend_count = len(entries)
        for (_chip, dot, txt), (name, size, col) in zip(self._legend_pool, entries):
            dot.configure(fg=col)
            txt.configure(text=f"{name} {fmt_bytes(size)}")
        self.ov_legend.after_idle(self._flow_legend)  # chip sizes settle at idle

        load = device_load(fr)
        t = self.ov_tiles
        t["gpu"].configure(text=fmt_pct(load))
        t["memact"].configure(text=fmt_pct(d.util_mem))
        hot = d.temp is not None and self.app.settings.alert_temp_c and d.temp >= self.app.settings.alert_temp_c
        t["temp"].configure(text=fmt_temp(d.temp), fg=c["crit"] if hot else c["text"])
        t["power"].configure(text=fmt_watts(d.power_w, d.power_limit_w))
        t["clock"].configure(text=fmt_mhz(d.sm_clock))
        t["fan"].configure(text=fmt_pct(d.fan))
        t["video"].configure(text=f"{fmt_pct(d.enc)} / {fmt_pct(d.dec)}")
        rx = f"{d.pcie_rx_mbs:.0f}" if d.pcie_rx_mbs is not None else _("n/a")
        tx = f"{d.pcie_tx_mbs:.0f}" if d.pcie_tx_mbs is not None else _("n/a")
        t["pcie"].configure(text=f"{rx} / {tx} MB/s")
        h = self.app.history
        self.ov_chart.update([(h.vram, c["series2"]), (h.gpu, c["accent"])])

    def _flow_legend(self) -> None:
        """Place the visible legend chips left to right, wrapping to a new row at the card edge."""
        pool = getattr(self, "_legend_pool", None)
        if not pool or not self.ov_legend.winfo_exists():
            return
        width = self.ov_legend.winfo_width()
        if width <= 1:  # not mapped yet: lay out on one row, <Configure> reflows later
            width = 1 << 30
        gap_x, gap_y = self._p(14), self._p(4)
        x = y = row_h = 0
        for i, (chip, _dot, _txt) in enumerate(pool):
            if i >= self._legend_count:
                chip.place_forget()
                continue
            w, h = chip.winfo_reqwidth(), chip.winfo_reqheight()
            if x and x + w > width:
                x, y, row_h = 0, y + row_h + gap_y, 0
            chip.place(x=x, y=y)
            x += w + gap_x
            row_h = max(row_h, h)
        height = max(1, y + row_h)
        if int(self.ov_legend.cget("height")) != height:
            self.ov_legend.configure(height=height)

    # ------------------------------------------------------------ processes
    COLUMNS = (("pid", "PID", 70, "e"), ("name", "Process", 200, "w"), ("kind", "Kind", 90, "w"),
               ("vram", "VRAM", 90, "e"), ("spill", "Spill", 80, "e"), ("paged", "Paged", 80, "e"),
               ("gpu", "GPU %", 60, "e"), ("inside", "Inside", 320, "w"))

    def _build_processes(self):
        c, f = self.c, self.f
        page = self._page(_("Processes"))
        pane = tk.PanedWindow(page, orient="vertical", bg=c["surface"], sashwidth=self._p(8), bd=0,
                              sashrelief="flat")
        pane.pack(fill="both", expand=True, pady=(self._p(16), 0))

        table = tk.Frame(pane, bg=c["card"], highlightthickness=1, highlightbackground=c["line"])
        cols = [k for k, *_r in self.COLUMNS]
        self.tree = ttk.Treeview(table, columns=cols, show="headings", style="GTM.Treeview", selectmode="browse")
        for key, label, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=_(label), anchor=anchor, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=self._p(width), anchor=anchor, stretch=key == "inside")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="GTM.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.tag_configure("odd", background=c["raised"])
        pane.add(table, minsize=self._p(160), stretch="always")

        detail = tk.Frame(pane, bg=c["card"], highlightthickness=1, highlightbackground=c["line"],
                          padx=self._p(16), pady=self._p(12))
        actions = tk.Frame(detail, bg=c["card"])
        actions.pack(fill="x", side="bottom", pady=(self._p(8), 0))
        self._button(actions, ICON["copy"], _("Copy details"), self._copy_details).pack(side="left")
        self._button(actions, ICON["folder"], _("Open file location"), self._open_location).pack(
            side="left", padx=self._p(8))
        self._button(actions, ICON["close"], _("End process"), self._end_process).pack(side="right")
        self.detail = tk.Text(detail, bg=c["card"], fg=c["text"], font=f["mono"], relief="flat", wrap="word",
                              height=10, highlightthickness=0, padx=0, pady=0, cursor="arrow")
        self.detail.tag_configure("h", font=f["body_b"], foreground=c["text"], spacing1=self._p(6))
        self.detail.tag_configure("m", foreground=c["muted"])
        self.detail.pack(fill="both", expand=True)
        pane.add(detail, minsize=self._p(140))
        self._set_detail(None)
        return page

    def _sort(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key not in ("name", "kind", "inside", "pid")
        if self.app.frame:
            self._render_processes(self.app.frame)

    def _sort_value(self, p: Proc):
        k = self.sort_key
        if k == "pid":
            return p.pid
        if k == "name":
            return p.name.lower()
        if k == "kind":
            return p.kind
        if k == "inside":
            return shown_inside(p.inside).lower()
        v = {"vram": p.vram, "spill": p.spill, "paged": p.paged, "gpu": p.gpu_pct}[k]
        return -1.0 if v is None else v

    def _render_processes(self, fr: Frame) -> None:
        procs = sorted(fr.procs, key=self._sort_value, reverse=self.sort_desc)
        self._by_key = {p.key: p for p in procs}
        existing = set(self.tree.get_children())
        wanted = []
        for i, p in enumerate(procs):
            values = (p.pid_label, p.name, p.kind, fmt_bytes(p.vram) if p.vram is not None else _("n/a"),
                      fmt_bytes(p.spill) if p.spill else "", fmt_bytes(p.paged) if p.paged else "",
                      fmt_pct(p.gpu_pct) if p.gpu_pct is not None else _("n/a"), shown_inside(p.inside))
            tags = ("odd",) if i % 2 else ()
            if p.key in existing:
                self.tree.item(p.key, values=values, tags=tags)
            else:
                self.tree.insert("", "end", iid=p.key, values=values, tags=tags)
            wanted.append(p.key)
        gone = existing - set(wanted)
        if gone:
            self.tree.delete(*gone)
        for i, key in enumerate(wanted):
            self.tree.move(key, "", i)
        for key, label, _w, anchor in self.COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_key else ""
            self.tree.heading(key, text=_(label) + arrow)
        if self.selected_key in self._by_key:
            if self.tree.selection() != (self.selected_key,):
                self.tree.selection_set(self.selected_key)
            self._set_detail(self._by_key[self.selected_key])
        elif self.selected_key is not None:
            self.selected_key = None
            self._set_detail(None)

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        key = sel[0] if sel else None
        if key != self.selected_key:
            self.selected_key = key
            self._set_detail(getattr(self, "_by_key", {}).get(key))

    def _set_detail(self, p: Proc | None) -> None:
        t = self.detail
        y = t.yview()[0]
        t.configure(state="normal")
        t.delete("1.0", "end")
        if p is None:
            t.insert("end", _("Select a process to see what it holds."), "m")
        else:
            for heading, lines in describe(p):
                t.insert("end", heading + "\n", "h")
                for line in lines:
                    t.insert("end", line + "\n", "m")
        t.configure(state="disabled")
        t.yview_moveto(y)

    def _current(self) -> Proc | None:
        return getattr(self, "_by_key", {}).get(self.selected_key)

    def _copy_details(self):
        p = self._current()
        if p:
            self.top.clipboard_clear()
            self.top.clipboard_append(describe_text(p))

    def _open_location(self):
        p = self._current()
        if p and p.exe and os.path.exists(p.exe) and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", p.exe])

    def _end_process(self):
        p = self._current()
        if not p or p.host:
            return
        if not messagebox.askyesno(brand.APP_NAME, _("End {name} (PID {pid})? Unsaved work in that program will "
                                                   "be lost.").format(name=p.name, pid=p.pid),
                                   icon="warning", parent=self.top):
            return
        try:
            import psutil
            psutil.Process(p.pid).terminate()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            messagebox.showerror(brand.APP_NAME, _("Could not end the process: {error}").format(error=exc),
                                 parent=self.top)

    # ------------------------------------------------------------ history
    def _build_history(self):
        c, f = self.c, self.f
        page = self._page(_("History"))
        grid = tk.Frame(page, bg=c["surface"])
        grid.pack(fill="both", expand=True, pady=(self._p(12), 0))
        self.charts = {}
        specs = (("gpu", _("GPU load"), "%", c["accent"], 100.0, False),
                 ("vram", _("VRAM"), "%", c["series2"], 100.0, False),
                 ("temp", _("Temperature"), "°C", c["series3"], 100.0, True),
                 ("power", _("Power"), "W", c["series4"], 50.0, True))
        for i, (key, title, unit, colour, top, auto) in enumerate(specs):
            card = tk.Frame(grid, bg=c["card"], padx=self._p(14), pady=self._p(12),
                            highlightthickness=1, highlightbackground=c["line"])
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=self._p(4), pady=self._p(4))
            row = tk.Frame(card, bg=c["card"])
            row.pack(fill="x")
            tk.Label(row, text=title, font=f["body_b"], bg=c["card"], fg=c["text"]).pack(side="left")
            value = tk.Label(row, text="", font=f["body_b"], bg=c["card"], fg=colour)
            value.pack(side="right")
            chart = LineChart(card, c, self.s, height=150, slots=self.app.history.maxlen, top=top, auto_top=auto,
                              font=f["small"])
            chart.canvas.pack(fill="both", expand=True, pady=(self._p(8), 0))
            self.charts[key] = (chart, value, unit, colour)
        for col in range(2):
            grid.columnconfigure(col, weight=1, uniform="h")
        for r in range(2):
            grid.rowconfigure(r, weight=1, uniform="hr")
        span = self.app.history.maxlen * self.app.settings.interval
        tk.Label(page, text=f"{span / 60:.0f} min", font=f["small"], bg=c["surface"], fg=c["subtle"],
                 anchor="e").pack(fill="x")
        return page

    def _render_history(self, fr: Frame) -> None:
        h = self.app.history
        for key, (chart, value, unit, colour) in self.charts.items():
            data = getattr(h, key)
            chart.update([(data, colour)])
            last = data[-1] if data else None
            value.configure(text="—" if last is None else f"{last:.0f} {unit}")

    # ------------------------------------------------------------ settings
    def _build_settings(self):
        c, f = self.c, self.f
        page = self._page(_("Settings"))
        s = self.app.settings
        container = ScrollFrame(page, c)
        container.outer.pack(fill="both", expand=True)
        scroll = container.inner
        scroll.configure(padx=self._p(2))

        def section(title):
            tk.Label(scroll, text=title, font=f["body_b"], bg=c["surface"], fg=c["text"], anchor="w").pack(
                fill="x", pady=(self._p(18), self._p(2)))

        def row(title, subtitle=""):
            card = self._card(scroll, pady=(6, 0))
            left = tk.Frame(card, bg=c["card"])
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=title, font=f["body"], bg=c["card"], fg=c["text"], anchor="w").pack(fill="x")
            if subtitle:
                tk.Label(left, text=subtitle, font=f["small"], bg=c["card"], fg=c["subtle"], anchor="w").pack(
                    fill="x")
            right = tk.Frame(card, bg=c["card"])
            right.pack(side="right")
            return right

        section(_("General"))
        r = row(_("Start with Windows"), _("Runs in the tray at sign-in."))
        self.autostart_switch = Switch(r, c, self.s, self._set_autostart, autostart.is_enabled())
        self.autostart_switch.canvas.pack()
        r = row(_("Refresh interval"), _("seconds"))
        Choice(r, c, f["small"], [(v, f"{v:g}") for v in INTERVALS], s.interval,
               lambda v: self.app.update_setting("interval", v)).frame.pack()
        r = row(_("Graphics card"), _("Restart required for the graphics card change."))
        self.gpu_choice_host = r
        self._gpu_choice()

        section(_("Appearance"))
        r = row(_("Theme"))
        Choice(r, c, f["small"], [("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))], s.theme,
               lambda v: self.app.update_setting("theme", v)).frame.pack()
        r = row(_("Language"))
        Choice(r, c, f["small"], [("system", _("System")), *LANGUAGE_NAMES.items()], s.language,
               lambda v: self.app.update_setting("language", v)).frame.pack()
        r = row(_("Tray icon shows"))
        Choice(r, c, f["small"], [("vram", _("VRAM in use")), ("gpu", _("GPU load (busiest engine)"))],
               s.tray_metric, lambda v: self.app.update_setting("tray_metric", v)).frame.pack()

        section(_("Alerts"))
        r = row(_("Notify when VRAM is above"))
        Choice(r, c, f["small"], [(v, f"{v}%" if v else _("Off")) for v in VRAM_ALERTS], s.alert_vram_pct,
               lambda v: self.app.update_setting("alert_vram_pct", v)).frame.pack()
        r = row(_("Notify when temperature is above"))
        Choice(r, c, f["small"], [(v, f"{v} °C" if v else _("Off")) for v in TEMP_ALERTS], s.alert_temp_c,
               lambda v: self.app.update_setting("alert_temp_c", v)).frame.pack()
        tk.Label(scroll, text=_("Changes apply immediately."), font=f["small"], bg=c["surface"], fg=c["subtle"],
                 anchor="w").pack(fill="x", pady=(self._p(14), 0))
        return page

    def _gpu_choice(self):
        for w in self.gpu_choice_host.winfo_children():
            w.destroy()
        names = self.app.adapters or (_("n/a"),)
        options = [(i, n if len(n) <= 28 else n[:27] + "…") for i, n in enumerate(names)]
        Choice(self.gpu_choice_host, self.c, self.f["small"], options, self.app.settings.gpu_index,
               lambda v: self.app.update_setting("gpu_index", v)).frame.pack()

    def _set_autostart(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError as exc:
            log.exception("autostart change failed")
            messagebox.showerror(brand.APP_NAME, str(exc), parent=self.top)
            self.autostart_switch.set(autostart.is_enabled())

    # ------------------------------------------------------------ about
    def _link(self, parent, text, url):
        """A label that opens `url` in the default browser (click, Enter or Space)."""
        c, f = self.c, self.f
        font = tkfont.Font(font=f["body"])
        font.configure(underline=True)
        lbl = tk.Label(parent, text=text, font=font, bg=parent["bg"], fg=c["accent"], cursor="hand2", takefocus=1)
        for seq in ("<Button-1>", "<Return>", "<space>"):
            lbl.bind(seq, lambda _e: webbrowser.open(url))
        return lbl

    def _build_about(self):
        c, f = self.c, self.f
        page = self._page(_("About"))
        card = self._card(page)
        tk.Label(card, text=brand.APP_NAME, font=f["title"], bg=c["card"], fg=c["text"], anchor="w").pack(fill="x")
        tk.Label(card, text=f"{_('Version')} {brand.APP_VERSION}   ·   {brand.COPYRIGHT}", font=f["small"],
                 bg=c["card"], fg=c["subtle"], anchor="w").pack(fill="x")
        tk.Label(card, text=_("Measured values come from Windows GPU counters and NVML. Model identification and LLM "
                              "memory breakdowns are estimates based on evidence such as mapped files, GGUF headers, "
                              "runtime logs and local server APIs."),
                 font=f["body"], bg=c["card"], fg=c["muted"], anchor="w", justify="left",
                 wraplength=self._p(720)).pack(fill="x", pady=(self._p(12), 0))
        links = self._card(page)
        for label, text, url in ((_("Source code"), brand.REPO_URL, brand.REPO_URL),
                                 (_("Author"), f"{brand.AUTHOR}  ·  {brand.AUTHOR_URL}", brand.AUTHOR_URL)):
            row = tk.Frame(links, bg=c["card"])
            row.pack(fill="x", pady=self._p(2))
            tk.Label(row, text=label, font=f["body_b"], bg=c["card"], fg=c["text"], anchor="w",
                     width=14).pack(side="left")
            self._link(row, text, url).pack(side="left")
        tk.Label(links, text=_("Free for non-commercial use under the PolyForm Noncommercial License 1.0.0. "
                               "For commercial use, contact the author."),
                 font=f["small"], bg=c["card"], fg=c["subtle"], anchor="w", justify="left",
                 wraplength=self._p(720)).pack(fill="x", pady=(self._p(8), 0))
        actions = tk.Frame(page, bg=c["surface"])
        actions.pack(fill="x", pady=(self._p(16), 0))
        self._button(actions, ICON["save"], _("Export snapshot…"), self.export_snapshot, primary=True).pack(
            side="left")
        self._button(actions, ICON["copy"], _("Copy report"), self.copy_report).pack(side="left", padx=self._p(8))
        self._button(actions, ICON["info"], _("Third-party licenses"), self._licenses).pack(side="left")
        self._button(actions, ICON["folder"], _("Open log folder"), lambda: open_path(data_dir())).pack(
            side="left", padx=self._p(8))
        self._button(actions, ICON["power"], _("Exit"), self.app.exit).pack(side="right")
        self.about_msg = tk.Label(page, text="", font=f["small"], bg=c["surface"], fg=c["ok"], anchor="w")
        self.about_msg.pack(fill="x", pady=(self._p(10), 0))
        return page

    def _licenses(self):
        base = resource_dir()
        target = base / "THIRD-PARTY-NOTICES.txt"
        if not target.exists():
            target = base / "THIRD-PARTY-NOTICES.md"
        open_path(target if target.exists() else base / "licenses")

    def export_snapshot(self):
        fr = self.app.frame
        if fr is None:
            return
        path = filedialog.asksaveasfilename(parent=self.top, defaultextension=".json",
                                            initialfile=f"{brand.APP_SLUG}-snapshot.json",
                                            filetypes=[("JSON", "*.json")])
        if path:
            Path(path).write_text(json.dumps(fr.raw, indent=2, default=str), encoding="utf-8")
            self.about_msg.configure(text=_("Snapshot saved."))

    def copy_report(self):
        fr = self.app.frame
        if fr is None:
            return
        self.top.clipboard_clear()
        self.top.clipboard_append(fr.text)
        self.about_msg.configure(text=_("Report copied to the clipboard."))

    # ------------------------------------------------------------ navigation & lifecycle
    def show_page(self, key: str) -> None:
        if key not in PAGES:
            key = "overview"
        self.page = key
        c = self.c
        for k, (inner, bar, g, t) in self.nav.items():
            on = k == key
            bg = c["hover"] if on else c["sidebar"]
            for w in (inner, g, t):
                w.configure(bg=bg)
            bar.configure(bg=c["accent"] if on else bg)
        for k, page in self.pages.items():
            if k == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        if key == "settings":
            self.autostart_switch.set(autostart.is_enabled())
            self._gpu_choice()
        self.render(self.app.frame)

    @property
    def visible(self) -> bool:
        return self.top.winfo_exists() and self.top.state() != "withdrawn"

    def show(self, page: str | None = None) -> None:
        self.top.deiconify()
        style_window(self.top, self.app.dark, rounded_corners=False)
        self._set_caption_icon()
        self.show_page(page or self.page)
        self.top.lift()
        self.top.focus_force()

    def hide(self) -> None:
        if self.top.winfo_exists():
            self.app.remember_geometry(self.top.geometry())
            self.top.withdraw()

    def destroy(self) -> None:
        if self.top.winfo_exists():
            self.app.remember_geometry(self.top.geometry())
            self.top.destroy()
        if self._caption_hicon:
            from . import winicon
            winicon.destroy(self._caption_hicon)
            self._caption_hicon = None

    def _set_caption_icon(self) -> None:
        if sys.platform != "win32" or self._caption_hicon:
            return
        try:
            from . import winicon
            self.top.update_idletasks()
            self._caption_hicon = winicon.set_caption_icon(int(self.top.wm_frame(), 16), art.caption_icon())
        except Exception:  # noqa: BLE001 - cosmetic: keep Tk's own icon
            log.debug("caption icon not set", exc_info=True)

    def render(self, fr: Frame | None) -> None:
        self.pause_lbl.configure(text=(f"{_('Paused')}  ·  {_('Resume')}" if self.app.paused else _("Pause")),
                                 fg=self.c["warn"] if self.app.paused else self.c["muted"])
        if fr is None:
            if self.app.error:
                self.ov_name.configure(text=_("The GPU counters could not be started."))
                self.ov_sub.configure(text=_("Is an NVIDIA or AMD driver installed? Details are in the log."))
                self.ov_status.configure(text=self.app.error)
                self.ov_status.pack(fill="x", pady=(self._p(6), 0))
            return
        if self.page == "overview":
            self._render_overview(fr)
        elif self.page == "processes":
            self._render_processes(fr)
        elif self.page == "history":
            self._render_history(fr)
