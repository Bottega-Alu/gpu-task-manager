"""Sampler thread: frames out, errors surfaced, collector rebuilt after a failure."""

import time

from gtm_desktop import sampler as sampler_mod
from gtm_desktop.model import Frame
from gtm_desktop.sampler import AdapterList, Sampler, SamplerError
from tests.test_model import snapshot


class FakeCollector:
    def __init__(self, fail_after=None):
        self.adapters = []
        self.calls = 0
        self.closed = False
        self.fail_after = fail_after

    def sample(self):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("driver reset")
        return snapshot()

    def close(self):
        self.closed = True


def collect(events, kind, n, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if sum(isinstance(e, kind) for e in events) >= n:
            return True
        time.sleep(0.02)
    return False


def test_publishes_frames():
    events = []
    s = Sampler(events.append, interval=0.05, collector_factory=lambda i: FakeCollector())
    s.start()
    try:
        assert collect(events, Frame, 3)
        assert any(isinstance(e, AdapterList) for e in events)
    finally:
        s.stop()


def test_failure_is_reported_and_collector_rebuilt(monkeypatch):
    monkeypatch.setattr(sampler_mod, "RETRY_S", 0.05)
    made = []

    def factory(i):
        c = FakeCollector(fail_after=1)
        made.append(c)
        return c

    events = []
    s = Sampler(events.append, interval=0.05, collector_factory=factory)
    s.start()
    try:
        assert collect(events, SamplerError, 1)
        assert collect(events, Frame, 2)
        assert len(made) >= 2 and made[0].closed
    finally:
        s.stop()


def test_start_failure_retries(monkeypatch):
    monkeypatch.setattr(sampler_mod, "RETRY_S", 0.05)
    attempts = []

    def factory(i):
        attempts.append(i)
        if len(attempts) < 3:
            raise OSError("no driver")
        return FakeCollector()

    events = []
    s = Sampler(events.append, interval=0.05, collector_factory=factory)
    s.start()
    try:
        assert collect(events, Frame, 1)
        assert sum(isinstance(e, SamplerError) for e in events) >= 2
    finally:
        s.stop()


def test_out_of_range_gpu_falls_back_to_zero():
    seen = []

    def factory(i):
        seen.append(i)
        if i > 0:
            raise ValueError("--gpu 3 is out of range")
        return FakeCollector()

    events = []
    s = Sampler(events.append, interval=0.05, gpu_index=3, collector_factory=factory)
    s.start()
    try:
        assert collect(events, Frame, 1)
        assert seen[:2] == [3, 0] and s.gpu_index == 0
    finally:
        s.stop()


def test_pause_stops_sampling():
    c = FakeCollector()
    events = []
    s = Sampler(events.append, interval=0.02, collector_factory=lambda i: c)
    s.start()
    try:
        assert collect(events, Frame, 2)
        s.set_paused(True)
        time.sleep(0.1)
        before = c.calls
        time.sleep(0.2)
        assert c.calls == before
    finally:
        s.stop()
