"""Raees web API.

Serves the PWA and the JSON API. Local-only bind by default; Tailscale gives
you remote access without exposing a port.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, engine, learn, router
from .config import TAILSCALE_HOST, WEB_DIR
from .llm import available_providers, ollama_is_up

app = FastAPI(title="Raees", version="0.1.0")


class Ask(BaseModel):
    question: str
    session: str | None = None


class DecisionIn(BaseModel):
    topic: str
    decision: str
    prediction: str | None = None
    confidence: float | None = None
    review_date: str | None = None


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
async def health() -> dict:
    providers = available_providers()
    if not any(p["ready"] for p in providers):
        # No key set anywhere - check whether a local model is actually
        # serving before telling the user there is nothing available.
        if await ollama_is_up():
            for p in providers:
                if p["name"] == "ollama":
                    p["ready"] = True
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


@app.post("/api/ask")
async def ask(payload: Ask) -> dict:
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

    # Learn after answering, so a slow extraction never delays the reply.
    learned = await learn.extract(
        payload.question, result["text"], result.get("provider", "offline")
    )
    if learned:
        result["learned"] = learned

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


@app.get("/api/decisions")
def decisions() -> dict:
    return {"due": db.due_decisions()}


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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")