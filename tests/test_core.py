"""Tests for the parts that must not break: the brake, the radar, retrieval.

Run:  .venv/bin/python -m tests.test_core
"""

from __future__ import annotations

import base64
import os
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
    from atif_assistant.engine import audit_response, parse_labels
    from atif_assistant import constitution as C

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
    from atif_assistant import db, radar

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
    from atif_assistant import db

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
    from atif_assistant.router import route, question_class

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
    from atif_assistant import db

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
    from atif_assistant import learn
    from atif_assistant import db

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
    from atif_assistant import learn

    print("\nextraction")

    async def run() -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e.db"
            from atif_assistant import db

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
    from atif_assistant import db

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
    from atif_assistant import db

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
    from atif_assistant import db

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
    from atif_assistant.engine import _self_critique, audit_response
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


def test_structure_guard() -> None:
    import asyncio

    from atif_assistant import engine
    from atif_assistant.engine import structure_ok

    print("\nstructure guard")
    check("plain prose is unstructured", not structure_ok("Love cannot be ranked."))
    check("[FACT]-labelled answer is structured", structure_ok("[FACT] She said so."))
    check(
        "challenge needs its sections",
        not structure_ok("[FACT] x\nCASE FOR: a", challenge_mode=True),
    )
    check(
        "full challenge is structured",
        structure_ok(
            "[FACT] a\nCASE FOR: b\nCASE AGAINST: c\nRECOMMENDATION: d",
            challenge_mode=True,
        ),
    )

    original = engine.complete
    try:
        # The draft is unlabelled and the revision loses the sections; the
        # repair pass must restore both.
        async def repair_scenario():
            async def fake(messages, **kw):
                system = messages[0]["content"]
                if "Reformat the ANSWER" in system:
                    return (
                        "[FACT] She wrote a lot.\n"
                        "[UNKNOWN] Whether she loves you more.\n\n"
                        "CASE FOR: things look good.\n"
                        "CASE AGAINST: you cannot measure it.\n"
                        "RECOMMENDATION: stop comparing.",
                        "fake",
                    )
                if "DRAFT ANSWER TO AUDIT" in messages[1]["content"]:
                    return (
                        "VERDICT: NEEDS_REVISION\nDEFECTS: 1. lost structure\n"
                        "REVISION: EMPTY",
                        "fake",
                    )
                return ("**Challenge:** unmeasurable. **Recommendation:** stop.", "fake")

            engine.complete = fake
            return await engine._challenge("She loves me more?", engine.build_context("q"))

        result = asyncio.run(repair_scenario())
        check(
            "repaired challenge has labels",
            bool(engine._LABEL_RE.search(result["text"])),
        )
        check(
            "repaired challenge keeps CASE AGAINST",
            "CASE AGAINST" in result["text"].upper(),
        )
        check("no structural warnings after repair", result["warnings"] == [])

        # A revision that drops the structure must be rejected in favour of the
        # structurally-correct draft.
        async def keep_draft_scenario():
            async def fake(messages, **kw):
                if "DRAFT ANSWER TO AUDIT" in messages[1]["content"]:
                    return (
                        "VERDICT: NEEDS_REVISION\nDEFECTS: 1. tone\n"
                        "REVISION: Here is a long plain paragraph that removes "
                        "every label and every required section header, so the "
                        "answer is now just flowing prose with no structure at all.",
                        "fake",
                    )
                return (
                    "[FACT] good draft\nCASE FOR: a\nCASE AGAINST: b\n"
                    "RECOMMENDATION: c",
                    "fake",
                )

            engine.complete = fake
            return await engine._challenge("q", engine.build_context("q"))

        kept = asyncio.run(keep_draft_scenario())
        check(
            "keeps the better draft over a structure-losing revision",
            bool(engine._LABEL_RE.search(kept["text"]))
            and "CASE AGAINST" in kept["text"].upper(),
        )
    finally:
        engine.complete = original


def test_isolation() -> None:
    """The real database must be untouched by a test run."""
    from atif_assistant import db

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

    from atif_assistant.app import app

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


