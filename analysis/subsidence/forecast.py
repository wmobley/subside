"""JSON-in / JSON-out adapter over the vendored subsidence screening model.

The model (``model.py``) is a parametric aquifer calculation: ~24 scalar inputs
(aquifer geometry, water levels, compressibilities, evaluation years) produce an
annual subsidence projection plus a 0-10 weighted risk score. This adapter runs
it in-process and returns a compact, JSON-safe result for the Risk Explorer's
"Potential" card — no files, no Tapis job.

Inputs are forgiving: ``run_forecast`` accepts either the plain visible-label
object, the snake_case keys, or the ``{"inputs": {...}}`` fixture shape, and the
model fills unspecified fields from its defaults (``coerce_inputs`` then validates
that the required numeric fields are present).
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from . import model as _model

# The six named risk factors plus the combined 0-10 score, as produced by
# model.risk_scores() / merged into run_prediction diagnostics.
_RISK_FACTOR_KEYS = (
    "lithology_risk",
    "clay_thickness_risk",
    "clay_compressibility_risk",
    "preconsolidation_risk",
    "water_level_trend_risk",
    "future_decline_risk",
)


def _clean(value: Any) -> Any:
    """Make a value JSON-safe: NaN/inf -> None, numpy scalars -> python scalars."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return None
    except TypeError:
        pass
    item = getattr(value, "item", None)  # numpy scalar -> python scalar
    if callable(item):
        try:
            return _clean(item())
        except (ValueError, TypeError):
            return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def default_scenario() -> dict[str, Any]:
    """The model's visible-label starter scenario (same as ``--write-template``)."""
    import tempfile
    from pathlib import Path

    # write_template only knows how to write to a path; round-trip through a temp
    # file so we return exactly what the CLI template would contain.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "template.json"
        _model.write_template(path)
        import json

        return json.loads(path.read_text())


def run_forecast(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run the screening model for one scenario and return a JSON-safe summary.

    Args:
        scenario: visible-label or snake_case inputs, or a ``{"inputs": {...}}``
            fixture object. Missing fields fall back to the model defaults.

    Returns:
        dict with ``risk_score`` (0-10), ``risk_factors``, ``projection`` (final
        year + min/max subsidence in feet), ``annual`` (per-year series), and
        ``resolved_inputs`` (the inputs actually used, after defaults).

    Raises:
        ValueError: if required numeric inputs are missing or invalid (the model's
            own validation) — the API surfaces this as a 400.
    """
    record = _model.unwrap_input_record(scenario or {})
    inputs = _model.coerce_inputs(record)  # raises ValueError on missing/invalid
    predictions, diagnostics = _model.run_prediction(inputs)

    annual = [
        {
            "year": int(row["year"]),
            "predicted_water_level_ft_msl": _clean(row["predicted_water_level_ft_msl"]),
            "drawdown_from_start_ft": _clean(row["drawdown_from_start_ft"]),
            "subsidence_min_ft": _clean(row["subsidence_min_ft"]),
            "subsidence_max_ft": _clean(row["subsidence_max_ft"]),
        }
        for _, row in predictions.iterrows()
    ]
    final = annual[-1] if annual else {}

    return {
        "scenario_id": str(inputs.scenario_id or inputs.well_name or inputs.aquifer or ""),
        "aquifer": str(inputs.aquifer or ""),
        "water_level_method": str(inputs.water_level_method or ""),
        "risk_score": _clean(diagnostics.get("weighted_risk_0_to_10_approx")),
        "risk_factors": {k: _clean(diagnostics.get(k)) for k in _RISK_FACTOR_KEYS},
        "projection": {
            "start_year": int(inputs.start_year),
            "final_year": final.get("year"),
            "final_subsidence_min_ft": final.get("subsidence_min_ft"),
            "final_subsidence_max_ft": final.get("subsidence_max_ft"),
            "final_drawdown_ft": final.get("drawdown_from_start_ft"),
        },
        "annual": annual,
        "resolved_inputs": {k: _clean(v) for k, v in asdict(inputs).items()},
    }
