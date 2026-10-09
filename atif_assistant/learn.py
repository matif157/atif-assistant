"""Memory learning.

After an answer, Atif Assistant reads its own exchange and pulls out what is durable.

Three gates, all of which must pass before anything is stored:

1. The model must propose it in strict format.
2. It must be about the user, not about the conversation.
3. It must not already exist in memory.

Anything stored lands as a *candidate*. It is never promoted to a curated
fact, and never becomes a rule, without explicit approval. Constitution
principle 06: memory may not silently change rules.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import db
from .llm import ProviderError, complete

EXTRACT_INSTRUCTIONS = """
You are extracting durable facts from a conversation, for a personal memory system.

Output STRICTLY, one per line, nothing else:
FACT | <subject> | <statement>

Rules:
- Only statements about the USER that will still be true in a month.
- First-person pronoun in the subject: "my sleep", "my job", "my ex".
- Never store: feelings, opinions, questions, opinions about other people,
  anything about this AI, anything that restates the conversation, anything
  already obvious from the question itself.
- Never store a clinical or diagnostic claim.
- If there is nothing durable, output EMPTY and nothing else.
- Maximum 3 lines.
"""

_FACT_LINE = re.compile(r"^\s*FACT\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", re.IGNORECASE)
_EMPTY = re.compile(r"^\s*(EMPTY|NONE)\s*$", re.IGNORECASE)

# Guardrails on what may be stored at all.
_DURABLE_HINT = re.compile(
    r"\b(started|joined|works?|working|lives?|living|moved|finished|"
    r"quit|married|engaged|birthday|born|studies|studying|degree|"
    r"diagnosed|scheduled|deadline|since|from|"
    r"bought|sold|switched|changed|relocated|registered|adopted)\b",
    re.IGNORECASE,
)

# Things that must never become durable memory.
_REJECT = re.compile(
    r"\b(feel|feels|felt|feeling|think|thought|want|wants|believe|"
    r"love|hate|miss|wish|hope|afraid|scared|sad|angry|"
    r"bipolar|schizo|depress|anxiety disorder|diagnos(is|ed) with)\b",
    re.IGNORECASE,
)


def _is_durable(subject: str, statement: str) -> bool:
    if not subject.lower().startswith(("my", "our", "i ")):
        return False
    if _REJECT.search(statement):
        return False
    return bool(_DURABLE_HINT.search(statement))


def _already_known(statement: str) -> bool:
    words = [w for w in re.findall(r"[a-z]{4,}", statement.lower())]
    if not words:
        return True
    probe = " ".join(words[:4])
    try:
        return bool(db.search_memory(probe, limit=1))
    except sqlite3.Error:  # pragma: no cover - defensive
        return True


async def extract(
    question: str,
    answer: str,
    provider: str,
    max_new: int = 3,
) -> list[dict[str, Any]]:
    """Propose durable facts from one exchange. Fails soft, always."""
    if provider == "offline" or not question.strip():
        return []

    try:
        raw, _ = await complete(
            [
                {"role": "system", "content": EXTRACT_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": (
                        f"USER QUESTION: {question[:600]}\n\n"
                        f"RAees ANSWER: {answer[:900]}"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=320,
        )
    except ProviderError:
        return []

    stored: list[dict[str, Any]] = []
    for line in raw.splitlines()[: max_new * 3]:
        if _EMPTY.match(line):
            continue
        m = _FACT_LINE.match(line)
        if not m:
            continue
        subject, statement = m.group(1), m.group(2)
        if not _is_durable(subject, statement):
            continue
        if _already_known(statement):
            continue
        fid = db.add_learned(
            text=f"{subject}: {statement}",
            kind="durable",
            source=f"conversation:{db.now()}",
            subject=subject.lower(),
            confidence=0.5,
        )
        stored.append(
            {"id": fid, "subject": subject, "statement": statement}
        )
        if len(stored) >= max_new:
            break
    return stored