"""Lightweight, thread-safe profiling for SUBSIDE pipeline stages.

Captures per-stage wall time, named byte/event counters, and peak RSS so a
run-manifest can answer "where did the time go and how much did we transfer?"
without pulling in a heavyweight profiler. Designed to be cheap enough to
leave on in production.

Usage::

    prof = Profiler()
    with prof.stage("download"):
        ...
        prof.add("bytes_downloaded", n)
    manifest["timings"] = prof.summary()
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator


def peak_rss_mb() -> float | None:
    """Peak resident set size of this process in MB, or None if unavailable.

    ``ru_maxrss`` is bytes on macOS/BSD and kilobytes on Linux, so normalize
    by platform. Falls back to psutil's current RSS when rusage is missing.
    """

    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024**2 if sys.platform == "darwin" else 1024
        return round(maxrss / divisor, 1)
    except Exception:
        try:
            import psutil

            return round(psutil.Process().memory_info().rss / 1024**2, 1)
        except Exception:
            return None


class CpuSampler:
    """Background sampler reporting how many cores a stage actually used.

    Answers "are the 16 cores busy or is one stream starving them?" directly,
    instead of inferring it from file counts. ``cpu_percent`` is process-wide
    (all threads), so 800.0 means ~8 cores busy on average. Degrades to a no-op
    if psutil is unavailable.
    """

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._samples: list[float] = []
        self._thread: threading.Thread | None = None
        self._proc: Any = None
        self._n_cpus = 0

    def __enter__(self) -> "CpuSampler":
        try:
            import psutil

            self._proc = psutil.Process()
            self._n_cpus = psutil.cpu_count() or 0
            self._proc.cpu_percent(None)  # prime the baseline
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        except Exception:
            self._proc = None
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self._samples.append(self._proc.cpu_percent(None))
            except Exception:
                break

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def result(self) -> dict[str, Any] | None:
        if not self._samples:
            return None
        avg = sum(self._samples) / len(self._samples)
        peak = max(self._samples)
        return {
            "avg_cores_busy": round(avg / 100, 2),
            "peak_cores_busy": round(peak / 100, 2),
            "n_cpus": self._n_cpus,
            "samples": len(self._samples),
        }


class Profiler:
    """Accumulates stage timings, counters, and notes across threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage_seconds: dict[str, float] = {}
        self._counters: dict[str, float] = {}
        self._meta: dict[str, Any] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            with self._lock:
                self._stage_seconds[name] = self._stage_seconds.get(name, 0.0) + elapsed

    def add(self, key: str, amount: float) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def note(self, key: str, value: Any) -> None:
        """Attach arbitrary metadata (e.g. CPU stats) to the summary."""

        with self._lock:
            self._meta[key] = value

    def summary(self) -> dict[str, Any]:
        with self._lock:
            stages = {k: round(v, 3) for k, v in self._stage_seconds.items()}
            counters = dict(self._counters)
            meta = dict(self._meta)
        if "bytes_downloaded" in counters:
            counters["mb_downloaded"] = round(counters["bytes_downloaded"] / 1024**2, 2)
        return {
            "stage_seconds": stages,
            "counters": counters,
            "meta": meta,
            "peak_rss_mb": peak_rss_mb(),
        }
