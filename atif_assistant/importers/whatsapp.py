"""WhatsApp Desktop (macOS) importer.

Reads ChatStorage.sqlite from the user's Group Containers and extracts
messages. This is read-only and returns candidate items for review.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Common paths for WhatsApp Desktop on macOS
WHATSAPP_PATHS = [
    Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite",
    Path.home() / "Library/Containers/net.whatsapp.WhatsApp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite",
    Path.home() / "Library/Application Support/WhatsApp/ChatStorage.sqlite",
]


def _apple_to_utc(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    # WhatsApp Desktop timestamps are often in Apple Core Data time
    # (seconds since 2001-01-01) or Unix time. Try to detect.
    try:
        if epoch > 1_000_000_000_000:  # ms
            dt = datetime.fromtimestamp(epoch / 1000, tz=timezone.utc)
            return dt.isoformat()
        if epoch > 10_000_000_000:  # seconds since 2001? unlikely; treat as unix
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.isoformat()
        # Core Data: 2001-01-01 epoch
        core_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
        dt = core_epoch + __import__("timedelta")(seconds=epoch)
        return dt.isoformat()
    except Exception:
        return None


def _extract_from_path(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    candidates: list[dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Get chats
        chats = conn.execute("SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID, ZSESSIONTYPE FROM ZWACHATSESSION").fetchall()
        for chat in chats:
            chat_id = chat["Z_PK"]
            chat_name = chat["ZPARTNERNAME"] or chat["ZCONTACTJID"] or f"chat-{chat_id}"
            # Get messages (text only, type 0 is text in many WA schemas)
            msgs = conn.execute(
                """SELECT Z_PK, ZTEXT, ZISFROMME, ZMESSAGEDATE, ZFROMJID, ZTOJID, ZMESSAGETYPE
                   FROM ZWAMESSAGE
                   WHERE ZCHATSESSION = ? AND ZTEXT IS NOT NULL AND ZTEXT != ''
                   ORDER BY ZMESSAGEDATE""",
                (chat_id,),
            ).fetchall()
            for m in msgs:
                text = str(m["ZTEXT"]).strip()
                if not text:
                    continue
                when = _apple_to_utc(m["ZMESSAGEDATE"])
                from_me = bool(m["ZISFROMME"])
                candidates.append(
                    {
                        "chat_id": chat_id,
                        "chat_name": chat_name,
                        "msg_id": m["Z_PK"],
                        "text": text,
                        "from_me": from_me,
                        "when": when,
                        "kind": "whatsapp",
                    }
                )
    finally:
        conn.close()
    return {"count": len(candidates), "candidates": candidates}


def find_db() -> Path | None:
    for p in WHATSAPP_PATHS:
        if p.exists():
            return p
    return None


def import_from_db(db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("WhatsApp ChatStorage.sqlite not found")
    res = _extract_from_path(db_path)
    if limit > 0:
        res["candidates"] = res["candidates"][:limit]
        res["truncated"] = len(res["candidates"]) < res["count"]
    return res
