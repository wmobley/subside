---
title: Measure how fast it is sinking
pipeline: werc
lab: Water Engineering Research Center (WERC), UT Arlington
labUrl: https://werc.uta.edu/
source: https://doi.org/10.5281/zenodo.20116072
---
This analysis downloads OPERA DISP-S1 satellite radar for the area you draw and
turns it into a **velocity estimate — how fast the ground is moving, in mm/yr** —
along with the cumulative displacement time series behind it. Use it when you
need a measured *rate* of subsidence rather than a single snapshot.

### What you get

- A ground-velocity layer (mm/yr; negative = motion toward subsidence),
  GIS-ready.
- The cumulative displacement time series the rate is derived from.
- A 0–10 observed-risk banding driven by the fastest subsidence in your area.

### Coverage & data volume

OPERA DISP-S1 comes as fixed ~250 km **frame tiles**, each a full time series
(Sentinel-1, ~6–12 day revisit, 2016-07 to present). Velocity is fit on **one
frame's grid**, so this analysis uses a **single frame — the one with the
greatest overlap with your area**. If several frames overlap (e.g. an ascending
*and* a descending track), the others are skipped and noted; set **Frame IDs** to
choose a specific one. It then downloads that frame's products in your date
range, crops them to your area, builds the displacement stack, and fits the rate.

So the product count is just **the acquisitions in your date range for that one
frame** (~30/year at the 12-day revisit). A longer date range means more
products; a **wider area does not add frames** here — unlike the displacement
analysis, which keeps every overlapping frame. Mixing frames from different
viewing geometries into one velocity would be invalid, which is why this stays
single-frame (the source notebook works one frame at a time too).

To keep a run small, shorten the date range.

### Good to know

- **Use a multi-year time range.** OPERA DISP-S1 measurements are relative in
  both time and space, so velocity and cumulative displacement only become
  meaningful when the series is long enough to average over seasonal and
  atmospheric noise. Short windows can produce misleading rates.
- **Reference-point selection is still under active research.** The automated
  stability-based reference picking is an ongoing methodological development,
  not a finalized standard. Treat absolute values and cumulative displacement as
  best-effort estimates — cross-check with GNSS or independent measurements
  before drawing scientific conclusions.

### Method & credits

Prepared by the **Water Engineering Research Center (WERC), University of Texas
at Arlington** — Seyed Mostafa Banihashem, Daniel Li, William Mobley, Suzanne
Pierce, and Nick Fang. Extends the open-source
[OPERA Cal/Val](https://github.com/OPERA-Cal-Val) work.

- Source: WERC cookbook **[github.com/mosiwsp/tacc_werc_ls](https://github.com/mosiwsp/tacc_werc_ls)**
  — notebook *OPERA DISP-S1 Subsidence Analysis Notebook*.
- Citation: Banihashem, S. M., Li, D., Mobley, W., Pierce, S. A., & Fang, N.
  (2026). *OPERA DISP-S1 Subsidence Analysis Notebook* (0.0.1). Zenodo —
  [doi:10.5281/zenodo.20116072](https://doi.org/10.5281/zenodo.20116072).
