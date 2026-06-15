"""Configuration objects for the H2I Lab OPERA workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


DEFAULT_FRAMES_INDEX_URL = (
    "https://raw.githubusercontent.com/OPERA-Cal-Val/OPERA_Applications/"
    "refs/heads/main/DISP/Discover/Frames_Information.geojson"
)


@dataclass(frozen=True)
class H2IRunConfig:
    """Normalized config shared by local, Tapis app, and workflow runs."""

    start_date: str
    end_date: str
    output_dir: str = "outputs"
    results_dir: str = "OPERA_L3_DISP-S1"
    num_workers: int = 4
    aoi_geojson_path: str | None = None
    aoi_shapefile_path: str | None = None
    bbox: list[float] | None = None
    frame_ids: list[int] = field(default_factory=list)
    min_overlap_percent: float = 50.0
    frames_index_url: str = DEFAULT_FRAMES_INDEX_URL
    frames_index_path: str | None = None
    require_products: bool = True
    preview_only: bool = False
    archive_name: str | None = None
    # Restrict discovery to a SINGLE OPERA frame (the one with the greatest AOI
    # overlap). WERC forces this on: its stack/velocity assume one frame's grid,
    # so mixing frames (e.g. ascending+descending) would be invalid. H2I leaves
    # it off and keeps every overlapping frame.
    single_frame: bool = False
    # Download tuning (see analysis/h2i_lab/benchmark.py; defaults chosen from
    # an ls6 vm-small ablation over 32 products):
    #   bbox_mode="prime" (default): download urls[0] once, reuse it for the
    #     pixel bbox AND as the first cropped output. ~1.5x faster than the
    #     legacy "sample" mode, which re-downloaded urls[0] in the worker pool.
    #   remote_subset (default off): HTTP range-read only the AOI chunks. Sound
    #     in theory but measured ~17x SLOWER on ls6 (latency-bound: every block
    #     re-pays the cumulus->URS->S3 redirect). Kept for research, off in prod.
    # num_workers default is 4: production downloads via `opera-utils disp-s1-download`,
    # whose parallel workers each open a TLS session to the DAAC — 8 raised the rate
    # of transient `ssl.SSLError` aborts, so 4 trades a little throughput for fewer
    # failed downloads. (The bespoke benchmark path measured 8 as the throughput
    # sweet spot at ~97 MB/s; that path is no longer used in production.)
    bbox_mode: str = "prime"
    remote_subset: bool = False
    # Cap the number of products downloaded (None = all). Handy for quick,
    # bounded benchmark/stress runs without widening the date range.
    max_products: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "H2IRunConfig":
        if not payload.get("start_date"):
            raise ValueError("Missing required start_date.")
        if not payload.get("end_date"):
            raise ValueError("Missing required end_date.")
        frame_ids = [int(value) for value in payload.get("frame_ids", [])]
        bbox = payload.get("bbox")
        if bbox is not None:
            bbox = [float(value) for value in bbox]
            if len(bbox) != 4:
                raise ValueError("bbox must contain [lon_min, lat_min, lon_max, lat_max].")
        return cls(
            start_date=str(payload["start_date"]),
            end_date=str(payload["end_date"]),
            output_dir=str(payload.get("output_dir") or "outputs"),
            results_dir=str(payload.get("results_dir") or "OPERA_L3_DISP-S1"),
            num_workers=int(payload.get("num_workers") or 4),
            aoi_geojson_path=payload.get("aoi_geojson_path"),
            aoi_shapefile_path=payload.get("aoi_shapefile_path"),
            bbox=bbox,
            frame_ids=frame_ids,
            min_overlap_percent=float(payload.get("min_overlap_percent") or 50.0),
            frames_index_url=str(payload.get("frames_index_url") or DEFAULT_FRAMES_INDEX_URL),
            frames_index_path=payload.get("frames_index_path"),
            require_products=bool(payload.get("require_products", True)),
            preview_only=bool(payload.get("preview_only", False)),
            archive_name=payload.get("archive_name"),
            single_frame=bool(payload.get("single_frame", False)),
            bbox_mode=str(payload.get("bbox_mode") or "prime"),
            remote_subset=bool(payload.get("remote_subset", False)),
            max_products=(int(payload["max_products"]) if payload.get("max_products") else None),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "H2IRunConfig":
        with Path(path).open() as stream:
            return cls.from_dict(json.load(stream))

    def output_path(self) -> Path:
        return Path(self.output_dir)

    def results_path(self) -> Path:
        return self.output_path() / self.results_dir

    def to_manifest_config(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "bbox": self.bbox,
            "frame_ids": self.frame_ids,
            "num_workers": self.num_workers,
            "min_overlap_percent": self.min_overlap_percent,
            "preview_only": self.preview_only,
            "bbox_mode": self.bbox_mode,
            "remote_subset": self.remote_subset,
            "single_frame": self.single_frame,
        }

