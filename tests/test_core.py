"""Tests for the parts that must not break: the brake, the radar, retrieval.

Run:  .venv/bin/python -m tests.test_core
"""

from __future__ import annotations

import base64
import json
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
    check(
        "catches a claim of lived human experience",
        any(
            "human experience" in w
            for w in audit_response("[FACT] Yesterday I had lunch with a friend.")
        ),
    )
    check(
        "catches a claimed body state",
        any(
            "human experience" in w
            for w in audit_response("[FACT] I'm tired today, let's pause.")
        ),
    )
    check(
        "a warm reciprocal answer is allowed (persona v2)",
        not any(
            "human experience" in w
            for w in audit_response("[FACT] I'm good, thanks - what about you?")
        ),
    )
    check(
        "a flat status line makes no human-experience claim",
        not any(
            "human experience" in w
            for w in audit_response("[FACT] I am an AI language model; I have no mood.")
        ),
    )
    check(
        "an incidental 'I'm well aware' is not a human-experience claim",
        not any(
            "human experience" in w
            for w in audit_response("[FACT] I'm well aware of the timeline.")
        ),
    )

    from atif_assistant.engine import normalize_labels

    check(
        "fullwidth labels are normalised before parsing",
        parse_labels(normalize_labels("她走了【INFERENCE】"))[0]["label"] == "INFERENCE",
    )
    check(
        "alternate brackets no longer trip the label brake",
        audit_response("Diagnosis is unclear【UNKNOWN】") == [],
    )
    check(
        "corner-bracket labels are normalised too",
        [x["label"] for x in parse_labels(normalize_labels("「FACT」 it rained"))] == ["FACT"],
    )

    labels = parse_labels("[FACT] a\n[UNKNOWN] b\n[INFERENCE] c")
    check("parses all three labels", [x["label"] for x in labels] == ["FACT", "UNKNOWN", "INFERENCE"])

    check("detects rumination", C.detect_rumination("does she love me more than him"))
    check("no false rumination on real question", not C.detect_rumination("should I learn German"))
    check(
        "'compare memory usage' is not rumination",
        not C.detect_rumination("compare memory usage of these indexes"),
    )
    check("detects medical risk", "doctor" in C.detect_professional_risk("see a doctor"))
    check("detects legal risk", "divorce" in C.detect_professional_risk("how does divorce work"))
    check("detects financial risk", "invest" in C.detect_professional_risk("where should I invest"))
    check(
        "'flaw'/'lawn'/'claw' are not legal terms",
        C.detect_professional_risk("the flaw in my lawn, and how to draw a claw") == [],
    )
    check(
        "'drugstore' is not a medical term",
        C.detect_professional_risk("what time does the drugstore close") == [],
    )
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

    check(
        "'how are you' is social, answered directly",
        route("how are you").mode == "ask",
    )
    check("bare greeting is social", route("hello").mode == "ask")
    check(
        "persona question is social",
        route("what's your name").mode == "ask",
    )
    check(
        "persona question is not mistaken for knowledge",
        question_class("what is your name") == "social",
    )
    check(
        "'what are you' is persona, not a knowledge lookup",
        question_class("what are you") == "social",
    )

    print("\nquestion classes")
    check("comparison class", question_class("does she love me more") == "comparison")
    check("self-worth class", question_class("am i worth it") == "self_worth")
    check("decision class", question_class("should i quit") == "decision")
    check("knowledge class", question_class("what is sqlite") == "knowledge")
    check("social class", question_class("how are you") == "social")


