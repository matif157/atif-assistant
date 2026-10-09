"""Turn a document into a strict, checkable plan.

Used by the "strict plan" flow: the user uploads a document - a training
schedule, a study plan, a budget - and asks the assistant to hold them to it.
The model extracts a short title and a handful of concrete, checkable rules.
Those rules are stored and, when the user asks for strict mode, approved so they
are injected into every later answer as standing commitments.

Fails soft: with no provider, or output that contains nothing actionable, this
returns ``None`` and the caller says so rather than inventing a plan.
"""

from __future__ import annotations

import re
from typing import Any

from .llm import ProviderError, complete

MAX_RULES = 8

PLAN_INSTRUCTIONS = """
You turn a person's document into a strict, checkable plan for that person.

Output EXACTLY this format and nothing else:
TITLE: a short plan name (max 8 words)
RULE: one concrete, checkable commitment drawn from the document
RULE: another
(up to 8 RULE lines)

Every RULE must be:
- concrete and checkable ("run on Tuesday and Friday", "save 500 per month")
- phrased as a commitment the assistant can hold the person to
- grounded ONLY in the document; never invent a goal the text does not contain
- short: one sentence, no numbering, no trailing commentary

If the document contains no actionable commitments, output a TITLE line and no
RULE lines. Output nothing except TITLE and RULE lines.
"""


def parse_plan(raw: str) -> dict[str, Any]:
    """Parse the model's TITLE/RULE output. Tolerant of stray formatting."""
    title = ""
    m = re.search(r"^\s*TITLE:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
    if m:
        title = m.group(1).strip().strip("\"'")[:80]

    rules: list[str] = []
    for rm in re.finditer(r"^\s*RULE:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE):
        rule = rm.group(1).strip()
        rule = re.sub(r"^[\-\*\u2022\d.)\s]+", "", rule).strip()
        if rule and rule not in rules:
            rules.append(rule[:200])
        if len(rules) >= MAX_RULES:
            break
    return {"title": title, "rules": rules}


async def draft_plan(text: str, related_to: str | None = None) -> dict[str, Any] | None:
    """Ask the model for a plan grounded in ``text``. None if it cannot."""
    if not text or not text.strip():
        return None
    prefix = f"RELATED TO: {related_to}\n\n" if related_to else ""
    try:
        raw, provider = await complete(
            [
                {"role": "system", "content": PLAN_INSTRUCTIONS},
                {"role": "user", "content": f"{prefix}DOCUMENT:\n{text[:8000]}"},
            ],
            temperature=0.2,
            max_tokens=600,
        )
    except ProviderError:
        return None
    parsed = parse_plan(raw)
    if not parsed["title"] and not parsed["rules"]:
        return None
    parsed["provider"] = provider
    return parsed
