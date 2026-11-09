"""View model: immutable, thread-safe copies of a gputaskman Snapshot for the UI.

The sampler thread builds a Frame right after Collector.sample(); the UI thread
only ever sees Frames. The engine's own objects (ProcDetail and friends) are
cached and mutated by later samples, so they never cross to the UI thread.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field

from .i18n import _, language

GiB = 1 << 30
MiB = 1 << 20


# ---------------------------------------------------------------- formatting

def _num(value: float, digits: int) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if language() != "en" else text


def fmt_bytes(n: float | None) -> str:
    if n is None:
        return _("n/a")
    if abs(n) >= GiB:
        return f"{_num(n / GiB, 1)} GB"
    return f"{n / MiB:.0f} MB"


def fmt_pct(v: float | None) -> str:
    return _("n/a") if v is None else f"{v:.0f}%"


def fmt_temp(v: float | None) -> str:
    return _("n/a") if v is None else f"{v:.0f} °C"


def fmt_watts(v: float | None, limit: float | None = None) -> str:
    if v is None:
        return _("n/a")
    return f"{v:.0f} W" + (f" / {limit:.0f} W" if limit else "")


def fmt_mhz(v: float | None) -> str:
    return _("n/a") if v is None else f"{v:.0f} MHz"


# ---------------------------------------------------------------- data

@dataclass(frozen=True)
class Device:
    name: str = ""
    vendor: str = ""
    driver: str = ""
    cuda: str = ""
    backend: str = ""
    vram_total: int = 0
    vram_used: int | None = None
    shared_used: int | None = None
    util_gpu: float | None = None
    util_mem: float | None = None
    temp: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    sm_clock: float | None = None
    sm_clock_max: float | None = None
    enc: float | None = None
    dec: float | None = None
    fan: float | None = None
    pcie_rx_mbs: float | None = None
    pcie_tx_mbs: float | None = None
    status: str = ""

    @property
    def vram_pct(self) -> float | None:
        if self.vram_used is None or not self.vram_total:
            return None
        return 100.0 * self.vram_used / self.vram_total


@dataclass(frozen=True)
class Proc:
    key: str
    pid: int
    pid_label: str
    name: str
    kind: str
    runtime: str
    vram: float | None
    spill: float | None
    paged: float | None
    gpu_pct: float | None
    inside: str
    exe: str
    host: bool
    raw: dict = field(compare=False, hash=False, repr=False)
    estimate: object = field(default=None, compare=False, hash=False, repr=False)  # estimate.Estimate | None


@dataclass(frozen=True)
class Frame:
    taken: float
    device: Device
    procs: tuple[Proc, ...]
    raw: dict = field(compare=False, hash=False, repr=False)
    text: str = ""


def _f(d: dict | None, key: str):
    if not d:
        return None
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# gputaskman's fixed "what's inside" descriptions per process kind (collector.ProcRow.inside): shown translated.
ENGINE_INSIDE = frozenset((
    "desktop back buffers + composed frames", "all Linux GPU memory (every WSL distro + WSLg)",
    "a process in another PID namespace (host or another container)", "driver/kernel allocations",
    "page textures, video, canvas/WebGL", "video frames (decode/encode)", "textures, meshes, render targets",
))


def shown_inside(text: str) -> str:
    """Display form of Proc.inside: the engine's fixed descriptions translated, everything else as is.
    Translated at display time, so a language switch applies at once and demo frames are covered too."""
    return _(text) if text in ENGINE_INSIDE else text


def estimate_inside(est) -> str:
    """One-line label, e.g. 'Systran/faster-whisper-large-v3 (estimate · by size, 2.9 GB)'."""
    basis = _("in code") if est.basis == "code" else _("by size")
    return f"{est.model.label} ({_('estimate')} · {basis}, {fmt_bytes(est.model.size)})"


def frame_from_snapshot(snap, estimator=None) -> Frame:
    """Build a Frame. Must run on the sampler thread, right after sample()."""
    from gputaskman.report import to_dict, to_text

    raw = to_dict(snap)
    nv = raw.get("device") or {}
    rx, tx = _f(nv, "pcie_rx_kbs"), _f(nv, "pcie_tx_kbs")
    device = Device(
        name=raw.get("gpu") or nv.get("name") or "GPU",
        vendor=snap.adapter.vendor if snap.adapter else "",
        driver=raw.get("driver") or "",
        cuda=raw.get("cuda") or "",
        backend=raw.get("backend") or "",
        vram_total=int(raw.get("vram_total") or 0),
        vram_used=raw.get("vram_used"),
        shared_used=raw.get("shared_used"),
        util_gpu=_f(nv, "util_gpu"),
        util_mem=_f(nv, "util_mem"),
        temp=_f(nv, "temp"),
        power_w=_f(nv, "power_w"),
        power_limit_w=_f(nv, "power_limit_w"),
        sm_clock=_f(nv, "sm_clock") or _f(nv, "gfx_clock"),
        sm_clock_max=_f(nv, "sm_clock_max"),
        enc=_f(nv, "enc"),
        dec=_f(nv, "dec"),
        fan=_f(nv, "fan"),
        pcie_rx_mbs=rx / 1024 if rx is not None else None,
        pcie_tx_mbs=tx / 1024 if tx is not None else None,
        status=raw.get("counter_status") or "",
    )
    procs = []
    for row, item in zip(snap.procs, raw.get("processes", [])):
        est = estimator.estimate(row) if estimator is not None else None
        runtime, inside = row.runtime, row.inside
        if est is not None:
            parts = runtime.split("+") if runtime else []
            runtime = "+".join([est.runtime] + [r for r in parts if r != est.runtime])
            inside = estimate_inside(est)
        procs.append(Proc(
            key=row.key, pid=row.pid, pid_label=row.pid_label, name=row.name, kind=row.kind,
            runtime=runtime, vram=row.gpu.shown_vram, spill=item.get("shared_bytes"),
            paged=item.get("paged_out_bytes"), gpu_pct=item.get("gpu_pct"), inside=inside,
            exe=row.detail.exe or "", host=row.host, raw=item, estimate=est,
        ))
    if estimator is not None:
        estimator.prune({row.pid for row in snap.procs if not row.host})
    return Frame(taken=raw.get("taken") or time.time(), device=device, procs=tuple(procs),
                 raw=raw, text=to_text(snap))


# GPU% of the whole device: NVML when present, else the busiest process (WDDM semantics).
def device_load(frame: Frame) -> float | None:
    if frame.device.util_gpu is not None:
        return frame.device.util_gpu
    loads = [p.gpu_pct for p in frame.procs if p.gpu_pct is not None]
    return max(loads) if loads else None


# ---------------------------------------------------------------- history

@dataclass
class History:
    """Rolling samples for the charts: GPU %, VRAM %, temperature, power."""
    maxlen: int = 300
    gpu: deque = field(default_factory=deque)
    vram: deque = field(default_factory=deque)
    temp: deque = field(default_factory=deque)
    power: deque = field(default_factory=deque)

    def __post_init__(self):
        for name in ("gpu", "vram", "temp", "power"):
            setattr(self, name, deque(maxlen=self.maxlen))

    def add(self, frame: Frame) -> None:
        self.gpu.append(device_load(frame))
        self.vram.append(frame.device.vram_pct)
        self.temp.append(frame.device.temp)
        self.power.append(frame.device.power_w)


# ---------------------------------------------------------------- alerts

@dataclass
class Alert:
    kind: str  # "vram" | "temp"
    title: str
    message: str


class AlertTracker:
    """Edge-triggered alerts with hysteresis and a cooldown, so a value hovering
    on the threshold produces one notification, not one per sample."""

    HYSTERESIS = 5.0
    COOLDOWN_S = 600.0

    def __init__(self, clock=time.monotonic):
        self._armed = {"vram": True, "temp": True}
        self._last = {"vram": -1e9, "temp": -1e9}
        self._clock = clock

    def _check(self, kind: str, value: float | None, limit: int) -> bool:
        if not limit or value is None:
            self._armed[kind] = True
            return False
        if value < limit - self.HYSTERESIS:
            self._armed[kind] = True
            return False
        if value >= limit and self._armed[kind]:
            self._armed[kind] = False
            now = self._clock()
            if now - self._last[kind] >= self.COOLDOWN_S:
                self._last[kind] = now
                return True
        return False

    def update(self, frame: Frame, vram_limit: int, temp_limit: int) -> list[Alert]:
        out = []
        dev = frame.device
        if self._check("vram", dev.vram_pct, vram_limit):
            top = max((p for p in frame.procs if p.vram is not None), key=lambda p: p.vram, default=None)
            proc = f"{top.name} ({fmt_bytes(top.vram)})" if top else "?"
            out.append(Alert("vram", _("VRAM almost full"), _("{used} of {total} in use. Largest: {proc}.").format(
                used=fmt_bytes(dev.vram_used), total=fmt_bytes(dev.vram_total), proc=proc)))
        if self._check("temp", dev.temp, temp_limit):
            out.append(Alert("temp", _("GPU running hot"), _("{temp} °C, threshold {limit} °C.").format(
                temp=f"{dev.temp:.0f}", limit=temp_limit)))
        return out


# ---------------------------------------------------------------- process detail

def describe(proc: Proc) -> list[tuple[str, list[str]]]:
    """Sections (heading, lines) for the inspector of one process."""
    item = proc.raw
    sections: list[tuple[str, list[str]]] = []
    head = [f"PID {proc.pid_label}   ·   {proc.kind}"]
    if proc.runtime:
        head.append(f"{_('Runtime')}: {proc.runtime}")
    head.append(f"VRAM {fmt_bytes(proc.vram)}   ·   {_('Spill')} {fmt_bytes(proc.spill)}   ·   "
                f"{_('Paged')} {fmt_bytes(proc.paged)}")
    engines = item.get("engines") or {}
    if engines:
        head.append(f"{_('Engines')}: " + ", ".join(f"{k} {v:.0f}%" for k, v in
                                                   sorted(engines.items(), key=lambda kv: -kv[1])))
    if proc.exe:
        head.append(f"{_('Executable')}: {proc.exe}")
    sections.append((proc.name, head))

    llm = item.get("llm")
    if llm:
        lines = []
        for m in llm.get("models", []):
            params = m.get("params")
            size = f"{params / 1e9:.1f}B" if isinstance(params, (int, float)) and params else ""
            bits = [x for x in (m.get("arch"), size, m.get("quant"),
                                f"{m.get('layers')} layers" if m.get("layers") else "") if x]
            lines.append(f"{m.get('kind_label') or m.get('kind')}: {m.get('label')}  [{', '.join(bits)}]")
            if m.get("sources"):
                lines.append(f"    {_('Evidence')}: {', '.join(m['sources'])}")
        sections.append(("LLM", lines or ["—"]))
        segs = llm.get("segments") or []
        if segs:
            sections.append((_("Memory breakdown"),
                             [f"{fmt_bytes(s.get('bytes')):>10}   {s.get('label')}" for s in segs]))
        sv = llm.get("server")
        if sv:
            line = f"{sv.get('kind')} {sv.get('url')}  ctx={sv.get('n_ctx')}  slots={sv.get('slots_busy')}/{sv.get('slots_total')}"
            if sv.get("gen_tok_s") is not None:
                line += f"  {sv['gen_tok_s']:.1f} tok/s"
            sections.append((_("Local server"), [line]))
        if llm.get("notes"):
            sections.append((_("Notes"), list(llm["notes"])))
    else:
        files = item.get("model_files") or []
        if files:
            sections.append((_("Model files"), [
                f"{m.get('store_name') or os.path.basename(m.get('path', ''))}  ({fmt_bytes(m.get('size'))})"
                f"  · {m.get('source', '')}" for m in files[:8]]))
        cands = item.get("installed_models") or []
        if cands:
            sections.append((_("Installed models (not proven loaded)"), [
                f"{m.get('store_name') or os.path.basename(m.get('path', ''))}  ({fmt_bytes(m.get('size'))})"
                for m in cands[:8]]))
    est = proc.estimate
    if est is not None:
        why = _("{runtime} does not keep the model file open, so Windows keeps no proof of which model is "
                "loaded.").format(runtime=est.runtime)
        if est.basis == "code":
            where = {"command line": _("command line"), "environment": _("environment variables"),
                     "source": _("source code")}.get(est.where, est.where)
            how = _("This model is named in the process's {where} and is on disk.").format(where=where)
        else:
            how = _("Picked the largest {runtime} model found that fits this process's VRAM ({vram}).").format(
                runtime=est.runtime, vram=fmt_bytes(est.vram))
        lines = [estimate_inside(est), f"{why} {how}", f"{_('Location')}: {est.model.path}"]
        if est.alternatives:
            lines.append(f"{_('Other models found')}: " + ", ".join(
                f"{c.label} ({fmt_bytes(c.size)})" for c in est.alternatives[:6]))
        sections.append((_("Estimated model"), lines))
    elif proc.inside and not llm:
        sections.append((_("Inside"), [shown_inside(proc.inside)]))
    return sections


def describe_text(proc: Proc) -> str:
    out = []
    for heading, lines in describe(proc):
        out.append(heading)
        out.extend(f"  {line}" for line in lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