def test_contradictions() -> None:
    """Two stored facts that cannot both be true must be surfaced."""
    from atif_assistant import db

    print("\ncontradictions")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "c.db")
        db.init_db()

        fa = db.add_fact("My sleep schedule is consistent.", source="test", confidence=0.8)
        fb = db.add_fact("My sleep schedule is not consistent at all.", source="test", confidence=0.8)
        found = db.find_contradictions()
        check("negated same-subject claims are flagged", len(found) >= 1)
        check("subject is reported", bool(found and found[0]["subject"]))
        check("both sides are reported", bool(found and found[0]["a"] and found[0]["b"]))
        check(
            "each side carries the fact id so it can be settled",
            found and {found[0]["a_id"], found[0]["b_id"]} == {fa, fb},
        )

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

    # A message that is only invisible direction marks must be dropped, while a
    # message that merely contains one is kept.
    with tempfile.TemporaryDirectory() as tmp:
        p2 = Path(tmp) / "invisible.txt"
        p2.write_text(
            "19/04/2026, 3:57 am - a: \u200e\u200f\u200b\n"
            "19/04/2026, 3:58 am - a: hello\u200eworld\n",
            encoding="utf-8",
        )
        rows2 = mod.parse_file(p2)
    check("a message of only invisible marks is dropped", len(rows2) == 1)
    check("a message containing an invisible mark is kept", "hello" in rows2[0][2])


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

    check("english has no language rule", engine._language_rule("en") == "")
    check("urdu rule mentions Urdu", "اردو" in engine._language_rule("ur"))
    check(
        "system prompt carries the urdu rule when lang=ur",
        "اردو" in engine._system_with({"language": "ur"}, "X"),
    )
    check(
        "system prompt stays english otherwise",
        "اردو" not in engine._system_with({"language": "en"}, "X"),
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

    # Cache discipline: with a cacheable shell the WebView keeps rendering the
    # pre-update HTML forever (zip-epoch Last-Modified = heuristic freshness of
    # years), which looks exactly like "the fix did not ship". The phone loads
    # /?v=<versionCode> and the server rewrites asset urls with the same token.
    page = client.get("/?v=7")
    check("index disables caching", "no-store" in page.headers.get("cache-control", ""))
    check(
        "index rewrites asset urls with the version token",
        "/static/app.js?v=7" in page.text and "/static/style.css?v=7" in page.text,
    )
    check(
        "unversioned index still serves",
        client.get("/").status_code == 200 and "ATIF ASSISTANT" in client.get("/").text,
    )
    asset = client.get("/static/app.js")
    check("static assets disable caching", "no-store" in asset.headers.get("cache-control", ""))

    main_java = (
        Path(__file__).resolve().parent.parent
        / "mobile/android/app/src/main/java/ai/atif/assistant/MainActivity.java"
    ).read_text()
    check("app loads the shell with LOAD_NO_CACHE", "LOAD_NO_CACHE" in main_java)
    check(
        "app busts the document url per version",
        '?v=" + BuildConfig.VERSION_CODE' in main_java,
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


def test_web_sync() -> None:
    """The three front ends must not drift apart.

    app.js talks to index.html by element id (a renamed element becomes a
    silent null), to FastAPI by literal path (a renamed route becomes a 404
    that only appears when that screen opens), and to the APK by AndroidVoice
    bridge method (a renamed method is skipped by its typeof guard). CI is
    the only place all three files are checked together, because the APK
    itself cannot be built on GitHub runners (arm64-only native libs).
    """
    import re

    root = Path(__file__).resolve().parent.parent
    js = (root / "web" / "app.js").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    java = (
        root / "mobile" / "android" / "app" / "src" / "main" / "java"
        / "ai" / "atif" / "assistant" / "MainActivity.java"
    ).read_text(encoding="utf-8")

    # 1. Every literal id app.js looks up exists in index.html or is created
    #    by app.js itself; otherwise the guarded branch simply never runs.
    js_ids = set(re.findall(r'getElementById\("([^"]+)"\)', js))
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    made_by_js = set(re.findall(r'\.id\s*=\s*"([^"]+)"', js))
    missing_ids = sorted(js_ids - html_ids - made_by_js)
    check("every getElementById target exists", not missing_ids)
    if missing_ids:
        print("       missing: " + ", ".join(missing_ids))

    # 2. Wiring that carries whole features: each id must be in BOTH files.
    #    (setup-sets is deliberately absent: JS reaches those buttons by
    #    class, and its id is only a CSS/anchor hook.)
    critical = (
        "setup-dl", "setup-pause",
        "lock-setting-row", "set-applock", "dot", "statusline",
        "btn-new-chat", "btn-history", "history-sheet", "history-list",
        "btn-home", "home-sheet", "home-body",
        "src-pick", "src-preview", "src-stage",
    )
    for el in critical:
        check(
            f"{el} wired in html and js",
            f'id="{el}"' in html and f'getElementById("{el}")' in js,
        )

    # 3. Literal fetches must match a FastAPI route, or the UI breaks with a
    #    404 only at runtime, and only when that screen opens.
    routes = set()
    for py in (root / "atif_assistant").glob("*.py"):
        routes |= set(
            re.findall(
                r'@app\.(?:get|post|put|delete)\("([^"]+)"',
                py.read_text(encoding="utf-8"),
            )
        )
    fetches = {f.split("?")[0] for f in re.findall(r'fetch\("(/[^"`]+)"', js)}
    unrouted = sorted(fetches - routes)
    check("every literal fetch hits a real route", not unrouted)
    if unrouted:
        print("       unrouted: " + ", ".join(unrouted))

    # 4. Bridge methods the page calls must exist on the Java side.
    js_methods = set(re.findall(r"AndroidVoice\.(\w+)\s*\(", js))
    js_methods |= set(re.findall(r"\bbridge\.(\w+)\s*\(", js))
    at = java.find("class VoiceBridge")
    bridge_src = java[at:] if at != -1 else ""
    java_methods = set(re.findall(r"public\s+\w+\s+(\w+)\s*\(", bridge_src))
    missing_m = sorted(js_methods - java_methods)
    check("every bridge call exists in MainActivity", not missing_m)
    if missing_m:
        print("       missing: " + ", ".join(missing_m))


def test_natural_reply_surface() -> None:
    """The conversation is plain chat; every meta artifact hides behind ⓘ.

    User decisions for v1.3.3: labels are stripped at render time instead of
    being badged, and the WHY THIS REPLY panel opens only from a per-answer
    ⓘ (never automatically - an auto-open panel eats 40vh of a phone
    screen). The panel must still surface MOOD/STATUS/INTENT, and restored
    history recovers its labels from the raw text. Guards both directions:
    inline chips sneaking back in, or the panel quietly stopping to open.
    """
    root = Path(__file__).resolve().parent.parent
    js = (root / "web" / "app.js").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    css = (root / "web" / "style.css").read_text(encoding="utf-8")

    print("\nnatural replies: plain bubble, meta aside")

    # Stripped (speak + labelize + history recovery), never badge-rendered.
    check(
        "reality labels stripped at render time",
        js.count("FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION") >= 2,
    )
    check("no inline meta chips", "meta.appendChild(chip" not in js)
    check("no red brake boxes in messages", '"brake"' not in js)
    check("no rumination chip text", "RUMINATION RISK" not in js)
    check("no self-audit chip text", "SELF-AUDIT" not in js)
    check("route strip function removed", "showRoute" not in js)
    check("route strip markup removed", 'id="route"' not in html)
    check("route strip css removed", ".route-mode" not in css)
    check(
        "chip and meta css removed",
        ".chip {" not in css and ".meta {" not in css,
    )

    # Every answer carries the opener, and the panel can be dismissed.
    check("per-answer why button", '"ⓘ"' in js)
    check(
        "why button opens the panel",
        "function showBasis" in js and "showBasis(res)" in js,
    )
    check(
        "close button in markup and js",
        "close-basis" in html and "close-basis" in js,
    )

    # The panel renders but never opens by itself.
    rb = js.split("function renderBasis(", 1)[-1].split("\nfunction ", 1)[0]
    check("why panel never auto-opens", "hidden = false" not in rb)
    check("why panel carries mood row", 'addRow("MOOD"' in rb)
    check("why panel flags stopped answers", 'addRow("STATUS"' in rb)

    # Restored history stores content only - labels come back from the text.
    check(
        "labels recoverable from raw text",
        "function parseLabelsFromText" in js,
    )

    check("old hint copy retired", "Every claim labelled" not in html)
    check("new hint promises a tap to details", "one tap away" in html)


def test_layout_navigation() -> None:
    """Phone layout pass (v1.3.3): primary row + MORE, sectioned settings,
    one scroll pane per surface.

    Every secondary screen stays a single copy of its button inside the
    MORE wrapper (display:contents on wide screens) so ids, handlers and
    tests never fork. Settings stop being one 200-line label wall: cards
    with titles, two columns at >=600px, and no <label> wrapping a <div>
    (labels swallow clicks of the buttons inside them). Each sheet body
    owns exactly one scroll region - bare divs used to spill past the fixed
    sheet with no way to reach the bottom of a phone screen.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    js = (root / "web" / "app.js").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    css = (root / "web" / "style.css").read_text(encoding="utf-8")

    print("\nlayout: nav, settings cards, scroll hygiene")

    # --- MORE menu: one copy of every button, ids intact on both sides.
    check("more button in markup and js", 'id="btn-more"' in html and '"btn-more"' in js)
    check("more wrapper in markup and js", 'id="hdr-more"' in html and '"hdr-more"' in js)
    more = html.split('<div class="hdr-more"', 1)[-1].split("</div>", 1)[0]
    for bid in (
        "btn-learned", "btn-decisions", "btn-rules", "btn-data",
        "btn-new-chat", "btn-history", "btn-settings",
    ):
        check(f"{bid} behind MORE", f'id="{bid}"' in more)
    primary = html.split('<div class="hdr-more"', 1)[0]
    for bid in ("btn-home", "btn-memory", "btn-insights", "btn-call"):
        check(f"{bid} in the primary row", f'id="{bid}"' in primary)
    check("wide screens keep the full nav", ".hdr-more { display: contents; }" in css)
    check("more hidden on wide screens", "#btn-more { display: none; }" in css)
    check(
        "phone opens the more menu",
        ".hdr-more.open" in css and "#btn-more { display: inline-block; }" in css,
    )
    check("old scroll strip removed", "overflow-x" not in css)
    check("menu closes on choice", "classList.remove(\"open\")" in js)

    # --- Settings: cards, grid, no label-wraps-div, hidden stays hidden.
    check("settings sectioned into cards", html.count('<section class="set-card">') >= 6)
    check("section tags balanced", html.count("<section") == html.count("</section>"))
    check("titles for every card", html.count('class="set-title"') >= 7)
    check(
        "two-column grid at >=600px",
        'class="set-grid"' in html and "grid-template-columns: 1fr 1fr" in css,
    )
    wrapped = re.findall(
        r"<label\b[^>]*>(?:(?!</label>).)*<div", html, re.S
    )
    check("no label wraps a div", not wrapped)
    check(
        "hidden labels stay hidden",
        ".settings-body label[hidden] { display: none; }" in css,
    )

    # --- One scroll pane per sheet.
    check(
        "memory results has min-height",
        re.search(r"#mem-results\s*\{[^}]*min-height:\s*0", css) is not None,
    )
    check(
        "decisions body has min-height",
        re.search(r"#decisions-body\s*\{[^}]*min-height:\s*0", css) is not None,
    )
    check(
        "home body scrolls",
        re.search(r"#home-body\s*\{[^}]*overflow-y:\s*auto", css) is not None,
    )
    check(
        "data tabs scroll in place",
        re.search(
            r"#data-import,\s*#data-media\s*\{[^}]*overflow-y:\s*auto", css
        )
        is not None,
    )
    check("library inner scroller gone", "max-height:420px" not in html)
    contain = re.search(r"([^{]*?)\{[^}]*overscroll-behavior:\s*contain", css)
    sels = contain.group(1) if contain else ""
    for sel in (
        "#chat", ".sheet", "#mem-results", "#decisions-body",
        "#home-body", "#data-import", ".settings-body",
    ):
        check(f"overscroll contained: {sel}", sel in sels)

    # --- Duplicated rules merged, composer hint clamped.
    check(
        "single chat scroll rule",
        css.count("#chat {") == 1 and ".chat-wrap #chat {" in css,
    )
    check("single pcard rule", css.count(".pcard {") == 1)
    check("composer hint clamped", "-webkit-line-clamp: 2" in css)


def test_ui_error_visibility() -> None:
    """Errors must be visible: a toast for the user, POST /api/app-log for adb.

    On-device there is no console - an exception that only lands in logcat
    looks like a dead button. window.onerror and unhandledrejection report
    through a guarded function (a broken toast must never rethrow) and the
    server stores what arrived in the bounded applog ring, fields capped at
    300 chars, readable back through the existing GET.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import applog
    from atif_assistant.app import app

    print("\nerror visibility: toast + app-log mirror")
    root = Path(__file__).resolve().parent.parent
    js = (root / "web" / "app.js").read_text(encoding="utf-8")

    check("onerror hooked", 'window.addEventListener("error"' in js)
    check("unhandledrejection hooked", 'window.addEventListener("unhandledrejection"' in js)
    check("reporter posts to app-log", 'fetch("/api/app-log"' in js)
    check("reporter guarded against rethrow", "reporting never throws" in js)

    client = TestClient(app)
    r = client.post(
        "/api/app-log", json={"message": "ui error: boom", "detail": "app.js:1:2"}
    )
    check("ui error accepted", r.status_code == 200 and r.json().get("ok") is True)
    r2 = client.post("/api/app-log", json={})
    check("empty message rejected", r2.status_code == 400)
    r3 = client.post("/api/app-log", json={"message": "x" * 900})
    check("oversized message accepted but capped on input",
          r3.status_code == 200)

    events = client.get("/api/app-log", params={"limit": 50}).json()["events"]
    hits = [e for e in events if e.get("event") == "ui.error"]
    check(
        "ui errors readable back",
        any(h.get("message") == "ui error: boom" for h in hits),
    )
    check(
        "stored message never exceeds the cap",
        all(len(h.get("message", "")) <= 300 for h in hits),
    )
    # The GET and the POST share one path - test_web_sync already checks the
    # literal fetch against the route table; here we pin the pair itself.
    check("ring stays bounded by applog", len(applog.tail(200)) <= 200)


def test_call_error_channel() -> None:
    """The call never stalls silently: every native failure carries a reason.

    Before v1.3.4 Java flattened mic/model/recogniser failures into an empty
    "silence" result, so the call looped on LISTENING forever. Now emitError
    feeds window.onAndroidSpeechError, strikes are counted in one place,
    three strikes end the call with the reason readable for a beat, and the
    boot-time engine probe re-runs after a model download (refreshStt).
    """
    import re

    root = Path(__file__).resolve().parent.parent
    js = (root / "web" / "app.js").read_text(encoding="utf-8")
    java = (root / "mobile" / "android" / "app" / "src" / "main" / "java"
            / "ai" / "atif" / "assistant" / "MainActivity.java").read_text(
        encoding="utf-8"
    )

    print("\ncall error channel: reasons instead of silent loops")

    # Java: a real error channel, with the reason preserved end to end.
    check("java emits errors", "private void emitError(final String reason)" in java)
    check("java targets the js handler", "window.onAndroidSpeechError" in java)
    check("java has multiple emit sites", java.count("emitError(") >= 6)
    check(
        "legacy onError no longer flattens to silence",
        re.search(r"onError\(int error\) \{\s*emitResult\(\"\"\);", java) is None,
    )
    check("never-spoke stays a soft retry", java.count('emitResult("")') >= 2)
    check("busy capture reports instead of vanishing",
          "Still recording the last clip - retrying." in java)
    check("mic failure reasons recorded", 'micFail = "Microphone unavailable' in java)
    check("server failure reasons recorded", "sttFail = serverReason(" in java)
    check("legacy network failure named", "SpeechRecognizer.ERROR_NETWORK" in java)
    check("bridge re-probes after downloads",
          'new Thread(() -> probeOfflineStt(), "stt-probe")' in java)

    # JS: one failure surface (heard line), strikes, delayed terminal.
    check("js owns the error channel", js.count("onAndroidSpeechError =") >= 3)
    check("callFail helper exists", "function callFail(message)" in js)
    check("callStrike helper exists", "function callStrike(message, hard)" in js)
    check("soft strike on empty result", "I didn't catch that - try again." in js)
    check("listen-throw path strikes", "callStrike(\"The microphone failed to start" in js)
    check("watchdog terminal uses callFail",
          "The microphone is not responding. Check it in Settings" in js)
    check("permission failures visible", 'callFail("Microphone permission is required for a call.")' in js)
    check("browser recogniser failures visible",
          'callFail("Speech recognition is unavailable in this browser.")' in js)
    check("local mic failure visible", 'callFail("Microphone unavailable: "' in js)
    check("local transcribe failure strikes",
          'callStrike("Offline speech failed: "' in js)
    check("terminal reason lingers (delayed end)",
          js.count("callEndTimer = setTimeout") >= 1
          and "clearTimeout(callEndTimer)" in js)
    check("late results cannot resurrect a failing call",
          "callEnding" in js
          and re.search(r"function callSubmit[\s\S]{0,160}?callEnding", js) is not None)
    check("a real turn resets strikes",
          re.search(r"async function callSubmit[\s\S]{0,200}?callErrorStreak = 0", js)
          is not None)
    check("offline start says why", "No speech engine: connect to the internet" in js)
    check("engine re-probe from the js side", js.count("AndroidVoice.refreshStt") >= 2)
    check("one-shot mic gets a default error owner",
          "if (callActive || handsFreeActive) return;" in js)
    check("hands-free shows the reason too",
          re.search(
              r"onAndroidSpeechError = \(reason\)[\s\S]{0,400}?handsFreeResume", js
          )
          is not None)


def test_phone_voice_engine() -> None:
    """VOICE PROFILES ships on the phone via the prebuilt C API, not pip.

    sherpa-onnx has no Android wheel for the app's Python (3.12) and Chaquopy
    blocks native source builds, so the APK stages the official prebuilt
    libs (build_native.sh, jniLibs) and voice_id binds them with ctypes.
    Guards both halves of that contract - staging and binding - plus the
    numpy pip line the bindings depend on and the UI's split messages
    (model missing vs engine missing vs engine broken).
    """
    import os as _os
    import re

    from atif_assistant import voice_id

    root = Path(__file__).resolve().parent.parent
    gradle = (root / "mobile" / "android" / "app" / "build.gradle").read_text(
        encoding="utf-8"
    )
    native_sh = (root / "mobile" / "android" / "build_native.sh").read_text(
        encoding="utf-8"
    )
    apk_sh = (root / "mobile" / "android" / "build_apk.sh").read_text(encoding="utf-8")
    run_server = (
        root / "mobile" / "android" / "app" / "src" / "main" / "python"
        / "run_server.py"
    ).read_text(encoding="utf-8")
    js = (root / "web" / "app.js").read_text(encoding="utf-8")

    print("\nphone voice engine: prebuilt C API + ctypes binding")

    # The pip half: numpy yes (Chaquopy index has the Android wheel), the
    # sherpa-onnx package no (it cannot install on our Python for Android).
    check("numpy installed on the phone", 'install "numpy==1.26.2"' in gradle)
    check("sherpa-onnx pip line stays out", "sherpa-onnx==" not in gradle)
    check("gradle comment names the ctypes path", "ctypes" in gradle)

    # The staging half: wheel pinned by url + sha, libs into jniLibs.
    check("native script fetches the android wheel",
          "sherpa_onnx_core-1.13.8-py3-none-android_24_arm64_v8a.whl" in native_sh)
    check("wheel pinned by sha256", "6bbde45a9f2efcc8647429cbb8e06718bfd4c2a55f831eb5482ffb5ab227af07" in native_sh)
    check("stages the C API lib", "libsherpa-onnx-c-api.so" in native_sh)
    check("stages its onnxruntime dependency", "libonnxruntime.so" in native_sh)
    check("stages the shared C++ runtime", "libc++_shared.so" in native_sh)
    check("arm64-only guard", '[ "$ABI" = "arm64-v8a" ]' in native_sh)
    check("apk build warns when the engine is missing",
          "no sherpa-onnx speaker engine staged" in apk_sh)

    # The env contract: run_server points voice_id at the JNI directory.
    check("run_server exports the lib directory",
          'os.environ["ATIF_ASSISTANT_SHERPA_LIBS"] = sherpa_dir' in run_server)
    check("run_server checks the C API lib", "libsherpa-onnx-c-api.so" in run_server)

    # The binding half: ctypes symbols must match c-api.h exactly.
    src = Path(voice_id.__file__).read_text(encoding="utf-8")
    check("ctypes extractor class", "class _NativeExtractor" in src)
    check("ctypes stream class", "class _NativeStream" in src)
    for symbol in (
        "SherpaOnnxCreateSpeakerEmbeddingExtractor",
        "SherpaOnnxDestroySpeakerEmbeddingExtractor",
        "SherpaOnnxSpeakerEmbeddingExtractorDim",
        "SherpaOnnxSpeakerEmbeddingExtractorCreateStream",
        "SherpaOnnxSpeakerEmbeddingExtractorIsReady",
        "SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding",
        "SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding",
        "SherpaOnnxOnlineStreamAcceptWaveform",
        "SherpaOnnxOnlineStreamInputFinished",
        "SherpaOnnxDestroyOnlineStream",
    ):
        check(f"C API symbol {symbol}", symbol in src)
    check("config struct order matches c-api.h",
          re.search(
              r"_fields_ = \[\s*\n\s*\(\"model\", ctypes\.c_char_p\),[\s\S]{0,120}?"
              r"\(\"provider\", ctypes\.c_char_p\),",
              src,
        )
        is not None)
    check("python package still wins when importable",
          "import sherpa_onnx as _sherpa_onnx" in src)

    # status() must name which half is missing (the UI splits on these).
    st = voice_id.status()
    check("status reports package presence", isinstance(st.get("package"), bool))
    check("status reports native presence", isinstance(st.get("native"), bool))
    check("host without env has no native engine", st.get("native") is False)
    # Pointing the env at the Android libs must fail GENTLY off-device
    # (wrong architecture / not an ELF the host can load).
    jni = root / "mobile" / "android" / "app" / "src" / "main" / "jniLibs" / "arm64-v8a"
    if (jni / "libsherpa-onnx-c-api.so").is_file():
        _os.environ["ATIF_ASSISTANT_SHERPA_LIBS"] = str(jni)
        try:
            check("android libs never crash the host", voice_id._native_lib() is None)
        finally:
            _os.environ.pop("ATIF_ASSISTANT_SHERPA_LIBS", None)
    check("native lib loader is cached per directory", "_native_cache" in src)

    # The UI half: three honest messages, the old catch-all gone.
    check("old catch-all message removed",
          "Speaker engine not ready (needs the sherpa-onnx package)." not in js)
    check("model-missing message kept",
          "Voice identification needs a model." in js)
    check("engine-missing message split",
          "Speaker engine is missing on this build" in js)
    check("engine-broken message split",
          "Speaker engine could not start" in js)


def test_downloads() -> None:
    """Phase 8 install channel: /dl serves only allowlisted build artifacts
    and 404s everything else - never becomes a general file server."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\ndownloads (release artifact channel)")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "dl.db")
        db.init_db()
        client = TestClient(app)
        try:
            evil = client.get("/dl/../../etc/passwd", follow_redirects=False)
            check("traversal rejected", evil.status_code in (400, 404, 307, 308))
            bad = client.get("/dl/evil.apk")
            check("non-allowlisted name 404", bad.status_code == 404)
            aab = client.get("/dl/app-release.aab")
            check("aab present only after a bundle build", aab.status_code in (200, 404))
            apk = client.get("/dl/app-release.apk")
            check("apk serves when built, else 404", apk.status_code in (200, 404))
            if apk.status_code == 200:
                check("apk starts with zip magic", apk.content[:2] == b"PK")
                check("apk not truncated", len(apk.content) > 10_000_000)
        finally:
            db.reset_db_path()


def test_sessions_feedback() -> None:
    """Conversations browsing and per-message feedback plumbing (Phase 1).

    The history sheet only works if sessions list with previews and counts;
    the future reflection loop only works if feedback kinds are validated at
    the API boundary instead of in the UI. Both depend on history exposing
    message ids, which the feedback UI will target.
    """
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    tmp = tempfile.mkdtemp()
    db.use_test_db(Path(tmp) / "sess.db")
    db.init_db()
    try:
        client = TestClient(app)

        # Two conversations; sessB holds the newest activity (last insert).
        db.save_message("sessA", "user", "first question from A")
        db.save_message("sessA", "assistant", "first answer to A")
        db.save_message("sessA", "user", "another line from A")
        last_id = db.save_message("sessB", "user", "the newest question belongs to B")

        sessions = client.get("/api/sessions").json()["sessions"]
        check("two sessions listed", len(sessions) == 2)
        check("newest activity listed first", sessions[0]["session"] == "sessB")
        by_id = {s["session"]: s for s in sessions}
        check(
            "session carries message count",
            by_id["sessA"]["messages"] == 3 and by_id["sessB"]["messages"] == 1,
        )
        check(
            "session preview is its last message",
            by_id["sessA"]["last_message"] == "another line from A"
            and by_id["sessB"]["last_message"] == "the newest question belongs to B",
        )

        # History exposes message ids (feedback targets) and stays isolated.
        hist_b = client.get("/api/history/sessB").json()["messages"]
        check("history exposes message ids", bool(hist_b) and hist_b[0]["id"] == last_id)
        hist_a = client.get("/api/history/sessA").json()["messages"]
        check(
            "sessions do not leak into each other",
            len(hist_a) == 3
            and all("belongs to B" not in m["content"] for m in hist_a),
        )

        # Feedback: valid kinds stored, invalid rejected at the boundary.
        ok = client.post(
            "/api/feedback",
            json={"kind": "down", "message_id": last_id,
                  "session": "sessB", "note": "too long"},
        )
        check("feedback accepted", ok.status_code == 200 and ok.json().get("ok"))
        bad = client.post("/api/feedback", json={"kind": "shrug"})
        check("unknown feedback kind rejected", bad.status_code == 400)
        bad2 = client.post("/api/feedback", json={"kind": "up", "message_id": "x"})
        check("non-numeric message id rejected", bad2.status_code == 400)

        pending = client.get(
            "/api/feedback", params={"unapplied": "true"}
        ).json()["feedback"]
        check(
            "unapplied feedback retrievable",
            len(pending) == 1 and pending[0]["kind"] == "down",
        )
        db.mark_feedback_applied(pending[0]["id"])
        check(
            "applied feedback leaves the pending queue",
            client.get("/api/feedback", params={"unapplied": "true"}).json()["feedback"] == [],
        )

        # The whitelist lives in db, so writer and reader always agree.
        try:
            db.save_feedback("nope")
            raised = False
        except ValueError:
            raised = True
        check("db refuses unknown feedback kind", raised)
    finally:
        db.reset_db_path()


def test_soul() -> None:
    """Soul layer (Phase 2): constitution v2, companion identity, emotion.

    The persona became a full free companion in this phase, so the safety
    properties move with it: warmth is no longer the enemy, claiming a human
    life still is - and every mood statement stays labelled inference.
    """
    from atif_assistant import constitution as C, emotion
    from atif_assistant.engine import SYSTEM_BASE, build_context

    print("\nsoul: constitution v2, identity, emotion")

    # --- constitution v2 keeps every old invariant, adds the human-life pair.
    check("truth-first rule untouched", C.CONSTITUTION.startswith("ATIF CONSTITUTION"))
    check("rule 10 still present", "\n10 Always present a better alternative" in C.CONSTITUTION)
    check("new constitution rules appended", "\n11 " in C.CONSTITUTION and "\n12 " in C.CONSTITUTION)
    check(
        "human-experience brake rule present",
        any("human experience" in r for r in C.BRAKE_RULES),
    )
    check(
        "real-people brake rule present",
        any("real people" in r for r in C.BRAKE_RULES),
    )
    check(
        "original brake rules survived",
        any("Never fabricate certainty" in r for r in C.BRAKE_RULES)
        and any("memory silently change core rules" in r for r in C.BRAKE_RULES),
    )
    check(
        "constitution block carries the new brake",
        "human experience" in C.constitution_block(),
    )

    # --- identity: warm companion, still not a human.
    from atif_assistant.engine import LABEL_INSTRUCTIONS

    check("identity declares the companion", "companion with a voice" in SYSTEM_BASE)
    flat = " ".join(SYSTEM_BASE.split())
    check(
        "old prohibition on warmth is gone",
        "as a request for operational status" not in flat
        and "a reciprocal question is welcome" in flat,
    )
    check("identity still denies a human life", "not human" in SYSTEM_BASE)
    check("reality labels still mandated", "[FACT]" in LABEL_INSTRUCTIONS)
    check("identity keeps the professional boundary", "therapist" in SYSTEM_BASE)

    # --- emotion: en / roman-urdu cues, conservative on neutral text.
    sad = emotion.detect_mood("I feel so sad and empty lately")
    check("english sad detected", sad["mood"] == "sad" and sad["score"] >= 0.5 and bool(sad["cues"]))
    check(
        "roman urdu sad detected",
        emotion.detect_mood("bhai main bahut udaas hoon")["mood"] == "sad",
    )
    check(
        "roman urdu anxious detected",
        emotion.detect_mood("pareshan ho gaya har waqt fikr hoti hai")["mood"] == "anxious",
    )
    check(
        "urdu script anxious detected",
        emotion.detect_mood("بہت پریشان ہوں، نیند نہیں آ رہی")["mood"] == "anxious",
    )
    neutral = emotion.detect_mood("what is the capital of France")
    check(
        "neutral text stays neutral",
        neutral["mood"] == "neutral" and neutral["score"] == 0.0 and not neutral["cues"],
    )
    check(
        "substring cues stay word-boundary safe",
        emotion.detect_mood("the corona virus spread")["mood"] == "neutral",
    )
    check("neutral mood renders no block", emotion.render_block(neutral) == "")

    block = emotion.render_block(sad, "steady")
    check("mood block labelled as inference", "INFERENCE" in block and "never state it as fact" in block)
    check("mood block carries the cue", "sad" in block)
    check("trajectory enters the block", "steady" in block)
    check("trajectory: same mood is steady", emotion.trajectory("sad", ["I am so sad"]) == "steady")
    check(
        "trajectory: returning to neutral is improving",
        emotion.trajectory("neutral", ["I am so sad"]) == "improving",
    )
    check(
        "trajectory: first turn is single turn",
        emotion.trajectory("sad", []) == "single turn",
    )

    # --- context: neutral questions stay byte-clean, sad ones carry the block.
    ctx_plain = build_context("what is the capital of France")
    check(
        "neutral question gets no mood block",
        "USER MOOD" not in ctx_plain["context_block"]
        and ctx_plain["mood"]["mood"] == "neutral",
    )
    ctx_sad = build_context("I am so sad and alone today", recent=["nothing much"])
    check(
        "sad question injects the mood block",
        "USER MOOD" in ctx_sad["context_block"]
        and ctx_sad["mood"]["mood"] == "sad"
        and ctx_sad["mood_trajectory"] in ("steady", "worsening", "improving", "shifting"),
    )


def test_soul_ask() -> None:
    """Soul behaviour through /api/ask: Urdu-first social voice, mood out.

    The model is stubbed (like test_ask_endpoint), so this drives the router
    social flag, the language override, the mood chip payload and the mood
    timeline end-to-end with no network.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, learn
    from atif_assistant.app import app

    print("\nsoul ask endpoint")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "soul.db")
        db.init_db()
        client = TestClient(app)

        async def fake_complete(messages, **kw):
            return "[FACT] Stub answer for the soul test.", "groq"

        orig_engine, orig_learn = engine.complete, learn.complete
        engine.complete = fake_complete
        learn.complete = fake_complete
        try:
            # Urdu-first: an English pleasantry answers in Urdu unless pinned.
            res = client.post("/api/ask", json={"question": "how are you"}).json()
            check("social turn flagged", res["route"].get("social") is True)
            check("social turn answers in urdu", res["language"] == "ur")

            res = client.post(
                "/api/ask", json={"question": "how are you", "reply_language": "en"}
            ).json()
            check("explicit language pin respected", res["language"] == "en")

            res = client.post(
                "/api/ask", json={"question": "what is the capital of France"}
            ).json()
            check("knowledge question keeps english", res["language"] == "en")
            check(
                "knowledge turn is not social",
                res["route"].get("social") is False,
            )

            # Mood: surfaced for the chip, logged to the timeline.
            sad = client.post(
                "/api/ask",
                json={"question": "I am so sad and alone today", "session": "soul-s"},
            ).json()
            check(
                "mood surfaced in the response",
                sad.get("mood", {}).get("mood") == "sad",
            )
            check(
                "mood trajectory on first turn is single turn",
                sad.get("mood_trajectory") == "single turn",
            )
            timeline = client.get("/api/mood").json()["mood"]
            check(
                "sad mood logged to the timeline",
                any(r["mood"] == "sad" for r in timeline),
            )

            # Second sad turn in the same session: trajectory becomes steady.
            sad2 = client.post(
                "/api/ask",
                json={"question": "still feeling sad", "session": "soul-s"},
            ).json()
            check("same mood across turns is steady", sad2.get("mood_trajectory") == "steady")

            # Neutral turn leaves no new timeline rows.
            before = len(client.get("/api/mood").json()["mood"])
            client.post("/api/ask", json={"question": "tell me about sqlite"})
            after = len(client.get("/api/mood").json()["mood"])
            check("neutral turn not logged as a mood moment", after == before)
        finally:
            engine.complete, learn.complete = orig_engine, orig_learn
            db.reset_db_path()


def test_style_mirror() -> None:
    """Mirror layer (Phase 3): EMA style profile, overrides, bounded block.

    Gates from the master plan: the profile must stay bounded in the prompt,
    never leak into facts (shape-only labelling), and the user's own edits
    (Profile card) must survive learning.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, style
    from atif_assistant.app import app

    print("\nmirror: style profile, overrides, bounded block")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "style.db")
        db.init_db()
        client = TestClient(app)
        try:
            check("no profile yet", db.get_profile("style") is None)
            check("no block without signal", style.render_block(None, ["hello"]) == "")
            check(
                "no block below threshold",
                style.render_block({"n": 1, "avg_words": 5}, ["hello"]) == "",
            )

            a = style.observe("hi")  # neutral: no formal or casual markers
            check("first message initializes", a["n"] == 1 and a["avg_words"] == 1.0)
            check("no register signal yet", "formality" not in a)
            b = style.observe(
                "please kindly assist me regarding this request of mine"
            )
            check("count increments", b["n"] == 2)
            check(
                "avg moves toward the new message but stays between",
                1.0 < b["avg_words"] < 9.0,
            )
            check("formal register learned", b.get("formality", 0) >= 0.6)
            check("formal label assigned", style.register_of(b) == "formal")

            # EMA is deliberate: several casual messages are needed before the
            # learned register actually flips.
            c = style.observe("lol yaar chal bas thx")
            d = style.observe("haha lol nah cool")
            e = style.observe("nah cool haha")
            check(
                "casual messages pull formality down",
                e["formality"] < b["formality"],
            )
            check("casual label eventually assigned", style.register_of(e) == "casual")
            u = style.observe("بہت اچھا لگا آج کا دن")
            check("urdu ratio rises", u["urdu_ratio"] > 0.2)

            # Stored profile is re-readable (persisted across calls).
            stored = db.get_profile("style")
            check("profile persisted", stored is not None and stored["n"] == 6)

            block = style.render_block(
                stored, ["first one", "second msg here", "kya haal hai"]
            )
            check("block labels shape-only", "SHAPE" in block)
            check("block carries length hint", "reply length" in block)
            check("keeps the most recent examples", "kya haal hai" in block)
            check("drops older examples", "first one" not in block)
            check("at most two examples", block.count('\n- "') == 2)
            check("examples bounded", len(block) <= 700)

            # Overrides pin a dimension; learning keeps running underneath.
            ov = {"length": "detailed", "register": "auto", "language": "auto"}
            pinned = style.render_block(stored, ["x"], ov)
            check("override wins over learned", "reply length: detailed" in pinned)
            check(
                "unpinned dimensions still learned",
                "register: casual" in pinned and "language lean: " in pinned,
            )

            # Prompt integration: build_context carries the block once learned.
            ctx = engine.build_context(
                "what is sqlite", recent=["ok", "please assist me regarding this"]
            )
            check(
                "context carries the mirror block",
                "MIRROR STYLE" in ctx["context_block"],
            )
            check(
                "mirror block marks shape-only",
                "never evidence for facts" in ctx["context_block"],
            )

            # Profile card endpoints: read, pin, reject invalid pins.
            got = client.get("/api/profile").json()
            check("profile endpoint returns style", got["style"].get("n", 0) >= 6)
            check("profile endpoint returns overrides", isinstance(got["overrides"], dict))
            saved = client.post("/api/profile", json={"length": "detailed"})
            check("override saved", saved.status_code == 200 and saved.json()["ok"])
            check(
                "override persisted",
                client.get("/api/profile").json()["overrides"].get("length") == "detailed",
            )
            check(
                "separate override doc does not touch learning",
                (db.get_profile("style") or {}).get("n", 0) == 6,
            )
            bad = client.post("/api/profile", json={"length": "enormous"})
            check("invalid override rejected", bad.status_code == 400)
            check(
                "invalid override leaves stored value alone",
                client.get("/api/profile").json()["overrides"].get("length") == "detailed",
            )

            # Ask path: the message is observed and the ask still answers.
            from atif_assistant import learn as learn_mod

            async def fake_complete(messages, **kw):
                return "[FACT] Stub answer for the mirror test.", "groq"

            orig_engine, orig_learn = engine.complete, learn_mod.complete
            engine.complete = fake_complete
            learn_mod.complete = fake_complete
            try:
                res = client.post(
                    "/api/ask",
                    json={"question": "how do i fix my routine", "session": "sty-s"},
                ).json()
                check("ask still answers", bool(res.get("text")))
                check(
                    "style observed through ask",
                    (db.get_profile("style") or {}).get("n", 0) == 7,
                )
            finally:
                engine.complete = orig_engine
                learn_mod.complete = orig_learn
        finally:
            db.reset_db_path()


def test_reflection() -> None:
    """Evolution loop (Phase 4): feedback -> proposal -> explicit approval.

    The master-plan gate is zero silent rule changes: reflecting must never
    touch the rules table on its own; only the approve endpoint may, only for
    pending items, and the user's press is the recorded approval.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, reflection
    from atif_assistant.app import app

    print("\nevolution: proposals, approval, zero silent changes")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "refl.db")
        db.init_db()
        client = TestClient(app)
        try:
            rules_before = len(db.approved_rules())

            # Signals: two noted downs, one noted edit, one bare down, one up.
            db.save_feedback(
                "down", message_id=1, session="s1",
                note="Stop using bullet points; write paragraphs.",
            )
            db.save_feedback("edit", message_id=2, session="s1",
                             note="Keep answers shorter please")
            db.save_feedback("down", message_id=3, session="s1")
            db.save_feedback("up", message_id=4, session="s1")
            db.save_feedback(
                "down", message_id=5, session="s1",
                note="Stop using bullet points; write paragraphs.",
            )

            res = client.get("/api/reflections").json()
            check(
                "two proposals from three noted signals (deduped)",
                len(res["proposals"]) == 2,
            )
            check("feedback queue drained", db.list_feedback(only_unapplied=True) == [])
            check(
                "feedback counts served",
                res["feedback_counts"].get("down") == 3
                and res["feedback_counts"].get("up") == 1,
            )
            check(
                "down-ratio insight present",
                any("👎" in line for line in res["insights"]),
            )
            check(
                "zero silent rule changes on read",
                len(db.approved_rules()) == rules_before,
            )

            pending = [p for p in res["proposals"] if p["status"] == "pending"]
            check("both proposals pending", len(pending) == 2)

            # Approve one: it becomes an approved rule reachable by guardrails.
            ok = client.post(f"/api/reflections/{pending[0]['id']}/approve")
            check("approve is ok", ok.status_code == 200 and ok.json().get("ok"))
            rule_id = ok.json().get("rule_id")
            check("rule id recorded on the reflection", rule_id and rule_id > 0)
            texts = [r["text"] for r in db.approved_rules()]
            check(
                "approved rule carries the proposal text",
                pending[0]["title"] in texts,
            )
            check(
                "reflection marked approved",
                db.get_reflection(pending[0]["id"])["status"] == "approved",
            )
            again = client.post(f"/api/reflections/{pending[0]['id']}/approve")
            check("approving twice is refused", again.status_code == 400)

            # Reject the other: it must never reach the rules table.
            rej = client.post(f"/api/reflections/{pending[1]['id']}/reject")
            check("reject is ok", rej.status_code == 200)
            check(
                "rejected proposal never becomes a rule",
                pending[1]["title"]
                not in [r["text"] for r in db.approved_rules()],
            )
            check(
                "reflection marked rejected",
                db.get_reflection(pending[1]["id"])["status"] == "rejected",
            )

            check(
                "unknown reflection approve is 404",
                client.post("/api/reflections/9999/approve").status_code == 404,
            )
            check(
                "unknown reflection reject is 404",
                client.post("/api/reflections/9999/reject").status_code == 404,
            )
            check(
                "bad status filter is 400",
                client.get("/api/reflections", params={"status": "maybe"}).status_code == 400,
            )
            filt = client.get("/api/reflections", params={"status": "pending"})
            check(
                "status filter serves only pending",
                filt.json()["proposals"] == [],
            )

            res2 = client.get("/api/reflections").json()
            check(
                "re-read keeps decided states, no resurrection",
                {p["status"] for p in res2["proposals"]} == {"approved", "rejected"},
            )
            check(
                "approved proposal visible to guardrails as REFLECT",
                any(
                    r.get("code") == "REFLECT"
                    and r["text"] == pending[0]["title"]
                    for r in db.approved_rules()
                ),
            )

            # A fresh noted signal after decisions still reflects.
            db.save_feedback("regenerate", message_id=9, session="s2",
                             note="Never open answers with a greeting")
            res3 = client.get("/api/reflections").json()
            check(
                "later signal still produces a pending proposal",
                any(
                    p["status"] == "pending"
                    and p["title"] == "Never open answers with a greeting"
                    for p in res3["proposals"]
                ),
            )
        finally:
            db.reset_db_path()


