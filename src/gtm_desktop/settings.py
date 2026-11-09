"""User settings in %APPDATA%\\<APP_NAME>\\settings.json.

Unknown keys are kept, invalid values fall back to defaults, and writes are
atomic (temp file + replace) so a crash mid-write never leaves a broken file.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import brand
from .i18n import LANGUAGES

INTERVALS = (0.5, 1.0, 2.0, 5.0)
VRAM_ALERTS = (0, 80, 85, 90, 95)   # percent; 0 = off
TEMP_ALERTS = (0, 75, 80, 85, 90)   # Celsius; 0 = off
TRAY_METRICS = ("vram", "gpu")


@dataclass
class Settings:
    interval: float = 1.0
    gpu_index: int = 0
    theme: str = "system"          # system | light | dark
    language: str = "system"       # system | it | en | pt-BR | fr | es | de | uk
    tray_metric: str = "vram"      # vram | gpu
    alert_vram_pct: int = 90
    alert_temp_c: int = 85
    window_geometry: str = ""

    def normalized(self) -> "Settings":
        d = Settings()
        if self.interval not in INTERVALS:
            self.interval = d.interval
        if not isinstance(self.gpu_index, int) or self.gpu_index < 0:
            self.gpu_index = d.gpu_index
        if self.theme not in ("system", "light", "dark"):
            self.theme = d.theme
        if self.language not in LANGUAGES:
            self.language = d.language
        if self.tray_metric not in TRAY_METRICS:
            self.tray_metric = d.tray_metric
        if self.alert_vram_pct not in VRAM_ALERTS:
            self.alert_vram_pct = d.alert_vram_pct
        if self.alert_temp_c not in TEMP_ALERTS:
            self.alert_temp_c = d.alert_temp_c
        if not isinstance(self.window_geometry, str):
            self.window_geometry = ""
        return self


def data_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    root = Path(base) if base else Path.home() / ".config"
    return root / brand.DATA_DIR_NAME


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    known = {f.name: f for f in fields(Settings)}
    values = {}
    for key, value in raw.items():
        f = known.get(key)
        if f is None:
            continue
        default = getattr(Settings(), key)
        if isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
            values[key] = float(value)
        elif type(value) is type(default):
            values[key] = value
    return Settings(**values).normalized()


def save(s: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (OSError, ValueError):
        existing = {}
    existing.update(asdict(s.normalized()))
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
