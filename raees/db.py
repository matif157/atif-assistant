"""SQLite storage for Raees.

One file, no server. Four memory types per the design:
  facts     - stable truths with confidence + verification dates
  episodes  - dated events
  patterns  - recurring behaviour with trigger/intervention
  rules     - constitution rules, user-approved before permanent

Plus: FTS5 index across all memory, a decision ledger with review dates,
and conversation history so memory survives restarts.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH

_local = threading.local()

# Snapshot of the configured database path, so tests can switch to a scratch
# file and restore the real one afterwards.
_REAL_DB_PATH = DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    source        TEXT,
    confidence    REAL DEFAULT 0.5,
    evidence      INTEGER DEFAULT 1,
    last_verified TEXT,
    status        TEXT DEFAULT 'active',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY,
    occurred_at TEXT,
    title       TEXT NOT NULL,
    summary     TEXT,
    source      TEXT,
    people      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patterns (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    trigger      TEXT,
    observed     TEXT,
    frequency    TEXT,
    function_    TEXT,
    effect       TEXT,
    intervention TEXT,
    triggers     TEXT,
    source       TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY,
    code        TEXT,
    text        TEXT NOT NULL,
    source      TEXT,
    approved    INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id               INTEGER PRIMARY KEY,
    topic            TEXT,
    decided_at       TEXT,
    decision         TEXT,
    evidence         TEXT,
    assumptions      TEXT,
    alternatives     TEXT,
    prediction       TEXT,
    confidence       REAL,
    expected_outcome TEXT,
    review_date      TEXT,
    actual_outcome   TEXT,
    resolved_at      TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    session    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    labels     TEXT,
    patterns   TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id         INTEGER PRIMARY KEY,
    source     TEXT NOT NULL,
    occurred_at TEXT,
    speaker    TEXT,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Question-class ledger. Repetition is the signal the router escalates on.
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY,
    qclass     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Durable facts Raees learned from conversation, kept separate from seeds so
-- a mistake is easy to delete without touching curated memory.
CREATE TABLE IF NOT EXISTS learned (
    id         INTEGER PRIMARY KEY,
    text       TEXT NOT NULL,
    subject    TEXT,
    kind       TEXT NOT NULL,
    source     TEXT NOT NULL,
    confidence REAL NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    kind UNINDEXED,
    ref_id UNINDEXED,
    title,
    body,
    tokenize = 'porter unicode61'
);

-- Contradiction candidates: same subject, different asserted value.
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    fact_id UNINDEXED,
    subject,
    value,
    tokenize = 'porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source);
CREATE INDEX IF NOT EXISTS idx_decisions_review ON decisions(review_date);
CREATE INDEX IF NOT EXISTS idx_questions_class ON questions(qclass);
CREATE INDEX IF NOT EXISTS idx_learned_status ON learned(status);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
        except sqlite3.Error:
            conn = None
        else:
            if str(getattr(_local, "path", "")) == str(DB_PATH):
                return conn
            conn.close()
            conn = None

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _local.conn = conn
    _local.path = str(DB_PATH)
    return conn


def use_test_db(path: Path) -> None:
    """Point the module at a scratch database.

    Tests must never write to the real one. Every public entry point reads
    ``DB_PATH`` at call time via ``connect()``, so overriding the module
    attribute is enough.
    """
    global DB_PATH
    DB_PATH = Path(path)
    if getattr(_local, "conn", None) is not None:
        _local.conn.close()
    _local.conn = None
    _local.path = ""


def reset_db_path() -> None:
    """Restore the configured (production) database path."""
    global DB_PATH
    DB_PATH = _REAL_DB_PATH
    if getattr(_local, "conn", None) is not None:
        _local.conn.close()
    _local.conn = None
    _local.path = ""


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()


def _fts_index(kind: str, ref_id: int, title: str, body: str) -> None:
    conn = connect()
    conn.execute(
        "DELETE FROM memory_fts WHERE kind=? AND ref_id=?", (kind, ref_id)
    )
    conn.execute(
        "INSERT INTO memory_fts(kind, ref_id, title, body) VALUES (?,?,?,?)",
        (kind, ref_id, title, body),
    )


def search_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Full-text search across every memory kind.

    Uses OR semantics so multi-word queries return partial matches ranked by
    relevance, rather than requiring every term to be present (FTS5's default
    AND behaviour makes most natural-language queries return nothing).
    """
    conn = connect()

    # Keep meaningful words, drop stopwords.
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "was", "were",
        "are", "his", "her", "him", "she", "you", "your", "have", "has",
        "not", "but", "what", "when", "why", "how", "did", "does", "can",
        "should", "would", "about", "into", "than", "then", "there",
        "their", "them", "they", "will", "been", "being", "also", "just",
    }
    words = [
        "".join(ch for ch in w if ch.isalnum())
        for w in query.lower().split()
    ]
    words = [w for w in words if len(w) > 2 and w not in stop]
    if not words:
        return []

    # Deduplicate while preserving order, longest terms first (more specific).
    seen: set[str] = set()
    terms = sorted(
        (w for w in words if not (w in seen or seen.add(w))),
        key=len,
        reverse=True,
    )
    match = " OR ".join(f'"{t}"' for t in terms[:12])

    try:
        rows = conn.execute(
            """
            SELECT kind, ref_id, title, body, bm25(memory_fts, 0, 0, 1.0, 1.0) AS score
            FROM memory_fts
            WHERE memory_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match, limit * 5),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        detail = _load_detail(row["kind"], row["ref_id"])
        if detail:
            detail["score"] = round(float(row["score"]), 4)
            detail["kind"] = row["kind"]
            out.append(detail)
        if len(out) >= limit:
            break
    return out


def _load_detail(kind: str, ref_id: int) -> dict[str, Any] | None:
    conn = connect()
    table = {
        "fact": "facts",
        "episode": "episodes",
        "pattern": "patterns",
        "rule": "rules",
        "learned": "learned",
    }.get(kind)
    if not table:
        return None
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (ref_id,)).fetchone()
    return dict(row) if row else None


def add_fact(
    text: str,
    source: str | None = None,
    confidence: float = 0.5,
    evidence: int = 1,
    last_verified: str | None = None,
) -> int:
    conn = connect()
    ts = now()
    cur = conn.execute(
        """INSERT INTO facts(text, source, confidence, evidence,
                             last_verified, status, created_at, updated_at)
           VALUES (?,?,?,?,?,'active',?,?)""",
        (text, source, confidence, evidence, last_verified, ts, ts),
    )
    conn.commit()
    _fts_index("fact", cur.lastrowid, text[:80], text)
    conn.commit()
    _index_claim(int(cur.lastrowid), text)
    return int(cur.lastrowid)


# ------------------------------------------- contradictions & learned facts

# Negations that flip a claim's meaning. Used to spot a fact and its denial.
_NEGATION = re.compile(
    r"\b(not|never|no|none|didn'?t|doesn'?t|did not|does not|wasn'?t|"
    r"was not|isn'?t|is not|can'?t|cannot|won'?t)\b",
    re.IGNORECASE,
)

_SUBJECT_RE = re.compile(
    r"\b(?:my|our)\s+([a-z][a-z ]{2,30}?)\s+(?:is|are|was|were|has|have|"
    r"does|do|did|feels?|think(?:s)?|said|says|wants?|likes?|loves?)\b",
    re.IGNORECASE,
)


def _index_claim(fact_id: int, text: str) -> None:
    """Record subject/value pairs so contradictions can be detected later."""
    conn = connect()
    m = _SUBJECT_RE.search(text)
    if not m:
        return
    subject = " ".join(m.group(1).lower().split())
    value = text[m.end() :].strip().lower()[:200]
    if not value:
        return
    conn.execute("DELETE FROM claims_fts WHERE fact_id=?", (fact_id,))
    conn.execute(
        "INSERT INTO claims_fts(fact_id, subject, value) VALUES (?,?,?)",
        (fact_id, subject, value),
    )
    conn.commit()


def find_contradictions(limit: int = 5) -> list[dict[str, Any]]:
    """Facts about the same subject whose values cannot both be true.

    Deliberately conservative: only same-subject pairs where one value is a
    negation of the other. Returns candidates for review, not verdicts.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT fact_id, subject, value FROM claims_fts"
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    by_subject: dict[str, list[tuple[int, str]]] = {}
    for r in rows:
        by_subject.setdefault(r["subject"], []).append((r["fact_id"], r["value"]))

    out: list[dict[str, Any]] = []
    for subject, claims in by_subject.items():
        if len(claims) < 2:
            continue
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                fa, va = claims[i]
                fb, vb = claims[j]
                if bool(_NEGATION.search(va)) != bool(_NEGATION.search(vb)):
                    texts = {}
                    for fid in (fa, fb):
                        row = conn.execute(
                            "SELECT text FROM facts WHERE id=?", (fid,)
                        ).fetchone()
                        if row:
                            texts[fid] = row["text"]
                    out.append(
                        {
                            "subject": subject,
                            "a": texts.get(fa),
                            "b": texts.get(fb),
                        }
                    )
    return out[:limit]


def record_question(qclass: str, body: str) -> int:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO questions(qclass, body, created_at) VALUES (?,?,?)",
        (qclass, body[:500], now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def question_count(qclass: str | None = None) -> int:
    conn = connect()
    if qclass:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM questions WHERE qclass=?", (qclass,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()
    return int(row["n"]) if row else 0


def question_distribution() -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        """SELECT qclass, COUNT(*) AS n FROM questions
           GROUP BY qclass ORDER BY n DESC"""
    ).fetchall()
    return [{"class": r["qclass"], "count": int(r["n"])} for r in rows]


def add_learned(
    text: str,
    kind: str,
    source: str,
    subject: str | None = None,
    confidence: float = 0.6,
) -> int:
    """Store a fact learned from conversation. Never auto-promoted to a rule."""
    conn = connect()
    ts = now()
    cur = conn.execute(
        """INSERT INTO learned(text, subject, kind, source, confidence,
                              status, created_at)
           VALUES (?,?,?,?,?,'candidate',?)""",
        (text, subject, kind, source, confidence, ts),
    )
    conn.commit()
    _fts_index("learned", int(cur.lastrowid), text[:80], text)
    conn.commit()
    return int(cur.lastrowid)


def learned_candidates() -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM learned WHERE status='candidate'
           ORDER BY created_at DESC LIMIT 50"""
    ).fetchall()
    return [dict(r) for r in rows]


def approve_learned(fact_id: int) -> int:
    """Promote a learned candidate into a curated fact."""
    conn = connect()
    row = conn.execute(
        "SELECT text, subject, confidence FROM learned WHERE id=?", (fact_id,)
    ).fetchone()
    if not row:
        return 0
    fid = add_fact(
        text=row["text"],
        source=f"learned:{fact_id}",
        confidence=row["confidence"],
    )
    conn.execute(
        "UPDATE learned SET status='approved' WHERE id=?", (fact_id,)
    )
    conn.commit()
    return fid


def reject_learned(fact_id: int) -> None:
    conn = connect()
    conn.execute("UPDATE learned SET status='rejected' WHERE id=?", (fact_id,))
    conn.execute("DELETE FROM memory_fts WHERE kind='learned' AND ref_id=?", (fact_id,))
    conn.commit()


def add_episode(
    title: str,
    summary: str | None = None,
    occurred_at: str | None = None,
    source: str | None = None,
    people: Iterable[str] | None = None,
) -> int:
    conn = connect()
    cur = conn.execute(
        """INSERT INTO episodes(occurred_at, title, summary, source,
                                people, created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            occurred_at,
            title,
            summary,
            source,
            json.dumps(list(people or [])),
            now(),
        ),
    )
    conn.commit()
    _fts_index(
        "episode", cur.lastrowid, title[:80], f"{title} {summary or ''}"
    )
    conn.commit()
    return int(cur.lastrowid)


