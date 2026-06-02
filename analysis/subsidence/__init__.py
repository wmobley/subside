"""SUBSIDE forecast (potential subsidence) screening model.

Wraps the vendored Texas Aquifer Potential Subsidence Prediction Screening Tool
(``model.py``) behind a small JSON-in/JSON-out adapter (``forecast.py``) used by
the API's synchronous ``/forecast`` endpoint.
"""

from .forecast import default_scenario, run_forecast

__all__ = ["run_forecast", "default_scenario"]
