"""WhatsApp Desktop (macOS) importer.

Reads ChatStorage.sqlite from the user's Group Containers and extracts
messages. This is read-only and returns candidate items for review.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
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
        if epoch > 10_000_000_000:  # likely unix seconds
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.isoformat()
        # Core Data: 2001-01-01 epoch
        core_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
        dt = core_epoch + timedelta(seconds=epoch)
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


def get_status() -> dict[str, Any]:
    db_path = find_db()
    if not db_path:
        return {"exists": False, "chats": []}
    try:
        size = db_path.stat().st_size
    except Exception:
        size = None
    try:
        chats = get_chats(db_path)
    except Exception:
        chats = []
    return {"exists": True, "path": str(db_path), "size": size, "chats": chats}


def get_chats(db_path: Path | None = None) -> list[dict[str, Any]]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID, ZSESSIONTYPE FROM ZWACHATSESSION").fetchall()
        chats: list[dict[str, Any]] = []
        for chat in rows:
            chat_id = chat["Z_PK"]
            chat_name = chat["ZPARTNERNAME"] or chat["ZCONTACTJID"] or f"chat-{chat_id}"
            jid = chat["ZCONTACTJID"]
            session_type = chat["ZSESSIONTYPE"]
            try:
                c = conn.execute(
                    "SELECT COUNT(*) AS c FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND ZTEXT IS NOT NULL AND ZTEXT!=''",
                    (chat_id,),
                ).fetchone()
                msg_count = int(c["c"]) if c else 0
            except Exception:
                msg_count = 0
            chats.append(
                {
                    "chat_id": chat_id,
                    "chat_name": chat_name,
                    "jid": jid,
                    "session_type": session_type,
                    "msg_count": msg_count,
                }
            )
        chats.sort(key=lambda x: (-x["msg_count"], (x["chat_name"] or "").lower()))
        return chats
    finally:
        conn.close()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.strip()
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def preview_messages(
    db_path: Path | None = None,
    chat_ids: list[int] | None = None,
    from_me: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError("WhatsApp ChatStorage.sqlite not found")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        chat_map: dict[int, str] = {}
        for ch in conn.execute("SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID FROM ZWACHATSESSION").fetchall():
            cid = ch["Z_PK"]
            chat_map[cid] = ch["ZPARTNERNAME"] or ch["ZCONTACTJID"] or f"chat-{cid}"

        where = ["ZTEXT IS NOT NULL", "ZTEXT != ''"]
        params: list[Any] = []
        if chat_ids:
            where.append("ZCHATSESSION IN (" + ",".join(["?"] * len(chat_ids)) + ")")
            params.extend(chat_ids)
        if from_me is True:
            where.append("ZISFROMME = 1")
        elif from_me is False:
            where.append("ZISFROMME = 0")
        where_sql = " AND ".join(where)

        count_row = conn.execute(f"SELECT COUNT(*) AS c FROM ZWAMESSAGE WHERE {where_sql}", params).fetchone()
        total = int(count_row["c"]) if count_row else 0

        rows = conn.execute(
            f"""SELECT Z_PK, ZCHATSESSION, ZTEXT, ZISFROMME, ZMESSAGEDATE
                FROM ZWAMESSAGE
                WHERE {where_sql}
                ORDER BY ZMESSAGEDATE DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        dt_from = _parse_iso(date_from)
        dt_to = _parse_iso(date_to)

        items: list[dict[str, Any]] = []
        for m in rows:
            when = _apple_to_utc(m["ZMESSAGEDATE"])
            if dt_from or dt_to:
                wdt = _parse_iso(when)
                if dt_from and wdt and wdt < dt_from:
                    continue
                if dt_to and wdt and wdt > dt_to:
                    continue
            text = str(m["ZTEXT"]).strip()
            if not text:
                continue
            cid = m["ZCHATSESSION"]
            items.append(
                {
                    "chat_id": cid,
                    "chat_name": chat_map.get(cid) or f"chat-{cid}",
                    "msg_id": m["Z_PK"],
                    "text": text,
                    "from_me": bool(m["ZISFROMME"]),
                    "when": when,
                    "kind": "whatsapp",
                }
            )
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


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
