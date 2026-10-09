"""Local model host control (Ollama).

Keeps the offline chat path usable without the user opening a terminal: detect
whether ollama is installed and running, start it, and pull a model. Everything
fails soft, so a machine without ollama still runs the app and simply reports
itself unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

_CANDIDATE_BINS = (
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
)


def binary() -> str | None:
    """Path to the ollama executable, or None if it is not installed."""
    found = shutil.which("ollama")
    if found:
        return found
    for path in _CANDIDATE_BINS:
        if Path(path).is_file():
            return path
    return None


def url() -> str:
    from .llm import ollama_url

    return ollama_url()


def desired_model() -> str:
    from .llm import provider_model

    return provider_model("ollama")


def models() -> list[str]:
    try:
        r = httpx.get(f"{url()}/api/tags", timeout=2.0)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001
        return []


def running() -> bool:
    try:
        r = httpx.get(f"{url()}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def status() -> dict[str, Any]:
    """What the local model host looks like right now."""
    up = running()
    present = models() if up else []
    want = desired_model()
    return {
        "installed": binary() is not None,
        "binary": binary(),
        "running": up,
        "url": url(),
        "models": present,
        "model": want,
        "model_present": want in present,
    }


def start() -> dict[str, Any]:
    """Start the local host if it is installed but not running.

    Prefers ``brew services`` so it survives logout; if brew is not present it
    falls back to a detached ``ollama serve``. Either way it waits briefly for
    the host to answer so the caller can report the real result.
    """
    if running():
        return {"ok": True, "running": True, "reason": "already running"}
    exe = binary()
    if not exe:
        return {"ok": False, "running": False, "reason": "ollama is not installed"}
    brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
    try:
        if Path(brew).exists():
            subprocess.run(
                [brew, "services", "start", "ollama"],
                capture_output=True,
                timeout=30,
            )
        else:
            log_dir = Path.home() / ".local" / "share" / "atif-assistant"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "ollama.log", "ab") as log:
                subprocess.Popen(  # noqa: S603
                    [exe, "serve"],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "running": False, "reason": str(exc)}
    for _ in range(20):
        if running():
            return {"ok": True, "running": True}
        time.sleep(0.5)
    return {"ok": False, "running": False, "reason": "started but not answering yet"}


def pull(model: str | None = None) -> dict[str, Any]:
    """Download a model into the local host. Blocking; call in a background task."""
    want = model or desired_model()
    if want in models():
        return {"ok": True, "model": want, "reason": "already present"}
    exe = binary()
    if exe:
        try:
            r = subprocess.run(  # noqa: S603
                [exe, "pull", want],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            if r.returncode == 0:
                return {"ok": True, "model": want}
            reason = (r.stderr or r.stdout or "").strip()[:200]
            return {"ok": False, "model": want, "reason": reason or f"exit {r.returncode}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "model": want, "reason": str(exc)}
    try:
        r = httpx.post(
            f"{url()}/api/pull", json={"name": want, "stream": False}, timeout=3600
        )
        r.raise_for_status()
        return {"ok": True, "model": want}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": want, "reason": str(exc)}


def autostart_enabled() -> bool:
    from . import db

    try:
        value = db.get_setting("ollama_autostart", "1")
    except Exception:  # noqa: BLE001
        value = "1"
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def ensure_autostart() -> None:
    """Start the local host in the background if it should be running.

    Never raises and never blocks startup: a slow or missing ollama must not
    delay the app coming up.
    """
    if not autostart_enabled() or not binary() or running():
        return
    import threading

    threading.Thread(target=start, name="ollama-autostart", daemon=True).start()
