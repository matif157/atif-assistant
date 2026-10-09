"""File upload ingestion.

Uploads arrive as JSON (base64 or plain text) so no multipart dependency is
needed and the whole thing stays pure-Python and offline-installable.

A file lands in ``data/uploads/`` keyed by its content hash, so uploading the
same file twice stores it once. A text file is additionally ingested as
searchable evidence and a dated episode, labelled with whatever the user said
it relates to. Binary files are stored and referenced only - nothing is guessed
from their bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import db
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


def _decode_text(raw: bytes) -> str | None:
    """Return decoded text if the bytes look like text, else None."""
    if not raw or b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


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
    }

    # Only text becomes memory here. Images, audio and PDFs are stored and
    # referenced but never parsed - guessing content from bytes would be
    # fabrication.
    body = text
    if body is None and kind == "text":
        body = _decode_text(raw)
    if body:
        body = body[:MAX_TEXT_CHARS]
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
            report["episode_id"] = db.add_episode(
                title=f"Uploaded {filename}"
                + (f" ({related_to})" if related_to else ""),
                summary=body[:2000],
                occurred_at=db.now(),
                source=f"{source}:{filename}",
            )

    return report
