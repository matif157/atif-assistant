"""Atif Assistant web API.

Serves the PWA and the JSON API. Local-only bind by default; Tailscale gives
you remote access without exposing a port.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, engine, learn, router
from .config import TAILSCALE_HOST, WEB_DIR
from .llm import probe_providers

app = FastAPI(title="Atif Assistant", version="0.1.0")


class Ask(BaseModel):
    question: str
    session: str | None = None


class DecisionIn(BaseModel):
    topic: str
    decision: str
    prediction: str | None = None
    confidence: float | None = None
    review_date: str | None = None


class ResolveIn(BaseModel):
    actual_outcome: str


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
async def health(probe: bool = False) -> dict:
    # `ready` is a live result, not just "a key string exists". Cached for two
    # minutes unless ?probe=1 forces a fresh check.
    providers = await probe_providers(force=probe)
    return {
        "ok": True,
        "seeded": db.is_seeded(),
        "counts": db.counts(),
        "providers": providers,
        "tailscale_host": TAILSCALE_HOST,
    }


@app.get("/api/memory")
def memory(q: str = "", limit: int = 20) -> JSONResponse:
    rows = db.search_memory(q, limit=limit) if q else []
    if not q:
        conn = db.connect()
        rows = [
            dict(r)
            for r in conn.execute(
                """SELECT 'fact' AS kind, id, text AS title,
                          text AS body, confidence, status
                   FROM facts ORDER BY confidence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        ]
    return JSONResponse({"results": rows})


async def _extract_in_background(question: str, answer: str, provider: str) -> None:
    """Learn from one exchange after the reply has already gone out.

    Runs as a background task so an extra provider call cannot slow the user
    down. Errors are swallowed: a failed extraction must not surface as a
    failed request, and must never crash the worker.
    """
    try:
        await learn.extract(question, answer, provider)
    except Exception:
        pass


@app.post("/api/ask")
async def ask(payload: Ask, background: BackgroundTasks) -> dict:
    session = payload.session or uuid.uuid4().hex[:12]

    # No mode in, no mode out. The router decides, and the user sees why.
    qclass = router.question_class(payload.question)
    repeats = db.question_count(qclass)
    route = router.route(payload.question, repeat_count=repeats)
    db.record_question(qclass, payload.question)

    ctx = engine.build_context(payload.question)
    ctx["escalations"] = route.escalations
    result = await engine.respond(
        payload.question, mode=route.mode, ctx=ctx
    )
    result["route"] = route.to_dict()
    result["asked_count"] = repeats + 1

    db.save_message(
        session,
        "user",
        payload.question,
        labels={
            "route": route.mode,
            "intent": result.get("intent"),
            "qclass": qclass,
        },
        patterns=[p["name"] for p in result.get("patterns", [])],
    )
    db.save_message(
        session,
        "assistant",
        result["text"],
        labels={
            "labels": result.get("labels", []),
            "route": route.mode,
            "warnings": result.get("warnings", []),
            "critique": result.get("critique", []),
        },
        patterns=[p["name"] for p in result.get("patterns", [])],
    )

    result["session"] = session

    # Memory extraction runs after the response is sent. It was awaited inline
    # before, which meant a slow extra provider call delayed the answer even
    # though the comment claimed otherwise.
    background.add_task(
        _extract_in_background,
        payload.question,
        result["text"],
        result.get("provider", "offline"),
    )

    return result


@app.get("/api/insights")
def insights() -> dict:
    """What the user keeps asking, and what that says about them."""
    dist = db.question_distribution()
    total = db.question_count()
    total_comparisons = next(
        (d["count"] for d in dist if d["class"] == "comparison"), 0
    )
    reading = ""
    if total_comparisons >= 5:
        reading = (
            f"{total_comparisons} of {total} questions are comparisons between "
            "people. That is the dominant shape of what you ask, and it has no "
            "possible answer."
        )
    return {
        "distribution": dist,
        "total": total,
        "comparisons": total_comparisons,
        "reading": reading,
        "contradictions": db.find_contradictions(limit=5),
    }


@app.get("/api/learned")
def learned_candidates() -> dict:
    return {"candidates": db.learned_candidates()}


