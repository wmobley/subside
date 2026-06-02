"""JSON manifest writer used by every SUBSIDE pipeline runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write ``payload`` to ``path`` as pretty-printed, sort-keyed JSON.

    Creates parent directories as needed. ``default=str`` so xarray /
    numpy / pathlib scalars serialize without a custom encoder.
    """

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, default=str)
    return output
