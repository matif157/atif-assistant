"""Raees reasoning engine.

Three modes:
  ask       - normal answer, but every claim labelled by the Reality Engine
  challenge - builds the case AGAINST the user's position
  decide    - full pipeline: options, reversibility, recommendation, ledger
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import constitution as C
from . import db, radar
from .config import RETRIEVAL_LIMIT
from .llm import ProviderError, complete

# ---------------------------------------------------------------- prompting

SYSTEM_BASE = f"""You are Raees, a personal intelligence system for one user.

{C.constitution_block()}

Reasoning protocol (internal, never printed):
{C.REASONING_PROTOCOL}

Style: direct, plain, no flattery, no therapeutic voice, no emojis.
Roman Urdu input is fine - reply in the same language the user used.
Never roleplay as a romantic partner or girlfriend.
Length: as short as the answer allows. No preamble.
"""

LABEL_INSTRUCTIONS = """
REQUIRED OUTPUT STRUCTURE:

Label every substantive claim with one of:
[FACT]        - directly supported by evidence the user provided or that is in memory
[INFERENCE]   - a reasoned conclusion from those facts
[ASSUMPTION]  - something believed but not established
[UNKNOWN]     - the available information cannot determine it
[PREDICTION]  - what is likely to happen, not certain

Format each as its own short line, then a brief plain-language explanation.
Example:
[FACT] She wrote that she wanted her ex "BHT" (a lot).
[UNKNOWN] How she ranked the user against that ex. No evidence supports a comparison.
[INFERENCE] The ex was emotionally significant to her.
[ASSUMPTION] That the user was loved less. Nothing in the record establishes this.

Rules:
- Never invent a comparison, ranking or percentage between people.
- If asked "does she love me more", the correct core answer is UNKNOWN.
- Never recommend searching old messages or re-reading chats to resolve a feeling.
- Say plainly when the user is wrong.
"""

CHALLENGE_INSTRUCTIONS = """
CHALLENGE MODE. Your job is to argue AGAINST the user's position, not to
comfort them and not to agree.

Output these sections in order:

CASE FOR: the strongest honest version of their position.

CASE AGAINST: the strongest honest version of why this is wrong.

WHAT YOU ARE OVERLOOKING: the thing they have not considered.

WHAT EMOTION IS DRIVING THIS: name the likely driver honestly.

WORST CASE: if this is wrong and they proceed.

BEST CASE: if they are right.

MOST PROBABLE: what actually happens, given the pattern.

BETTER ALTERNATIVE: one concrete different action.

RECOMMENDATION: one clear sentence.

Be direct. Do not soften the case against. Do not end with "but you decide"
if you have a view. Have a view.
"""

DECIDE_INSTRUCTIONS = """
DECISION MODE. Structure your answer exactly:

OPTIONS: 2-4 real options, named.

REVERSIBILITY: which choices can be undone later, which cannot.

CONSEQUENCES: for each option, what happens in 1 month / 1 year.

ASSUMPTIONS IN PLAY: what you are assuming that might be false.

MISSING INFORMATION: what you would need to know to be more confident.

RECOMMENDATION: one option, one reason.

CONFIDENCE: a percentage with one sentence of justification.

