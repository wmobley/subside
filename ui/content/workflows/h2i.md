---
title: See surface displacement
pipeline: h2i
lab: Hydrology & Hydroinformatics Innovation (H2I) Lab
labUrl: https://www.adnanrajib.com/
source: https://www.hydroshare.org/resource/d98cc7ceebff4c15975f43dde371229e
---
This analysis searches, downloads, and maps **30-meter [OPERA Surface
Displacement (DISP-S1) products](https://www.earthdata.nasa.gov/about/nasa-support-snwg/solutions/opera-north-america-disp-product)**
for the area you draw. The products are derived from Sentinel-1 radar
acquisitions (2016-07 to present, 6–12 day revisit) and show how the ground
surface has moved over your chosen time range — a snapshot map of cumulative
displacement.

### What you get

- A cumulative surface-displacement map (GIS-ready GeoTIFF) for your area.
- Coverage anywhere OPERA DISP-S1 data exists across North America.
- New products are picked up automatically as NASA publishes them.

### Coverage & data volume

OPERA DISP-S1 is delivered as fixed ~250 km **frame tiles**, and each frame is a
full time series (Sentinel-1, ~6–12 day revisit, 2016-07 to present). The
analysis includes **every frame that overlaps your area by 50% or more** (of the
area you drew), downloads each matching product, and crops it to your area. If no
frame clears 50%, none are selected — widen or reposition your area.

So the number of products is **(overlapping frames) × (acquisitions in your date
range)**. An area imaged from more than one satellite track (ascending *and*
descending), or one straddling a frame boundary, pulls each frame's full stack —
so a wide area or a long time range can mean **hundreds of products and tens of
gigabytes**. Each product is the full frame (~420 MB) fetched and then cropped,
so download volume scales with frame count and window length, not with how small
your drawn area is.

To keep a run small, draw a tighter area or shorten the date range. Restricting
to a single frame (one viewing geometry) is possible via the **Frame IDs** run
parameter.

### Good to know

- **Pick a longer time range when you can.** DISP-S1 measurements are relative
  in time and space; a multi-year window averages out seasonal and atmospheric
  noise and gives a more reliable picture than a few months.
- Displacement is useful for detecting gradual land sinking — e.g. from
  groundwater extraction — and for assessing flood risk, infrastructure
  vulnerability, and long-term landscape stability.

### Method & credits

Developed by Qianjin Zheng, Shihab Uddin, Adnan Rajib, and Dipen Saha at the
**H2I Lab, University of Texas at Arlington**.

- Source: H2I Lab cookbook **[github.com/fazle0rabbi/h2i_lab](https://github.com/fazle0rabbi/h2i_lab)**
  — notebook *Mapping Ground Subsidence from Space: Automatic Discovery and
  Mapping of NASA OPERA Surface Displacement Data*.
- Data: NASA/JPL/OPERA, *OPERA Surface Displacement from Sentinel-1 validated
  product* (v1), via the Alaska Satellite Facility DAAC —
  [doi:10.5067/SNWG/OPL3DISPS1-V1](https://doi.org/10.5067/SNWG/OPL3DISPS1-V1).
