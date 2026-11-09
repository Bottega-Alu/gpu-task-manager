"""Windows 11 look shared by the quick panel and the main window.

Theme follows Windows unless chosen in the app (set_theme); accent comes from
the Windows accent palette; glyphs from the system icon font (Segoe Fluent
Icons on Windows 11, Segoe MDL2 Assets on Windows 10). Widgets are plain Tk,
created and touched only on the Tk (main) thread.
"""

from __future__ import annotations

import sys

ICON = {
    "chip": "", "home": "", "list": "", "chart": "", "settings": "",
    "info": "", "power": "", "open": "", "pause": "", "play": "",
    "temp": "", "bolt": "", "memory": "", "save": "", "copy": "",
    "folder": "", "close": "", "warning": "", "speed": "", "fan": "",
}

THEMES = ("system", "light", "dark")
_theme = "system"


def set_theme(choice: str) -> None:
    global _theme
    _theme = choice if choice in THEMES else "system"


def dark_mode(surface: str = "apps") -> bool:
    """Chosen theme, else Windows' app mode (windows) or system mode (tray surfaces)."""
    if _theme != "system":
        return _theme == "dark"
    if sys.platform != "win32":
        return False
    value = "SystemUsesLightTheme" if surface == "system" else "AppsUseLightTheme"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, value)[0] == 0
    except OSError:
        return False


def accent(dark: bool) -> str:
    """System accent as Windows 11 uses it: Light2 on dark, Dark1 on light."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as key:
                palette = winreg.QueryValueEx(key, "AccentPalette")[0]
            i = (1 if dark else 4) * 4
            r, g, b = palette[i:i + 3]
            return f"#{r:02x}{g:02x}{b:02x}"
        except (OSError, ValueError, TypeError):
            pass
    return "#4cc2ff" if dark else "#005fb8"


def colors(dark: bool) -> dict[str, str]:
    base = ({"surface": "#202020", "raised": "#2d2d2d", "hover": "#383838", "card": "#2b2b2b",
             "sidebar": "#1c1c1c", "text": "#ffffff", "muted": "#c5c5c5", "subtle": "#9a9a9a",
             "line": "#3d3d3d", "on": "#000000", "ok": "#6ccb5f", "warn": "#fce100", "crit": "#ff99a4",
             "track": "#3a3a3a", "series2": "#c8a2ff", "series3": "#ffb86b", "series4": "#7ee0c3",
             "unattributed": "#5f5f5f"}
            if dark else
            {"surface": "#f3f3f3", "raised": "#fbfbfb", "hover": "#eaeaea", "card": "#fbfbfb",
             "sidebar": "#ebebeb", "text": "#1a1a1a", "muted": "#5c5c5c", "subtle": "#8a8a8a",
             "line": "#e0e0e0", "on": "#ffffff", "ok": "#0f7b0f", "warn": "#9d5d00", "crit": "#c42b1c",
             "track": "#e5e5e5", "series2": "#7a4fd1", "series3": "#c25e00", "series4": "#00806a",
             "unattributed": "#c4c4c4"})
    base["accent"] = accent(dark)
    return base


def level_color(c: dict, pct: float | None, warn: float = 80, crit: float = 92) -> str:
    if pct is None:
        return c["subtle"]
    return c["crit"] if pct >= crit else c["warn"] if pct >= warn else c["accent"]


def icon_font(root) -> str | None:
    import tkinter.font as tkfont
    families = set(tkfont.families(root))
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return None


def text_font(root) -> str:
    import tkinter.font as tkfont
    families = set(tkfont.families(root))
    for name in ("Segoe UI Variable Text", "Segoe UI", "DejaVu Sans"):
        if name in families:
            return name
    return "TkDefaultFont"


def enable_dpi_awareness() -> None:
    """System DPI awareness before Tk starts, so text is sharp instead of bitmap-stretched."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def ui_scale(root) -> float:
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:  # noqa: BLE001
        return 1.0


def rounded(root, width, height, radius, fill, outline=None, background=None):
    """Antialiased rounded rectangle as a PhotoImage (Tk has no native one)."""
    from PIL import Image, ImageDraw, ImageTk
    k = 3
    width, height = max(2, int(width)), max(2, int(height))
    image = Image.new("RGBA", (width * k, height * k), background or (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, width * k - 1, height * k - 1), radius=radius * k, fill=fill,
        outline=outline or fill, width=k)
    return ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=root)