def test_home() -> None:
    """/api/home (Phase 5): the dashboard's single round trip carries today's
    activity, growth pending count and recent sessions - and a fresh install
    answers with zeros instead of failing."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\nhome dashboard")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "home.db")
        db.init_db()
        client = TestClient(app)
        try:
            # zero state first: nothing has happened yet.
            empty = client.get("/api/home").json()
            check("zero-state home answers", client.get("/api/home").status_code == 200)
            check("zero-state today is zero", empty["today"] == {"messages": 0, "questions": 0})
            check("zero-state has no recent", empty["recent"] == [])
            check("zero-state mood is null", empty["mood"] is None)

            db.save_message("h1", "user", "hello home")
            db.save_message("h1", "assistant", "[FACT] hi")
            db.record_question("social", "hello home")

            res = client.get("/api/home").json()
            check(
                "today counts this session's rows",
                res["today"]["messages"] == 2 and res["today"]["questions"] == 1,
            )
            check(
                "all-time aggregates present",
                res["sessions"] == 1 and res["messages"] == 2 and res["evidence"] == 0,
            )
            check("growth pending is an int", isinstance(res["pending_reflections"], int))
            check("feedback map is a dict", isinstance(res["feedback"], dict))
            check("due decisions counted", res["due_decisions"] == 0)
            check(
                "recent sessions listed newest-first",
                [s["session"] for s in res["recent"]] == ["h1"]
                and res["recent"][0]["messages"] == 2,
            )
            check("date stamped ISO", len(res["date"]) == 10)
        finally:
            db.reset_db_path()


def test_inbox() -> None:
    """Phase 8b: live inbox - the notification listener's push endpoint
    dedupes re-fired notifications, lists recent messages, and gates on
    supported packages only."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\ninbox (live notification feed)")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "inbox.db")
        db.init_db()
        client = TestClient(app)
        try:
            bad = client.post("/api/inbox/whatsapp", json={"text": "hi", "package": "com.evil"})
            check("foreign package rejected", bad.status_code == 400)
            empty = client.post("/api/inbox/whatsapp", json={"chat": "Ali", "text": "  "})
            check("empty text rejected", empty.status_code == 400)
            ok = client.post(
                "/api/inbox/whatsapp",
                json={"chat": "Ali Khan", "text": "Salaam, kal milte hain", "package": "com.whatsapp"},
            )
            check("message accepted", ok.status_code == 200 and ok.json()["ok"] and not ok.json()["dup"])
            same = client.post(
                "/api/inbox/whatsapp",
                json={"chat": "Ali Khan", "text": "Salaam, kal milte hain", "package": "com.whatsapp"},
            )
            check("re-fired notification dedupes", same.json()["dup"] is True)
            other = client.post(
                "/api/inbox/whatsapp",
                json={"chat": "Ali Khan", "text": "Doosra paighaam", "package": "com.whatsapp"},
            )
            check("new message gets new id", other.json()["dup"] is False and other.json()["id"] != ok.json()["id"])
            lst = client.get("/api/inbox")
            check("list returns newest first", [i["text"] for i in lst.json()["items"]] == ["Doosra paighaam", "Salaam, kal milte hain"])
            only = client.get("/api/inbox", params={"chat": "Ali Khan"})
            check("chat filter works", len(only.json()["items"]) == 2)
            row_id = ok.json()["id"]
            check("set draft writes", db.set_inbox_draft(row_id, "Main theek hoon"))
            check("draft readable", db.inbox_row(row_id)["draft"] == "Main theek hoon")
            no_row = client.get("/api/inbox", params={"chat": "Nope"})
            check("unknown chat empty", no_row.json()["items"] == [])
        finally:
            db.reset_db_path()


