"""macOS Messages (SMS/iMessage) importer - read-only, propose-then-approve.

Reads ~/Library/Messages/chat.db. May require Full Disk Access depending on
execution context; returns candidates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sqlite3

MSG_DB = Path.home() / "Library/Messages/chat.db"


def _apple_to_utc(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    try:
        # Messages uses Apple epoch (2001-01-01)
        core_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
        dt = core_epoch + __import__("timedelta")(seconds=epoch)
        return dt.isoformat()
    except Exception:
        return None


def find_db() -> Path | None:
    return MSG_DB if MSG_DB.exists() else None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("Messages chat.db not found")
    candidates: list[dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Simple query: join chat/message for text messages
        rows = conn.execute("""
            SELECT c.display_name, c.chat_identifier, m.is_from_me, m.date, m.text
            FROM message m
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.text IS NOT NULL AND m.text != ''
            ORDER BY m.date
        """).fetchall()
        for r in rows:
            text = str(r["text"]).strip()
            if not text:
                continue
            candidates.append(
                {
                    "chat_name": r["display_name"] or r["chat_identifier"] or "chat",
                    "from_me": bool(r["is_from_me"]),
                    "when": _apple_to_utc(r["date"]),
                    "text": text,
                    "kind": "messages",
                }
            )
    finally:
        conn.close()
    if limit > 0:
        res = {"count": len(candidates), "candidates": candidates[:limit]}
        res["truncated"] = len(candidates) > limit
        return res
    return {"count": len(candidates), "candidates": candidates}
