"""Read the text out of an uploaded file.

Local-first and dependency-light. Plain text and structured text (JSON, CSV,
HTML, XML) are decoded directly. PDFs use ``pypdf`` (pure Python). Office
formats - ``.docx``, ``.pptx``, ``.xlsx`` - are just zipped XML, so the standard
library reads them with no extra packages. WhatsApp chat exports are detected
and parsed into a clean transcript with a small summary.

Images and scanned PDFs need OCR. OCR is only attempted when both Tesseract and
``pytesseract`` are present; otherwise the file is stored unread and the caller
is told exactly why. Nothing here invents content: when a file cannot be read,
``text`` is ``None`` and ``reason`` says why.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from typing import Any

# Extensions we can read as text with no extra tooling.
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log",
    ".yml", ".yaml", ".ini", ".cfg", ".conf", ".srt", ".vtt",
}
MARKUP_EXTS = {".html", ".htm", ".xml", ".svg"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
PPTX_EXTS = {".pptx"}
XLSX_EXTS = {".xlsx", ".xlsm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic"}

MAX_CHARS = 120_000

# A WhatsApp export line: "[31/12/2025, 9:41:03 PM] Name: message" (Android) or
# "31/12/2025, 9:41 PM - Name: message" (iOS).
_WA_BRACKET = re.compile(
    r"^\[(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[APap]\.?[Mm]\.?)?\]\s*([^:]{1,60}):\s?(.*)$"
)
_WA_DASH = re.compile(
    r"^(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:[APap]\.?[Mm]\.?)?\s*-\s*([^:]{1,60}):\s?(.*)$"
)


def _decode(raw: bytes) -> str | None:
    """Decode bytes that look like text; return None for binary."""
    if not raw or b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _strip_markup(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _zip_text(raw: bytes, member: str, tag: str, paragraph_tag: str | None = None) -> str | None:
    """Pull ``tag`` runs out of an XML member inside a zip container."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        xml = zf.read(member).decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    blocks = re.split(rf"</{paragraph_tag}>", xml) if paragraph_tag else [xml]
    lines: list[str] = []
    for block in blocks:
        runs = re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S)
        line = unescape("".join(runs)).strip()
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def _zip_members_text(raw: bytes, prefix: str, tag: str) -> str | None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError):
        return None
    names = sorted(
        n for n in zf.namelist() if n.startswith(prefix) and n.endswith(".xml")
    )
    chunks: list[str] = []
    for name in names:
        try:
            xml = zf.read(name).decode("utf-8", "ignore")
        except (KeyError, OSError):
            continue
        runs = re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
        text = unescape("".join(runs)).strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks) or None


