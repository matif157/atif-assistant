"""Mirror layer (Phase 3): adopt the user's thought pattern and writing way.

Three EMA dimensions, learned from the user's own messages across sessions
and stored as the ``profiles`` document ``"style"``:

- avg_words    their message length, so replies land at the same rhythm
- formality    formal-vs-casual marker ratio (0..1)
- urdu_ratio   share of messages that are Urdu (script or Roman Urdu)

Overrides (the editable Profile card) pin any dimension to a fixed label and
live in a separate document so learning never clobbers a user edit.
``render_block`` turns the profile plus 1-2 of the user's own recent messages
into a bounded prompt block: rhythm and shape only - the block says so, at
most two truncated examples are ever included, and the whole block is capped
so it can never crowd out retrieval or labels.
"""

from __future__ import annotations

import re
from typing import Any

from . import db

# EMA rate: a new message moves the average visibly, but never flips it.
_LEARNING = 0.3

_BLOCK_CAP = 700
_EXAMPLE_CAP = 160

_FORMAL = (
    "please", "kindly", "could you", "would you", "shall we", "thank you",
    "thanks in advance", "regards", "sincerely", "regarding", "assist",
    "assistance", "request", "appreciate", "grateful", "certainly",
    "pursuant", "hereby", "respectfully",
)

_CASUAL = (
    "lol", "haha", "hehe", "yaar", "bhai", "bro", "dude", "gonna", "wanna",
    "kinda", "sorta", "nah", "yep", "yeah", "ok", "okay", "cool", "hmm",
    "hm", "thx", "plz", "btw", "idk", "imo", "kya", "acha", "chal", "bas",
    "oye",
)

# Allowed values for the editable Profile card, mirroring app.py's endpoint.
LENGTH_KEYS = ("auto", "brief", "medium", "detailed")
REGISTER_KEYS = ("auto", "casual", "mixed", "formal")
LANGUAGE_KEYS = ("auto", "english", "urdu", "mixed")


def _count(text: str, terms: tuple[str, ...]) -> int:
    from .constitution import _matches  # local: avoids a module-level cycle

    return len(_matches(text.lower(), terms))


def _urdu_flag(text: str) -> float:
    from .engine import detect_language  # lazy: engine imports this module

    return 1.0 if detect_language(text) == "ur" else 0.0


def _ema(old: Any, new: float) -> float:
    try:
        old_f = float(old)
    except (TypeError, ValueError):
        return round(float(new), 3)
    return round(_LEARNING * float(new) + (1 - _LEARNING) * old_f, 3)


def observe(message: str) -> dict[str, Any]:
    """Fold one user message into the style profile; returns the new profile."""
    prior = db.get_profile("style") or {}
    words = float(len((message or "").split()))
    formal = _count(message, _FORMAL)
    casual = _count(message, _CASUAL)
    register = formal / (formal + casual) if (formal + casual) else None

    style: dict[str, Any] = dict(prior)
    style["n"] = int(style.get("n") or 0) + 1
    style["avg_words"] = _ema(style.get("avg_words"), words)
    if register is not None:
        style["formality"] = _ema(style.get("formality"), register)
    style["urdu_ratio"] = _ema(style.get("urdu_ratio"), _urdu_flag(message))
    db.set_profile("style", style)
    return style


def length_of(style: dict[str, Any] | None) -> str:
    avg = float((style or {}).get("avg_words") or 0)
    if avg <= 8:
        return "brief"
    if avg >= 24:
        return "detailed"
    return "medium"


def register_of(style: dict[str, Any] | None) -> str:
    f = (style or {}).get("formality")
    if f is None:
        return "mixed"
    f = float(f)
    if f >= 0.65:
        return "formal"
    if f <= 0.35:
        return "casual"
    return "mixed"


def language_of(style: dict[str, Any] | None) -> str:
    r = float((style or {}).get("urdu_ratio") or 0)
    if r >= 0.6:
        return "urdu"
    if r <= 0.3:
        return "english"
    return "mixed"


def render_block(
    style: dict[str, Any] | None,
    examples: list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    """The bounded prompt block for the mirror layer; empty until learned."""
    if not style or int(style.get("n") or 0) < 2:
        return ""
    ov = overrides or {}

    def pick(key: str, learned: str, keys: tuple[str, ...]) -> str:
        chosen = (ov.get(key) or "auto").strip().lower()
        return chosen if chosen in keys and chosen != "auto" else learned

    length = pick("length", length_of(style), LENGTH_KEYS)
    register = pick("register", register_of(style), REGISTER_KEYS)
    language = pick("language", language_of(style), LANGUAGE_KEYS)

    lines = [
        "MIRROR STYLE (how this user writes - match their rhythm and "
        "register; their words below are examples of SHAPE only, never "
        "evidence for facts):",
        f"- reply length: {length}; register: {register}; "
        f"language lean: {language}.",
    ]
    ex = [" ".join((e or "").split()) for e in (examples or []) if (e or "").strip()]
    if ex:
        lines.append("Their own recent messages (tone and shape only):")
        for e in ex[-2:]:
            lines.append(f'- "{e[:_EXAMPLE_CAP]}"')
    block = "\n".join(lines)
    if len(block) > _BLOCK_CAP:
        block = block[:_BLOCK_CAP]
    return block
