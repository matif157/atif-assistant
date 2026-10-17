"""Mail importer (propose-then-approve).

Reads the per-account Envelope Index sqlite under ~/Library/Mail (subjects,
senders, dates). Dates there are nanoseconds since 2001-01-01. Mailbox files
that are not readable simply produce zero candidates.
"""
from __future__ import annotations

from glob import glob
from pathlib import Path
from typing import Any

from ._common import (
    TITLE_COLS,
    candidate,
    columns,
    find_table,
    open_ro,
    pick,
    respond,
    when_iso,
)

MAIL_ROOT = Path.home() / "Library/Mail"
ENVELOPE_GLOB = "V*/Mailboxes/*/Envelope Index"


def find_db() -> Path | None:
    if not MAIL_ROOT.is_dir():
        return None
    hits = sorted(glob(str(MAIL_ROOT / ENVELOPE_GLOB)))
    return Path(hits[0]) if hits else None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("Mail Envelope Index not found")
    conn = open_ro(db_path)
    try:
        table = find_table(
            conn,
            hints=("message",),
            needs=("subject", "title"),
            avoid=("attachment", "message_link", "gmail", "mailbox"),
        )
        if table is None:
            return respond([], limit)
        cols = columns(conn, table)
        subject = pick(cols, ("subject",))
        sender = pick(cols, ("sender", "sender_address", "from"))
        when = pick(cols, ("date_sent", "date", "received"))
        if subject is None:
            return respond([], limit)
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            title = str(r[subject] or "").strip()
            if not title:
                continue
            detail = str(r[sender]).strip() if sender and r[sender] else None
            iso = when_iso(r[when], epoch="apple_ns") if when else None
            candidates.append(candidate(r["rowid"], title, detail, iso, kind="mail"))
        candidates.sort(key=lambda c: c["when"] or "9999")
        return respond(candidates, limit)
    finally:
        conn.close()
