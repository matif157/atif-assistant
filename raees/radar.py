"""Pattern Radar.

Matches an incoming message against stored patterns by trigger keywords.
Deliberately conservative: fires on keyword evidence only, never guesses.
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .config import PATTERN_LIMIT


def _tokens(text: str) -> set[str]:
    """Tokenise for pattern matching.

    Keeps digits attached to words so clock-time triggers like "3am", "4am"
    and "11pm" survive. Purely numeric tokens shorter than 4 chars are
    dropped to avoid noise.
    """
    words: set[str] = set()
    for raw in text.lower().split():
        w = "".join(ch for ch in raw if ch.isalnum())
        if not w:
            continue
        if len(w) > 3 or (any(ch.isdigit() for ch in w) and len(w) >= 2):
            words.add(w)
    return words


# Trigger words too generic to carry meaning on their own. Without this,
# "what did she feel" fires on "what is the capital of France".
_GENERIC = {"what", "when", "where", "which", "who", "does", "this", "that",
            "with", "from", "your", "yours", "hers", "their"}


def match_patterns(text: str) -> list[dict[str, Any]]:
    """Return patterns whose triggers overlap this message."""
    msg_tokens = _tokens(text)
    if not msg_tokens:
        return []

    hits: list[tuple[int, dict[str, Any]]] = []
    for pat in db.all_patterns():
        raw = pat.get("triggers") or "[]"
        try:
            triggers = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            triggers = []

        score = 0
        for trigger in triggers:
            trigger_tokens = _tokens(str(trigger))
            # A multi-word trigger must match substantially, not on one
            # shared word. Require every distinctive token to be present.
            distinctive = trigger_tokens - _GENERIC
            if not distinctive:
                distinctive = trigger_tokens
            if not distinctive:
                continue
            overlap = distinctive & msg_tokens
            # All distinctive words present, or at least half of them.
            if len(overlap) == len(distinctive) or len(overlap) * 2 >= len(distinctive):
                score += len(overlap) + (1 if len(overlap) == len(distinctive) else 0)

        if score:
            hits.append((score, pat))

    hits.sort(key=lambda p: p[0], reverse=True)
    return [p for _, p in hits[:PATTERN_LIMIT]]


def render_patterns(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return ""
    lines = ["PATTERN RADAR - relevant history:"]
    for p in patterns:
        lines.append(f"\n- {p['name']}")
        if p.get("trigger"):
            lines.append(f"  Trigger: {p['trigger']}")
        if p.get("observed"):
            lines.append(f"  Observed: {p['observed']}")
        if p.get("effect"):
            lines.append(f"  Effect: {p['effect']}")
        if p.get("intervention"):
            lines.append(f"  Intervention: {p['intervention']}")
    lines.append(
        "\nSurface this only if it genuinely applies. Do not narrate it "
        "mechanically."
    )
    return "\n".join(lines)