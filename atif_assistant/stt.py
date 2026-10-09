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
# An explicit override wins; otherwise the best installed model is used, newest
# first. The small model is markedly better at Urdu than base and is the default
# recommendation, but base still works if that is all that is installed.
_MODEL_OVERRIDE = os.environ.get("ATIF_ASSISTANT_WHISPER_MODEL")
MODEL_CANDIDATES = ("ggml-small.bin", "ggml-base.bin", "ggml-tiny.bin")
# The model the downloader installs by default. Small is the accuracy sweet
# spot for Urdu without being slow on a fanless Mac.
PREFERRED_MODEL = "ggml-small.bin"
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


def model_dir() -> Path:
    return _MODEL_DIR


def model_path() -> Path:
    """The model actually in use: an explicit override, else the best present."""
    if _MODEL_OVERRIDE:
        return Path(_MODEL_OVERRIDE)
    for name in MODEL_CANDIDATES:
        candidate = _MODEL_DIR / name
        if candidate.is_file():
            return candidate
    return _MODEL_DIR / MODEL_CANDIDATES[0]


def available() -> bool:
    return bool(_BIN) and model_path().is_file()


def status() -> dict[str, Any]:
    path = model_path()
    present = path.is_file()
    return {
        "available": available(),
        "bin": _BIN,
        "model": path.name if present else None,
        "uses_small": present and path.name == "ggml-small.bin",
        "small_present": (_MODEL_DIR / "ggml-small.bin").is_file(),
        "models_present": [n for n in MODEL_CANDIDATES if (_MODEL_DIR / n).is_file()],
        "model_dir": str(_MODEL_DIR),
    }


# Hugging Face paths for the whisper.cpp GGML models the app can fetch itself.
MODEL_URLS = {
    "ggml-small.bin": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
    "ggml-base.bin": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
    "ggml-tiny.bin": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
}


def download_model(name: str = "ggml-small.bin") -> dict[str, Any]:
    """Fetch a GGML model into the model directory. Never raises.

    Downloads to a temp file and renames only on success, so an interrupted
    download never leaves a half-written model that ``available()`` would trust.
    """
    name = name or "ggml-small.bin"
    url = MODEL_URLS.get(name)
    if not url:
        return {"ok": False, "reason": f"unknown model {name!r}", "model": name}
    dest = _MODEL_DIR / name
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return {"ok": True, "reason": "already installed", "model": name, "path": str(dest)}
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "atif-assistant"})
        with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
        if tmp.stat().st_size < 1_000_000:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "reason": "download too small; check the connection", "model": name}
        tmp.replace(dest)
    except Exception as exc:  # noqa: BLE001 - fail soft, report the reason
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "reason": f"download failed: {type(exc).__name__}", "model": name}
    return {
        "ok": True,
        "reason": None,
        "model": name,
        "path": str(dest),
        "bytes": dest.stat().st_size,
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
