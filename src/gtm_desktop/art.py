"""Pillow drawings: the live tray icon and the application icon.

The tray icon is a GPU chip whose core fills bottom-up with the chosen metric
(VRAM in use, or GPU load). Colour carries the level: accent below WARN,
amber from WARN, red from CRIT. Drawn at 4x and downsampled for clean edges.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

WARN, CRIT = 80.0, 92.0
NORMAL_RGB = (76, 194, 255)
WARN_RGB = (252, 185, 0)
CRIT_RGB = (232, 64, 64)


def level_rgb(pct: float | None) -> tuple[int, int, int]:
    if pct is None:
        return (150, 150, 150)
    return CRIT_RGB if pct >= CRIT else WARN_RGB if pct >= WARN else NORMAL_RGB


def chip(pct: float | None, size: int = 64, dark_taskbar: bool = True, pins: bool = True,
         rgb: tuple[int, int, int] | None = None) -> Image.Image:
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    frame = (235, 235, 235, 255) if dark_taskbar else (40, 40, 40, 255)
    fill_rgb = rgb or level_rgb(pct)

    pad = round(s * (0.14 if pins else 0.04))
    body = (pad, pad, s - pad - 1, s - pad - 1)
    stroke = max(k, round(s * 0.075))
    radius = round(s * 0.16)

    if pins:
        pin_w, pin_len = max(k, round(s * 0.06)), pad - k
        for i in range(3):
            c = pad + round((s - 2 * pad) * (i + 1) / 4)
            for box in ((c - pin_w // 2, 0, c + pin_w // 2, pin_len),
                        (c - pin_w // 2, s - pin_len, c + pin_w // 2, s),
                        (0, c - pin_w // 2, pin_len, c + pin_w // 2),
                        (s - pin_len, c - pin_w // 2, s, c + pin_w // 2)):
                d.rounded_rectangle(box, radius=pin_w // 2, fill=frame)

    d.rounded_rectangle(body, radius=radius, outline=frame, width=stroke)

    inner_pad = stroke + max(k, round(s * 0.04))
    inner = (body[0] + inner_pad, body[1] + inner_pad, body[2] - inner_pad, body[3] - inner_pad)
    inner_r = max(k, radius - inner_pad // 2)
    track = (255, 255, 255, 40) if dark_taskbar else (0, 0, 0, 30)
    d.rounded_rectangle(inner, radius=inner_r, fill=track)

    if pct is not None and pct > 0:
        level = max(0.0, min(100.0, pct)) / 100.0
        height = inner[3] - inner[1]
        top = inner[3] - max(k, round(height * level))
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(inner, radius=inner_r, fill=255)
        bar = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rectangle((inner[0], top, inner[2], inner[3]), fill=(*fill_rgb, 255))
        img.paste(bar, (0, 0), Image.composite(bar, Image.new("RGBA", (s, s)), mask).split()[3])

    return img.resize((size, size), Image.Resampling.LANCZOS)


def tray_icon(pct: float | None, dark_taskbar: bool, size: int = 64) -> Image.Image:
    # Pins only where they stay legible: the tray renders 16-32 px, pins blur below that.
    return chip(pct, size=size, dark_taskbar=dark_taskbar, pins=True)


def app_icon_images() -> list[Image.Image]:
    """Sizes for a multi-resolution .ico (taskbar, Start, Explorer, installer)."""
    out = []
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tile = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=size * 4 // 5,
                                               fill=(24, 28, 36, 255))
        base.alpha_composite(tile.resize((size, size), Image.Resampling.LANCZOS))
        inner = chip(68, size=max(12, round(size * 0.82)), dark_taskbar=True, pins=size >= 24,
                     rgb=NORMAL_RGB)
        off = (size - inner.width) // 2
        base.alpha_composite(inner, (off, off))
        out.append(base)
    return out


def caption_icon(size: int = 256, margin: float = 0.12) -> Image.Image:
    """App icon with a transparent margin, for the window title bar. A maximized classic window draws its
    caption icon a few pixels from the screen edge, where a full-bleed tile looks cut off."""
    tile = app_icon_images()[-1].resize((round(size * (1 - 2 * margin)),) * 2, Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    off = (size - tile.width) // 2
    out.alpha_composite(tile, (off, off))
    return out
