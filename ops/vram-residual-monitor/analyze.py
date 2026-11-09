"""Summarise a monitor.py run: how the residual moved, and which events sit next to its jumps.

    .venv\\Scripts\\python.exe ops\\vram-residual-monitor\\analyze.py ops\\vram-residual-monitor\\runs\\<run> [--jump-mb 64]

Writes report.md into the run folder and prints it. A jump is a change of at least --jump-mb in the residual between
two consecutive samples; events from the previous sample time up to the jump's sample count as "nearby".
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
from datetime import datetime
from pathlib import Path


def load(run: Path):
    with open(run / "samples.csv", encoding="utf-8") as f:
        samples = [dict(r, t=datetime.fromisoformat(r["time"])) for r in csv.DictReader(f)]
    events = []
    if (run / "events.jsonl").exists():
        for line in open(run / "events.jsonl", encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                e["t"] = datetime.fromisoformat(e["time"])
                events.append(e)
    return samples, events


def describe(e: dict) -> str:
    k = e["kind"]
    if k in ("started", "exited", "changed"):
        extra = f" ({e['delta_mb']:+} MB)" if k == "changed" else f" {e.get('vram_mb')} MB"
        return f"{k} {e['name']}{extra}"
    if k == "gap":
        return f"gap {e['seconds']} s"
    if k == "screens":
        return f"screens {e['before']} -> {e['after']}"
    return k


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--jump-mb", type=float, default=64.0)
    args = ap.parse_args()
    samples, events = load(args.run)
    if len(samples) < 2:
        print("not enough samples yet")
        return 1
    res = [int(s["residual_mb"]) for s in samples]
    hours = (samples[-1]["t"] - samples[0]["t"]).total_seconds() / 3600
    lines = [f"# Residual VRAM: {args.run.name}", "",
             f"- Samples: {len(samples)} from {samples[0]['time']} to {samples[-1]['time']} ({hours:.2f} h)",
             f"- Residual: start {res[0]} MB, end {res[-1]} MB, min {min(res)} MB, max {max(res)} MB",
             f"- Net change: {res[-1] - res[0]:+} MB" + (f" ({(res[-1] - res[0]) / hours:+.0f} MB/h)" if hours else ""),
             f"- Events: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(e["kind"] for e in events).items()),
             "", f"## Jumps of at least {args.jump_mb:.0f} MB", ""]
    jumps, near_up = [], collections.Counter()
    for prev, cur in zip(samples, samples[1:]):
        d = int(cur["residual_mb"]) - int(prev["residual_mb"])
        if abs(d) >= args.jump_mb:
            near = [e for e in events if prev["t"] < e["t"] <= cur["t"] and e["kind"] not in ("start", "stop")]
            jumps.append((cur, d, near))
            if d > 0:
                for e in near:
                    near_up[(e["kind"], e.get("name", ""))] += 1
    if not jumps:
        lines.append("None: the residual moved only in small steps.")
    for cur, d, near in jumps:
        what = "; ".join(describe(e) for e in near) or "no event nearby"
        lines.append(f"- {cur['time']}  {d:+} MB -> {cur['residual_mb']} MB  |  {what}")
    ups = sum(d for _c, d, _n in jumps if d > 0)
    lines += ["", "## Events next to upward jumps", ""]
    if near_up:
        for (kind, name), n in near_up.most_common(15):
            lines.append(f"- {n}x {kind} {name}".rstrip())
    else:
        lines.append("None.")
    small = (res[-1] - res[0]) - sum(d for _c, d, _n in jumps)
    lines += ["", "## Reading", "",
              f"- Upward jumps add up to {ups:+} MB; small steps between them to {small:+} MB.",
              "- The same event next to most upward jumps points at that app or workload.",
              "- Growth in small steps with no events, or jumps with no event nearby, points at the driver itself."]
    report = "\n".join(lines) + "\n"
    (args.run / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
