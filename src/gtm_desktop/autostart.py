"""Start at sign-in through the per-user Run key (HKCU, no admin, no UAC).

A monitor needs no restart-on-failure or delayed trigger, so the Run key is
enough: Windows starts "<exe>" --tray in the user's session, where the tray and
the GPU counters live. The installer writes and the uninstaller removes the
same value (installer/GPUTaskManager.iss, [Registry] with uninsdeletevalue).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import brand

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command(exe: str | Path | None = None) -> str:
    exe = Path(exe or sys.executable)
    return f'"{exe}" --tray'


def _winreg():
    import winreg  # Windows only; imported lazily so tests run anywhere
    return winreg


def is_enabled() -> bool:
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, brand.RUN_VALUE_NAME)
        return bool(value)
    except (ImportError, OSError):
        return False


def enable(exe: str | Path | None = None) -> None:
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, brand.RUN_VALUE_NAME, 0, winreg.REG_SZ, command(exe))


def disable() -> None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, brand.RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


def set_enabled(on: bool) -> None:
    enable() if on else disable()
