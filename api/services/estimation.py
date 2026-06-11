"""Run-time estimation for the pre-submit UI step.

Combines fast OPERA discovery (frame intersect + product count) with the
measured runtime model in ``analysis.h2i_lab.estimate`` to answer "how long
will this run take and how much walltime should we request?" before a job is
submitted. The same ``walltime_minutes`` it returns is what ``manager.submit_run``
passes to the Tapis job as ``maxMinutes``, so the estimate the user sees and
the walltime the job gets stay in lockstep.
"""

from __future__ import annotations

import sys
from typing import Any

from . import discovery
from ..config import SUBSIDE_ROOT

if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))


# Fallback walltime (minutes) per pipeline when discovery can't run — generous
# enough for any realistic catalog, matching the pipeline YAML defaults.
_FALLBACK_WALLTIME = {"h2i": 240, "werc": 300}


def estimate(
    aoi_geojson: dict[str, Any],
    start_date: str,
    end_date: str,
    *,
    pipeline: str = "h2i",
    num_workers: int = 8,
    min_overlap_percent: float = 50.0,
    reference_mode: str = "auto",
) -> dict[str, Any]:
    """Discover product count for the AOI/window and estimate runtime + walltime."""

    from analysis.h2i_lab.estimate import estimate_run

    frames = discovery.find_frames(aoi_geojson, min_overlap_percent)
    frame_ids = frames.get("frame_ids", [])
    if not frame_ids:
        result = estimate_run(0, pipeline=pipeline, num_workers=num_workers, reference_mode=reference_mode)
        result["warning"] = "No OPERA frames intersect this AOI."
        return result

    products = discovery.search_products(frame_ids, start_date, end_date)
    product_count = products.get("product_count", 0)
    result = estimate_run(
        product_count, pipeline=pipeline, num_workers=num_workers, reference_mode=reference_mode
    )
    if product_count == 0:
        result["warning"] = "No OPERA DISP-S1 products found in this date range."
    return result


def walltime_for_request(req: Any) -> int | None:
    """Best-effort walltime (minutes) for a RunRequest, or None to use the
    pipeline default. Never raises — submission must not fail on a slow ASF."""

    try:
        result = estimate(
            req.aoi_geojson,
            req.start_date,
            req.end_date,
            pipeline=req.pipeline,
            num_workers=req.num_workers,
            min_overlap_percent=req.min_overlap_percent,
            reference_mode=getattr(req, "reference_mode", "auto"),
        )
        return int(result["walltime_minutes"])
    except Exception:
        return _FALLBACK_WALLTIME.get(getattr(req, "pipeline", "h2i"))
