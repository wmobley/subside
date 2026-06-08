#!/usr/bin/env python3
# VENDORED — do not edit here. This is a verbatim copy of
# subsidence_pandas_user_inputs_package/subsidence_pandas.py, vendored into the
# subside repo so the API can import it without depending on a path outside the
# repo. To refresh: re-copy the upstream file and keep this header.
# Entry points the API uses: unwrap_input_record, coerce_inputs, run_prediction,
# risk_scores, write_template, SubsidenceInputs.
"""
Pandas-based visible-user-input version of the Texas Aquifer Potential Subsidence
Prediction Screening Tool.

This version treats the workbook visible blue/gray fields as USER INPUTS.
Input templates use the same human-readable labels shown in the Excel sheet.
Calculated/intermediate quantities are not required as inputs.

Input options
-------------
1) JSON file with one scenario object
2) CSV file with one or more scenario rows
3) Use --write-template to create a starter JSON input file

Example
-------
python subsidence_pandas_user_inputs.py --inputs pecos_417430_example.json \
  --out prediction.csv --diagnostics-out diagnostics.csv

python subsidence_pandas_user_inputs.py --inputs scenarios.csv --out predictions.csv
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

FT_TO_M = 0.3048
M_TO_FT = 1.0 / FT_TO_M
PA_PER_PSI = 6894.757293168361
GRAVITY = 9.81
DEFAULT_ROCK_DENSITY = 2671.0  # kg/m^3 from the workbook VBA
DEFAULT_UNSAT_RETENTION = 0.25


def ft_to_m(x: float) -> float:
    return float(x) * FT_TO_M


def m_to_ft(x: float) -> float:
    return float(x) * M_TO_FT


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if value == "":
                return default
        out = float(value)
        if np.isnan(out):
            return default
        return out
    except Exception:
        return default


def safe_int(value: Any, default: int) -> int:
    try:
        out = safe_float(value, float(default))
        if np.isnan(out):
            return default
        return int(round(out))
    except Exception:
        return default


def clean_key(key: str) -> str:
    """Normalize labels from the Excel UI into stable snake_case-ish keys."""
    out = str(key).strip().lower()
    replacements = {
        "feet msl": "ft_msl",
        "feet mean sea level": "ft_msl",
        "ft msl": "ft_msl",
        "degrees celsius": "c",
        "milligrams per liter": "mg_l",
        "mg/l": "mg_l",
        "tds": "tds",
        "psi-1": "psi_inv",
        "psi^-1": "psi_inv",
        "foot-1": "ft_inv",
        "ft-1": "ft_inv",
        "%": "pct",
        "-": "_",
        "/": "_",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
    }
    for a, b in replacements.items():
        out = out.replace(a, b)
    out = "_".join(out.replace(".", " ").replace("__", "_").split())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


# Accept both Python-friendly keys and labels copied from the spreadsheet UI.
ALIASES = {
    "scenario_id": "scenario_id",
    "scenario": "scenario_id",
    "aquifer": "aquifer",
    "report_generated_by": "report_generated_by",
    "report_date": "report_date",
    "well_name": "well_name",
    "water_levels_to_use_for_predictions": "water_level_method",
    "water_level_method": "water_level_method",
    "land_surface_ft_msl": "land_surface_ft_msl",
    "aquifer_top_ft_msl": "aquifer_top_ft_msl",
    "aquifer_thickness": "aquifer_thickness_ft",
    "aquifer_thickness_ft": "aquifer_thickness_ft",
    "clay_thickness_within_aquifer": "clay_thickness_ft",
    "clay_thickness_ft": "clay_thickness_ft",
    "groundwater_temperature": "groundwater_temp_c",
    "groundwater_temperature_c": "groundwater_temp_c",
    "groundwater_total_dissolved_solids_tds": "groundwater_tds_mg_l",
    "groundwater_tds_mg_l": "groundwater_tds_mg_l",
    "predevelopment_water_level_ft_msl": "predevelopment_water_level_ft_msl",
    "current_water_level_ft_msl": "current_water_level_ft_msl",
    "unsaturated_thickness": "unsat_thickness_ft",
    "unsaturated_thickness_ft": "unsat_thickness_ft",
    "preconsolidation_deepest_water_level_ft_msl": "preconsolidation_water_level_ft_msl",
    "preconsolidation_water_level_ft_msl": "preconsolidation_water_level_ft_msl",
    "base_water_level_ft_msl": "base_water_level_ft_msl",
    "future_water_level_ft_msl": "future_water_level_ft_msl",
    "beginning_year_for_subsidence_evaluation": "start_year",
    "ending_year_for_subsidence_evaluation": "end_year",
    "water_level_trend": "water_level_trend_ft_per_year",
    "water_level_trend_ft_per_year": "water_level_trend_ft_per_year",
    "predominant_aquifer_lithology": "aquifer_lithology",
    "aquifer_lithology": "aquifer_lithology",
    "aquifer_storage_coefficient": "aquifer_storage_coefficient",
    "aquifer_porosity": "aquifer_porosity_pct",
    "aquifer_porosity_pct": "aquifer_porosity_pct",
    "predominant_aquifer_clay_type": "clay_type",
    "clay_type": "clay_type",
    "aquifer_clay_porosity": "clay_porosity_pct",
    "clay_porosity_pct": "clay_porosity_pct",
    "minimum_aquifer_compressibility": "aq_comp_min_psi_inv",
    "minimum_aquifer_compressibility_psi_inv": "aq_comp_min_psi_inv",
    "maximum_aquifer_compressibility": "aq_comp_max_psi_inv",
    "maximum_aquifer_compressibility_psi_inv": "aq_comp_max_psi_inv",
    "minimum_clay_compressibility": "clay_comp_min_psi_inv",
    "minimum_clay_compressibility_psi_inv": "clay_comp_min_psi_inv",
    "maximum_clay_compressibility": "clay_comp_max_psi_inv",
    "maximum_clay_compressibility_psi_inv": "clay_comp_max_psi_inv",
}


@dataclass
class SubsidenceInputs:
    # Header / descriptive fields from the UI
    scenario_id: str = ""
    aquifer: str = "General Calculation"
    report_generated_by: str = "User"
    report_date: str = ""
    well_name: str = "Well"
    water_level_method: str = "Current and Trend"  # or "Base and Future"

    # Location and water-level user inputs
    land_surface_ft_msl: float = np.nan
    aquifer_top_ft_msl: float = np.nan
    aquifer_thickness_ft: float = np.nan
    clay_thickness_ft: float = np.nan
    groundwater_temp_c: float = np.nan
    groundwater_tds_mg_l: float = np.nan
    predevelopment_water_level_ft_msl: float = np.nan
    current_water_level_ft_msl: float = np.nan
    unsat_thickness_ft: float = np.nan
    preconsolidation_water_level_ft_msl: float = np.nan
    base_water_level_ft_msl: float = np.nan
    future_water_level_ft_msl: float = np.nan
    start_year: int = 2010
    end_year: int = 2070

    # Aquifer-property user inputs
    water_level_trend_ft_per_year: float = 0.0
    aquifer_lithology: str = "Unconsolidated Clastic"
    aquifer_storage_coefficient: float = 0.15
    aquifer_porosity_pct: float = 35.0
    clay_type: str = "Plastic Clay"
    clay_porosity_pct: float = 50.0
    aq_comp_min_psi_inv: float = 5.2e-8
    aq_comp_max_psi_inv: float = 1.0e-7
    clay_comp_min_psi_inv: float = 2.6e-7
    clay_comp_max_psi_inv: float = 2.0e-6

    @property
    def aquifer_base_ft_msl(self) -> float:
        return self.aquifer_top_ft_msl - self.aquifer_thickness_ft

    @property
    def sand_thickness_ft(self) -> float:
        return max(self.aquifer_thickness_ft - self.clay_thickness_ft, 0.0)

    @property
    def method_key(self) -> str:
        key = clean_key(self.water_level_method)
        if "base" in key and "future" in key:
            return "base_and_future"
        return "current_and_trend"

    def starting_water_level_ft_msl(self) -> float:
        return self.base_water_level_ft_msl if self.method_key == "base_and_future" else self.current_water_level_ft_msl

    def predicted_water_level(self, year: int) -> float:
        if self.method_key == "base_and_future":
            years = max(self.end_year - self.start_year, 1)
            frac = (year - self.start_year) / years
            wl = self.base_water_level_ft_msl + frac * (self.future_water_level_ft_msl - self.base_water_level_ft_msl)
        else:
            wl = self.current_water_level_ft_msl + (year - self.start_year) * self.water_level_trend_ft_per_year
        return max(wl, self.aquifer_base_ft_msl)


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        k0 = str(key).strip()
        k1 = clean_key(k0)
        canonical = ALIASES.get(k0, ALIASES.get(k1, k1))
        out[canonical] = value
    return out


def coerce_inputs(record: dict[str, Any]) -> SubsidenceInputs:
    record = normalize_record(record)
    valid = {f.name: f for f in fields(SubsidenceInputs)}
    kwargs: dict[str, Any] = {}
    for name, f in valid.items():
        if name not in record:
            continue
        val = record[name]
        default_value = getattr(SubsidenceInputs(), name)
        if isinstance(default_value, float):
            kwargs[name] = safe_float(val)
        elif isinstance(default_value, int):
            kwargs[name] = safe_int(val, default_value)
        else:
            kwargs[name] = "" if val is None else str(val)
    inputs = SubsidenceInputs(**kwargs)
    validate_inputs(inputs)
    return inputs


def validate_inputs(inputs: SubsidenceInputs) -> None:
    required = [
        "land_surface_ft_msl", "aquifer_top_ft_msl", "aquifer_thickness_ft",
        "clay_thickness_ft", "groundwater_temp_c", "groundwater_tds_mg_l",
        "current_water_level_ft_msl", "unsat_thickness_ft",
        "preconsolidation_water_level_ft_msl", "base_water_level_ft_msl",
        "future_water_level_ft_msl", "aquifer_porosity_pct", "clay_porosity_pct",
        "aq_comp_min_psi_inv", "aq_comp_max_psi_inv", "clay_comp_min_psi_inv",
        "clay_comp_max_psi_inv",
    ]
    missing = [name for name in required if np.isnan(safe_float(getattr(inputs, name)))]
    if missing:
        raise ValueError("Missing required numeric inputs: " + ", ".join(missing))
    if inputs.end_year < inputs.start_year:
        raise ValueError("end_year must be greater than or equal to start_year")
    for name in ["aquifer_porosity_pct", "clay_porosity_pct"]:
        v = getattr(inputs, name)
        if not (0 <= v <= 100):
            raise ValueError(f"{name} should be entered as percent between 0 and 100, e.g. 35 not 0.35")


def unwrap_input_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Accept either a plain input object or the JSON fixture shape:

        {
          "scenario_id": "HS-01",
          "purpose": "...",
          "inputs": { ... },
          "expected": { ... }
        }

    The model only needs the visible Excel-style inputs. Expected outputs and
    other fixture metadata are ignored, except scenario_id is preserved for
    labeling outputs.
    """
    if not isinstance(record, dict):
        raise ValueError("Each scenario record must be a JSON object.")

    if isinstance(record.get("inputs"), dict):
        out = dict(record["inputs"])
        if "scenario_id" in record and "scenario_id" not in out and "Scenario ID" not in out:
            out["scenario_id"] = record["scenario_id"]
        return out

    return record


