"""Regenerate assets/app.ico (multi-size) and a tray preview sheet.

    python scripts/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from gtm_desktop import art  # noqa: E402


def main() -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    images = art.app_icon_images()
    images[-1].save(assets / "app.ico", sizes=[(i.width, i.height) for i in images], append_images=images[:-1])
    images[-1].save(assets / "app-256.png")

    # Preview: tray icon at 16/24/32 px for several levels, on dark and light taskbars.
    levels = (None, 5, 35, 65, 85, 97)
    cell = 40
    sheet = Image.new("RGBA", (cell * len(levels), cell * 6), (0, 0, 0, 0))
    for row, (dark, size) in enumerate([(d, s) for d in (True, False) for s in (16, 24, 32)]):
        bg = (32, 32, 32, 255) if dark else (243, 243, 243, 255)
        for col, pct in enumerate(levels):
            tile = Image.new("RGBA", (cell, cell), bg)
            icon = art.tray_icon(pct, dark, size=64).resize((size, size), Image.Resampling.LANCZOS)
            tile.alpha_composite(icon, ((cell - size) // 2, (cell - size) // 2))
            sheet.paste(tile, (col * cell, row * cell))
    sheet.save(assets / "tray-preview.png")
    print("written:", assets / "app.ico", assets / "tray-preview.png")


if __name__ == "__main__":
    main()
