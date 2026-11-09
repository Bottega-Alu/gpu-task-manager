"""View model: formatting, frames built from real engine snapshots, alerts, process detail."""

from gputaskman.collector import ProcRow, Snapshot
from gputaskman.dxgi import Adapter
from gputaskman.pdh import ProcGpu
from gputaskman.procinfo import ProcDetail
from gputaskman.telemetry import DeviceTelemetry

from gtm_desktop import demo, i18n
from gtm_desktop.model import (GiB, MiB, AlertTracker, History, describe, describe_text, device_load,
                               fmt_bytes, fmt_pct, frame_from_snapshot)


def snapshot():
    adapter = Adapter(luid=1, name="NVIDIA GeForce RTX 4080 SUPER", vendor_id=0x10DE,
                      dedicated_vram=16 * GiB, shared_system=32 * GiB, software=False)
    g = ProcGpu(dedicated=10 * GiB, shared=200 * MiB, committed=11 * GiB)
    g.engines["3D"] = 87.0
    row = ProcRow(pid=42, name="llama-server.exe", kind="LLM", gpu=g,
                  detail=ProcDetail(pid=42, name="llama-server.exe", exe=r"C:\x\llama-server.exe",
                                    runtimes=["CUDA", "ggml"]))
    nv = DeviceTelemetry(index=0, name="RTX", util_gpu=91.0, temp=70.0, power_w=250.0, power_limit_w=320.0,
                         pcie_rx_kbs=2048)
    return Snapshot(taken=1.0, adapter=adapter, adapters=[adapter], nv=nv, driver="581.57", cuda="13.0",
                    vram_total=16 * GiB, vram_used=12 * GiB, shared_used=300 * MiB, procs=[row])


def test_frame_from_real_snapshot():
    f = frame_from_snapshot(snapshot())
    assert f.device.name == "NVIDIA GeForce RTX 4080 SUPER"
    assert f.device.vendor == "NVIDIA"
    assert f.device.vram_pct == 75.0
    assert f.device.pcie_rx_mbs == 2.0
    (p,) = f.procs
    assert p.name == "llama-server.exe" and p.vram == 10 * GiB and p.spill == 200 * MiB
    assert p.paged == 1 * GiB - 200 * MiB
    assert p.gpu_pct == 87.0 and p.runtime == "CUDA+ggml"
    assert "llama-server.exe" in f.text
    assert f.raw["processes"][0]["pid"] == 42


def test_device_load_falls_back_to_busiest_process():
    f = frame_from_snapshot(snapshot())
    assert device_load(f) == 91.0
    s = snapshot()
    s.nv = None
    assert device_load(frame_from_snapshot(s)) == 87.0


def test_formatting_follows_language():
    i18n.set_language("en")
    assert fmt_bytes(1.5 * GiB) == "1.5 GB"
    assert fmt_bytes(300 * MiB) == "300 MB"
    assert fmt_pct(None) == "n/a"
    i18n.set_language("it")
    assert fmt_bytes(1.5 * GiB) == "1,5 GB"
    assert fmt_pct(None) == "n/d"
    i18n.set_language("en")


def test_alerts_fire_once_then_rearm_below_hysteresis():
    now = [0.0]
    t = AlertTracker(clock=lambda: now[0])
    hot = demo.frame(0)
    # demo VRAM is ~87%: a 85% limit fires once, then stays quiet while above it.
    assert [a.kind for a in t.update(hot, 85, 0)] == ["vram"]
    assert t.update(hot, 85, 0) == []
    # still above limit - hysteresis: no re-arm, no repeat
    assert t.update(hot, 85, 0) == []
    # dropping well below re-arms, but the cooldown suppresses a quick repeat
    now[0] = 10
    assert t.update(hot, 95, 0) == []      # below 95-5: re-armed
    assert t.update(hot, 85, 0) == []      # cooldown
    now[0] = 10_000
    assert t.update(hot, 95, 0) == []
    assert [a.kind for a in t.update(hot, 85, 0)] == ["vram"]


def test_alerts_off_when_limit_zero():
    t = AlertTracker()
    assert t.update(demo.frame(0), 0, 0) == []


def test_temp_alert_message():
    i18n.set_language("en")
    t = AlertTracker()
    alerts = t.update(demo.frame(0), 0, 50)
    assert alerts and alerts[0].kind == "temp" and "threshold 50" in alerts[0].message


def test_describe_llm_process():
    i18n.set_language("en")
    llama = demo.frame(0).procs[0]
    sections = dict(describe(llama))
    assert "LLM" in sections and any("qwen3:14b" in line for line in sections["LLM"])
    assert any("KV cache" in line for line in sections["Memory breakdown"])
    assert "61.4 tok/s" in describe_text(llama)


def test_history_is_bounded():
    h = History(maxlen=5)
    for i in range(12):
        h.add(demo.frame(i))
    assert len(h.gpu) == len(h.vram) == len(h.temp) == 5
