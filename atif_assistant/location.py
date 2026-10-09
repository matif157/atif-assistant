"""Location helpers.

Ingestion and routine derivation live in ``db`` because they are pure SQLite
work and must run offline. This module only adds the one thing that needs the
network: turning a coordinate into a human place name. It is best-effort and
never required - an unnamed place is still a usable place.
"""

from __future__ import annotations

from typing import Any

import httpx

# Nominatim asks for a descriptive User-Agent and a low request rate. One
# lookup per newly created place, not per fix, keeps well under the limit.
_NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_UA = "atif-assistant/0.1 (personal, local use)"


async def reverse_geocode(lat: float, lon: float, timeout: float = 6.0) -> dict[str, Any]:
    """Best-effort coordinate -> place name. Never raises.

    Returns {"label": str | None, "kind": str | None, "source": str | None}.
    On any failure the label is None and ingestion keeps working offline.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                _NOMINATIM,
                params={
                    "lat": f"{lat}",
                    "lon": f"{lon}",
                    "format": "jsonv2",
                    "zoom": "16",
                },
                headers={"User-Agent": _UA},
            )
        if r.status_code != 200:
            return {"label": None, "kind": None, "source": "nominatim-error"}
        data = r.json()
        addr = data.get("address", {}) or {}
        label = (
            addr.get("amenity")
            or addr.get("shop")
            or addr.get("building")
            or addr.get("road")
            or addr.get("suburb")
            or addr.get("neighbourhood")
            or data.get("name")
            or data.get("display_name")
        )
        kind = data.get("type") or data.get("category")
        return {"label": label, "kind": kind, "source": "nominatim"}
    except Exception:  # noqa: BLE001 - geocoding must never break ingestion
        return {"label": None, "kind": None, "source": None}