def load_input_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "scenarios" in data:
            data = data["scenarios"]
        if isinstance(data, dict):
            return [unwrap_input_record(data)]
        if isinstance(data, list):
            return [unwrap_input_record(x) for x in data]
        raise ValueError("JSON input must be an object, a list of objects, or {'scenarios': [...]}." )
    if suffix in [".csv", ".tsv"]:
        sep = "\t" if suffix == ".tsv" else ","
        return pd.read_csv(path, sep=sep).to_dict(orient="records")
    raise ValueError("Input file must be .json, .csv, or .tsv")


def water_density_kg_m3(temp_c: float, tds_mg_l: float, water_level_ft_msl: float,
                        aquifer_top_ft_msl: float, aquifer_thickness_ft: float) -> float:
    """VBA port of brine/freshwater density approximation used by the workbook."""
    s = tds_mg_l / 1000.0
    pressure_like = (water_level_ft_msl - aquifer_top_ft_msl + aquifer_thickness_ft) * 0.029847446
    numerator = (
        999.842594
        + 0.06793952 * temp_c
        - 0.00909529 * temp_c**2
        + 0.0001001685 * temp_c**3
        - 0.000001120083 * temp_c**4
        + 0.000000006536332 * temp_c**5
        + s * (0.824493 - 0.0040899 * temp_c + 0.000076438 * temp_c**2 - 0.00000082467 * temp_c**3 + 0.0000000053875 * temp_c**4)
        + s**1.5 * (-0.00572466 + 0.00010227 * temp_c - 0.0000016546 * temp_c**2)
        + 0.00048314 * s**2
    )
    denominator_inner = (
        19652.21
        + 148.4206 * temp_c
        - 2.327105 * temp_c**2
        + 0.01360477 * temp_c**3
        - 0.00005155288 * temp_c**4
        + s * (54.6476 - 0.603459 * temp_c + 0.0109987 * temp_c**2 - 0.00006167 * temp_c**3)
        + s**1.5 * (0.07944 + 0.016483 * temp_c - 0.00053009 * temp_c**2)
        + pressure_like * (3.239908 + 0.00143713 * temp_c + 0.000116092 * temp_c**2 - 0.000000577905 * temp_c**3)
        + pressure_like * s * (0.0022838 - 0.000010981 * temp_c - 0.0000016078 * temp_c**2)
        + 0.000191075 * pressure_like * s**1.5
        + pressure_like**2 * (0.0000850935 - 0.00000612293 * temp_c + 0.000000052787 * temp_c**2)
        + pressure_like**2 * s * (-0.00000099348 + 0.000000020816 * temp_c + 0.00000000091697 * temp_c**2)
    )
    return numerator / (1 - pressure_like / denominator_inner)


