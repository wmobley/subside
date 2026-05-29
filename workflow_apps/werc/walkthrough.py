"""WERC OPERA Workflow — local walkthrough.

Run end-to-end as a script:
    python walkthrough.py

Or step through cells in any editor that recognises ``# %%`` markers
(VS Code, PyCharm, Cursor, Spyder, ...).

Composes the H2I download stage with the WERC stack / reference / velocity /
export steps — the same code path the Tapis batch app runs via ``run.sh``.
"""

# %% [markdown]
# ## 1. Setup
#
# Put the repo's ``subside/`` directory on ``sys.path`` so ``subside_analysis``
# is importable from this script's location (``subside/workflow_apps/werc/``).

# %%
import json
import os
import sys
from pathlib import Path

try:
    NOTEBOOK_DIR = Path(__file__).resolve().parent
except NameError:
    NOTEBOOK_DIR = Path(os.getcwd()).resolve()
SUBSIDE_ROOT = NOTEBOOK_DIR.parents[1]  # subside/
sys.path.insert(0, str(SUBSIDE_ROOT))

OUTPUT_DIR = NOTEBOOK_DIR / "walkthrough_outputs"
AOI_GEOJSON = NOTEBOOK_DIR / "walkthrough_aoi.geojson"
OUTPUT_DIR.mkdir(exist_ok=True)
print("subside/ on path:", SUBSIDE_ROOT)
print("outputs:", OUTPUT_DIR)

# %% [markdown]
# ## 2. Earthdata credentials

# %%
EARTHDATA_USERNAME = "mobley"
EARTHDATA_PASSWORD = "fRk4h)?i4-d5/9a"

if EARTHDATA_USERNAME and EARTHDATA_PASSWORD:
    os.environ["EARTHDATA_USERNAME"] = EARTHDATA_USERNAME
    os.environ["EARTHDATA_PASSWORD"] = EARTHDATA_PASSWORD
    print("Earthdata credentials set from script variables.")
elif os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
    print("Using existing EARTHDATA_USERNAME env credentials.")
else:
    from netrc import netrc
    try:
        creds = netrc().authenticators("urs.earthdata.nasa.gov")
        print("Using ~/.netrc credentials." if creds else "No urs.earthdata.nasa.gov entry in ~/.netrc.")
    except FileNotFoundError:
        print(
            "No env credentials and no ~/.netrc. "
            "Set EARTHDATA_USERNAME / EARTHDATA_PASSWORD above before continuing."
        )

# %% [markdown]
# ## 3. Run config + AOI
#
# Tiny AOI over Houston-Galveston. The WERC config carries a nested H2I config
# plus the stack/reference/velocity options.

# %%
from subside_analysis.werc.config import WercRunConfig

aoi = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-95.55, 29.55], [-95.35, 29.55],
                    [-95.35, 29.75], [-95.55, 29.75],
                    [-95.55, 29.55],
                ]],
            },
        }
    ],
}
AOI_GEOJSON.write_text(json.dumps(aoi))

config = WercRunConfig.from_dict({
    "start_date": "2024-06-01",
    "end_date": "2024-09-01",
    "output_dir": str(OUTPUT_DIR),
    "aoi_geojson_path": str(AOI_GEOJSON),
    "num_workers": 2,
    "min_overlap_percent": 50.0,
    "reference_mode": "auto",
    "anchor_radius_m": 5000,
    "n_reference_pixels": 25,
    "anchor_dir": str(OUTPUT_DIR / "anchors"),
})
print(config)

# %% [markdown]
# ## 4. H2I download (reused stage)
#
# The WERC pipeline reuses ``h2i_lab.runner.run`` to pull and crop the
# DISP-S1 NetCDFs. After this cell the results live in
# ``config.h2i.results_path()``.

# %%
from subside_analysis.h2i_lab.runner import run as h2i_run

h2i_manifest = h2i_run(config.h2i)
nc_dir = config.h2i.results_path()
print("NetCDFs in:", nc_dir)
print("Count    :", len(list(nc_dir.glob("*.nc"))))

# %% [markdown]
# ## 5. Build the displacement stack

# %%
from subside_analysis.werc import stack as stack_mod

disp_df = stack_mod.load_disp_product_list(nc_dir)
stack_prod = stack_mod.build_displacement_stack(disp_df)
frame_id = stack_mod.resolve_frame_id(disp_df)
print("Frame ID :", frame_id)
print("Stack dims:", dict(stack_prod.sizes))
print(disp_df.head())

# %% [markdown]
# ## 6. Quality layers + auto reference
#
# Anchor JSON is persisted under ``anchor_dir`` so subsequent runs in any
# overlapping BBOX reuse the same reference.

# %%
from subside_analysis.werc import reference

quality = reference.compute_quality_layers(stack_prod)
ref = reference.apply_auto_reference(
    stack_prod, quality, frame_id,
    anchor_dir=config.anchor_path(),
    radius_m=config.anchor_radius_m,
    n_target=config.n_reference_pixels,
)
print(f"Anchor     : ({ref.anchor_lat:.5f}°N, {ref.anchor_lon:.5f}°E)")
print(f"Threshold  : {ref.threshold_label}")
print(f"Pixels     : {len(ref.iy_sel)} (newly picked: {ref.newly_picked})")
print(f"Anchor file: {ref.anchor_path}")

# %% [markdown]
# ## 7. Velocity estimation
#
# Per-pixel linear fit of displacement vs. time, returned in m/year on the
# stack grid.

# %%
import numpy as np

from subside_analysis.werc import velocity

vel_da = velocity.estimate_velocity_linear(stack_prod)
print(
    "Velocity m/year — p2 / p50 / p98:",
    float(np.nanpercentile(vel_da, 2)),
    float(np.nanpercentile(vel_da, 50)),
    float(np.nanpercentile(vel_da, 98)),
)

# %% [markdown]
# ## 8. Export GeoTIFFs
#
# Both writers reproject to EPSG:4326 and convert m → mm. Outputs are tiled +
# deflate-compressed and tagged with date range / reference coords.

# %%
from subside_analysis.werc import export

disp_info = export.write_cumulative_displacement_geotiff(
    stack_prod,
    OUTPUT_DIR / "opera_disp_s1_cumulative.tif",
    reference_lon=ref.anchor_lon,
    reference_lat=ref.anchor_lat,
)
vel_info = export.write_velocity_geotiff(
    vel_da, stack_prod, OUTPUT_DIR / "opera_disp_s1_velocity.tif"
)
print("Cumulative:", json.dumps(disp_info, indent=2, default=str))
print("Velocity  :", json.dumps(vel_info, indent=2, default=str))

# %% [markdown]
# ## 9. End-to-end equivalence (Tapis path)
#
# ``werc.runner.run`` does steps 4–8 in one call and writes
# ``werc-run-manifest.json`` — the same code path
# ``workflow_apps/werc/run.sh`` executes inside the Tapis container. Using
# ``skip_download=True`` so we reuse the NetCDFs we already pulled.

# %%
from dataclasses import replace

from subside_analysis.werc.runner import run as werc_run

rerun_config = replace(config, skip_download=True, netcdf_dir=str(nc_dir))
werc_manifest = werc_run(rerun_config)
print(json.dumps({
    "frame_id": werc_manifest["frame_id"],
    "reference": werc_manifest["reference"],
    "artifacts": list(werc_manifest["artifacts"].keys()),
}, indent=2, default=str))
