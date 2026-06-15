"""Dump the SUBSIDE API's OpenAPI spec to a file — the published API reference.

The live API always serves interactive docs at ``/api/v1/docs`` (Swagger) and
``/redoc`` (ReDoc), plus the raw spec at ``/openapi.json``. This script writes
that same spec to disk without a running server, so it can be committed/published
(e.g. rendered with ReDoc or checked in as ``docs/openapi.json``).

    python api/scripts/export_openapi.py            # -> docs/openapi.json
    python api/scripts/export_openapi.py out.json   # custom path
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Import the app without starting a server.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.main import app  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[0]) if argv else Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = app.openapi()
    out.write_text(json.dumps(spec, indent=2))
    paths = len(spec.get("paths", {}))
    tags = [t["name"] for t in spec.get("tags", [])]
    print(f"wrote {out}  ({paths} paths, tags: {', '.join(tags)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
