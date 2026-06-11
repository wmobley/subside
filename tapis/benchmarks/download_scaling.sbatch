#!/bin/bash
# Download-scaling benchmark on ls6 (vm-small): wall time vs file count (up to
# 100) and vs per-file transfer size (range, small window -> whole image), to
# refine analysis/h2i_lab/estimate.py.
#
# Submit WITH your allocation (vm-small needs one):
#   sbatch -A <ALLOCATION> tapis/benchmarks/download_scaling.sbatch
# Override the checkout location if needed:
#   SUBSIDE_DIR=/path/to/subside sbatch -A <ALLOCATION> .../download_scaling.sbatch
#
#SBATCH -J subside-dlbench
#SBATCH -p vm-small
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 01:30:00
#SBATCH -o dlbench-%j.out
#SBATCH -e dlbench-%j.err

set -euo pipefail

# --- repo location ---------------------------------------------------------
SUBSIDE_DIR="${SUBSIDE_DIR:-$WORK/subside}"
cd "$SUBSIDE_DIR"

# --- conda env (h5py / xarray / disp_xr / opera_utils) ---------------------
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate subside-h2i-opera

# --- thread pinning, same as production run.sh -----------------------------
export OMP_NUM_THREADS="${SLURM_CPUS_ON_NODE:-16}"
export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
export NUMEXPR_NUM_THREADS="$OMP_NUM_THREADS"
export GDAL_NUM_THREADS=ALL_CPUS

# --- Earthdata creds: ~/.netrc (urs.earthdata.nasa.gov) or EARTHDATA_* env --
if [ ! -f "$HOME/.netrc" ] && [ -z "${EARTHDATA_USERNAME:-}" ]; then
  echo "ERROR: need ~/.netrc with a urs.earthdata.nasa.gov entry, or EARTHDATA_USERNAME/PASSWORD." >&2
  exit 2
fi

OUT="${SCRATCH:-$PWD}/dlbench-${SLURM_JOB_ID:-local}"
echo "host=$(hostname) cores=$(nproc) threads=$OMP_NUM_THREADS out=$OUT"

# Count sweep up to 100 full products; size sweep dials per-file bytes via the
# crop window read over HTTP Range, up to the whole image ('full').
python -m analysis.h2i_lab.download_scaling \
  --aoi examples/sample_aoi.geojson \
  --start 2023-01-01 --end 2025-12-31 \
  --counts 2,10,25,50,100 \
  --windows 512,4096,full \
  --size-files 3 \
  --workers 8 --size-workers 4 \
  --output-root "$OUT"

echo "DONE -> $OUT/download-scaling-results.json"
