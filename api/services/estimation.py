"""Run-time estimation for the pre-submit UI step.

Combines fast OPERA discovery (frame intersect + product count) with the
measured runtime model in ``analysis.h2i_lab.estimate`` to show the user how
long a run will take before they submit. The job walltime itself is a flat 12 h
set in ``manager`` (``estimate_run`` returns the same flat value), so this is
purely the informational estimate.
"""

from __future__ import annotations

import sys
from typing import Any

from . import discovery
from ..config import SUBSIDE_ROOT

if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))


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