def groundwater_compressibility_pa_inv(temp_c: float) -> float:
    return (
        5.088496e-10
        + 6.163813e-12 * temp_c
        + 1.459187e-14 * temp_c**2
        + 2.008438e-16 * temp_c**3
        - 5.847727e-19 * temp_c**4
        + 4.10411e-21 * temp_c**5
    ) / (1 + 0.01967348 * temp_c)


def sig_trend(swl: float, pred_wl: float, unsat_b: float, ls: float, aq_top: float,
              aq_b: float, aq_por: float, water_density: float,
              rock_density: float = DEFAULT_ROCK_DENSITY,
              unsat_retention: float = DEFAULT_UNSAT_RETENTION) -> float:
    depth_to_base = ls - (aq_top - aq_b)
    depth_to_water = ls - pred_wl
    por = aq_por / 100.0
    if pred_wl < aq_top - aq_b:
        m = ft_to_m(depth_to_base)
        result = m * ((rock_density * GRAVITY) * (1 - por) + (por * unsat_retention) * (water_density * GRAVITY))
    elif pred_wl < aq_top:
        m = ft_to_m(depth_to_water)
        result = m * ((rock_density * GRAVITY) * (1 - por) + (por * unsat_retention) * (water_density * GRAVITY))
        m = ft_to_m(aq_b - ls + pred_wl)
        result += m * ((rock_density * GRAVITY) - por * (rock_density * GRAVITY - water_density * GRAVITY))
    else:
        m = ft_to_m(unsat_b)
        result = m * ((rock_density * GRAVITY) * (1 - por) + (por * unsat_retention) * (water_density * GRAVITY))
        m = ft_to_m(ls - unsat_b - aq_top + aq_b)
        result += m * ((rock_density * GRAVITY) - por * (rock_density * GRAVITY - water_density * GRAVITY))
    return result