def window_handle(window) -> int:
    import ctypes
    window.update_idletasks()
    parent = ctypes.windll.user32.GetParent(window.winfo_id())
    return parent or window.winfo_id()


def style_window(window, dark: bool, rounded_corners: bool = True) -> None:
    """Dark/light native title bar and Windows 11 rounded corners (no-ops where unsupported)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = window_handle(window)
        dwm = ctypes.WinDLL("dwmapi")
        value = ctypes.c_int(int(dark))
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))  # IMMERSIVE_DARK_MODE
        if rounded_corners:
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        user = ctypes.WinDLL("user32")
        user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_uint]
        user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    except (AttributeError, OSError):
        pass


def work_area() -> tuple[int, int, int, int] | None:
    """Desktop rectangle without the taskbar (primary monitor), in pixels."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    return None


class Switch:
    """Windows 11 toggle switch; keyboard and mouse accessible."""

    def __init__(self, parent, theme, scale, command, value=False):
        import tkinter as tk
        self.theme, self.scale, self.command, self.value = theme, scale, command, value
        self.canvas = tk.Canvas(parent, width=self._p(44), height=self._p(24), bg=parent["bg"],
                                highlightthickness=0, takefocus=1, cursor="hand2")
        for seq in ("<Button-1>", "<space>", "<Return>"):
            self.canvas.bind(seq, lambda e: self.toggle())
        self.canvas.bind("<FocusIn>", lambda e: self.draw())
        self.canvas.bind("<FocusOut>", lambda e: self.draw())
        self.draw()

    def _p(self, v):
        return round(v * self.scale)

    def set(self, value):
        if value != self.value:
            self.value = value
            self.draw()

    def toggle(self):
        self.set(not self.value)
        self.command(self.value)

    def draw(self):
        c, canvas = self.theme, self.canvas
        canvas.delete("all")
        w, h = self._p(44), self._p(22)
        fill = c["accent"] if self.value else canvas["bg"]
        outline = c["accent"] if self.value else c["muted"]
        self._image = rounded(canvas, w - 2, h - 2, (h - 2) // 2, fill, outline)
        canvas.create_image(1, 2, image=self._image, anchor="nw")
        knob = self._p(6 if self.value else 5)
        x = w - h // 2 - 1 if self.value else h // 2 + 1
        y = h // 2 + 2
        canvas.create_oval(x - knob, y - knob, x + knob, y + knob,
                           fill=c["on"] if self.value else c["muted"], outline="")
        if canvas.focus_get() is canvas:
            canvas.create_rectangle(0, 0, w + 1, self._p(24) - 1, outline=c["text"], dash=(1, 2))


class ScrollFrame:
    """Vertically scrolling container: put children in .inner. Wheel scrolls while the pointer is over it."""

    def __init__(self, parent, theme):
        import tkinter as tk
        self.outer = tk.Frame(parent, bg=parent["bg"])
        self.canvas = tk.Canvas(self.outer, bg=parent["bg"], highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=parent["bg"])
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.outer.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.outer.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")


class Choice:
    """Row of pill buttons, one selected (a compact segmented control)."""

    def __init__(self, parent, theme, font, options, value, command):
        import tkinter as tk
        self.theme, self.command, self.value = theme, command, value
        self.frame = tk.Frame(parent, bg=parent["bg"])
        self.buttons = {}
        for key, label in options:
            b = tk.Label(self.frame, text=label, font=font, padx=12, pady=5, cursor="hand2", takefocus=1)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, k=key: self.select(k))
            b.bind("<space>", lambda e, k=key: self.select(k))
            self.buttons[key] = b
        self.draw()

    def select(self, key):
        if key != self.value:
            self.value = key
            self.draw()
            self.command(key)

    def draw(self):
        c = self.theme
        for key, b in self.buttons.items():
            on = key == self.value
            b.configure(bg=c["accent"] if on else c["raised"], fg=c["on"] if on else c["text"],
                        highlightthickness=1, highlightbackground=c["accent"] if on else c["line"])
