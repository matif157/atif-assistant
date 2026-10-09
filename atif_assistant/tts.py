"""Server-side text to speech for voices the browser does not have.

Most systems ship no Urdu voice, so the Web Speech API reads Urdu replies with
an English voice and the result is unintelligible. When a Gemini key is
configured this module synthesizes the reply on the server instead and returns
a WAV clip the browser can play. It fails soft: with no key or no quota the
caller gets `None` plus a reason, and the browser falls back to its own voices.
"""

from __future__ import annotations

import base64
import os
import re
import struct
import time
from typing import Any

import httpx

from . import llm

DEFAULT_MODEL = os.environ.get(
    "ATIF_ASSISTANT_TTS_MODEL", "gemini-2.5-flash-preview-tts"
)
DEFAULT_VOICE = os.environ.get("ATIF_ASSISTANT_TTS_VOICE", "Kore")
MAX_CHARS = 3000

# Labels and markdown markers should not be read aloud.
_LABELS = re.compile(
    r"\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]", re.IGNORECASE
)
_MARKUP = re.compile(r"[*_#>`]+")
_SPACE = re.compile(r"\s+")


def _clean(text: str) -> str:
    t = _LABELS.sub("", text or "")
    t = _MARKUP.sub(" ", t)
    return _SPACE.sub(" ", t).strip()


def _wav(pcm: bytes, rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw little-endian PCM in a WAV container the browser can play."""
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def available() -> bool:
    return bool(llm.provider_key("gemini")) and llm.provider_enabled("gemini")


def synthesize(text: str, lang: str = "en") -> dict[str, Any]:
    """Return {"audio": <wav bytes|None>, "reason": <str|None>, "model": ...}."""
    if not llm.provider_enabled("gemini"):
        return {"audio": None, "reason": "server speech is turned off"}
    key = llm.provider_key("gemini")
    if not key:
        return {"audio": None, "reason": "server speech needs a Gemini key"}
    clean = _clean(text)[:MAX_CHARS]
    if not clean:
        return {"audio": None, "reason": "nothing to say"}

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{DEFAULT_MODEL}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": clean}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": DEFAULT_VOICE}
                }
            },
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=120) as client:
            resp = None
            for attempt in range(3):
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code in (429, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {
            "audio": None,
            "reason": f"speech request failed: HTTP {exc.response.status_code}",
        }
    except Exception as exc:  # noqa: BLE001 - best effort, never break the reply
        return {"audio": None, "reason": f"speech request failed: {type(exc).__name__}"}

    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get(
        "parts"
    ) or []
    inline = None
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            break
    if not inline or not inline.get("data"):
        return {"audio": None, "reason": "the speech model returned no audio"}

    try:
        pcm = base64.b64decode(inline["data"])
    except Exception:  # noqa: BLE001
        return {"audio": None, "reason": "the speech model returned bad audio"}

    rate = 24000
    mime = inline.get("mimeType") or inline.get("mime_type") or ""
    match = re.search(r"rate=(\d+)", mime)
    if match:
        rate = int(match.group(1))
    return {"audio": _wav(pcm, rate=rate), "reason": None, "model": DEFAULT_MODEL}
