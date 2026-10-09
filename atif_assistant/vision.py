"""Read images and scans with a vision model.

Local extraction (``extract.py``) cannot read pixels: a photo, a screenshot or a
scanned PDF has no text layer. When a vision-capable provider is configured
(Gemini), such a file is sent as an inline part and the model transcribes the
text and describes what is visible. The result becomes memory like any other
upload.

Without a provider the caller gets ``text=None`` and a reason naming what is
missing - the file is stored and referenced only, never guessed at.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

from . import llm

MAX_BYTES = 8 * 1024 * 1024

MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".heic": "image/heic",
    ".pdf": "application/pdf",
}

VISION_PROMPT = (
    "Transcribe every piece of text in this file exactly, preserving reading "
    "order and line breaks. Then, on a new line beginning with \"DESCRIPTION:\", "
    "briefly describe what it shows (objects, people, layout) in one or two "
    "sentences. If there is no text, output only the DESCRIPTION line. Never "
    "guess at anything you cannot actually see."
)


def vision_available() -> bool:
    """True when a key for a vision-capable provider is configured."""
    return bool(llm.provider_key("gemini"))


def describe(raw: bytes, filename: str) -> dict[str, Any]:
    """Transcribe and describe an image or scanned document.

    Result mirrors ``extract.extract``: ``text`` (or ``None``), ``source``,
    ``reason`` and ``meta``.
    """
    key = llm.provider_key("gemini")
    if not key:
        return {
            "text": None,
            "source": None,
            "reason": "images and scans need a vision provider (add a Gemini key)",
            "meta": {},
        }
    if len(raw) > MAX_BYTES:
        return {
            "text": None,
            "source": None,
            "reason": "the file is too large for inline vision (max 8 MB)",
            "meta": {},
        }

    model = llm.provider_model("gemini")
    mime = MIME_BY_EXT.get(Path(filename or "").suffix.lower(), "image/jpeg")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(raw).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    try:
        with httpx.Client(timeout=120) as client:
            data = None
            for attempt in range(3):
                r = client.post(url, headers={"x-goog-api-key": key}, json=body)
                if r.status_code in (429, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                break
            if data is None:
                r.raise_for_status()
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") if candidates else []
        text = "\n".join(p.get("text", "") for p in (parts or [])).strip()
        if not text:
            return {
                "text": None,
                "source": None,
                "reason": "the vision model returned no text",
                "meta": {},
            }
        return {"text": text, "source": "vision", "reason": None, "meta": {"model": model}}
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")[:120]
        except Exception:  # noqa: BLE001
            detail = ""
        return {
            "text": None,
            "source": None,
            "reason": f"vision request failed: HTTP {exc.response.status_code}"
            + (f" ({detail})" if detail else ""),
            "meta": {},
        }
    except Exception as exc:  # noqa: BLE001 - vision must never break an upload
        return {
            "text": None,
            "source": None,
            "reason": f"vision request failed: {type(exc).__name__}",
            "meta": {},
        }
