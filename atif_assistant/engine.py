"""Atif Assistant reasoning engine.

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

SYSTEM_BASE = f"""You are Atif Assistant, a personal intelligence system for one user.

{C.constitution_block()}

Reasoning protocol (internal, never printed):
{C.REASONING_PROTOCOL}

Identity: you are not a person, a companion or a chatbot. You have no moods,
feelings, body or personal life, and you never pretend to. Never answer social
pleasantries with small talk or a reciprocal question - no "I'm good, what
about you?". Treat "how are you" as a request for operational status: one
plain line, then the substance. Do not thank, do not flatter, do not roleplay
as a friend, assistant-persona or romantic partner.
Roman Urdu input is fine. Obey the LANGUAGE rule when one is given.
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

Label the key claim in each section with [FACT], [INFERENCE], [ASSUMPTION],
[UNKNOWN] or [PREDICTION]. Never drop a section header.
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

Label the key claim in each section with [FACT], [INFERENCE], [ASSUMPTION],
[UNKNOWN] or [PREDICTION].
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

    low_words = [w for w in question.lower().split() if len(w) > 3]

    # A detected contradiction outranks a clean retrieval: if two stored facts
    # cannot both be true, the answer must surface that before anything else.
    contradictions = db.find_contradictions(limit=3)
    relevant_contradictions = (
        [
            c
            for c in contradictions
            if c.get("a")
            and any(w in c["subject"].split() for w in low_words)
        ]
        or contradictions[:1]
    )
    if relevant_contradictions:
        parts.append(
            "CONFLICTING MEMORY. These two stored facts cannot both be true. "
            "Do not pick one silently - state the conflict and say which one "
            "the evidence favours, or that it cannot be resolved."
        )
        for c in relevant_contradictions:
            parts.append(f"- ({c['subject']}) A: {c['a']}")
            if c.get("b"):
                parts.append(f"- ({c['subject']}) B: {c['b']}")

    # Location memory, surfaced only when the question is about it, so it does
    # not crowd every answer. These are observed visits and candidate patterns;
    # a reason is never attached here.
    loc_words = (
        "where", "location", "routine", "routine", "place", "places",
        "visit", "visits", "went", "gym", "office",
    )
    if any(w in question.lower() for w in loc_words):
        routines = db.list_routines(limit=5)
        places = [p for p in db.list_places(limit=8) if p.get("name")]
        if routines or places:
            lines = ["LOCATION MEMORY (observed visits only; reasons are NOT known):"]
            for p in places:
                lines.append(
                    f"- place: {p['name']} ({p.get('kind') or 'unlabelled'}), "
                    f"{p['visits']} visits"
                )
            for r in routines:
                lines.append(
                    f"- routine (candidate): {r['name']} "
                    f"[confidence {r['confidence']}, {r['observations']} observations]"
                )
            parts.append("\n".join(lines))

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
        "contradictions": relevant_contradictions,
        "escalations": [],
        "language": None,
        "detail": None,
    }


def _language_rule(language: str | None) -> str:
    """The output-language instruction, or empty for the default (English)."""
    if (language or "").lower().startswith("ur"):
        return (
            "LANGUAGE RULE (this overrides the language of the question and of "
            "any draft): write the ENTIRE answer in Urdu (اردو) - headings, "
            "sections and explanations all in Urdu script. Keep only the "
            "bracketed labels [FACT] [INFERENCE] [ASSUMPTION] [UNKNOWN] "
            "[PREDICTION] in English so the Reality Engine can read them."
        )
    return ""


def _system_with(ctx: dict[str, Any], instructions: str) -> str:
    rule = _language_rule(ctx.get("language"))
    return BASE_SYSTEM + instructions + (f"\n\n{rule}" if rule else "")


