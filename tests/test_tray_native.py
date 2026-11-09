"""Native Win32 tray icon: add, click routing, icon/tooltip updates, clean removal."""

import sys
import threading
import time

import pytest

if sys.platform != "win32":
    pytest.skip("Shell_NotifyIcon is Windows-only", allow_module_level=True)

from gtm_desktop import tray  # noqa: E402


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_native_tray_lifecycle():
    clicks = []
    t = tray.Tray(on_left=lambda: clicks.append("left"), on_right=lambda: clicks.append("right"),
                  on_exit=lambda: None)
    assert t.start() is True
    icon = t._icon
    hwnd = icon._hwnd
    assert hwnd

    # Click routing: the shell sends WM_TRAY with the mouse message in lParam.
    tray._user32.PostMessageW(hwnd, tray.WM_TRAY, tray.ICON_ID, tray.WM_LBUTTONUP)
    tray._user32.PostMessageW(hwnd, tray.WM_TRAY, tray.ICON_ID, tray.WM_RBUTTONUP)
    assert _wait(lambda: clicks == ["left", "right"]), clicks

    # Icon redrawn on level/band change; tooltip truncated to the shell limit.
    first = icon._hicon
    t.update(10.0, ["VRAM 10%"])
    second = icon._hicon
    t.update(95.0, ["x" * 300])
    assert first != second != icon._hicon
    assert len(icon._tip) <= tray.TOOLTIP_MAX

    t.stop()
    assert icon._hwnd is None
    assert not any(th.name == "tray" and th.is_alive() for th in threading.enumerate())


def test_tray_restarts_in_same_process():
    # A fresh window class per icon: a second start must not reuse a dead WNDPROC.
    for _ in range(2):
        t = tray.Tray(on_left=lambda: None, on_right=lambda: None, on_exit=lambda: None)
        assert t.start() is True
        t.stop()
