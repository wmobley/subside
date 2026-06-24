"""Publish NTGAM v3.01 data to CKAN (org: twdb-subside) with schema-correct metadata.

The CKAN `dataset` type on this instance is ckanext-scheming managed, so only
defined fields persist (free-form extras are dropped). We therefore map metadata
to the real schema fields and carry the SVO on each resource via the
`mint_standard_variables` field (the MINT standard-variable autocomplete).

One dataset, 26 resources:
  * 24 simulated hydraulic-head rasters (8 layers x 3 snapshots) -> COGs
  * 1 aquifer storativity layer (all model cells) -> GeoParquet
  * 1 MODFLOW 6 DIS geometry bundle (grid, land surface, layer bottoms) -> zip

Auth: a Tapis access-token JWT (password grant) used as the CKAN bearer token
(see tapis_ckan_auth). Set TAPIS_USERNAME / TAPIS_PASSWORD.

  Dry run:   python ntgam_publish.py --dry-run
  Publish:   TAPIS_USERNAME=... TAPIS_PASSWORD=... python ntgam_publish.py
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.shutil import copy as rio_copy
from rasterio.warp import transform_bounds

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "stac-platform"))
from stacmap.ckan import CkanClient  # noqa: E402

LAYERS = {1: "Outcrop", 2: "Woodbine", 3: "Washita-Fredericksburg", 4: "Paluxy",
          5: "Glen Rose", 6: "Hensell", 7: "Pearsall", 8: "Hosston"}
SP_YEAR = {52: 1939, 92: 1979, 132: 2019}
# MINT standard-variable names (domain__quantity form, per the mint_standard_variables field).
HEAD_VAR = "groundwater__hydraulic_head"
STORATIVITY_VAR = "aquifer__storativity"
LANDSURFACE_VAR = "land_surface__elevation"

CKAN_URL = "https://ckan.tacc.utexas.edu"
ORG = "twdb-subside"
DATASET_NAME = "ntgam-trinity-woodbine-v301"
ITEM_ID = DATASET_NAME
SOURCE_URL = "https://www.twdb.texas.gov/groundwater/models/gam/trnt_n/trnt_n.asp"
CRS_NAME = "GAM Albers Equal Area (NAD83, US survey feet)"


def _waterlevels_dir(geodb: Path) -> Path:
    return geodb / "Rasters" / "SubSurfaceHydroHydraulics" / "waterlevels"


def domain_geojson(geodb: Path) -> dict:
    with rasterio.open(_waterlevels_dir(geodb) / "hds_lyr1_sp132.tif") as s:
        w, sth, e, n = transform_bounds(s.crs, "EPSG:4326", *s.bounds)
    return {"type": "Polygon",
            "coordinates": [[[w, sth], [e, sth], [e, n], [w, n], [w, sth]]]}


def dataset_payload(spatial: dict) -> dict:
    notes = (
        "Data extracted from the calibrated Northern Trinity Aquifer & Woodbine "
        "Aquifer Groundwater Availability Model (GAM), version 3.01 — a MODFLOW 6 "
        "model developed by INTERA, Inc. for Groundwater Management Area 8 (Texas "
        "Water Development Board), released March 2026.\n\n"
        "Contents: simulated hydraulic heads for 8 model layers (Outcrop, Woodbine, "
        "Washita-Fredericksburg, Paluxy, Glen Rose, Hensell, Pearsall, Hosston) at 3 "
        "stress-period snapshots (~1939, 1979, 2019) as Cloud-Optimized GeoTIFFs in "
        "feet MSL; aquifer storativity per model cell (GeoParquet); and the MODFLOW 6 "
        "DIS geometry (grid, land surface, layer bottoms).\n\n"
        "Grid: 8 layers x 1124 rows x 1412 cols, 1320 ft cells, 65° rotation. "
        f"Spatial reference: {CRS_NAME}. Heads resampled to a 500-ft grid. "
        "Source: Texas Water Development Board."
    )
    return {
        "name": DATASET_NAME,
        "title": "Northern Trinity & Woodbine GAM v3.01 — Heads, Storage & Geometry",
        "notes": notes,
        "owner_org": ORG,
        "fields": {  # ckanext-scheming dataset fields (the ones that persist)
            "license_id": "other-pd",
            "url": SOURCE_URL,
            "version": "3.01",
            "author": "INTERA, Inc. for GMA 8 (Texas Water Development Board)",
            "temporal_coverage_start": "1939-01-01",
            "temporal_coverage_end": "2019-12-31",
            "spatial": json.dumps(spatial),
            "tag_string": ("groundwater,subsidence,modflow-6,trinity-aquifer,"
                           "woodbine-aquifer,gam,twdb,hydraulic-head,storativity,"
                           "dallas-fort-worth,gma-8"),
        },
    }


def _svo_decomposition(**parts: str) -> str:
    """Render the atomistic SVO decomposition (phenomenon/property/modifiers)."""
    order = ["phenomenon", "property", "process", "medium", "location", "temporal",
             "operation", "method", "unit", "aggregation"]
    bits = [f"{k}: {parts[k]}" for k in order if parts.get(k)]
    return "SVO decomposition — " + "; ".join(bits) + "."


def head_resources() -> list[dict]:
    res = []
    for layer in sorted(LAYERS):
        for sp in sorted(SP_YEAR):
            year, formation = SP_YEAR[sp], LAYERS[layer]
            decomp = _svo_decomposition(
                phenomenon="groundwater", property="hydraulic_head",
                medium=f"aquifer ({formation}, model layer {layer})",
                location="Northern Trinity/Woodbine GAM domain (DFW)",
                temporal=f"stress period {sp} (~{year})",
                operation="simulated state variable (no aggregation)",
                method="MODFLOW 6 (NTGAM v3.01), resampled to 500-ft grid",
                unit="ft (datum: feet above MSL)")
            res.append({
                "kind": "cog", "src_name": f"hds_lyr{layer}_sp{sp}.tif",
                "name": f"Hydraulic head — {formation} (layer {layer}) — {year}",
                "fmt": "GeoTIFF", "svo": HEAD_VAR,
                "description": (
                    f"Simulated hydraulic head in the {formation} (model layer {layer}), "
                    f"stress period {sp} (~{year}). Units: feet above mean sea level. "
                    f"CRS: {CRS_NAME}. Cloud-Optimized GeoTIFF resampled to a 500-ft grid. "
                    f"Source file: hds_lyr{layer}_sp{sp}.tif. {decomp}"
                ),
            })
    return res


def property_resources() -> list[dict]:
    storativity_decomp = _svo_decomposition(
        phenomenon="aquifer", property="storativity (storage coefficient)",
        medium="aquifer (all 8 model layers)",
        operation="intrinsic property (no aggregation)",
        method="calibrated MODFLOW 6 model parameter (NTGAM v3.01)",
        unit="dimensionless")
    landsurface_decomp = _svo_decomposition(
        phenomenon="land_surface", property="elevation",
        location="NTGAM model grid", operation="none",
        method="MODFLOW 6 DIS `top` array", unit="ft (datum: feet above MSL)")
    return [
        {"kind": "storativity", "name": "Aquifer storativity (per model cell, all layers)",
         "fmt": "Parquet", "svo": STORATIVITY_VAR,
         "description": ("Storativity (storage coefficient) at every active model cell for "
                         "all 8 layers, as GeoParquet (fields: row, col, storativit, layer, "
                         f"geometry). Dimensionless. CRS: {CRS_NAME}. "
                         f"Source feature class: ntgam_storativity. {storativity_decomp}")},
        {"kind": "dis", "name": "MODFLOW 6 DIS geometry (grid, land surface, layer bottoms)",
         "fmt": "ZIP", "svo": LANDSURFACE_VAR,
         "description": ("MODFLOW 6 DIS package (ntgam.dis: land-surface 'top' + grid) with "
                         "external layer-bottom (Bot1-8.ref) and idomain (Id1-8.ref) arrays. "
                         f"Grid: 8 layers x 1124 x 1412, 1320 ft cells, 65° rotation; feet MSL; "
                         f"{CRS_NAME}. NOTE: distributed Bot*.ref arrays are ragged (token "
                         "count != NROW*NCOL); reconstruct layer bottoms from top minus "
                         f"cumulative thickness. {landsurface_decomp}")},
    ]


# --- exporters (real run only) ---------------------------------------------
def to_cog(src: Path, dst: Path) -> None:
    rio_copy(str(src), str(dst), driver="COG", compress="DEFLATE", predictor=3,
             overview_resampling="nearest", blocksize=512)


def export_storativity(geodb: Path, dst: Path) -> None:
    gdb = geodb / "GAM_FileGeodatabase_v4.3.3.gdb"
    gpd.read_file(gdb, layer="ntgam_storativity").to_parquet(dst)


def make_dis_zip(model_ws: Path, dst: Path) -> None:
    members = ["ntgam.dis"] + [f"Bot{i}.ref" for i in range(1, 9)] + [f"Id{i}.ref" for i in range(1, 9)]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for m in members:
            if (model_ws / m).exists():
                z.write(model_ws / m, m)


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish NTGAM v3.01 to CKAN (twdb-subside)")
    ap.add_argument("--geodb", type=Path, default=Path("/Users/wmobley/Downloads/NTGAM_Geodatabase"))
    ap.add_argument("--model", type=Path,
                    default=Path("/Users/wmobley/Downloads/NTGAM_Final_model_2025/NTGAM_Feb_2025_all"))
    ap.add_argument("--dry-run", action="store_true", help="print payloads + sizes; no network")
    ap.add_argument("--limit", type=int, default=0, help="publish only the first N resources (testing)")
    args = ap.parse_args()

    spatial = domain_geojson(args.geodb)
    wl = _waterlevels_dir(args.geodb)
    pkg = dataset_payload(spatial)
    resources = head_resources() + property_resources()
    if args.limit:
        resources = resources[: args.limit]

    if args.dry_run:
        print("=== DATASET (scheming type=dataset) ===")
        shown = {**pkg, "fields": {**pkg["fields"], "spatial": pkg["fields"]["spatial"][:50] + "…"}}
        print(json.dumps(shown, indent=2))
        print(f"\n=== {len(resources)} RESOURCES (persisting fields: name, format, description, mint_standard_variables) ===")
        for r in resources:
            if r["kind"] == "cog":
                mb = (wl / r["src_name"]).stat().st_size / 1e6
                size = f"src {mb:.0f} MB -> COG ~{mb/2:.0f} MB"
            elif r["kind"] == "storativity":
                size = "GeoParquet ~168 MB"
            else:
                size = "zip (ntgam.dis + Bot*.ref + Id*.ref)"
            print(f"- [{r['fmt']}] {r['name']}")
            print(f"    mint_standard_variables={r['svo']!r}  [{size}]")
        print(f"\nOrg={ORG}, dataset={DATASET_NAME}, type=dataset, license=other-pd. No network calls.")
        return

    from tapis_ckan_auth import ckan_token_from_tapis
    token = ckan_token_from_tapis()
    with CkanClient(url=CKAN_URL, token=token, org=ORG) as ckan, \
            tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ds = ckan.ensure_dataset(pkg["name"], title=pkg["title"], notes=pkg["notes"],
                                 owner_org=ORG, fields=pkg["fields"])
        print(f"dataset ready: {ds.get('name')} ({ds.get('id')})")
        for r in resources:
            if r["kind"] == "cog":
                out = tmp / f"cog_{r['src_name']}"; to_cog(wl / r["src_name"], out)
            elif r["kind"] == "storativity":
                out = tmp / "ntgam_storativity.parquet"; export_storativity(args.geodb, out)
            else:
                out = tmp / "ntgam_dis_geometry.zip"; make_dis_zip(args.model, out)
            up = ckan.upload_resource(pkg["name"], str(out), item_id=ITEM_ID,
                                      name=r["name"], fmt=r["fmt"])
            ckan._action_json("resource_patch", {
                "id": up["id"], "description": r["description"],
                "mint_standard_variables": r["svo"],
            })
            print(f"  uploaded + tagged ({r['svo']}): {r['name']} -> {up.get('id')}")
        print("done.")


if __name__ == "__main__":
    main()
