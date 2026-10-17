"""Contacts importer (propose-then-approve).

Reads macOS AddressBook (a sqlite file per user account) for people and their
first reachable value. Full Disk Access may be required; a blocked read is a
zero-candidate result, never a crash.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import candidate, columns, find_table, open_ro, respond

AB_DIR = Path.home() / "Library/Application Support/AddressBook"
HINTS = ("addressbook", "abperson", ".abcddb")


def find_db() -> Path | None:
    if not AB_DIR.is_dir():
        return None
    for pattern in ("*.sqlitedb", "*.sqlite", "*.abcddb"):
        for p in sorted(AB_DIR.glob(pattern)):
            if p.is_file():
                return p
    return None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("AddressBook database not found")
    conn = open_ro(db_path)
    try:
        person = find_table(
            conn,
            hints=("abperson", "person"),
            needs=("first", "last", "zfirst", "name"),
        )
        if person is None:
            return respond([], limit)
        cols = columns(conn, person)
        first = _col(cols, "first", "zfirst")
        middle = _col(cols, "middle", "zmiddle")
        last = _col(cols, "last", "zlast")
        org = _col(cols, "organization", "zorganization", "org")
        rows = conn.execute(f'SELECT * FROM "{person}"').fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            parts = [r[c] for c in (first, middle, last) if c and r[c]]
            name = " ".join(str(p).strip() for p in parts if str(p).strip())
            if not name and org and r[org]:
                name = str(r[org]).strip()
            if not name:
                continue
            detail = str(r[org]).strip() if org and r[org] else None
            candidates.append(candidate(r["rowid"], name, detail, kind="contacts"))
        return respond(candidates, limit)
    finally:
        conn.close()


def _col(cols: list[str], *wanted: str) -> str | None:
    lower = {c.lower(): c for c in cols}
    for w in wanted:
        if w in lower:
            return lower[w]
    return None
