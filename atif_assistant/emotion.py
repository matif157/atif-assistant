"""Emotion layer for the Soul (Phase 2): mood detection from the user's message.

Offline, deterministic keyword inference - the same word-boundary matching
constitution._matches uses, over English, Urdu script and Roman Urdu cue
words. Everything this module returns is an INFERENCE, never a stored fact:
build_context() renders it into the prompt with an explicit "never state as
fact, never announce the label" instruction, and /api/ask exposes it so the
UI can show a mood chip. A neutral message produces no block at all, so plain
knowledge questions reach the model unchanged.
"""

from __future__ import annotations

from typing import Any

from .constitution import _matches

# mood -> cue words and phrases, matched as whole words. Roman Urdu sits
# beside English because the user mixes both inside one sentence; Urdu script
# forms are included too (script input is decisive in detect_language, so the
# mood layer must not miss it). Phrases with spaces work because _matches
# anchors the ends of the whole phrase.
MOOD_CUES: dict[str, tuple[str, ...]] = {
    "sad": (
        "sad", "unhappy", "depress", "depressed", "miserable", "hopeless",
        "crying", "cries", "tears", "feel empty", "empty inside",
        "broken inside", "heartbroken",
        "udaas", "dukhi", "dukhiya", "rona", "aansu", "dil tuta",
        "اداس", "دکھی", "رونا", "آنسو", "دل ٹوٹا", "دل ٹوٹ",
    ),
    "lonely": (
        "lonely", "alone", "no one cares", "koi nahi", "akela", "akeli",
        "isolated", "ignored", "left out", "miss kar raha", "miss kar rahi",
        "اکیلا", "اکیلی", "کوئی نہیں", "تنہائی",
    ),
    "anxious": (
        "anxious", "anxiety", "worry", "worried", "stressed", "stress",
        "panic", "nervous", "overthink", "tension", "scared", "afraid",
        "pareshan", "fikr", "ghabra", "darr", "bechain", "neend nahi",
        "پریشان", "فکر", "گھبرا", "ڈر", "بے چین", "نیند نہیں", "خوف",
    ),
    "angry": (
        "angry", "furious", "rage", "frustrated", "frustration", "annoyed",
        "mad at", "fed up", "gussa", "ghussa", "naaraaz", "chidchida",
        "tang aa", "غصہ", "ناراض",
    ),
    "tired": (
        "tired", "exhausted", "drained", "burnt out", "burnout", "sleepy",
        "no energy", "thaka", "thak gaya", "thak gayi", "haust",
        "neend aa rahi", "neend aa raha", "تھک", "تھکا", "تھکی",
    ),
    "confused": (
        "confused", "confusing", "don't understand", "dont understand",
        "do not understand", "no idea", "clueless", "samajh nahi",
        "pata nahi chal", "پتہ نہیں چل", "سمجھ نہیں",
    ),
    "happy": (
        "happy", "great day", "good news", "excited", "amazing", "grateful",
        "blessed", "khush", "maza aa", "shukar", "acha laga", "dil khush",
        "خوش", "شکر", "مزہ",
    ),
    "affectionate": (
        "love you", "miss you", "pyar", "yaad aati", "yaad aa raha",
        "yaad aa rahi", "care karta", "care karti", "dil se",
        "پیار", "یاد آتی", "یاد آ رہا",
    ),
}

# Families used only for the turn-to-turn trajectory label.
_NEGATIVE = frozenset({"sad", "lonely", "anxious", "angry", "tired", "confused"})
_POSITIVE = frozenset({"happy", "affectionate"})


def detect_mood(text: str) -> dict[str, Any]:
    """Classify the message's mood by cue evidence. Neutral when nothing fires.

    Ties go to the first mood in MOOD_CUES order (sad first): a message that
    reads as both sad and anxious leads with sadness, which is the safer
    opening for a warm reply.
    """
    low = (text or "").lower()
    best_mood, best_hits = "neutral", []
    for mood, cues in MOOD_CUES.items():
        hits = [c for c in cues if _matches(low, (c,))]
        if len(hits) > len(best_hits):
            best_mood, best_hits = mood, hits
    if not best_hits:
        return {"mood": "neutral", "score": 0.0, "cues": []}
    score = min(0.5 + 0.2 * (len(best_hits) - 1), 0.9)
    return {"mood": best_mood, "score": round(score, 2), "cues": best_hits[:4]}


def trajectory(current_mood: str, previous_texts: list[str]) -> str:
    """How the mood moved across turns: steady / improving / worsening /
    shifting / neutral / single turn. Previous user messages, oldest first.
    """
    seen = [detect_mood(t)["mood"] for t in previous_texts if (t or "").strip()]
    if not seen:
        return "single turn"
    prev = next((m for m in reversed(seen) if m != "neutral"), "neutral")
    now = current_mood
    if now == "neutral":
        return "improving" if prev != "neutral" else "neutral"
    if prev == "neutral":
        return "worsening" if now in _NEGATIVE else "improving"
    if now == prev:
        return "steady"
    if now in _POSITIVE and prev in _NEGATIVE:
        return "improving"
    if now in _NEGATIVE and prev in _POSITIVE:
        return "worsening"
    return "shifting"


def render_block(mood: dict[str, Any], trajectory_label: str = "") -> str:
    """The prompt block for a non-neutral mood; empty for neutral.

    Labelled as inference twice - once at the header, once in the closing
    instruction - because a small model reads the mood line as a fact about
    the user and will otherwise announce it ("you seem sad").
    """
    if mood.get("mood", "neutral") == "neutral":
        return ""
    lines = [
        "USER MOOD (keyword INFERENCE from this message - never state it as "
        "fact, never announce the label to the user, never treat it as a "
        "diagnosis):",
        f"- mood: {mood['mood']} [confidence {mood.get('score', 0):.2f}] "
        f"cues: {', '.join(mood.get('cues', []))}",
    ]
    if trajectory_label and trajectory_label not in ("single turn", "neutral"):
        lines.append(f"- trajectory across turns: {trajectory_label}")
    lines.append(
        "Meet the mood first with one warm line (Roman Urdu/Urdu fits here), "
        "then answer the question. Warmth never replaces the labels."
    )
    return "\n".join(lines)
