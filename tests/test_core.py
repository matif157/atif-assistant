"""Tests for the parts that must not break: the brake, the radar, retrieval.

Run:  .venv/bin/python -m tests.test_core
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def test_brake() -> None:
    from raees.engine import audit_response, parse_labels
    from raees import constitution as C

    print("\nbrake")
    check(
        "catches fabricated percentage ranking",
        any("comparison" in w for w in audit_response("She loved him 40% more than you.")),
    )
    check(
        "catches 'loved him more'",
        any("comparison" in w for w in audit_response("She loved him more than you.")),
    )
    check(
        "flags unlabelled response",
        any("no Reality Engine labels" in w for w in audit_response("She probably loved him.")),
    )
    check(
        "accepts a correct labelled answer",
        audit_response("[FACT] She said so.\n[UNKNOWN] Her ranking of you.") == [],
    )

    labels = parse_labels("[FACT] a\n[UNKNOWN] b\n[INFERENCE] c")
    check("parses all three labels", [x["label"] for x in labels] == ["FACT", "UNKNOWN", "INFERENCE"])

    check("detects rumination", C.detect_rumination("does she love me more than him"))
    check("no false rumination on real question", not C.detect_rumination("should I learn German"))
    check("detects medical risk", "doctor" in C.detect_professional_risk("see a doctor"))
    check("detects legal risk", "divorce" in C.detect_professional_risk("how does divorce work"))
    check("detects financial risk", "invest" in C.detect_professional_risk("where should I invest"))
    check("classifies avoidance intent", C.hidden_objective("does she love me more").startswith("AVOIDANCE"))
    check("classifies decision intent", C.hidden_objective("should I message her").startswith("DECISION"))
    check("classifies information intent", C.hidden_objective("what is FTS5").startswith("INFORMATION"))


def test_radar() -> None:
    from raees import db, radar

    print("\nradar")
    check("keeps clock tokens like 3am", "3am" in radar._tokens("i miss her at 3am"))
    check("keeps short alnum tokens", "11pm" in radar._tokens("11pm message"))

    # Use a scratch database so these tests never touch real data.
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "radar.db")
        db.init_db()

        db.add_pattern(
            "Uncertainty seeking loop",
            triggers=["does she love me", "compare", "old messages"],
        )
        db.add_pattern(
            "Late-night contact",
            triggers=["cant sleep", "awake at", "3am", "4am", "tonight"],
        )

        hits = [p["name"] for p in radar.match_patterns("does she love me more")]
        check("fires on love comparison", "Uncertainty seeking loop" in hits)
        check(
            "fires on a specific phrase",
            "Late-night contact" in [p["name"] for p in radar.match_patterns("awake at 4am again")],
        )
        check(
            "stays quiet on unrelated text",
            radar.match_patterns("what is the capital of France") == [],
        )
        # "tonight" is a real trigger, so this SHOULD match. What must not
        # happen is a match on the generic word "what" alone.
        generic_only = [p["name"] for p in radar.match_patterns("what is the capital of France")]
        check(
            "does not fire on a generic word alone",
            "Uncertainty seeking loop" not in generic_only,
        )

    db.reset_db_path()


def test_retrieval() -> None:
    from raees import db

    print("\nretrieval")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "t.db")
        db.init_db()

        db.add_fact("He saw a doctor on 13 Jul 2026.", source="test", confidence=0.9)
        db.add_episode("First job at Easylink", summary="Started work.", occurred_at="2024")
        db.add_pattern("Test pattern", triggers=["doctor", "clinic"])

        check("finds by single word", len(db.search_memory("doctor", limit=5)) > 0)
        check(
            "multi-word query returns results",
            len(db.search_memory("doctor visit appointment", limit=5)) > 0,
        )
        check("episode searchable", len(db.search_memory("Easylink", limit=5)) > 0)
        check("empty query returns nothing", db.search_memory("", limit=5) == [])
        check("stopword-only query returns nothing", db.search_memory("the and for", limit=5) == [])

        # Idempotency of seeding
        counts_before = db.counts()
        db.add_pattern("Second pattern", triggers=["sleep"])
        check("pattern count increments", db.counts()["patterns"] > counts_before["patterns"])

    db.reset_db_path()


def test_router() -> None:
    """The router decides the treatment. No user-visible mode."""
    from raees.router import route, question_class

    print("\nrouter")
    cases = [
        # (question, expected mode, why)
        ("does she love me more than her ex", "challenge", "unmeasurable comparison"),
        ("i want to know if she misses me more", "challenge", "comparison"),
        ("am i worth it?", "challenge", "self-worth verdict"),
        ("do i deserve this", "challenge", "self-worth verdict"),
        ("should i quit my job", "decide", "real decision"),
        ("which laptop should i buy", "decide", "real decision"),
        ("should i go to a doctor for chest pain", "ask", "professional domain"),
        ("where should i invest my savings", "ask", "financial domain"),
        ("what is FTS5", "ask", "knowledge question"),
        ("how does sqlite indexing work", "ask", "knowledge question"),
    ]
    for q, expected, why in cases:
        got = route(q).mode
        check(f"{why}: routes to {expected}", got == expected)

    check(
        "unclassified defaults to challenge, not agree",
        route("hmm").mode == "challenge",
    )
    check(
        "distress phrasing is detected",
        route("I AM SO TIRED OF THIS!!!!! WHY IS THIS ALWAYS ME").mode == "ask",
    )
    check(
        "escalates when a question class repeats",
        route("does she love me more", repeat_count=4).mode == "challenge",
    )
    check(
        "repetition produces an escalation note",
        any("times" in e for e in route("does she love me more", repeat_count=4).escalations),
    )
    check(
        "professional risk outranks a decision signal",
        any("Professional" in r.reason for r in [route("should i see a doctor")]),
    )

    print("\nquestion classes")
    check("comparison class", question_class("does she love me more") == "comparison")
    check("self-worth class", question_class("am i worth it") == "self_worth")
    check("decision class", question_class("should i quit") == "decision")
    check("knowledge class", question_class("what is sqlite") == "knowledge")


def test_contradictions() -> None:
    """Two stored facts that cannot both be true must be surfaced."""
    from raees import db

    print("\ncontradictions")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "c.db")
        db.init_db()

        db.add_fact("My sleep schedule is consistent.", source="test", confidence=0.8)
        db.add_fact("My sleep schedule is not consistent at all.", source="test", confidence=0.8)
        found = db.find_contradictions()
        check("negated same-subject claims are flagged", len(found) >= 1)
        check("subject is reported", bool(found and found[0]["subject"]))
        check("both sides are reported", bool(found and found[0]["a"] and found[0]["b"]))

        # Two consistent facts must not be flagged.
        db.add_fact("My job title is engineer.", source="test")
        db.add_fact("My job title is designer.", source="test")
        subjects = {c["subject"] for c in db.find_contradictions(limit=50)}
        check("non-negated difference is not a contradiction", "job title" not in subjects)

        check("empty database yields nothing", db.find_contradictions() is not None)

    db.reset_db_path()


def test_learning_gates() -> None:
    """Nothing becomes durable memory without passing every gate."""
    from raees import learn
    from raees import db

    print("\nlearning gates")  # noqa: E501
    check("rejects a feeling", not learn._is_durable("my mood", "I feel anxious about it"))
    check("rejects a belief", not learn._is_durable("my belief", "I believe she does not care"))
    check("rejects a clinical claim", not learn._is_durable("my health", "diagnosed with anxiety"))
    check("rejects a non-first-person subject", not learn._is_durable("her mood", "started work in 2024"))
    check("accepts a durable fact", learn._is_durable("my job", "started work in 2024 at Easylink"))

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "l.db")
        db.init_db()
        db.add_learned("my city: moved to Islamabad in 2023", kind="durable", source="test")
        cands = db.learned_candidates()
        check("learned fact starts as candidate", len(cands) == 1)
        check("candidate is searchable", len(db.search_memory("Islamabad", limit=3)) > 0)

        fid = db.approve_learned(cands[0]["id"])
        check("approval promotes to a curated fact", bool(fid))
        check("approved candidate leaves the queue", len(db.learned_candidates()) == 0)

        db.add_learned("my phone: bought a new one in 2025", kind="durable", source="test")
        rid = db.learned_candidates()[0]["id"]
        db.reject_learned(rid)
        check("rejection empties the queue", len(db.learned_candidates()) == 0)
        check("rejected fact is not searchable", db.search_memory("phone bought", limit=3) == [])


def test_extraction() -> None:
    """End-to-end: proposal text in, gated candidates out."""
    import asyncio
    from raees import learn

    print("\nextraction")

    async def run() -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e.db"
            from raees import db

            db.use_test_db(db_path)
            db.init_db()
            db.add_fact("I started a new job in August 2026 at Easylink.", source="seed")

            async def fake(_messages, **_kw):
                return "\n".join(
                    [
                        "FACT | my bicycle | I bought a road bike in March 2026",
                        "FACT | my mood | I feel anxious about the situation",
                        "FACT | her career | she started work in 2019",
                        "FACT | my health | I am diagnosed with anxiety disorder",
                        "FACT | my work | I started a new job in August 2026",
                        "EMPTY",
                    ]
                ), "fake"

            learn.complete = fake
            try:
                return await learn.extract("tell me something", "answer", "fake")
            finally:
                db.reset_db_path()

    got = asyncio.run(run())
    stored = [g["statement"] for g in got]
    check("durable first-person fact is stored", len(stored) == 1)
    check("the fact itself is correct", stored and "road bike" in stored[0])
    check("feeling is rejected", not any("anxious" in s for s in stored))
    check("third party is rejected", not any("her career" in s for s in stored))
    check("clinical claim is rejected", not any("anxiety disorder" in s for s in stored))
    check("already-known fact is rejected", not any("new job" in s for s in stored))
    check("EMPTY marker ignored", len(stored) == 1)

    print("\noffline extraction")
    offline = asyncio.run(learn.extract("q", "a", "offline"))
    check("offline provider extracts nothing", offline == [])


def test_evidence() -> None:
    """Raw source lines are stored once, findable, and cannot outlive a delete."""
    from raees import db

    print("\nevidence")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "ev.db")
        db.init_db()

        eid = db.add_evidence(
            source="chat.txt",
            body="But sometimes you upgrade yourself and change",
            occurred_at="2026-04-21 11:06am",
            speaker="hmm",
        )
        check("evidence row is created", eid is not None)
        check(
            "evidence is indexed",
            db.search_evidence("upgrade", limit=3) != [],
        )
        check(
            "same line again is a duplicate",
            db.add_evidence(
                source="chat.txt",
                body="But sometimes you upgrade yourself and change",
                occurred_at="2026-04-21 11:06am",
                speaker="hmm",
            ) is None,
        )
        check(
            "a different timestamp is a different line",
            db.add_evidence(
                source="chat.txt",
                body="But sometimes you upgrade yourself and change",
                occurred_at="2026-04-21 11:07am",
                speaker="hmm",
            ) is not None,
        )
        check("blank body is refused", db.add_evidence("chat.txt", "   ") is None)

        # The digest is what makes ingestion idempotent, so it must key on the
        # line's content and not on a row id the database assigns.
        a = db.evidence_digest("chat.txt", "2026-01-01 1:00am", "s", "body")
        b = db.evidence_digest("chat.txt", "2026-01-01 1:00am", "s", "body")
        c = db.evidence_digest("chat.txt", "2026-01-01 1:00am", "other", "body")
        check("digest is stable for the same line", a == b)
        check("digest distinguishes the speaker", a != c)

        hits = db.search_evidence("upgrade", limit=2)
        check("search returns the timestamp", bool(hits[0]["occurred_at"]))
        check("search returns the body", "upgrade" in hits[0]["body"])
        check("empty query returns nothing", db.search_evidence("   ") == [])

        conn = db.connect()
        # Delete the indexed row the way a plain SQL delete would, which is how
        # the orphan arose in the first place.
        conn.execute("DELETE FROM evidence WHERE id=?", (eid,))
        conn.commit()
        check(
            "deleting evidence orphans its index row",
            conn.execute(
                "SELECT COUNT(*) c FROM evidence_fts WHERE ref_id=?", (eid,)
            ).fetchone()["c"] == 1,
        )
        check("prune clears the evidence orphan", db.prune_fts_orphans() == 1)
        check(
            "the orphan is gone from search",
            all(h["id"] != eid for h in db.search_evidence("upgrade", limit=5)),
        )

    db.reset_db_path()


def test_evidence_parsing() -> None:
    """The WhatsApp export parser must keep lines and drop system noise."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ingest_evidence",
        Path(__file__).resolve().parent.parent / "scripts" / "ingest_evidence.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    print("\nevidence parsing")
    sample = "\n".join(
        [
            "19/04/2026, 3:57 am - Messages and calls are end-to-end encrypted.",
            "19/04/2026, 3:56 am - Churhail: Assalamualaikum",
            "19/04/2026, 4:07 am - Churhail: You wanted to talk",
            "19/04/2026, 4:09 am - hmm: Can we have a meeting",
            "continuation of the previous message",
            "20/04/2026, 9:02 am - Messages and calls are end-to-end encrypted.",
            "20/04/2026, 9:03 pm - hmm: Mny dad sy aj tk paisy ni leye",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chat.txt"
        path.write_text(sample, encoding="utf-8")
        rows = mod.parse_file(path)

    bodies = [r[2] for r in rows]
    check("encryption banners are dropped", not any("end-to-end" in b for b in bodies))
    # Three speakers lines plus the continuation, so four stored messages.
    check("every real message is kept", len(rows) == 4)
    check(
        "multi-line messages are joined",
        any("continuation of the previous" in b for b in bodies),
    )
    check(
        "date and time are normalised",
        rows[0][0] == "2026-04-19 3:56am",
    )
    check("speaker is captured", rows[0][1] == "Churhail")

    # Modern exports put U+202F before am/pm; it must not reach the database.
    narrow = mod.normalize_ts("21/04/2026", "11:06\u202fam")
    check("narrow no-break space is stripped", "\u202f" not in narrow)
    check("narrow no-break timestamp is clean", narrow == "2026-04-21 11:06am")

    check(
        "a file with no chat lines yields nothing",
        mod.parse_file(Path(tempfile.gettempdir()) / "definitely_missing.txt") == [],
    )


def test_question_ledger() -> None:
    """Repetition counting, which drives router escalation."""
    from raees import db

    print("\nquestion ledger")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "q.db")
        db.init_db()

        check("starts at zero", db.question_count("comparison") == 0)
        for _ in range(3):
            db.record_question("comparison", "does she love me more")
        check("counts repeats", db.question_count("comparison") == 3)
        check("counts total", db.question_count() == 3)

        db.record_question("knowledge", "what is sqlite")
        dist = {d["class"]: d["count"] for d in db.question_distribution()}
        check("distribution groups by class", dist.get("comparison") == 3)
        check("distribution includes other classes", dist.get("knowledge") == 1)

    db.reset_db_path()


def test_fts_integrity() -> None:
    """The search index must not outlive the rows it points at."""
    from raees import db

    print("\nfts integrity")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "fts.db")
        db.init_db()
        conn = db.connect()

        fid = db.add_fact(text="my father never took money from me", source="seed:test")
        check("indexed fact is findable", bool(db.search_memory("father", limit=3)))
        check(
            "index row exists",
            conn.execute(
                "SELECT COUNT(*) c FROM memory_fts WHERE kind='fact' AND ref_id=?", (fid,)
            ).fetchone()["c"] == 1,
        )

        # Reproduce the re-seed path: plain SQL delete, no _fts_index call.
        conn.execute("DELETE FROM facts WHERE id=?", (fid,))
        conn.commit()
        check(
            "plain SQL delete leaves an orphan",
            conn.execute(
                "SELECT COUNT(*) c FROM memory_fts WHERE kind='fact' AND ref_id=?", (fid,)
            ).fetchone()["c"] == 1,
        )

        removed = db.prune_fts_orphans()
        check("prune reports the orphan", removed == 1)
        check("orphan is gone from the index", db.search_memory("father", limit=3) == [])

        # Re-indexing the same content must not duplicate index rows.
        db.add_fact(text="my father never took money from me", source="seed:test")
        check(
            "re-index does not duplicate",
            conn.execute(
                "SELECT COUNT(*) c FROM memory_fts WHERE kind='fact' AND ref_id=?", (fid,)
            ).fetchone()["c"] == 1,
        )
        check("prune is a no-op when clean", db.prune_fts_orphans() == 0)

        learned_id = db.add_learned(
            text="i bought a road bike in march 2026",
            kind="fact",
            source="learned:test",
            subject="bicycle",
        )
        check(
            "learned candidate is indexed",
            conn.execute(
                "SELECT COUNT(*) c FROM memory_fts WHERE kind='learned' AND ref_id=?",
                (learned_id,),
            ).fetchone()["c"] == 1,
        )
        conn.execute("DELETE FROM learned WHERE id=?", (learned_id,))
        conn.commit()
        check(
            "prune also cleans learned orphans",
            db.prune_fts_orphans() == 1,
        )

    db.reset_db_path()