def u_trend(swl: float, pred_wl: float, ls: float, aq_top: float,
            aq_b: float, water_density: float) -> float:
    depth_to_base = ls - (aq_top - aq_b)
    if pred_wl < aq_top - aq_b:
        result = ft_to_m(aq_b - depth_to_base) * water_density * GRAVITY
    elif pred_wl < aq_top:
        result = ft_to_m(aq_b - ls + pred_wl) * water_density * GRAVITY
    else:
        result = ft_to_m(pred_wl - aq_top + aq_b) * water_density * GRAVITY
    return result


def sig_prm_trend(swl: float, pred_wl: float, unsat_b: float, ls: float, aq_top: float,
                  aq_b: float, aq_por: float, water_density: float) -> float:
    return sig_trend(swl, pred_wl, unsat_b, ls, aq_top, aq_b, aq_por, water_density) - u_trend(swl, pred_wl, ls, aq_top, aq_b, water_density)


def specific_storage_ft_inv(inputs: SubsidenceInputs, density: float, gw_comp: float, use_max: bool) -> float:
    aq_comp_psi_inv = inputs.aq_comp_max_psi_inv if use_max else inputs.aq_comp_min_psi_inv
    clay_comp_psi_inv = inputs.clay_comp_max_psi_inv if use_max else inputs.clay_comp_min_psi_inv
    aq_comp_pa_inv = aq_comp_psi_inv / PA_PER_PSI
    clay_comp_pa_inv = clay_comp_psi_inv / PA_PER_PSI
    aq_b = inputs.aquifer_thickness_ft
    sand_b = inputs.sand_thickness_ft
    clay_b = inputs.clay_thickness_ft
    depth_to_base = inputs.land_surface_ft_msl - inputs.aquifer_top_ft_msl + inputs.aquifer_thickness_ft
    depth_factor = 10 ** ((0 if depth_to_base < 250 else 250 - depth_to_base) / 4000.0)
    sand_term_ft_inv = density * GRAVITY * ((inputs.aquifer_porosity_pct / 100.0) * gw_comp + aq_comp_pa_inv) * FT_TO_M
    clay_term_ft_inv = density * GRAVITY * ((inputs.clay_porosity_pct / 100.0) * gw_comp + clay_comp_pa_inv) * FT_TO_M
    weighted = (sand_b / aq_b) * sand_term_ft_inv + (clay_b / aq_b) * clay_term_ft_inv
    return 0.00990099 * max(depth_factor * weighted, 1.3e-8)


