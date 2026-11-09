"""One instance per Windows session; a second launch brings the first one forward.

Decision tree (claim):
  1. CreateMutexW(MUTEX_NAME) says it already existed
       -> another instance runs: signal SHOW_EVENT_NAME and exit
  2. otherwise we own the mutex for the process lifetime (the OS releases it
     on exit or crash, so there is never a stale lock), and a watcher thread
     waits on SHOW_EVENT_NAME to open the main window on request.
Non-Windows platforms (tests, development) always run.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

from . import brand

log = logging.getLogger(__name__)
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

_handles: list = []  # kept alive for the whole process


def _kernel32():
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def claim() -> bool:
    """True when this process is the instance. False: another one was asked to show itself."""
    if sys.platform != "win32":
        return True
    k = _kernel32()
    handle = k.CreateMutexW(None, False, brand.MUTEX_NAME)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if not handle:
        log.warning("CreateMutexW failed; running without the single-instance guard")
        return True
    if already:
        k.CloseHandle(handle)
        event = k.CreateEventW(None, False, False, brand.SHOW_EVENT_NAME)
        if event:
            k.SetEvent(event)
            k.CloseHandle(event)
        return False
    _handles.append(handle)
    return True


def watch_show_requests(on_show: Callable[[], None]) -> None:
    """Call on_show (from a daemon thread) whenever a second launch asks for the window."""
    if sys.platform != "win32":
        return
    k = _kernel32()
    event = k.CreateEventW(None, False, False, brand.SHOW_EVENT_NAME)  # auto-reset
    if not event:
        log.warning("CreateEventW failed; a second launch will not raise the window")
        return
    _handles.append(event)

    def loop():
        while True:
            if k.WaitForSingleObject(event, INFINITE) == WAIT_OBJECT_0:
                try:
                    on_show()
                except Exception:
                    log.exception("show request failed")
            else:
                return

    threading.Thread(target=loop, name="show-requests", daemon=True).start()
