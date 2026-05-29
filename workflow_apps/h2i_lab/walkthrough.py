"""H2I Lab OPERA Workflow — local walkthrough.

Run end-to-end as a script:
    python walkthrough.py

Or step through cells in any editor that recognises ``# %%`` markers
(VS Code, PyCharm, Cursor, Spyder, ...).

Exercises the extracted ``subside_analysis.h2i_lab`` package against real
Earthdata downloads — the same code path the Tapis batch app runs via
``run.sh``.
"""

# %% [markdown]
# ## 1. Setup
#
# Put the repo's ``subside/`` directory on ``sys.path`` so ``subside_analysis``
# is importable from this script's location (``subside/workflow_apps/h2i_lab/``).

# %%
import json
import os
import sys
from pathlib import Path

try:
    NOTEBOOK_DIR = Path(__file__).resolve().parent
except NameError:  # interactive cell execution without __file__
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
#
# Set ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD`` below; the script writes
# them into ``os.environ`` so the H2I runner picks them up.

# %%
EARTHDATA_USERNAME = "mobley"
EARTHDATA_PASSWORD = "fRk4h)?i4-d5/9a"

os.environ["EARTHDATA_USERNAME"] = EARTHDATA_USERNAME
os.environ["EARTHDATA_PASSWORD"] = EARTHDATA_PASSWORD

# %% [markdown]
# ## 3. Run config + AOI
#
# Tiny AOI over the Houston-Galveston area (known subsidence + good DISP-S1
# coverage). Adjust the bounding box and date range freely; smaller windows
# download faster.

# %%
from subside_analysis.h2i_lab.config import H2IRunConfig

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

config = H2IRunConfig.from_dict({
    "start_date": "2024-06-01",
    "end_date": "2024-09-01",
    "output_dir": str(OUTPUT_DIR),
    "aoi_geojson_path": str(AOI_GEOJSON),
    "num_workers": 2,
    "min_overlap_percent": 50.0,
})
print(config)

# %% [markdown]
# ## 4. Preflight
#
# Downloads the OPERA frames index, finds frames intersecting the AOI,
# queries ASF for available DISP-S1 products, filters by date, and writes
# ``outputs/preflight-manifest.json``. No Earthdata download yet.

# %%
from subside_analysis.h2i_lab.runner import preflight

preflight_manifest = preflight(config)
print("Frames  :", preflight_manifest["frame_ids"])
print("Products:", preflight_manifest["product_count"])
print("Warnings:", preflight_manifest["warnings"])

# %% [markdown]
# ## 5. Run — download, subset, preview, archive
#
# Pixel-bbox estimate, parallel NetCDF download with cropping, Folium PNG/HTML
# preview, zip archive. Output paths land under ``outputs/``.

# %%
from subside_analysis.h2i_lab.runner import run

run_manifest = run(config)
print(json.dumps(run_manifest["artifacts"], indent=2, default=str))

# %% [markdown]
# ## 6. Inspect artifacts

# %%
artifacts = run_manifest["artifacts"]
print("NetCDFs downloaded:", len(artifacts.get("downloaded_files", [])))
print("Overlay PNG       :", artifacts.get("overlay_png"))
print("Preview HTML      :", artifacts.get("preview_html"))
print("Archive zip       :", artifacts.get("archive_zip"))
