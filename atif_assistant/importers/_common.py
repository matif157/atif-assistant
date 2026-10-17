"""Shared read-only primitives for the five light importers (Phase 6).

Each source lives in a sqlite file whose exact schema drifts across macOS
versions, so parsers name columns by *role* (title / detail / when) and pick
whatever the installed file actually has. A file that does not match yields
zero candidates instead of crashing - Full Disk Access can also block the
read, which is a skip, not an error.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Role lookup lists, checked in order, matched case-insensitively.
TITLE_COLS = (
    "ztitle", "summary", "title", "subject", "display_name", "name",
    "label", "body", "text", "content",
)
DETAIL_COLS = (
    "zsnippet", "snippet", "detail", "zorganization", "organization",
    "sender", "sender_address", "value", "address", "email", "phone",
    "location", "note",
)
WHEN_COLS = (
    "zcreationdate1", "zcreationdate", "zdatecreated", "date_sent",
    "created_at", "created", "start_date", "start", "due", "when",
    "timestamp", "date",
)

_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def open_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'Z_METADATA%'"
        " AND name NOT LIKE '\\_%' ESCAPE '\\'"
    ).fetchall()
    return [r["name"] for r in rows]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def pick(cols: list[str], role: tuple[str, ...]) -> str | None:
    """First role column present in the table, else None."""
    lower = {c.lower(): c for c in cols}
    for want in role:
        if want in lower:
            return lower[want]
    return None


def when_iso(value: Any, epoch: str = "apple") -> str | None:
    """Stored date -> ISO. Apple files count seconds (or nanoseconds, for
    Mail's Envelope Index) from 2001-01-01; ISO strings pass through."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if not isinstance(value, (int, float)):
        return None
    try:
        if epoch == "apple_ns":
            seconds = float(value) / 1e9
        elif epoch == "apple":
            seconds = float(value) / 1e9 if abs(float(value)) > 1e14 else float(value)
        else:  # unix seconds
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        return (_APPLE_EPOCH + timedelta(seconds=seconds)).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def find_table(
    conn: sqlite3.Connection,
    hints: tuple[str, ...] = (),
    needs: tuple[str, ...] = TITLE_COLS,
    avoid: tuple[str, ...] = (),
) -> str | None:
    """First table whose name matches a hint (or any table when no hints)
    and that carries at least one `needs` column. An empty `needs` accepts
    the name match alone (used to sniff out link tables)."""
    for table in user_tables(conn):
        low = table.lower()
        if any(a in low for a in avoid):
            continue
        if hints and not any(h in low for h in hints):
            continue
        if not needs or pick(columns(conn, table), needs):
            return table
    return None


def respond(candidates: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Uniform {count, candidates, truncated} envelope every importer keeps."""
    if limit > 0 and len(candidates) > limit:
        return {"count": len(candidates), "candidates": candidates[:limit], "truncated": True}
    return {"count": len(candidates), "candidates": candidates, "truncated": False}


def candidate(
    cid: Any,
    title: str,
    detail: str | None = None,
    when: str | None = None,
    kind: str = "",
) -> dict[str, Any]:
    return {
        "id": str(cid),
        "title": (title or "").strip(),
        "detail": (detail or "").strip() or None,
        "when": when,
        "kind": kind,
    }
