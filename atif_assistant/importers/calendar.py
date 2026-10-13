"""Calendar importer - placeholder."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def find_db() -> Path | None:
    return None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    return {"count": 0, "candidates": [], "truncated": False}
