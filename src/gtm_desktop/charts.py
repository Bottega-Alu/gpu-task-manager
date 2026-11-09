"""Canvas charts: a filled line chart and a horizontal stacked bar.

Both redraw from scratch on every update; at one sample per second and a few
hundred points that is far below a millisecond of Tk work.
"""

from __future__ import annotations

import tkinter as tk


def _hex_mix(a: str, b: str, t: float) -> str:
    """Blend colour a toward b by t (Tk canvas has no alpha)."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t), round(ag + (bg - ag) * t), round(ab + (bb - ab) * t))


class LineChart:
    """One or more series over a fixed number of slots, newest on the right.

    series: list of (values, colour). Missing samples (None) break the line, so
    a gap reads as "no reading", never as zero.
    """

    def __init__(self, parent, theme, scale, height=140, slots=300, top=100.0, auto_top=False,
                 grid_lines=4, font=None):
        self.theme, self.scale = theme, scale
        self.slots, self.top, self.auto_top, self.grid_lines = slots, top, auto_top, grid_lines
        self.font = font
        self.canvas = tk.Canvas(parent, height=round(height * scale), bg=theme["card"], highlightthickness=0)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._series: list[tuple[list, str]] = []

    def update(self, series: list[tuple[list, str]]) -> None:
        self._series = [(list(v), c) for v, c in series]
        self._redraw()

    def _redraw(self) -> None:
        c, cv = self.theme, self.canvas
        if not cv.winfo_exists():
            return
        cv.delete("all")
        w, h = max(cv.winfo_width(), 50), max(cv.winfo_height(), 30)
        pad = round(4 * self.scale)
        top = self.top
        if self.auto_top:
            peak = max((x for v, _ in self._series for x in v if x is not None), default=0.0)
            top = max(self.top, peak * 1.15)
        for i in range(1, self.grid_lines):
            y = pad + (h - 2 * pad) * i / self.grid_lines
            cv.create_line(0, y, w, y, fill=c["line"], dash=(2, 4))
        step = (w - 1) / max(1, self.slots - 1)
        for values, colour in self._series:
            values = values[-self.slots:]
            offset = self.slots - len(values)
            run: list[tuple[float, float]] = []
            fill = _hex_mix(colour, c["card"], 0.82)

            def flush(points):
                if len(points) >= 2:
                    poly = points + [(points[-1][0], h), (points[0][0], h)]
                    cv.create_polygon(*[k for p in poly for k in p], fill=fill, outline="")
                    cv.create_line(*[k for p in points for k in p], fill=colour,
                                   width=max(1, round(1.6 * self.scale)), smooth=False)
                elif len(points) == 1:
                    x, y = points[0]
                    r = max(1, round(1.5 * self.scale))
                    cv.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline="")

            for i, v in enumerate(values):
                if v is None:
                    flush(run)
                    run = []
                    continue
                x = (offset + i) * step
                y = pad + (h - 2 * pad) * (1 - max(0.0, min(v, top)) / top)
                run.append((x, y))
            flush(run)
        if self.auto_top and self.font:
            cv.create_text(w - pad, pad, text=f"{top:.0f}", anchor="ne", fill=c["subtle"], font=self.font)


class StackedBar:
    """Horizontal bar of (bytes, colour) parts over a total, rounded ends."""

    def __init__(self, parent, theme, scale, height=14):
        self.theme, self.scale = theme, scale
        self.canvas = tk.Canvas(parent, height=round(height * scale), bg=parent["bg"], highlightthickness=0)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._parts: list[tuple[float, str]] = []
        self._total = 1.0

    def update(self, parts: list[tuple[float, str]], total: float) -> None:
        self._parts, self._total = parts, max(total, 1.0)
        self._redraw()

    def _redraw(self) -> None:
        c, cv = self.theme, self.canvas
        if not cv.winfo_exists():
            return
        cv.delete("all")
        w, h = max(cv.winfo_width(), 20), max(cv.winfo_height(), 6)
        r = h / 2
        cv.create_rectangle(r, 0, w - r, h, fill=c["track"], outline="")
        cv.create_oval(0, 0, h, h, fill=c["track"], outline="")
        cv.create_oval(w - h, 0, w, h, fill=c["track"], outline="")
        used = sum(max(0.0, p) for p, _ in self._parts)
        scale = min(1.0, self._total / used) if used > self._total else 1.0  # never overflow the track
        x = 0.0
        for i, (part, colour) in enumerate(self._parts):
            width = max(0.0, part) * scale / self._total * w
            if width <= 0:
                continue
            x1 = min(w, x + width)
            if i == 0:
                cv.create_oval(0, 0, h, h, fill=colour, outline="")
                cv.create_rectangle(min(r, x1), 0, x1, h, fill=colour, outline="")
            else:
                cv.create_rectangle(x, 0, x1, h, fill=colour, outline="")
            if x1 >= w - r:
                cv.create_oval(w - h, 0, w, h, fill=colour, outline="")
            # 1 px separator between segments
            if i > 0:
                cv.create_line(x, 0, x, h, fill=c["card"])
            x = x1
