"""Log the VRAM no process accounts for (NVML used - sum of per-process WDDM usage), with the events around it.

    .venv\\Scripts\\pythonw.exe ops\\vram-residual-monitor\\monitor.py --hours 6 --interval 10

Writes to ops/vram-residual-monitor/runs/<start time>/:
  samples.csv    one row per sample: used, attributed, residual (MB), process count, top processes, screens
  events.jsonl   GPU processes started / exited / changed by >= --delta-mb, sampling gaps (sleep, hang), screen changes,
                 errors
  status.json    last sample and counters, rewritten every sample (to check it is alive)
Stop early: create a file named STOP in the run folder. Read with analyze.py.
Background: see audits/2026-11-09_vram-unattributed/README.md.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

MB = 1024 ** 2
MAX_FAILS = 5          # consecutive sample failures before a long pause (circuit breaker)
COOLDOWN_S = 60


def screens() -> str:
    if sys.platform != "win32":
        return ""
    u = ctypes.windll.user32
    # SM_CMONITORS, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
    return f"{u.GetSystemMetrics(80)}x {u.GetSystemMetrics(78)}x{u.GetSystemMetrics(79)}"


class Run:
    def __init__(self, out: Path, interval: float, delta_mb: float) -> None:
        self.out, self.interval, self.delta = out, interval, delta_mb * MB
        out.mkdir(parents=True, exist_ok=True)
        self.csv_f = open(out / "samples.csv", "a", newline="", encoding="utf-8")
        self.csv = csv.writer(self.csv_f)
        if self.csv_f.tell() == 0:
            self.csv.writerow(["time", "used_mb", "attributed_mb", "residual_mb", "processes", "top", "screens"])
        self.ev_f = open(out / "events.jsonl", "a", encoding="utf-8")
        self.prev: dict[int, tuple[str, float]] | None = None
        self.prev_screens = ""
        self.last_t: float | None = None
        self.samples = self.errors = 0

    def event(self, kind: str, **data) -> None:
        self.ev_f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "kind": kind, **data}) + "\n")
        self.ev_f.flush()

    def record(self, frame) -> dict:
        now = time.time()
        if self.last_t is not None and now - self.last_t > 3 * self.interval:
            self.event("gap", seconds=round(now - self.last_t), note="no samples: sleep, hibernation or a hang")
        self.last_t = now
        procs = {p.pid: (p.name, p.vram) for p in frame.procs if p.vram and not p.host}
        used = frame.device.vram_used or 0
        attributed = sum(v for _n, v in procs.values())
        residual = used - attributed
        if self.prev is not None:
            for pid, (name, v) in procs.items():
                if pid not in self.prev:
                    self.event("started", pid=pid, name=name, vram_mb=round(v / MB))
                elif abs(v - self.prev[pid][1]) >= self.delta:
                    self.event("changed", pid=pid, name=name, vram_mb=round(v / MB),
                               delta_mb=round((v - self.prev[pid][1]) / MB))
            for pid, (name, v) in self.prev.items():
                if pid not in procs:
                    self.event("exited", pid=pid, name=name, vram_mb=round(v / MB))
        self.prev = procs
        scr = screens()
        if scr != self.prev_screens:
            if self.prev_screens:
                self.event("screens", before=self.prev_screens, after=scr)
            self.prev_screens = scr
        top = sorted(procs.items(), key=lambda kv: -kv[1][1])[:3]
        row = [datetime.now().isoformat(timespec="seconds"), round(used / MB), round(attributed / MB),
               round(residual / MB), len(procs), "; ".join(f"{n} {v / MB:.0f}" for _p, (n, v) in top), scr]
        self.csv.writerow(row)
        self.csv_f.flush()
        self.samples += 1
        status = {"time": row[0], "used_mb": row[1], "attributed_mb": row[2], "residual_mb": row[3],
                  "samples": self.samples, "errors": self.errors}
        (self.out / "status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
        return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--delta-mb", type=float, default=128.0, help="log a process whose VRAM moves by this much")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if sys.platform == "win32":  # real pixels in screens(), not the 96-dpi virtualised ones
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass
    out = args.out or Path(__file__).parent / "runs" / datetime.now().strftime("%Y-%m-%d_%H%M")
    run = Run(out, args.interval, args.delta_mb)

    from gputaskman.collector import Collector
    from gtm_desktop.model import frame_from_snapshot

    run.event("start", hours=args.hours, interval=args.interval, delta_mb=args.delta_mb, pid=__import__("os").getpid())
    end = time.time() + args.hours * 3600
    collector, fails = None, 0
    try:
        while time.time() < end and not (out / "STOP").exists():
            started = time.monotonic()
            try:
                if collector is None:
                    collector = Collector(args.gpu)
                    collector.sample()
                    time.sleep(1.0)
                run.record(frame_from_snapshot(collector.sample()))
                fails = 0
            except Exception as exc:  # noqa: BLE001 - keep monitoring; every failure is logged
                fails += 1
                run.errors += 1
                run.event("error", error=f"{type(exc).__name__}: {exc}", consecutive=fails)
                try:
                    if collector is not None:
                        collector.close()
                except Exception:  # noqa: BLE001
                    pass
                collector = None
                if fails >= MAX_FAILS:
                    run.event("cooldown", seconds=COOLDOWN_S)
                    time.sleep(COOLDOWN_S)
                    fails = 0
            time.sleep(max(0.5, args.interval - (time.monotonic() - started)))
    finally:
        run.event("stop", samples=run.samples, errors=run.errors,
                  reason="STOP file" if (out / "STOP").exists() else "duration elapsed or interrupted")
        if collector is not None:
            collector.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
