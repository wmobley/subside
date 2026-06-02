# analysis.subsidence — potential-subsidence forecast

A thin, synchronous wrapper around the **Texas Aquifer Potential Subsidence
Prediction Screening Tool**. Given aquifer/water-level inputs it returns an
annual subsidence projection and a **0–10 weighted risk score**. This powers the
Risk Explorer's *Potential* (forecast) card via the API's `/forecast` endpoint —
it runs in-process (sub-second), so there is **no Tapis job** for this model.

## Files

- `model.py` — **vendored, do not edit.** A verbatim copy of
  `subsidence_pandas_user_inputs_package/subsidence_pandas.py`. To refresh:
  ```bash
  cp ../../../subsidence_pandas_user_inputs_package/subsidence_pandas.py \
     analysis/subsidence/model.py
  ```
  then re-add the `VENDORED` header comment at the top.
- `forecast.py` — the adapter. `run_forecast(scenario)` → JSON-safe summary;
  `default_scenario()` → the model's starter scenario (visible Excel labels).

## Inputs

`run_forecast` accepts any of: the visible-label object, snake_case keys, or the
`{"inputs": {...}}` fixture shape. Unspecified fields fall back to the model
defaults; the model validates that the required numeric fields are present and
raises `ValueError` otherwise (the API maps that to HTTP 400).

## Dependencies

`numpy` and `pandas` only. The API serves `/forecast` when these are importable
and returns HTTP 503 otherwise (same graceful-degradation pattern as the PostGIS
layer endpoints). They are present in the `subside-h2i-opera` conda env used to
run the API.

## Verified against

`subsidence_validation_json_tests/per_scenario/HS-01.json` — risk 8.0, final
(2080) subsidence 7.19–49.50 ft, matching the fixture's expected values.