def add_pattern(
    name: str,
    trigger: str | None = None,
    observed: str | None = None,
    frequency: str | None = None,
    function_: str | None = None,
    effect: str | None = None,
    intervention: str | None = None,
    triggers: Iterable[str] | None = None,
    source: str | None = None,
) -> int:
    conn = connect()
    cur = conn.execute(
        """INSERT INTO patterns(name, trigger, observed, frequency, function_,
                                effect, intervention, triggers, source, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            trigger,
            observed,
            frequency,
            function_,
            effect,
            intervention,
            json.dumps(list(triggers or [])),
            source,
            now(),
        ),
    )
    conn.commit()
    _fts_index(
        "pattern", cur.lastrowid, name[:80], " ".join(filter(None, [trigger, observed, effect]))
    )
    conn.commit()
    return int(cur.lastrowid)


def add_rule(
    text: str,
    code: str | None = None,
    source: str | None = None,
    approved: bool = False,
) -> int:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO rules(code, text, source, approved, created_at) VALUES (?,?,?,?,?)",
        (code, text, source, int(approved), now()),
    )
    conn.commit()
    _fts_index("rule", cur.lastrowid, code or "rule", text)
    conn.commit()
    return int(cur.lastrowid)


def all_patterns() -> list[dict[str, Any]]:
    conn = connect()
    return [dict(r) for r in conn.execute("SELECT * FROM patterns").fetchall()]


def approved_rules() -> list[dict[str, Any]]:
    conn = connect()
    return [
        dict(r)
        for r in conn.execute("SELECT * FROM rules WHERE approved=1").fetchall()
    ]


def add_decision(**kw: Any) -> int:
    conn = connect()
    cols = (
        "topic",
        "decided_at",
        "decision",
        "evidence",
        "assumptions",
        "alternatives",
        "prediction",
        "confidence",
        "expected_outcome",
        "review_date",
    )
    values = [kw.get(c) for c in cols]
    cur = conn.execute(
        f"INSERT INTO decisions({','.join(cols)}, created_at) "
        f"VALUES ({','.join('?' * len(cols))},?)",
        [*values, now()],
    )
    conn.commit()
    return int(cur.lastrowid)


def due_decisions() -> list[dict[str, Any]]:
    conn = connect()
    today = datetime.now(timezone.utc).date().isoformat()
    return [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM decisions
               WHERE resolved_at IS NULL AND review_date IS NOT NULL
                 AND review_date <= ?
               ORDER BY review_date""",
            (today,),
        ).fetchall()
    ]


def save_message(
    session: str,
    role: str,
    content: str,
    labels: Any = None,
    patterns: Any = None,
) -> None:
    conn = connect()
    conn.execute(
        """INSERT INTO messages(session, role, content, labels, patterns, created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            session,
            role,
            content,
            json.dumps(labels) if labels is not None else None,
            json.dumps(patterns) if patterns is not None else None,
            now(),
        ),
    )
    conn.commit()


def history(session: str, limit: int = 12) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        """SELECT role, content, created_at FROM messages
           WHERE session=? ORDER BY id DESC LIMIT ?""",
        (session, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def counts() -> dict[str, int]:
    conn = connect()
    tables = (
        "facts",
        "episodes",
        "patterns",
        "rules",
        "decisions",
        "messages",
        "evidence",
        "questions",
        "learned",
    )
    return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tables}


def is_seeded() -> bool:
    conn = connect()
    return conn.execute("SELECT COUNT(*) c FROM patterns").fetchone()["c"] > 0