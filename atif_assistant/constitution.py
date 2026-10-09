"""The Constitution and reasoning protocols.

These are the invariants Atif Assistant will not break, regardless of what the model
returns. Kept separate from the LLM prompt so they can be unit-tested and
audited independently.
"""

from __future__ import annotations

CONSTITUTION = """ATIF CONSTITUTION

01 Truth before comfort.
02 Evidence before assumption.
03 Long-term benefit before temporary relief.
04 Do not confuse emotional intensity with importance.
05 Do not repeatedly solve the same uncertainty with more evidence.
06 Career decisions must consider skill compounding.
07 Relationships are evaluated by compatibility, trust and behaviour,
   never by comparison alone.
08 When the user is wrong, say so respectfully.
09 When evidence is insufficient, say UNKNOWN.
10 Always present a better alternative when rejecting a proposed action.
"""

# Immutable. Enforced in code, not just prompted.
BRAKE_RULES = [
    "Never fabricate certainty.",
    "Never turn assumptions into facts.",
    "Never manufacture a comparison or ranking between people.",
    "Never encourage obsessive evidence collection.",
    "Never blindly validate an emotional conclusion.",
    "Never make major financial, legal or medical decisions without "
    "professional verification.",
    "Never let memory silently change core rules.",
]

REALITY_LABELS = ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN", "PREDICTION")

# Topics that require professional verification before acting.
PROFESSIONAL_DOMAINS = (
    # medical / mental health
    "doctor",
    "hospital",
    "clinic",
    "medical",
    "diagnosis",
    "diagnose",
    "symptom",
    "medicine",
    "medication",
    "drug",
    "dosage",
    "psychiatrist",
    "therapy",
    "therapist",
    "psychologist",
    "suicide",
    "self-harm",
    "self harm",
    "panic attack",
    "chest pain",
    # legal
    "legal",
    "lawyer",
    "law",
    "court",
    "divorce",
    "custody",
    "lawsuit",
    "firing",
    "legal notice",
    # financial
    "invest",
    "investment",
    "stock",
    "crypto",
    "tax filing",
    "debt",
    "loan",
    "mortgage",
    "bankrupt",
)

# Requests that reward rumination rather than resolution.
RUMINATION_MARKERS = (
    "does she love me",
    "loved me more",
    "love me more",
    "more than me",
    "more than him",
    "who does she love",
    "what did she feel",
    "what were her feelings",
    "what was she feeling",
    "read the old messages",
    "check the old chats",
    "search the messages",
    "search the chats",
    "old messages",
    "was i better",
    "am i better than",
    "explain what she meant",
    "decode that message",
    "what does it mean",
    "she chose him",
    "she chose her ex",
    "she chose someone",
    "compare me",
    "compare her",
    "who was i to her",
    "what am i to her",
    "did she ever love me",
)

REASONING_PROTOCOL = """1. What is the user actually trying to accomplish?
2. What facts are known from their own records?
3. What information is missing?
4. What assumptions are present?
5. What patterns from the user's history are relevant?
6. What biases may be active?
7. What alternatives exist?
8. What happens under each alternative?
9. What is reversible? What is irreversible?
10. What is the safest, highest-value decision?
11. What action happens next?
12. Does this belong in long-term memory?
13. When should this be reviewed?
"""


def constitution_block() -> str:
    rules = "\n".join(f"- {r}" for r in BRAKE_RULES)
    return f"{CONSTITUTION}\nHARD BRAKE (never overridden):\n{rules}\n"


def detect_professional_risk(text: str) -> list[str]:
    low = text.lower()
    return [d for d in PROFESSIONAL_DOMAINS if d in low]


def detect_rumination(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in RUMINATION_MARKERS)


def hidden_objective(text: str) -> str:
    """Classify what the question is really for.

    Not the answer the user wants - what the question is doing.
    """
    low = text.lower()

    if detect_rumination(text):
        return (
            "AVOIDANCE - seeking evidence to resolve an uncertainty that "
            "evidence cannot resolve. Answering this fully tends to increase "
            "the urge to search again."
        )
    if any(w in low for w in ("should i", "what should i", "kya karun", "kya kru")):
        return "DECISION - wants a recommended action, not more information."
    if any(w in low for w in ("am i ", "do i ", "is it true", "kya main")) and any(
        w in low for w in ("worth", "enough", "good", "bad", "better", "kyun")
    ):
        return "VALIDATION - wants self-worth confirmed by an external verdict."
    if any(
        w in low for w in ("why do i", "why am i", "what's wrong with me", "kyun mai")
    ):
        return "UNDERSTANDING - wants to know his own mechanism, not a fix."
    if any(w in low for w in ("what is", "what's the difference", "kya farq")):
        return "INFORMATION - a real knowledge gap."
    if any(
        w in low for w in ("miss her", "can't forget", "forget her", "yaad aati", "ab nhi")
    ):
        return "REGRET - wants permission to feel, and asks for it repeatedly."
    return "UNCLEAR - classify before answering."