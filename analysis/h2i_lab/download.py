"""DISP-S1 download and subset helpers from the H2I notebook.

Two transfer strategies share one HDF5->NetCDF writer:

* full download (``remote_subset=False``) — pull the whole product into memory
  and crop afterward. Simple, but transfers bytes the AOI never uses.
* remote subset (``remote_subset=True``) — open the product over HTTP range
  reads (:class:`HttpRangeFile`) so only the chunks overlapping the AOI window
  cross the wire. Wins scale with how small the AOI is relative to the frame.

Both paths feed byte/stage counters into an optional :class:`Profiler` so the
benchmark harness can attribute wall time and transfer volume.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any
import os
import subprocess

from analysis.etl.profiling import Profiler

URS_HOST = "urs.earthdata.nasa.gov"


def ensure_earthdata_netrc() -> Path:
    """Guarantee a ``~/.netrc`` entry for Earthdata so ``opera-utils`` can auth.

    The OPERA download stack reads credentials from ``~/.netrc`` (not env vars).
    Leave an existing ``urs.earthdata.nasa.gov`` entry untouched; otherwise write
    one from ``EARTHDATA_USERNAME``/``EARTHDATA_PASSWORD`` — mirroring the
    notebook's credential cell.
    """
    from netrc import NetrcParseError, netrc as _netrc

    netrc_path = Path(os.path.expanduser("~")) / ("_netrc" if os.name == "nt" else ".netrc")
    try:
        if netrc_path.exists() and _netrc(str(netrc_path)).authenticators(URS_HOST):
            return netrc_path
    except (NetrcParseError, OSError):
        pass  # unreadable/parse error -> (re)write below

    from analysis.etl.auth import earthdata_credentials

    user, password = earthdata_credentials()
    netrc_path.write_text(f"machine {URS_HOST} login {user} password {password}\n")
    os.chmod(netrc_path, 0o600)
    return netrc_path


def download_via_opera_utils(
    frame_id: int,
    bbox: dict[str, float],
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    *,
    num_workers: int = 4,
    executable: str = "opera-utils",
) -> list[Path]:
    """Download + AOI-subset DISP-S1 with ``opera-utils disp-s1-download``.

    This is the exact path the OPERA notebook uses (cell 8): opera-utils discovers
    the products for ``frame_id`` over the date window and crops each to the lon/lat
    ``bbox`` itself, so we don't reimplement product search or subsetting. The
    cropped NetCDFs land in ``output_dir`` ready for ``disp_xr`` / the WERC stack.
    Returns the downloaded ``*.nc`` paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ensure_earthdata_netrc()
    cmd = [
        executable, "disp-s1-download",
        "--output-dir", str(out),
        "--bbox", str(bbox["lon_min"]), str(bbox["lat_min"]),
        str(bbox["lon_max"]), str(bbox["lat_max"]),
        "--frame-id", str(int(frame_id)),
        "--start-datetime", str(start_date),
        "--end-datetime", str(end_date),
        "--num-workers", str(int(num_workers)),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return sorted(out.glob("*.nc"))


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


class HttpRangeFile:
    """Seekable, read-only file object backed by HTTP range requests.

    h5py can open any Python file-like with ``read``/``seek``/``tell``; backing
    those by ``Range`` GETs means an HDF5 reader only pulls the bytes it touches
    (superblock, b-trees, and the chunks under the AOI window) instead of the
    whole product. Reuses the OAuth-redirect-surviving ``EarthdataSession`` so
    auth Just Works against URS-protected DAACs.

    Falls back transparently to a single full GET when the origin ignores
    ``Range`` (HTTP 200 instead of 206) — correctness is preserved, savings are
    not.
    """

    def __init__(self, session: Any, url: str, *, block: int = 4 * 1024 * 1024, profiler: Profiler | None = None) -> None:
        self.session = session
        self.url = url
        self.block = block
        self.profiler = profiler
        self.pos = 0
        self._blocks: dict[int, bytes] = {}
        self._whole: bytes | None = None
        self.size = self._probe()

    # --- byte accounting -------------------------------------------------
    def _count(self, n: int) -> None:
        if self.profiler is not None:
            self.profiler.add("bytes_downloaded", n)

    def _probe(self) -> int:
        """Fetch the first block and learn the total size from Content-Range."""

        headers = {"Range": f"bytes=0-{self.block - 1}"}
        with self.session.get(self.url, headers=headers, timeout=600) as resp:
            resp.raise_for_status()
            content = resp.content
            self._count(len(content))
            if resp.status_code == 206 and "Content-Range" in resp.headers:
                total = int(resp.headers["Content-Range"].split("/")[-1])
                self._blocks[0] = content
                return total
            # Range unsupported: we just downloaded the whole object.
            self._whole = content
            return len(content)

    def _get_block(self, index: int) -> bytes:
        if self._whole is not None:
            start = index * self.block
            return self._whole[start : start + self.block]
        cached = self._blocks.get(index)
        if cached is not None:
            return cached
        start = index * self.block
        stop = min(self.size, start + self.block) - 1
        headers = {"Range": f"bytes={start}-{stop}"}
        with self.session.get(self.url, headers=headers, timeout=600) as resp:
            resp.raise_for_status()
            content = resp.content
        self._count(len(content))
        self._blocks[index] = content
        return content

    # --- file-like protocol ---------------------------------------------
    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            self.pos = offset
        elif whence == os.SEEK_CUR:
            self.pos += offset
        elif whence == os.SEEK_END:
            self.pos = self.size + offset
        return self.pos

    def tell(self) -> int:
        return self.pos

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self.pos
        start = self.pos
        end = min(self.size, start + size)
        if start >= end:
            return b""
        out = bytearray()
        first = start // self.block
        last = (end - 1) // self.block
        for index in range(first, last + 1):
            block = self._get_block(index)
            base = index * self.block
            lo = max(start, base) - base
            hi = min(end, base + len(block)) - base
            out += block[lo:hi]
        self.pos = end
        return bytes(out)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def close(self) -> None:  # noqa: D401 - file-like no-op
        self._blocks.clear()
        self._whole = None


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


def _copy_aux_groups(source_h5: Any, dest_path: str | Path) -> None:
    """Copy metadata/identification/orbit groups in a single dest open.

    Previously each group cost its own ``h5py.File(outname, "a")`` open/flush
    cycle (four per product); one open does the lot.
    """

    import h5py

    with h5py.File(dest_path, "a") as dest_hf:
        for group in ("metadata", "identification"):
            try:
                if group in dest_hf:
                    del dest_hf[group]
                source_h5.copy(group, dest_hf, name=group)
            except Exception as exc:
                print(f"Failed to copy group {group!r}: {exc}")
        for group in ("metadata/reference_orbit", "metadata/secondary_orbit"):
            try:
                src_group = source_h5[group]
                tgt_group = dest_hf.require_group(group)
                for name, dataset in src_group.items():
                    if name in tgt_group:
                        del tgt_group[name]
                    tgt_ds = tgt_group.create_dataset(name, data=dataset[()])
                    for key, val in dataset.attrs.items():
                        tgt_ds.attrs[key] = val
                for key, val in src_group.attrs.items():
                    tgt_group.attrs[key] = val
            except Exception as exc:
                print(f"Failed to copy {group} with h5py: {exc}")


def _write_product(h5f: Any, outname: Path, bbox: list[int] | None, filename: str) -> Path | None:
    """Crop the open product (h5py source) and write the cropped NetCDF."""

    import xarray as xr

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

    _copy_aux_groups(h5f, outname)
    return outname


def process_bytes(file_bytes: BytesIO, url: str, bbox: list[int] | None, outdir: str | Path) -> Path | None:
    """Crop and write a product whose bytes are already in memory.

    Lets the runner reuse the sample it downloaded to derive the pixel bbox as
    the first cropped output, instead of fetching that product a second time.
    """

    import h5py

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    base, _ext = os.path.splitext(filename)
    outname = outdir / f"{base}.nc"
    if outname.exists():
        print(f"Skipped (exists): {filename}")
        return outname
    file_bytes.seek(0)
    with h5py.File(file_bytes, "r") as h5f:
        result = _write_product(h5f, outname, bbox, filename)
    if result is not None:
        print(f"Done: {filename}")
    return result


def process_file(
    url: str,
    bbox: list[int] | None,
    outdir: str | Path,
    username: str,
    password: str,
    *,
    remote_subset: bool = False,
    profiler: Profiler | None = None,
) -> Path | None:
    """Download one DISP-S1 product and optionally crop it to a pixel bbox.

    With ``remote_subset`` the product is read over HTTP range requests so only
    the AOI chunks transfer; otherwise the whole product is pulled into memory
    and cropped afterward.
    """

    import h5py

    from analysis.etl.auth import earthdata_session

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
        if remote_subset:
            range_file = HttpRangeFile(session, url, profiler=profiler)
            try:
                with h5py.File(range_file, "r") as h5f:
                    result = _write_product(h5f, outname, bbox, filename)
            finally:
                range_file.close()
        else:
            with session.get(url, stream=True, timeout=600) as response:
                response.raise_for_status()
                payload = response.content
                if profiler is not None:
                    profiler.add("bytes_downloaded", len(payload))
                file_bytes = BytesIO(payload)
                try:
                    with h5py.File(file_bytes, "r") as h5f:
                        result = _write_product(h5f, outname, bbox, filename)
                finally:
                    file_bytes.close()
    finally:
        session.close()

    if result is not None:
        print(f"Done: {filename}")
    return result


def download_disp_files(
    nc_urls: list[str],
    bbox: list[int] | None,
    outdir: str | Path,
    username: str,
    password: str,
    num_workers: int = 3,
    *,
    remote_subset: bool = False,
    profiler: Profiler | None = None,
) -> list[Path]:
    """Download and optionally crop DISP NetCDF files in parallel."""

    outputs: list[Path] = []
    with ThreadPoolExecutor(max_workers=int(num_workers)) as executor:
        future_to_url = {
            executor.submit(
                process_file,
                url,
                bbox,
                outdir,
                username,
                password,
                remote_subset=remote_subset,
                profiler=profiler,
            ): url
            for url in nc_urls
        }
        for future in as_completed(future_to_url):
            result = future.result()
            if result is not None:
                outputs.append(result)
    return sorted(outputs)
