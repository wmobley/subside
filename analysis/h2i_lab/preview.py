"""Preview helpers extracted from the H2I notebook.

The generic zip-archive helper ``archive_results`` lives in
:mod:`analysis.etl.archive` and is re-exported here for
backward compatibility.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import base64
import glob

from analysis.etl.archive import archive_results  # noqa: F401  re-exported


def _displacement_is_valid(netcdf_path: str | Path) -> bool:
    """True if the displacement band has at least one finite (non-nodata) pixel."""

    import numpy as np
    import rioxarray as rxr

    data = rxr.open_rasterio(netcdf_path)
    disp = data["displacement"].sel(band=1)
    return bool(np.isfinite(disp.values).any())


def latest_netcdf(results_path: str | Path) -> Path:
    """Return the most recent NetCDF product with usable displacement data.

    Candidates are tried newest-first (by filename sort, as before). Frames are
    downloaded and AOI-cropped independently, so one frame's cropped product can
    land entirely on nodata for a given date even though the frame passed the
    overlap gate — skip that candidate in favor of the next most recent one
    instead of silently propagating an all-NaN band into the preview/COG.
    """

    files = sorted(Path(path) for path in glob.glob(str(Path(results_path) / "*.nc")))
    if not files:
        raise FileNotFoundError(f"No NetCDF files found under {results_path}")

    for candidate in reversed(files):
        if _displacement_is_valid(candidate):
            return candidate
        print(f"Skipping {candidate.name}: displacement band is entirely nodata over the AOI")

    raise RuntimeError(
        f"No NetCDF product under {results_path} has valid displacement data over the AOI "
        f"(checked {len(files)} file(s))."
    )


def make_displacement_overlay_png(netcdf_path: str | Path, output_png: str | Path) -> dict[str, float]:
    """Create a transparent PNG overlay for the first displacement band."""

    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image
    import rioxarray as rxr

    data = rxr.open_rasterio(netcdf_path)
    disp = data["displacement"].sel(band=1)
    disp_values = disp.values.copy()
    disp_values = np.nan_to_num(disp_values, nan=np.nan)
    vmin, vmax = np.nanpercentile(disp_values, [2, 98])
    disp_clipped = np.clip(disp_values, vmin, vmax)
    disp_norm = (disp_clipped - vmin) / (vmax - vmin)
    cmap = plt.get_cmap("viridis")
    disp_rgba = cmap(disp_norm)
    disp_rgba[..., 3] = np.where(np.isnan(disp_values), 0, 1)
    disp_rgba_img = (disp_rgba * 255).astype(np.uint8)
    if disp_rgba_img.ndim == 3 and disp_rgba_img.shape[0] == 4:
        disp_rgba_img = np.transpose(disp_rgba_img, (1, 2, 0))
    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(disp_rgba_img, mode="RGBA").save(output)
    return {"vmin": float(vmin), "vmax": float(vmax)}


def make_displacement_cog(netcdf_path: str | Path, output_tif: str | Path) -> dict[str, str]:
    """Write the first displacement band to a Cloud-Optimized GeoTIFF (COG).

    rioxarray carries the CRS/affine transform from the OPERA NetCDF, and the
    ``COG`` driver adds internal tiling + overviews so the file can be visualised
    by range requests (client-side georaster / a titiler) without downloading
    the whole raster."""

    import rioxarray as rxr  # noqa: F401  (registers the .rio accessor)

    data = rxr.open_rasterio(netcdf_path)
    disp = data["displacement"].sel(band=1)
    output = Path(output_tif)
    output.parent.mkdir(parents=True, exist_ok=True)
    disp.rio.to_raster(output, driver="COG", compress="DEFLATE")
    return {"path": str(output)}


def write_folium_preview(
    overlay_png: str | Path,
    aoi_path: str | Path,
    output_html: str | Path,
    *,
    vmin: float,
    vmax: float,
) -> Path:
    """Write the notebook-style Folium preview map as an HTML artifact."""

    import folium
    import geopandas as gpd
    import matplotlib
    import matplotlib.pyplot as plt
    from branca.element import Element

    aoi_gdf = gpd.read_file(aoi_path).to_crs("EPSG:4326")
    coords = aoi_gdf.total_bounds
    bounds = [[coords[1], coords[0]], [coords[3], coords[2]]]
    lat = (coords[1] + coords[3]) / 2
    lon = (coords[0] + coords[2]) / 2
    cmap = plt.get_cmap("viridis")
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(figsize=(0.6, 3), dpi=200)
    fig.subplots_adjust(right=0.5)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=ax)
    cbar.set_label("Displacement (m)", fontsize=9)
    buf_leg = BytesIO()
    fig.savefig(buf_leg, format="png", bbox_inches="tight")
    plt.close(fig)
    _legend_url = "data:image/png;base64," + base64.b64encode(buf_leg.getvalue()).decode("utf-8")

    map_obj = folium.Map([lat, lon], zoom_start=10, tiles="cartodb positron")
    map_obj.add_child(
        folium.raster_layers.ImageOverlay(
            image=str(overlay_png),
            bounds=bounds,
            colormap="viridis",
            opacity=1,
            interactive=True,
            overlay=True,
            name="OPERA DISP-S1",
        )
    )
    legend_html = f"""
<div style="position: fixed; bottom: 10px; left: 10px; z-index: 9999;
  background: #fff; border: 1px solid #999; border-radius: 6px;
  padding: 10px 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.3);
  font-size: 12px; line-height: 1.2; pointer-events: none;">
  <div style="width:100%; text-align:center; font-weight:700;">OPERA DISP-S1</div>
  <div style="width:100%; text-align:center; margin-bottom:6px;">Displacement (m)</div>
  <div style="display:flex; align-items:center; gap:8px; justify-content:center;">
    <span style="min-width:42px; text-align:right;">{vmin:.2f}</span>
    <div style="height:14px; width:240px; border:1px solid #999; border-radius:3px;
      background: linear-gradient(to right,#440154,#482878,#3e4989,#31688e,#26828e,#1f9e89,#35b779,#6ece58,#b5de2b,#fde725);"></div>
    <span style="min-width:42px; text-align:left;">{vmax:.2f}</span>
  </div>
</div>
"""
    map_obj.get_root().html.add_child(Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(map_obj)
    output = Path(output_html)
    output.parent.mkdir(parents=True, exist_ok=True)
    map_obj.save(output)
    return output



