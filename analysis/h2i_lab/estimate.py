"""Runtime estimation for SUBSIDE OPERA pipelines.

Single source of truth for "how long will this run take, and how much walltime
should we request?" — used by the API to size the Tapis job's ``maxMinutes``
and to show the user an estimate before they submit.

Constants are MEASURED, not guessed: an ls6 vm-small download-scaling run
(tapis/benchmarks/download_scaling.sbatch, 2026-06) over 2..100 OPERA DISP-S1
products at 8 workers. Throughput is not flat — it peaks ~87 MB/s near N=25 and
throttles to ~63 MB/s by N=100 — so the realistic rate is set near the
sustained/throttled end (~68 MB/s) to avoid underestimating large runs.
Products are ~420 MB each; cores stay idle (download is I/O-bound).

The user-facing *estimate* uses the realistic rate. The job *walltime* is a flat
12 h, NOT sized to the estimate: a SLURM job releases its node the instant it
finishes, so an over-sized cap costs only a little scheduling priority, and 12 h
clears even the slow/throttled worst case we've observed (a 209-product run that
needed ~4.5 h at 2 workers) with wide margin. Sizing walltime to the estimate
risked under-reserving when ASF throttles old/large requests below calibration;
a flat 12 h sidesteps that entirely.
"""

from __future__ import annotations

from typing import Any


# --- measured constants (ls6 vm-small, full-download path) ------------------
# From the download-scaling run (tapis/benchmarks/download_scaling.sbatch, 2026-06,
# workers=8): aggregate throughput is NOT flat — it peaks ~87 MB/s around N=25
# then THROTTLES under sustained load to ~63 MB/s by N=100 (marginal ~50 MB/s).
# The rates below are the *sustained* values, deliberately set near the throttled
# end so large runs aren't underestimated (the dangerous direction for walltime).
# Only workers=8 was characterized at scale; 4/16 are scaled from it.
_THROUGHPUT_MBPS: dict[int, float] = {4: 48.0, 8: 68.0, 16: 64.0}
_REALISTIC_FLOOR_MBPS = 45.0   # don't show a rosier rate than the sustained floor
_CONSERVATIVE_MBPS = 25.0      # walltime guard: < worst measured marginal (~50), safe
_AVG_PRODUCT_MB = 420.0        # measured 418-422 MB per full DISP-S1 product
_FIXED_OVERHEAD_S = 25.0       # connection ramp + bbox parse (small; ramp is in the rate)

# WERC continues into stack/reference/velocity/export. Those stages were not
# separately benchmarked, so these are deliberately generous placeholders.
_WERC_FIXED_S = 300.0
_WERC_PER_PRODUCT_S = 8.0

# --- walltime policy --------------------------------------------------------
# Flat 12 h reservation (see module docstring). The job exits and frees the node
# when done, so the cap is a safety ceiling, not a cost.
_WALLTIME_MIN = 720


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
    """Estimate run time and return the (flat 12 h) walltime to request.

    ``estimated_minutes`` is the realistic finish estimate to show the user;
    ``walltime_minutes`` is the flat 12 h ``maxMinutes`` the job reserves.
    """

    n = max(0, int(product_count))
    realistic = _realistic_mbps(num_workers)

    download_realistic_s = _FIXED_OVERHEAD_S + n * _AVG_PRODUCT_MB / realistic
    analysis_s = (_WERC_FIXED_S + n * _WERC_PER_PRODUCT_S) if pipeline == "werc" else 0.0
    estimated_s = download_realistic_s + analysis_s

    return {
        "product_count": n,
        "pipeline": pipeline,
        "num_workers": num_workers,
        "estimated_minutes": round(estimated_s / 60.0, 1),
        "estimated_human": _human(estimated_s),
        "walltime_minutes": _WALLTIME_MIN,
        "may_exceed_walltime": estimated_s / 60.0 > _WALLTIME_MIN,
        "assumptions": {
            "avg_product_mb": _AVG_PRODUCT_MB,
            "realistic_mbps": realistic,
            "walltime_minutes_flat": _WALLTIME_MIN,
            "source": "ls6 download-scaling run, 2..100 products, 2026-06",
        },
    }