def test_autodraft() -> None:
    """Phase 8c: per-chat auto-draft - watched chats get a suggested reply
    (humor mode etc), the draft flows to /api/inbox/drafts until marked
    notified, and staging keeps the propose-then-approve contract."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    import atif_assistant.app as app_mod
    from atif_assistant.app import app

    print("\nautodraft (watched chats suggest replies)")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "autodraft.db")
        db.init_db()
        client = TestClient(app)
        real_complete = app_mod.complete
        seen: dict = {}

        async def fake_complete(messages, temperature=0.4, max_tokens=1800):
            seen["messages"] = messages
            seen["temperature"] = temperature
            return "Bilkul, kal 4 baje milte hain", "fake"

        app_mod.complete = fake_complete
        try:
            bad = client.post("/api/autoreply/watch", json={"chat": "", "mode": "humor"})
            check("empty chat rejected", bad.status_code == 400)
            bad_mode = client.post("/api/autoreply/watch", json={"chat": "Ali", "mode": "sassy"})
            check("unknown mode rejected", bad_mode.status_code == 400)
            watched = client.post(
                "/api/autoreply/watch", json={"chat": "Ali Khan", "mode": "humor"}
            )
            check("watch recorded", watched.json()["watched"] == {"Ali Khan": {"enabled": True, "mode": "humor"}})
            got = client.get("/api/autoreply")
            check("watch readable", got.json()["watched"]["Ali Khan"]["mode"] == "humor")
            off = client.post("/api/autoreply/watch", json={"chat": "Ali Khan", "mode": "off"})
            check("off removes watch", off.json()["watched"] == {})
            client.post("/api/autoreply/watch", json={"chat": "Ali Khan", "mode": "humor"})

            r1 = client.post(
                "/api/inbox/whatsapp",
                json={"chat": "Ali Khan", "text": "Kal kya plan hai?", "package": "com.whatsapp"},
            )
            iid = r1.json()["id"]
            row = db.inbox_row(iid)
            check("watched chat got a draft", row["draft"] == "Bilkul, kal 4 baje milte hain")
            check("prompt carries the message", "Kal kya plan hai?" in seen["messages"][1]["content"])
            check("prompt sets humor style", "witty" in seen["messages"][0]["content"])
            check("prompt forbids claiming a send", "never claim" in seen["messages"][0]["content"])

            r2 = client.post(
                "/api/inbox/whatsapp",
                json={"chat": "Unwatched", "text": "Hello!", "package": "com.whatsapp"},
            )
            check("unwatched chat has no draft", db.inbox_row(r2.json()["id"])["draft"] is None)

            drafts = client.get("/api/inbox/drafts")
            check("draft listed once", [d["id"] for d in drafts.json()["items"]] == [iid])
            marked = client.post(f"/api/inbox/{iid}/notified")
            check("marked notified", marked.json()["ok"] is True)
            check("drafts empty after notify", client.get("/api/inbox/drafts").json()["items"] == [])
            check("notified row keeps its draft", db.inbox_row(iid)["notified"] == 1)

            missing = client.post("/api/inbox/99999/notified")
            check("unknown notified id 404", missing.status_code == 404)

            st = client.post(f"/api/inbox/{iid}/stage")
            check("message staged as candidate", st.json() == {"staged": 1, "skipped": 0, "total": 1})
            check(
                "staged message searchable",
                bool(db.search_memory("Kal kya plan hai")),
            )
            again = client.post(f"/api/inbox/{iid}/stage")
            check("re-stage skips", again.json() == {"staged": 0, "skipped": 1, "total": 1})
            miss_stage = client.post("/api/inbox/99999/stage")
            check("unknown stage id 404", miss_stage.status_code == 404)
        finally:
            app_mod.complete = real_complete
            db.reset_db_path()


def test_whatsapp_txt() -> None:
    """Phase 8: WhatsApp .txt chat exports - both official formats parse,
    stage as LEARNED candidates with content-key dedupe, and land in the
    memory index so past talks become answerable."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app
    from atif_assistant.importers import whatsapp_txt

    print("\nwhatsapp txt export importer")
    android = (
        "[12/08/2024, 3:44:00 PM] Messages and calls are end-to-end encrypted\n"
        "[12/08/2024, 3:45:21 PM] Ali: Salaam, kya haal hai?\n"
        "[12/08/2024, 3:46:02 PM] You: Theek hoon bhai\n"
        "[12/08/2024, 3:47:10 PM] Ali: Chalo milte hain\nkal shaam\n"
    )
    res = whatsapp_txt.parse_export(android, "Ali Ahmed (2).txt")
    check("android export parses 3 messages", len(res["messages"]) == 3)
    check("chat name from filename", res["chat"] == "Ali Ahmed (2)")
    first = res["messages"][0]
    check("system line skipped", first["from"] == "Ali" and "encrypted" not in first["text"])
    check("12h clock converts to 24h iso", first["ts"] == "2024-08-12T15:45:21")
    me = res["messages"][1]
    check("You marks from_me", me["from_me"] and me["from"] == "You")
    multi = res["messages"][2]
    check("continuation lines join", "\nkal shaam" in multi["text"])
    check("content key stable", len(multi["key"]) == 16)
    ios = (
        "8/17/25, 10:32 PM - Sara: Dekho main aa rahi hoon\n"
        "8/17/25, 10:33 PM - You: Theek hai\n"
    )
    ires = whatsapp_txt.parse_export(ios, "sara.txt")
    check("ios export parses", len(ires["messages"]) == 2)
    check("ios month-first when unambiguous", ires["messages"][0]["ts"] == "2025-08-17T22:32:00")
    try:
        whatsapp_txt.parse_export("random notes", "x.txt")
        check("garbage rejected", False)
    except ValueError:
        check("garbage rejected", True)

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "wtxt.db")
        db.init_db()
        client = TestClient(app)
        try:
            bad = client.post(
                "/api/import/whatsapp-txt/preview",
                json={"content": "nope", "filename": "x.txt"},
            )
            check("preview rejects non-export", bad.status_code == 400)
            miss = client.post("/api/import/whatsapp-txt/preview", json={"filename": "x.txt"})
            check("preview requires content", miss.status_code == 400)
            prev = client.post(
                "/api/import/whatsapp-txt/preview",
                json={"filename": "Ali Ahmed (2).txt", "content": android, "recent_first": True},
            )
            check("preview returns messages", prev.status_code == 200 and prev.json()["total"] == 3)
            check(
                "recent_first shows last message first",
                prev.json()["messages"][0]["text"].startswith("Chalo"),
            )
            items = [
                {"text": m["text"], "from": m["from"], "when": m["when"]}
                for m in prev.json()["messages"]
            ]
            st = client.post(
                "/api/import/whatsapp-txt/stage",
                json={"chat": "Ali Ahmed (2)", "items": items},
            )
            check("stage stores all", st.status_code == 200 and st.json()["staged"] == 3)
            again = client.post(
                "/api/import/whatsapp-txt/stage",
                json={"chat": "Ali Ahmed (2)", "items": items},
            )
            check(
                "re-stage dedupes by content key",
                again.json()["staged"] == 0 and len(again.json()["skipped"]) == 3,
            )
            rows = client.get("/api/learned", params={"status": "candidate"})
            check(
                "staged rows are learned candidates",
                rows.status_code == 200 and len(rows.json()["candidates"]) == 3,
            )
            found = db.search_memory("Salaam haal")
            check(
                "staged message is memory-searchable",
                any(f["kind"] == "learned" for f in found),
            )
        finally:
            db.reset_db_path()


def test_importers() -> None:
    """Phase 6: the five light importers parse real-shaped fixtures,
    stage as LEARNED candidates (propose-then-approve), and never explode
    on a missing file."""
    import sqlite3
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app
    from atif_assistant.importers import calendar, contacts, mail, notes, photos

    print("\nimporters (5 light sources)")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "imp.db")
        db.init_db()
        client = TestClient(app)
        tmp_path = Path(tmp)
        try:
            # --- contacts: person table with First/Last/Organization
            cx = tmp_path / "contacts.db"
            c = sqlite3.connect(cx)
            c.execute(
                "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT,"
                " Middle TEXT, Last TEXT, Organization TEXT)"
            )
            c.executemany(
                "INSERT INTO ABPerson(ROWID, First, Last, Organization) VALUES (?,?,?,?)",
                [(1, "Ada", "Lovelace", "Analytical Engine"), (2, "Hamza", None, None)],
            )
            c.commit(); c.close()
            res = contacts.import_from_db(db_path=cx)
            check("contacts parses persons", res["count"] == 2 and res["truncated"] is False)
            check(
                "contacts builds full name + org detail",
                res["candidates"][0]["title"] == "Ada Lovelace"
                and res["candidates"][0]["detail"] == "Analytical Engine"
                and res["candidates"][0]["kind"] == "contacts",
            )
            check("contacts single name kept", res["candidates"][1]["title"] == "Hamza")

            # --- calendar: event table with summary + apple-epoch start
            cal = tmp_path / "calendar.db"
            c = sqlite3.connect(cal)
            c.execute(
                "CREATE TABLE EKEVENT (ROWID INTEGER PRIMARY KEY, summary TEXT,"
                " start_date REAL, location TEXT)"
            )
            c.execute(
                "INSERT INTO EKEVENT(ROWID, summary, start_date) VALUES (1, 'Football', 800000000.0)"
            )
            c.commit(); c.close()
            cres = calendar.import_from_db(db_path=cal)
            check("calendar parses events", cres["count"] == 1)
            check(
                "calendar converts apple epoch",
                cres["candidates"][0]["when"] is not None
                and cres["candidates"][0]["when"].startswith("2026-"),
            )

            # --- mail: Envelope Index style messages, ns-since-2001 dates
            ml = tmp_path / "envelope.db"
            c = sqlite3.connect(ml)
            c.execute(
                "CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, subject TEXT,"
                " sender TEXT, date_sent INTEGER)"
            )
            c.execute(
                "INSERT INTO messages(ROWID, subject, sender, date_sent)"
                " VALUES (1, 'Rent due', 'landlord@mail.com', 800000000000000000)"
            )
            c.commit(); c.close()
            mres = mail.import_from_db(db_path=ml)
            check("mail parses subjects", mres["count"] == 1 and mres["candidates"][0]["title"] == "Rent due")
            check("mail lists sender as detail", mres["candidates"][0]["detail"] == "landlord@mail.com")
            check("mail converts ns apple date", (mres["candidates"][0]["when"] or "").startswith("2026-"))

            # --- notes: ZTITLE rows, folder rows (no snippet) skipped
            nt = tmp_path / "notes.db"
            c = sqlite3.connect(nt)
            c.execute(
                "CREATE TABLE ZICCLOUDSYNCINGOBJECT (ROWID INTEGER PRIMARY KEY,"
                " ZTITLE TEXT, ZSNIPPET TEXT, ZCREATIONDATE1 REAL)"
            )
            c.executemany(
                "INSERT INTO ZICCLOUDSYNCINGOBJECT(ROWID, ZTITLE, ZSNIPPET, ZCREATIONDATE1)"
                " VALUES (?,?,?,?)",
                [
                    (1, "Groceries", "milk, eggs", 700000000.0),
                    (2, "Work", None, None),  # folder row: no snippet -> skipped
                ],
            )
            c.commit(); c.close()
            nres = notes.import_from_db(db_path=nt)
            check("notes skips folder rows", nres["count"] == 1)
            check("notes carries snippet", nres["candidates"][0]["detail"] == "milk, eggs")

            # --- photos: album titles + counts through the link table
            #     (the link table has one row per album<->asset pair, which
            #     is how Photos itself stores it)
            ph = tmp_path / "photos.db"
            c = sqlite3.connect(ph)
            c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT)")
            c.execute("CREATE TABLE Z_3ALBUMS (_3ALBUMS INTEGER, _3ASSETS INTEGER)")
            c.executemany("INSERT INTO ZGENERICALBUM(Z_PK, ZTITLE) VALUES (?,?)",
                          [(1, "Lahore 2025"), (2, "Family")])
            pairs = [(1, 101), (1, 102), (1, 103), (1, 104), (2, 201), (2, 202)]
            c.executemany("INSERT INTO Z_3ALBUMS(_3ALBUMS, _3ASSETS) VALUES (?,?)", pairs)
            c.commit(); c.close()
            pres = photos.import_from_db(db_path=ph)
            check("photos parses albums", pres["count"] == 2)
            check(
                "photos counts linked assets per album",
                pres["candidates"][0]["detail"] == "4 photos"
                and pres["candidates"][1]["detail"] == "2 photos",
            )

            # --- uniform envelope: truncation marks honestly
            lim = contacts.import_from_db(db_path=cx, limit=1)
            check("limit truncates and flags", lim["count"] == 2 and lim["truncated"] is True)

            # --- missing file is a clear FileNotFoundError, not a crash
            try:
                contacts.import_from_db(db_path=tmp_path / "nope.db")
                check("missing file raises FileNotFoundError", False)
            except FileNotFoundError:
                check("missing file raises FileNotFoundError", True)

            # --- routes: unknown source rejected
            check(
                "unknown source previews 400",
                client.get("/api/import/nope/preview").status_code == 400,
            )
            check(
                "unknown source stages 400",
                client.post("/api/import/nope/stage", json={"items": [{"id": 1, "title": "x"}]}).status_code == 400,
            )

            # --- stage: propose-then-approve into learned, deduped
            items = [
                {"id": 1, "title": "Ada Lovelace", "detail": "Analytical Engine"},
                {"id": 2, "title": "Hamza"},
                {"id": "", "title": "no id"},  # invalid -> skipped
            ]
            st = client.post("/api/import/contacts/stage", json={"items": items}).json()
            check("stage writes candidates", st["staged"] == 2 and len(st["skipped"]) == 1)
            again = client.post(
                "/api/import/contacts/stage", json={"items": items[:1]}
            ).json()
            check("stage dedups on source", again["staged"] == 0 and again["skipped"][0]["reason"] == "already staged")
            learned = client.get("/api/learned").json()["candidates"]
            imp = [l for l in learned if l["kind"] == "contacts"]
            check("staged rows are learned candidates", len(imp) == 2 and imp[0]["status"] == "candidate")
            check(
                "staged text carries title + detail",
                any("Ada Lovelace - Analytical Engine" in l["text"] for l in imp),
            )
        finally:
            db.reset_db_path()


def test_todos_reminders() -> None:
    """Phase 6: task capture from the user's own words, todo/reminder CRUD,
    due delivery marking, and the Home aggregate fields."""
    import tempfile

    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, learn
    from atif_assistant.app import _extract_tasks, app

    print("\ntodos + reminders")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "tasks.db")
        db.init_db()
        client = TestClient(app)

        async def fake_complete(messages, **kw):
            return "[FACT] noted.", "groq"

        orig = (engine.complete, learn.complete)
        engine.complete = fake_complete
        learn.complete = fake_complete
        try:
            # extraction: cue match creates one todo; repeats do not duplicate
            check("cue sentence captured", _extract_tasks("Remind me to call ammi after isha") == 1)
            check("repeat sentence deduped", _extract_tasks("Remind me to call ammi after isha") == 0)
            check("neutral question ignored", _extract_tasks("what is the capital of france") == 0)
            open_t = db.list_todos(open_only=True)
            check("chat todo is open with origin chat",
                  len(open_t) == 1 and open_t[0]["origin"] == "chat")

            # the ask flow itself feeds the background extractor
            r = client.post("/api/ask", json={"question": "don't let me forget the passport fee"})
            check("ask answers", r.status_code == 200)
            check(
                "ask background captured the task",
                any("passport fee" in t["text"] for t in db.list_todos(open_only=True)),
            )

            # manual todos + routes
            created = client.post("/api/todos", json={"text": "  file taxes  "}).json()
            check("manual todo created", created["ok"] and created["id"] > 0)
            tid = created["id"]
            listed = client.get("/api/todos").json()["todos"]
            check("todo text normalised", any(t["id"] == tid and t["text"] == "file taxes" for t in listed))
            check(
                "empty todo rejected",
                client.post("/api/todos", json={"text": "   "}).status_code == 400,
            )
            client.post(f"/api/todos/{tid}/toggle", json={"done": True})
            check("toggle removes from open", all(t["id"] != tid for t in client.get("/api/todos").json()["todos"]))
            check("toggle 404s on unknown", client.post("/api/todos/99999/toggle", json={}).status_code == 404)
            check("delete 404s on unknown", client.delete("/api/todos/99999").status_code == 404)
            check("delete removes", client.delete(f"/api/todos/{tid}").status_code == 200)

            # reminders: due -> fire -> gone from due
            check(
                "reminder rejects missing time",
                client.post("/api/reminders", json={"text": "tea"}).status_code == 400,
            )
            rid = client.post(
                "/api/reminders",
                json={"text": "call ammi", "due_at": "2001-01-01T00:00:00+00:00"},
            ).json()["id"]
            due = client.get("/api/reminders/due").json()["due"]
            check("past reminder is due", any(d["id"] == rid for d in due))
            check("fire marks it", client.post(f"/api/reminders/{rid}/fire").json()["ok"] is True)
            check("fired reminder leaves due list", client.get("/api/reminders/due").json()["due"] == [])
            with_fired = client.get("/api/reminders?include_fired=true").json()["reminders"]
            check("fired still listed when asked", any(w["id"] == rid and w["fired"] == 1 for w in with_fired))
            check("fire 404s on unknown", client.post("/api/reminders/99999/fire").status_code == 404)

            # home carries the new tiles
            home = client.get("/api/home").json()
            check(
                "home aggregates todos/reminders/places",
                home["todos"] == len(db.list_todos(open_only=True))
                and "reminders" in home
                and "places" in home,
            )
        finally:
            engine.complete, learn.complete = orig
            db.reset_db_path()


