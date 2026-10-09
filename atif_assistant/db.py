"""SQLite storage for Atif Assistant.

One file, no server. Four memory types per the design:
  facts     - stable truths with confidence + verification dates
  episodes  - dated events
  patterns  - recurring behaviour with trigger/intervention
  rules     - constitution rules, user-approved before permanent

Plus: FTS5 index across all memory, a decision ledger with review dates,
and conversation history so memory survives restarts.
"""

from __future__ import annotations

import hashlib
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
    digest     TEXT UNIQUE,
    created_at TEXT NOT NULL
);

-- Question-class ledger. Repetition is the signal the router escalates on.
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY,
    qclass     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Durable facts Atif Assistant learned from conversation, kept separate from seeds so
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

-- Extended tables. All additive: `CREATE TABLE IF NOT EXISTS` never touches an
-- existing database, so these are ignored on the real one until first used.

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    kind TEXT,
    tags TEXT,
    meta TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    title TEXT,
    body TEXT NOT NULL,
    tags TEXT,
    mood TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active',
    data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS social_accounts (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    username TEXT,
    connected INTEGER DEFAULT 0,
    last_sync TEXT,
    data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS social_posts (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    external_id TEXT,
    content TEXT,
    posted_at TEXT,
    data TEXT,
    created_at TEXT NOT NULL
);

-- Location. Raw GPS points land in location_points; nearby points are folded
-- into a named place. A routine is a repeated (place, weekday, hour) visit and
-- is only ever an observed pattern, never a claimed reason.
CREATE TABLE IF NOT EXISTS places (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    radius_m   REAL DEFAULT 150,
    kind       TEXT,
    visits     INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen  TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS location_points (
    id          INTEGER PRIMARY KEY,
    occurred_at TEXT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    accuracy    REAL,
    source      TEXT,
    place_id    INTEGER,
    digest      TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routines (
    id           INTEGER PRIMARY KEY,
    name         TEXT,
    place_id     INTEGER,
    weekday      INTEGER,
    hour_bucket  INTEGER,
    observations INTEGER DEFAULT 0,
    confidence   REAL DEFAULT 0.0,
    status       TEXT DEFAULT 'candidate',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Raw source lines, indexed for retrieval. A stored fact can be traced back to
-- the message it came from instead of only carrying a confidence number.
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    ref_id UNINDEXED,
    speaker UNINDEXED,
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
CREATE INDEX IF NOT EXISTS idx_evidence_at ON evidence(occurred_at);
CREATE INDEX IF NOT EXISTS idx_decisions_review ON decisions(review_date);
CREATE INDEX IF NOT EXISTS idx_questions_class ON questions(qclass);
CREATE INDEX IF NOT EXISTS idx_learned_status ON learned(status);
"""

# Columns introduced after the first schema. (table, column, declaration)
# `_add_missing_columns` applies these to databases created by older versions,
# which is why the evidence table can grow a digest without a new build.
_ADDED_COLUMNS = (
    ("evidence", "digest", "TEXT"),
)


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


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Add columns added after a database was first created.

    `CREATE TABLE IF NOT EXISTS` silently leaves an existing table alone, so a
    new column never reaches a database created by an older version. Without
    this the first query touching a new column fails with "no such column".
    """
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table not created yet
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # SQLite cannot add a UNIQUE constraint to an existing column, so the
    # uniqueness of evidence.digest is enforced by an index instead. Backfill
    # first: rows added before the column existed have no digest, and a unique
    # index allows several NULLs but nothing else to collide on.
    rows = conn.execute(
        "SELECT id, source, occurred_at, speaker, body FROM evidence "
        "WHERE digest IS NULL"
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE evidence SET digest=? WHERE id=?",
            (
                evidence_digest(r["source"], r["occurred_at"], r["speaker"], r["body"]),
                r["id"],
            ),
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_digest ON evidence(digest)"
    )


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
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


def list_rules(limit: int = 200) -> list[dict[str, Any]]:
    """Every stored rule, approved first, newest first."""
    conn = connect()
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM rules ORDER BY approved DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]


def set_rule_approved(rule_id: int, approved: bool) -> bool:
    conn = connect()
    cur = conn.execute(
        "UPDATE rules SET approved=? WHERE id=?", (int(approved), rule_id)
    )
    conn.commit()
    return cur.rowcount > 0


def delete_rule(rule_id: int) -> bool:
    """Remove a rule and its search-index row so nothing cites a gone rule."""
    conn = connect()
    cur = conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    conn.execute("DELETE FROM memory_fts WHERE kind='rule' AND ref_id=?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


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


def open_decisions(limit: int = 50) -> list[dict[str, Any]]:
    """Unresolved decisions, soonest review first, nulls last.

    A decision with no review date is still open but has nothing to prompt for,
    so it sorts after everything that is actually due.
    """
    conn = connect()
    return [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM decisions
               WHERE resolved_at IS NULL
               ORDER BY review_date IS NULL, review_date, id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    ]


def resolve_decision(decision_id: int, actual_outcome: str) -> bool:
    """Close a decision by recording what actually happened.

    Returns False if the decision does not exist or was already resolved, so
    the caller can answer 404 instead of silently pretending it worked. An
    outcome must be recorded: resolving with a blank string would lose the one
    piece of data that makes the ledger worth keeping.
    """
    outcome = (actual_outcome or "").strip()
    if not outcome:
        return False
    conn = connect()
    row = conn.execute(
        "SELECT resolved_at FROM decisions WHERE id=?", (decision_id,)
    ).fetchone()
    if not row or row["resolved_at"]:
        return False
    conn.execute(
        "UPDATE decisions SET actual_outcome=?, resolved_at=? WHERE id=?",
        (outcome, now(), decision_id),
    )
    conn.commit()
    return True


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


COUNTED_TABLES = (
    "facts",
    "episodes",
    "patterns",
    "rules",
    "decisions",
    "messages",
    "evidence",
    "questions",
    "learned",
    "settings",
    "profiles",
    "media",
    "notes",
    "works",
    "social_accounts",
    "social_posts",
    "places",
    "location_points",
    "routines",
)


def counts() -> dict[str, int]:
    conn = connect()
    return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in COUNTED_TABLES}


def content_digest() -> str:
    """Hash of every row in every counted table, order-independent per table.

    `counts()` alone cannot tell "one row deleted, one row added" from "no
    change at all". A test asserting only on counts can pass while rows are
    being rewritten, so anything claiming to protect the real database should
    compare this instead.
    """
    conn = connect()
    digest = hashlib.sha256()
    for table in COUNTED_TABLES:
        digest.update(f"\n##{table}\n".encode())
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        # Sort by the row's own JSON so row order in the table cannot make two
        # identical databases hash differently.
        for raw in sorted(
            json.dumps(dict(r), sort_keys=True, default=str) for r in rows
        ):
            digest.update(raw.encode("utf-8", errors="replace"))
            digest.update(b"\x00")
    return digest.hexdigest()


def evidence_digest(source: str, occurred_at: str | None, speaker: str | None, body: str) -> str:
    """Stable identity for one raw line, used to keep ingestion idempotent.

    Hashes the fields rather than the row id, because the same line exported
    twice has two different ids but must not be stored twice.
    """
    parts = "\x00".join((source or "", occurred_at or "", speaker or "", body or ""))
    return hashlib.sha256(parts.encode("utf-8", errors="replace")).hexdigest()


def add_evidence(
    source: str,
    body: str,
    occurred_at: str | None = None,
    speaker: str | None = None,
) -> int | None:
    """Store one raw source line. Returns None if it is already present.

    Idempotent: re-ingesting an unchanged export adds nothing.
    """
    body = (body or "").strip()
    if not body:
        return None
    digest = evidence_digest(source, occurred_at, speaker, body)
    conn = connect()
    row = conn.execute(
        "SELECT id FROM evidence WHERE digest=?", (digest,)
    ).fetchone()
    if row:
        return None
    cur = conn.execute(
        """INSERT INTO evidence(source, occurred_at, speaker, body, digest, created_at)
           VALUES (?,?,?,?,?,?)""",
        (source, occurred_at, speaker, body, digest, now()),
    )
    conn.commit()
    eid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO evidence_fts(ref_id, speaker, body) VALUES (?,?,?)",
        (eid, speaker or "", body),
    )
    conn.commit()
    return eid


def search_evidence(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Full-text search over raw source lines.

    Same stopword and OR handling as `search_memory`, so a natural question
    returns partial matches instead of nothing.
    """
    conn = connect()
    terms = [
        "".join(ch for ch in w if ch.isalnum())
        for w in query.lower().split()
    ]
    terms = sorted({t for t in terms if len(t) > 2})
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms[:12])
    try:
        rows = conn.execute(
            """SELECT ref_id, speaker,
                      bm25(evidence_fts, 0, 0, 1.0) AS score
               FROM evidence_fts
               WHERE evidence_fts MATCH ?
               ORDER BY score LIMIT ?""",
            (match, limit * 3),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        detail = conn.execute(
            "SELECT * FROM evidence WHERE id=?", (row["ref_id"],)
        ).fetchone()
        if detail:
            d = dict(detail)
            d["score"] = round(float(row["score"]), 4)
            out.append(d)
        if len(out) >= limit:
            break
    return out


def prune_fts_orphans() -> int:
    """Delete FTS rows whose parent row no longer exists. Returns rows removed.

    Memory rows are removed by `source LIKE 'seed:%'` and by approve/reject
    flows. Any deletion done as plain SQL bypasses `_fts_index`, so the search
    index keeps pointing at rows that are gone. Those orphans are worse than
    noise: `search_memory()` happily returns them, so retrieval can cite a
    fact that no longer exists and was never user-approved.
    """
    conn = connect()
    parents = {
        "fact": "facts",
        "episode": "episodes",
        "pattern": "patterns",
        "rule": "rules",
        "learned": "learned",
    }
    removed = 0
    for kind, table in parents.items():
        cur = conn.execute(
            f"""DELETE FROM memory_fts
                 WHERE kind = ?
                   AND ref_id NOT IN (SELECT id FROM {table})""",
            (kind,),
        )
        removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    cur = conn.execute(
        """DELETE FROM evidence_fts
           WHERE ref_id NOT IN (SELECT id FROM evidence)"""
    )
    removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return removed


def is_seeded() -> bool:
    conn = connect()
    return conn.execute("SELECT COUNT(*) c FROM patterns").fetchone()["c"] > 0


def set_setting(key: str, value: str) -> None:
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES (?,?,?)",
        (key, value, now()),
    )
    conn.commit()


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = connect()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    return row["value"]


def delete_setting(key: str) -> None:
    """Remove a setting so it falls back to the environment/default again."""
    conn = connect()
    conn.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.commit()


def add_note(title: str | None, body: str, tags: str | None = None, mood: str | None = None) -> int:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO notes(title, body, tags, mood, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (title, body, tags, mood, now(), now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_notes(limit: int = 20) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM notes ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ location

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two coordinates."""
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def location_digest(
    occurred_at: str | None, lat: float, lon: float, source: str | None
) -> str:
    """Stable identity for one GPS fix, so re-importing a trace adds nothing."""
    # Round the coordinates so a re-export with extra float digits still matches.
    parts = "\x00".join(
        (source or "", occurred_at or "", f"{lat:.5f}", f"{lon:.5f}")
    )
    return hashlib.sha256(parts.encode("utf-8", errors="replace")).hexdigest()


def _parse_when(value: str | None) -> datetime | None:
    """Parse the timestamp formats seen in exports, or return None."""
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M%p",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _nearest_place(conn: sqlite3.Connection, lat: float, lon: float) -> sqlite3.Row | None:
    """Closest existing place within its own radius, else None."""
    best = None
    best_d = None
    for row in conn.execute("SELECT * FROM places").fetchall():
        d = haversine_m(lat, lon, row["lat"], row["lon"])
        if d <= (row["radius_m"] or 150) and (best_d is None or d < best_d):
            best, best_d = row, d
    return best


def add_location_point(
    lat: float,
    lon: float,
    occurred_at: str | None = None,
    accuracy: float | None = None,
    source: str | None = None,
) -> int | None:
    """Store one GPS fix, folding it into a place. None if already present.

    A fix that lands within an existing place's radius is a visit; otherwise it
    starts a new unnamed place at that coordinate. Naming is explicit, never
    guessed from coordinates alone.
    """
    digest = location_digest(occurred_at, lat, lon, source)
    conn = connect()
    if conn.execute("SELECT id FROM location_points WHERE digest=?", (digest,)).fetchone():
        return None

    place = _nearest_place(conn, lat, lon)
    if place is None:
        cur = conn.execute(
            """INSERT INTO places(lat, lon, radius_m, visits, first_seen, last_seen, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (lat, lon, 150, 0, occurred_at, occurred_at, now()),
        )
        place_id = int(cur.lastrowid)
    else:
        place_id = place["id"]

    conn.execute(
        """UPDATE places
           SET visits = visits + 1,
               last_seen = COALESCE(?, last_seen),
               first_seen = COALESCE(first_seen, ?)
           WHERE id = ?""",
        (occurred_at, occurred_at, place_id),
    )
    cur = conn.execute(
        """INSERT INTO location_points(occurred_at, lat, lon, accuracy, source, place_id, digest, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (occurred_at, lat, lon, accuracy, source, place_id, digest, now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def name_place(place_id: int, name: str, kind: str | None = None) -> bool:
    conn = connect()
    cur = conn.execute(
        "UPDATE places SET name=?, kind=COALESCE(?, kind) WHERE id=?",
        (name, kind, place_id),
    )
    conn.commit()
    return cur.rowcount > 0


def list_places(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM places ORDER BY visits DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def list_location_points(limit: int = 100) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM location_points ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def derive_routines(min_observations: int = 3) -> list[dict[str, Any]]:
    """Rebuild routines from stored visits.

    A routine is a place visited at least ``min_observations`` times in the
    same (weekday, 3-hour bucket). Confidence is observations over the number
    of distinct days that bucket could have occurred. Only observed co-visiting
    is recorded - reasons are never inferred here.
    """
    conn = connect()
    points = conn.execute(
        "SELECT occurred_at, place_id FROM location_points WHERE place_id IS NOT NULL"
    ).fetchall()

    buckets: dict[tuple[int, int, int], dict[str, Any]] = {}
    days: dict[tuple[int, int], set[str]] = {}
    for row in points:
        when = _parse_when(row["occurred_at"])
        if when is None:
            continue
        bucket = when.hour // 3
        key = (row["place_id"], when.weekday(), bucket)
        entry = buckets.setdefault(
            key, {"obs": 0, "days": set()}
        )
        entry["obs"] += 1
        entry["days"].add(when.date().isoformat())

    conn.execute("DELETE FROM routines")
    out: list[dict[str, Any]] = []
    for (place_id, weekday, bucket), entry in buckets.items():
        if entry["obs"] < min_observations:
            continue
        # Distinct days on which this bucket could have been seen, from the
        # place's full history - a rough denominator, and labelled as such.
        total_days = conn.execute(
            "SELECT COUNT(DISTINCT substr(occurred_at,1,10)) c FROM location_points WHERE place_id=?",
            (place_id,),
        ).fetchone()["c"] or 1
        confidence = round(min(1.0, len(entry["days"]) / total_days), 3)
        place = conn.execute("SELECT name FROM places WHERE id=?", (place_id,)).fetchone()
        label = (place["name"] if place and place["name"] else f"place {place_id}")
        name = f"{label} around {bucket * 3:02d}:00 on day {weekday}"
        cur = conn.execute(
            """INSERT INTO routines(name, place_id, weekday, hour_bucket, observations, confidence, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, place_id, weekday, bucket, entry["obs"], confidence, "candidate", now(), now()),
        )
        out.append(
            {
                "id": int(cur.lastrowid),
                "name": name,
                "place_id": place_id,
                "weekday": weekday,
                "hour_bucket": bucket,
                "observations": entry["obs"],
                "confidence": confidence,
                "status": "candidate",
            }
        )
    conn.commit()
    return out


def list_routines(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM routines ORDER BY confidence DESC, observations DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- backup

# Tables included in an export. Deliberately excludes raw `messages` (chat
# transcripts) and `evidence` (source lines can be huge and are re-ingestible),
# so a backup carries the curated memory, not the raw firehose.
EXPORT_TABLES = (
    "facts",
    "episodes",
    "patterns",
    "rules",
    "decisions",
    "learned",
    "notes",
    "works",
    "media",
    "places",
    "location_points",
    "routines",
    "settings",
)


def export_data() -> dict[str, Any]:
    """A JSON-serialisable snapshot of the curated memory."""
    conn = connect()
    tables: dict[str, list[dict[str, Any]]] = {}
    for t in EXPORT_TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
        except sqlite3.OperationalError:
            continue
        tables[t] = [dict(r) for r in rows]
    # API keys (settings under `provider.*`) are deliberately excluded: a
    # backup may be shared or stored elsewhere, and a key is not memory.
    if "settings" in tables:
        tables["settings"] = [
            r for r in tables["settings"] if not str(r.get("key", "")).startswith("provider.")
        ]
    return {
        "app": "atif-assistant",
        "version": 1,
        "exported_at": now(),
        "counts": counts(),
        "tables": tables,
    }


def import_data(payload: dict[str, Any]) -> dict[str, int]:
    """Restore a backup, add-only and de-duplicated.

    Never deletes or overwrites an existing row: an import can only add memory
    that is missing. This is the conservative direction - a malformed backup
    cannot destroy the live database.
    """
    tables = payload.get("tables") or {}
    added = {k: 0 for k in EXPORT_TABLES}
    conn = connect()

    seen_facts = {r["text"] for r in conn.execute("SELECT text FROM facts")}
    for f in tables.get("facts", []):
        text = (f.get("text") or "").strip()
        if not text or text in seen_facts:
            continue
        add_fact(
            text,
            source=f.get("source"),
            confidence=f.get("confidence", 0.5),
            evidence=f.get("evidence", 1),
            last_verified=f.get("last_verified"),
        )
        seen_facts.add(text)
        added["facts"] += 1

    seen_eps = {
        (r["title"], r["occurred_at"])
        for r in conn.execute("SELECT title, occurred_at FROM episodes")
    }
    for e in tables.get("episodes", []):
        title = (e.get("title") or "").strip()
        key = (title, e.get("occurred_at"))
        if not title or key in seen_eps:
            continue
        add_episode(
            title=title,
            summary=e.get("summary"),
            occurred_at=e.get("occurred_at"),
            source=e.get("source"),
        )
        seen_eps.add(key)
        added["episodes"] += 1

    seen_patterns = {r["name"] for r in conn.execute("SELECT name FROM patterns")}
    for p in tables.get("patterns", []):
        name = (p.get("name") or "").strip()
        if not name or name in seen_patterns:
            continue
        triggers = p.get("triggers")
        if isinstance(triggers, str):
            try:
                triggers = json.loads(triggers)
            except (ValueError, TypeError):
                triggers = [t.strip() for t in triggers.split(",") if t.strip()]
        add_pattern(
            name=name,
            trigger=p.get("trigger"),
            observed=p.get("observed"),
            frequency=p.get("frequency"),
            function_=p.get("function_"),
            effect=p.get("effect"),
            intervention=p.get("intervention"),
            triggers=triggers,
            source=p.get("source"),
        )
        seen_patterns.add(name)
        added["patterns"] += 1

    seen_rules = {r["text"] for r in conn.execute("SELECT text FROM rules")}
    for r in tables.get("rules", []):
        text = (r.get("text") or "").strip()
        if not text or text in seen_rules:
            continue
        add_rule(
            text,
            code=r.get("code"),
            source=r.get("source"),
            approved=bool(r.get("approved")),
        )
        seen_rules.add(text)
        added["rules"] += 1

    seen_dec = {
        (r["topic"], r["decision"])
        for r in conn.execute("SELECT topic, decision FROM decisions")
    }
    for d in tables.get("decisions", []):
        key = (d.get("topic"), d.get("decision"))
        if key[0] is None or key in seen_dec:
            continue
        add_decision(
            topic=d.get("topic"),
            decided_at=d.get("decided_at"),
            decision=d.get("decision"),
            evidence=d.get("evidence"),
            assumptions=d.get("assumptions"),
            alternatives=d.get("alternatives"),
            prediction=d.get("prediction"),
            confidence=d.get("confidence"),
            expected_outcome=d.get("expected_outcome"),
            review_date=d.get("review_date"),
        )
        seen_dec.add(key)
        added["decisions"] += 1

    seen_learned = {r["text"] for r in conn.execute("SELECT text FROM learned")}
    for l in tables.get("learned", []):
        text = (l.get("text") or "").strip()
        if not text or text in seen_learned:
            continue
        cur = conn.execute(
            """INSERT INTO learned(text, subject, kind, source, confidence,
                                   status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                text,
                l.get("subject"),
                l.get("kind") or "durable",
                l.get("source") or "import",
                l.get("confidence", 0.5),
                l.get("status") or "candidate",
                l.get("created_at") or now(),
            ),
        )
        conn.commit()
        _fts_index("learned", int(cur.lastrowid), text[:80], text)
        conn.commit()
        seen_learned.add(text)
        added["learned"] += 1

    seen_notes = {r["body"] for r in conn.execute("SELECT body FROM notes")}
    for n in tables.get("notes", []):
        body = (n.get("body") or "").strip()
        if not body or body in seen_notes:
            continue
        add_note(n.get("title"), body, n.get("tags"), n.get("mood"))
        seen_notes.add(body)
        added["notes"] += 1

    seen_works = {r["title"] for r in conn.execute("SELECT title FROM works")}
    for w in tables.get("works", []):
        title = (w.get("title") or "").strip()
        if not title or title in seen_works:
            continue
        conn.execute(
            "INSERT INTO works(title, description, status, data, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                title,
                w.get("description"),
                w.get("status", "active"),
                w.get("data"),
                now(),
                now(),
            ),
        )
        conn.commit()
        seen_works.add(title)
        added["works"] += 1

    seen_media = {r["path"] for r in conn.execute("SELECT path FROM media")}
    for m in tables.get("media", []):
        path = (m.get("path") or "").strip()
        if not path or path in seen_media:
            continue
        conn.execute(
            "INSERT INTO media(path, kind, tags, meta, created_at) VALUES (?,?,?,?,?)",
            (
                path,
                m.get("kind"),
                m.get("tags"),
                m.get("meta"),
                m.get("created_at") or now(),
            ),
        )
        conn.commit()
        seen_media.add(path)
        added["media"] += 1

    # Places: reuse an existing place within radius when one is present, else
    # insert the exported place (carrying its own visit counts) so a restoration
    # never double-counts or duplicates a spot. Keeps an old-id -> new-id map for
    # the points and routines that reference it.
    place_map: dict[Any, int] = {}
    for p in tables.get("places", []):
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        existing = _nearest_place(conn, lat, lon)
        if existing is not None:
            if p.get("id") is not None:
                place_map[p["id"]] = int(existing["id"])
            continue
        cur = conn.execute(
            """INSERT INTO places(name, lat, lon, radius_m, kind, visits,
                                  first_seen, last_seen, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                p.get("name"),
                lat,
                lon,
                p.get("radius_m", 150),
                p.get("kind"),
                p.get("visits", 0),
                p.get("first_seen"),
                p.get("last_seen"),
                p.get("created_at") or now(),
            ),
        )
        conn.commit()
        new_id = int(cur.lastrowid)
        if p.get("id") is not None:
            place_map[p["id"]] = new_id
        added["places"] += 1

    seen_points = {
        r["digest"]
        for r in conn.execute("SELECT digest FROM location_points WHERE digest IS NOT NULL")
    }
    for pt in tables.get("location_points", []):
        lat, lon = pt.get("lat"), pt.get("lon")
        if lat is None or lon is None:
            continue
        digest = pt.get("digest") or location_digest(
            pt.get("occurred_at"), lat, lon, pt.get("source")
        )
        if digest in seen_points:
            continue
        place_id = place_map.get(pt.get("place_id"))
        conn.execute(
            """INSERT INTO location_points(occurred_at, lat, lon, accuracy,
                                           source, place_id, digest, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                pt.get("occurred_at"),
                lat,
                lon,
                pt.get("accuracy"),
                pt.get("source"),
                place_id,
                digest,
                pt.get("created_at") or now(),
            ),
        )
        conn.commit()
        seen_points.add(digest)
        added["location_points"] += 1

    seen_routines = {r["name"] for r in conn.execute("SELECT name FROM routines")}
    for rt in tables.get("routines", []):
        name = (rt.get("name") or "").strip()
        if not name or name in seen_routines:
            continue
        place_id = place_map.get(rt.get("place_id"))
        conn.execute(
            """INSERT INTO routines(name, place_id, weekday, hour_bucket,
                                    observations, confidence, status,
                                    created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                name,
                place_id,
                rt.get("weekday"),
                rt.get("hour_bucket"),
                rt.get("observations", 0),
                rt.get("confidence", 0.0),
                rt.get("status") or "candidate",
                rt.get("created_at") or now(),
                rt.get("updated_at") or now(),
            ),
        )
        conn.commit()
        seen_routines.add(name)
        added["routines"] += 1

    # Settings are restored only when the key is absent: an import must never
    # overwrite a live preference (or a cleared provider key set to "").
    for s in tables.get("settings", []):
        key, value = s.get("key"), s.get("value")
        if key is None or value is None:
            continue
        if str(key).startswith("provider."):
            continue
        if get_setting(str(key)) is not None:
            continue
        set_setting(str(key), str(value))
        added["settings"] += 1

    return added
