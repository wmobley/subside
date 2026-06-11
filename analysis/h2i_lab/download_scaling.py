"""Download-scaling benchmark to refine analysis/h2i_lab/estimate.py.

Two sweeps, both through the real crop+write pipeline (download_disp_files):

* COUNT sweep — N full products on the full-download path, N up to 100. Tells
  us whether aggregate throughput holds as the file count grows or ASF throttles
  sustained load, and gives the real per-product size distribution.

* SIZE sweep — a fixed handful of products, with the bytes transferred *per
  file* dialed by the crop window read over HTTP Range (small window up to the
  whole image). Tells us how wall time scales with per-file transfer size on the
  range path.

Run on ls6 via tapis/benchmarks/download_scaling.sbatch. Needs the
subside-h2i-opera env and Earthdata creds (~/.netrc or EARTHDATA_* env).
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from analysis.etl.auth import earthdata_credentials
from analysis.etl.profiling import CpuSampler, Profiler
from analysis.h2i_lab.config import H2IRunConfig
from analysis.h2i_lab.download import download_disp_files
from analysis.h2i_lab.runner import preflight


# Nominal DISP-S1 frame dimensions; crop windows are centered in this and
# clamped per product, so an off-by-a-bit frame size is harmless.
_FRAME_W, _FRAME_H = 9464, 7733


def _discover_urls(aoi: str, start: str, end: str, min_overlap: float = 50.0) -> tuple[list[str], Any]:
    cfg = H2IRunConfig.from_dict({
        "start_date": start, "end_date": end, "aoi_geojson_path": aoi,
        "output_dir": "_dlbench_scan", "min_overlap_percent": min_overlap,
    })
    manifest = preflight(cfg)
    return manifest.get("product_urls") or [], manifest.get("bbox")


def _centered_window(px: int) -> list[int]:
    """A px-by-px pixel window centered in the frame: [c0, c1, r0, r1]."""

    half = px // 2
    cx, cy = _FRAME_W // 2, _FRAME_H // 2
    return [max(0, cx - half), cx + half, max(0, cy - half), cy + half]


def _run_once(urls: list[str], bbox: list[int] | None, outdir: Path,
              workers: int, remote: bool) -> dict[str, Any]:
    """One clean download (fresh dir, so nothing is skipped) with metrics."""

    if outdir.exists():
        shutil.rmtree(outdir)
    username, password = earthdata_credentials()
    prof = Profiler()
    cpu = CpuSampler()
    start = time.perf_counter()
    with cpu:
        files = download_disp_files(
            urls, bbox, outdir, username, password,
            num_workers=workers, remote_subset=remote, profiler=prof,
        )
    wall = time.perf_counter() - start
    summary = prof.summary()
    mb = summary["counters"].get("mb_downloaded", 0.0)
    cpu_stats = cpu.result() or {}
    return {
        "files": len(files),
        "wall_s": round(wall, 2),
        "mb": round(mb, 1),
        "mb_per_file": round(mb / max(1, len(files)), 1),
        "mbps": round(mb / wall, 1) if wall else None,
        "avg_cores_busy": cpu_stats.get("avg_cores_busy"),
        "peak_cores_busy": cpu_stats.get("peak_cores_busy"),
        "peak_rss_mb": summary["peak_rss_mb"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download-scaling benchmark (count + per-file size).")
    ap.add_argument("--aoi", required=True, help="AOI GeoJSON path.")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--counts", default="2,10,25,50,100", help="File counts to sweep (full-download path).")
    # NOTE: the full crop+write pipeline reads every variable + metadata groups,
    # so a range read over-fetches — even a 256px window pulls ~300 MB. Per-file
    # transfer is effectively floored near ~300 MB and only climbs at 'full'
    # (~423 MB). Keep levels few and non-redundant; the range path is also slow.
    ap.add_argument("--windows", default="512,4096,full",
                    help="Crop-window pixel sizes for the range size sweep; 'full' = whole image.")
    ap.add_argument("--size-files", type=int, default=3, help="Files per size-sweep level (range path is slow).")
    ap.add_argument("--workers", type=int, default=8, help="Workers for the count sweep.")
    ap.add_argument("--size-workers", type=int, default=4, help="Workers for the size sweep.")
    ap.add_argument("--output-root", default="dlbench-out")
    args = ap.parse_args(argv)

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)

    urls, bbox = _discover_urls(args.aoi, args.start, args.end)
    print(f"discovered {len(urls)} products; bbox={bbox}", flush=True)
    if not urls:
        print("No products discovered — widen the AOI/date range.", flush=True)
        return 1

    counts = [int(x) for x in args.counts.split(",") if x.strip()]
    if max(counts) > len(urls):
        print(f"WARNING: only {len(urls)} products available; capping counts.", flush=True)
        counts = sorted({min(c, len(urls)) for c in counts})

    count_window = _centered_window(1024)  # crop only affects the tiny written .nc
    results: dict[str, Any] = {
        "discovered": len(urls), "workers": args.workers,
        "count_sweep": [], "size_sweep": [],
    }

    print(f"\n== COUNT SWEEP (full-download, workers={args.workers}) ==", flush=True)
    print(f"{'N':>5}{'wall_s':>9}{'MB':>10}{'MB/s':>8}{'avgCPU':>8}{'peakRSS':>9}", flush=True)
    for n in counts:
        r = _run_once(urls[:n], count_window, root / f"count-{n}", args.workers, remote=False)
        r["n"] = n
        results["count_sweep"].append(r)
        print(f"{n:>5}{r['wall_s']:>9}{r['mb']:>10}{str(r['mbps']):>8}{str(r['avg_cores_busy']):>8}{str(r['peak_rss_mb']):>9}", flush=True)

    print(f"\n== SIZE SWEEP (range path, {args.size_files} files, workers={args.size_workers}) ==", flush=True)
    print(f"{'window':>7}{'wall_s':>9}{'MB':>10}{'MB/file':>9}{'MB/s':>8}", flush=True)
    size_urls = urls[: args.size_files]
    for w in [x.strip() for x in args.windows.split(",") if x.strip()]:
        window = None if w == "full" else _centered_window(int(w))
        r = _run_once(size_urls, window, root / f"size-{w}", args.size_workers, remote=True)
        r["window"] = w
        results["size_sweep"].append(r)
        print(f"{w:>7}{r['wall_s']:>9}{r['mb']:>10}{r['mb_per_file']:>9}{str(r['mbps']):>8}", flush=True)

    out = root / "download-scaling-results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
