"""Ablation harness for the H2I download stage.

Runs the same workload under several configurations and reports per-variant
wall time, per-stage timing, and bytes transferred so we can see which code
changes actually move H2I wall-clock. Each variant gets its own output dir so
"skip (exists)" never contaminates a timing.

Run inside the ``subside-h2i-opera`` conda env, from the ``subside/`` dir::

    python -m analysis.h2i_lab.benchmark \
        --aoi examples/sample_aoi.geojson \
        --start 2024-06-01 --end 2024-12-01 \
        --max-products 3 --reps 1

Requires Earthdata credentials (EARTHDATA_USERNAME/PASSWORD or ~/.netrc).
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from .config import H2IRunConfig
from .runner import run


# Each variant toggles one lever relative to the production baseline so the
# deltas are attributable. Workers are bumped together with prime/remote since
# those are the realistic "fast" configurations we'd actually ship.
VARIANTS: list[dict[str, Any]] = [
    {"name": "baseline", "bbox_mode": "sample", "remote_subset": False, "num_workers": 2},
    {"name": "prime", "bbox_mode": "prime", "remote_subset": False, "num_workers": 2},
    {"name": "prime+workers8", "bbox_mode": "prime", "remote_subset": False, "num_workers": 8},
    {"name": "remote_subset+workers8", "bbox_mode": "prime", "remote_subset": True, "num_workers": 8},
]


def _build_config(base: dict[str, Any], variant: dict[str, Any], output_dir: Path) -> H2IRunConfig:
    payload = {
        **base,
        "output_dir": str(output_dir),
        "bbox_mode": variant["bbox_mode"],
        "remote_subset": variant["remote_subset"],
        "num_workers": variant["num_workers"],
    }
    return H2IRunConfig.from_dict(payload)


def run_variant(base: dict[str, Any], variant: dict[str, Any], output_root: Path, rep: int) -> dict[str, Any]:
    output_dir = output_root / f"{variant['name']}-rep{rep}"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    config = _build_config(base, variant, output_dir)

    start = time.perf_counter()
    error = None
    timings: dict[str, Any] = {}
    n_files = 0
    try:
        manifest = run(config)
        timings = manifest.get("timings", {})
        n_files = len(manifest.get("artifacts", {}).get("downloaded_files", []))
    except Exception as exc:  # keep the sweep going; record the failure
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - start

    cpu = (timings.get("meta", {}) or {}).get("download_cpu") or {}
    return {
        "variant": variant["name"],
        "rep": rep,
        "workers": variant["num_workers"],
        "wall_seconds": round(wall, 2),
        "files": n_files,
        "mb_downloaded": timings.get("counters", {}).get("mb_downloaded"),
        "avg_cores_busy": cpu.get("avg_cores_busy"),
        "peak_cores_busy": cpu.get("peak_cores_busy"),
        "n_cpus": cpu.get("n_cpus"),
        "stage_seconds": timings.get("stage_seconds", {}),
        "peak_rss_mb": timings.get("peak_rss_mb"),
        "error": error,
    }


def _print_table(results: list[dict[str, Any]]) -> None:
    header = f"{'variant':<24}{'wkrs':>5}{'wall_s':>9}{'MB':>9}{'files':>6}{'avgCPU':>8}{'peakCPU':>8}  stages"
    print("\n" + header)
    print("-" * len(header))
    baseline_wall = next((r["wall_seconds"] for r in results if r["variant"] == "baseline" and not r["error"]), None)
    if baseline_wall is None:  # no baseline in this sweep; use the slowest as reference
        walls = [r["wall_seconds"] for r in results if not r["error"]]
        baseline_wall = max(walls) if walls else None
    for r in results:
        if r["error"]:
            print(f"{r['variant']:<24}{r['workers']:>5}{'ERROR':>9}   {r['error']}")
            continue
        speedup = f"{baseline_wall / r['wall_seconds']:.2f}x" if baseline_wall else ""
        stages = " ".join(f"{k}={v}" for k, v in r["stage_seconds"].items())
        mb = f"{r['mb_downloaded']:.0f}" if r["mb_downloaded"] is not None else "?"
        avg = f"{r['avg_cores_busy']:.1f}" if r["avg_cores_busy"] is not None else "?"
        peak = f"{r['peak_cores_busy']:.1f}" if r["peak_cores_busy"] is not None else "?"
        n = r.get("n_cpus") or "?"
        print(f"{r['variant']:<24}{r['workers']:>5}{r['wall_seconds']:>9}{mb:>9}{r['files']:>6}{avg:>8}{peak:>8}  {stages}  {speedup} ({avg}/{n} cores)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ablation benchmark for the H2I download stage.")
    parser.add_argument("--aoi", required=True, help="AOI GeoJSON path.")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    parser.add_argument("--max-products", type=int, default=3, help="Cap products per run.")
    parser.add_argument("--reps", type=int, default=1, help="Repetitions per variant.")
    parser.add_argument("--output-root", default="bench-out", help="Root dir for per-variant outputs.")
    parser.add_argument("--variants", help="Comma-separated subset of variant names to run.")
    parser.add_argument(
        "--workers",
        help="Comma-separated worker counts to sweep, e.g. '4,8,16'. Runs the "
        "full-download 'prime' path at each count to test core scaling "
        "(overrides --variants).",
    )
    parser.add_argument(
        "--sweep-remote",
        action="store_true",
        help="With --workers, also run the remote_subset (range-read) path at "
        "each worker count, side by side with full-download.",
    )
    args = parser.parse_args(argv)

    base = {
        "start_date": args.start,
        "end_date": args.end,
        "aoi_geojson_path": args.aoi,
        "max_products": args.max_products,
        "min_overlap_percent": 50.0,
    }
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    selected = VARIANTS
    if args.workers:
        counts = [int(w) for w in args.workers.split(",") if w.strip()]
        selected = []
        for w in counts:
            selected.append({"name": f"full+w{w}", "bbox_mode": "prime", "remote_subset": False, "num_workers": w})
            if args.sweep_remote:
                selected.append({"name": f"remote+w{w}", "bbox_mode": "prime", "remote_subset": True, "num_workers": w})
    elif args.variants:
        wanted = {name.strip() for name in args.variants.split(",")}
        selected = [v for v in VARIANTS if v["name"] in wanted]

    results: list[dict[str, Any]] = []
    for rep in range(1, args.reps + 1):
        for variant in selected:
            print(f"\n=== {variant['name']} (rep {rep}) ===", flush=True)
            result = run_variant(base, variant, output_root, rep)
            results.append(result)
            print(json.dumps({k: result[k] for k in ("wall_seconds", "mb_downloaded", "files", "error")}), flush=True)

    _print_table(results)
    out = output_root / "benchmark-results.json"
    out.write_text(json.dumps({"base": base, "results": results}, indent=2))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
