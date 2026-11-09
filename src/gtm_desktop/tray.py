"""Notification-area icon: left click opens the main window, right click the quick panel.

Native Win32 through ctypes (Shell_NotifyIconW), no third-party code. A hidden
window on a dedicated "tray" thread owns the icon and runs its message loop.
Click callbacks run on that thread, so they only post work to the Tk thread
(app.post); nothing here touches Tk. Icon, tooltip and balloon updates come from
the Tk thread and go straight to Shell_NotifyIconW (thread-safe, keyed by hWnd).

The icon image is redrawn only when the shown level changes by at least STEP
percent, or the colour band or the taskbar theme changes. If Explorer restarts,
the TaskbarCreated broadcast re-adds the icon.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

from . import art, brand
from .fluent import dark_mode

log = logging.getLogger(__name__)
STEP = 3.0
TOOLTIP_MAX = 127  # NOTIFYICONDATAW.szTip
AVAILABLE = sys.platform == "win32"


def tooltip(lines: list[str]) -> str:
    text = "\n".join([brand.APP_NAME] + [line for line in lines if line])
    return text if len(text) <= TOOLTIP_MAX else text[: TOOLTIP_MAX - 1] + "…"


if AVAILABLE:
    from ctypes import wintypes as wt

    from PIL import Image

    from . import winicon
    from .winicon import win_error as _win_error

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    WM_DESTROY, WM_CLOSE = 0x0002, 0x0010
    WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
    WM_TRAY = 0x8000 + 1  # WM_APP + 1: our notify-icon callback message
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
    NIIF_INFO = 0x01
    ICON_ID = 1

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                    ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                    ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                    ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                    ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                    ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]

    def _sig(fn, restype, *argtypes):
        fn.restype, fn.argtypes = restype, list(argtypes)

    _sig(_user32.DefWindowProcW, LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    _sig(_user32.RegisterClassExW, wt.ATOM, ctypes.POINTER(WNDCLASSEXW))
    _sig(_user32.UnregisterClassW, wt.BOOL, wt.LPCWSTR, wt.HINSTANCE)
    _sig(_user32.CreateWindowExW, wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
         ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
    _sig(_user32.DestroyWindow, wt.BOOL, wt.HWND)
    _sig(_user32.PostMessageW, wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    _sig(_user32.GetMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
    _sig(_user32.TranslateMessage, wt.BOOL, ctypes.POINTER(wt.MSG))
    _sig(_user32.DispatchMessageW, LRESULT, ctypes.POINTER(wt.MSG))
    _sig(_user32.PostQuitMessage, None, ctypes.c_int)
    _sig(_user32.RegisterWindowMessageW, wt.UINT, wt.LPCWSTR)
    _sig(_user32.DestroyIcon, wt.BOOL, wt.HICON)
    _sig(_shell32.Shell_NotifyIconW, wt.BOOL, wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW))

    class NOTIFYICONIDENTIFIER(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("guidItem", GUID)]

    _sig(_shell32.Shell_NotifyIconGetRect, ctypes.c_long, ctypes.POINTER(NOTIFYICONIDENTIFIER),
         ctypes.POINTER(wt.RECT))
    _sig(_kernel32.GetModuleHandleW, wt.HMODULE, wt.LPCWSTR)

    _hicon = winicon.hicon

    class _NotifyIcon:
        """One Shell_NotifyIcon entry owned by a hidden window on its own thread."""

        def __init__(self, on_left: Callable[[], None], on_right: Callable[[], None]) -> None:
            self._on_left, self._on_right = on_left, on_right
            self._hwnd = None
            self._hicon = None
            self._tip = brand.APP_NAME
            self._lock = threading.Lock()
            self._ready = threading.Event()
            self._error: str = ""
            self._class = f"{brand.APP_SLUG}TrayWindow{id(self):x}"  # unique: a class outlives its WNDPROC
            self._wndproc = WNDPROC(self._proc)  # keep a reference for the window's lifetime
            self._taskbar_created = 0
            self._thread: threading.Thread | None = None

        # ---- lifecycle (start/stop from the Tk thread)
        def start(self, image: "Image.Image", timeout: float = 5.0) -> bool:
            self._hicon = _hicon(image)
            self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                self._error = "tray thread did not start in time"
            if self._error:
                log.warning("tray icon unavailable: %s", self._error)
                with self._lock:
                    if self._hicon and not self._hwnd:
                        _user32.DestroyIcon(self._hicon)
                        self._hicon = None
                return False
            return True

        def stop(self) -> None:
            hwnd = self._hwnd
            if hwnd:
                _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)

        # ---- updates (any thread)
        def set_image(self, image: "Image.Image") -> None:
            new = _hicon(image)
            with self._lock:
                old, self._hicon = self._hicon, new
                if self._hwnd:
                    self._shell(NIM_MODIFY, NIF_ICON)
            if old:
                _user32.DestroyIcon(old)

        def set_tip(self, text: str) -> None:
            with self._lock:
                if text == self._tip:
                    return
                self._tip = text[:TOOLTIP_MAX]
                if self._hwnd:
                    self._shell(NIM_MODIFY, NIF_TIP)

        def notify(self, title: str, message: str) -> None:
            with self._lock:
                if not self._hwnd:
                    return
                nid = self._nid(NIF_INFO)
                nid.szInfo = message[:255]
                nid.szInfoTitle = title[:63]
                nid.dwInfoFlags = NIIF_INFO
                if not _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)):
                    raise _win_error("Shell_NotifyIconW(balloon)")

        def rect(self) -> tuple[int, int, int, int] | None:
            """Screen rectangle of the icon (None when hidden in the overflow area or unknown)."""
            hwnd = self._hwnd
            if not hwnd:
                return None
            ident = NOTIFYICONIDENTIFIER(cbSize=ctypes.sizeof(NOTIFYICONIDENTIFIER), hWnd=hwnd, uID=ICON_ID)
            r = wt.RECT()
            if _shell32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(r)) != 0:  # S_OK == 0
                return None
            if r.right <= r.left or r.bottom <= r.top:
                return None
            return r.left, r.top, r.right, r.bottom

        # ---- internals
        def _nid(self, flags: int) -> "NOTIFYICONDATAW":
            nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self._hwnd, uID=ICON_ID,
                                  uFlags=flags, uCallbackMessage=WM_TRAY, hIcon=self._hicon)
            nid.szTip = self._tip
            return nid

        def _shell(self, message: int, flags: int) -> bool:
            ok = bool(_shell32.Shell_NotifyIconW(message, ctypes.byref(self._nid(flags))))
            if not ok and message != NIM_DELETE:
                log.debug("Shell_NotifyIconW(%d) failed: winerror %d", message, ctypes.get_last_error())
            return ok

        def _add(self) -> bool:
            with self._lock:
                return self._shell(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)

        def _run(self) -> None:
            hinst = _kernel32.GetModuleHandleW(None)
            try:
                wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=hinst,
                                 lpszClassName=self._class)
                if not _user32.RegisterClassExW(ctypes.byref(wc)):
                    raise _win_error("RegisterClassExW")
                # A normal (hidden) top-level window, not message-only: those miss the TaskbarCreated broadcast.
                hwnd = _user32.CreateWindowExW(0, self._class, brand.APP_NAME, 0, 0, 0, 0, 0, None, None, hinst,
                                               None)
                if not hwnd:
                    raise _win_error("CreateWindowExW")
                self._hwnd = hwnd
                self._taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")
                if not self._add():
                    raise _win_error("Shell_NotifyIconW(add)")
            except OSError as exc:
                self._error = str(exc)
                if self._hwnd:
                    _user32.DestroyWindow(self._hwnd)
                    self._hwnd = None
                _user32.UnregisterClassW(self._class, hinst)
                self._ready.set()
                return
            self._ready.set()

            msg = wt.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            _user32.UnregisterClassW(self._class, hinst)
            with self._lock:
                if self._hicon:
                    _user32.DestroyIcon(self._hicon)
                    self._hicon = None

        def _proc(self, hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAY:
                    event = lparam & 0xFFFF
                    if event == WM_LBUTTONUP:
                        self._on_left()
                    elif event == WM_RBUTTONUP:
                        self._on_right()
                    return 0
                if self._taskbar_created and msg == self._taskbar_created:  # Explorer restarted
                    self._add()
                    return 0
                if msg == WM_CLOSE:
                    _user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    with self._lock:
                        self._shell(NIM_DELETE, 0)
                        self._hwnd = None
                    _user32.PostQuitMessage(0)
                    return 0
            except Exception:  # noqa: BLE001 - an exception must never cross the Win32 boundary
                log.exception("tray window procedure failed (msg 0x%04x)", msg)
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class Tray:
    def __init__(self, on_left: Callable[[], None], on_right: Callable[[], None],
                 on_exit: Callable[[], None]) -> None:
        self._on_left, self._on_right, self._on_exit = on_left, on_right, on_exit
        self._icon = None
        self._shown: tuple | None = None

    def start(self) -> bool:
        if not AVAILABLE:
            log.warning("no tray icon on %s: running without one", sys.platform)
            return False
        icon = _NotifyIcon(self._on_left, self._on_right)
        try:
            ok = icon.start(art.tray_icon(None, dark_mode("system")))
        except OSError:
            log.exception("tray icon could not be created")
            return False
        self._icon = icon if ok else None
        return ok

    def update(self, pct: float | None, tip_lines: list[str]) -> None:
        if self._icon is None:
            return
        dark = dark_mode("system")
        band = art.level_rgb(pct)
        level = None if pct is None else round(pct / STEP)
        key = (level, band, dark)
        if key != self._shown:
            self._shown = key
            try:
                self._icon.set_image(art.tray_icon(pct, dark))
            except Exception:  # noqa: BLE001
                log.exception("tray icon update failed")
        try:
            self._icon.set_tip(tooltip(tip_lines))
        except Exception:  # noqa: BLE001
            log.debug("tray tooltip update failed", exc_info=True)

    def icon_rect(self) -> tuple[int, int, int, int] | None:
        if self._icon is None:
            return None
        try:
            return self._icon.rect()
        except Exception:  # noqa: BLE001
            log.debug("tray icon rect unavailable", exc_info=True)
            return None

    def notify(self, title: str, message: str) -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(title, message)
        except Exception:  # noqa: BLE001
            log.exception("tray notification failed")

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                log.debug("tray stop failed", exc_info=True)
            self._icon = None
