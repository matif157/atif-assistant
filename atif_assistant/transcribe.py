"""Transcribe audio with a hosted speech model.

Local extraction cannot read sound. When a Groq key is configured, an uploaded
voice note or recording is sent to Whisper and the transcript becomes memory.
Without a key the file is stored and the caller is told what is missing.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from . import llm

MAX_BYTES = 25 * 1024 * 1024

MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".mp4": "audio/mp4",
}


def transcribe_available() -> bool:
    return bool(llm.provider_key("groq"))


def transcribe(raw: bytes, filename: str) -> dict[str, Any]:
    """Return a transcript, or ``text=None`` with a reason.

    Result mirrors ``extract.extract``: ``text``, ``source``, ``reason``, ``meta``.
    """
    key = llm.provider_key("groq")
    if not key:
        return {
            "text": None,
            "source": None,
            "reason": "audio transcription needs a Groq key (Whisper)",
            "meta": {},
        }
    if len(raw) > MAX_BYTES:
        return {
            "text": None,
            "source": None,
            "reason": "the audio is too large to transcribe (max 25 MB)",
            "meta": {},
        }

    model = os.environ.get("ATIF_ASSISTANT_TRANSCRIBE_MODEL", "whisper-large-v3-turbo")
    mime = MIME_BY_EXT.get(Path(filename or "").suffix.lower(), "application/octet-stream")
    try:
        with httpx.Client(timeout=120) as client:
            for attempt in range(3):
                r = client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (filename or "audio", raw, mime)},
                    data={"model": model, "response_format": "text"},
                )
                if r.status_code in (429, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                break
            text = r.text.strip()
        if not text:
            return {
                "text": None,
                "source": None,
                "reason": "the speech model returned no words",
                "meta": {},
            }
        return {
            "text": text,
            "source": "transcript",
            "reason": None,
            "meta": {"model": model},
        }
    except httpx.HTTPStatusError as exc:
        return {
            "text": None,
            "source": None,
            "reason": f"transcription failed: HTTP {exc.response.status_code}",
            "meta": {},
        }
    except Exception as exc:  # noqa: BLE001 - transcription must never break an upload
        return {
            "text": None,
            "source": None,
            "reason": f"transcription failed: {type(exc).__name__}",
            "meta": {},
        }
