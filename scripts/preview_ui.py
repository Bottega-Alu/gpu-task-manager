"""Open the real UI fed by demo data, optionally saving screenshots of every surface.

    python scripts/preview_ui.py                      # interactive preview, no GPU needed
    python scripts/preview_ui.py --shots out --theme dark --lang it

With --shots it opens the quick panel and each window page in turn, saves a PNG
of each to the folder and exits. Works on Windows and under Xvfb on Linux.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_desktop import settings as settings_mod  # noqa: E402
from gtm_desktop.app import App  # noqa: E402
from gtm_desktop.demo import DemoSampler  # noqa: E402


def grab(widget, path: Path) -> None:
    from PIL import ImageGrab
    widget.update_idletasks()
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    print("saved", path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--theme", choices=("system", "light", "dark"))
    from gtm_desktop.i18n import LANGUAGES
    ap.add_argument("--lang", choices=LANGUAGES)
    args = ap.parse_args()

    original = settings_mod.load
    overrides = {k: v for k, v in (("theme", args.theme), ("language", args.lang)) if v}

    def load(path=None):
        s = original(path)
        for k, v in overrides.items():
            setattr(s, k, v)
        s.window_geometry = ""
        return s

    settings_mod.load = load
    if args.shots:
        settings_mod.save = lambda s, path=None: None  # never touch the real settings file

    app = App(start_in_tray=bool(args.shots), sampler_factory=DemoSampler)
    if not args.shots:
        app.run()
        return

    args.shots.mkdir(parents=True, exist_ok=True)
    tag = f"{args.theme or 'system'}-{args.lang or 'system'}"
    steps = [
        (1500, lambda: app.flyout.show()),
        (900, lambda: grab(app.flyout.top, args.shots / f"flyout-{tag}.png")),
        (100, lambda: app.flyout.hide()),
    ]
    for page in ("overview", "processes", "history", "settings", "about"):
        def show(p=page):
            app.open_window(p)
            if p == "processes":
                tree = app.window.tree
                kids = tree.get_children()
                if kids:
                    tree.selection_set(kids[0])
        steps += [(400, show), (900, lambda p=page: grab(app.window.top, args.shots / f"window-{p}-{tag}.png"))]
    steps.append((200, app.exit))

    delay = 0
    for wait, action in steps:
        delay += wait
        app.root.after(delay, action)
    app.run()


if __name__ == "__main__":
    main()