def _from_pdf(raw: bytes) -> tuple[str | None, str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "the PDF reader is not installed"
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return None, "the PDF is password-protected"
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # noqa: BLE001 - a bad PDF must not break an upload
        return None, f"the PDF could not be read ({exc})"
    text = "\n".join(pages).strip()
    if text:
        return text, None
    return None, "the PDF has no extractable text (it is likely scanned; OCR is needed)"


def _ocr(raw: bytes) -> tuple[str | None, str | None]:
    """Best-effort OCR. Only runs when a full OCR stack is installed."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return None, "OCR is not installed (needs tesseract, pytesseract and Pillow)"
    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(raw))).strip()
    except Exception as exc:  # noqa: BLE001
        return None, f"OCR failed ({exc})"
    if text:
        return text, None
    return None, "OCR found no text in the image"


def _whatsapp(text: str) -> dict[str, Any] | None:
    """Parse a WhatsApp export into a clean transcript plus a summary."""
    lines = text.splitlines()
    matched = 0
    people: list[str] = []
    msgs = 0
    first = last = None
    out: list[str] = []
    for line in lines:
        m = _WA_BRACKET.match(line) or _WA_DASH.match(line)
        if m:
            matched += 1
            date, time, who, body = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
            first = first or date
            last = date
            if who not in people:
                people.append(who)
            msgs += 1
            out.append(f"{date} {time} — {who}: {body}")
        elif matched and line.strip():
            # A continuation of the previous message.
            out.append("    " + line.strip())
    if matched < 5 or len(people) < 2:
        return None
    summary = (
        f"WhatsApp export: {msgs} messages between {len(people)} people "
        f"({', '.join(people[:12])}), from {first} to {last}."
    )
    return {
        "transcript": "\n".join(out),
        "summary": summary,
        "people": people,
        "messages": msgs,
    }


def extract(filename: str, raw: bytes) -> dict[str, Any]:
    """Return what could be read from ``raw``.

    Result keys:
      ``text``    the extracted text, or ``None`` if nothing could be read
      ``source``  how it was read (``text``, ``pdf``, ``docx``, ``ocr`` ...)
      ``reason``  why reading failed, when ``text`` is ``None``
      ``meta``    extra facts about the file (e.g. WhatsApp participants)
    """
    ext = Path(filename or "").suffix.lower()

    if ext in PDF_EXTS:
        text, reason = _from_pdf(raw)
        if text:
            return {"text": text[:MAX_CHARS], "source": "pdf", "reason": None, "meta": {}}
        # A scanned PDF can still be OCR'd page-image by page-image, but that is
        # more than pypdf offers; report the reason honestly.
        return {"text": None, "source": None, "reason": reason, "meta": {}}

    if ext in DOCX_EXTS:
        text = _zip_text(raw, "word/document.xml", "w:t", paragraph_tag="w:p")
        if text:
            return {"text": text[:MAX_CHARS], "source": "docx", "reason": None, "meta": {}}
        return {"text": None, "source": None, "reason": "the document could not be read", "meta": {}}

    if ext in PPTX_EXTS:
        text = _zip_members_text(raw, "ppt/slides/", "a:t")
        if text:
            return {"text": text[:MAX_CHARS], "source": "pptx", "reason": None, "meta": {}}
        return {"text": None, "source": None, "reason": "the presentation could not be read", "meta": {}}

    if ext in XLSX_EXTS:
        text = _zip_members_text(raw, "xl/", "t")
        if text:
            return {"text": text[:MAX_CHARS], "source": "xlsx", "reason": None, "meta": {}}
        return {"text": None, "source": None, "reason": "the spreadsheet could not be read", "meta": {}}

    decoded = _decode(raw)

    if ext in MARKUP_EXTS and decoded:
        return {"text": _strip_markup(decoded)[:MAX_CHARS], "source": "markup", "reason": None, "meta": {}}

    if ext in TEXT_EXTS and decoded is not None:
        if ext in {".txt", ".log"} or ext == "":
            wa = _whatsapp(decoded)
            if wa:
                return {
                    "text": wa["transcript"][:MAX_CHARS],
                    "source": "whatsapp",
                    "reason": None,
                    "meta": {
                        "whatsapp_summary": wa["summary"],
                        "people": wa["people"],
                        "messages": wa["messages"],
                    },
                }
        if ext == ".json":
            try:
                parsed = json.loads(decoded)
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                return {"text": pretty[:MAX_CHARS], "source": "json", "reason": None, "meta": {}}
            except (json.JSONDecodeError, ValueError):
                pass
        return {"text": decoded[:MAX_CHARS], "source": "text", "reason": None, "meta": {}}

    if ext in IMAGE_EXTS:
        text, reason = _ocr(raw)
        if text:
            return {"text": text[:MAX_CHARS], "source": "ocr", "reason": None, "meta": {}}
        return {"text": None, "source": None, "reason": reason, "meta": {}}

    # Unknown extension: if it happens to be decodable text, keep it.
    if decoded is not None and ext == "":
        return {"text": decoded[:MAX_CHARS], "source": "text", "reason": None, "meta": {}}

    return {
        "text": None,
        "source": None,
        "reason": f"files ending in {ext or '(none)'} are stored but not read",
        "meta": {},
    }