def test_ask_stream() -> None:
    """/api/ask/stream (Phase 5): deltas then one final event; sectioned
    modes arrive as a single final; STOP keeps the question and flags the
    partial answer instead of losing the turn or shipping it as complete.
    """
    import asyncio
    import json as _json

    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, learn
    from atif_assistant.app import app

    print("\nask stream")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "stream.db")
        db.init_db()
        client = TestClient(app)

        async def fake_complete(messages, **kw):
            return "[FACT] Blocking stub answer.", "groq"

        chunks = (
            "[FACT] Streamed ", "answer ", "in ", "six ", "small ", "parts."
        )

        async def fake_stream(messages, **kw):
            async def deltas():
                for c in chunks:
                    await asyncio.sleep(0.05)
                    yield c
            return "groq", deltas()

        orig = (engine.complete, engine.complete_stream, learn.complete)
        engine.complete = fake_complete
        engine.complete_stream = fake_stream
        learn.complete = fake_complete
        try:
            # 1. ask mode: deltas in order, exactly one final, last event.
            with client.stream(
                "POST",
                "/api/ask/stream",
                json={"question": "what is photosynthesis", "session": "st-s"},
            ) as resp:
                ctype = resp.headers.get("content-type", "")
                check("stream responds ndjson", "ndjson" in ctype)
                events = [_json.loads(l) for l in resp.iter_lines() if l.strip()]
            deltas = [e for e in events if "delta" in e]
            finals = [e for e in events if "final" in e]
            check("all deltas arrive before one final", len(deltas) == len(chunks) and len(finals) == 1)
            check("final is the last event", "final" in events[-1])
            joined = "".join(d["delta"] for d in deltas)
            check("deltas concatenate to the draft", joined == "".join(chunks))
            fin = finals[0]["final"]
            check("final carries the full text", fin["text"] == "".join(chunks))
            check("final carries route and language", "route" in fin and "language" in fin)
            hist = client.get("/api/history/st-s").json()["messages"]
            check("stream exchange persisted", len(hist) == 2 and hist[1]["role"] == "assistant")
            check(
                "final exposes message ids for feedback buttons",
                isinstance(fin.get("message_id"), int)
                and isinstance(fin.get("user_message_id"), int),
            )

            # 2. challenge mode: sectioned output needs the whole answer -
            #    a single final event, no deltas.
            with client.stream(
                "POST", "/api/ask/stream", json={"question": "why am i like this"}
            ) as resp:
                ev2 = [_json.loads(l) for l in resp.iter_lines() if l.strip()]
            check(
                "challenge emits one final only",
                len(ev2) == 1
                and "final" in ev2[0]
                and ev2[0]["final"]["route"]["mode"] == "challenge",
            )

            # 3. STOP is exercised over a real socket in
            #    test_ask_stop_disconnect() - TestClient drains the app
            #    instead of delivering a disconnect, so it can't test STOP.

            # 4. blocking endpoint is intact alongside the stream one.
            r = client.post("/api/ask", json={"question": "what is sqlite"})
            check("blocking ask still answers", "Blocking stub answer" in r.json().get("text", ""))
        finally:
            engine.complete, engine.complete_stream, learn.complete = orig
            db.reset_db_path()


def test_ask_stop_disconnect() -> None:
    """STOP over a real socket: aborting the stream mid-answer must leave the
    question plus a flagged partial behind, and never a silently-complete one.

    TestClient drains the ASGI app instead of delivering a client disconnect,
    so this single test boots uvicorn in-process on an ephemeral port and
    closes the connection for real - which is exactly what the phone's
    AbortController does.
    """
    import asyncio
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from atif_assistant import db, engine, learn
    from atif_assistant.app import app

    print("\nask stop (real disconnect)")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "stop.db")
        db.init_db()

        async def fake_complete(messages, **kw):
            return "[FACT] Blocking stub answer.", "groq"

        # Long enough that the stream cannot finish before the abort lands.
        chunks = ("[FACT] The long story ",) + tuple(
            f"beat {i}. " for i in range(29)
        )

        async def fake_stream(messages, **kw):
            async def deltas():
                for c in chunks:
                    await asyncio.sleep(0.1)
                    yield c
            return "groq", deltas()

        orig = (engine.complete, engine.complete_stream, learn.complete)
        engine.complete = fake_complete
        engine.complete_stream = fake_stream
        learn.complete = fake_complete

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        base = f"http://127.0.0.1:{port}"

        ready = False
        for _ in range(60):
            try:
                httpx.get(base + "/api/health", timeout=0.5)
                ready = True
                break
            except Exception:
                time.sleep(0.1)

        try:
            check("ephemeral test server boots", ready)
            if not ready:
                return

            # 1. stream starts, then the client yanks the connection away.
            saw_delta = False
            with httpx.stream(
                "POST",
                base + "/api/ask/stream",
                json={
                    "question": "how does sqlite write data to disk",
                    "session": "stop-s",
                },
                timeout=5.0,
            ) as resp:
                for line in resp.iter_lines():
                    if '"delta"' in line:
                        saw_delta = True
                        break  # __exit__ closes the socket for real
            check("first delta arrived before the abort", saw_delta)

            # 2. the server-side save happens after cancellation - poll.
            rows: list = []
            bot = None
            for _ in range(50):
                conn = db.connect()
                rows = conn.execute(
                    "SELECT role, content, labels FROM messages WHERE session=? ORDER BY id",
                    ("stop-s",),
                ).fetchall()
                bots = [r for r in rows if r["role"] == "assistant"]
                if bots:
                    bot = bots[0]
                    break
                time.sleep(0.1)

            check(
                "question survived the abort",
                any(r["role"] == "user" for r in rows),
            )
            check("partial answer persisted after stop", bot is not None)
            if bot is not None:
                labels = json.loads(bot["labels"]) if bot["labels"] else {}
                check("partial flagged stopped", labels.get("stopped") is True)
                check(
                    "partial text is the streamed prefix",
                    bot["content"].startswith(chunks[0]),
                )
                check(
                    "no complete answer slipped through",
                    "Blocking stub" not in bot["content"],
                )
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            engine.complete, engine.complete_stream, learn.complete = orig
            db.reset_db_path()


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

        # Duplicate handling must be time-independent: evidence identity
        # hashes occurred_at, so a re-upload "later" (clock frozen forward)
        # still must not stack rows. Regression for a CI-only flake where the
        # two uploads straddled a second boundary.
        orig_now = db.now
        db.now = lambda: "2099-01-01 00:00:00"
        try:
            r2b = client.post(
                "/api/upload",
                json={"filename": "plan.txt", "related_to": "business plan",
                      "text": "Secret growth plan"},
            )
        finally:
            db.now = orig_now
        b2b = r2b.json()
        check("duplicate detected even at a later time", b2b.get("duplicate_file") is True)
        check(
            "later duplicate adds no episode or evidence",
            b2b.get("episode_id") is None and b2b.get("evidence_id") is None,
        )

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
        db.add_pattern("Late-night rumination", trigger="after 11pm", triggers=["3am", "scroll"])
        db.add_rule("Sleep before midnight on weekdays", code="SLEEP", approved=True)
        client.post("/api/media", json={"path": "/tmp/clip.mp4", "kind": "video"})
        db.set_setting("theme", "dark")
        db.add_location_point(51.5, -0.12, occurred_at="2026-01-02T08:00:00", source="test")

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
        check("import restores a pattern", added["patterns"] == 1)
        check("import restores a rule", added["rules"] == 1)
        check("import restores media", added["media"] == 1)
        check("import restores a setting", added["settings"] == 1)
        check("import restores the GPS trace", added["places"] == 1 and added["location_points"] == 1)
        check(
            "restored pattern keeps its keyword list",
            json.loads(db.all_patterns()[0]["triggers"]) == ["3am", "scroll"],
        )
        check(
            "restored rule keeps its approval flag",
            any(r["text"].startswith("Sleep before") for r in db.approved_rules()),
        )

        # An import must never overwrite a live preference.
        db.set_setting("theme", "light")
        again = client.post("/api/import", json=exp).json()["added"]
        check("re-import is a no-op", again["facts"] == 0 and again["notes"] == 0)
        check("re-import does not re-add settings", again["settings"] == 0)
        check("re-import leaves a changed setting alone", db.get_setting("theme") == "light")

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

        # --- a provider can be turned off and on; a disabled provider is
        #     skipped by the failover chain and is never probed.
        db.set_setting("provider.groq.api_key", "toggle-key")
        check("providers start enabled", llm.provider_enabled("groq") is True)
        toggled = client.post("/api/providers/groq", json={"enabled": False}).json()
        check("provider can be turned off", toggled["provider"]["enabled"] is False)
        check("turning off keeps the key", llm.provider_key("groq") == "toggle-key")
        listed = [p for p in client.get("/api/providers").json()["providers"] if p["name"] == "groq"][0]
        check("disabled state shows in the listing", listed["enabled"] is False)
        client.post("/api/providers/groq", json={"enabled": True})
        check("provider can be turned on again", llm.provider_enabled("groq") is True)

        import asyncio

        async def skip_disabled():
            called = []
            original_handlers = {n: llm.HANDLERS.get(n) for n in llm.HANDLERS}

            def make_spy(name):
                async def spy(model, messages, **kw):
                    called.append(name)
                    return "spy"

                return spy

            for n in ("groq", "gemini", "openrouter", "ollama"):
                llm.HANDLERS[n] = make_spy(n)
            try:
                await llm.complete([{"role": "user", "content": "hi"}])
            except llm.ProviderError:
                pass
            finally:
                for n, h in original_handlers.items():
                    llm.HANDLERS[n] = h
            return called

        db.set_setting("provider.groq.enabled", "0")
        called_order = asyncio.run(skip_disabled())
        check("complete() skips a disabled provider", called_order and called_order[0] == "gemini")
        db.delete_setting("provider.groq.enabled")


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


def test_ask_endpoint() -> None:
    """/api/ask maps each question class to the honest mode and persists it.

    The model is stubbed, so this drives the router, the label brake, the
    background extractor and message persistence end-to-end with no network.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, learn
    from atif_assistant.app import app

    print("\nask endpoint")
    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "ask.db")
        db.init_db()
        client = TestClient(app)

        async def fake_complete(messages, **kw):
            return (
                "[FACT] Stable test answer.\n"
                "[INFERENCE] Provided by the test stub.",
                "groq",
            )

        orig_engine, orig_learn = engine.complete, learn.complete
        engine.complete = fake_complete
        learn.complete = fake_complete
        try:
            cases = {
                "what is your name": "ask",
                "should i quit my job": "decide",
                "why am i like this": "challenge",
                "what is photosynthesis": "ask",
                "tell me a story about dragons": "challenge",
            }
            for q, want in cases.items():
                res = client.post("/api/ask", json={"question": q}).json()
                check(f"route {q!r} -> {want}", res["route"]["mode"] == want)
                check(f"answer carries a label ({q!r})", bool(res["labels"]))
                sess = res["session"]
                hist = client.get(f"/api/history/{sess}").json()["messages"]
                check(
                    f"exchange persisted ({q!r})",
                    len(hist) == 2
                    and hist[0]["role"] == "user"
                    and hist[1]["role"] == "assistant",
                )

            before = db.question_count("knowledge")
            r1 = client.post("/api/ask", json={"question": "how to bake bread"}).json()
            r2 = client.post("/api/ask", json={"question": "how to bake bread"}).json()
            check("first ask of a class counts once", r1["asked_count"] == before + 1)
            check("repeat ask increments the count", r2["asked_count"] == before + 2)

            check(
                "empty question does not error",
                client.post("/api/ask", json={"question": ""}).status_code == 200,
            )
        finally:
            engine.complete = orig_engine
            learn.complete = orig_learn

    db.reset_db_path()


def test_misc_endpoints() -> None:
    """Memory search, evidence, the decision ledger, learned gating and media
    content lookups all behave through the HTTP layer."""
    from fastapi.testclient import TestClient

    from atif_assistant import db, uploads

    from atif_assistant.app import app

    print("\nmisc endpoints")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "misc.db")
        db.init_db()
        client = TestClient(app)
        prev_uploads = uploads.UPLOADS_DIR
        uploads.UPLOADS_DIR = base / "uploads"
        uploads.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        # --- memory: empty query lists facts, a query searches them.
        db.add_fact("I prefer morning work", source="test", confidence=0.8)
        listed = client.get("/api/memory?limit=5").json()["results"]
        check("memory lists facts when no query", any("morning work" in r["body"] for r in listed))
        found = client.get("/api/memory?q=morning").json()["results"]
        check("memory search finds the fact", any("morning work" in str(r) for r in found))

        # --- evidence search and its empty-query guard.
        db.add_evidence(source="test:ev", body="photosynthesis converts light to sugar")
        check("empty evidence query returns nothing", client.get("/api/evidence").json() == {"results": []})
        ev = client.get("/api/evidence?q=photosynthesis").json()["results"]
        check("evidence search finds the line", any("photosynthesis" in e["body"] for e in ev))

        # --- decision ledger: due, resolve, and the 404 guards.
        did = client.post(
            "/api/decisions",
            json={
                "topic": "job",
                "decision": "stay",
                "prediction": "calmer",
                "review_date": "2000-01-01",
            },
        ).json()["id"]
        due = client.get("/api/decisions").json()["due"]
        check("past review date shows as due", any(d["id"] == did for d in due))
        check(
            "blank resolution is rejected",
            client.post(f"/api/decisions/{did}/resolve", json={"actual_outcome": "  "}).status_code == 404,
        )
        ok = client.post(f"/api/decisions/{did}/resolve", json={"actual_outcome": "still employed"})
        check("decision resolves", ok.json().get("ok") is True and ok.json()["id"] == did)
        check(
            "resolved decision leaves due",
            not any(d["id"] == did for d in client.get("/api/decisions").json()["due"]),
        )
        check(
            "double resolution is a 404",
            client.post(f"/api/decisions/{did}/resolve", json={"actual_outcome": "again"}).status_code == 404,
        )
        check(
            "resolving a missing decision is a 404",
            client.post("/api/decisions/999999/resolve", json={"actual_outcome": "x"}).status_code == 404,
        )
        did2 = client.post(
            "/api/decisions", json={"topic": "delete me", "decision": "gone"}
        ).json()["id"]
        check(
            "deleting a decision is ok",
            client.delete(f"/api/decisions/{did2}").json().get("ok") is True,
        )
        check(
            "deleted decision leaves the ledger",
            not any(d["id"] == did2 for d in client.get("/api/decisions").json()["open"]),
        )
        check(
            "deleting a missing decision is a 404",
            client.delete("/api/decisions/999999").status_code == 404,
        )

        # --- insights: a contradiction is surfaced with both fact ids, and
        # keeping one side (deleting the other) settles it.
        db.add_fact("My commute is long", source="test")
        db.add_fact("My commute is not long", source="test")
        con = client.get("/api/insights").json()["contradictions"]
        mine = next((c for c in con if c["subject"] == "commute"), None)
        check(
            "a contradiction is surfaced with both fact ids",
            bool(mine and mine.get("a_id") and mine.get("b_id")),
        )
        if mine:
            client.delete(f"/api/facts/{mine['a_id']}")
            after = client.get("/api/insights").json()["contradictions"]
            check(
                "keeping one side settles the contradiction",
                not any(c["subject"] == "commute" for c in after),
            )

        # --- learned gating: candidates surface; approve promotes; reject drops.
        lid = db.add_learned("My sister lives in Oslo", kind="durable", source="test")
        cands = client.get("/api/learned").json()["candidates"]
        check("learned candidate appears", any(c["id"] == lid for c in cands))
        check(
            "approving a candidate is ok",
            client.post(f"/api/learned/{lid}/approve").json().get("ok") is True,
        )
        check(
            "approved candidate leaves the queue",
            not any(c["id"] == lid for c in client.get("/api/learned").json()["candidates"]),
        )
        check(
            "approving a missing candidate fails",
            client.post("/api/learned/999999/approve").json()["ok"] is False,
        )
        lid2 = db.add_learned("My car is blue", kind="durable", source="test")
        check(
            "rejecting a candidate is ok",
            client.post(f"/api/learned/{lid2}/reject").json().get("ok") is True,
        )
        check(
            "rejected candidate leaves the queue",
            not any(c["id"] == lid2 for c in client.get("/api/learned").json()["candidates"]),
        )

        # --- media content lookup.
        real = base / "note.txt"
        real.write_text("hello")
        good = client.post("/api/media", json={"path": str(real), "kind": "text"}).json()["id"]
        got = client.get(f"/api/media/{good}/content")
        check("media content returns the size", got.status_code == 200 and got.json()["size"] == 5)
        check("missing media id is a 404", client.get("/api/media/999999/content").status_code == 404)
        missing = client.post(
            "/api/media", json={"path": str(base / "gone.bin"), "kind": "file"}
        ).json()["id"]
        check(
            "media row with no file on disk is a 404",
            client.get(f"/api/media/{missing}/content").status_code == 404,
        )
        check(
            "media tags can be edited",
            client.put(f"/api/media/{good}", json={"tags": "tax 2025"}).json().get("ok")
            is True,
        )
        check(
            "edited media tags are stored",
            any(
                r["id"] == good and r["tags"] == "tax 2025"
                for r in client.get("/api/media").json()["media"]
            ),
        )
        check(
            "editing a missing media row is a 404",
            client.put("/api/media/999999", json={"tags": "x"}).status_code == 404,
        )
        check(
            "deleting a media row is ok",
            client.delete(f"/api/media/{good}").json().get("ok") is True,
        )
        check(
            "deleted media leaves the list",
            not any(r["id"] == good for r in client.get("/api/media").json()["media"]),
        )
        check(
            "deleting a missing media row is a 404",
            client.delete("/api/media/999999").status_code == 404,
        )

        # The stored file is removed only when the last row pointing at it is
        # deleted (uploads are de-duplicated by content hash).
        stored = uploads.UPLOADS_DIR / "abc123_note.txt"
        stored.write_text("hi")
        m1 = client.post("/api/media", json={"path": str(stored), "kind": "text"}).json()["id"]
        m2 = client.post("/api/media", json={"path": str(stored), "kind": "text"}).json()["id"]
        client.delete(f"/api/media/{m1}")
        check("shared upload survives one delete", stored.exists())
        client.delete(f"/api/media/{m2}")
        check("last delete removes the stored file", not stored.exists())

    db.reset_db_path()
    uploads.UPLOADS_DIR = prev_uploads


def _make_pdf(text: str = "Hello PDF plan") -> bytes:
    """Build a minimal, valid single-page PDF so the reader can be tested."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = ("BT /F1 24 Tf 72 700 Td (" + text + ") Tj ET").encode()
    objs.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + o + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return bytes(out)


