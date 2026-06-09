"""Bridge to the in-process subsidence forecast model.

Keeps the heavy import (numpy/pandas + the vendored model) out of the API's
import path so the core API runs without them — the `/forecast` endpoint returns
503 if they're missing, mirroring how the PostGIS layer endpoints degrade.

The model lives in the repo's top-level `analysis` package; ensure the
repo root is importable regardless of where uvicorn was launched from.
"""

from __future__ import annotations

import sys
from typing import Any

from ..config import SUBSIDE_ROOT

if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))


class ForecastUnavailable(RuntimeError):
    """The forecast model can't be imported (numpy/pandas not installed)."""


def _adapter():
    try:
        from analysis.subsidence import forecast as _forecast
    except Exception as exc:  # ImportError, or anything the model import raises
        raise ForecastUnavailable(
            "Subsidence forecast model unavailable — the API needs numpy + pandas "
            "(run it in the subside-h2i-opera conda env). "
            f"Import error: {exc}"
        ) from exc
    return _forecast


def compute(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run the screening model for one scenario. Raises ValueError on bad inputs."""
    return _adapter().run_forecast(scenario or {})


def template() -> dict[str, Any]:
    """The model's starter scenario (visible Excel-style labels)."""
    return _adapter().default_scenario()
