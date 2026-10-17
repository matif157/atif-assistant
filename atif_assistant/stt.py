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
        "download": stt_download_status(),
    }


# Mirror chains for the whisper.cpp GGML models: Hugging Face first, its
# proxy mirror second (verified Range-capable). Same never-lose-progress
# rules as the LLM downloader.
MODEL_URLS: dict[str, list[str]] = {
    name: [
        f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{name}",
        f"https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/{name}",
    ]
    for name in ("ggml-small.bin", "ggml-base.bin", "ggml-tiny.bin")
}

# Exact sizes from the source repo (99% tolerance counts as complete).
MODEL_EXPECTED = {
    "ggml-small.bin": 487_601_967,
    "ggml-base.bin": 147_951_465,
    "ggml-tiny.bin": 77_691_713,
}

# Minimum download attempts before giving up (each rotates the mirror).
# Tests lower this to keep failure paths fast.
_DL_ATTEMPTS = 6


def download_model(name: str = "ggml-small.bin") -> dict[str, Any]:
    """Fetch a GGML model into the model directory. Never raises.

    Downloads to a temp file and renames only on success, so an interrupted
    download never leaves a half-written model that ``available()`` would
    trust. The temp file itself is kept on failure so a later call can
    resume with a Range request instead of starting from zero.
    """
    name = name or "ggml-small.bin"
    urls = MODEL_URLS.get(name)
    if not urls:
        return {"ok": False, "reason": f"unknown model {name!r}", "model": name}
    dest = _MODEL_DIR / name
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return {"ok": True, "reason": "already installed", "model": name, "path": str(dest)}
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    expected = MODEL_EXPECTED.get(name, 0)
    import urllib.request

    last_reason = "download failed"
    attempts = max(_DL_ATTEMPTS, len(urls) * 2)
    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        try:
            have = tmp.stat().st_size if tmp.is_file() else 0
            if expected and have >= expected * 0.99:
                tmp.replace(dest)
                return {"ok": True, "reason": None, "model": name, "path": str(dest),
                        "bytes": dest.stat().st_size}
            headers = {"User-Agent": "atif-assistant"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                resuming = have > 0 and getattr(resp, "status", 200) == 206
                if have and not resuming:
                    have = 0
                mode = "ab" if have else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
            got = tmp.stat().st_size if tmp.is_file() else 0
            if expected:
                if got < expected * 0.99:
                    raise OSError(f"connection ended early ({got} of {expected} bytes)")
            elif got < 1_000_000:
                raise OSError("download too small; check the connection")
            tmp.replace(dest)
            return {
                "ok": True,
                "reason": None,
                "model": name,
                "path": str(dest),
                "bytes": dest.stat().st_size,
            }
        except Exception as exc:  # noqa: BLE001 - rotate mirror, then fail soft
            last_reason = f"download failed: {type(exc).__name__}"
            if attempt < attempts - 1:
                time.sleep(1.5)
                continue
        break
    partial = tmp.stat().st_size if tmp.is_file() else 0
    if partial:
        last_reason = f"{last_reason} — progress saved ({partial // 1048576} MB), tap resume"
    return {"ok": False, "reason": last_reason, "model": name, "partial": partial}


# ------------------------------------------- background model download
#
# A phone-side fetch of the 466 MB small model must not hold an HTTP request
# open for minutes, and a dropped connection must not start over. This mirrors
# the on-device LLM downloader: a daemon thread, Range-resume, and a state
# dict the settings screen can poll.

import threading  # noqa: E402 - sits next to the download it serves

_STT_DL_LOCK = threading.Lock()
_STT_DL: dict[str, Any] = {
    "state": "idle",  # idle | downloading | paused | ready | error
    "name": None, "bytes": 0, "total": 0, "reason": None,
    "partial": 0, "pause": False,
}


def stt_download_status() -> dict[str, Any]:
    with _STT_DL_LOCK:
        out = dict(_STT_DL)
        out.pop("pause", None)
        name = out.get("name")
    if out.get("state") in ("idle", "paused", "error") and name:
        part = (_MODEL_DIR / (name + ".part"))
        if part.is_file():
            out["partial"] = part.stat().st_size
    return out


def stt_download_pause() -> dict[str, Any]:
    with _STT_DL_LOCK:
        if _STT_DL["state"] != "downloading":
            return {"ok": True, "reason": "not downloading"}
        _STT_DL["pause"] = True
    return {"ok": True, "reason": "pausing"}


def stt_download_start(name: str | None = None) -> dict[str, Any]:
    """Start the model download in the background; never blocks the caller."""
    name = name or PREFERRED_MODEL
    if name not in MODEL_URLS:
        return {"ok": False, "reason": f"unknown model {name!r}"}
    dest = _MODEL_DIR / name
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return {"ok": True, "reason": "already installed"}
    with _STT_DL_LOCK:
        if _STT_DL["state"] == "downloading":
            return {"ok": True, "reason": "already running"}
        _STT_DL.update(
            {"state": "downloading", "name": name, "bytes": 0, "total": 0,
             "reason": None, "pause": False}
        )
    threading.Thread(target=_stt_download_worker, args=(name,), daemon=True).start()
    return {"ok": True, "started": True}


def _stt_download_worker(name: str) -> None:
    """Fetch a GGML model with resume, mirror rotation and pause.

    The .part file is never deleted on failure - a phone on a flaky link
    keeps every byte it managed to pull, and     the next session continues.
    """
    import urllib.request

    urls = MODEL_URLS[name]
    expected = MODEL_EXPECTED.get(name, 0)
    dest = _MODEL_DIR / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    last_error = "download failed"
    attempts = max(_DL_ATTEMPTS, len(urls) * 2)
    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        try:
            with _STT_DL_LOCK:
                if _STT_DL["pause"]:
                    _STT_DL.update({"state": "paused", "reason": "paused by user"})
                    return
            have = tmp.stat().st_size if tmp.is_file() else 0
            if expected and have >= expected * 0.99:
                tmp.replace(dest)
                with _STT_DL_LOCK:
                    _STT_DL.update({"state": "ready", "reason": "installed", "partial": 0})
                return
            headers = {"User-Agent": "atif-assistant"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                resuming = have > 0 and getattr(resp, "status", 200) == 206
                clen = int(resp.headers.get("Content-Length") or 0)
                if have and not resuming:
                    have = 0
                total = (expected or clen) + (have if resuming else 0)
                with _STT_DL_LOCK:
                    _STT_DL.update({"total": total, "bytes": have})
                done = have
                mode = "ab" if have else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        with _STT_DL_LOCK:
                            if _STT_DL["pause"]:
                                _STT_DL.update({"state": "paused", "reason": "paused by user"})
                                return
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        with _STT_DL_LOCK:
                            _STT_DL["bytes"] = done
            got = tmp.stat().st_size if tmp.is_file() else 0
            if expected and got < expected * 0.99:
                raise OSError(f"connection ended early ({got} of {expected} bytes)")
            if not expected and total and got < total * 0.99:
                raise OSError(f"connection ended early ({got} of {total} bytes)")
            if got < 1_000_000:
                raise OSError("download too small; check the connection")
            tmp.replace(dest)
            with _STT_DL_LOCK:
                _STT_DL.update({"state": "ready", "reason": "installed", "partial": 0})
            try:
                from . import applog

                applog.log("stt.model_ready", name=name, bytes=dest.stat().st_size)
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception as exc:  # noqa: BLE001 - rotate mirror, then fail soft
            last_error = str(exc)[:200] or type(exc).__name__
            if attempt < attempts - 1:
                time.sleep(1.5)
                continue
        break
    # Keep every byte: the next start resumes from here instead of zero.
    partial = tmp.stat().st_size if tmp.is_file() else 0
    reason = last_error
    if partial:
        reason = f"{last_error} — progress saved ({partial // 1048576} MB), tap resume"
    with _STT_DL_LOCK:
        _STT_DL.update({"state": "error", "reason": reason, "partial": partial})
    try:
        from . import applog

        applog.log("stt.model_failed", name=name, error=last_error, partial=partial)
    except Exception:  # noqa: BLE001
        pass


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
        try:
            from . import applog

            applog.log("stt.transcribe", ok=bool(text), **meta)
        except Exception:  # noqa: BLE001
            pass
        if not text:
            return {"text": None, "reason": "no speech recognised", "meta": meta}
        return {"text": text, "reason": None, "meta": meta}
