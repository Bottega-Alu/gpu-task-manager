"""Entry point: GPUTaskManager.exe [--tray]

  (no flag)  opens the main window, the tray icon stays available
  --tray     starts hidden in the notification area (used at sign-in)

A second launch does not start a second copy: it asks the running one to show
its window (single_instance) and exits.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

from . import brand


def _setup_logging() -> None:
    from .settings import data_dir
    folder = data_dir()
    handlers: list[logging.Handler] = []
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(folder / "app.log", maxBytes=1_000_000,
                                                             backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:  # None under a windowed (no console) exe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")


def _fatal(message: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, brand.APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=brand.APP_SLUG, description=brand.APP_NAME)
    ap.add_argument("--tray", action="store_true", help="start hidden in the notification area")
    ap.add_argument("--version", action="version", version=f"{brand.APP_NAME} {brand.APP_VERSION}")
    args = ap.parse_args(argv)

    _setup_logging()
    log = logging.getLogger("gtm")
    log.info("%s %s starting (tray=%s)", brand.APP_NAME, brand.APP_VERSION, args.tray)

    from . import single_instance
    if not single_instance.claim():
        log.info("already running: asked the running instance to show its window")
        return 0

    try:
        from .app import App
        App(start_in_tray=args.tray).run()
    except Exception as exc:  # noqa: BLE001 - last resort, the user must see something
        log.exception("fatal error")
        _fatal(f"{brand.APP_NAME}: {exc}")
        return 1
    log.info("exited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
