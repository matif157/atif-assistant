"""Evolution loop (Phase 4): feedback -> reflection -> propose-then-approve.

Deterministic and offline - no model call. Unapplied feedback is folded into
PENDING proposals (a user note on 👎/edit/regenerate IS the proposal text) and
the feedback queue is drained. Zero silent changes: nothing in this module
writes to the ``rules`` table; only the explicit approve endpoint does, and
that endpoint records the user's press as the approval. Insights (ratios,
mood mix) are computed live at read time instead of stored, so they can never
stale or re-approve themselves.
"""

from __future__ import annotations

from typing import Any

from . import db

# Feedback kinds whose attached note becomes a proposal. "up" is praise, not
# an instruction; plain "down" without a note has nothing actionable to say.
NOTE_KINDS = ("down", "edit", "regenerate", "note")

_TITLE_CAP = 160


def _title_from(note: str, kind: str) -> str:
    flat = " ".join(note.split())
    if len(flat) > _TITLE_CAP:
        flat = flat[: _TITLE_CAP - 1].rstrip() + "…"
    return flat


def reflect(limit: int = 50) -> list[dict[str, Any]]:
    """Fold unapplied feedback into proposals; returns the ones created this
    call. Every processed row is marked applied whether or not it produced a
    proposal, so the queue cannot loop."""
    created: list[dict[str, Any]] = []
    seen_titles = {
        r["title"] for r in db.list_reflections(limit=500)
    }
    for fb in db.list_feedback(limit, only_unapplied=True):
        note = (fb.get("note") or "").strip()
        if note and fb.get("kind") in NOTE_KINDS:
            title = _title_from(note, fb["kind"])
            if title not in seen_titles:
                rid = db.create_reflection(
                    title=title,
                    detail=f"From your {fb['kind']} signal"
                    + (f" on {fb.get('created_at')}" if fb.get("created_at") else "")
                    + ".",
                    source=[fb["id"]],
                )
                seen_titles.add(title)
                item = db.get_reflection(rid)
                if item:
                    created.append(item)
        db.mark_feedback_applied(fb["id"])
    return created


def insights() -> list[str]:
    """Live, derived observations for the Growth tab. Never stored."""
    counts = db.feedback_counts()
    total = sum(counts.values())
    downs = counts.get("down", 0)
    ups = counts.get("up", 0)
    lines: list[str] = []
    if downs >= 2:
        lines.append(
            f"{downs} of {total or downs} signals were 👎 - the notes attached "
            "to them are waiting as proposals below."
        )
    elif downs == 1 and total >= 1:
        lines.append("1 👎 so far - attach a note next time to turn it into a proposal.")
    if ups >= 3:
        lines.append(f"{ups} 👍 - the current voice is landing; keep the notes coming.")

    moods = db.mood_timeline(50)
    tally: dict[str, int] = {}
    for m in moods:
        name = m.get("mood") or "neutral"
        if name != "neutral":
            tally[name] = tally.get(name, 0) + 1
    if tally:
        mix = ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))
        lines.append(f"Mood mix from your last {len(moods)} detected turns: {mix}.")
    return lines