def _guardrails(ctx: dict[str, Any]) -> str:
    lines = []
    obj = ctx["hidden_objective"]
    if obj != "UNCLEAR - classify before answering.":
        lines.append(f"CLASSIFIED INTENT: {obj}")
    for e in ctx.get("escalations", []):
        lines.append(f"ROUTER REQUIREMENT: {e}")
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
    # Output language and length are user settings. The reality labels stay in
    # English brackets so the Reality Engine can still parse and colour them.
    if (ctx.get("language") or "").lower().startswith("ur"):
        lines.append(
            "LANGUAGE: answer in Urdu (اردو). Keep the bracketed labels "
            "[FACT] [INFERENCE] [ASSUMPTION] [UNKNOWN] [PREDICTION] in English."
        )
    detail = ctx.get("detail")
    if detail == "short":
        lines.append("LENGTH: be brief. A few sentences at most.")
    elif detail == "deep":
        lines.append("LENGTH: be thorough and explain the reasoning.")
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


# A challenge that ends without a position is a challenge that failed.
_HEDGE_OUT = re.compile(
    r"(but you decide|at the end of the day|only you can know|"
    r"it depends on you|whatever you (feel|think)|"
    r"you know (best|yourself) (better|what)|"
    r"time will tell|mai apni marzi)",
    re.IGNORECASE,
)

# Language that hands the verdict back to the user instead of reasoning.
_SOFTENING = re.compile(
    r"(you're doing (great|fine|well)|it'?s completely normal|"
    r"you seem like a (really )?(good|nice) (person|man)|"
    r"don'?t be so hard on yourself|give yourself (credit|a break)|"
    r"your feelings are valid)",
    re.IGNORECASE,
)


_REQUIRED_CHALLENGE_SECTIONS = (
    "CASE FOR",
    "CASE AGAINST",
    "RECOMMENDATION",
)


def structure_ok(text: str, challenge_mode: bool = False) -> bool:
    """True when the response keeps the Reality Engine's required structure."""
    if not _LABEL_RE.search(text):
        return False
    if challenge_mode:
        upper = text.upper()
        if any(section not in upper for section in _REQUIRED_CHALLENGE_SECTIONS):
            return False
    return True


# Chatbot small talk / fake-persona slips.
_SMALL_TALK = re.compile(
    r"(what about you|how about you|and you\?|nice to meet you|"
    r"\bi'?m (good|fine|well|great)\b|\bi am (good|fine|well|great)\b|"
    r"as your (assistant|friend)|i'?d love to|how'?s your day|"
    r"i hope you'?re (doing )?(well|good|okay|ok))",
    re.IGNORECASE,
)


def audit_response(text: str, challenge_mode: bool = False) -> list[str]:
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
    if _HEDGE_OUT.search(text):
        warnings.append(
            "BRAKE: response handed the decision back to the user instead of "
            "reasoning to a position."
        )
    if _SOFTENING.search(text):
        warnings.append(
            "BRAKE: response used reassurance language in place of analysis."
        )
    if _SMALL_TALK.search(text):
        warnings.append(
            "BRAKE: response slipped into chatbot small talk. Atif Assistant "
            "has no mood or personal life."
        )
    if challenge_mode:
        for required in ("CASE AGAINST", "RECOMMENDATION"):
            if required.upper() not in text.upper():
                warnings.append(
                    f"BRAKE: challenge is missing the {required} section."
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
        {"role": "system", "content": _system_with(ctx, LABEL_INSTRUCTIONS)},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages)
    except ProviderError:
        text, provider = _offline_answer(question, ctx), "offline"

    # Adversarial second pass: find what the draft got wrong, then fix it.
    draft = text
    critique, revised, critique_notes = await _self_critique(
        question, text, ctx, provider
    )
    if revised and (structure_ok(revised) or not structure_ok(draft)):
        text = revised
    if provider != "offline" and not structure_ok(text):
        repaired = await _repair_structure(
            text, provider, language=ctx.get("language")
        )
        if structure_ok(repaired):
            text = repaired
            critique_notes.append("Answer reformatted to restore Reality Engine labels.")

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
        "critique": critique_notes,
    }


# ------------------------------------------------- adversarial self-critique

