"""Check the WERC velocity solver and profile its memory/time across cube sizes.

The shipped solver ([analysis/werc/velocity.py] ``estimate_velocity_linear``)
follows the WERC notebook (OPERA DISP-S1.ipynb cell 24) exactly:
``np.linalg.lstsq(A, disp.reshape(nt,-1))``. This tool, on real or synthetic data
across a range of cube sizes:

  * **faithfulness** — confirms the shipped solver reproduces an *independent*
    re-implementation of the notebook's cell-24 lstsq (max/mean |Δ| on co-finite
    pixels; ~0 since it's the same algorithm). Guards against future drift.
  * **memory** — marginal RSS the solver adds over the loaded displacement, in a
    clean child process. lstsq upcasts the cube to float64 and sizes LAPACK's
    gelsd workspace by the pixel count, so this grows ~``nt × npix × 8`` bytes —
    use it to see how big a cube the node can take before it OOMs.
  * **time** — wall time.

It exits non-zero if any size exceeds ``--tol``, so it doubles as a regression gate.

Usage::

    # Real data — a prebuilt stack, or a directory of OPERA DISP-S1 NetCDFs:
    python -m analysis.werc.velocity_check --stack stack.nc --memory --report-out report.json
    python -m analysis.werc.velocity_check --netcdf-dir output/OPERA_L3_DISP-S1 --memory

    # No data handy — synthetic cubes of several sizes:
    python -m analysis.werc.velocity_check --synthetic

Size variety comes from center-cropping the real stack to spatial fractions
(``--fractions 1,0.5,0.25``) and optionally sub-setting time
(``--time-fractions``), so every variant is *real values*, just a different
``(nt, ny, nx)``.

NOTE on the memory profile: it materializes only the windowed displacement, so it
measures the *solver's* marginal memory — NOT production's footprint. Production
(``load_stack().load()`` + ``stack["displacement"].values``) holds the whole cube
resident; this tool isolates the solver on purpose.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.etl.stack import DEFAULT_ENGINE as _ENGINE, load_stack, save_stack

from . import velocity
from .stack import build_displacement_stack, load_disp_product_list


# --- the two solvers -------------------------------------------------------


def shipped_velocity(stack: xr.Dataset) -> np.ndarray:
    """The shipped solver — analysis.werc.velocity.estimate_velocity_linear."""
    return velocity.estimate_velocity_linear(stack).values


def notebook_lstsq(stack: xr.Dataset) -> np.ndarray:
    """Independent re-implementation of the notebook's cell-24 lstsq (the reference
    the shipped solver must match)."""
    disp = stack["displacement"].values
    times = stack["time"].values
    nt, ny, nx = disp.shape
    tdec = velocity.decimal_year(times)
    design = np.vstack([tdec, np.ones_like(tdec)]).T
    coef, *_ = np.linalg.lstsq(design, disp.reshape(nt, -1), rcond=None)
    return coef[0].reshape(ny, nx).astype(np.float32)


# --- metrics ---------------------------------------------------------------


def diff_metrics(closed: np.ndarray, ref: np.ndarray) -> dict[str, Any]:
    """Compare two velocity grids on the pixels where both are finite."""
    both_finite = np.isfinite(closed) & np.isfinite(ref)
    n_finite = int(both_finite.sum())
    if n_finite:
        d = np.abs(closed[both_finite] - ref[both_finite])
        max_abs, mean_abs = float(d.max()), float(d.mean())
    else:
        max_abs = mean_abs = 0.0
    # Pixels finite in one solver but not the other (should be zero).
    nan_disagree = int((np.isfinite(closed) ^ np.isfinite(ref)).sum())
    return {
        "n_finite": n_finite,
        "max_abs_diff": max_abs,
        "mean_abs_diff": mean_abs,
        "nan_disagreement": nan_disagree,
    }


# --- peak-RSS measurement (clean child process per method) -----------------


def _rss_to_mb(ru_maxrss: int) -> float:
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    return ru_maxrss / (1024 ** 2) if sys.platform == "darwin" else ru_maxrss / 1024


def _current_rss_mb() -> float:
    """Current (not high-water) resident set size in MB. Linux /proc; else ru_maxrss."""
    try:
        import os
        with open("/proc/self/statm") as fh:
            resident_pages = int(fh.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 ** 2)
    except Exception:
        import resource
        return _rss_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _measure_child(q: "mp.Queue", stack_path: str, window: dict) -> None:
    """Measure the shipped solver's *marginal* memory in a fresh process.

    Open lazily and materialize ONLY the windowed displacement into a minimal
    Dataset, so the baseline scales with the cube and doesn't dominate. Report
    ``solver_mb`` = peak RSS during the solve minus the post-load baseline — the
    memory the solver itself adds (its float64 upcast + gelsd workspace).
    Measuring absolute peak instead lets the load mask the solver's growth.
    """
    import resource

    import xarray as xr

    ds = xr.open_dataset(stack_path, engine=_ENGINE)  # lazy — nothing materialized yet
    sub = ds.isel(time=slice(*window["t"]), y=slice(*window["y"]), x=slice(*window["x"]))
    mini = xr.Dataset(
        {"displacement": sub["displacement"]},
        coords={"time": sub["time"], "y": sub["y"], "x": sub["x"]},
    )
    mini["displacement"].load()  # materialize ONLY this window's displacement (float32)
    baseline = _current_rss_mb()

    t0 = time.perf_counter()
    out = shipped_velocity(mini)
    elapsed = time.perf_counter() - t0
    _ = float(np.nansum(out))  # touch result so it isn't optimized away

    peak = _rss_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    q.put({
        "elapsed_s": elapsed,
        "baseline_mb": baseline,
        "peak_rss_mb": peak,
        "solver_mb": max(0.0, peak - baseline),  # marginal memory the solver adds
    })


def peak_rss(stack_path: str, window: dict) -> dict[str, float]:
    """Run the shipped solver in a fresh process; return wall time + its marginal RSS (MB)."""
    ctx = mp.get_context("spawn")  # fresh interpreter -> clean measurement
    q: "mp.Queue" = ctx.Queue()
    p = ctx.Process(target=_measure_child, args=(q, stack_path, window))
    p.start()
    p.join()
    if p.exitcode != 0:
        return {"elapsed_s": float("nan"), "solver_mb": float("nan"), "died": p.exitcode}
    return q.get()


# --- stack loading / variants ----------------------------------------------


def _load_or_build_stack(args: argparse.Namespace) -> xr.Dataset:
    if args.stack:
        return load_stack(args.stack)
    if args.netcdf_dir:
        disp_df = load_disp_product_list(args.netcdf_dir)
        if disp_df.empty:
            raise SystemExit(f"No DISP-S1 NetCDFs found in {args.netcdf_dir}.")
        return build_displacement_stack(disp_df)
    raise SystemExit("Provide --stack, --netcdf-dir, or --synthetic.")


def _synthetic_stack(nt: int = 120, ny: int = 600, nx: int = 600, seed: int = 0) -> xr.Dataset:
    """A small real-shaped stack: linear subsidence + noise + NaN holes."""
    rng = np.random.default_rng(seed)
    times = np.array(
        [np.datetime64("2016-09-01") + np.timedelta64(12 * i, "D") for i in range(nt)]
    )
    tdec = velocity.decimal_year(times)
    rate = rng.uniform(-0.05, 0.01, size=(ny, nx)).astype(np.float32)  # m/yr
    disp = (rate[None] * (tdec - tdec[0])[:, None, None]).astype(np.float32)
    disp += rng.normal(0, 0.002, size=disp.shape).astype(np.float32)
    holes = rng.random((ny, nx)) < 0.05
    disp[:, holes] = np.nan  # masked pixels -> NaN columns
    return xr.Dataset(
        {"displacement": (("time", "y", "x"), disp)},
        coords={"time": times, "y": np.arange(ny), "x": np.arange(nx)},
    )


def _variants(stack: xr.Dataset, fractions: list[float], time_fractions: list[float]):
    """Yield (label, window-dict) for center-cropped spatial + leading-time subsets."""
    nt = stack.sizes["time"]
    ny = stack.sizes["y"]
    nx = stack.sizes["x"]
    for tf in time_fractions:
        t_keep = max(2, int(round(nt * tf)))
        for f in fractions:
            ky = max(3, int(round(ny * f)))
            kx = max(3, int(round(nx * f)))
            y0 = (ny - ky) // 2
            x0 = (nx - kx) // 2
            window = {"t": (0, t_keep), "y": (y0, y0 + ky), "x": (x0, x0 + kx)}
            label = f"t{t_keep}_{ky}x{kx}"
            yield label, window


# --- main ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--stack", help="Prebuilt displacement stack NetCDF.")
    src.add_argument("--netcdf-dir", help="Directory of OPERA DISP-S1 NetCDFs (built into a stack).")
    src.add_argument("--synthetic", action="store_true", help="Use a synthetic stack (no real data).")
    p.add_argument("--fractions", default="1,0.5,0.25", help="Spatial size fractions (comma-sep).")
    p.add_argument("--time-fractions", default="1", help="Temporal size fractions (comma-sep).")
    p.add_argument("--memory", action="store_true", help="Also measure per-method peak RSS in a child process.")
    p.add_argument("--tol", type=float, default=1e-5, help="Max |Δ| (m/yr) allowed between solvers (pass/fail).")
    p.add_argument("--report-out", help="Write the full report as JSON to this path.")
    args = p.parse_args(argv)

    fractions = [float(x) for x in args.fractions.split(",") if x.strip()]
    time_fractions = [float(x) for x in args.time_fractions.split(",") if x.strip()]

    stack = _synthetic_stack() if args.synthetic else _load_or_build_stack(args)

    # The memory pass reloads the stack per child, so it needs a path. Persist a
    # synthetic/just-built stack to a temp file once.
    stack_path = args.stack
    tmp_path = None
    if args.memory and not stack_path:
        tmp_path = Path(args.netcdf_dir or ".") / "_velocity_check_stack.nc"
        save_stack(stack, tmp_path)
        stack_path = str(tmp_path)

    rows: list[dict[str, Any]] = []
    ok = True
    for label, window in _variants(stack, fractions, time_fractions):
        sub = stack.isel(
            time=slice(*window["t"]), y=slice(*window["y"]), x=slice(*window["x"])
        )
        nt, ny, nx = (sub.sizes["time"], sub.sizes["y"], sub.sizes["x"])

        t0 = time.perf_counter()
        shipped = shipped_velocity(sub)
        shipped_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        ref = notebook_lstsq(sub)
        notebook_s = time.perf_counter() - t0

        row: dict[str, Any] = {
            "variant": label, "nt": nt, "ny": ny, "nx": nx, "npix": ny * nx,
            "shipped_s_inproc": round(shipped_s, 3), "notebook_s_inproc": round(notebook_s, 3),
            **diff_metrics(shipped, ref),
        }
        row["pass"] = row["max_abs_diff"] <= args.tol and row["nan_disagreement"] == 0
        ok = ok and row["pass"]

        if args.memory and stack_path:
            row["mem"] = peak_rss(stack_path, window)

        rows.append(row)

    if tmp_path and tmp_path.exists():
        tmp_path.unlink()

    # --- report ---
    print("\n===== WERC velocity solver: shipped vs notebook cell-24 lstsq =====")
    src_label = "synthetic" if args.synthetic else (args.stack or args.netcdf_dir)
    print(f"source: {src_label}   tol: {args.tol:g} m/yr\n")
    hdr = f"{'variant':>14} {'nt':>4} {'pixels':>12} {'maxΔ(m/yr)':>12} {'meanΔ':>10} {'shipped_s':>10} {'notebk_s':>9}"
    if args.memory:
        # Marginal memory the solver ADDS over the loaded displacement (MB). The
        # solver is lstsq (matches the notebook), so this grows ~nt×npix×8 bytes
        # for its float64 copy — your OOM signal for big cubes.
        hdr += f" {'solverΔMB':>10}"
    hdr += "  result"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        line = (f"{r['variant']:>14} {r['nt']:>4} {r['npix']:>12,} "
                f"{r['max_abs_diff']:>12.2e} {r['mean_abs_diff']:>10.2e} "
                f"{r['shipped_s_inproc']:>10} {r['notebook_s_inproc']:>9}")
        if args.memory:
            mb = r.get("mem", {}).get("solver_mb", float("nan"))
            line += f" {mb:>10.0f}"
        line += "   PASS" if r["pass"] else "   FAIL"
        print(line)
    if args.memory:
        print("\n(solverΔMB = memory the lstsq solver adds beyond the loaded "
              "displacement; grows ~nt×npix×8 bytes for its float64 copy.)")

    if args.report_out:
        Path(args.report_out).write_text(json.dumps(
            {"source": src_label, "tol": args.tol, "platform": sys.platform, "rows": rows},
            indent=2,
        ))
        print(f"\nReport written to {args.report_out}")

    print("\nRESULT:", "ALL EQUIVALENT ✓" if ok else "MISMATCH ✗ (see FAIL rows)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