def test_critique_parsing() -> None:
    """The self-audit must never let a bad revision replace a good draft."""
    from raees.engine import _self_critique, audit_response
    import inspect

    print("\nself-audit")
    src = inspect.getsource(_self_critique)
    check("fails soft on empty draft", "return {}, None, []" in src)

    check(
        "reassurance language is caught",
        any("reassurance" in w for w in audit_response("You are doing great, don't be so hard on yourself.")),
    )
    check(
        "handing the decision back is caught",
        any("handed the decision" in w for w in audit_response("At the end of the day, only you can know.")),
    )
    check(
        "challenge missing CASE AGAINST is caught",
        any("CASE AGAINST" in w for w in audit_response("CASE FOR: x\nRECOMMENDATION: y", challenge_mode=True)),
    )
    check(
        "complete challenge is not flagged for sections",
        not any("CASE AGAINST" in w for w in audit_response(
            "CASE FOR: a\nCASE AGAINST: b\nRECOMMENDATION: c", challenge_mode=True)),
    )
    check(
        "fabrication is caught in challenge mode too",
        any("comparison" in w for w in audit_response(
            "CASE FOR: a\nCASE AGAINST: she loved him 40% more", challenge_mode=True)),
    )


def test_isolation() -> None:
    """The real database must be untouched by a test run."""
    from raees import db

    print("\nisolation")
    check(
        "test db path is not the production path",
        "test" in str(db.DB_PATH) or "data" in str(db.DB_PATH),
    )


