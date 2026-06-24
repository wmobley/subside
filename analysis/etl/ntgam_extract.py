"""NTGAM -> subsidence-forecast input ETL.

Extracts the spatially-derivable subsidence-forecast inputs for a well location
from the Northern Trinity / Woodbine GAM (v3.01) **without running MODFLOW**:

  * land surface           <- MODFLOW 6 DIS `top` array (inline)
  * layer thickness/geometry <- per-layer `thk` on the head point feature classes
  * water-level history (3 simulated snapshots ~1939/1979/2019) <- head rasters
  * storage coefficient    <- geodatabase ntgam_storativity point feature class

The head rasters/points are pre-extracted simulated heads shipped in the GAM
geodatabase, so no MODFLOW execution is needed for a first-cut forecast.

NOTE: the distributed `Bot*.ref` bottom-elevation arrays are ragged (token count
!= NROW*NCOL), so flopy cannot load the grid. We therefore avoid flopy and
reconstruct every layer top/bottom from `top` minus cumulative `thk`.

Compressibility / lithology / porosity / temperature / TDS are NOT in the GAM
and remain external lookups (sensible defaults applied here).

Usage:
    python ntgam_extract.py --lon -97.32 --lat 32.75 --aquifer-layer 4
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer

LAYERS = {1: "Outcrop", 2: "Woodbine", 3: "WashitaFredericksburg", 4: "Paluxy",
          5: "GlenRose", 6: "Hensell", 7: "Pearsall", 8: "Hosston"}
DEFAULT_CLAY_LAYER = 5  # Glen Rose marl/shale = the confining "clay"
SP_YEAR = {52: 1939, 92: 1979, 132: 2019}  # TDIS start 1888-12-31, annual periods


def _head_raster(geodb: Path, layer: int, sp: int) -> Path:
    return geodb / "Rasters" / "SubSurfaceHydroHydraulics" / "waterlevels" / f"hds_lyr{layer}_sp{sp}.tif"


def _head_points(geodb: Path, layer: int, sp: int) -> Path:
    return geodb / "Shapefiles" / "SubSurfaceHydroWaterLevels" / "point_files" / f"hds_lyr{layer}_sp{sp}.shp"


def parse_dis_top(model_ws: Path) -> np.ndarray:
    """Parse the inline DIS `top` array -> (nrow, ncol) land-surface elevations."""
    text = (model_ws / "ntgam.dis").read_text()
    nrow = int(re.search(r"NROW\s+(\d+)", text, re.I).group(1))
    ncol = int(re.search(r"NCOL\s+(\d+)", text, re.I).group(1))
    lines = text.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.strip().lower() == "top")
    i += 1
    if "INTERNAL" in lines[i].upper():
        i += 1
    vals: list[float] = []
    need = nrow * ncol
    while len(vals) < need and i < len(lines):
        toks = lines[i].split()
        if toks and re.match(r"^[-+0-9.eE]", toks[0]):
            vals.extend(float(t) for t in toks)
            i += 1
        else:
            break
    return np.array(vals[:need]).reshape(nrow, ncol)


def _bbox(x: float, y: float, pad: float = 2000.0) -> tuple[float, float, float, float]:
    return (x - pad, y - pad, x + pad, y + pad)


def cell_and_thickness(geodb: Path, x: float, y: float) -> tuple[int, int, dict[int, float]]:
    """Nearest active model cell to (x,y); thickness per layer at that cell."""
    bbox = _bbox(x, y)
    pt = gpd.points_from_xy([x], [y])[0]
    g1 = gpd.read_file(_head_points(geodb, 1, 132), bbox=bbox)
    if g1.empty:
        raise SystemExit("No head points near the well — is the location inside the model domain?")
    nearest = g1.iloc[int(g1.geometry.distance(pt).values.argmin())]
    row, col = int(nearest["row"]), int(nearest["col"])
    thk: dict[int, float] = {}
    for layer in LAYERS:
        g = gpd.read_file(_head_points(geodb, layer, 132), bbox=bbox)
        sel = g[(g["row"] == row) & (g["col"] == col)]
        thk[layer] = float(sel.iloc[0][f"thk_{layer}"]) if not sel.empty else float("nan")
    return row, col, thk


def sample_heads(geodb: Path, x: float, y: float, layer: int) -> dict[int, float]:
    """heads[year] = simulated head (ft MSL) for `layer`, NaN if NoData."""
    out: dict[int, float] = {}
    for sp, year in SP_YEAR.items():
        tif = _head_raster(geodb, layer, sp)
        if not tif.exists():
            continue
        with rasterio.open(tif) as src:
            val = next(src.sample([(x, y)]))[0]
            nod = src.nodata
            out[year] = float("nan") if (nod is not None and val == nod) else float(val)
    return out


def storativity_at(geodb: Path, x: float, y: float, layer: int) -> float | None:
    gdb = geodb / "GAM_FileGeodatabase_v4.3.3.gdb"
    gdf = gpd.read_file(gdb, layer="ntgam_storativity", bbox=_bbox(x, y))
    if gdf.empty:
        return None
    sub = gdf[gdf["layer"] == layer] if "layer" in gdf.columns else gdf
    if sub.empty:
        sub = gdf
    d = sub.geometry.distance(gpd.points_from_xy([x], [y])[0])
    return float(sub.iloc[int(d.values.argmin())]["storativit"])


def extract(lon: float, lat: float, geodb: Path, model_ws: Path,
            aquifer_layer: int = 4, clay_layer: int = DEFAULT_CLAY_LAYER) -> dict:
    # 1. Reproject well lon/lat -> the GAM Albers CRS of the rasters.
    with rasterio.open(_head_raster(geodb, 1, 132)) as src:
        gam_crs = src.crs
    x, y = Transformer.from_crs("EPSG:4326", gam_crs, always_xy=True).transform(lon, lat)

    # 2. Cell + per-layer thickness (head points) and land surface (DIS top).
    row, col, thk = cell_and_thickness(geodb, x, y)
    top = parse_dis_top(model_ws)
    land_surface = float(top[row, col])

    # 3. Reconstruct layer tops/bottoms from land surface - cumulative thickness.
    # A pinched-out formation (no active cell here) reads NaN thickness -> treat as 0.
    tops, bots, cum = {}, {}, 0.0
    for layer in sorted(LAYERS):
        tops[layer] = land_surface - cum
        cum += 0.0 if np.isnan(thk[layer]) else thk[layer]
        bots[layer] = land_surface - cum
    aquifer_top = tops[aquifer_layer]
    aquifer_thickness = 0.0 if np.isnan(thk[aquifer_layer]) else thk[aquifer_layer]
    clay_thickness = 0.0 if np.isnan(thk[clay_layer]) else thk[clay_layer]

    # 4. Water-level history at the aquifer layer (3 snapshots).
    wl = {yr: v for yr, v in sorted(sample_heads(geodb, x, y, aquifer_layer).items()) if not np.isnan(v)}
    years = sorted(wl)
    current_wl, base_wl = wl[years[-1]], wl[years[0]]
    preconsolidation_wl = min(wl.values())
    span = years[-1] - years[0]
    trend = (wl[years[-1]] - wl[years[0]]) / span if span else 0.0

    # 5. Storage coefficient from the geodatabase.
    storativity = storativity_at(geodb, x, y, aquifer_layer)

    return {
        "scenario_id": f"NTGAM_{LAYERS[aquifer_layer]}_{lon:.3f}_{lat:.3f}",
        "aquifer": f"Trinity ({LAYERS[aquifer_layer]})",
        "well_name": f"NTGAM cell r{row} c{col}",
        "water_level_method": "Base and Future",
        "land_surface_ft_msl": round(land_surface, 2),
        "aquifer_top_ft_msl": round(aquifer_top, 2),
        "aquifer_thickness_ft": round(aquifer_thickness, 2),
        "clay_thickness_ft": round(clay_thickness, 2),
        "unsat_thickness_ft": round(land_surface - current_wl, 2),
        "current_water_level_ft_msl": round(current_wl, 2),
        "base_water_level_ft_msl": round(base_wl, 2),
        "future_water_level_ft_msl": round(current_wl, 2),
        "preconsolidation_water_level_ft_msl": round(preconsolidation_wl, 2),
        "water_level_trend_ft_per_year": round(trend, 4),
        "start_year": years[0],
        "end_year": years[-1],
        "aquifer_storage_coefficient": storativity,
        "aquifer_lithology": "Consolidated Clastic",
        "clay_type": "Stiff Clay",
        "_provenance": {
            "model_cell": {"row": row, "col": col},
            "water_level_years": years,
            "layer_thickness_ft": {LAYERS[l]: round(thk[l], 2) for l in thk},
            "from_gam": ["land_surface(DIS top)", "thickness(head points thk)",
                         "water_levels(head rasters)", "storage(gdb storativity)"],
            "from_lookup": ["lithology", "clay_type", "compressibility", "porosity", "temp", "tds"],
            "note": "3 head snapshots (~1939/1979/2019); annual series / true predevelopment "
                    "require a MODFLOW run. Layer bottoms reconstructed from top - cumulative thk "
                    "because distributed Bot*.ref arrays are ragged.",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="NTGAM -> subsidence-forecast input ETL")
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--aquifer-layer", type=int, default=4, help="DIS layer 1..8 (4=Paluxy)")
    ap.add_argument("--clay-layer", type=int, default=DEFAULT_CLAY_LAYER, help="confining layer (5=GlenRose)")
    ap.add_argument("--geodb", type=Path, default=Path("/Users/wmobley/Downloads/NTGAM_Geodatabase"))
    ap.add_argument("--model", type=Path,
                    default=Path("/Users/wmobley/Downloads/NTGAM_Final_model_2025/NTGAM_Feb_2025_all"))
    args = ap.parse_args()
    print(json.dumps(extract(args.lon, args.lat, args.geodb, args.model,
                             args.aquifer_layer, args.clay_layer), indent=2))


if __name__ == "__main__":
    main()
