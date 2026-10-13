"""Apple Mail importer - placeholder (propose-then-approve).

Mail is usually stored in ~/Library/Mail/V10 or similar; reading
full mailboxes requires care. This returns empty until implemented.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MAIL_ROOT = Path.home() / "Library/Mail"


def find_db() -> Path | None:
    # Mail uses EMLX files, not a single simple sqlite for all in all cases
    return MAIL_ROOT if MAIL_ROOT.exists() else None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("Mail directory not found")
    # TODO: implement EMLX/SQLite scanning with propose-then-approve
    return {"count": 0, "candidates": [], "truncated": False}
