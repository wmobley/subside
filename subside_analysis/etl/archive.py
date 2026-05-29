"""Output archiving helpers shared by SUBSIDE pipelines."""

from __future__ import annotations

import shutil
from pathlib import Path


def archive_results(results_path: str | Path, archive_base_name: str | Path) -> Path:
    """Zip ``results_path`` into ``archive_base_name.zip`` and return the archive path."""

    archive_base = Path(archive_base_name)
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        shutil.make_archive(
            base_name=str(archive_base),
            format="zip",
            root_dir=str(Path(results_path).parent),
            base_dir=Path(results_path).name,
        )
    )
