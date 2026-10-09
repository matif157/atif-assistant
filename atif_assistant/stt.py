"""Offline speech recognition with whisper.cpp.

The browser's Web Speech API sends audio to Google, so it cannot recognise
speech without a network. When ``whisper-cli`` and a GGML model are installed,
this module transcribes a recorded clip locally instead, which is what lets the
mic and the phone call work offline (in Urdu as well as English).

It fails soft: when the tool or model is missing the caller gets ``None`` plus a
reason, and the browser recogniser is used instead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

_BIN_NAMES = ("whisper-cli", "whisper-cpp", "main")
_FALLBACK_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
)


def find_bin(name: str) -> str | None:
    """Locate an executable even when PATH is minimal (as under launchd)."""
    found = shutil.which(name)
    if found:
        return found
    for directory in _FALLBACK_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _first_bin(names: tuple[str, ...]) -> str | None:
    for name in names:
        found = find_bin(name)
        if found:
            return found
    return None


_BIN = os.environ.get("ATIF_ASSISTANT_WHISPER_BIN") or _first_bin(_BIN_NAMES)
_MODEL_DIR = Path(
    os.environ.get("ATIF_ASSISTANT_MODEL_DIR", Path.home() / ".local/share/atif-assistant/models")
)
_MODEL = os.environ.get("ATIF_ASSISTANT_WHISPER_MODEL") or str(_MODEL_DIR / "ggml-base.bin")
_NO_GPU = os.environ.get("ATIF_ASSISTANT_WHISPER_NO_GPU", "1") not in {"0", "false", "no"}

MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = 150

# The browser sends BCP-47 codes (ur-PK); whisper wants ISO-639-1 (ur).
_LANG = {
    "ur": "ur",
    "ur-pk": "ur",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
}


def _lang(code: str | None) -> str:
    if not code:
        return "auto"
    return _LANG.get(code.lower(), code.split("-")[0].lower() or "auto")


def model_path() -> Path:
    return Path(_MODEL)


def available() -> bool:
    return bool(_BIN) and model_path().is_file()


def status() -> dict[str, Any]:
    return {
        "available": available(),
        "bin": _BIN,
        "model": model_path().name if model_path().is_file() else None,
    }


def transcribe(raw: bytes, lang: str = "auto") -> dict[str, Any]:
    """Transcribe a WAV clip. Returns {text, reason, meta} and never raises."""
    if not _BIN:
        return {
            "text": None,
            "reason": "offline speech needs whisper.cpp (brew install whisper.cpp)",
            "meta": {},
        }
    if not model_path().is_file():
        return {
            "text": None,
            "reason": "offline speech model is not downloaded",
            "meta": {},
        }
    if not raw:
        return {"text": None, "reason": "empty clip", "meta": {}}
    if len(raw) > MAX_BYTES:
        return {"text": None, "reason": "clip too long", "meta": {}}

    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.wav"
        clip.write_bytes(raw)
        out = Path(tmp) / "out"
        cmd = [
            _BIN,
            "-m",
            str(model_path()),
            "-l",
            _lang(lang),
            "-f",
            str(clip),
            "-otxt",
            "-of",
            str(out),
            "-nt",
            "-np",
        ]
        if _NO_GPU:
            cmd.append("-ng")
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"text": None, "reason": "offline speech timed out", "meta": {}}
        except Exception as exc:  # noqa: BLE001 - never break the request
            return {"text": None, "reason": f"offline speech failed: {type(exc).__name__}", "meta": {}}

        text = ""
        txt = out.with_suffix(".txt")
        if txt.is_file():
            text = txt.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"\[[^\]]*\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        meta = {
            "model": model_path().name,
            "seconds": round(time.monotonic() - started, 1),
            "returncode": proc.returncode,
        }
        if not text:
            return {"text": None, "reason": "no speech recognised", "meta": meta}
        return {"text": text, "reason": None, "meta": meta}
