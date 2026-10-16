"""In-memory log of notable runtime events.

Useful on-device, where stdout disappears into logcat: model downloads,
provider spawns, speech transcriptions and failures all land here and are
readable through ``GET /api/app-log`` (and therefore from the UI or adb).
Bounded ring buffer - never grows, never touches disk.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_MAX = 200
_LOCK = threading.Lock()
_EVENTS: list[dict[str, Any]] = []


def log(event: str, **fields: Any) -> None:
    """Record one event. Never raises; never blocks the caller for long."""
    try:
        entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
        entry.update(fields)
        with _LOCK:
            _EVENTS.append(entry)
            if len(_EVENTS) > _MAX:
                del _EVENTS[: len(_EVENTS) - _MAX]
    except Exception:  # noqa: BLE001 - logging must never break the app
        pass


def tail(limit: int = 50) -> list[dict[str, Any]]:
    """The most recent events, oldest first, capped at ``limit``."""
    with _LOCK:
        return list(_EVENTS[-max(1, min(limit, _MAX)):])
