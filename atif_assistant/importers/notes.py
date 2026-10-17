"""Notes importer (propose-then-approve).

Reads NoteStore.sqlite (Apple Notes). Notes live in ZICCLOUDSYNCINGOBJECT as
rows that carry a title (and, for real notes, a snippet); folder rows have no
snippet and are skipped. Creation dates are Apple-epoch seconds.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import candidate, columns, find_table, open_ro, pick, respond, when_iso

NOTES_DB = (
    Path.home()
    / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
)
NOTES_DB_ALT = Path.home() / "Library/Containers/com.apple.Notes/Data/Library/Notes/notes.sqlite"


def find_db() -> Path | None:
    for p in (NOTES_DB, NOTES_DB_ALT):
        if p.exists():
            return p
    return None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("NoteStore.sqlite not found")
    conn = open_ro(db_path)
    try:
        table = find_table(
            conn,
            hints=("iccloudsyncingobject", "note"),
            needs=("ztitle", "zsnippet"),
            avoid=("attachment", "media", "garbage"),
        )
        if table is None:
            return respond([], limit)
        cols = columns(conn, table)
        title = pick(cols, ("ztitle",))
        snippet = pick(cols, ("zsnippet",))
        created = pick(cols, ("zcreationdate1", "zcreationdate", "zcreationdate2"))
        if title is None:
            return respond([], limit)
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            text = str(r[title] or "").strip()
            if not text:
                continue
            # Folder/group rows also carry ZTITLE; a snippet marks a note.
            if snippet and not r[snippet]:
                continue
            detail = str(r[snippet]).strip() if snippet and r[snippet] else None
            when = when_iso(r[created]) if created else None
            candidates.append(candidate(r["rowid"], text, detail, when, kind="notes"))
        return respond(candidates, limit)
    finally:
        conn.close()
