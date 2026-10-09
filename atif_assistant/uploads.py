"""File upload ingestion.

Uploads arrive as JSON (base64 or plain text) so no multipart dependency is
needed and the whole thing stays pure-Python and offline-installable.

A file lands in ``data/uploads/`` keyed by its content hash, so uploading the
same file twice stores it once. Text, JSON, CSV, markup, PDF, Office documents,
spreadsheets, presentations and WhatsApp exports are read locally (see
``extract.py``) and folded into memory. Files that cannot be read - images
without OCR, unknown binaries - are stored and referenced only; the response
reports ``read: false`` and a reason instead of pretending they were understood.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import db, extract
from .config import UPLOADS_DIR

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log",
    ".yml", ".yaml", ".html", ".htm", ".xml", ".ini", ".cfg", ".conf",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff", ".svg"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx"}

MAX_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 20_000


def detect_kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in DOC_EXTS:
        return "document"
    if ext in TEXT_EXTS:
        return "text"
    return "file"


def _safe_name(filename: str) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return name[:120]


def ingest_upload(
    filename: str,
    related_to: str | None = None,
    kind: str | None = None,
    text: str | None = None,
    content_b64: str | None = None,
    source: str = "upload",
) -> dict[str, Any]:
    """Store one uploaded file and fold its text into memory.

    Exactly one of ``text`` or ``content_b64`` must be present. Raises
    ValueError on bad input or an oversized file.
    """
    if content_b64 is not None:
        try:
            raw = base64.b64decode(content_b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("content_b64 is not valid base64") from exc
    elif text is not None:
        raw = text.encode("utf-8")
    else:
        raise ValueError("provide either text or content_b64")

    if len(raw) > MAX_BYTES:
        raise ValueError(f"file too large (max {MAX_BYTES} bytes)")

    filename = filename or "upload"
    kind = (kind or detect_kind(filename)).lower()
    digest = hashlib.sha256(raw).hexdigest()

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored = UPLOADS_DIR / f"{digest[:16]}_{_safe_name(filename)}"
    duplicate_file = stored.exists()
    if not duplicate_file:
        stored.write_bytes(raw)

    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO media(path, kind, tags, meta, created_at) VALUES (?,?,?,?,?)",
        (
            str(stored),
            kind,
            related_to,
            json.dumps(
                {
                    "filename": filename,
                    "size": len(raw),
                    "sha256": digest,
                }
            ),
            db.now(),
        ),
    )
    conn.commit()
    media_id = int(cur.lastrowid)

    report: dict[str, Any] = {
        "ok": True,
        "media_id": media_id,
        "kind": kind,
        "stored": str(stored),
        "duplicate_file": duplicate_file,
        "related_to": related_to,
        "evidence_id": None,
        "episode_id": None,
        "read": False,
        "read_chars": 0,
        "text_source": None,
        "read_reason": None,
    }

    # Read the file's text locally. Text/JSON/CSV, PDF, Office and WhatsApp
    # exports become searchable memory; anything unreadable is stored only, and
    # the response says which and why rather than implying it was understood.
    if text is not None:
        result: dict[str, Any] = {"text": text, "source": "text", "reason": None, "meta": {}}
    else:
        result = extract.extract(filename, raw)

    body = result.get("text")
    report["text_source"] = result.get("source")
    report["read_reason"] = result.get("reason")
    if body:
        body = body[:MAX_TEXT_CHARS]
        report["read"] = True
        report["read_chars"] = len(body)
        eid = db.add_evidence(
            source=f"{source}:{filename}",
            body=body,
            occurred_at=db.now(),
            speaker=source,
        )
        report["evidence_id"] = eid
        # Evidence is idempotent; only record an episode for genuinely new
        # content, so re-uploading the same file does not stack episodes.
        if eid is not None:
            meta = result.get("meta") or {}
            if meta.get("whatsapp_summary"):
                title = f"WhatsApp export {filename}"
            else:
                title = f"Uploaded {filename}"
            if related_to:
                title += f" ({related_to})"
            report["episode_id"] = db.add_episode(
                title=title,
                summary=body[:2000],
                occurred_at=db.now(),
                source=f"{source}:{filename}",
            )
            if meta.get("whatsapp_summary"):
                report["whatsapp_summary"] = meta["whatsapp_summary"]

    return report