REVIEW: when this decision should be re-examined.
"""

BASE_SYSTEM = SYSTEM_BASE


def build_context(question: str) -> dict[str, Any]:
    memories = db.search_memory(question, limit=RETRIEVAL_LIMIT)
    patterns = radar.match_patterns(question)

    parts: list[str] = []
    if memories:
        parts.append("RETRIEVED MEMORY (cite only what is relevant):")
        for m in memories:
            kind = m["kind"].upper()
            conf = m.get("confidence")
            extra = f" [confidence {conf:.2f}]" if isinstance(conf, float) else ""
            verified = m.get("last_verified")
            if verified:
                extra += f" [last verified {verified}]"
            body = m.get("text") or m.get("title") or ""
            parts.append(f"- ({kind}{extra}) {body}")
    if patterns:
        pr = radar.render_patterns(patterns)
        if pr:
            parts.append(pr)

    risks = C.detect_professional_risk(question)
    rumination = C.detect_rumination(question)
    objective = C.hidden_objective(question)

    return {
        "memories": memories,
        "patterns": patterns,
        "context_block": "\n\n".join(parts),
        "professional_risk": risks,
        "rumination": rumination,
        "hidden_objective": objective,
    }


def _guardrails(ctx: dict[str, Any]) -> str:
    lines = []
    obj = ctx["hidden_objective"]
    if obj != "UNCLEAR - classify before answering.":
        lines.append(f"CLASSIFIED INTENT: {obj}")
    if ctx["rumination"]:
        lines.append(
            "RUMINATION RISK: this request asks for evidence about an "
            "uncertainty that evidence cannot resolve. Do NOT encourage "
            "searching old messages, re-reading chats, or collecting more "
            "proof. Give a short honest answer and redirect to a decision."
        )
    if ctx["professional_risk"]:
        lines.append(
            "PROFESSIONAL DOMAIN: "
            + ", ".join(ctx["professional_risk"])
            + ". State clearly that this needs a qualified professional, "
            "and give the practical next step."
        )
    return "\n".join(lines)


# ------------------------------------------------------------ Reality Engine

_LABEL_RE = re.compile(
    r"\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]", re.IGNORECASE
)


def parse_labels(text: str) -> list[dict[str, str]]:
    out = []
    for line in text.splitlines():
        m = _LABEL_RE.search(line)
        if m:
            out.append(
                {
                    "label": m.group(1).upper(),
                    "text": _LABEL_RE.sub("", line).strip(" -*:"),
                }
            )
    return out


# Ranking/percentage fabrication the brake must catch.
_FABRICATION = re.compile(
    r"(\d{1,3}\s*%\s*(more|less|love|likely)|she loved (him|him more) more|"
    r"loved (him|him more) more than)",
    re.IGNORECASE,
)


def audit_response(text: str) -> list[str]:
    """Post-hoc brake. Returns warnings if the model broke a hard rule."""
    warnings = []
    if _FABRICATION.search(text):
        warnings.append(
            "BRAKE: response contained a comparison or percentage the "
            "evidence does not support. Treat that claim as withdrawn."
        )
    if not _LABEL_RE.search(text):
        warnings.append(
            "BRAKE: response carried no Reality Engine labels. Claims are "
            "unverified."
        )
    return warnings


# --------------------------------------------------------------- generators

async def _ask(question: str, ctx: dict[str, Any]) -> dict[str, Any]:
    ctx_block = ctx["context_block"]
    guard = _guardrails(ctx)

    user_content = "\n\n".join(
        part
        for part in (
            ctx_block,
            f"GUARDRAILS:\n{guard}" if guard else "",
            f"QUESTION: {question}",
        )
        if part
    )

    messages = [
        {"role": "system", "content": BASE_SYSTEM + LABEL_INSTRUCTIONS},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages)
    except ProviderError:
        text, provider = _offline_answer(question, ctx), "offline"

    return {
        "text": text,
        "provider": provider,
        "labels": parse_labels(text),
        "warnings": audit_response(text),
        "patterns": [
            {"name": p["name"], "intervention": p.get("intervention")}
            for p in ctx["patterns"]
        ],
        "intent": ctx["hidden_objective"],
        "rumination": ctx["rumination"],
        "professional_risk": ctx["professional_risk"],
        "memories_used": len(ctx["memories"]),
    }


async def _challenge(question: str, ctx: dict[str, Any]) -> dict[str, Any]:
    guard = _guardrails(ctx)
    user_content = "\n\n".join(
        part
        for part in (
            ctx["context_block"],
            f"GUARDRAILS:\n{guard}" if guard else "",
            f"POSITION TO CHALLENGE: {question}",
        )
        if part
    )
    messages = [
        {"role": "system", "content": BASE_SYSTEM + CHALLENGE_INSTRUCTIONS},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages, temperature=0.55)
    except ProviderError:
        text, provider = _offline_challenge(question, ctx), "offline"

    return {
        "text": text,
        "provider": provider,
        "labels": [],
        "warnings": [],
        "patterns": [
            {"name": p["name"], "intervention": p.get("intervention")}
            for p in ctx["patterns"]
        ],
        "intent": ctx["hidden_objective"],
        "rumination": ctx["rumination"],
        "professional_risk": ctx["professional_risk"],
        "memories_used": len(ctx["memories"]),
    }


async def _decide(question: str, ctx: dict[str, Any]) -> dict[str, Any]:
    guard = _guardrails(ctx)
    user_content = "\n\n".join(
        part
        for part in (
            ctx["context_block"],
            f"GUARDRAILS:\n{guard}" if guard else "",
            f"DECISION: {question}",
        )
        if part
    )
    messages = [
        {"role": "system", "content": BASE_SYSTEM + DECIDE_INSTRUCTIONS},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages, temperature=0.35)
    except ProviderError:
        text, provider = _offline_answer(question, ctx), "offline"

    return {
        "text": text,
        "provider": provider,
        "labels": [],
        "warnings": [],
        "patterns": [
            {"name": p["name"], "intervention": p.get("intervention")}
            for p in ctx["patterns"]
        ],
        "intent": ctx["hidden_objective"],
        "rumination": ctx["rumination"],
        "professional_risk": ctx["professional_risk"],
        "memories_used": len(ctx["memories"]),
    }


# ------------------------------------------------------- offline fallbacks

def _offline_answer(question: str, ctx: dict[str, Any]) -> str:
    lines = ["[UNKNOWN] No model provider is configured, so this is not an analysis.", ""]
    lines.append(
        "Raees cannot think right now. Set GROQ_API_KEY (free tier) in "
        ".env and restart. Retrieval and the brake still work offline."
    )
    if ctx["rumination"]:
        lines += [
            "",
            "[INFERENCE] This request asks for evidence that cannot resolve "
            "an uncertainty.",
            "[PREDICTION] Searching old messages will raise the urge to "
            "search again, not lower it.",
        ]
    if ctx["memories"]:
        lines += ["", "Relevant memory is still searchable - try again once a model is set."]
    return "\n".join(lines)


def _offline_challenge(question: str, ctx: dict[str, Any]) -> str:
    return (
        "[UNKNOWN] No model provider configured, so the adversarial pass did not run.\n\n"
        "CASE FOR: not generated offline.\n\n"
        "CASE AGAINST: if the evidence you are relying on requires repeated "
        "searching to find, that is itself evidence it is not there.\n\n"
        "RECOMMENDATION: set GROQ_API_KEY and re-run /challenge."
    )


async def respond(question: str, mode: str = "ask") -> dict[str, Any]:
    ctx = build_context(question)
    if mode == "challenge":
        return await _challenge(question, ctx)
    if mode == "decide":
        return await _decide(question, ctx)
    return await _ask(question, ctx)