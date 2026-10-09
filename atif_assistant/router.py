"""The router.

One question in, the right treatment out. The user never picks a mode.

Design principle: the mode is chosen by *what kind of answer is honest* for
this question, not by what the user asked for. A request disguised as
information ("does she love me more?") gets the treatment its real shape
requires - a challenge, not a fact-check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import constitution as C

# Modes
ASK = "ask"
CHALLENGE = "challenge"
DECIDE = "decide"


@dataclass
class Route:
    mode: str
    reason: str
    confidence: float
    escalations: list[str] = field(default_factory=list)
    intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "escalations": self.escalations,
            "intent": self.intent,
        }


# Phrases that signal the user is asking for permission, not information.
_VALIDATION = (
    "am i worth",
    "am i enough",
    "am i good enough",
    "do i matter",
    "do i deserve",
    "am i attractive",
    "am i boring",
    "am i better",
    "was i better",
    "am i loveable",
    "am i lovable",
    "why am i like this",
    "what's wrong with me",
    "is it my fault",
    "kya mai",
    "mera kya",
)

# Genuine two-way choices with consequences.
_DECISION = (
    "should i",
    "what should i",
    "should we",
    "which one",
    "which should",
    "do i take",
    "do i accept",
    "do i quit",
    "do i leave",
    "do i tell",
    "do i go",
    "is it worth",
    "worth it to",
    "kya karun",
    "kya kru",
    "kya karu",
)

# Explaining how something works.
_KNOWLEDGE = (
    "what is",
    "what are",
    "what does",
    "how does",
    "how do i",
    "how to",
    "explain",
    "difference between",
    "why do people",
    "why does",
    "kya hota",
    "farq",
    "kaise",
)

# Social pleasantries and persona questions. These are not requests for an
# analysis; they get one direct labelled line, never chatbot small talk.
_SOCIAL = (
    "how are you",
    "how are u",
    "how you doing",
    "how's it going",
    "how are things",
    "how do you feel",
    "how do u feel",
    "are you happy",
    "are you sad",
    "are you okay",
    "are you ok",
    "do you love me",
    "what's your name",
    "what is your name",
    "who are you",
    "what are you",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "assalam",
    "salam",
    "kaise ho",
    "kya haal",
    "aap kaun",
)

# Bare greetings with nothing else to answer.
_GREETINGS = ("hi", "hey", "hello", "yo", "hola")


# Non-verbal cues: all-caps, repeated punctuation, no question words.
def _is_distressed(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    exclamations = text.count("!") + text.count("?")
    if upper_ratio > 0.6 and len(text) > 30:
        return True
    return exclamations >= 4


def route(text: str, repeat_count: int = 0) -> Route:
    """Choose the honest treatment for this question.

    ``repeat_count`` is how many times this question *class* has been asked
    before. Repetition escalates the treatment - the same question asked five
    times is not answered five times the same way.
    """
    low = text.lower().strip()
    intent = C.hidden_objective(text)
    rumination = C.detect_rumination(text)
    professional = C.detect_professional_risk(text)
    escalations: list[str] = []

    # --- Rule 0: repetition escalation applies to EVERY route.
    # Computed before the early returns, because the questions a person
    # repeats most (comparisons above all) would otherwise never escalate.
    if repeat_count >= 3:
        escalations.append(
            f"This class of question has come up {repeat_count + 1} times. "
            "Stop re-answering it. Name the loop and address it directly."
        )
    elif repeat_count == 2:
        escalations.append(
            "Third time asking this. Note the repetition and answer at a "
            "higher level than last time."
        )

    # --- Rule 1: professional domains always go to a careful, signposted ask.
    # Never answered with confident advice, whatever else is true.
    if professional:
        return Route(
            mode=ASK,
            reason=f"Professional domain: {', '.join(professional[:3])}",
            confidence=0.95,
            escalations=[
                "Point to a qualified professional before advising.",
                *escalations,
            ],
            intent=intent,
        )

    # --- Rule 2: comparison / ranking requests cannot be answered as asked.
    # The premise is unmeasurable, so the honest mode is a challenge.
    if rumination:
        return Route(
            mode=CHALLENGE,
            reason="Comparison between people's feelings is not measurable; "
            "answering it as a fact would invent certainty.",
            confidence=0.92,
            escalations=[
                "Do NOT search old messages or collect more evidence.",
                "State plainly that no evidence supports the comparison.",
                "Redirect to the decision the user actually faces.",
                *escalations,
            ],
            intent=intent,
        )

    # --- Rule 3: self-worth questions get challenged, not confirmed.
    if any(p in low for p in _VALIDATION):
        return Route(
            mode=CHALLENGE,
            reason="Question asks for a verdict on self-worth, which no "
            "external observer can supply.",
            confidence=0.88,
            escalations=[
                "Do not supply the verdict being requested.",
                "Answer the underlying need instead.",
                *escalations,
            ],
            intent=intent,
        )

    # --- Rule 4: real decisions with consequences.
    if any(p in low for p in _DECISION):
        return Route(
            mode=DECIDE,
            reason="Concrete decision with stated consequences.",
            confidence=0.85,
            escalations=["Include reversibility and a review date."],
            intent=intent,
        )

    # --- Rule 5: social pleasantries and persona questions. Checked before the
    # repetition rule and before generic knowledge, so a greeting that recurs, or
    # a persona question like "what is your name" / "what are you", is still
    # answered as a person-to-person line rather than escalated into an analysis
    # or mistaken for an encyclopaedia lookup.
    stripped = low.strip(" .!?")
    if any(p in low for p in _SOCIAL) or stripped in _GREETINGS:
        return Route(
            mode=ASK,
            reason="Social or persona question; answered directly, without "
            "small talk or a reciprocal question.",
            confidence=0.7,
            escalations=[
                "One direct line. No 'I'm good, what about you?' and no "
                "pretend feelings.",
                *escalations,
            ],
            intent=intent,
        )

    # --- Rule 6: repetition is itself the signal. Once a class of question
    # has been asked enough times, the mode stops mattering and the loop
    # becomes the subject.
    if repeat_count >= 3:
        return Route(
            mode=CHALLENGE,
            reason=f"Repeated question ({repeat_count + 1}x) - repetition is "
            "the signal, not the question.",
            confidence=0.8,
            escalations=escalations,
            intent=intent,
        )

    # --- Rule 7: distress signal overrides everything.
    if _is_distressed(text):
        escalations.append(
            "High-arousal phrasing. Be brief, calm and concrete. Do not "
            "analyse, do not list options."
        )
        return Route(
            mode=ASK,
            reason="Distress signal detected; brevity over analysis.",
            confidence=0.75,
            escalations=escalations,
            intent=intent,
        )

    # --- Rule 8: genuine knowledge question.
    if any(p in low for p in _KNOWLEDGE):
        return Route(
            mode=ASK,
            reason="Knowledge question with a checkable answer.",
            confidence=0.8,
            escalations=escalations,
            intent=intent,
        )

    # --- Default: challenge, because unclassified asks are rarely neutral.
    return Route(
        mode=CHALLENGE,
        reason="Unclassified request; defaulting to the honest treatment "
        "rather than the agreeable one.",
        confidence=0.5,
        escalations=escalations,
        intent=intent,
    )


def question_class(text: str) -> str:
    """Stable key for counting how often a *kind* of question recurs."""
    low = text.lower()
    if C.detect_rumination(text):
        return "comparison"
    if any(p in low for p in _VALIDATION):
        return "self_worth"
    if any(p in low for p in _DECISION):
        return "decision"
    if any(p in low for p in _SOCIAL) or low.strip(" .!?") in _GREETINGS:
        return "social"
    if any(p in low for p in _KNOWLEDGE):
        return "knowledge"
    return "other"