def compression_indices(inputs: SubsidenceInputs, density: float, sig_current: float,
                        sske_min: float, sske_max: float) -> dict[str, float]:
    sskv_min = sske_min * 100.0
    sskv_max = sske_max * 100.0
    clay_por = inputs.clay_porosity_pct / 100.0

    def cc(ssk: float) -> float:
        return (sig_current * (1 - clay_por) * (ssk / FT_TO_M)) / (0.434 * density * GRAVITY)

    return {
        "Sske_min_ft_inv": sske_min,
        "Sske_max_ft_inv": sske_max,
        "Sskv_min_ft_inv": sskv_min,
        "Sskv_max_ft_inv": sskv_max,
        "Cc_min": cc(sskv_min),
        "Cc_max": cc(sskv_max),
        "Cr_min": cc(sske_min),
        "Cr_max": cc(sske_max),
    }


def subsidence_ft(clay_thickness_ft: float, clay_porosity_pct: float, sig_initial: float,
                  sig_precon: float, sig_final: float, cc: float, cr: float) -> float:
    if any(np.isnan(x) for x in [clay_thickness_ft, clay_porosity_pct, sig_initial, sig_precon, sig_final, cc, cr]):
        return np.nan
    if sig_initial == 0:
        return np.nan
    clay_b_m = ft_to_m(clay_thickness_ft)
    e0 = clay_porosity_pct / 100.0
    comp = cc if sig_final > sig_precon else cr
    settlement_m = (0.434 * clay_b_m) / ((1 + e0) * sig_initial) * (
        comp * (sig_final - sig_precon) + cr * (sig_precon - sig_initial)
    )
    return max(m_to_ft(settlement_m), 0.0)


def risk_scores(inputs: SubsidenceInputs) -> dict[str, float]:
    lith = {"Unconsolidated Clastic": 4, "Consolidated Clastic": 3, "Carbonate": 2, "Igneous": 1}.get(inputs.aquifer_lithology, np.nan)
    clay_b = inputs.clay_thickness_ft
    cl_b_risk = 1 if clay_b <= 0 else 2 if clay_b <= 100 else 3 if clay_b <= 200 else 4 if clay_b <= 300 else 5
    clay_comp = {"Plastic Clay": 3, "Stiff Clay": 2, "Hard Clay": 1}.get(inputs.clay_type, np.nan) if clay_b > 0 else 1
    pc = 1 if inputs.current_water_level_ft_msl > inputs.preconsolidation_water_level_ft_msl + 50 else 2 if inputs.current_water_level_ft_msl >= inputs.preconsolidation_water_level_ft_msl + 25 else 3
    wl50 = -inputs.water_level_trend_ft_per_year * 50
    wlm = 1 if wl50 <= 0 else 2 if wl50 <= 50 else 3 if wl50 <= 100 else 4 if wl50 <= 200 else 5
    decline = inputs.base_water_level_ft_msl - inputs.future_water_level_ft_msl
    dfc = 1 if decline <= 0 else 2 if decline <= 50 else 3 if decline <= 100 else 4 if decline <= 200 else 5
    total = np.nanmean([lith, cl_b_risk, clay_comp, pc, wlm, dfc]) * 2.0
    return {
        "lithology_risk": lith,
        "clay_thickness_risk": cl_b_risk,
        "clay_compressibility_risk": clay_comp,
        "preconsolidation_risk": pc,
        "water_level_trend_risk": wlm,
        "future_decline_risk": dfc,
        "weighted_risk_0_to_10_approx": total,
    }


