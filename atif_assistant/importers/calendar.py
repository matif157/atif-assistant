"""Calendar importer (propose-then-approve).

Reads ~/Library/Calendar/Calendar.sqlitedb for event titles and start times.
Schemas drift by macOS version, so the event table is found by role: a table
named like an event store that has a title-ish and a date-ish column.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import (
    TITLE_COLS,
    WHEN_COLS,
    candidate,
    columns,
    find_table,
    open_ro,
    pick,
    respond,
    when_iso,
)

CAL_DB = Path.home() / "Library/Calendar/Calendar.sqlitedb"


def find_db() -> Path | None:
    return CAL_DB if CAL_DB.exists() else None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("Calendar.sqlitedb not found")
    conn = open_ro(db_path)
    try:
        table = find_table(
            conn,
            hints=("ekevent", "event"),
            needs=TITLE_COLS,
            avoid=("exception", "recurrence", "notification", "calendaritem"),
        )
        if table is None:
            return respond([], limit)
        cols = columns(conn, table)
        tcol = pick(cols, TITLE_COLS)
        wcol = pick(cols, WHEN_COLS)
        if tcol is None:
            return respond([], limit)
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            title = str(r[tcol] or "").strip()
            if not title:
                continue
            when = when_iso(r[wcol]) if wcol else None
            candidates.append(candidate(r["rowid"], title, when=when, kind="calendar"))
        candidates.sort(key=lambda c: c["when"] or "9999")
        return respond(candidates, limit)
    finally:
        conn.close()
