"""Photos importer (propose-then-approve).

Reads the Photos library database for album titles (with asset counts when
the album link table is present). Photos itself is never copied - only
titles and counts become candidates for approval.
"""
from __future__ import annotations

from glob import glob
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

PIC_ROOT = Path.home() / "Pictures"
PHOTOS_GLOB = "*.photoslibrary/database/photos.sqlite"


def find_db() -> Path | None:
    if not PIC_ROOT.is_dir():
        return None
    hits = sorted(glob(str(PIC_ROOT / PHOTOS_GLOB)))
    return Path(hits[0]) if hits else None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("Photos library database not found")
    conn = open_ro(db_path)
    try:
        album = find_table(
            conn,
            hints=("genericalbum", "album"),
            needs=("ztitle",),
            avoid=("virtual", "delete"),
        )
        if album is None:
            # A stripped library (or an older schema) may have no album
            # table: fall back to dated asset rows so the source still
            # previews something real.
            return respond(import_assets(db_path, limit=limit), limit)
        cols = columns(conn, album)
        title = pick(cols, ("ztitle",))
        if title is None:
            return respond([], limit)

        # Asset counts come from the album<->asset link table when present.
        counts: dict[str, int] = {}
        link = find_table(conn, hints=("_3assets", "_3albums", "albumasset"), needs=())
        if link is not None:
            lcols = columns(conn, link)
            a_col = next((c for c in lcols if c.lower() in ("_3albums", "album_id")), None)
            s_col = next((c for c in lcols if c.lower() in ("_3assets", "asset_id")), None)
            if a_col and s_col:
                for row in conn.execute(
                    f'SELECT "{a_col}" AS a, COUNT("{s_col}") AS n FROM "{link}" GROUP BY "{a_col}"'
                ):
                    counts[str(row["a"])] = int(row["n"])

        rows = conn.execute(f'SELECT rowid AS _rid, * FROM "{album}"').fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            name = str(r[title] or "").strip()
            if not name:
                continue
            n = counts.get(str(r["_rid"]))
            detail = f"{n} photo{'s' if n != 1 else ''}" if n else None
            candidates.append(candidate(r["_rid"], name, detail, kind="photos"))
        return respond(candidates, limit)
    finally:
        conn.close()


def import_assets(db_path: Path, limit: int = 100, epoch: str = "apple") -> list[dict[str, Any]]:
    """Recent assets as candidates (fallback when the library has no albums)."""
    conn = open_ro(db_path)
    try:
        table = find_table(conn, hints=("zasset", "asset"), needs=WHEN_COLS)
        if table is None:
            return []
        cols = columns(conn, table)
        when = pick(cols, WHEN_COLS)
        loc = pick(cols, ("zlocation", "location"))
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY "{when}" DESC LIMIT ?', (limit,)).fetchall()
        out = []
        for r in rows:
            iso = when_iso(r[when], epoch=epoch) if when else None
            out.append(candidate(r["rowid"], iso or "photo", str(r[loc]) if loc and r[loc] else None, iso, kind="photos"))
        return out
    finally:
        conn.close()
