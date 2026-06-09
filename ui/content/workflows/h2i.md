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

- Source notebook: *Mapping Ground Subsidence from Space — Automatic Discovery
  and Mapping of NASA OPERA Surface Displacement Data*
  ([examples/notebookExamples/OPERA Surface Displacement_05.11.2026.ipynb](../../examples/notebookExamples)).
- Data: NASA/JPL/OPERA, *OPERA Surface Displacement from Sentinel-1 validated
  product* (v1), via the Alaska Satellite Facility DAAC —
  [doi:10.5067/SNWG/OPL3DISPS1-V1](https://doi.org/10.5067/SNWG/OPL3DISPS1-V1).