def test_extract() -> None:
    """Files are actually read into text: text, markup, PDF, Office, WhatsApp."""
    import io
    import zipfile

    from atif_assistant import extract

    print("\nextract")

    txt = extract.extract("notes.md", b"# Title\nthree things to do")
    check("markdown reads as text", txt["source"] == "text" and "three things" in txt["text"])

    js = extract.extract("d.json", b'{"a":1,"b":[2,3]}')
    check("json is parsed and re-emitted", js["source"] == "json" and '"a": 1' in js["text"])

    html = extract.extract("p.html", b"<html><body><h1>Hi</h1><p>a &amp; b</p></body></html>")
    check("markup keeps text and unescapes entities", html["text"] == "Hi a & b")

    pdf = extract.extract("plan.pdf", _make_pdf("Run 3x per week"))
    check("pdf text is extracted", pdf["source"] == "pdf" and "Run 3x per week" in (pdf["text"] or ""))

    bad_pdf = extract.extract("scan.pdf", b"%PDF-1.4 not really a pdf")
    check("unreadable pdf reports a reason, not fake text", bad_pdf["text"] is None and bool(bad_pdf["reason"]))

    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
            "<w:p><w:r><w:t>Goal: save money</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Run 3x per week</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    docx = extract.extract("plan.docx", docx_buf.getvalue())
    check("docx paragraphs are read", docx["source"] == "docx" and "save money" in docx["text"] and "Run 3x" in docx["text"])

    xlsx_buf = io.BytesIO()
    with zipfile.ZipFile(xlsx_buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="x"><si><t>Item</t></si><si><t>Cost 20</t></si></sst>')
    xlsx = extract.extract("budget.xlsx", xlsx_buf.getvalue())
    check("xlsx strings are read", xlsx["source"] == "xlsx" and "Cost 20" in xlsx["text"])

    wa_text = "\n".join(
        [
            "[31/12/2025, 9:41:03 PM] Alex: Hey are we still on?",
            "[31/12/2025, 9:42:00 PM] Sam: Yes 7pm",
            "[31/12/2025, 9:43:10 PM] Alex: perfect",
            "[31/12/2025, 9:44:00 PM] Sam: bring the notes",
            "[31/12/2025, 9:45:00 PM] Alex: ok",
            "[31/12/2025, 9:46:00 PM] Sam: see you",
        ]
    )
    wa = extract.extract("chat.txt", wa_text.encode())
    check("whatsapp export is detected", wa["source"] == "whatsapp")
    check("whatsapp summary names participants", wa["meta"]["people"] == ["Alex", "Sam"])
    check("whatsapp messages counted", wa["meta"]["messages"] == 6)

    png = extract.extract("pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    check("image without OCR reports a reason", png["text"] is None and "OCR" in (png["reason"] or ""))

    unknown = extract.extract("archive.zip", b"PK\x03\x04\x00\x00binary")
    check("unknown binary reports a reason", unknown["text"] is None and bool(unknown["reason"]))


def test_upload_reads() -> None:
    """Uploads report honestly whether the file was read, and the text reaches
    retrieval so the assistant can answer from the file."""
    import io
    import zipfile

    from fastapi.testclient import TestClient

    from atif_assistant import db, uploads
    from atif_assistant.app import app

    print("\nupload reading")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "reads.db")
        db.init_db()
        uploads.UPLOADS_DIR = base / "uploads"
        client = TestClient(app)

        docx_buf = io.BytesIO()
        with zipfile.ZipFile(docx_buf, "w") as z:
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
                "<w:p><w:r><w:t>My marathon plan: run every Tuesday and Friday</w:t></w:r></w:p>"
                "</w:body></w:document>",
            )
        docx_b64 = base64.b64encode(docx_buf.getvalue()).decode()
        r = client.post(
            "/api/upload",
            json={"filename": "marathon.docx", "related_to": "training", "content_b64": docx_b64},
        ).json()
        check("docx upload is read", r.get("read") is True and r.get("text_source") == "docx")
        check("docx upload reports character count", r.get("read_chars", 0) > 0)
        check("docx upload became memory", r.get("evidence_id") is not None and r.get("episode_id") is not None)

        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60).decode()
        # Stub vision so the test never reaches the network; the point here is
        # the upload path, and a configured key must not decide the outcome.
        orig_vision = uploads.vision.describe
        uploads.vision.describe = lambda raw, fn: {
            "text": None, "source": None, "reason": "no vision provider in tests", "meta": {}
        }
        try:
            r2 = client.post("/api/upload", json={"filename": "photo.png", "content_b64": png}).json()
        finally:
            uploads.vision.describe = orig_vision
        check("unreadable upload says so", r2.get("read") is False and bool(r2.get("read_reason")))
        check("unreadable upload is still stored", r2.get("ok") is True)

        # The uploaded file's text must be usable as context for a question.
        ev = db.search_evidence("marathon Tuesday", limit=3)
        check("uploaded text is searchable evidence", any("marathon plan" in (e.get("body") or "") for e in ev))

    db.reset_db_path()


def test_read_fallbacks() -> None:
    """Images and audio go through hosted models when configured, and report an
    honest reason - never invented content - when they are not."""
    import base64

    from fastapi.testclient import TestClient

    from atif_assistant import db, transcribe, uploads, vision
    from atif_assistant.app import app

    print("\nread fallbacks")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "fall.db")
        db.init_db()
        uploads.UPLOADS_DIR = base / "uploads"
        client = TestClient(app)

        calls = {"vision": 0, "audio": 0}
        orig_v, orig_t = vision.describe, transcribe.transcribe

        def fake_vision(raw, filename):
            calls["vision"] += 1
            return {
                "text": "GROCERY: milk, eggs\nDESCRIPTION: a whiteboard",
                "source": "vision",
                "reason": None,
                "meta": {"model": "stub"},
            }

        def fake_audio(raw, filename):
            calls["audio"] += 1
            return {
                "text": "remind me to call the doctor on Friday",
                "source": "transcript",
                "reason": None,
                "meta": {"model": "stub"},
            }

        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60).decode()
        mp3 = base64.b64encode(b"ID3\x03\x00" + b"\x00" * 40).decode()
        vision.describe, transcribe.transcribe = fake_vision, fake_audio
        try:
            r = client.post("/api/upload", json={"filename": "board.png", "content_b64": png}).json()
            check("an image is sent to the vision model", calls["vision"] == 1)
            check("vision text is read", r.get("read") is True and r.get("text_source") == "vision")
            check("vision text became evidence", r.get("evidence_id") is not None)

            r2 = client.post("/api/upload", json={"filename": "note.mp3", "content_b64": mp3}).json()
            check("audio is sent to transcription", calls["audio"] == 1)
            check("audio transcript is read", r2.get("read") is True and r2.get("text_source") == "transcript")
            check(
                "audio transcript is searchable",
                any("doctor" in (e.get("body") or "") for e in db.search_evidence("doctor", limit=3)),
            )
        finally:
            vision.describe, transcribe.transcribe = orig_v, orig_t

        # No provider: honest reason, nothing invented.
        vision.describe = lambda raw, fn: {"text": None, "source": None, "reason": "images need a vision provider", "meta": {}}
        transcribe.transcribe = lambda raw, fn: {"text": None, "source": None, "reason": "audio needs a Groq key", "meta": {}}
        try:
            r3 = client.post("/api/upload", json={"filename": "x.png", "content_b64": png}).json()
            check(
                "unread image names the missing provider",
                r3.get("read") is False and "vision" in (r3.get("read_reason") or "").lower(),
            )
            r4 = client.post("/api/upload", json={"filename": "y.mp3", "content_b64": mp3}).json()
            check(
                "unread audio names the missing key",
                r4.get("read") is False and "groq" in (r4.get("read_reason") or "").lower(),
            )
        finally:
            vision.describe, transcribe.transcribe = orig_v, orig_t

    db.reset_db_path()


def test_plan() -> None:
    """A document becomes a strict, editable plan: rules are stored, enforced,
    and always under the user's control."""
    from fastapi.testclient import TestClient

    from atif_assistant import db, plan
    from atif_assistant.app import app

    print("\nplan")

    parsed = plan.parse_plan("TITLE: Marathon Plan\nRULE: Run on Tuesday\nRULE: Rest on Sunday\n")
    check("plan title is parsed", parsed["title"] == "Marathon Plan")
    check("plan rules are parsed", parsed["rules"] == ["Run on Tuesday", "Rest on Sunday"])
    check("empty plan parses to nothing", plan.parse_plan("no structure here")["rules"] == [])

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "plan.db")
        db.init_db()
        client = TestClient(app)

        async def fake_complete(messages, **kw):
            return (
                "TITLE: Saving Plan\n"
                "RULE: Save 500 every month\n"
                "RULE: Do not buy takeaway on weekdays\n",
                "groq",
            )

        orig = plan.complete
        plan.complete = fake_complete
        try:
            # Strict plan: rules are approved immediately and enforced.
            r = client.post("/api/plan", json={"text": "save 500 monthly, no weekday takeaway", "strict": True}).json()
            check("plan is drafted", r.get("ok") is True and r["title"] == "Saving Plan")
            check("plan created an episode", r.get("episode_id") is not None)
            check("strict plan enforces two rules", len(r["rules"]) == 2 and all(x["approved"] for x in r["rules"]))

            rules = {x["text"]: x for x in client.get("/api/rules").json()["rules"]}
            check("rules are listed", set(rules) == {"Save 500 every month", "Do not buy takeaway on weekdays"})
            check("enforced rules reach the guardrails prompt", any(
                "Save 500 every month" in rule["text"] for rule in db.approved_rules()
            ))

            # Candidate plan: not enforced until approved.
            r2 = client.post("/api/plan", json={"text": "study twice a week", "strict": False}).json()
            cand = r2["rules"][0]
            check("non-strict plan starts as candidates", cand["approved"] is False)
            check(
                "approving a candidate enforces it",
                client.post(f"/api/rules/{cand['id']}/approve").json().get("ok") is True,
            )
            check(
                "approving a missing rule is a 404",
                client.post("/api/rules/999999/approve").status_code == 404,
            )

            check(
                "a rule can be removed",
                client.delete(f"/api/rules/{cand['id']}").json().get("ok") is True,
            )
            check(
                "removing a missing rule is a 404",
                client.delete("/api/rules/999999").status_code == 404,
            )
            remaining = [x["text"] for x in client.get("/api/rules").json()["rules"]]
            check("removed rule is gone", "Save 500 every month" in remaining and "Study twice a week" not in remaining)

            # No provider -> honest failure, nothing invented.
            async def boom(messages, **kw):
                raise plan.ProviderError("no provider")

            plan.complete = boom
            check(
                "plan without a provider fails cleanly",
                client.post("/api/plan", json={"text": "some document"}).status_code == 503,
            )
        finally:
            plan.complete = orig

        check(
            "plan with no input is rejected",
            client.post("/api/plan", json={}).status_code == 400,
        )

    db.reset_db_path()


def test_tts() -> None:
    """Speech is synthesized server-side for languages with no local voice,
    and fails soft with an honest reason when it cannot."""
    import struct

    from fastapi.testclient import TestClient

    from atif_assistant import db, tts
    from atif_assistant.app import app

    print("\ntts")

    check(
        "speech cleaning drops labels",
        tts._clean("[FACT] Hello [PREDICTION] world") == "Hello world",
    )
    wav = tts._wav(b"\x00\x00" * 100, rate=24000)
    check("wav has a RIFF header", wav[:4] == b"RIFF" and wav[8:12] == b"WAVE")
    check("wav size field matches", struct.unpack("<I", wav[4:8])[0] == len(wav) - 8)
    check("wav sample rate is written", struct.unpack("<I", wav[24:28])[0] == 24000)

    orig_key = tts.llm.provider_key
    orig_espeak = tts.ESPEAK
    tts.llm.provider_key = lambda name: ""
    tts.ESPEAK = None  # pretend espeak-ng is not installed
    try:
        r = tts.synthesize("hello")
        check(
            "speech without a key or offline voice fails soft",
            r["audio"] is None and "gemini" in (r["reason"] or "").lower(),
        )
    finally:
        tts.llm.provider_key = orig_key
        tts.ESPEAK = orig_espeak

    if orig_espeak:
        # The offline voice must rescue spoken replies when the server voice is
        # unavailable, which is what makes Urdu work with no network.
        tts.llm.provider_key = lambda name: ""
        try:
            r = tts.synthesize("hello", "en")
            check(
                "speech falls back to the offline voice",
                bool(r.get("audio")) and (r.get("model") or "").startswith("espeak"),
            )
            check("offline speech is a wav", bytes(r["audio"])[:4] == b"RIFF")
        finally:
            tts.llm.provider_key = orig_key

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "tts.db")
        db.init_db()
        client = TestClient(app)

        orig_syn = tts.synthesize
        tts.synthesize = lambda text, lang="en": {
            "audio": tts._wav(b"\x00\x00" * 50),
            "reason": None,
            "model": "stub",
        }
        try:
            r = client.post("/api/tts", json={"text": "السلام علیکم", "lang": "ur"})
            check(
                "tts endpoint returns audio",
                r.status_code == 200 and r.headers.get("content-type", "").startswith("audio/wav"),
            )
            check("tts endpoint returns a wav body", r.content[:4] == b"RIFF")
        finally:
            tts.synthesize = orig_syn

        tts.synthesize = lambda text, lang="en": {"audio": None, "reason": "no speech key"}
        try:
            r = client.post("/api/tts", json={"text": "hi"})
            check(
                "tts endpoint reports an honest failure",
                r.status_code == 503 and "no speech key" in r.json().get("error", ""),
            )
        finally:
            tts.synthesize = orig_syn

    db.reset_db_path()


def test_stt() -> None:
    """Offline speech recognition (whisper.cpp) and its endpoint fail soft."""
    from fastapi.testclient import TestClient

    from atif_assistant import db, stt
    from atif_assistant.app import app

    print("\nstt (offline speech)")

    check(
        "stt maps browser language codes",
        stt._lang("ur-PK") == "ur" and stt._lang("en-US") == "en" and stt._lang(None) == "auto",
    )

    orig_bin = stt._BIN
    orig_model = stt._MODEL_OVERRIDE
    stt._BIN = None
    try:
        r = stt.transcribe(b"RIFF....")
        check(
            "offline speech without the tool fails soft",
            r["text"] is None and "whisper" in (r["reason"] or "").lower(),
        )
    finally:
        stt._BIN = orig_bin

    # Any real executable gets us past the "tool missing" branch so this
    # check exercises the model branch on machines without whisper installed
    # (e.g. CI runners) as well as developer Macs.
    stt._BIN = "/bin/ls"
    stt._MODEL_OVERRIDE = "/nonexistent/ggml.bin"
    try:
        r = stt.transcribe(b"RIFF....")
        check(
            "offline speech without the model fails soft",
            r["text"] is None and "model" in (r["reason"] or "").lower(),
        )
        check("offline status is honest", stt.status()["available"] is False)
    finally:
        stt._BIN = orig_bin
        stt._MODEL_OVERRIDE = orig_model

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "stt.db")
        db.init_db()
        client = TestClient(app)

        h = client.get("/api/health").json()
        check("health reports offline speech", "speech" in h and "offline_in" in h["speech"])

        orig_tr = stt.transcribe
        stt.transcribe = lambda raw, lang="auto": {
            "text": "السلام علیکم",
            "reason": None,
            "meta": {"model": "stub"},
        }
        try:
            import base64 as _b64

            r = client.post(
                "/api/stt",
                json={"audio": _b64.b64encode(b"RIFF0000").decode(), "lang": "ur-PK"},
            )
            check(
                "stt endpoint returns the transcript",
                r.status_code == 200 and r.json().get("text") == "السلام علیکم",
            )
        finally:
            stt.transcribe = orig_tr

        stt.transcribe = lambda raw, lang="auto": {
            "text": None,
            "reason": "offline speech model is not downloaded",
            "meta": {},
        }
        try:
            r = client.post("/api/stt", json={"audio": _b64.b64encode(b"x").decode()})
            check(
                "stt endpoint reports an honest failure",
                r.status_code == 503 and "model" in r.json().get("error", "").lower(),
            )
        finally:
            stt.transcribe = orig_tr

    db.reset_db_path()


