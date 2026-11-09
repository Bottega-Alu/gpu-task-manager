"""The real UI with demo data: build, switch theme and language live, page through, exit.

Needs a display (Windows desktop, or Xvfb on Linux); skipped otherwise.
"""

import os
import sys
import time

import pytest

tk = pytest.importorskip("tkinter")
if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    pytest.skip("no display", allow_module_level=True)


def test_ui_lifecycle(monkeypatch, tmp_path):
    from gtm_desktop import autostart, settings as settings_mod
    from gtm_desktop.app import App
    from gtm_desktop.demo import DemoSampler

    monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    app = App(start_in_tray=True, sampler_factory=DemoSampler)
    seen = {}

    def script():
        app.flyout.show()
        app.root.update()
        seen["flyout"] = app.flyout.visible
        # Short screen, taskbar not reserved in the work area: the panel must stay above the icon and on screen.
        from gtm_desktop import flyout as flyout_mod
        monkeypatch.setattr(flyout_mod, "work_area", lambda: (0, 0, 1600, 640))
        monkeypatch.setattr(app.tray, "icon_rect", lambda: (1500, 600, 1530, 630))
        app.flyout.hide()
        app.flyout.show()
        app.root.update()
        top = app.flyout.top
        y, h = top.winfo_y(), top.winfo_height()
        seen["flyout_fits"] = y >= 0 and y + h <= 600
        print("flyout y/h:", y, h, "rows:", app.flyout.max_rows)
        monkeypatch.undo()
        monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "settings.json")
        monkeypatch.setattr(autostart, "is_enabled", lambda: False)
        app.open_window("overview")
        w = app.window
        w.top.geometry("760x700")  # narrow: the VRAM legend must wrap, not run past the card
        for _i in range(20):
            app.root.update()
            time.sleep(0.05)
        width = w.ov_legend.winfo_width()
        shown = [chip for chip, _d, _t in w._legend_pool[:w._legend_count]]
        seen["legend_fits"] = bool(shown) and all(ch.winfo_x() + ch.winfo_width() <= width for ch in shown)
        print("legend rows:", len({ch.winfo_y() for ch in shown}), "width:", width)
        for page in ("overview", "processes", "history", "settings", "about"):
            app.open_window(page)
            app.root.update()
        app.update_setting("theme", "dark")
        from gtm_desktop.i18n import LANGUAGES
        for code in LANGUAGES[1:]:  # every language rebuilds every surface without error
            app.update_setting("language", code)
            app.root.update()
        app.update_setting("language", "it")
        app.root.update()
        seen["page_after_rebuild"] = app.window.page
        seen["title"] = app.window.nav["settings"][3]["text"]
        seen["frame"] = app.frame is not None
        app.exit()

    app.root.after(1500, script)
    app.run()
    assert seen == {"flyout": True, "flyout_fits": True, "legend_fits": True, "page_after_rebuild": "about", "title": "Impostazioni", "frame": True}
    assert (tmp_path / "settings.json").exists()
