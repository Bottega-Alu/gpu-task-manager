"""Application orchestration: Tk on the main thread, sampler and tray on their own threads.

Threads and what they may touch:
  main (Tk)    every widget, settings, history, alerts
  gpu-sampler  the gputaskman Collector only; hands over immutable Frames
  tray         native Shell_NotifyIcon window and message loop; its callbacks only call post()
  show-requests  waits for a second launch; only calls post()

Cross-thread traffic goes through one queue drained every PUMP_MS on the Tk
thread, so no Tk call ever happens off the main thread.
"""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from . import brand, fluent, settings as settings_mod
from .i18n import set_language
from .model import AlertTracker, Frame, History, device_load, fmt_bytes, fmt_pct, fmt_temp
from .sampler import AdapterList, Sampler, SamplerError
from .tray import Tray

log = logging.getLogger(__name__)
PUMP_MS = 100
THEME_POLL_MS = 3000


class App:
    def __init__(self, start_in_tray: bool = True, sampler_factory=None) -> None:
        self.settings = settings_mod.load()
        set_language(self.settings.language)
        fluent.set_theme(self.settings.theme)
        fluent.enable_dpi_awareness()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(brand.APP_NAME)
        self.icon_path = self._find_icon()
        self.scale = fluent.ui_scale(self.root)
        self._queue: queue.Queue = queue.Queue()
        self.frame: Frame | None = None
        self.error: str = ""
        self.adapters: tuple[str, ...] = ()
        self.paused = False
        self.history = History(maxlen=300)
        self.alerts = AlertTracker()
        self._start_in_tray = start_in_tray
        self._closing = False

        self.window = None
        self.flyout = None
        self._apply_theme()

        make = sampler_factory or Sampler  # previews and tests pass a fake that publishes demo frames
        self.sampler = make(self._queue.put, self.settings.interval, self.settings.gpu_index)
        self.tray = Tray(on_left=lambda: self.post(lambda: self.open_window()),
                         on_right=lambda: self.post(self.toggle_flyout),
                         on_exit=lambda: self.post(self.exit))

    # ------------------------------------------------------------ setup
    @staticmethod
    def _find_icon() -> Path | None:
        here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else \
            Path(__file__).resolve().parents[2]
        for candidate in (here / "assets" / "app.ico", here / "_internal" / "assets" / "app.ico"):
            if candidate.exists():
                return candidate
        return None

    def _apply_theme(self) -> None:
        self.dark = fluent.dark_mode("apps")
        self.theme = fluent.colors(self.dark)
        family = fluent.text_font(self.root)
        icons = fluent.icon_font(self.root) or family
        mono = "Cascadia Mono" if "Cascadia Mono" in set(tkfont.families(self.root)) else "Consolas"
        self.fonts = {
            "display": (family, 20, "bold"), "title": (family, 14, "bold"), "metric": (family, 15, "bold"),
            "body": (family, 10), "body_b": (family, 10, "bold"), "small": (family, 9),
            "small_b": (family, 9, "bold"), "mono": (mono, 9),
            "icon_s": (icons, 11), "icon_m": (icons, 13), "icon_l": (icons, 20),
        }
        self.root.configure(bg=self.theme["surface"])

    def _build_ui(self, reopen_page: str | None = None) -> None:
        from .flyout import Flyout
        from .window import MainWindow
        self.window = MainWindow(self)
        self.flyout = Flyout(self)
        if reopen_page:
            self.window.show(reopen_page)

    def rebuild_ui(self) -> None:
        """Theme or language changed: rebuild every surface with the new look and strings."""
        page = self.window.page if self.window and self.window.visible else None
        if self.window:
            self.window.destroy()
        if self.flyout:
            self.flyout.destroy()
        self._apply_theme()
        self._build_ui(page)

    # ------------------------------------------------------------ threads -> Tk
    def post(self, fn) -> None:
        self._queue.put(fn)

    def _pump(self) -> None:
        latest = None
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, Frame):
                    self.history.add(item)  # every sample counts for the charts...
                    latest = item  # ...but only the newest is drawn
                elif isinstance(item, SamplerError):
                    self.error = item.message
                    if self.frame is None:
                        self._refresh_surfaces()
                elif isinstance(item, AdapterList):
                    self.adapters = item.names
                    if item.selected != self.settings.gpu_index:
                        self.settings.gpu_index = item.selected
                elif callable(item):
                    try:
                        item()
                    except Exception:  # noqa: BLE001
                        log.exception("posted action failed")
        except queue.Empty:
            pass
        if latest is not None:
            self._on_frame(latest)
        if not self._closing:
            self.root.after(PUMP_MS, self._pump)

    def _on_frame(self, frame: Frame) -> None:
        self.frame, self.error = frame, ""
        d = frame.device
        load = device_load(frame)
        metric = load if self.settings.tray_metric == "gpu" else d.vram_pct
        self.tray.update(metric, [
            f"{d.name}",
            f"VRAM {fmt_bytes(d.vram_used)} / {fmt_bytes(d.vram_total)} ({fmt_pct(d.vram_pct)})",
            f"GPU {fmt_pct(load)}   {fmt_temp(d.temp)}",
        ])
        for alert in self.alerts.update(frame, self.settings.alert_vram_pct, self.settings.alert_temp_c):
            self.tray.notify(alert.title, alert.message)
        self._refresh_surfaces()

    def _refresh_surfaces(self) -> None:
        if self.window and self.window.visible:
            self.window.render(self.frame)
        if self.flyout and self.flyout.visible:
            self.flyout.render(self.frame)

    def _watch_theme(self) -> None:
        if self._closing:
            return
        if self.settings.theme == "system" and fluent.dark_mode("apps") != self.dark:
            self.rebuild_ui()
        self.root.after(THEME_POLL_MS, self._watch_theme)

    # ------------------------------------------------------------ actions (Tk thread)
    def toggle_flyout(self) -> None:
        if self.window and self.window.visible and self.flyout.visible:
            self.flyout.hide()
            return
        self.flyout.toggle()

    def open_window(self, page: str | None = None) -> None:
        if self.flyout:
            self.flyout.hide()
        self.window.show(page)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.sampler.set_paused(self.paused)
        self._refresh_surfaces()

    def update_setting(self, key: str, value) -> None:
        setattr(self.settings, key, value)
        self.settings.normalized()
        settings_mod.save(self.settings)
        if key == "interval":
            self.sampler.set_interval(self.settings.interval)
        elif key == "theme":
            fluent.set_theme(self.settings.theme)
            self.rebuild_ui()
        elif key == "language":
            set_language(self.settings.language)
            self.rebuild_ui()
        elif key == "tray_metric" and self.frame:
            self._on_frame(self.frame)

    def remember_geometry(self, geometry: str) -> None:
        if geometry and geometry != self.settings.window_geometry and not geometry.startswith("1x1"):
            self.settings.window_geometry = geometry
            try:
                settings_mod.save(self.settings)
            except OSError:
                log.exception("could not save window geometry")

    def exit(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self.window:
            self.window.destroy()
        self.tray.stop()
        self.sampler.stop()
        self.root.after(50, self.root.destroy)

    # ------------------------------------------------------------ run
    def run(self) -> None:
        from . import single_instance
        self._build_ui()
        has_tray = self.tray.start()
        self.sampler.start()
        single_instance.watch_show_requests(lambda: self.post(lambda: self.open_window()))
        self.root.after(PUMP_MS, self._pump)
        self.root.after(THEME_POLL_MS, self._watch_theme)
        if not self._start_in_tray or not has_tray:
            self.root.after(200, lambda: self.open_window("overview"))
        try:
            self.root.mainloop()
        finally:
            self._closing = True
            self.tray.stop()
            self.sampler.stop()
