"""DISP-S1 download and subset helpers from the H2I notebook."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any
import gc
import os


def clip_bbox(ds: Any, bbox: list[int] | None):
    """Clip an xarray dataset to [col_start, col_end, row_start, row_end]."""

    if bbox is None:
        return None
    height = ds.sizes["y"]
    width = ds.sizes["x"]
    x_start = max(0, min(width, bbox[0]))
    x_stop = max(0, min(width, bbox[1]))
    y_start = max(0, min(height, bbox[2]))
    y_stop = max(0, min(height, bbox[3]))
    if x_start >= x_stop or y_start >= y_stop:
        return None
    return slice(y_start, y_stop), slice(x_start, x_stop)


def copy_group_h5py(source_h5: Any, target_path: str | Path, group_name: str) -> None:
    """Copy a nested HDF5 group to a NetCDF/HDF5 target file."""

    import h5py

    try:
        with h5py.File(target_path, "a") as target_h5:
            src_group = source_h5[group_name]
            tgt_group = target_h5.require_group(group_name)
            for name, dataset in src_group.items():
                if name in tgt_group:
                    del tgt_group[name]
                tgt_ds = tgt_group.create_dataset(name, data=dataset[()])
                for key, val in dataset.attrs.items():
                    tgt_ds.attrs[key] = val
            for key, val in src_group.attrs.items():
                tgt_group.attrs[key] = val
    except Exception as exc:
        print(f"Failed to copy {group_name} with h5py: {exc}")


def _subset_to_netcdf(ds: Any, outname: str | Path, clipped: tuple[slice, slice] | None, *, mode: str = "w", group: str | None = None) -> None:
    subset = ds.isel(y=clipped[0], x=clipped[1]) if clipped is not None else ds
    comp = dict(zlib=True, complevel=4, shuffle=True)
    encoding = {
        var: {
            **comp,
            "chunksizes": (
                min(512, subset[var].shape[0]),
                min(512, subset[var].shape[1]),
            ),
        }
        for var in subset.data_vars
        if subset[var].dtype.kind in "fiu" and subset[var].ndim >= 2
    }
    subset.to_netcdf(outname, mode=mode, group=group, engine="h5netcdf", encoding=encoding)


def process_file(url: str, bbox: list[int] | None, outdir: str | Path, username: str, password: str) -> Path | None:
    """Download one DISP-S1 product and optionally crop it to a pixel bbox."""

    import h5py
    import xarray as xr

    from subside_analysis.etl.auth import earthdata_session

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    base, _ext = os.path.splitext(filename)
    outname = outdir / f"{base}.nc"
    if outname.exists():
        print(f"Skipped (exists): {filename}")
        return outname

    session = earthdata_session(username, password)
    try:
        with session.get(url, stream=True, timeout=600) as response:
            response.raise_for_status()
            file_bytes = BytesIO(response.content)
            try:
                with h5py.File(file_bytes, "r") as h5f:
                    with xr.open_dataset(h5f, engine="h5netcdf") as ds:
                        clipped = clip_bbox(ds, bbox)
                        if bbox is not None and clipped is None:
                            print(f"Skipped (bbox out of bounds): {filename}")
                            return None
                        _subset_to_netcdf(ds, outname, clipped)

                    with xr.open_dataset(h5f, engine="h5netcdf", group="corrections") as ds_corr:
                        clipped = clip_bbox(ds_corr, bbox)
                        if bbox is None or clipped is not None:
                            _subset_to_netcdf(ds_corr, outname, clipped, mode="a", group="corrections")

                    for group in ["metadata", "identification"]:
                        try:
                            with h5py.File(outname, "a") as dest_hf:
                                if group in dest_hf:
                                    del dest_hf[group]
                                h5f.copy(group, dest_hf, name=group)
                        except Exception as exc:
                            print(f"Failed to copy group {group!r}: {exc}")
                    copy_group_h5py(h5f, outname, "metadata/reference_orbit")
                    copy_group_h5py(h5f, outname, "metadata/secondary_orbit")
            finally:
                file_bytes.close()
                gc.collect()
    finally:
        session.close()

    print(f"Done: {filename}")
    return outname


def download_disp_files(
    nc_urls: list[str],
    bbox: list[int] | None,
    outdir: str | Path,
    username: str,
    password: str,
    num_workers: int = 3,
) -> list[Path]:
    """Download and optionally crop DISP NetCDF files in parallel."""

    outputs: list[Path] = []
    with ThreadPoolExecutor(max_workers=int(num_workers)) as executor:
        future_to_url = {
            executor.submit(process_file, url, bbox, outdir, username, password): url
            for url in nc_urls
        }
        for future in as_completed(future_to_url):
            result = future.result()
            if result is not None:
                outputs.append(result)
    return sorted(outputs)

