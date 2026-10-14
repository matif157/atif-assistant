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

from . import db, extract, transcribe, vision
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

# Advisory extraction from readable uploads. A directive sentence becomes a
# RULES row with approved=0; a durable personal fact becomes a LEARNED row with
# status='candidate'. Nothing here changes behaviour on its own - a human
# approves either row in the RULES or LEDGER screen first.
MAX_RULES_PER_UPLOAD = 5
MAX_LEARNED_PER_UPLOAD = 5

_DIRECTIVE = re.compile(
    r"^\s*(?:always|never|please|kindly|don'?t|do not|remember to|make sure|stop)\b"
    r"|^\s*(?:you|atif)\s+(?:must|should|shall|need to|have to)\b"
    r"|\b(?:and|,)\s*(?:always|never)\s+\w+",
    re.IGNORECASE,
)
_FACT = re.compile(
    r"\b(?:my|our)\s+(?:name|address|city|country|job|title|boss|wife|husband|"
    r"mother|father|mom|dad|son|daughter|sister|brother|phone|email|birthday|"
    r"home|flat|apartment|car|school|university|company|religion|language)\b"
    r"|\bi\s+(?:live|work|stay|study|speak|prefer|like|hate|need|want|am)\b",
    re.IGNORECASE,
)
_SKIP_LINE = re.compile(r"^\s*(#|//|;|https?://|www\.)")
_LIST_MARK = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+")


def _sentences(text: str) -> list[str]:
    """Split an upload into candidate sentences, dropping headings and URLs.

    List markers are stripped rather than skipped - people write "- always
    answer in Urdu" in notes all the time, and that line is exactly a rule.
    """
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _SKIP_LINE.search(line):
            continue
        line = _LIST_MARK.sub("", line).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            s = sentence.strip()
            if s:
                out.append(s)
    return out


def _rule_exists(text: str) -> bool:
    conn = db.connect()
    return (
        conn.execute("SELECT 1 FROM rules WHERE text=?", (text,)).fetchone()
        is not None
    )


def _learned_exists(text: str) -> bool:
    conn = db.connect()
    return (
        conn.execute("SELECT 1 FROM learned WHERE text=?", (text,)).fetchone()
        is not None
    )


def classify_upload_text(text: str, source: str = "upload") -> dict[str, list[int]]:
    """Propose rules and LEARNED candidates from readable upload text.

    Propose-then-approve: rules land unapproved and learned rows land as
    candidates, so an uploaded file can never silently change how the
    assistant behaves. Re-uploading the same file creates no duplicates
    because every proposal is checked against what is already stored.
    """
    rules_added: list[int] = []
    learned_added: list[int] = []
    for sentence in _sentences(text):
        if not 12 <= len(sentence) <= 160:
            continue
        if _DIRECTIVE.search(sentence):
            if len(rules_added) >= MAX_RULES_PER_UPLOAD or _rule_exists(sentence):
                continue
            rules_added.append(
                db.add_rule(
                    text=sentence, code=None,
                    source=f"{source}:proposal", approved=False,
                )
            )
            continue  # a directive is an instruction, not a personal fact
        if _FACT.search(sentence):
            if len(learned_added) >= MAX_LEARNED_PER_UPLOAD or _learned_exists(sentence):
                continue
            learned_added.append(
                db.add_learned(
                    text=sentence, kind="durable",
                    source=f"{source}:proposal", confidence=0.5,
                )
            )
    return {"rules_added": rules_added, "learned_added": learned_added}


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


def read_upload(filename: str, raw: bytes, kind: str | None = None) -> dict[str, Any]:
    """Read an uploaded file, falling back to hosted models when needed.

    Local extraction runs first. If it can find no text and the file is audio,
    an image, or a scanned PDF, a configured hosted model is tried (Groq Whisper
    for audio, Gemini vision for pixels). Every path returns ``text``/``source``/
    ``reason``/``meta`` and never invents content.
    """
    result = extract.extract(filename, raw)
    if result.get("text"):
        return result

    resolved = (kind or detect_kind(filename)).lower()
    ext = Path(filename or "").suffix.lower()
    fallback: dict[str, Any] | None = None
    if resolved == "audio":
        fallback = transcribe.transcribe(raw, filename)
    elif resolved == "image" or (resolved == "document" and ext == ".pdf"):
        fallback = vision.describe(raw, filename)

    if fallback and fallback.get("text"):
        return fallback
    if fallback and fallback.get("reason"):
        result["reason"] = fallback["reason"]
    return result


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
        "rules_added": [],
        "learned_added": [],
    }

    # Read the file's text locally, falling back to hosted models for audio,
    # images and scans. Readable content becomes searchable memory; anything
    # unreadable is stored only, and the response says which and why rather
    # than implying it was understood.
    if text is not None:
        result: dict[str, Any] = {"text": text, "source": "text", "reason": None, "meta": {}}
    else:
        result = read_upload(filename, raw, kind)

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
            # Only genuinely new content is classified, so re-uploading the
            # same file cannot stack duplicate proposals on top of each other.
            classified = classify_upload_text(body, source=f"{source}:{filename}")
            report["rules_added"] = classified["rules_added"]
            report["learned_added"] = classified["learned_added"]
            if meta.get("whatsapp_summary"):
                report["whatsapp_summary"] = meta["whatsapp_summary"]

    return report
