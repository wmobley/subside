"""Runtime estimation for SUBSIDE OPERA pipelines.

Single source of truth for "how long will this run take, and how much walltime
should we request?" — used by the API to size the Tapis job's ``maxMinutes``
and to show the user an estimate before they submit.

Constants are MEASURED, not guessed: an ls6 vm-small ablation over 32 OPERA
DISP-S1 products (analysis/h2i_lab/benchmark.py, 2026-06) gave aggregate
download throughput of 67 / 97 / 88 MB/s at 4 / 8 / 16 workers, ~423 MB per
full product, and ~30 s of fixed discover+preview overhead.

Two throughputs are used deliberately:
* a *realistic* rate for the estimate shown to the user, and
* a *conservative* rate (well below anything measured) times a safety factor
  for the walltime guard, so a slow ASF night can't kill an otherwise-fine run.

The walltime is capped at 24 h: any run whose guarded estimate is under a day
gets enough walltime to finish; only an implausibly large request would flag
``may_exceed_walltime``.
"""

from __future__ import annotations

import math
from typing import Any


# --- measured constants (ls6 vm-small, full-download path) ------------------
_THROUGHPUT_MBPS: dict[int, float] = {4: 67.0, 8: 97.0, 16: 88.0}
_REALISTIC_FLOOR_MBPS = 55.0   # don't show a rosier rate than the slowest measured
_CONSERVATIVE_MBPS = 25.0      # walltime guard: ~1/4 of measured, absorbs throttling
_AVG_PRODUCT_MB = 450.0        # ~423 measured, rounded up for headroom
_FIXED_OVERHEAD_S = 40.0       # preflight + bbox metadata parse + preview + staging

# WERC continues into stack/reference/velocity/export. Those stages were not
# separately benchmarked, so these are deliberately generous placeholders.
_WERC_FIXED_S = 300.0
_WERC_PER_PRODUCT_S = 8.0

# --- walltime policy --------------------------------------------------------
_WALLTIME_SAFETY = 1.5
_WALLTIME_FLOOR_MIN = 30
_WALLTIME_CAP_MIN = 1440       # 24 h ceiling


def _realistic_mbps(num_workers: int) -> float:
    """Realistic aggregate throughput for a worker count (nearest measured)."""

    nearest = min(_THROUGHPUT_MBPS, key=lambda w: abs(w - num_workers))
    return max(_REALISTIC_FLOOR_MBPS, _THROUGHPUT_MBPS[nearest])


def _human(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"~{minutes} min"
    hours, mins = divmod(minutes, 60)
    return f"~{hours} h {mins} min" if mins else f"~{hours} h"


def estimate_run(
    product_count: int,
    *,
    pipeline: str = "h2i",
    num_workers: int = 8,
    reference_mode: str = "auto",
) -> dict[str, Any]:
    """Estimate wall time and a safe walltime request for a run.

    Returns a dict with the human-facing estimate, the ``walltime_minutes`` to
    pass as the Tapis job ``maxMinutes`` (clamped to [30 min, 24 h]), and the
    assumptions behind the numbers so the UI can be transparent.
    """

    n = max(0, int(product_count))
    realistic = _realistic_mbps(num_workers)

    download_realistic_s = _FIXED_OVERHEAD_S + n * _AVG_PRODUCT_MB / realistic
    download_conservative_s = _FIXED_OVERHEAD_S + n * _AVG_PRODUCT_MB / _CONSERVATIVE_MBPS

    analysis_s = (_WERC_FIXED_S + n * _WERC_PER_PRODUCT_S) if pipeline == "werc" else 0.0

    estimated_s = download_realistic_s + analysis_s
    guarded_s = (download_conservative_s + analysis_s) * _WALLTIME_SAFETY
    guarded_min = guarded_s / 60.0

    walltime_min = int(min(_WALLTIME_CAP_MIN, max(_WALLTIME_FLOOR_MIN, math.ceil(guarded_min))))

    return {
        "product_count": n,
        "pipeline": pipeline,
        "num_workers": num_workers,
        "estimated_minutes": round(estimated_s / 60.0, 1),
        "estimated_human": _human(estimated_s),
        "walltime_minutes": walltime_min,
        "may_exceed_walltime": guarded_min > _WALLTIME_CAP_MIN,
        "assumptions": {
            "avg_product_mb": _AVG_PRODUCT_MB,
            "realistic_mbps": realistic,
            "conservative_mbps": _CONSERVATIVE_MBPS,
            "safety_factor": _WALLTIME_SAFETY,
            "walltime_cap_minutes": _WALLTIME_CAP_MIN,
            "source": "ls6 vm-small ablation, 32 products, 2026-06",
        },
    }
