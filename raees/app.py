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

from . import db, engine
from .config import TAILSCALE_HOST, WEB_DIR
from .llm import available_providers

app = FastAPI(title="Raees", version="0.1.0")


class Ask(BaseModel):
    question: str
    mode: str = "ask"
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
def health() -> dict:
    return {
        "ok": True,
        "seeded": db.is_seeded(),
        "counts": db.counts(),
        "providers": available_providers(),
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
    ctx = engine.build_context(payload.question)
    result = await engine.respond(payload.question, mode=payload.mode)

    db.save_message(
        session,
        "user",
        payload.question,
        labels={"mode": payload.mode, "intent": result.get("intent")},
        patterns=[p["name"] for p in result.get("patterns", [])],
    )
    db.save_message(
        session,
        "assistant",
        result["text"],
        labels={"labels": result.get("labels", [])},
        patterns=[p["name"] for p in result.get("patterns", [])],
    )

    result["session"] = session
    return result


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