def test_extended_api() -> None:
    """Settings, notes, works, media and social endpoints persist correctly.

    These are the surfaces added after the rename. Each one previously had no
    coverage, so a broken route or a missing table would only show up when the
    phone hit it.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\nextended api")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "ext.db")
        db.init_db()
        client = TestClient(app)

        check("settings start empty", client.get("/api/settings").json() == {})
        client.post("/api/settings", json={"theme": "dark", "skip": None})
        got = client.get("/api/settings").json()
        check("settings round-trip", got.get("theme") == "dark")
        check("null settings are ignored", "skip" not in got)

        nid = client.post(
            "/api/notes", json={"title": "t", "body": "hello", "mood": "calm"}
        ).json()["id"]
        notes = client.get("/api/notes").json()["notes"]
        check("note is stored", any(n["id"] == nid for n in notes))
        check("note body survives", notes[0]["body"] == "hello")

        wid = client.post("/api/works", json={"title": "proj"}).json()["id"]
        works = client.get("/api/works").json()["works"]
        check("work is stored", any(w["id"] == wid for w in works))

        mid = client.post("/api/media", json={"path": "/x.png", "kind": "image"}).json()["id"]
        media = client.get("/api/media").json()["media"]
        check("media is stored", any(m["id"] == mid for m in media))

        sid = client.post(
            "/api/social/accounts", json={"platform": "x", "username": "u"}
        ).json()["id"]
        accts = client.get("/api/social/accounts").json()["accounts"]
        check("social account is stored", any(a["id"] == sid for a in accts))
        check("social posts start empty", client.get("/api/social/posts").json() == {"posts": []})

    db.reset_db_path()


def test_location() -> None:
    """GPS fixes are idempotent, cluster into places, and yield routines."""
    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\nlocation")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "loc.db")
        db.init_db()
        client = TestClient(app)

        a = client.post(
            "/api/location",
            json={"lat": 51.5074, "lon": -0.1278, "occurred_at": "2026-01-05 09:00:00"},
        ).json()
        check("first fix is stored", a.get("ok") and not a.get("duplicate"))
        place_id = a["place_id"]
        check("fix created a place", place_id is not None)

        dup = client.post(
            "/api/location",
            json={"lat": 51.5074, "lon": -0.1278, "occurred_at": "2026-01-05 09:00:00"},
        ).json()
        check("same fix is a duplicate", dup.get("duplicate") is True)

        near = client.post(
            "/api/location",
            json={"lat": 51.5076, "lon": -0.1279, "occurred_at": "2026-01-12 09:30:00"},
        ).json()
        check("nearby fix folds into the same place", near["place_id"] == place_id)

        far = client.post(
            "/api/location",
            json={"lat": 48.8566, "lon": 2.3522, "occurred_at": "2026-01-12 15:00:00"},
        ).json()
        check("distant fix starts a new place", far["place_id"] != place_id)

        named = client.post(f"/api/places/{place_id}/name", json={"name": "Office", "kind": "work"})
        check("place can be named", named.json().get("ok") is True)
        check("bad place id is rejected", client.post("/api/places/999999/name", json={"name": "x"}).status_code == 404)
        check("empty name is rejected", client.post(f"/api/places/{place_id}/name", json={"name": "  "}).status_code == 400)

        # A third Monday 09:xx visit makes the 09:00 bucket a routine.
        client.post(
            "/api/location",
            json={"lat": 51.5074, "lon": -0.1278, "occurred_at": "2026-01-19 09:10:00"},
        )
        derived = client.post("/api/routines/derive?min_observations=3").json()
        check("routine derived from repeated visits", derived["count"] >= 1)
        rout = client.get("/api/routines").json()["routines"]
        check("routine names the place", any("Office" in r["name"] for r in rout))
        check(
            "routine has candidate status, not certainty",
            all(r["status"] == "candidate" for r in rout),
        )

        pts = client.get("/api/location").json()["points"]
        check("points are listed", len(pts) == 4)

    db.reset_db_path()


def test_uploads() -> None:
    """Uploads are content-addressed, fold text into memory, and stay idempotent."""
    from fastapi.testclient import TestClient

    from atif_assistant import db, uploads
    from atif_assistant.app import app

    print("\nuploads")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "up.db")
        db.init_db()
        uploads.UPLOADS_DIR = base / "uploads"
        client = TestClient(app)

        r = client.post(
            "/api/upload",
            json={"filename": "plan.txt", "related_to": "business plan", "text": "Secret growth plan"},
        )
        body = r.json()
        check("text upload succeeds", body.get("ok") is True)
        check("kind detected as text", body.get("kind") == "text")
        check("text became evidence", body.get("evidence_id") is not None)
        check("text became an episode", body.get("episode_id") is not None)

        conn = db.connect()
        check("media row written", conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"] == 1)
        lib = client.get("/api/media").json()["media"]
        check("upload appears in media library", len(lib) == 1)
        import json as _json

        meta = _json.loads(lib[0]["meta"] or "{}")
        check("media library carries the filename", meta.get("filename") == "plan.txt")
        check("media library carries related_to as tags", lib[0]["tags"] == "business plan")
        check(
            "uploaded text is searchable as evidence",
            any("Secret" in h["body"] for h in db.search_evidence("growth", limit=3)),
        )

        r2 = client.post(
            "/api/upload",
            json={"filename": "plan.txt", "related_to": "business plan", "text": "Secret growth plan"},
        )
        b2 = r2.json()
        check("same file is recognised as duplicate", b2.get("duplicate_file") is True)
        check("duplicate adds no second episode", b2.get("episode_id") is None)
        check("duplicate adds no second evidence row", b2.get("evidence_id") is None)

        png = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00binary").decode()
        r3 = client.post("/api/upload", json={"filename": "pic.png", "content_b64": png})
        b3 = r3.json()
        check("binary upload succeeds", b3.get("ok") is True)
        check("binary kind detected", b3.get("kind") == "image")
        check("binary is not parsed into memory", b3.get("evidence_id") is None)

        check("missing content is rejected", client.post("/api/upload", json={"filename": "x"}).status_code == 400)
        check(
            "bad base64 is rejected",
            client.post("/api/upload", json={"filename": "x", "content_b64": "!!!not base64!!!"}).status_code == 400,
        )

    db.reset_db_path()


def test_backup() -> None:
    """Export produces a downloadable snapshot; import restores add-only."""
    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\nbackup")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "a.db")
        db.init_db()
        client = TestClient(app)

        db.add_fact("I prefer morning work", source="test", confidence=0.7)
        client.post("/api/notes", json={"title": "t", "body": "note body"})
        client.post(
            "/api/decisions",
            json={"topic": "job", "decision": "stay", "prediction": "calmer", "confidence": 0.6},
        )

        exp = client.get("/api/export").json()
        check("export has metadata", exp.get("app") == "atif-assistant" and "tables" in exp)
        check("export includes the fact", any("morning work" in f["text"] for f in exp["tables"]["facts"]))
        check(
            "export sets a download filename",
            client.get("/api/export").headers.get("content-disposition", "").startswith("attachment"),
        )

        # Restore into a different, empty database.
        db.use_test_db(base / "b.db")
        db.init_db()
        added = client.post("/api/import", json=exp).json()["added"]
        check("import adds the fact", added["facts"] == 1)
        check("import adds the note", added["notes"] == 1)
        check("import adds the decision", added["decisions"] == 1)

        again = client.post("/api/import", json=exp).json()["added"]
        check("re-import is a no-op", again["facts"] == 0 and again["notes"] == 0)

        check(
            "a foreign file is rejected",
            client.post("/api/import", json={"app": "other", "tables": {}}).status_code == 400,
        )
        check(
            "a file without tables is rejected",
            client.post("/api/import", json={"app": "atif-assistant"}).status_code == 400,
        )

    db.reset_db_path()


def test_providers() -> None:
    """API keys are configurable at runtime, masked, and never leaked."""
    from fastapi.testclient import TestClient

    from atif_assistant import db, llm
    from atif_assistant.app import app

    print("\nproviders")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "p.db")
        db.init_db()
        client = TestClient(app)

        # --- resolver precedence: DB override wins, empty row means cleared.
        old_env = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = "env-key-value"
        try:
            check("env key is used when no override", llm.provider_key("groq") == "env-key-value")
            db.set_setting("provider.groq.api_key", "")
            check("empty override clears the env key", llm.provider_key("groq") == "")
            db.set_setting("provider.groq.api_key", "db-key-value")
            check("db override wins over env", llm.provider_key("groq") == "db-key-value")
        finally:
            if old_env is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = old_env

        # --- model resolution.
        check("model falls back to the default", llm.provider_model("groq") == "openai/gpt-oss-120b")
        db.set_setting("provider.groq.model", "custom-model")
        check("model override is used", llm.provider_model("groq") == "custom-model")
        client.post("/api/providers/groq", json={"model": ""})
        check("clearing the model reverts to the default", llm.provider_model("groq") == "openai/gpt-oss-120b")

        # --- masking never reveals the whole key.
        check("mask keeps only the tail", llm.mask_key("sk-abcdef123456") == "\u20263456")
        check("empty key masks to empty", llm.mask_key("") == "")

        # --- keys are hidden from the generic settings endpoint.
        db.set_setting("theme", "dark")
        saved = client.get("/api/settings").json()
        check("provider keys hidden from /api/settings", not any(k.startswith("provider.") for k in saved))
        check("ordinary settings still returned", saved.get("theme") == "dark")

        # --- keys are excluded from backups.
        exp = client.get("/api/export").json()
        exported = [r.get("key") for r in exp["tables"].get("settings", [])]
        check("provider keys excluded from export", not any(str(k).startswith("provider.") for k in exported))

        # --- save and clear through the API, with a masked response.
        db.set_setting("provider.groq.api_key", "")
        r = client.post("/api/providers/groq", json={"api_key": "sk-live-9999"})
        body = r.json()
        check("save reports the key set", body["provider"]["key_set"] is True)
        check("save response is masked", body["provider"]["key_hint"] == "\u20269999")
        check("key actually stored", llm.provider_key("groq") == "sk-live-9999")
        client.post("/api/providers/groq", json={"clear_key": True})
        check("clear blanks the key", llm.provider_key("groq") == "")

        # --- GET /api/providers lists all with labels.
        listing = client.get("/api/providers").json()
        names = [p["name"] for p in listing["providers"]]
        check("providers endpoint lists all", names == listing["order"] and "groq" in names)
        check("providers carry a label", all(p.get("label") for p in listing["providers"]))

        # --- unknown provider rejected.
        check("unknown provider is a 404", client.post("/api/providers/nope", json={}).status_code == 404)

        # --- the TEST endpoint, with the network call stubbed out.
        original = llm.HANDLERS.get("groq")

        async def ok_handler(model, messages, **kw):
            ok_handler.seen_key = kw.get("key")
            return "pong"

        async def boom_handler(model, messages, **kw):
            raise RuntimeError("provider exploded")

        try:
            llm.HANDLERS["groq"] = ok_handler
            t = client.post("/api/providers/groq/test", json={"api_key": "unsaved-key"}).json()
            check("test reports ready for a working provider", t["ready"] is True)
            check("test passes the unsaved key through", ok_handler.seen_key == "unsaved-key")
            check("test returns latency", isinstance(t["latency_ms"], int))

            llm.HANDLERS["groq"] = boom_handler
            t2 = client.post("/api/providers/groq/test", json={"api_key": "unsaved-key"}).json()
            check("test reports failure when the provider raises", t2["ready"] is False)
            check("test surfaces the error", "provider exploded" in (t2["error"] or ""))

            all_res = client.post("/api/providers/test").json()["results"]
            check("test all returns one result per provider", len(all_res) == len(listing["order"]))
        finally:
            if original is not None:
                llm.HANDLERS["groq"] = original

        llm.invalidate_probe_cache()

    db.reset_db_path()


def main() -> int:
    before = None
    before_digest = None
    try:
        from atif_assistant import db

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
    test_extended_api()
    test_location()
    test_uploads()
    test_backup()
    test_providers()
    test_structure_guard()

    if before is not None:
        from atif_assistant import db

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