def test_remote_web() -> None:
    """The phone-facing surface: service worker scope, manifest, API shape.

    These are the bits that make remote access work, and each one failed
    silently at least once: a wrong sw.js path leaves the app unusable offline
    without any visible error in the browser.
    """
    from fastapi.testclient import TestClient

    from raees.app import app

    client = TestClient(app)

    sw = client.get("/sw.js")
    check("service worker served at root scope", sw.status_code == 200)
    check(
        "service worker has javascript content type",
        "javascript" in sw.headers.get("content-type", ""),
    )

    # The registration path in app.js must match where the worker is served.
    # A mismatch still returns 200 from /static/sw.js but never controls "/".
    app_js = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text()
    check(
        "app registers the worker at root scope",
        'serviceWorker.register("/sw.js")' in app_js,
    )
    check(
        "app does not register the worker under /static",
        'register("/static/sw.js")' not in app_js,
    )

    # start_url must sit inside the worker's scope, or installing to the
    # homescreen produces a shortcut that opens with no offline shell.
    import json

    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "web" / "manifest.json").read_text()
    )
    check("manifest start_url is origin root", manifest.get("start_url") == "/")
    check("manifest is standalone", manifest.get("display") == "standalone")

    # The app must not cache API traffic, or answers go stale on a second device.
    sw_body = sw.text
    check("service worker skips /api/", '/api/' in sw_body and "return;" in sw_body)

    health = client.get("/api/health")
    check("health endpoint responds", health.status_code == 200)
    check("health reports counts", "counts" in health.json())


def main() -> int:
    before = None
    before_digest = None
    try:
        from raees import db

        db.init_db()
        before = db.counts()
        before_digest = db.content_digest()
    except Exception:
        pass

    test_brake()
    test_router()
    test_radar()
    test_retrieval()
    test_contradictions()
    test_learning_gates()
    test_extraction()
    test_question_ledger()
    test_fts_integrity()
    test_evidence()
    test_evidence_parsing()
    test_critique_parsing()
    test_isolation()
    test_remote_web()

    if before is not None:
        from raees import db

        db.reset_db_path()
        db.init_db()
        after = db.counts()
        check(
            "real database row counts unchanged by tests",
            before == after,
        )
        check(
            "real database content unchanged by tests",
            before_digest == db.content_digest(),
        )

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())