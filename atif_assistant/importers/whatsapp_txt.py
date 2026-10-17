"""WhatsApp chat-export (.txt) importer.

WhatsApp can export any conversation as a plain text file (chat menu ->
More -> Export chat). Those files are the one legitimate way to get full
history off a phone: this module parses both formats WhatsApp ships:

    Android:  [12/08/2024, 3:45:21 PM] Ali: message
    iOS:      12/08/24, 3:45:21 PM - Ali: message

Continuation lines belong to the message above them; lines without a
sender (system notices like "end-to-end encrypted") are skipped. Parsing
is pure - the caller supplies the file content, so this works identically
on the Mac server and inside the APK.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

# Android bracket form and iOS dash form, both 12h and 24h clocks.
_ANDROID = re.compile(
    r"^\[(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}),\s+"
    r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?)\]\s*(.*)$"
)
_IOS = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+"
    r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?)\s+-\s+(.*)$"
)
_ME = {"you", "me"}


def _iso_date(a: str, b: str, c: str) -> str | None:
    """Best-effort YYYY-MM-DD from (d,m,y) or (m,d,y) pieces.

    A part > 12 settles the ambiguity; when both fit we assume day-first
    (the export locale this user's phone uses). Unparseable returns None -
    the raw string still rides along in the message's source.
    """
    try:
        x, y, z = int(a), int(b), int(c)
        year = z + 2000 if z < 100 else z
        if x > 12 and y <= 12:
            d, m = x, y
        elif y > 12 and x <= 12:
            m, d = x, y
        else:
            d, m = x, y  # day-first default
        datetime(year, m, d)  # validates (raises on 30/02 etc.)
        return f"{year:04d}-{m:02d}-{d:02d}"
    except Exception:  # noqa: BLE001
        return None


def _iso_time(t: str) -> str | None:
    t = t.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?$", t)
    if not m:
        return None
    h, mi, s, ap = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4)
    if ap:
        ap = ap.lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    if h > 23 or mi > 59 or s > 59:
        return None
    return f"{h:02d}:{mi:02d}:{s:02d}"


def parse_export(content: str, filename: str = "chat") -> dict[str, Any]:
    """Parse a WhatsApp export into staging candidates.

    Returns {chat, messages: [{idx, chat, from, from_me, when, ts, text,
    key}]} where ``key`` is a content hash used for cross-export dedupe.
    Raises ValueError when the content does not look like an export.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty file")

    chat = re.sub(r"\.txt$", "", filename or "chat", flags=re.I).strip() or "chat"
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    messages: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    matched = 0

    def flush() -> None:
        nonlocal cur
        if cur and cur["text"]:
            sender = cur["from"]
            raw = cur["when"]
            key_src = f"{chat}|{sender}|{raw}|{cur['text']}"
            cur["key"] = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
            cur["idx"] = len(messages)
            messages.append(cur)
        cur = None

    for line in lines:
        m = _ANDROID.match(line)
        if m:
            a, b, c, t, rest = m.groups()
        else:
            mi = _IOS.match(line)
            if not mi:
                if cur is not None and line:
                    # continuation: the message body itself spans lines
                    cur["text"] = cur["text"] + "\n" + line
                continue
            a, b, c = mi.group(1).split("/")
            t, rest = mi.group(2), mi.group(3)
        flush()
        matched += 1
        iso_d = _iso_date(a, b, c)
        raw_d = f"{a}/{b}/{c}"
        iso_t = _iso_time(t)
        ts = None
        if iso_d and iso_t:
            ts = f"{iso_d}T{iso_t}"
        sender, text = rest, ""
        if ": " in rest:
            sender, text = rest.split(": ", 1)
        elif rest.endswith(":"):
            sender, text = rest[:-1], ""
        else:
            # system line (encryption notice, group subject change...)
            sender, text = "", ""
        sender = sender.strip()
        from_me = sender.lower() in _ME
        cur = {
            "chat": chat,
            "from": "You" if from_me else sender,
            "from_me": from_me,
            "when": f"{raw_d}, {t}",
            "ts": ts,
            "text": text,
        }
        if not sender:
            cur = None  # drop system lines entirely

    flush()
    if matched == 0:
        raise ValueError("not a WhatsApp export (no timestamped lines found)")
    return {"chat": chat, "messages": messages}