CRITIQUE_INSTRUCTIONS = """
You are auditing another AI's draft answer. Your job is to find its failures.

Check, in order:
1. FABRICATION - did it assert anything the evidence does not support?
2. SYMPATHY DRIFT - did it soften a truth, or validate a conclusion it
   should have challenged?
3. PREMISE COMPLIANCE - did it accept an unmeasurable premise (comparing
   feelings, ranking people) instead of refusing it?
4. MISSED QUESTION - is the user actually asking something the draft avoided?
5. LABEL HONESTY - are the FACT/INFERENCE/ASSUMPTION labels accurate, or is
   an assumption dressed up as a fact?
6. RUMINATION ENABLEMENT - does it encourage searching for more evidence?

Output STRICTLY:
VERDICT: SOUND | NEEDS_REVISION
DEFECTS: numbered list, or NONE
REVISION: the corrected answer in full, or EMPTY if SOUND
"""


async def _self_critique(
    question: str,
    draft: str,
    ctx: dict[str, Any],
    provider: str,
    audit_challenge: bool = False,
) -> tuple[dict[str, Any], str | None, list[str]]:
    """Second pass over the draft. Fails soft - never breaks the answer."""
    if provider == "offline" or not draft.strip():
        return {}, None, []

    extra: list[str] = []
    if audit_challenge:
        extra.append(
            "This draft was a CHALLENGE. It is meant to argue against the "
            "user. If it ended up agreeing, softening, or leaving the user to "
            "decide without a view, that is a critical defect."
        )
    for e in ctx.get("escalations", []):
        extra.append(f"ROUTER REQUIREMENT: {e}")

    ctx_block = ctx["context_block"]
    user_content = "\n\n".join(
        part
        for part in (
            ctx_block,
            "\n".join(extra),
            f"ORIGINAL QUESTION: {question}",
            f"DRAFT ANSWER TO AUDIT:\n{draft}",
        )
        if part and part.strip()
    )
    system = BASE_SYSTEM + CRITIQUE_INSTRUCTIONS + _language_rule(ctx.get("language"))
    if audit_challenge:
        system += "\n7. CHALLENGE INTEGRITY - did it actually push back?\n"
    # A revision must not strip the mandated output structure, or the brake
    # fires on an answer that was otherwise correct.
    system += (
        "\nFORMAT RULES FOR THE REVISION: label every substantive claim with "
        "[FACT], [INFERENCE], [ASSUMPTION], [UNKNOWN] or [PREDICTION]."
    )
    if audit_challenge:
        system += (
            " Keep these section headers exactly: "
            + ", ".join(_REQUIRED_CHALLENGE_SECTIONS)
            + "."
        )
    system += " Never remove labels or required section headers.\n"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    try:
        raw, _ = await complete(messages, temperature=0.2, max_tokens=2200)
    except ProviderError:
        return {}, None, []

    verdict = "SOUND"
    m = re.search(r"VERDICT:\s*(SOUND|NEEDS_REVISION)", raw, re.IGNORECASE)
    if m:
        verdict = m.group(1).upper()

    defects: list[str] = []
    dm = re.search(r"DEFECTS:\s*(.+?)(?:\nREVISION:|\Z)", raw, re.DOTALL | re.I)
    if dm:
        block = dm.group(1).strip()
        if block.upper() not in {"NONE", "NONE.", "-"}:
            defects = [
                re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
                for line in block.splitlines()
                if line.strip()
            ]

    revision = None
    rm = re.search(r"REVISION:\s*(.+)\Z", raw, re.DOTALL | re.I)
    if rm:
        candidate = rm.group(1).strip()
        # A revision that is empty, a placeholder, or obviously truncated is
        # discarded rather than replacing a working draft.
        if len(candidate) > 80 and candidate.upper() not in {"EMPTY", "NONE", "N/A"}:
            revision = candidate

    notes: list[str] = []
    if defects:
        notes.append(f"Self-critique ({verdict}): " + "; ".join(defects[:3]))
    if revision:
        notes.append("Answer revised after adversarial pass.")

    return {"verdict": verdict, "defects": defects}, revision, notes


