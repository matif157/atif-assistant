"""Seed Raees memory from the existing archive repo.

Reads CONTEXT.md, TIMELINE.md, PATTERN.md, AGENTS.md, ASK-LATER.md and
converts them into structured memory rows. Idempotent: re-running replaces
seeded rows rather than duplicating them.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raees import db  # noqa: E402
from raees.config import ARCHIVE_DIR  # noqa: E402

# Patterns are the highest-value memory, so they're curated explicitly rather
# than blindly parsed. Triggers are the keywords the Pattern Radar matches on.
CURATED_PATTERNS = [
    {
        "name": "Uncertainty seeking loop",
        "trigger": "Uncertainty about another person's feelings",
        "observed": (
            "Searches old messages, compares with another person, requests "
            "certainty, receives an answer, develops a new doubt, searches again."
        ),
        "frequency": "High",
        "function_": "Reduce uncertainty temporarily",
        "effect": "Increases rumination and blocks action",
        "intervention": (
            "Stop evidence collection after a threshold. Switch from 'what did "
            "they feel' to 'what decision should I make'."
        ),
        "triggers": [
            "does she love me",
            "loved me more",
            "compare",
            "compare her",
            "old messages",
            "what did she feel",
            "read chats",
            "who does she love",
            "ex",
        ],
    },
    {
        "name": "Validation outsourcing",
        "trigger": "Self-worth questions directed at a partner",
        "observed": (
            "Asks 'am I worth it', 'am I better', 'do you love me' and waits "
            "for an external verdict before deciding anything."
        ),
        "frequency": "High",
        "function_": "Borrow self-worth from someone else",
        "effect": "Mood becomes hostage to another person's availability",
        "intervention": (
            "Answer the underlying question (what does the user actually want?) "
            "rather than the verdict being requested."
        ),
        "triggers": [
            "am i worth",
            "am i enough",
            "worth it",
            "do you love me",
            "am i better",
            "do i matter",
            "am i attractive",
            "am i boring",
        ],
    },
    {
        "name": "Early full disclosure",
        "trigger": "Attachment forming quickly",
        "observed": (
            "Discloses complete childhood trauma within weeks of contact, before "
            "any mutual commitment, to obtain care."
        ),
        "frequency": "High",
        "function_": "Secure attachment early",
        "effect": "Creates asymmetry and leaves the user exposed",
        "intervention": (
            "Keep trauma disclosure for the therapist and established, "
            "reciprocal relationships. Not as a bid for attention."
        ),
        "triggers": [
            "madrassa",
            "childhood",
            "trauma",
            "i told her everything",
            "opened up",
            "shared everything",
        ],
    },
    {
        "name": "Score and rank seeking",
        "trigger": "Requests for numerical or ranked evaluation",
        "observed": (
            "Asks for pros and cons, scores, rankings, percentages - then argues "
            "with any answer received."
        ),
        "frequency": "High",
        "function_": "Obtain certainty through external scoring",
        "effect": "No score is ever sufficient; dissatisfaction repeats",
        "intervention": (
            "Refuse to manufacture a number. Redirect to behaviours that are "
            "actually observable and controllable."
        ),
        "triggers": [
            "pros and cons",
            "score",
            "rate me",
            "percentage",
            "rank",
            "how much do you",
            "10 out of 10",
        ],
    },
    {
        "name": "Unavailable partner selection",
        "trigger": "Selecting a partner who is unavailable",
        "observed": (
            "Attaches to partners who are already taken, blocked, engaged or "
            "hot-and-cold."
        ),
        "frequency": "Recurring",
        "function_": "Replicate an early unreliable-attachment template",
        "effect": "Guarantees unavailability",
        "intervention": (
            "Treat availability as a precondition, not a preference. "
            "Intermittent reinforcement is the strongest known bonding mechanism."
        ),
        "triggers": [
            "she is engaged",
            "her ex",
            "she blocked",
            "she chose",
            "another guy",
            "waiting for her",
        ],
    },
    {
        "name": "Late-night contact",
        "trigger": "Contact outside 22:00-07:00",
        "observed": "Most intense messages occur between midnight and 04:00.",
        "frequency": "High",
        "function_": "Shorten the gap between distress and reassurance",
        "effect": "Deepens attachment and worsens sleep",
        "intervention": "Hard cutoff at 22:00. Delay any urge to message by one hour.",
        "triggers": ["cant sleep", "awake at", "3am", "4am", "tonight"],
    },
]


def _read(name: str) -> str | None:
    p = ARCHIVE_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def _bullets(text: str, min_len: int = 25) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            body = line[2:].strip()
            if len(body) >= min_len and not body.startswith("|"):
                out.append(body)
    return out


def _headings(text: str) -> list[str]:
    return [
        m.group(2).strip()
        for m in re.finditer(r"^(#{2,3})\s+(.+)$", text, re.M)
        if len(m.group(2).strip()) > 3
    ]


DATE_RE = re.compile(
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"[\s,]*(?:\d{4})?)",
    re.IGNORECASE,
)


def seed(archive_dir: Path | None = None) -> dict[str, int]:
    db.init_db()
    conn = db.connect()

    # Idempotency: clear only previously seeded rows.
    for table in ("facts", "episodes", "patterns"):
        conn.execute(f"DELETE FROM {table} WHERE source LIKE 'seed:%'")
    conn.execute("DELETE FROM rules WHERE source LIKE 'seed:%'")
    conn.commit()

    # Those deletes are plain SQL, so they bypass _fts_index and leave the
    # search index pointing at rows that are gone. Re-seeding used to leave a
    # trail of orphans that retrieval would happily return. Prune them before
    # adding anything back, otherwise the same content gets indexed twice.
    db.prune_fts_orphans()

    added = {"facts": 0, "episodes": 0, "patterns": 0, "rules": 0}

    # --- patterns (curated) ---
    for p in CURATED_PATTERNS:
        db.add_pattern(
            name=p["name"],
            trigger=p["trigger"],
            observed=p["observed"],
            frequency=p["frequency"],
            function_=p["function_"],
            effect=p["effect"],
            intervention=p["intervention"],
            triggers=p["triggers"],
            source="seed:curated",
        )
        added["patterns"] += 1

    # --- facts from CONTEXT.md ---
    ctx = _read("CONTEXT.md")
    if ctx:
        section = ""
        for line in ctx.splitlines():
            h = re.match(r"^#{2,3}\s+(.+)$", line.strip())
            if h:
                section = h.group(1).strip()
                continue
            s = line.strip()
            if s.startswith(("- ", "* ")) and len(s) > 30:
                body = s[2:].strip()
                conf = 0.75 if section else 0.6
                db.add_fact(
                    body,
                    source=f"seed:CONTEXT.md#{section}",
                    confidence=conf,
                    evidence=2,
                    last_verified="2026-10-06",
                )
                added["facts"] += 1

    # --- episodes from TIMELINE.md ---
    # TIMELINE.md is organised by thread (## headings) with dated events
    # inline in prose. Extract each thread as an episode, then split out any
    # explicit date mentions inside it as dated sub-episodes.
    tl = _read("TIMELINE.md")
    if tl:
        threads = [
            m for m in re.finditer(
                r"^##\s+(.+?)$(.*?)(?=^##\s+|\Z)", tl, re.M | re.S
            )
            if m.group(1).strip().lower()
            not in {"timeline", "scale", "self-harm content"}
        ]
        for m in threads:
            heading = m.group(1).strip()
            body = m.group(2)
            first_para = next(
                (
                    p.strip()
                    for p in body.split("\n\n")
                    if len(p.strip()) > 80 and not p.strip().startswith(("**", "#"))
                ),
                "",
            )
            people = re.findall(r"\b([A-Z][a-z]{2,12})\b", heading)
            dm = DATE_RE.search(heading)
            db.add_episode(
                title=heading,
                summary=first_para[:800],
                occurred_at=dm.group(1) if dm else None,
                source="seed:TIMELINE.md",
                people=people,
            )
            added["episodes"] += 1

            # Dated facts inside the thread become their own episodes.
            for para in body.split("\n\n"):
                para = para.strip()
                if len(para) < 60 or para.startswith("#"):
                    continue
                pdates = DATE_RE.findall(para)
                if not pdates:
                    continue
                clean = re.sub(r"[*_`]", "", para)
                snippet = clean[:400]
                db.add_episode(
                    title=f"{heading.split(',')[0].strip()} — {pdates[0].strip()}",
                    summary=snippet,
                    occurred_at=pdates[0].strip(),
                    source="seed:TIMELINE.md#dated",
                    people=re.findall(r"\b([A-Z][a-z]{2,12})\b", para)[:6],
                )
                added["episodes"] += 1

    # --- rules from AGENTS.md + ASK-LATER.md ---
    ag = _read("AGENTS.md")
    if ag:
        for b in _bullets(ag, 25):
            db.add_rule(b, source="seed:AGENTS.md", approved=True)
            added["rules"] += 1
    al = _read("ASK-LATER.md")
    if al:
        for h in _headings(al):
            if not h.lower().startswith(("ask", "later", "open")):
                db.add_rule(f"Open question: {h}", source="seed:ASK-LATER.md")
                added["rules"] += 1

    return added


if __name__ == "__main__":
    if not ARCHIVE_DIR.exists():
        print(f"archive not found at {ARCHIVE_DIR}")
        raise SystemExit(1)
    result = seed()
    print("seeded:", json.dumps(result))
    print("counts:", json.dumps(db.counts()))