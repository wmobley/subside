"""Configuration objects for the WERC OPERA DISP-S1 workflow."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from subside_analysis.h2i_lab.config import H2IRunConfig


REFERENCE_MODES = ("auto", "manual", "none")


@dataclass(frozen=True)
class WercRunConfig:
    """Normalized config for the WERC stack/reference/velocity pipeline.

    Wraps an :class:`H2IRunConfig` for the discovery + download stage and
    adds the WERC-specific options for stack assembly, reference selection,
    velocity estimation, and raster export.
    """

    h2i: H2IRunConfig
    reference_mode: str = "auto"
    reference_lat: float | None = None
    reference_lon: float | None = None
    anchor_radius_m: int = 5000
    n_reference_pixels: int = 25
    anchor_dir: str | None = None
    skip_download: bool = False
    netcdf_dir: str | None = None
    displacement_geotiff_name: str | None = None
    velocity_geotiff_name: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WercRunConfig":
        mode = str(payload.get("reference_mode", "auto")).lower()
        if mode not in REFERENCE_MODES:
            raise ValueError(
                f"reference_mode must be one of {REFERENCE_MODES}, got {mode!r}."
            )
        if mode == "manual" and (
            payload.get("reference_lat") is None or payload.get("reference_lon") is None
        ):
            raise ValueError("Manual reference requires reference_lat and reference_lon.")

        if isinstance(payload.get("h2i"), dict):
            h2i_payload = payload["h2i"]
        else:
            h2i_fields = set(H2IRunConfig.__dataclass_fields__.keys())
            h2i_payload = {k: v for k, v in payload.items() if k in h2i_fields}

        return cls(
            h2i=H2IRunConfig.from_dict(h2i_payload),
            reference_mode=mode,
            reference_lat=(
                float(payload["reference_lat"])
                if payload.get("reference_lat") is not None else None
            ),
            reference_lon=(
                float(payload["reference_lon"])
                if payload.get("reference_lon") is not None else None
            ),
            anchor_radius_m=int(payload.get("anchor_radius_m", 5000)),
            n_reference_pixels=int(payload.get("n_reference_pixels", 25)),
            anchor_dir=payload.get("anchor_dir"),
            skip_download=bool(payload.get("skip_download", False)),
            netcdf_dir=payload.get("netcdf_dir"),
            displacement_geotiff_name=payload.get("displacement_geotiff_name"),
            velocity_geotiff_name=payload.get("velocity_geotiff_name"),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "WercRunConfig":
        with Path(path).open() as stream:
            return cls.from_dict(json.load(stream))

    def output_path(self) -> Path:
        return self.h2i.output_path()

    def anchor_path(self) -> Path:
        if self.anchor_dir:
            return Path(self.anchor_dir)
        return self.output_path() / "anchors"

    def to_manifest_config(self) -> dict[str, Any]:
        return {
            **self.h2i.to_manifest_config(),
            "reference_mode": self.reference_mode,
            "reference_lat": self.reference_lat,
            "reference_lon": self.reference_lon,
            "anchor_radius_m": self.anchor_radius_m,
            "n_reference_pixels": self.n_reference_pixels,
            "skip_download": self.skip_download,
            "netcdf_dir": self.netcdf_dir,
        }