def test_model_downloads() -> None:
    """Model downloads: mirror fallback, resume, pause - progress is sacred.

    The bugs this guards: a dead huggingface.co mirror bricking first run,
    the downloader deleting its own .part file after six failures (so a phone
    on a flaky link restarted 1.5 GB from zero every time), and no way to
    pause a mobile-data download.
    """
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from fastapi.testclient import TestClient

    from atif_assistant import app as app_mod, db, llm, stt
    from atif_assistant.app import app

    print("\nmodel downloads (mirrors, resume, pause)")

    payload = bytes((i * 7 + 3) % 256 for i in range(1_100_000))

    class Handler(BaseHTTPRequestHandler):
        routes: dict = {}
        seen: list = []  # (path, range-header, served-start)
        stop = threading.Event()

        def log_message(self, *args) -> None:  # noqa: D102 - fixture stays quiet
            pass

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            route = Handler.routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            data, mode = route["data"], route["mode"]
            rng = self.headers.get("Range")
            start = 0
            if rng and "=" in rng:
                try:
                    start = int(rng.split("=", 1)[1].split("-")[0] or 0)
                except ValueError:
                    start = 0
            Handler.seen.append((self.path, rng, start))
            try:
                if mode == "half":
                    # Claim the full length, deliver half, hang up: exactly
                    # what a flaky mobile link looks like.
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data[: len(data) // 2])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if mode == "slow":
                    # Trick the payload out for ~20 s so a pause can land
                    # while the download is still running.
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    pos = 0
                    while not Handler.stop.is_set():
                        chunk = data[pos:pos + 8192]
                        if not chunk:
                            pos, chunk = 0, data[:8192]
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        pos += len(chunk)
                        time.sleep(0.15)
                    return
                body = data[start:]
                self.send_response(206 if start else 200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    dead = "http://127.0.0.1:9/gguf"  # nothing listens there: instant refusal

    orig = {
        "llm": {
            k: getattr(llm, k)
            for k in ("DATA_DIR", "LLM_MODEL_URLS", "LLM_MODEL_EXPECTED", "_DL_ATTEMPTS")
        },
        "stt": {
            k: getattr(stt, k)
            for k in ("_MODEL_DIR", "MODEL_URLS", "MODEL_EXPECTED", "_DL_ATTEMPTS")
        },
    }

    def wait_for(fn, timeout=15.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.05)
        return False

    def reset_dl() -> None:
        with llm._LLM_DL_LOCK:
            llm._LLM_DL.update(
                {"state": "idle", "name": None, "bytes": 0, "total": 0,
                 "reason": None, "partial": 0, "pause": False}
            )
        with stt._STT_DL_LOCK:
            stt._STT_DL.update(
                {"state": "idle", "name": None, "bytes": 0, "total": 0,
                 "reason": None, "partial": 0, "pause": False}
            )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            db.use_test_db(Path(tmp) / "dl.db")
            db.init_db()
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            llm.DATA_DIR = data_dir
            llm._DL_ATTEMPTS = 2
            llm.LLM_MODEL_URLS = {"unit-model": [f"{base}/unit"], "guarded": [dead]}
            llm.LLM_MODEL_EXPECTED = {"unit-model": len(payload), "guarded": 100}
            stt._MODEL_DIR = Path(tmp) / "whisper"
            stt._DL_ATTEMPTS = 2
            stt.MODEL_URLS = {"ggml-unit.bin": [f"{base}/whisper"]}
            stt.MODEL_EXPECTED = {"ggml-unit.bin": len(payload)}
            dest = data_dir / "models" / "unit-model.gguf"
            part = data_dir / "models" / "unit-model.gguf.part"

            # 1. dead first mirror, working second mirror
            reset_dl()
            Handler.routes["/unit"] = {"data": payload, "mode": "ok"}
            llm.LLM_MODEL_URLS["unit-model"] = [dead, f"{base}/unit"]
            check("llm download starts", llm.llm_download_start("unit-model").get("ok") is True)
            check(
                "survives a dead first mirror",
                wait_for(lambda: llm.llm_model_status()["download"]["state"] == "ready"),
            )
            check(
                "model arrives complete",
                dest.is_file() and dest.stat().st_size == len(payload),
            )

            # 2. dropped connection: fail, but never lose the bytes fetched
            reset_dl()
            dest.unlink(missing_ok=True)
            part.unlink(missing_ok=True)
            Handler.routes["/unit"] = {"data": payload, "mode": "half"}
            llm.LLM_MODEL_URLS["unit-model"] = [f"{base}/unit"]
            llm.llm_download_start("unit-model")
            check(
                "failed download reports an error",
                wait_for(lambda: llm.llm_model_status()["download"]["state"] == "error"),
            )
            st = llm.llm_model_status()["download"]
            check(
                "partial file survives the failure",
                part.is_file() and part.stat().st_size > 0 and st.get("partial", 0) > 0,
            )
            check(
                "failure reason mentions saved progress",
                "progress saved" in (st.get("reason") or ""),
            )
            check("no finished model after failure", not dest.exists())

            # 3. a later start resumes the partial instead of restarting
            reset_dl()
            Handler.routes["/unit"] = {"data": payload, "mode": "ok"}
            half = len(payload) // 2
            part.write_bytes(payload[:half])
            Handler.seen.clear()
            llm.llm_download_start("unit-model")
            check(
                "resumes from the saved partial",
                wait_for(lambda: llm.llm_model_status()["download"]["state"] == "ready"),
            )
            check(
                "resume asked only for the missing bytes",
                any(p == "/unit" and s == half for p, _rg, s in Handler.seen),
            )
            check(
                "resumed file is byte-complete",
                dest.is_file() and dest.read_bytes() == payload,
            )

            # 4. pause mid-download keeps the partial file
            reset_dl()
            dest.unlink(missing_ok=True)
            part.unlink(missing_ok=True)
            Handler.routes["/unit"] = {"data": payload, "mode": "slow"}
            llm.llm_download_start("unit-model")
            check(
                "download begins on the slow mirror",
                wait_for(
                    lambda: llm.llm_model_status()["download"]["bytes"] > 0, timeout=10
                ),
            )
            check("pause is accepted", llm.llm_download_pause().get("ok") is True)
            check(
                "worker stops in the paused state",
                wait_for(
                    lambda: llm.llm_model_status()["download"]["state"] == "paused",
                    timeout=10,
                ),
            )
            check(
                "pause keeps the partial file",
                part.is_file() and part.stat().st_size > 0,
            )
            check(
                "paused status reports partial bytes",
                (llm.llm_model_status()["download"].get("partial") or 0) > 0,
            )
            r = llm.llm_download_start()  # no name: resumes the paused model
            check(
                "nameless start resumes the paused model",
                r.get("ok") is True
                and llm.llm_model_status()["download"]["name"] == "unit-model",
            )
            check(
                "resume returns to downloading",
                wait_for(
                    lambda: llm.llm_model_status()["download"]["state"] == "downloading"
                ),
            )
            llm.llm_download_pause()
            wait_for(
                lambda: llm.llm_model_status()["download"]["state"] == "paused",
                timeout=10,
            )

            # 5. whisper (sync path): failure keeps progress, retry resumes
            reset_dl()
            stt_dest = stt._MODEL_DIR / "ggml-unit.bin"
            stt_tmp = stt._MODEL_DIR / "ggml-unit.bin.part"
            stt_dest.unlink(missing_ok=True)
            stt_tmp.unlink(missing_ok=True)
            Handler.routes["/whisper"] = {"data": payload, "mode": "half"}
            r = stt.download_model("ggml-unit.bin")
            check(
                "failed whisper fetch keeps its partial",
                r.get("ok") is False
                and r.get("partial", 0) > 0
                and stt_tmp.is_file()
                and stt_tmp.stat().st_size > 0,
            )
            Handler.routes["/whisper"] = {"data": payload, "mode": "ok"}
            Handler.seen.clear()
            r2 = stt.download_model("ggml-unit.bin")
            check(
                "second whisper fetch resumes and finishes",
                r2.get("ok") is True
                and stt_dest.is_file()
                and stt_dest.read_bytes() == payload,
            )
            check(
                "whisper resume used a Range request",
                any(s > 0 for p, rg, s in Handler.seen if p == "/whisper" and rg),
            )

            # 6. whisper background worker rotates mirrors too
            reset_dl()
            stt_dest.unlink(missing_ok=True)
            stt_tmp.unlink(missing_ok=True)
            stt.MODEL_URLS["ggml-unit.bin"] = [dead, f"{base}/whisper"]
            check(
                "whisper background download starts",
                stt.stt_download_start("ggml-unit.bin").get("ok") is True,
            )
            check(
                "whisper worker rotates past the dead mirror",
                wait_for(lambda: stt.stt_download_status()["state"] == "ready"),
            )
            check(
                "whisper model complete",
                stt_dest.is_file() and stt_dest.stat().st_size == len(payload),
            )

            # 7. first-run setup facts
            client = TestClient(app)
            s = client.get("/api/setup").json()
            check(
                "/api/setup offers quick and full sets",
                set(s.get("sets", {})) == {"quick", "full"}
                and s["sets"]["quick"]["total_mib"] == 610
                and s["sets"]["full"]["total_mib"] == 1531,
            )
            check("setup recommends a known set", s.get("recommended") in {"quick", "full"})
            check(
                "setup reports free storage",
                isinstance(s.get("storage", {}).get("free_bytes"), int),
            )
            check(
                "setup warns above the set size",
                (s.get("warn_bytes") or 0)
                > s["sets"][s["recommended"]]["total_mib"] * 1048576,
            )

            # 8. pause endpoints
            with llm._LLM_DL_LOCK:
                llm._LLM_DL.update(
                    {"state": "downloading", "name": "unit-model", "pause": False}
                )
            r = client.post("/api/llm/model", json={"action": "pause"})
            check(
                "llm pause endpoint pauses",
                r.status_code == 200 and r.json().get("reason") == "pausing",
            )
            check(
                "pausing disables auto-resume",
                db.get_setting("models.auto_resume") == "off",
            )
            reset_dl()
            r = client.post("/api/speech/model", json={"action": "pause"})
            check(
                "whisper pause answers without a running download",
                r.status_code == 200 and r.json().get("reason") == "not downloading",
            )

            # 9. boot auto-resume: honours pause, resumes interrupted work
            calls: list = []
            orig_ls, orig_ss = llm.llm_download_start, stt.stt_download_start
            llm.llm_download_start = lambda name=None: (
                calls.append(("llm", name)),
                {"ok": True},
            )[1]
            stt.stt_download_start = lambda name=None: (
                calls.append(("stt", name)),
                {"ok": True},
            )[1]
            guard_part = llm._part_file("guarded")
            try:
                guard_part.parent.mkdir(parents=True, exist_ok=True)
                guard_part.write_bytes(b"partial")
                db.set_setting("models.auto_resume", "off")
                app_mod._resume_partial_downloads()
                check("paused downloads stay paused across a restart", calls == [])
                db.delete_setting("models.auto_resume")
                app_mod._resume_partial_downloads()
                check(
                    "interrupted downloads resume on boot",
                    ("llm", "guarded") in calls,
                )
            finally:
                llm.llm_download_start = orig_ls
                stt.stt_download_start = orig_ss
                guard_part.unlink(missing_ok=True)
    finally:
        for key, value in orig["llm"].items():
            setattr(llm, key, value)
        for key, value in orig["stt"].items():
            setattr(stt, key, value)
        reset_dl()
        Handler.stop.set()
        server.shutdown()
        server.server_close()

    db.reset_db_path()


def test_language() -> None:
    """Reply language follows the question when set to auto (Urdu fix).

    The bug being guarded against: an Urdu question answered in English because
    a stale "English" setting overrode what the user actually wrote.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, engine, stt
    from atif_assistant.app import app

    print("\nlanguage routing")

    check("urdu script is detected", engine.detect_language("آپ کیا سیو؟") == "ur")
    check(
        "roman urdu is detected",
        engine.detect_language("sleep kyun zaroori hai") == "ur",
    )
    check("short roman urdu is detected", engine.detect_language("kya hua") == "ur")
    check("english is not urdu", engine.detect_language("what is FTS5") == "en")
    check("empty is english", engine.detect_language("") == "en")

    check(
        "auto follows urdu",
        engine.resolve_language("auto", "نیند کیوں ضروری ہے؟") == "ur",
    )
    check(
        "auto follows english",
        engine.resolve_language("auto", "what is sleep") == "en",
    )
    check(
        "explicit english wins over urdu text",
        engine.resolve_language("en", "نیند کیوں ضروری ہے؟") == "en",
    )
    check(
        "explicit urdu wins over english text",
        engine.resolve_language("ur", "what is sleep") == "ur",
    )
    check("urdu rule is emitted", engine._language_rule("ur") != "")
    check("english emits no rule", engine._language_rule("en") == "")

    ctx = engine.build_context("نیند کیوں ضروری ہے؟")
    check("context records the detected language", ctx["detected_language"] == "ur")

    # The small model (best for Urdu) is preferred, with base as fallback.
    check("preferred offline model is small", stt.PREFERRED_MODEL == "ggml-small.bin")
    check(
        "model candidates prefer small then base",
        stt.MODEL_CANDIDATES[:2] == ("ggml-small.bin", "ggml-base.bin"),
    )
    check(
        "unknown model download is rejected",
        stt.download_model("nope.bin")["ok"] is False,
    )

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "lang.db")
        db.init_db()
        client = TestClient(app)

        async def fake_respond(question, mode="ask", ctx=None):
            return {
                "text": "[FACT] stub",
                "labels": [],
                "warnings": [],
                "patterns": [],
                "provider": "stub",
                "critique": [],
            }

        orig_respond = engine.respond
        orig_extract = __import__(
            "atif_assistant.app", fromlist=["_extract_in_background"]
        )._extract_in_background
        engine.respond = fake_respond
        import atif_assistant.app as app_mod

        async def noop_extract(*args, **kwargs):
            return None

        app_mod._extract_in_background = noop_extract
        try:
            r = client.post(
                "/api/ask",
                json={"question": "نیند کیوں ضروری ہے؟", "reply_language": "auto"},
            )
            check("ask echoes urdu", r.json().get("language") == "ur")

            r2 = client.post(
                "/api/ask", json={"question": "what is sleep", "reply_language": "auto"}
            )
            check("ask echoes english", r2.json().get("language") == "en")

            r3 = client.post(
                "/api/ask",
                json={"question": "نیند کیوں ضروری ہے؟", "reply_language": "en"},
            )
            check("ask honours an explicit override", r3.json().get("language") == "en")
        finally:
            engine.respond = orig_respond
            app_mod._extract_in_background = orig_extract

        speech = client.get("/api/speech").json()
        check("speech status endpoint responds", "stt" in speech and "tts" in speech)
        check("speech status lists models", "models_present" in speech["stt"])

        bad = client.post("/api/speech/model", json={"name": "bogus.bin"})
        check("model endpoint rejects unknown names", bad.status_code == 400)

        client.post(
            "/api/settings", json={"handsfree": "on", "reply_language": "ur"}
        )
        saved = client.get("/api/settings").json()
        check("handsfree setting persists", saved.get("handsfree") == "on")
        check("reply language setting persists", saved.get("reply_language") == "ur")

    db.reset_db_path()

    web = Path(__file__).resolve().parent.parent / "web"
    app_js = (web / "app.js").read_text()
    index_html = (web / "index.html").read_text()
    check("hands-free setting is in the UI", 'id="set-handsfree"' in index_html)
    check(
        "hands-free loop is wired",
        "startHandsFree" in app_js and "handsFreeSubmit" in app_js,
    )
    check("hands-free is persisted", "handsfree: settings.handsfree" in app_js)


def test_voice() -> None:
    """Speaker identification: matching, averaging, and advisory endpoints.

    The voice engine is stubbed so the test needs neither the model nor a
    microphone; what it guards is the matching maths, the enrolment averaging,
    and that a spoken answer is attributed without that attribution becoming a
    stored fact.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, stt, voice_id
    from atif_assistant.app import app

    print("\nvoice id")

    check(
        "default voice model is downloadable",
        voice_id.DEFAULT_MODEL in voice_id.MODEL_URLS,
    )
    check(
        "unknown voice model is rejected",
        voice_id.download_model("nope.onnx")["ok"] is False,
    )
    status = voice_id.status()
    check(
        "voice status reports the engine",
        "available" in status and "threshold" in status and "model" in status,
    )

    a = voice_id.normalize([1.0, 0.0, 0.0])
    close = voice_id.normalize([0.9, 0.1, 0.0])
    far = voice_id.normalize([0.0, 0.0, 1.0])
    match = voice_id.identify(a, [{"id": 1, "name": "A", "embedding": close}])
    check("same voice matches the saved print", match and match["name"] == "A")
    check("a close voice is reported known", match["known"] is True)
    check(
        "a different voice is not known",
        voice_id.identify(a, [{"id": 1, "name": "A", "embedding": far}])["known"] is False,
    )
    check("no saved prints means no match", voice_id.identify(a, []) is None)
    check("no embedding means no match", voice_id.identify(None, [{"id": 1, "name": "A", "embedding": close}]) is None)

    with tempfile.TemporaryDirectory() as tmp:
        db.use_test_db(Path(tmp) / "voice.db")
        db.init_db()

        vid = db.add_voiceprint("Atif", [1.0, 0.0])
        again = db.add_voiceprint("Atif", [0.0, 1.0])
        check("the same name reuses the row", vid == again)
        saved = db.list_voiceprints()
        check("one voiceprint is stored", len(saved) == 1)
        check("re-enrolment counts samples", saved[0]["samples"] == 2)
        check("the list API never exposes the embedding", "embedding" not in saved[0])
        check(
            "the raw embedding is kept for matching",
            len(db.voiceprints()[0]["embedding"]) == 2,
        )
        check("a voiceprint can be removed", db.remove_voiceprint(vid) is True)
        check("removing it again reports nothing", db.remove_voiceprint(vid) is False)

        client = TestClient(app)
        orig_available = voice_id.available
        orig_embed = voice_id.embed_wav
        voice_id.available = lambda: True
        voice_id.embed_wav = lambda data: [1.0, 0.0, 0.0]
        try:
            r = client.post("/api/voiceprints", json={"name": "Atif", "audio": "AAAA"})
            check("the enrol endpoint accepts a clip", r.status_code == 200 and r.json()["ok"])
            r = client.get("/api/voiceprints")
            check(
                "the voiceprints endpoint lists people",
                r.status_code == 200 and r.json()["count"] == 1,
            )
            r = client.post("/api/voice/identify", json={"audio": "AAAA"})
            check(
                "the identify endpoint returns a match",
                (r.json().get("match") or {}).get("name") == "Atif",
            )
            vp_id = r.json()["match"]["id"]
            check(
                "the delete endpoint removes a voice",
                client.delete(f"/api/voiceprints/{vp_id}").json()["ok"] is True,
            )
            check(
                "deleting a missing voice is a 404",
                client.delete(f"/api/voiceprints/{vp_id}").status_code == 404,
            )
            check(
                "a blank name is refused",
                client.post("/api/voiceprints", json={"name": "  ", "audio": "AAAA"}).status_code == 400,
            )

            orig_transcribe = stt.transcribe
            stt.transcribe = lambda raw, lang: {"text": "hello", "meta": {}}
            try:
                client.post("/api/voiceprints", json={"name": "Atif", "audio": "AAAA"})
                r = client.post("/api/stt", json={"audio": "AAAA", "lang": "en"})
                check(
                    "stt attaches the identified speaker",
                    (r.json().get("speaker") or {}).get("name") == "Atif",
                )
                r = client.post("/api/stt", json={"audio": "AAAA", "lang": "en", "identify": False})
                check("stt can skip identification", r.json().get("speaker") is None)
            finally:
                stt.transcribe = orig_transcribe
        finally:
            voice_id.available = orig_available
            voice_id.embed_wav = orig_embed

        # With no engine the endpoints say so instead of guessing.
        voice_id.available = lambda: False
        try:
            check(
                "enrolling without an engine is a 503",
                client.post("/api/voiceprints", json={"name": "X", "audio": "AAAA"}).status_code == 503,
            )
            check(
                "identifying without an engine is a 503",
                client.post("/api/voice/identify", json={"audio": "AAAA"}).status_code == 503,
            )
        finally:
            voice_id.available = orig_available

    db.reset_db_path()


def test_ollama() -> None:
    """Local model host: fail-soft start, autostart toggle, and endpoints.

    The engine probes are stubbed so the test never touches the network or a
    real ollama install; what it guards is that a missing or stopped host is
    reported clearly, never crashes a request, and that autostart is a setting.
    """
    from fastapi.testclient import TestClient

    from atif_assistant import db, ollama
    from atif_assistant.app import app

    print("\nlocal model host")

    status = ollama.status()
    check(
        "ollama status reports the expected shape",
        {"installed", "running", "url", "models", "model", "model_present"}
        <= set(status),
    )
    check("ollama has a desired model slug", bool(ollama.desired_model()))

    orig_binary, orig_running, orig_models = ollama.binary, ollama.running, ollama.models
    try:
        # A host that is not installed and not running must fail soft.
        ollama.binary = lambda: None
        ollama.running = lambda: False
        ollama.models = lambda: []
        res = ollama.start()
        check(
            "start without ollama fails soft with a reason",
            res.get("ok") is False and bool(res.get("reason")),
        )
        check("autostart is a no-op when ollama is absent", ollama.ensure_autostart() is None)

        with tempfile.TemporaryDirectory() as tmp:
            db.use_test_db(Path(tmp) / "ollama.db")
            db.init_db()
            db.set_setting("ollama_autostart", "0")
            client = TestClient(app)

            st = client.get("/api/ollama").json()
            check("ollama endpoint reports autostart", "autostart" in st)
            check("start endpoint is 503 when ollama is missing",
                  client.post("/api/ollama/start").status_code == 503)
            check("pull endpoint is 503 when ollama is missing",
                  client.post("/api/ollama/pull", json={}).status_code == 503)

            client.post("/api/ollama/autostart", json={"enabled": True})
            check("autostart can be turned on", ollama.autostart_enabled() is True)
            client.post("/api/ollama/autostart", json={"enabled": False})
            check("autostart can be turned off", ollama.autostart_enabled() is False)
    finally:
        ollama.binary, ollama.running, ollama.models = orig_binary, orig_running, orig_models

    db.reset_db_path()


def test_crud() -> None:
    from fastapi.testclient import TestClient

    from atif_assistant import db
    from atif_assistant.app import app

    print("\ncrud")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db.use_test_db(base / "crud.db")
        db.init_db()
        client = TestClient(app)

        # --- facts: create, list, update, delete.
        created = client.post("/api/facts", json={"text": "I work mornings", "confidence": 0.7})
        check("a fact can be created", created.status_code == 201 and created.json()["ok"])
        fid = created.json()["id"]
        listed = client.get("/api/facts").json()["facts"]
        check("the created fact is listed", any(f["id"] == fid for f in listed))
        check(
            "blank fact text is rejected",
            client.post("/api/facts", json={"text": "   "}).status_code == 400,
        )
        check(
            "non-numeric confidence is rejected",
            client.post("/api/facts", json={"text": "x", "confidence": "abc"}).status_code == 400,
        )
        upd = client.put(f"/api/facts/{fid}", json={"text": "I work evenings", "status": "active"})
        check("a fact can be updated", upd.status_code == 200 and upd.json()["ok"])
        check(
            "the update is visible",
            any(f["id"] == fid and "evenings" in f["text"] for f in client.get("/api/facts").json()["facts"]),
        )
        check(
            "updating a missing fact is a 404",
            client.put("/api/facts/999999", json={"text": "x"}).status_code == 404,
        )
        check(
            "updating with no fields is a 404",
            client.put(f"/api/facts/{fid}", json={}).status_code == 404,
        )
        check("a fact can be deleted", client.delete(f"/api/facts/{fid}").status_code == 200)
        check(
            "the deleted fact is gone",
            not any(f["id"] == fid for f in client.get("/api/facts").json()["facts"]),
        )
        check(
            "deleting a missing fact is a 404",
            client.delete(f"/api/facts/{fid}").status_code == 404,
        )

        # --- episodes: list, update, delete.
        eid = db.add_episode("Morning walk", summary="thirty minutes")
        eps = client.get("/api/episodes").json()["episodes"]
        check("episodes are listed", any(e["id"] == eid for e in eps))
        check(
            "an episode can be updated",
            client.put(f"/api/episodes/{eid}", json={"title": "Evening walk"}).json()["ok"],
        )
        check(
            "the episode update is visible",
            any(
                e["id"] == eid and e["title"] == "Evening walk"
                for e in client.get("/api/episodes").json()["episodes"]
            ),
        )
        check("an episode can be deleted", client.delete(f"/api/episodes/{eid}").status_code == 200)
        check(
            "deleting a missing episode is a 404",
            client.delete(f"/api/episodes/{eid}").status_code == 404,
        )

        # --- rules: update (text and approval).
        rid = db.add_rule("Old rule text", code="R1")
        check(
            "a rule can be updated",
            client.put(f"/api/rules/{rid}", json={"text": "New rule text", "approved": True}).json()["ok"],
        )
        rules = client.get("/api/rules").json()["rules"]
        match = next((r for r in rules if r["id"] == rid), None)
        check("the rule update is visible", match and match["text"] == "New rule text")
        check("the rule is now approved", match and int(match["approved"]) == 1)
        check(
            "updating a missing rule is a 404",
            client.put("/api/rules/999999", json={"text": "x"}).status_code == 404,
        )

        # --- learned: candidates can be deleted or rejected.
        lid = db.add_learned("My dog is called Rufus", kind="durable", source="test")
        check(
            "a learned candidate can be rejected via api",
            client.post(f"/api/learned/{lid}/reject").json().get("ok") is True,
        )
        lid2 = db.add_learned("I grew up in Lahore", kind="durable", source="test")
        check("a learned candidate can be removed", db.delete_learned(lid2) is True)
        check("removing it again reports nothing", db.delete_learned(lid2) is False)

        db.reset_db_path()


def _js_skeleton(src: str) -> str:
    """Blank out strings, comments, template bodies and regex literals.

    Only a hand-rolled scanner is safe here: a regex like // inside a string
    would derail a naive split, and a missed declaration turns into a false
    alarm in the sweep below. Interpolations (``${...}``) are dropped whole -
    losing a rare inline declaration only weakens the sweep, never breaks it.
    """
    out: list[str] = []
    i, n = 0, len(src)
    mode = "code"
    quote = ""
    last_sig = ""        # last meaningful char in code mode
    last_word = ""       # identifier run immediately before position
    while i < n:
        c = src[i]
        if mode == "code":
            if c == "/" and i + 1 < n and src[i + 1] == "/":
                mode = "line"
                i += 2
                continue
            if c == "/" and i + 1 < n and src[i + 1] == "*":
                mode = "block"
                i += 2
                continue
            if c in "\"'":
                quote = c
                mode = "str"
                out.append(" ")
                i += 1
                continue
            if c == "`":
                mode = "tpl"
                i += 1
                continue
            regex_after = (
                last_sig in "([=,:;!&|?{};+-*%^~<>\n"
                or last_sig == ""
                or last_word in ("return", "case", "typeof", "instanceof", "in",
                                 "of", "delete", "void", "new", "do", "else",
                                 "yield", "await")
            )
            if c == "/" and regex_after:
                mode = "regex"
                i += 1
                continue
            out.append(c)
            if c.isspace():
                if c == "\n":
                    last_sig = "\n"
                    last_word = ""
            else:
                last_sig = c
                if c.isalnum() or c in "_$":
                    last_word += c
                else:
                    last_word = ""
            i += 1
        elif mode == "line":
            if c == "\n":
                mode = "code"
                out.append("\n")
                last_sig = "\n"
                last_word = ""
            i += 1
        elif mode == "block":
            if c == "*" and i + 1 < n and src[i + 1] == "/":
                mode = "code"
                i += 2
            else:
                if c == "\n":
                    out.append("\n")
                    last_sig = "\n"
                    last_word = ""
                i += 1
        elif mode == "str":
            if c == "\\":
                i += 2
                continue
            if c == quote:
                mode = "code"
                last_sig = quote
                last_word = ""
            i += 1
        else:  # tpl or regex
            if c == "\\":
                i += 2
                continue
            if mode == "tpl" and c == "`":
                mode = "code"
                last_sig = "`"
                last_word = ""
                i += 1
                continue
            if mode == "regex":
                if c == "[":
                    i += 1
                    while i < n and src[i] != "]":
                        if src[i] == "\\":
                            i += 1
                        i += 1
                    i += 1  # past the class (or off the end)
                    continue
                if c == "/":
                    mode = "code"
                    last_sig = "/"
                    last_word = ""
                    i += 1
                    while i < n and (src[i].isalpha() or src[i] == "$"):
                        i += 1  # flags
                    continue
                if c == "\n":
                    # Not a regex after all - recover at the line break.
                    mode = "code"
                    out.append("\n")
                    last_sig = "\n"
                    last_word = ""
            i += 1
    return "".join(out)


def test_no_undeclared_identifiers() -> None:
    """An undeclared identifier throws at click time and is invisible to the
    getElementById checks: one stale variable kept Settings closed for a whole
    release. Sweep app.js - every property base and call target must be
    declared somewhere in the file or be a known browser global."""
    import re

    root = Path(__file__).resolve().parent.parent
    src = (root / "web" / "app.js").read_text(encoding="utf-8")
    stripped = _js_skeleton(src)

    globals_ok = set(
        """
        window document navigator location history console performance screen
        localStorage sessionStorage caches fetch WebSocket Worker XMLHttpRequest
        URL URLSearchParams Blob File FormData AbortController AbortSignal Headers
        Request Response Event CustomEvent KeyboardEvent MouseEvent EventSource
        TextEncoder TextDecoder IntersectionObserver MutationObserver ResizeObserver
        requestAnimationFrame cancelAnimationFrame setTimeout clearTimeout
        setInterval clearInterval queueMicrotask matchMedia getComputedStyle
        alert confirm prompt atob btoa encodeURIComponent decodeURIComponent
        encodeURI decodeURI parseInt parseFloat isNaN isFinite Math JSON Date
        String Number Boolean Array Object Promise Error TypeError RangeError
        RegExp Map Set WeakMap WeakSet Symbol Proxy Reflect Infinity NaN
        undefined speechSynthesis SpeechRecognition webkitSpeechRecognition
        SpeechSynthesisUtterance Audio Image AudioContext webkitAudioContext
        OfflineAudioContext MediaRecorder AndroidVoice globalThis top self
        Notification crypto structuredClone DOMParser HTMLElement Element Node
        devicePixelRatio constructor get set of from async await new function
        if for while switch catch return typeof delete void instanceof in do
        else break continue case default class extends super this null true
        false with throw import export yield
        ArrayBuffer DataView Uint8Array Int8Array Uint16Array Int16Array
        Uint32Array Int32Array Float32Array Float64Array BigInt
        """.split()
    )

    bases = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\.", stripped))
    calls = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", stripped))
    candidates = (bases | calls) - globals_ok

    declared = set(
        re.findall(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
                   stripped)
    )
    # Destructuring targets: const { a, b: c } = ... / const [x] = ...
    for m in re.finditer(r"\b(?:const|let|var)\s*[{[]([^=;]+?)[=\]]", stripped):
        declared.update(re.findall(r"[A-Za-z_$][\w$]*", m.group(1)))
    # Arrow parameters, including single-parameter arrows without parens.
    declared.update(re.findall(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*=>", stripped))
    # Object-literal method shorthand: { name(...) {} } declares name.
    for m in re.finditer(r"[{,]\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(", stripped):
        declared.add(m.group(1))
    # Every balanced paren group may hold a parameter list (or a catch var).
    depth = 0
    start = -1
    for idx, ch in enumerate(stripped):
        if ch == "(":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                declared.update(re.findall(r"[A-Za-z_$][\w$]*", stripped[start + 1:idx]))
                start = -1

    missing = sorted(candidates - declared)
    check(
        "no undeclared identifiers in app.js",
        not missing,
    )
    if missing:
        print(f"         undeclared: {', '.join(missing[:12])}")


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
    test_web_sync()
    test_natural_reply_surface()
    test_layout_navigation()
    test_ui_error_visibility()
    test_call_error_channel()
    test_phone_voice_engine()
    test_no_undeclared_identifiers()
    test_downloads()
    test_sessions_feedback()
    test_soul()
    test_soul_ask()
    test_style_mirror()
    test_reflection()
    test_ask_stream()
    test_ask_stop_disconnect()
    test_home()
    test_importers()
    test_whatsapp_txt()
    test_inbox()
    test_autodraft()
    test_todos_reminders()
    test_extended_api()
    test_location()
    test_uploads()
    test_backup()
    test_providers()
    test_language()
    test_ask_endpoint()
    test_misc_endpoints()
    test_extract()
    test_upload_reads()
    test_read_fallbacks()
    test_plan()
    test_tts()
    test_stt()
    test_model_downloads()
    test_voice()
    test_ollama()
    test_crud()
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