@app.post("/api/learned/{fact_id}/approve")
def approve(fact_id: int) -> dict:
    fid = db.approve_learned(fact_id)
    if not fid:
        return {"ok": False, "error": "not found"}
    return {"ok": True, "fact_id": fid}


@app.post("/api/learned/{fact_id}/reject")
def reject(fact_id: int) -> dict:
    db.reject_learned(fact_id)
    return {"ok": True}


@app.get("/api/history/{session}")
def history(session: str) -> dict:
    return {"messages": db.history(session)}


@app.get("/api/evidence")
def evidence(q: str = "", limit: int = 20) -> JSONResponse:
    """Search the raw source lines behind stored memory."""
    if not q.strip():
        return JSONResponse({"results": []})
    return JSONResponse({"results": db.search_evidence(q, limit=min(limit, 100))})


@app.get("/api/decisions")
def decisions() -> dict:
    return {"due": db.due_decisions(), "open": db.open_decisions()}


@app.post("/api/decisions")
def add_decision(payload: DecisionIn) -> dict:
    did = db.add_decision(
        topic=payload.topic,
        decision=payload.decision,
        prediction=payload.prediction,
        confidence=payload.confidence,
        review_date=payload.review_date,
        decided_at=db.now(),
    )
    return {"id": did}


@app.post("/api/decisions/{decision_id}/resolve")
def resolve_decision(decision_id: int, payload: ResolveIn) -> JSONResponse:
    if not db.resolve_decision(decision_id, payload.actual_outcome):
        return JSONResponse(
            {"error": "not found, already resolved, or no outcome given"},
            status_code=404,
        )
    return JSONResponse({"ok": True, "id": decision_id})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # Served from the root, not /static, so its default scope covers the whole
    # origin. From /static/sw.js the scope would be limited to /static/, the app
    # page at / would not be controlled, and the offline shell plus
    # install-to-homescreen would silently do nothing on the phone.
    return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")


@app.get("/api/settings")
def get_settings():
    conn = db.connect()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.post("/api/settings")
def set_settings(payload: dict):
    for k, v in payload.items():
        if v is None:
            continue
        db.set_setting(str(k), str(v))
    return {"ok": True}


@app.post("/api/notes")
def add_note(payload: dict):
    nid = db.add_note(
        payload.get("title"),
        payload.get("body", ""),
        payload.get("tags"),
        payload.get("mood"),
    )
    return {"id": nid}


@app.get("/api/notes")
def list_notes(limit: int = 20):
    return {"notes": db.list_notes(limit)}


@app.get("/api/works")
def list_works(limit: int = 20):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM works ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"works": [dict(r) for r in rows]}


@app.post("/api/works")
def add_work(payload: dict):
    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO works(title, description, status, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (payload.get("title"), payload.get("description"), payload.get("status", "active"), 
         json.dumps(payload.get("data")) if payload.get("data") else None, db.now(), db.now()),
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}


@app.get("/api/media")
def list_media(limit: int = 20):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM media ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"media": [dict(r) for r in rows]}


@app.post("/api/media")
def add_media(payload: dict):
    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO media(path, kind, tags, meta, created_at) VALUES (?,?,?,?,?)",
        (payload.get("path"), payload.get("kind"), payload.get("tags"), 
         json.dumps(payload.get("meta")) if payload.get("meta") else None, db.now()),
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}


@app.get("/api/social/accounts")
def list_social_accounts():
    conn = db.connect()
    rows = conn.execute("SELECT * FROM social_accounts ORDER BY id DESC").fetchall()
    return {"accounts": [dict(r) for r in rows]}


@app.post("/api/social/accounts")
def add_social_account(payload: dict):
    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO social_accounts(platform, username, connected, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (payload.get("platform"), payload.get("username"), int(payload.get("connected", 0)), 
         json.dumps(payload.get("data")) if payload.get("data") else None, db.now(), db.now()),
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}


@app.get("/api/social/posts")
def list_social_posts(limit: int = 20):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM social_posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"posts": [dict(r) for r in rows]}


# Mounted last so the API routes above are matched before the static handler.
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
