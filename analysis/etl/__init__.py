"""Reusable ETL primitives shared by SUBSIDE analyses.

These modules deliberately know nothing about OPERA DISP-S1 specifics —
the cross-cutting concerns (auth, AOI loading, manifest writing, NetCDF
stack save/load, archive helpers) live here so a second analysis
(other InSAR datasets, HLS, Sentinel-2) can drop them in directly.

OPERA-specific concerns (frame index, ASF / opera_utils product search,
DISP metadata, disp_xr stack assembly) stay in ``h2i_lab`` and ``werc``.
"""

from . import aoi, archive, auth, manifest, stack

__all__ = ["aoi", "archive", "auth", "manifest", "stack"]
