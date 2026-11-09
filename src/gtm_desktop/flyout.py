"""Quick panel opened by a right click on the tray icon, styled like Windows 11 Quick Settings.

Built once and reused: every widget exists from the start and render() only
changes texts and redraws two canvases, so updates never flicker. The panel
hides when it loses focus or on Escape, like any Windows flyout.
"""

from __future__ import annotations

import time
import tkinter as tk

from . import brand
from .charts import LineChart, StackedBar
from .fluent import ICON, level_color, style_window, work_area
from .i18n import _
from .model import Frame, device_load, fmt_bytes, fmt_mhz, fmt_pct, fmt_temp, fmt_watts, shown_inside

WIDTH = 380
TOP_N = 5
SLOTS = 60  # one minute at the default interval


class Flyout:
    def __init__(self, app) -> None:
        self.app = app
        c, s = app.theme, app.scale
        self.c, self.s = c, s
        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=c["surface"], highlightthickness=1, highlightbackground=c["line"])
        self.top.bind("<Escape>", lambda e: self.hide())
        self.top.bind("<FocusOut>", self._focus_out)
        self._hidden_at = 0.0
        self.max_rows = TOP_N  # lowered by show() when the panel would not fit the screen
        self._build()

    def _p(self, v):
        return round(v * self.s)

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        c, f = self.c, self.app.fonts
        body = tk.Frame(self.top, bg=c["surface"], padx=self._p(16), pady=self._p(14))
        body.pack(fill="both", expand=True)

        head = tk.Frame(body, bg=c["surface"])
        head.pack(fill="x")
        tk.Label(head, text=ICON["chip"], font=f["icon_l"], bg=c["surface"], fg=c["accent"]).pack(side="left")
        # Pause first: packed before the names it keeps its space, and a long GPU name is clipped, not drawn over it.
        self.pause = self._glyph_button(head, ICON["pause"], self.app.toggle_pause)
        self.pause.pack(side="right")
        names = tk.Frame(head, bg=c["surface"])
        names.pack(side="left", padx=(self._p(10), self._p(6)), fill="x", expand=True)
        self.name = tk.Label(names, text=_("Starting…"), font=f["title"], bg=c["surface"], fg=c["text"], anchor="w")
        self.name.pack(fill="x")
        self.sub = tk.Label(names, text="", font=f["small"], bg=c["surface"], fg=c["subtle"], anchor="w")
        self.sub.pack(fill="x")

        # VRAM card
        card = self._card(body)
        row = tk.Frame(card, bg=c["card"])
        row.pack(fill="x")
        tk.Label(row, text=_("GPU memory"), font=f["body_b"], bg=c["card"], fg=c["text"]).pack(side="left")
        self.vram_pct = tk.Label(row, text="", font=f["body_b"], bg=c["card"], fg=c["accent"])
        self.vram_pct.pack(side="right")
        self.vram_bar = StackedBar(card, c, self.s, height=10)
        self.vram_bar.canvas.configure(bg=c["card"])
        self.vram_bar.canvas.pack(fill="x", pady=(self._p(8), self._p(6)))
        self.vram_text = tk.Label(card, text="", font=f["small"], bg=c["card"], fg=c["muted"], anchor="w")
        self.vram_text.pack(fill="x")

        # metric tiles 2x2
        grid = tk.Frame(body, bg=c["surface"])
        grid.pack(fill="x", pady=(self._p(8), 0))
        self.tiles = {}
        for i, (key, glyph, label) in enumerate((("gpu", ICON["speed"], _("GPU load")),
                                                 ("temp", ICON["temp"], _("Temperature")),
                                                 ("power", ICON["bolt"], _("Power")),
                                                 ("clock", ICON["chip"], _("Clock")))):
            tile = tk.Frame(grid, bg=c["card"], padx=self._p(12), pady=self._p(10),
                            highlightthickness=1, highlightbackground=c["line"])
            tile.grid(row=i // 2, column=i % 2, sticky="nsew",
                      padx=(0, self._p(4)) if i % 2 == 0 else (self._p(4), 0), pady=self._p(4))
            top = tk.Frame(tile, bg=c["card"])
            top.pack(fill="x")
            tk.Label(top, text=glyph, font=f["icon_s"], bg=c["card"], fg=c["subtle"]).pack(side="left")
            tk.Label(top, text=label, font=f["small"], bg=c["card"], fg=c["subtle"]).pack(side="left",
                                                                                       padx=(self._p(6), 0))
            value = tk.Label(tile, text="—", font=f["metric"], bg=c["card"], fg=c["text"], anchor="w")
            value.pack(fill="x", pady=(self._p(2), 0))
            self.tiles[key] = value
        grid.columnconfigure(0, weight=1, uniform="t")
        grid.columnconfigure(1, weight=1, uniform="t")

        # last minute
        chart_card = self._card(body)
        legend = tk.Frame(chart_card, bg=c["card"])
        legend.pack(fill="x")
        for text, colour in ((_("GPU load"), c["accent"]), (_("VRAM"), c["series2"])):
            tk.Label(legend, text="●", font=f["small"], bg=c["card"], fg=colour).pack(side="left")
            tk.Label(legend, text=text, font=f["small"], bg=c["card"], fg=c["muted"]).pack(side="left",
                                                                                        padx=(2, self._p(10)))
        self.chart = LineChart(chart_card, c, self.s, height=56, slots=SLOTS)
        self.chart.canvas.pack(fill="x", pady=(self._p(6), 0))

        # top processes
        tk.Label(body, text=_("Top processes"), font=f["body_b"], bg=c["surface"], fg=c["text"],
                 anchor="w").pack(fill="x", pady=(self._p(12), self._p(4)))
        self.rows = []
        for _i in range(TOP_N):
            r = tk.Frame(body, bg=c["surface"], cursor="hand2")
            r.pack(fill="x", pady=self._p(2))
            left = tk.Frame(r, bg=c["surface"])
            left.pack(side="left", fill="x", expand=True)
            name = tk.Label(left, text="", font=f["body"], bg=c["surface"], fg=c["text"], anchor="w")
            name.pack(fill="x")
            inside = tk.Label(left, text="", font=f["small"], bg=c["surface"], fg=c["subtle"], anchor="w")
            inside.pack(fill="x")
            size = tk.Label(r, text="", font=f["body_b"], bg=c["surface"], fg=c["text"])
            size.pack(side="right", padx=(self._p(8), 0))
            for w in (r, left, name, inside, size):
                w.bind("<Button-1>", lambda e: self._open("processes"))
            self.rows.append((r, name, inside, size))
        self.empty = tk.Label(body, text=_("No process is using this GPU right now."), font=f["small"],
                              bg=c["surface"], fg=c["subtle"], anchor="w")

        # footer
        foot = tk.Frame(self.top, bg=c["sidebar"], padx=self._p(12), pady=self._p(10))
        foot.pack(fill="x", side="bottom")
        open_lbl = tk.Label(foot, text=_("Open {app}").format(app=brand.APP_NAME), font=f["body_b"], bg=c["accent"],
                            fg=c["on"], padx=self._p(12), pady=self._p(6), cursor="hand2", takefocus=1)
        open_lbl.pack(side="left")
        open_lbl.bind("<Button-1>", lambda e: self._open("overview"))
        open_lbl.bind("<Return>", lambda e: self._open("overview"))
        self._glyph_button(foot, ICON["power"], self.app.exit, bg=c["sidebar"]).pack(side="right")
        self._glyph_button(foot, ICON["settings"], lambda: self._open("settings"),
                           bg=c["sidebar"]).pack(side="right", padx=(0, self._p(4)))

    def _card(self, parent):
        c = self.c
        card = tk.Frame(parent, bg=c["card"], padx=self._p(14), pady=self._p(12),
                        highlightthickness=1, highlightbackground=c["line"])
        card.pack(fill="x", pady=(self._p(10), 0))
        return card

    def _glyph_button(self, parent, glyph, command, bg=None):
        c, f = self.c, self.app.fonts
        bg = bg or c["surface"]
        b = tk.Label(parent, text=glyph, font=f["icon_m"], bg=bg, fg=c["text"], width=3, pady=self._p(4),
                     cursor="hand2", takefocus=1)
        b.bind("<Button-1>", lambda e: command())
        b.bind("<space>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(bg=c["hover"]))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    # ------------------------------------------------------------ behaviour
    def _open(self, page):
        self.hide()
        self.app.open_window(page)

    def _focus_out(self, event):
        # Focus moving between our own widgets also fires FocusOut: check where it went.
        self.top.after(120, self._maybe_hide)

    def _maybe_hide(self):
        try:
            focus = self.top.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is None or not str(focus).startswith(str(self.top)):
            self.hide()

    @property
    def visible(self) -> bool:
        return self.top.winfo_exists() and self.top.winfo_viewable()

    def show(self) -> None:
        w = self._p(WIDTH)
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        left, top, right, bottom = work_area() or (0, 0, sw, sh - self._p(48))
        margin = self._p(12)
        # Which screen edge the taskbar is on. The tray icon's own rectangle is the best evidence: some
        # shells do not reserve a work area for their taskbar, so it would otherwise be covered.
        icon = self.app.tray.icon_rect()
        if icon:
            il, it, ir, ib = icon
            if it >= (top + bottom) // 2:
                edge, bottom = "bottom", min(bottom, it)
            elif ib <= (top + bottom) // 2:
                edge, top = "top", max(top, ib)
            elif il >= (left + right) // 2:
                edge, right = "right", min(right, il)
            else:
                edge, left = "left", max(left, ir)
        else:  # fall back to the work area offset (bottom-right by default)
            edge = "left" if left > 0 else "top" if top > 0 else "bottom"
        room = bottom - top - 2 * margin
        # Tallest layout that fits: drop process rows from the bottom, then clip as a last resort.
        self.max_rows = TOP_N
        while True:
            self.render(self.app.frame)
            self.top.update_idletasks()
            h = self.top.winfo_reqheight()
            if h <= room or self.max_rows <= 1:
                break
            self.max_rows -= 1
        h = min(h, room)
        # Next to the notification area, in the corner of the taskbar's edge.
        x = left + margin if edge == "left" else right - w - margin
        y = top + margin if edge == "top" else bottom - h - margin
        self.top.geometry(f"{w}x{h}+{x}+{y}")
        self.top.deiconify()
        style_window(self.top, self.app.dark)
        self.top.lift()
        self.top.focus_force()

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.4:
            # A click on the tray icon first takes focus away (which hides the panel), then
            # arrives here: without this guard that click would reopen what it just closed.
            self.show()

    def hide(self) -> None:
        if self.top.winfo_exists() and self.visible:
            self.top.withdraw()
            self._hidden_at = time.monotonic()

    def destroy(self) -> None:
        if self.top.winfo_exists():
            self.top.destroy()

    def render(self, frame: Frame | None) -> None:
        c = self.c
        self.pause.configure(text=ICON["play"] if self.app.paused else ICON["pause"])
        if self.app.error and frame is None:
            self.name.configure(text=_("No GPU"))
            self.sub.configure(text=self.app.error[:80])
            return
        if frame is None:
            return
        d = frame.device
        self.name.configure(text=d.name)
        sub = [x for x in (f"{_('Driver')} {d.driver}" if d.driver else "", f"CUDA {d.cuda}" if d.cuda else "",
                           _("Paused") if self.app.paused else "") if x]
        self.sub.configure(text="   ·   ".join(sub))

        pct = d.vram_pct
        self.vram_pct.configure(text=fmt_pct(pct), fg=level_color(c, pct))
        parts, palette = [], [c["accent"], c["series2"], c["series3"], c["series4"]]
        with_vram = [p for p in frame.procs if p.vram]
        top = with_vram[:len(palette)]
        for p, colour in zip(top, palette):
            parts.append((p.vram, colour))
        if d.vram_used is not None:  # same split as the main window: other processes, then not attributed
            rest = sum(p.vram for p in with_vram[len(palette):])
            parts.append((rest, c["subtle"]))
            parts.append((max(0.0, d.vram_used - sum(x for x, _c in parts)), c["unattributed"]))
        self.vram_bar.update(parts, d.vram_total or 1)
        text = f"{fmt_bytes(d.vram_used)} {_('of')} {fmt_bytes(d.vram_total)}"
        if d.shared_used:
            text += f"   ·   {_('Spill to RAM')} {fmt_bytes(d.shared_used)}"
        self.vram_text.configure(text=text)

        load = device_load(frame)
        self.tiles["gpu"].configure(text=fmt_pct(load), fg=level_color(c, load, 90, 98) if load else c["text"])
        self.tiles["temp"].configure(text=fmt_temp(d.temp),
                                     fg=c["crit"] if d.temp and d.temp >= self.app.settings.alert_temp_c > 0
                                     else c["text"])
        self.tiles["power"].configure(text=fmt_watts(d.power_w))
        self.tiles["clock"].configure(text=fmt_mhz(d.sm_clock))

        h = self.app.history
        self.chart.update([(list(h.vram)[-SLOTS:], c["series2"]), (list(h.gpu)[-SLOTS:], c["accent"])])

        procs = [p for p in frame.procs if (p.vram or 0) > 0 or (p.gpu_pct or 0) >= 1][:self.max_rows]
        for i, (r, name, inside, size) in enumerate(self.rows):
            if i < len(procs):
                p = procs[i]
                name.configure(text=p.name)
                inside.configure(text=(shown_inside(p.inside) or p.kind)[:58])
                size.configure(text=fmt_bytes(p.vram) if p.vram is not None else fmt_pct(p.gpu_pct))
                if not r.winfo_manager():  # hidden rows are always the tail, so order holds
                    r.pack(fill="x", pady=self._p(2), before=self.empty if self.empty.winfo_manager() else None)
            elif r.winfo_manager():
                r.pack_forget()
        if procs:
            self.empty.pack_forget()
        elif not self.empty.winfo_manager():
            self.empty.pack(fill="x")
