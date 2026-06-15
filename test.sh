#!/usr/bin/env bash
#
# Run the SUBSIDE WERC tests/benchmarks.
#
# Intended for an ls6 idev node (the `vm-small` queue, 128 GB / 16 cores — the
# production box) in the `subside-werc-opera` conda env, but runs anywhere the
# env + deps exist.
#
#   idev -A <ALLOCATION> -p vm-small -N 1 -n 1 -t 01:00:00
#   conda activate subside-werc-opera        # or let this script do it
#   ./test.sh                                # synthetic equivalence (no data/network)
#   ./test.sh /path/to/stack.nc              # + real-data equivalence + per-method memory
#   NETCDF_DIR=output/OPERA_L3_DISP-S1 ./test.sh
#
# Optional env vars:
#   CONDA_ENV   conda env to activate (default: subside-werc-opera)
#   PYTHON      python executable (default: python)
#   STACK       real displacement-stack NetCDF (same as the positional arg)
#   NETCDF_DIR  directory of OPERA DISP-S1 NetCDFs (built into a stack)
#   FRACTIONS   spatial size fractions for the velocity sweep (default: 1,0.5,0.25)
#   TOL         max |Δ| (m/yr) allowed between solvers (default: 1e-5)
#
# Exit code is non-zero if any test fails (the velocity solver report gates it),
# so this is safe to use as a CI/idev pass-fail check.

set -euo pipefail

# This script lives in subside/; run from here so `analysis` is importable.
cd "$(dirname "$0")"

CONDA_ENV="${CONDA_ENV:-werc}"
PY="${PYTHON:-python}"
FRACTIONS="${FRACTIONS:-1,0.5,0.25}"
TOL="${TOL:-1e-5}"
STACK="${1:-${STACK:-}}"
NETCDF_DIR="${NETCDF_DIR:-}"

# One input drives both the ls6 pytest tests and the velocity_check real-data
# stage: the ls6 tests read WERC_TEST_NETCDF_DIR, so default it to NETCDF_DIR.
# (They need a *directory* of NetCDFs; a bare --stack file won't trigger them.)
export WERC_TEST_NETCDF_DIR="${WERC_TEST_NETCDF_DIR:-$NETCDF_DIR}"

# Fail fast with a clear message if a real-data input was given but has no data,
# instead of a confusing "skipped" (stage 2) + late abort (stage 5).
if [ -n "$NETCDF_DIR" ] && ! ls "$NETCDF_DIR"/*.nc >/dev/null 2>&1; then
  echo "ERROR: NETCDF_DIR='$NETCDF_DIR' has no *.nc files (looked under $PWD)." >&2
  echo "       Point it at a directory of OPERA DISP-S1 NetCDFs — an absolute path is safest." >&2
  echo "       Find candidates:  find \"\$SCRATCH\" \"\$WORK\" -name '*DISP-S1*.nc' 2>/dev/null | head" >&2
  exit 1
fi
if [ -n "$STACK" ] && [ ! -f "$STACK" ]; then
  echo "ERROR: STACK='$STACK' not found (looked under $PWD). Use an absolute path." >&2
  exit 1
fi

# Activate the conda env if it isn't already active and conda is on PATH.
if [ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ] && command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
fi

# Run pytest tolerating exit code 5 ("no tests collected" for a marker selection)
# but failing on real test failures — so an empty selection never aborts the run.
run_pytest() {
  local rc=0
  $PY -m pytest "$@" || rc=$?
  if [ "$rc" -eq 5 ]; then echo "  (no tests collected for this selection — ok)"; return 0; fi
  return "$rc"
}

echo "================================================================"
echo " SUBSIDE WERC tests"
echo "   python : $($PY -V 2>&1)   ($(command -v "$PY"))"
echo "   env    : ${CONDA_DEFAULT_ENV:-<none>}"
echo "   cwd    : $PWD"
echo "================================================================"

# 0) Fast unit suite (the same set GitHub Actions runs) — quick sanity first.
echo
echo "### 1/5  fast unit tests (pytest -m 'not ls6 and not integration') ###"
run_pytest -m "not ls6 and not integration" -q

# 0b) Whole-flow tests that need real data/compute — ls6 only. Driven by env
#     vars (e.g. WERC_TEST_NETCDF_DIR); they self-skip if inputs aren't set.
echo
echo "### 2/5  whole-flow tests (pytest -m ls6) ###"
run_pytest -m ls6 -q

# 1) Fast fail: import the modules we changed (catches syntax/import breakage).
echo
echo "### 3/5  import check ###"
$PY - <<'PYCODE'
import importlib
mods = [
    "analysis.werc.velocity", "analysis.werc.reference", "analysis.werc.runner",
    "analysis.werc.export", "analysis.werc.config", "analysis.werc.velocity_check",
    "analysis.h2i_lab.runner", "analysis.h2i_lab.download",
]
for m in mods:
    importlib.import_module(m)
    print("  ok", m)
PYCODE

# 2) Velocity solver equivalence — synthetic, no data/network needed.
echo
echo "### 4/5  velocity solver: synthetic faithfulness (shipped vs notebook lstsq) ###"
$PY -m analysis.werc.velocity_check --synthetic --fractions "$FRACTIONS" --tol "$TOL"

# 3) Velocity solver on REAL data + per-method peak memory, if a stack/dir is given.
echo
echo "### 5/5  velocity solver: real data + memory ###"
if [ -n "$STACK" ]; then
  $PY -m analysis.werc.velocity_check --stack "$STACK" --memory \
      --fractions "$FRACTIONS" --tol "$TOL" --report-out velreport.json
elif [ -n "$NETCDF_DIR" ]; then
  $PY -m analysis.werc.velocity_check --netcdf-dir "$NETCDF_DIR" --memory \
      --fractions "$FRACTIONS" --tol "$TOL" --report-out velreport.json
else
  echo "  (skipped — pass a stack NetCDF as the first arg, or set NETCDF_DIR,"
  echo "   to run the real-data equivalence + memory comparison.)"
fi

echo
echo "================================================================"
echo " ALL TESTS PASSED"
echo "================================================================"
