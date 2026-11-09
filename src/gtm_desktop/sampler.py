"""Background sampling thread around gputaskman's Collector.

Every engine object (PDH query, NVML handle, DXGI adapters, process caches) is
created, used and closed on this one thread. The UI receives only immutable
model.Frame objects through the `publish` callback, which must be thread-safe
(the app puts them on a queue drained by Tk's after() loop).

Decision tree per iteration:
  paused                      -> wait, sample nothing (GPU counters stay idle)
  no collector                -> try to create one; on failure publish the
                                 error and retry after RETRY_S
  collector                   -> sample, build a Frame, publish it; a sample
                                 that raises is logged and the collector is
                                 rebuilt on the next iteration
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .model import Frame, frame_from_snapshot

log = logging.getLogger(__name__)
RETRY_S = 10.0


@dataclass(frozen=True)
class SamplerError:
    message: str


@dataclass(frozen=True)
class AdapterList:
    names: tuple[str, ...]
    selected: int


class Sampler:
    def __init__(self, publish: Callable[[object], None], interval: float = 1.0, gpu_index: int = 0,
                 collector_factory: Callable[[int], object] | None = None) -> None:
        self._publish = publish
        self.interval = interval
        self.gpu_index = gpu_index
        self._factory = collector_factory or self._default_factory
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._paused = False
        self._thread: threading.Thread | None = None
        self._collector = None
        from .estimate import Estimator
        self._estimator = Estimator()  # model guesses for AI processes without OS evidence

    @staticmethod
    def _default_factory(gpu_index: int):
        from gputaskman.collector import Collector
        return Collector(gpu_index)

    # -- control (any thread)
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="gpu-sampler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._wake.set()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_interval(self, seconds: float) -> None:
        self.interval = max(0.25, float(seconds))
        self._wake.set()

    # -- sampler thread
    def _open(self) -> bool:
        try:
            self._collector = self._factory(self.gpu_index)
        except ValueError:
            log.warning("GPU index %s out of range, falling back to 0", self.gpu_index)
            self.gpu_index = 0
            try:
                self._collector = self._factory(0)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                log.exception("collector start failed")
                self._publish(SamplerError(str(exc)))
                return False
        except Exception as exc:  # noqa: BLE001
            log.exception("collector start failed")
            self._publish(SamplerError(str(exc)))
            return False
        try:
            from gputaskman.collector import ordered_adapters
            names = tuple(a.name for a in ordered_adapters(self._collector.adapters))
        except Exception:  # noqa: BLE001 - optional information
            names = ()
        self._publish(AdapterList(names, self.gpu_index))
        return True

    def _close(self) -> None:
        if self._collector is not None:
            try:
                self._collector.close()
            except Exception:  # noqa: BLE001
                log.exception("collector close failed")
            self._collector = None

    def _sleep(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._paused:
                    self._sleep(1.0)
                    continue
                if self._collector is None and not self._open():
                    self._sleep(RETRY_S)
                    continue
                started = time.monotonic()
                try:
                    frame: Frame = frame_from_snapshot(self._collector.sample(), self._estimator)
                except Exception as exc:  # noqa: BLE001
                    log.exception("sample failed; collector will be rebuilt")
                    self._publish(SamplerError(str(exc)))
                    self._close()
                    self._sleep(RETRY_S)
                    continue
                self._publish(frame)
                self._sleep(max(0.05, self.interval - (time.monotonic() - started)))
        finally:
            self._close()
