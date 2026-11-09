"""Demo data: realistic Frames without a GPU, for UI previews, screenshots and tests.

`GPUTaskManager.exe` never uses this module; scripts/preview_ui.py and the
tests do (python -m gtm_desktop.demo opens the real UI fed by demo frames).
"""

from __future__ import annotations

import math
import random
import threading
import time

from .model import GiB, MiB, Device, Frame, Proc
from .sampler import AdapterList

_LLM = {
    "models": [{"label": "qwen3:14b", "kind": "LLM", "kind_label": "LLM", "arch": "qwen3", "params": 14.8e9,
                "quant": "Q4_K_M", "layers": 40, "sources": ["api", "mapped"]}],
    "segments": [{"label": "weights (GPU)", "bytes": 8.4 * GiB, "exact": True},
                 {"label": "KV cache (f16, 8192 ctx)", "bytes": 1.25 * GiB, "exact": True},
                 {"label": "compute buffer", "bytes": 0.56 * GiB, "exact": True},
                 {"label": "runtime / unknown", "bytes": 0.31 * GiB, "exact": False}],
    "server": {"kind": "ollama", "url": "http://127.0.0.1:11434", "n_ctx": 8192, "slots_busy": 1,
               "slots_total": 1, "gen_tok_s": 61.4},
    "notes": ["Log sizes describe allocations at load time."],
}


def frame(t: float = 0.0, seed: int = 7) -> Frame:
    rnd = random.Random(seed + int(t))
    wave = (math.sin(t / 9) + 1) / 2
    gen = 70 + 25 * wave + rnd.uniform(-4, 4)
    procs = [
        Proc("0:18244", 18244, "18244", "llama-server.exe", "LLM", "CUDA+ggml", 10.52 * GiB, 0.0, None,
             gen, "qwen3:14b 14.8B Q4_K_M", r"C:\Users\demo\AppData\Local\Programs\Ollama\lib\ollama\llama-server.exe",
             False, {"engines": {"3D": gen, "Copy": 3.0}, "llm": _LLM}),
        Proc("0:9120", 9120, "9120", "chrome.exe", "browser", "Direct3D", 1.38 * GiB, 210 * MiB, 0.0,
             6 + 4 * wave, "page textures, video, canvas/WebGL", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             False, {"engines": {"3D": 5.0, "VideoDecode": 4.0}}),
        Proc("0:1460", 1460, "1460", "dwm.exe", "compositor", "Direct3D", 0.92 * GiB, 64 * MiB, 0.0, 3.0,
             "desktop back buffers + composed frames", r"C:\Windows\System32\dwm.exe", False,
             {"engines": {"3D": 3.0}}),
        Proc("0:22710", 22710, "22710", "Code.exe", "3D/game", "Direct3D", 0.41 * GiB, 18 * MiB, 0.0, 1.0,
             "textures, meshes, render targets", r"C:\Users\demo\AppData\Local\Programs\Microsoft VS Code\Code.exe",
             False, {"engines": {"3D": 1.0}}),
        Proc("0:30112", 30112, "30112", "Handy.exe", "speech", "ONNX Runtime", 0.33 * GiB, 0.0, None, 0.0,
             "installed (unproven): whisper-large-v3-turbo 1.62 GB", r"C:\Program Files\Handy\Handy.exe", False,
             {"installed_models": [{"path": "whisper-large-v3-turbo.bin", "size": 1.62 * GiB}]}),
    ]
    used = sum(p.vram for p in procs) + 0.38 * GiB
    device = Device(name="NVIDIA GeForce RTX 4080 SUPER", vendor="NVIDIA", driver="581.57", cuda="13.0",
                    backend="wddm", vram_total=16 * GiB, vram_used=int(used), shared_used=int(0.29 * GiB),
                    util_gpu=gen, util_mem=40 + 20 * wave, temp=58 + 12 * wave, power_w=180 + 90 * wave,
                    power_limit_w=320, sm_clock=2610 + rnd.uniform(-30, 30), sm_clock_max=3105,
                    enc=0.0, dec=4.0, fan=38 + 10 * wave, pcie_rx_mbs=420.0, pcie_tx_mbs=95.0)
    raw = {"gpu": device.name, "processes": [p.raw for p in procs], "demo": True}
    text = "\n".join([f"{device.name}  driver {device.driver}  CUDA {device.cuda}"] +
                     [f"{p.pid:>7}  {p.name:<20} {p.kind:<10} {p.inside}" for p in procs])
    return Frame(taken=time.time(), device=device, procs=tuple(procs), raw=raw, text=text)


class DemoSampler:
    """Drop-in for Sampler: publishes demo frames on a thread."""

    def __init__(self, publish, interval: float = 1.0, gpu_index: int = 0) -> None:
        self._publish, self.interval, self.gpu_index = publish, interval, gpu_index
        self._stop = threading.Event()
        self.paused = False

    def start(self) -> None:
        self._publish(AdapterList(("NVIDIA GeForce RTX 4080 SUPER", "Intel(R) UHD Graphics 770"), 0))

        def run():
            t = 0.0
            for i in range(240):  # pre-fill history so charts are not empty
                self._publish(frame(i - 240.0))
            while not self._stop.is_set():
                if not self.paused:
                    self._publish(frame(t))
                    t += self.interval
                self._stop.wait(self.interval)

        threading.Thread(target=run, daemon=True).start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_interval(self, seconds: float) -> None:
        self.interval = seconds


if __name__ == "__main__":
    from .app import App
    App(start_in_tray=False, sampler_factory=DemoSampler).run()