async def _repair_structure(
    text: str,
    provider: str,
    challenge_mode: bool = False,
    language: str | None = None,
) -> str:
    """Last resort: re-emit an answer with labels and section headers intact.

    Content must not change - only the formatting the brake requires. Fails
    soft: on any error the original text is returned untouched.
    """
    if provider == "offline" or not text.strip():
        return text
    rules = (
        "Reformat the ANSWER below. Do not add, remove or soften any claim, do "
        "not answer anything new - only restore the required formatting. Label "
        "every substantive claim with [FACT], [INFERENCE], [ASSUMPTION], "
        "[UNKNOWN] or [PREDICTION]."
    )
    if challenge_mode:
        rules += (
            " Keep these section headers exactly, in order: "
            + ", ".join(_REQUIRED_CHALLENGE_SECTIONS)
            + "."
        )
    rules += " Output only the reformatted answer, with no commentary."
    lang = _language_rule(language)
    system = BASE_SYSTEM + "\n" + rules + (f"\n{lang}" if lang else "")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"ANSWER:\n{text}"},
    ]
    try:
        raw, _ = await complete(messages, temperature=0.1, max_tokens=2200)
    except ProviderError:
        return text
    return raw.strip() if raw.strip() else text


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
        {"role": "system", "content": _system_with(ctx, CHALLENGE_INSTRUCTIONS)},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages, temperature=0.55)
    except ProviderError:
        text, provider = _offline_challenge(question, ctx), "offline"

    # The challenge is the mode most likely to drift into validating, because
    # the user's position is emotionally loaded. Audit it hardest.
    draft = text
    critique, revised, critique_notes = await _self_critique(
        question, text, ctx, provider, audit_challenge=True
    )
    if revised and (
        structure_ok(revised, True) or not structure_ok(draft, True)
    ):
        text = revised
    if provider != "offline" and not structure_ok(text, True):
        repaired = await _repair_structure(
            text, provider, challenge_mode=True, language=ctx.get("language")
        )
        if structure_ok(repaired, True):
            text = repaired
            critique_notes.append(
                "Challenge reformatted to restore labels and sections."
            )

    return {
        "text": text,
        "provider": provider,
        "labels": parse_labels(text),
        "warnings": audit_response(text, challenge_mode=True),
        "patterns": [
            {"name": p["name"], "intervention": p.get("intervention")}
            for p in ctx["patterns"]
        ],
        "intent": ctx["hidden_objective"],
        "rumination": ctx["rumination"],
        "professional_risk": ctx["professional_risk"],
        "memories_used": len(ctx["memories"]),
        "critique": critique_notes,
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
        {"role": "system", "content": _system_with(ctx, DECIDE_INSTRUCTIONS)},
        {"role": "user", "content": user_content},
    ]

    try:
        text, provider = await complete(messages, temperature=0.35)
    except ProviderError:
        text, provider = _offline_answer(question, ctx), "offline"

    draft = text
    critique, revised, critique_notes = await _self_critique(
        question, text, ctx, provider
    )
    if revised and (structure_ok(revised) or not structure_ok(draft)):
        text = revised
    if provider != "offline" and not structure_ok(text):
        repaired = await _repair_structure(
            text, provider, language=ctx.get("language")
        )
        if structure_ok(repaired):
            text = repaired
            critique_notes.append("Answer reformatted to restore Reality Engine labels.")

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
        "critique": critique_notes,
    }


# ------------------------------------------------------- offline fallbacks

def _offline_answer(question: str, ctx: dict[str, Any]) -> str:
    lines = ["[UNKNOWN] No model provider is configured, so this is not an analysis.", ""]
    lines.append(
        "Atif Assistant cannot think right now. Set GROQ_API_KEY (free tier) in "
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


async def respond(
    question: str,
    mode: str = "ask",
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if ctx is None:
        ctx = build_context(question)
    if mode == "challenge":
        return await _challenge(question, ctx)
    if mode == "decide":
        return await _decide(question, ctx)
    return await _ask(question, ctx)