def run_prediction(inputs: SubsidenceInputs, custom_water_levels: Optional[pd.DataFrame] = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    density = water_density_kg_m3(
        inputs.groundwater_temp_c,
        inputs.groundwater_tds_mg_l,
        inputs.current_water_level_ft_msl,
        inputs.aquifer_top_ft_msl,
        inputs.aquifer_thickness_ft,
    )
    gw_comp = groundwater_compressibility_pa_inv(inputs.groundwater_temp_c)
    sig_current = sig_prm_trend(inputs.current_water_level_ft_msl, inputs.current_water_level_ft_msl, inputs.unsat_thickness_ft,
                                inputs.land_surface_ft_msl, inputs.aquifer_top_ft_msl, inputs.aquifer_thickness_ft,
                                inputs.aquifer_porosity_pct, density)
    sig_precon = sig_prm_trend(inputs.current_water_level_ft_msl, inputs.preconsolidation_water_level_ft_msl, inputs.unsat_thickness_ft,
                               inputs.land_surface_ft_msl, inputs.aquifer_top_ft_msl, inputs.aquifer_thickness_ft,
                               inputs.aquifer_porosity_pct, density)
    sske_min = specific_storage_ft_inv(inputs, density, gw_comp, use_max=False)
    sske_max = specific_storage_ft_inv(inputs, density, gw_comp, use_max=True)
    coeffs = compression_indices(inputs, density, sig_current, sske_min, sske_max)

    custom_map: dict[int, float] = {}
    if custom_water_levels is not None:
        cols = {clean_key(c): c for c in custom_water_levels.columns}
        ycol = cols.get("year")
        wlcol = cols.get("water_level_ft_msl") or cols.get("predicted_water_level_ft_msl") or cols.get("water_level_ft")
        if ycol and wlcol:
            for _, row in custom_water_levels.iterrows():
                custom_map[int(row[ycol])] = safe_float(row[wlcol])

    start_wl = inputs.starting_water_level_ft_msl()
    years = np.arange(inputs.start_year, inputs.end_year + 1)
    rows = []
    prev_min = prev_max = 0.0
    previous_wl = None
    for year in years:
        wl = custom_map.get(int(year), inputs.predicted_water_level(int(year)))
        wl = max(wl, inputs.aquifer_base_ft_msl)
        sig_final = sig_prm_trend(inputs.current_water_level_ft_msl, wl, inputs.unsat_thickness_ft,
                                  inputs.land_surface_ft_msl, inputs.aquifer_top_ft_msl, inputs.aquifer_thickness_ft,
                                  inputs.aquifer_porosity_pct, density)
        sub_min = subsidence_ft(inputs.clay_thickness_ft, inputs.clay_porosity_pct, sig_current, sig_precon, sig_final, coeffs["Cc_min"], coeffs["Cr_min"])
        sub_max = subsidence_ft(inputs.clay_thickness_ft, inputs.clay_porosity_pct, sig_current, sig_precon, sig_final, coeffs["Cc_max"], coeffs["Cr_max"])
        # Excel behavior approximated: if water levels continue declining, subsidence does not decrease.
        if previous_wl is not None and wl < previous_wl:
            sub_min = max(sub_min, prev_min)
            sub_max = max(sub_max, prev_max)
        prev_min, prev_max, previous_wl = sub_min, sub_max, wl
        rows.append({
            "scenario": inputs.scenario_id or inputs.well_name or inputs.aquifer,
            "aquifer": inputs.aquifer,
            "water_level_method": inputs.water_level_method,
            "year": int(year),
            "predicted_water_level_ft_msl": wl,
            "drawdown_from_start_ft": start_wl - wl,
            "effective_stress_pa": sig_final,
            "subsidence_min_ft": sub_min,
            "subsidence_max_ft": sub_max,
        })

    diagnostics = {
        **asdict(inputs),
        "water_density_kg_m3": density,
        "groundwater_compressibility_pa_inv": gw_comp,
        "sig_prm_current_pa": sig_current,
        "sig_prm_preconsolidation_pa": sig_precon,
        **coeffs,
        **risk_scores(inputs),
    }
    return pd.DataFrame(rows), diagnostics


def write_template(path: Path) -> None:
    """Write an input file using the same labels visible in the Excel workbook."""
    template = {
        "Aquifer": "Pecos Valley",
        "Report Generated by": "User",
        "Report Date": "3/13/18",
        "Well Name": "Well",
        "Water Levels to Use for Predictions": "Current and Trend",

        "Land Surface (feet MSL)": 2470,
        "Aquifer Top (feet MSL)": 2470,
        "Aquifer Thickness": 331,
        "Clay Thickness within Aquifer": 135,
        "Groundwater Temperature": 20,
        "Groundwater Total Dissolved Solids (TDS)": 1095,
        "Predevelopment Water Level (feet MSL)": 2474,
        "Current Water Level (feet MSL)": 2467,
        "Unsaturated Thickness": 42,
        "Preconsolidation (deepest) Water Level (feet MSL)": 2467,
        "Base Water Level (feet MSL)": 2474,
        "Future Water Level (feet MSL)": 2462,
        "Beginning Year for Subsidence Evaluation": 2010,
        "Ending Year for Subsidence Evaluation": 2070,

        "Water Level Trend": -1.0,
        "Predominant Aquifer Lithology": "Unconsolidated Clastic",
        "Aquifer Storage Coefficient": 9.99999999998936e-05,
        "Aquifer Porosity": 35,
        "Predominant Aquifer Clay Type": "Plastic Clay",
        "Aquifer Clay Porosity": 50,
        "Minimum Aquifer Compressibility": 5.2e-08,
        "Maximum Aquifer Compressibility": 1.0e-07,
        "Minimum Clay Compressibility": 2.6e-07,
        "Maximum Clay Compressibility": 2.0e-06,
    }
    path.write_text(json.dumps(template, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the subsidence model from visible Excel-style user inputs.")
    parser.add_argument("--inputs", type=Path, help="JSON/CSV/TSV file containing visible user inputs")
    parser.add_argument("--custom-water-levels", type=Path, default=None, help="Optional CSV with columns year, water_level_ft_msl to override annual predicted water levels")
    parser.add_argument("--out", type=Path, default=Path("subsidence_prediction.csv"), help="Annual water-level/drawdown/subsidence prediction table")
    parser.add_argument("--calculated-out", type=Path, default=Path("subsidence_calculated_outputs.csv"), help="Workbook-style calculated outputs such as specific storage and weighted risk")
    parser.add_argument("--debug-out", type=Path, default=None, help="Optional verbose debug/intermediate calculations")
    parser.add_argument("--write-template", type=Path, default=None, help="Write an Excel-label JSON template and exit")
    args = parser.parse_args()

    if args.write_template:
        write_template(args.write_template)
        print(f"Wrote template to {args.write_template}")
        return
    if args.inputs is None:
        parser.error("Either --inputs or --write-template is required")

    custom_df = pd.read_csv(args.custom_water_levels) if args.custom_water_levels else None
    records = load_input_records(args.inputs)
    all_predictions = []
    all_debug = []
    all_calculated = []
    calculated_cols = [
        "scenario_index", "scenario_id", "aquifer", "well_name",
        "Sske_min_ft_inv", "Sske_max_ft_inv", "Sskv_min_ft_inv", "Sskv_max_ft_inv",
        "lithology_risk", "clay_thickness_risk", "clay_compressibility_risk",
        "preconsolidation_risk", "water_level_trend_risk", "future_decline_risk",
        "weighted_risk_0_to_10_approx",
    ]
    for i, record in enumerate(records, start=1):
        inputs = coerce_inputs(record)
        pred, diag = run_prediction(inputs, custom_df if len(records) == 1 else None)
        pred.insert(0, "scenario_index", i)
        all_predictions.append(pred)
        debug_row = {"scenario_index": i, **diag}
        all_debug.append(debug_row)
        all_calculated.append({k: debug_row.get(k) for k in calculated_cols})

    predictions = pd.concat(all_predictions, ignore_index=True)
    calculated = pd.DataFrame(all_calculated)
    predictions.to_csv(args.out, index=False)
    calculated.to_csv(args.calculated_out, index=False)
    if args.debug_out:
        pd.DataFrame(all_debug).to_csv(args.debug_out, index=False)
    print(f"Wrote {args.out}")
    print(f"Wrote {args.calculated_out}")
    if args.debug_out:
        print(f"Wrote {args.debug_out}")
    print(predictions.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
