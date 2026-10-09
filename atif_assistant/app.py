"""Atif Assistant web API.

Serves the PWA and the JSON API. Local-only bind by default; Tailscale gives
you remote access without exposing a port.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, engine, learn, location, router, uploads
from .config import PROVIDER_LABELS, PROVIDER_ORDER, TAILSCALE_HOST, WEB_DIR
from .llm import (
    invalidate_probe_cache,
    probe_providers,
    provider_status,
    test_provider,
)

app = FastAPI(title="Atif Assistant", version="0.1.0")


class Ask(BaseModel):
    question: str
    session: str | None = None
    lang: str | None = None
    detail: str | None = None


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
    ctx["language"] = payload.lang
    ctx["detail"] = payload.detail
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
    # API keys live under `provider.*`. They are never returned here; the
    # provider endpoints expose only a masked hint.
    return {
        r["key"]: r["value"]
        for r in rows
        if not r["key"].startswith("provider.")
    }


@app.post("/api/settings")
def set_settings(payload: dict):
    for k, v in payload.items():
        if v is None:
            continue
        if str(k).startswith("provider."):
            continue
        db.set_setting(str(k), str(v))
    return {"ok": True}


# ------------------------------------------------------------ providers

class ProviderIn(BaseModel):
    api_key: str | None = None
    model: str | None = None
    url: str | None = None
    clear_key: bool = False


@app.get("/api/providers")
async def list_providers(probe: bool = False) -> dict:
    """Provider config with masked keys, plus a live readiness flag."""
    live = {p["name"]: p for p in await probe_providers(force=probe)}
    providers = []
    for name in PROVIDER_ORDER:
        status = provider_status(name)
        status["ready"] = live.get(name, {}).get("ready", False)
        status["error"] = live.get(name, {}).get("error")
        providers.append(status)
    return {"providers": providers, "order": PROVIDER_ORDER}


@app.post("/api/providers/test")
async def test_all_providers() -> dict:
    """Test every provider with its stored config.

    Declared before `/api/providers/{name}` so the literal path wins; otherwise
    the path parameter would capture `test` and demand a body.
    """
    import asyncio

    results = await asyncio.gather(*(test_provider(n) for n in PROVIDER_ORDER))
    return {"results": results}


@app.post("/api/providers/{name}")
def save_provider(name: str, payload: ProviderIn) -> JSONResponse:
    """Store a provider's key/model/url, or clear its key.

    A key is stored as given, or blanked with ``clear_key``. An empty stored
    key means 'disabled' and overrides any value still present in `.env`.
    """
    if name not in PROVIDER_LABELS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    def put_or_clear(key: str, value: str | None) -> None:
        """Store a plain value; an empty/absent value removes the override."""
        if value is None:
            return
        if value.strip():
            db.set_setting(key, value.strip())
        else:
            db.delete_setting(key)

    if name == "ollama":
        put_or_clear("provider.ollama.url", payload.url)
        put_or_clear("provider.ollama.model", payload.model)
        if payload.clear_key:
            # A blank key is a deliberate override: it disables the provider.
            db.set_setting("provider.ollama.api_key", "")
        elif payload.api_key and payload.api_key.strip():
            db.set_setting("provider.ollama.api_key", payload.api_key.strip())
    else:
        if payload.clear_key:
            db.set_setting(f"provider.{name}.api_key", "")
        elif payload.api_key and payload.api_key.strip():
            db.set_setting(f"provider.{name}.api_key", payload.api_key.strip())
        put_or_clear(f"provider.{name}.model", payload.model)
    invalidate_probe_cache()
    return JSONResponse({"ok": True, "provider": provider_status(name)})


@app.post("/api/providers/{name}/test")
async def test_one_provider(name: str, payload: ProviderIn) -> JSONResponse:
    """Test a provider, optionally with values not yet saved."""
    if name not in PROVIDER_LABELS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    result = await test_provider(
        name,
        api_key=payload.api_key,
        model=payload.model,
        url=payload.url,
    )
    return JSONResponse(result)


class LocationIn(BaseModel):
    lat: float
    lon: float
    occurred_at: str | None = None
    accuracy: float | None = None
    source: str | None = None


@app.post("/api/location")
async def add_location(payload: LocationIn, geocode: bool = False) -> dict:
    """Ingest one GPS fix. Idempotent; nearby fixes fold into one place.

    Geocoding is opt-in because it needs the network and the app is local-first.
    An unnamed place still supports routine detection - the name is cosmetic.
    """
    before = {p["id"] for p in db.list_places(limit=10_000)}
    pid = db.add_location_point(
        payload.lat,
        payload.lon,
        occurred_at=payload.occurred_at,
        accuracy=payload.accuracy,
        source=payload.source,
    )
    if pid is None:
        return {"ok": True, "duplicate": True}

    point = db.connect().execute(
        "SELECT place_id FROM location_points WHERE id=?", (pid,)
    ).fetchone()
    place_id = point["place_id"] if point else None
    named = None
    if geocode and place_id not in before:
        geo = await location.reverse_geocode(payload.lat, payload.lon)
        if geo["label"]:
            db.name_place(place_id, geo["label"], geo["kind"])
            named = geo["label"]
    return {"ok": True, "id": pid, "place_id": place_id, "named": named}


@app.get("/api/location")
def list_location(limit: int = 100) -> dict:
    return {"points": db.list_location_points(limit)}


@app.get("/api/places")
def list_places(limit: int = 50) -> dict:
    return {"places": db.list_places(limit)}


@app.post("/api/places/{place_id}/name")
def name_place(place_id: int, payload: dict) -> JSONResponse:
    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    ok = db.name_place(place_id, name, payload.get("kind"))
    if not ok:
        return JSONResponse({"error": "place not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": place_id})


@app.get("/api/routines")
def list_routines(limit: int = 50) -> dict:
    return {"routines": db.list_routines(limit)}


@app.post("/api/routines/derive")
def derive_routines(min_observations: int = 3) -> dict:
    routines = db.derive_routines(min_observations=min_observations)
    return {"ok": True, "count": len(routines), "routines": routines}


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


class UploadIn(BaseModel):
    filename: str
    related_to: str | None = None
    kind: str | None = None
    text: str | None = None
    content_b64: str | None = None


@app.post("/api/upload")
def upload_file(payload: UploadIn) -> JSONResponse:
    """Ingest an uploaded file and fold its text into memory.

    JSON only (text or base64) so no multipart dependency is required. A text
    file becomes searchable evidence plus an episode labelled with ``related_to``.
    """
    try:
        report = uploads.ingest_upload(
            filename=payload.filename,
            related_to=payload.related_to,
            kind=payload.kind,
            text=payload.text,
            content_b64=payload.content_b64,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(report)


@app.get("/api/media/{media_id}/content")
def media_content(media_id: int) -> JSONResponse:
    conn = db.connect()
    row = conn.execute("SELECT path FROM media WHERE id=?", (media_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = Path(row["path"])
    if not path.exists():
        return JSONResponse({"error": "file missing"}, status_code=404)
    return JSONResponse({"path": str(path), "size": path.stat().st_size})


@app.get("/api/export")
def export_backup() -> JSONResponse:
    """Download the curated memory as JSON."""
    data = db.export_data()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    headers = {
        "Content-Disposition": f'attachment; filename="atif-backup-{stamp}.json"'
    }
    return JSONResponse(data, headers=headers)


@app.post("/api/import")
def import_backup(payload: dict) -> JSONResponse:
    """Restore a backup add-only. Never deletes or overwrites existing rows."""
    if payload.get("app") and payload.get("app") != "atif-assistant":
        return JSONResponse({"error": "not an Atif Assistant backup"}, status_code=400)
    if not isinstance(payload.get("tables"), dict):
        return JSONResponse({"error": "missing tables"}, status_code=400)
    added = db.import_data(payload)
    return JSONResponse({"ok": True, "added": added})


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
