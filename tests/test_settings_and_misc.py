"""Settings persistence, autostart command, tray tooltip, icon art."""

import json

from gtm_desktop import art, autostart, brand, settings
from gtm_desktop.tray import TOOLTIP_MAX, tooltip


def test_settings_roundtrip_keeps_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"future_option": 1, "theme": "dark"}))
    s = settings.load(path)
    assert s.theme == "dark"
    s.interval = 2.0
    settings.save(s, path)
    raw = json.loads(path.read_text())
    assert raw["future_option"] == 1 and raw["interval"] == 2.0 and raw["theme"] == "dark"


def test_settings_invalid_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"interval": 7, "theme": "neon", "gpu_index": -3, "alert_vram_pct": "x",
                                "language": "xx", "tray_metric": "temp"}))
    s = settings.load(path)
    d = settings.Settings()
    assert (s.interval, s.theme, s.gpu_index, s.alert_vram_pct, s.language, s.tray_metric) == \
        (d.interval, d.theme, d.gpu_index, d.alert_vram_pct, d.language, d.tray_metric)


def test_settings_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert settings.load(path) == settings.Settings()


def test_autostart_command_quotes_path():
    assert autostart.command(r"C:\Program Files\X\GPUTaskManager.exe") == \
        '"C:\\Program Files\\X\\GPUTaskManager.exe" --tray'


def test_tooltip_fits_windows_limit():
    text = tooltip(["x" * 200, "y"])
    assert len(text) <= TOOLTIP_MAX and text.startswith(brand.APP_NAME)


def test_tray_icon_levels():
    assert art.level_rgb(50) == art.NORMAL_RGB
    assert art.level_rgb(85) == art.WARN_RGB
    assert art.level_rgb(99) == art.CRIT_RGB
    for pct in (None, 0, 50, 100, 140):
        img = art.tray_icon(pct, dark_taskbar=True)
        assert img.size == (64, 64) and img.mode == "RGBA"
    assert len(art.app_icon_images()) >= 8


def test_brand_is_single_source():
    assert brand.EXE_NAME == brand.APP_SLUG + ".exe"
    assert " " not in brand.APP_SLUG
    assert brand.APP_GUID.startswith("{") and brand.APP_GUID.endswith("}")


def test_version_matches_pyproject():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == brand.APP_VERSION


def test_engine_is_untouched_copy_with_licence():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert "MIT License" in (root / "licenses" / "gputaskman-LICENSE.txt").read_text(encoding="utf-8")
    assert "Commit: `" in (root / "UPSTREAM.md").read_text(encoding="utf-8")


def test_every_ui_string_has_an_italian_translation():
    import ast
    from pathlib import Path
    from gtm_desktop import i18n
    pkg = Path(__file__).resolve().parents[1] / "src" / "gtm_desktop"
    missing = set()
    for py in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                if node.args[0].value not in i18n._IT:
                    missing.add(node.args[0].value)
    assert not missing, sorted(missing)


def _fields(text):
    import string
    return sorted(n for _l, n, _f, _c in string.Formatter().parse(text) if n is not None)


def test_every_language_table_matches_italian_keys_and_placeholders():
    from gtm_desktop import i18n
    codes = [c for c in i18n.LANGUAGES if c not in ("system", "en")]
    assert set(codes) == set(i18n._TABLES) and set(codes) == set(i18n.LANGUAGE_NAMES) - {"en"}
    problems = []
    for code in codes:
        table = i18n._TABLES[code]
        problems += [f"{code}: missing {k!r}" for k in i18n._IT if k not in table]
        problems += [f"{code}: extra {k!r}" for k in table if k not in i18n._IT]
        for k, v in table.items():
            if k in i18n._IT and _fields(k) != _fields(v):
                problems.append(f"{code}: placeholders differ for {k!r}")
            if k in i18n._IT and not v.strip():
                problems.append(f"{code}: empty {k!r}")
    assert not problems, problems


def test_system_language_mapping():
    from gtm_desktop.i18n import _code_to_language as m
    assert [m(c) for c in ("pt_BR", "pt_PT", "fr_CA", "es_MX", "de_AT", "uk_UA", "ru_RU", "it_IT")] == \
        ["pt-BR", "pt-BR", "fr", "es", "de", "uk", "uk", "it"]
    assert [m(c) for c in ("German_Germany", "Ukrainian_Ukraine", "ja_JP", "en_US", "")] == ["de", "uk", "en", "en", "en"]
    assert m("pl_PL") == "en"
