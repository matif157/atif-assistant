"""Atif Assistant web API.

Serves the PWA and the JSON API. Local-only bind by default; Tailscale gives
you remote access without exposing a port.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import (
    applog, constitution, db, engine, learn, llm, location, ollama, pipeline, plan,
    reflection, router, stt, style, tts, uploads, voice_id,
)
from .config import DATA_DIR, DB_PATH, PROVIDER_LABELS, PROVIDER_ORDER, TAILSCALE_HOST, WEB_DIR
from .importers import whatsapp
from .importers import whatsapp_txt
from .importers import calendar as importer_calendar
from .importers import contacts as importer_contacts
from .importers import mail as importer_mail
from .importers import notes as importer_notes
from .importers import photos as importer_photos

# The five light sources (Phase 6) all follow the same contract: preview
# candidates read-only, stage them as LEARNED rows the user then approves.
# WhatsApp keeps its own richer chat-picker routes above.
IMPORTERS = {
    "contacts": importer_contacts,
    "calendar": importer_calendar,
    "mail": importer_mail,
    "notes": importer_notes,
    "photos": importer_photos,
}
from .llm import (
    invalidate_probe_cache,
    llm_download_pause,
    llm_download_start,
    llm_model_status,
    probe_providers,
    provider_status,
    test_provider,
    visible_providers,
)

app = FastAPI(title="Atif Assistant", version="0.1.0")


@app.middleware("http")
async def web_password_gate(request: Request, call_next):
    """Optional gate for public URLs (tunnels, hosted deployments).

    Set ``ATIF_ASSISTANT_WEB_PASSWORD`` and every request needs HTTP Basic
    auth — the browser prompts once and then attaches the header to all
    fetches automatically, so the UI needs no changes. Unset = no gate,
    which keeps local/Tailscale use exactly as before.
    """
    expected = os.environ.get("ATIF_ASSISTANT_WEB_PASSWORD", "")
    if not expected:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            _user, _sep, password = decoded.partition(":")
            if secrets.compare_digest(password, expected):
                return await call_next(request)
        except Exception:  # noqa: BLE001 - malformed header just fails the gate
            pass
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Atif Assistant"'},
    )


class Ask(BaseModel):
    question: str
    session: str | None = None
    lang: str | None = None
    reply_language: str | None = None
    detail: str | None = None
    speaker: str | None = None
    speaker_score: float | None = None


class TtsIn(BaseModel):
    text: str
    lang: str | None = None


class SttIn(BaseModel):
    audio: str
    lang: str | None = None
    identify: bool = True


class VoiceEnrollIn(BaseModel):
    name: str
    audio: str


class VoiceAudioIn(BaseModel):
    audio: str


class DecisionIn(BaseModel):
    topic: str
    decision: str
    prediction: str | None = None
    confidence: float | None = None
    review_date: str | None = None


class ResolveIn(BaseModel):
    actual_outcome: str


class LearnedUpdate(BaseModel):
    text: str | None = None
    subject: str | None = None
    kind: str | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # The vocabulary is fixed; anything else would create a row that no
    # filter in the UI can ever show again.
    status: Literal["candidate", "approved", "rejected"] | None = None


class LearnedBulk(BaseModel):
    action: str = Field(..., pattern=r"^(approve|reject|delete)$")
    ids: list[int] = Field(default_factory=list)


class DecisionUpdate(BaseModel):
    topic: str | None = None
    decision: str | None = None
    prediction: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_date: str | None = None
    actual_outcome: str | None = None
    resolved_at: str | None = None


class ContradictionMerge(BaseModel):
    keep_id: int
    remove_id: int
    reconciled_text: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MediaBulkDelete(BaseModel):
    ids: list[int] = Field(default_factory=list)


class PlanIn(BaseModel):
    media_id: int | None = None
    text: str | None = None
    related_to: str | None = None
    strict: bool = True


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # Bring the local offline model host up in the background if it is installed
    # and not already running, so offline chat works without a terminal.
    ollama.ensure_autostart()
    _resume_partial_downloads()
    return None


def _ram_gb() -> float | None:
    """Physical RAM in GiB, or None where the OS will not say."""
    try:  # Android and Linux expose this world-readable
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1048576, 1)
    except OSError:
        pass
    try:  # macOS has no SC_PHYS_PAGES; raises ValueError there
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page > 0:
            return round(pages * page / (1024 ** 3), 1)
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _resume_partial_downloads() -> None:
    """Continue downloads a previous session started, after any restart.

    Only fires when a .part file exists (the user really began that download)
    and the user has not pressed pause (that intent is stored as
    ``models.auto_resume``). Never starts a download nobody asked for.
    """
    try:
        if db.get_setting("models.auto_resume", "on") == "off":
            return
        for name in llm.LLM_MODEL_URLS:
            if llm._part_file(name).is_file():
                llm.llm_download_start(name)
        for name in stt.MODEL_URLS:
            if (stt.model_dir() / f"{name}.part").is_file():
                stt.stt_download_start(name)
    except Exception:  # noqa: BLE001 - resume must never block boot
        pass


@app.get("/api/setup")
def setup_info() -> dict:
    """First-run facts: device RAM tier, free storage, and the two model sets.

    The Quick set exists for low-RAM phones and flaky connections; the Full
    set is the accuracy choice. The UI shows the recommendation but never
    forces it.
    """
    ram = _ram_gb()
    recommended = "quick" if (ram is not None and ram < 3.5) else "full"
    try:
        free = shutil.disk_usage(DATA_DIR).free
    except OSError:
        free = 0
    sets = {
        "quick": {
            "llm": "qwen2.5-0.5b", "llm_mib": 469,
            "stt": "ggml-base.bin", "stt_mib": 141,
            "total_mib": 610, "label": "Quick set - about 610 MB",
        },
        "full": {
            "llm": "qwen2.5-1.5b", "llm_mib": 1066,
            "stt": "ggml-small.bin", "stt_mib": 465,
            "total_mib": 1531, "label": "Full set - about 1.5 GB",
        },
    }
    return {
        "device": {"ram_gb": ram},
        "storage": {"free_bytes": free},
        "sets": sets,
        "recommended": recommended,
        "warn_bytes": int(sets[recommended]["total_mib"] * 1048576 * 1.1),
    }


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
        "speech": {
            "server": tts.server_available(),
            "offline_out": tts.offline_available(),
            "offline_in": stt.status(),
            "speaker_id": voice_id.status(),
        },
        "ollama": ollama.status(),
        "tailscale_host": TAILSCALE_HOST,
    }


@app.get("/api/version")
def version() -> dict:
    """Which build this instance is running.

    Every target (Mac, web, Android) serves the same code, so a commit hash
    is how you check that all three deployments are actually in sync.
    ``ATIF_ASSISTANT_COMMIT`` is set by CI/containers; local runs fall back
    to git, and the APK reports ``dev``.
    """
    commit = os.environ.get("ATIF_ASSISTANT_COMMIT", "")
    if not commit:
        try:
            commit = (
                subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=2,
                    cwd=Path(__file__).resolve().parent.parent,
                ).stdout.strip()
                or "dev"
            )
        except Exception:  # noqa: BLE001 - no git on device/in containers
            commit = "dev"
    return {"app": "atif-assistant", "version": "1.0.0", "commit": commit}


@app.get("/api/backup")
def backup(token: str = "") -> Response:
    """Download memory + uploads as a zip (models excluded - they re-download).

    Guarded by ``ATIF_ASSISTANT_BACKUP_TOKEN``; when that env var is unset the
    endpoint does not exist. On a hosted instance this is how memory survives
    a redeploy; on a phone it is the export button.
    """
    expected = os.environ.get("ATIF_ASSISTANT_BACKUP_TOKEN", "")
    if not expected or token != expected:
        return JSONResponse({"error": "not available"}, status_code=404)
    import tempfile
    import zipfile

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.is_file():
            zf.write(DB_PATH, "atif-assistant.db")
        uploads = DATA_DIR / "uploads"
        if uploads.is_dir():
            for path in sorted(uploads.rglob("*")):
                if path.is_file():
                    zf.write(path, str(path.relative_to(DATA_DIR)))

    def _cleanup(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    return FileResponse(
        tmp.name,
        media_type="application/zip",
        background=BackgroundTask(_cleanup, tmp.name),
        headers={"Content-Disposition": 'attachment; filename="atif-assistant-backup.zip"'},
    )


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


@app.post("/api/tts")
def make_speech(payload: TtsIn) -> Response:
    """Synthesize a spoken reply server-side.

    Used for languages with no local browser voice (notably Urdu). Falls back
    with a clear reason so the client can use its own voices instead.
    """
    result = tts.synthesize(payload.text, payload.lang or "en")
    audio = result.get("audio")
    if not audio:
        return JSONResponse(
            {"error": result.get("reason") or "speech unavailable"}, status_code=503
        )
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/stt")
def make_transcript(payload: SttIn) -> JSONResponse:
    """Transcribe a recorded WAV clip locally with whisper.cpp.

    The browser Web Speech API needs a network; this endpoint turns a recorded
    clip into text offline (Urdu included) when whisper.cpp and a model are
    installed. It fails with a clear reason so the client can fall back.
    """
    try:
        raw = base64.b64decode(payload.audio, validate=False)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "audio was not valid base64"}, status_code=400)
    result = stt.transcribe(raw, payload.lang or "auto")
    if not result.get("text"):
        return JSONResponse(
            {"error": result.get("reason") or "speech recognition unavailable"},
            status_code=503,
        )
    speaker = None
    if payload.identify:
        speaker = _identify_speaker(raw)
    return JSONResponse(
        {"text": result["text"], "meta": result.get("meta") or {}, "speaker": speaker},
        headers={"Cache-Control": "no-store"},
    )


def _identify_speaker(raw: bytes) -> dict | None:
    """Attribute a clip to a saved person, if the engine and prints exist.

    Best-effort and advisory: returns None whenever anything is missing rather
    than failing the transcription that already succeeded.
    """
    if not voice_id.available():
        return None
    prints = db.voiceprints()
    if not prints:
        return None
    embedding = voice_id.embed_wav(raw)
    return voice_id.identify(embedding, prints)


@app.get("/api/speech")
def speech_status() -> dict:
    """What the offline speech stack currently has, and what it could fetch."""
    return {"stt": stt.status(), "tts": tts.status()}


@app.post("/api/speech/model")
def download_speech_model(payload: dict | None = None) -> JSONResponse:
    """Download a better offline Whisper model (default: small, best for Urdu).

    ``{"background": true}`` returns immediately and lets the client poll
    GET /api/speech for progress - a phone-side fetch of the 466 MB model must
    not hold one HTTP request open for minutes. ``{"action": "pause"}`` stops
    an in-flight download and keeps its partial file for a later resume.
    """
    body = payload or {}
    if body.get("action") == "pause":
        result = stt.stt_download_pause()
        if result.get("reason") == "pausing":
            db.set_setting("models.auto_resume", "off")
        return JSONResponse(result)
    name = body.get("name") or stt.PREFERRED_MODEL
    if name not in stt.MODEL_URLS:
        return JSONResponse({"error": f"unknown model {name!r}"}, status_code=400)
    if body.get("background"):
        db.set_setting("models.auto_resume", "on")
        result = stt.stt_download_start(name)
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    result = stt.download_model(name)
    if not result.get("ok"):
        return JSONResponse(result, status_code=503)
    return JSONResponse(result)


@app.get("/api/llm")
def llm_status() -> dict:
    """On-device LLM: binary, model file, server and download progress."""
    return llm_model_status()


@app.get("/api/app-log")
def app_log(limit: int = 50) -> dict:
    """Recent runtime events (model downloads, provider spawns, failures).

    On-device stdout vanishes into logcat; this is the readable mirror for
    the UI and for adb-based debugging.
    """
    return {"events": applog.tail(limit)}


@app.post("/api/llm/model")
def llm_model_download(payload: dict | None = None) -> JSONResponse:
    """Start fetching the offline model in the background; poll GET /api/llm.

    ``{"action": "pause"}`` stops the download but never deletes the bytes
    already fetched - the next start resumes from there.
    """
    body = payload or {}
    if body.get("action") == "pause":
        result = llm_download_pause()
        if result.get("reason") == "pausing":
            db.set_setting("models.auto_resume", "off")
        return JSONResponse(result)
    name = body.get("name")
    db.set_setting("models.auto_resume", "on")
    result = llm_download_start(name)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.get("/api/voiceprints")
def get_voiceprints() -> dict:
    """Saved people plus the speaker-identification engine status."""
    return {
        "engine": voice_id.status(),
        "voiceprints": db.list_voiceprints(),
        "count": len(db.list_voiceprints()),
    }


@app.post("/api/voiceprints")
def enroll_voiceprint(payload: VoiceEnrollIn) -> JSONResponse:
    """Enrol a person's voice from a short clip so their speech is recognised."""
    name = (payload.name or "").strip()
    if not name:
        return JSONResponse({"error": "a name is required"}, status_code=400)
    if not voice_id.available():
        return JSONResponse(
            {
                "error": "speaker identification is not installed",
                "hint": "Download the voice model in Settings, or install sherpa-onnx.",
            },
            status_code=503,
        )
    try:
        raw = base64.b64decode(payload.audio, validate=False)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "audio was not valid base64"}, status_code=400)
    embedding = voice_id.embed_wav(raw)
    if not embedding:
        return JSONResponse(
            {"error": "could not read a voice in that clip; record 2-3 seconds of speech"},
            status_code=400,
        )
    vid = db.add_voiceprint(payload.name.strip(), embedding)
    saved = next((p for p in db.list_voiceprints() if p["id"] == vid), None)
    return JSONResponse({"ok": True, "voiceprint": saved})


@app.delete("/api/voiceprints/{voiceprint_id}")
def delete_voiceprint(voiceprint_id: int) -> JSONResponse:
    ok = db.remove_voiceprint(voiceprint_id)
    if not ok:
        return JSONResponse({"error": "no such voiceprint"}, status_code=404)
    return JSONResponse({"ok": True})


@app.post("/api/voice/identify")
def identify_voice(payload: VoiceAudioIn) -> JSONResponse:
    """Say who a clip belongs to, without transcribing it."""
    if not voice_id.available():
        return JSONResponse(
            {"error": "speaker identification unavailable"}, status_code=503
        )
    try:
        raw = base64.b64decode(payload.audio, validate=False)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "audio was not valid base64"}, status_code=400)
    embedding = voice_id.embed_wav(raw)
    if embedding is None:
        return JSONResponse({"error": "could not read a voice in that clip"}, status_code=400)
    return JSONResponse(
        {
            "match": voice_id.identify(embedding, db.voiceprints()),
            "threshold": voice_id.threshold(),
        }
    )


@app.post("/api/voice/model")
def download_voice_model(payload: dict | None = None) -> JSONResponse:
    """Download a speaker-embedding model for offline voice identification."""
    name = (payload or {}).get("name") or voice_id.DEFAULT_MODEL
    result = voice_id.download_model(name)
    if not result.get("ok"):
        status = 400 if "unknown model" in (result.get("reason") or "") else 503
        return JSONResponse(result, status_code=status)
    return JSONResponse(result)


async def _extract_in_background(question: str, answer: str, provider: str) -> None:
    """Learn from one exchange after the reply has already gone out.

    Runs as a background task so an extra provider call cannot slow the user
    down. Errors are swallowed: a failed extraction must not surface as a
    failed request, and must never crash the worker.
    """
    try:
        _extract_tasks(question)
    except Exception:
        pass
    try:
        await learn.extract(question, answer, provider)
    except Exception:
        pass


# Phase 6: to-do capture runs on the user's own words only. The cue list is
# deliberately conservative - an over-capture is a visible todo they delete,
# an invented task would be a lie - and it never invents a due time.
_TASK_CUES = (
    "remind me to", "remind me", "don't let me forget", "do not let me forget",
    "remember to", "still need to", "need to finish", "have to finish",
    "got to finish", "must finish", "forgot to", "i owe",
    "karna hai", "karnay hai", "karna para", "karnay paray", "karna parega",
    "yaad dilana", "bhoolna mat", "bhool na jana",
)


def _extract_tasks(question: str) -> int:
    """Pull a to-do out of what the user typed. Returns 1 only when a new
    todo appeared - saying the same thing twice is still one task."""
    text = " ".join(question.split())[:300]
    if not constitution._matches(text.casefold(), _TASK_CUES):
        return 0
    before = {t["id"] for t in db.list_todos(limit=500)}
    tid = db.add_todo(text, origin="chat", source=None)
    return 0 if tid in before else 1


def _prepare_ask(payload: Ask) -> dict:
    """Route, context, language - everything generation needs.

    Shared verbatim by the blocking and the streaming endpoint so the two
    cannot diverge on routing, Urdu-first social handling, mood or style.
    """
    session = payload.session or uuid.uuid4().hex[:12]

    # No mode in, no mode out. The router decides, and the user sees why.
    qclass = router.question_class(payload.question)
    repeats = db.question_count(qclass)
    route = router.route(payload.question, repeat_count=repeats)
    db.record_question(qclass, payload.question)
    # Mirror layer (Phase 3): fold this message into the style profile. One
    # sqlite write, so it stays inline with the ask.
    style.observe(payload.question)

    # Trajectory + few-shot examples need the user's previous turns in this
    # session, read before the current exchange is saved (oldest first).
    recent = [
        m["content"]
        for m in db.history(session)
        if m.get("role") == "user"
    ][-4:]

    ctx = engine.build_context(payload.question, recent=recent)
    ctx["escalations"] = route.escalations
    # The reply language follows the question when the setting is "auto" (the
    # default), so speaking Urdu is answered in Urdu without touching a setting.
    forced = (
        payload.reply_language
        if payload.reply_language is not None
        else db.get_setting("reply_language", "auto")
    )
    resolved_lang = engine.resolve_language(forced, payload.question)
    # Urdu-first persona: a social/pleasantry turn opens in Urdu/Roman Urdu
    # even when the greeting was typed in English - unless the user pinned a
    # language explicitly.
    if route.social and not (forced or "auto").strip().lower().startswith(
        ("en", "ur")
    ):
        resolved_lang = "ur"
    ctx["language"] = resolved_lang
    ctx["detail"] = payload.detail
    # A voice-identified speaker is advisory context only; it never becomes a
    # stored fact and is labelled as a guess in the guardrails.
    if payload.speaker:
        ctx["speaker"] = {"name": payload.speaker, "score": payload.speaker_score}
    return {
        "question": payload.question,
        "session": session,
        "qclass": qclass,
        "repeats": repeats,
        "route": route,
        "ctx": ctx,
        "language": resolved_lang,
    }


def _finalize_ask(
    prepared: dict,
    result: dict,
    background: BackgroundTasks | None,
    *,
    user_saved: bool = False,
) -> dict:
    """Persist the exchange and decorate the result (shared by both ends)."""
    session = prepared["session"]
    route = prepared["route"]
    result["route"] = route.to_dict()
    result["asked_count"] = prepared["repeats"] + 1
    result["language"] = prepared["language"]

    if not user_saved:
        uid = db.save_message(
            session,
            "user",
            prepared["question"],
            labels={
                "route": route.mode,
                "intent": result.get("intent"),
                "qclass": prepared["qclass"],
            },
            patterns=[p["name"] for p in result.get("patterns", [])],
        )
        result["user_message_id"] = uid
    bid = db.save_message(
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
    result["message_id"] = bid

    result["session"] = session
    # Soul layer exposure: the mood chip in the UI, and the trajectory the
    # reflection loop will read later (Phase 4).
    ctx = prepared["ctx"]
    result["mood"] = ctx.get("mood")
    result["mood_trajectory"] = ctx.get("mood_trajectory")
    mood = ctx.get("mood") or {}
    if mood.get("mood", "neutral") != "neutral":
        db.log_mood(
            mood["mood"],
            score=float(mood.get("score") or 0.0),
            cues=mood.get("cues") or [],
            trajectory=ctx.get("mood_trajectory"),
            session=session,
        )

    # Memory extraction runs after the response is sent. It was awaited inline
    # before, which meant a slow extra provider call delayed the answer even
    # though the comment claimed otherwise.
    if background is not None:
        background.add_task(
            _extract_in_background,
            prepared["question"],
            result["text"],
            result.get("provider", "offline"),
        )
    return result


@app.post("/api/ask")
async def ask(payload: Ask, background: BackgroundTasks) -> dict:
    prepared = _prepare_ask(payload)
    result = await engine.respond(
        payload.question, mode=prepared["route"].mode, ctx=prepared["ctx"]
    )
    return _finalize_ask(prepared, result, background)


def _save_stopped(session: str, prepared: dict, text: str) -> None:
    """Persist a STOPPED partial answer, clearly marked, and nothing else.

    The memory extractor never runs over half an answer; the marker lets the
    UI and later phases tell a stop from a finished reply.
    """
    if not text.strip():
        return
    try:
        db.save_message(
            session,
            "assistant",
            text,
            labels={"stopped": True, "route": prepared["route"].mode},
            patterns=[],
        )
    except Exception:  # noqa: BLE001 - teardown must never raise
        pass


@app.post("/api/ask/stream")
async def ask_stream(payload: Ask, background: BackgroundTasks) -> StreamingResponse:
    """NDJSON stream: ``{"delta": ...}`` lines while the model writes, one
    ``{"final": {...}}`` line at the end (same shape as /api/ask).

    The user's question is persisted before the first delta, so a client that
    presses STOP never loses the turn; the partial answer is saved flagged
    ``stopped``. challenge/decide modes arrive as a single final event.
    """
    prepared = _prepare_ask(payload)
    session = prepared["session"]

    async def gen():
        uid = db.save_message(
            session,
            "user",
            payload.question,
            labels={
                "route": prepared["route"].mode,
                "qclass": prepared["qclass"],
            },
            patterns=[],
        )
        partial: list[str] = []
        try:
            async for event in engine.respond_stream(
                payload.question,
                mode=prepared["route"].mode,
                ctx=prepared["ctx"],
            ):
                if "final" in event:
                    event["final"]["user_message_id"] = uid
                    _finalize_ask(prepared, event["final"], background, user_saved=True)
                    yield json.dumps(event) + "\n"
                else:
                    partial.append(event.get("delta", ""))
                    yield json.dumps(event) + "\n"
        except (GeneratorExit, asyncio.CancelledError):
            _save_stopped(session, prepared, "".join(partial))
            raise
        except Exception:
            _save_stopped(session, prepared, "".join(partial))
            raise

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


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
def learned_candidates(status: str = "candidate") -> JSONResponse:
    """Learned rows for one bucket: candidate (default), approved, rejected, all.

    Kept under the original ``candidates`` key so existing clients keep
    working; a bad bucket is refused rather than silently returning a queue
    the caller did not ask for.
    """
    if status not in {"candidate", "approved", "rejected", "all"}:
        return JSONResponse(
            {"error": "status must be candidate, approved, rejected or all"},
            status_code=400,
        )
    return JSONResponse({"candidates": db.learned_by_status(status), "status": status})


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


@app.get("/api/import/whatsapp/status")
def wa_status() -> JSONResponse:
    try:
        s = whatsapp.get_status()
        return JSONResponse(s)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"exists": False, "chats": [], "error": str(e)})


@app.post("/api/import/whatsapp/preview")
def wa_preview(payload: dict) -> JSONResponse:
    try:
        chat_ids = payload.get("chat_ids") if isinstance(payload, dict) else None
        if chat_ids is not None:
            if not isinstance(chat_ids, list) or not all(isinstance(x, int) for x in chat_ids):
                return JSONResponse({"error": "invalid chat_ids"}, status_code=400)
        from_me = payload.get("from_me") if isinstance(payload, dict) else None
        if from_me is not None and not isinstance(from_me, bool):
            from_me = None
        limit = payload.get("limit", 50) if isinstance(payload, dict) else 50
        offset = payload.get("offset", 0) if isinstance(payload, dict) else 0
        date_from = payload.get("date_from") if isinstance(payload, dict) else None
        date_to = payload.get("date_to") if isinstance(payload, dict) else None
        try:
            limit = int(limit)
            offset = int(offset)
        except Exception:
            return JSONResponse({"error": "invalid params"}, status_code=400)
        res = whatsapp.preview_messages(
            chat_ids=chat_ids,
            from_me=from_me,
            limit=limit,
            offset=offset,
            date_from=date_from if isinstance(date_from, str) else None,
            date_to=date_to if isinstance(date_to, str) else None,
        )
        return JSONResponse(res)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/import/whatsapp/stage")
def wa_stage(payload: dict) -> JSONResponse:
    try:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "no items"}, status_code=400)
        staged = 0
        skipped: list[dict[str, Any]] = []
        conn = db.connect()
        # load existing learned whatsapp entries for dedup
        existing = conn.execute("SELECT id, source FROM learned WHERE kind='whatsapp'").fetchall()
        for it in items:
            try:
                msg_id = int(it.get("msg_id")) if it.get("msg_id") is not None else None
                chat_id = int(it.get("chat_id")) if it.get("chat_id") is not None else None
            except Exception:
                skipped.append({"reason": "invalid ids", "item": it})
                continue
            text = str(it.get("text") or "").strip()
            if not text or msg_id is None or chat_id is None:
                skipped.append({"reason": "invalid item", "item": {"msg_id": msg_id, "chat_id": chat_id}})
                continue
            # dedup
            is_dup = False
            for ex in existing:
                src = ex["source"] or ""
                if f"msg_id={msg_id}" in src and f"chat_id={chat_id}" in src:
                    is_dup = True
                    break
            if is_dup:
                skipped.append({"reason": "already staged or exists", "item": {"msg_id": msg_id, "chat_id": chat_id}})
                continue
            chat_name = it.get("chat_name") or f"chat-{chat_id}"
            from_me = bool(it.get("from_me"))
            when = it.get("when") if isinstance(it.get("when"), str) else ""
            src = f"whatsapp:desktop|chat_id={chat_id}|chat_name={chat_name}|msg_id={msg_id}|from_me={1 if from_me else 0}|when={when}"
            db.add_learned(text=text, kind="whatsapp", source=src, confidence=0.7, subject=None)
            staged += 1
        return JSONResponse({"staged": staged, "skipped": skipped, "total": len(items)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/import/whatsapp-txt/preview")
def wtxt_preview(payload: dict) -> JSONResponse:
    """Parse an exported WhatsApp .txt chat and return selectable messages.

    The phone-side path: WhatsApp exports a chat to plain text, the WebView
    reads the file, and only the parse result comes here - so this endpoint
    never touches the filesystem and works identically in the APK.
    """
    try:
        if not isinstance(payload, dict):
            return JSONResponse({"error": "invalid payload"}, status_code=400)
        content = payload.get("content")
        filename = payload.get("filename")
        if not isinstance(content, str) or not isinstance(filename, str):
            return JSONResponse({"error": "content and filename required"}, status_code=400)
        try:
            limit = int(payload.get("limit", 500))
            offset = int(payload.get("offset", 0))
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid params"}, status_code=400)
        limit = max(1, min(limit, 2000))
        offset = max(0, offset)
        recent_first = bool(payload.get("recent_first", False))
        try:
            res = whatsapp_txt.parse_export(content, filename)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        msgs = res["messages"]
        total = len(msgs)
        if recent_first:
            view = list(reversed(msgs))[offset:offset + limit]
        else:
            view = msgs[offset:offset + limit]
        return JSONResponse({
            "chat": res["chat"],
            "total": total,
            "shown": len(view),
            "offset": offset,
            "recent_first": recent_first,
            "messages": view,
        })
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/import/whatsapp-txt/stage")
def wtxt_stage(payload: dict) -> JSONResponse:
    """Stage selected exported messages as LEARNED candidates.

    Dedupe is by content key (chat|sender|timestamp|text), so re-importing
    the same or a re-exported file never duplicates a message - unlike the
    desktop importer, this does not rely on row ids surviving an export.
    """
    try:
        if not isinstance(payload, dict):
            return JSONResponse({"error": "invalid payload"}, status_code=400)
        chat = str(payload.get("chat") or "").strip() or "chat"
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "no items"}, status_code=400)
        staged = 0
        skipped: list[dict[str, Any]] = []
        conn = db.connect()
        existing = conn.execute(
            "SELECT source FROM learned WHERE kind='whatsapp'"
        ).fetchall()
        have = {ex["source"] or "" for ex in existing}
        for it in items:
            text = str((it or {}).get("text") or "").strip()
            sender = str((it or {}).get("from") or "").strip()
            when = str((it or {}).get("when") or "").strip()
            if not text:
                skipped.append({"reason": "empty text"})
                continue
            key = hashlib.sha1(
                f"{chat}|{sender}|{when}|{text}".encode("utf-8")
            ).hexdigest()[:16]
            marker = f"h={key}"
            if any(marker in s for s in have):
                skipped.append({"reason": "already staged", "key": key})
                continue
            src = f"whatsapp:txt|chat={chat}|{marker}|when={when}|from={sender or '?'}"
            db.add_learned(text=text, kind="whatsapp", source=src, confidence=0.7)
            staged += 1
        return JSONResponse({"staged": staged, "skipped": skipped, "total": len(items)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/inbox/whatsapp")
def inbox_whatsapp(payload: dict) -> JSONResponse:
    """Push endpoint for the Android notification listener (Phase 8).

    Called by MessageListenerService inside the app process whenever WhatsApp
    posts/updates a notification. Loopback-only server; duplicates (the same
    notification re-firing) collapse on the content key.
    """
    try:
        if not isinstance(payload, dict):
            return JSONResponse({"error": "invalid payload"}, status_code=400)
        package = str(payload.get("package") or "com.whatsapp")
        if package not in {"com.whatsapp", "com.whatsapp.w4b"}:
            return JSONResponse({"error": "unsupported package"}, status_code=400)
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "empty text"}, status_code=400)
        text = text[:4000]
        chat = str(payload.get("chat") or "").strip() or "unknown"
        chat = chat[:200]
        sender = payload.get("sender")
        sender = str(sender)[:200] if isinstance(sender, str) and sender.strip() else None
        post_time = payload.get("post_time")
        post_time = str(post_time) if isinstance(post_time, (int, float)) else None
        key = hashlib.sha1(f"{package}|{chat}|{text}".encode("utf-8")).hexdigest()[:16]
        iid = db.add_inbox(
            package=package, chat=chat, text=text, msg_key=key,
            sender=sender, post_time=post_time,
        )
        if iid is None:
            return JSONResponse({"ok": True, "dup": True})
        return JSONResponse({"ok": True, "dup": False, "id": iid})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/inbox")
def inbox_list(limit: int = 50, chat: str | None = None) -> JSONResponse:
    items = db.recent_inbox(limit=limit, chat=chat)
    watched = (db.get_profile("auto_reply") or {}).get("watched", {})
    for it in items:
        it["watched"] = bool(watched.get(it["chat"]))
    return JSONResponse({"items": items})


@app.get("/api/import/{source}/preview")
def import_preview(source: str, limit: int = 100) -> JSONResponse:
    """Read-only candidate preview for one of the five light sources."""
    mod = IMPORTERS.get(source)
    if mod is None:
        return JSONResponse(
            {"error": f"unknown source (expected one of {sorted(IMPORTERS)})"},
            status_code=400,
        )
    try:
        return JSONResponse(mod.import_from_db(limit=min(max(limit, 1), 500)))
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/import/{source}/stage")
def import_stage(source: str, payload: dict) -> JSONResponse:
    """Stage selected candidates as LEARNED rows - propose-then-approve:
    nothing here becomes a fact until the user approves it in LEARNED."""
    if source not in IMPORTERS:
        return JSONResponse({"error": "unknown source"}, status_code=400)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return JSONResponse({"error": "no items"}, status_code=400)
    staged = 0
    skipped: list = []
    conn = db.connect()
    seen = {
        r["source"]
        for r in conn.execute(
            "SELECT source FROM learned WHERE kind=? AND source IS NOT NULL",
            (source,),
        ).fetchall()
    }
    for it in items:
        if not isinstance(it, dict):
            skipped.append({"reason": "invalid item", "item": it})
            continue
        title = str(it.get("title") or "").strip()
        cid = it.get("id")
        if not title or cid in (None, ""):
            skipped.append({"reason": "invalid item", "item": it})
            continue
        detail = str(it.get("detail") or "").strip()
        when = str(it.get("when") or "").strip()
        text = f"{title} - {detail}" if detail else title
        if when:
            text = f"{text} ({when[:10]})"
        src = f"{source}:id={cid}"
        if src in seen:
            skipped.append({"reason": "already staged", "item": {"id": cid}})
            continue
        db.add_learned(text=text, kind=source, source=src, confidence=0.6, subject=None)
        seen.add(src)
        staged += 1
    return JSONResponse({"staged": staged, "skipped": skipped, "total": len(items)})


@app.get("/api/history/{session}")
def history(session: str) -> dict:
    return {"messages": db.history(session)}


@app.get("/api/sessions")
def sessions(limit: int = 50) -> dict:
    return {"sessions": db.list_sessions(limit=min(max(limit, 1), 200))}


@app.get("/api/mood")
def mood(limit: int = 50) -> dict:
    """The detected-mood timeline (inference only, newest first)."""
    return {"mood": db.mood_timeline(limit=min(max(limit, 1), 200))}


@app.get("/api/home")
def home() -> dict:
    """Home dashboard aggregate: today's shape of the assistant in one
    round trip. Phase 6 hangs routines/notes/reminders off the same tiles."""
    counts = db.counts()
    moods = db.mood_timeline(30)
    latest = None
    for m in reversed(moods):
        if (m.get("mood") or "neutral") != "neutral":
            latest = m
            break
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "today": db.today_activity(),
        "sessions": db.session_count(),
        "messages": counts["messages"],
        "evidence": counts["evidence"],
        "routines": counts["routines"],
        "notes": counts["notes"],
        "pending_reflections": len(db.list_reflections(limit=100, status="pending")),
        "feedback": db.feedback_counts(),
        "mood": latest,
        "due_decisions": len(db.due_decisions()),
        "todos": len(db.list_todos(open_only=True, limit=500)),
        "reminders": len(db.list_reminders(limit=500)),
        "places": counts["places"],
        "recent": [
            {
                "session": s["session"],
                "preview": (s["last_message"] or "")[:80],
                "messages": s["messages"],
            }
            for s in db.list_sessions(limit=3)
        ],
    }


class TodoIn(BaseModel):
    text: str
    due: str | None = None


class ReminderIn(BaseModel):
    text: str
    # Optional here (not required) so a missing time gets this endpoint's
    # explicit 400 instead of an opaque 422 from request validation.
    due_at: str | None = None


@app.get("/api/todos")
def todos(open_only: bool = True, limit: int = 100) -> dict:
    return {"todos": db.list_todos(open_only=open_only, limit=min(max(limit, 1), 500))}


@app.post("/api/todos")
def create_todo(payload: TodoIn) -> JSONResponse:
    text = " ".join(payload.text.split())
    if not text:
        return JSONResponse({"error": "empty todo"}, status_code=400)
    tid = db.add_todo(text[:300], due=payload.due, origin="manual")
    return {"ok": True, "id": tid}


@app.post("/api/todos/{todo_id}/toggle")
def toggle_todo(todo_id: int, payload: dict) -> JSONResponse:
    done = bool(payload.get("done", True)) if isinstance(payload, dict) else True
    if not db.set_todo_done(todo_id, done):
        return JSONResponse({"error": "no such todo"}, status_code=404)
    return {"ok": True, "id": todo_id, "done": done}


@app.delete("/api/todos/{todo_id}")
def remove_todo(todo_id: int) -> JSONResponse:
    if not db.delete_todo(todo_id):
        return JSONResponse({"error": "no such todo"}, status_code=404)
    return {"ok": True, "id": todo_id}


@app.get("/api/reminders")
def reminders(include_fired: bool = False, limit: int = 100) -> dict:
    return {
        "reminders": db.list_reminders(
            limit=min(max(limit, 1), 500), include_fired=include_fired
        )
    }


@app.post("/api/reminders")
def create_reminder(payload: ReminderIn) -> JSONResponse:
    text = " ".join(payload.text.split())
    if not text or not payload.due_at:
        return JSONResponse({"error": "text and due_at are required"}, status_code=400)
    rid = db.add_reminder(text[:300], payload.due_at)
    return {"ok": True, "id": rid}


@app.get("/api/reminders/due")
def reminders_due() -> dict:
    """Unfired reminders whose time has passed. The client notifies (or
    toasts) and then POSTs /fire, so nothing is delivered twice."""
    return {"due": db.due_reminders()}


@app.post("/api/reminders/{reminder_id}/fire")
def fire_reminder(reminder_id: int) -> JSONResponse:
    if not db.fire_reminder(reminder_id):
        return JSONResponse({"error": "no such reminder"}, status_code=404)
    return {"ok": True, "id": reminder_id}


class ProfileIn(BaseModel):
    """Editable Profile-card overrides. Omitted fields stay untouched.

    The wire name stays ``register``; the Python field is ``register_value``
    because pydantic's BaseModel already has a ``register`` attribute.
    """

    model_config = {"populate_by_name": True}

    length: str | None = None
    register_value: str | None = Field(default=None, alias="register")
    language: str | None = None


@app.get("/api/profile")
def profile_card() -> dict:
    """Learned style + the user's own overrides for the Profile card."""
    return {
        "style": db.get_profile("style") or {},
        "overrides": db.get_profile("style_overrides") or {},
    }


@app.post("/api/profile")
def update_profile(payload: ProfileIn) -> JSONResponse:
    allowed = {
        "length": style.LENGTH_KEYS,
        "register": style.REGISTER_KEYS,
        "language": style.LANGUAGE_KEYS,
    }
    current = db.get_profile("style_overrides") or {}
    changed = False
    for field, keys in allowed.items():
        attr = "register_value" if field == "register" else field
        value = getattr(payload, attr)
        if value is None:
            continue
        value = value.strip().lower()
        if value not in keys:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"invalid {field}: {value!r} (allowed: {', '.join(keys)})",
                },
                status_code=400,
            )
        current[field] = value
        changed = True
    if changed:
        db.set_profile("style_overrides", current)
    return {"ok": True, "overrides": current}


@app.post("/api/feedback")
def record_feedback(payload: dict) -> JSONResponse:
    """A per-message user signal (thumbs / edit / regenerate / note).

    Validation lives here, not in the UI: the reflection loop in a later
    phase reads this table and must never see an unknown kind.
    """
    kind = payload.get("kind")
    if kind not in db.FEEDBACK_KINDS:
        return JSONResponse(
            {"ok": False, "error": f"kind must be one of {list(db.FEEDBACK_KINDS)}"},
            status_code=400,
        )
    try:
        message_id = payload.get("message_id")
        fid = db.save_feedback(
            kind=str(kind),
            message_id=int(message_id) if message_id is not None else None,
            session=payload.get("session"),
            note=payload.get("note"),
        )
    except (TypeError, ValueError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "id": fid}


@app.get("/api/feedback")
def feedback(limit: int = 100, unapplied: bool = False) -> dict:
    return {
        "feedback": db.list_feedback(
            limit=min(max(limit, 1), 500), only_unapplied=unapplied
        )
    }


@app.get("/api/reflections")
def reflections(status: str | None = None) -> dict:
    """Evolution loop: drain the feedback queue into proposals, then serve
    them plus live insights. Reading never approves anything."""
    if status is not None and status not in ("pending", "approved", "rejected"):
        return JSONResponse(
            {"error": "status must be pending, approved or rejected"},
            status_code=400,
        )
    reflection.reflect()
    return {
        "proposals": db.list_reflections(limit=200, status=status),
        "feedback_counts": db.feedback_counts(),
        "insights": reflection.insights(),
    }


@app.post("/api/reflections/{reflection_id}/approve")
def approve_reflection(reflection_id: int) -> JSONResponse:
    """The user's press IS the approval: the proposal becomes an approved
    rule and from then on reaches every answer via the guardrails block."""
    item = db.get_reflection(reflection_id)
    if item is None:
        return JSONResponse({"ok": False, "error": "no such reflection"}, status_code=404)
    if item["status"] != "pending":
        return JSONResponse(
            {"ok": False, "error": f"already {item['status']}"},
            status_code=400,
        )
    rule_id = db.add_rule(
        text=item["title"],
        code="REFLECT",
        source=f"reflection:{reflection_id}",
        approved=True,
    )
    db.set_reflection_status(reflection_id, "approved", rule_id=rule_id)
    return {"ok": True, "rule_id": rule_id}


@app.post("/api/reflections/{reflection_id}/reject")
def reject_reflection(reflection_id: int) -> JSONResponse:
    item = db.get_reflection(reflection_id)
    if item is None:
        return JSONResponse({"ok": False, "error": "no such reflection"}, status_code=404)
    if item["status"] != "pending":
        return JSONResponse(
            {"ok": False, "error": f"already {item['status']}"},
            status_code=400,
        )
    db.set_reflection_status(reflection_id, "rejected")
    return {"ok": True}


@app.get("/api/evidence")
def evidence(q: str = "", limit: int = 20) -> JSONResponse:
    """Search the raw source lines behind stored memory."""
    if not q.strip():
        return JSONResponse({"results": []})
    return JSONResponse({"results": db.search_evidence(q, limit=min(limit, 100))})


@app.get("/api/decisions")
def decisions() -> dict:
    """The whole ledger: what is due, what is open, and what already closed.

    ``resolved`` is additive so existing clients that only read ``due`` and
    ``open`` keep working unchanged.
    """
    return {
        "due": db.due_decisions(),
        "open": db.open_decisions(),
        "resolved": db.resolved_decisions(),
    }


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


@app.delete("/api/decisions/{decision_id}")
def delete_decision(decision_id: int) -> JSONResponse:
    if not db.delete_decision(decision_id):
        return JSONResponse({"error": "not found"}, status_code=404)
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


@app.post("/api/settings/reset")
def reset_settings() -> dict:
    """Delete every stored setting except provider API keys.

    Keys survive because they are expensive to re-enter and live on their own
    screen; everything else falls back to its built-in default, which is what
    a stuck settings screen needs as a way out.
    """
    conn = db.connect()
    conn.execute("DELETE FROM settings WHERE key NOT LIKE 'provider.%'")
    conn.commit()
    return {"ok": True}


# ------------------------------------------------------------ providers

class ProviderIn(BaseModel):
    api_key: str | None = None
    model: str | None = None
    url: str | None = None
    clear_key: bool = False
    enabled: bool | None = None


@app.get("/api/providers")
async def list_providers(probe: bool = False) -> dict:
    """Provider config with masked keys, plus a live readiness flag."""
    live = {p["name"]: p for p in await probe_providers(force=probe)}
    providers = []
    for name in visible_providers():
        status = provider_status(name)
        status["ready"] = live.get(name, {}).get("ready", False)
        status["error"] = live.get(name, {}).get("error")
        providers.append(status)
    return {"providers": providers, "order": visible_providers()}


@app.post("/api/providers/test")
async def test_all_providers() -> dict:
    """Test every provider with its stored config.

    Declared before `/api/providers/{name}` so the literal path wins; otherwise
    the path parameter would capture `test` and demand a body.
    """
    import asyncio

    results = await asyncio.gather(*(test_provider(n) for n in visible_providers()))
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
    if payload.enabled is not None:
        db.set_setting(f"provider.{name}.enabled", "1" if payload.enabled else "0")
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


class OllamaPullIn(BaseModel):
    model: str | None = None


@app.get("/api/ollama")
def ollama_status() -> dict:
    """State of the local offline model host (installed? running? model?)."""
    return {**ollama.status(), "autostart": ollama.autostart_enabled()}


@app.post("/api/ollama/autostart")
def ollama_autostart(payload: dict) -> dict:
    """Turn 'start with the app' on or off."""
    enabled = payload.get("enabled")
    db.set_setting("ollama_autostart", "1" if enabled else "0")
    return {"ok": True, "autostart": ollama.autostart_enabled()}


@app.post("/api/ollama/start")
def ollama_start() -> JSONResponse:
    """Start the local host if it is installed but not yet running."""
    result = ollama.start()
    invalidate_probe_cache()
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@app.post("/api/ollama/pull")
def ollama_pull(
    background: BackgroundTasks, payload: OllamaPullIn | None = None
) -> JSONResponse:
    """Pull a model in the background; poll GET /api/ollama until it appears."""
    want = (payload.model if payload else None) or ollama.desired_model()
    if not ollama.running():
        started = ollama.start()
        if not started.get("ok"):
            return JSONResponse(started, status_code=503)
    background.add_task(ollama.pull, want)
    invalidate_probe_cache()
    return JSONResponse({"ok": True, "started": True, "model": want})


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


@app.post("/api/plan")
async def make_plan(payload: PlanIn) -> JSONResponse:
    """Turn a document (uploaded file or raw text) into a strict plan.

    The model drafts a title and concrete rules, grounded only in the document.
    The rules are stored; in strict mode they are approved, so every later
    answer is held to them.
    """
    text = payload.text
    related = payload.related_to
    if not text and payload.media_id is not None:
        row = db.connect().execute(
            "SELECT path, tags FROM media WHERE id=?", (payload.media_id,)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "media not found"}, status_code=404)
        stored = Path(row["path"])
        if not stored.exists():
            return JSONResponse({"error": "the file is missing on disk"}, status_code=404)
        result = uploads.read_upload(stored.name, stored.read_bytes())
        text = result.get("text")
        related = related or row["tags"]
        if not text:
            return JSONResponse(
                {"error": result.get("reason") or "the file could not be read"},
                status_code=400,
            )
    if not text or not text.strip():
        return JSONResponse(
            {"error": "provide text or the id of a readable upload"}, status_code=400
        )

    drafted = await plan.draft_plan(text, related)
    if not drafted:
        return JSONResponse(
            {"error": "no plan could be drafted (no provider, or nothing actionable in the file)"},
            status_code=503,
        )

    source = f"plan:{payload.media_id}" if payload.media_id is not None else f"plan:{db.now()}"
    title = drafted["title"] or "Uploaded plan"
    body = "\n".join(f"- {r}" for r in drafted["rules"]) or "(no concrete commitments found)"
    episode_id = db.add_episode(
        title=f"PLAN: {title}", summary=body, occurred_at=db.now(), source=source
    )
    added = [
        {"id": db.add_rule(text=r, code="PLAN", source=source, approved=payload.strict),
         "text": r, "approved": payload.strict}
        for r in drafted["rules"]
    ]
    return JSONResponse(
        {
            "ok": True,
            "title": title,
            "episode_id": episode_id,
            "rules": added,
            "strict": payload.strict,
            "provider": drafted.get("provider"),
        }
    )


@app.get("/api/rules")
def get_rules() -> dict:
    return {"rules": db.list_rules()}


@app.post("/api/rules/{rule_id}/approve")
def approve_rule(rule_id: int) -> JSONResponse:
    if not db.set_rule_approved(rule_id, True):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": rule_id})


@app.delete("/api/rules/{rule_id}")
def remove_rule(rule_id: int) -> JSONResponse:
    if not db.delete_rule(rule_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": rule_id})


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


@app.put("/api/media/{media_id}")
def update_media(media_id: int, payload: dict) -> JSONResponse:
    if not db.update_media(media_id, tags=payload.get("tags"), kind=payload.get("kind")):
        return JSONResponse({"error": "not found or nothing to update"}, status_code=404)
    return JSONResponse({"ok": True, "id": media_id})


@app.delete("/api/media/{media_id}")
def delete_media(media_id: int) -> JSONResponse:
    """Delete a media row, and its file when nothing else points at it.

    Uploads are de-duplicated by content hash, so one stored file can back more
    than one row. The file is unlinked only when it lives under the uploads dir
    and no remaining row references it, so a shared upload is never destroyed.
    """
    path = db.media_path(media_id)
    if path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.delete_media(media_id)
    try:
        p = Path(path).resolve()
        if p.is_relative_to(uploads.UPLOADS_DIR.resolve()) and not db.media_path_in_use(path):
            p.unlink(missing_ok=True)
    except (OSError, ValueError):
        # A read-only or already-missing file must never fail the delete.
        pass
    return JSONResponse({"ok": True, "id": media_id})


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


@app.get("/api/facts")
def list_facts(limit: int = 100) -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM facts ORDER BY confidence DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"facts": [dict(r) for r in rows]}


@app.post("/api/facts")
def create_fact(payload: dict) -> JSONResponse:
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        return JSONResponse({"error": "confidence must be a number"}, status_code=400)
    fid = db.add_fact(text, confidence=confidence, source=payload.get("source") or "manual")
    return JSONResponse({"ok": True, "id": fid}, status_code=201)


@app.put("/api/facts/{fact_id}")
def update_fact(fact_id: int, payload: dict) -> JSONResponse:
    def _float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    ok = db.update_fact(
        fact_id,
        text=payload.get("text"),
        source=payload.get("source"),
        confidence=_float(payload.get("confidence")) if payload.get("confidence") is not None else None,
        evidence=_int(payload.get("evidence")) if payload.get("evidence") is not None else None,
        status=payload.get("status"),
    )
    if not ok:
        return JSONResponse({"error": "not found or no changes"}, status_code=404)
    return JSONResponse({"ok": True, "id": fact_id})


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int) -> JSONResponse:
    if not db.delete_fact(fact_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": fact_id})


@app.get("/api/episodes")
def list_episodes(limit: int = 100) -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM episodes ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"episodes": [dict(r) for r in rows]}


@app.put("/api/episodes/{episode_id}")
def update_episode(episode_id: int, payload: dict) -> JSONResponse:
    ok = db.update_episode(
        episode_id,
        title=payload.get("title"),
        summary=payload.get("summary"),
        occurred_at=payload.get("occurred_at"),
        source=payload.get("source"),
    )
    if not ok:
        return JSONResponse({"error": "not found or no changes"}, status_code=404)
    return JSONResponse({"ok": True, "id": episode_id})


@app.delete("/api/episodes/{episode_id}")
def delete_episode(episode_id: int) -> JSONResponse:
    if not db.delete_episode(episode_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": episode_id})


@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: int, payload: dict) -> JSONResponse:
    approved = payload.get("approved")
    ok = db.update_rule(
        rule_id,
        text=payload.get("text"),
        code=payload.get("code"),
        source=payload.get("source"),
        approved=bool(approved) if approved is not None else None,
    )
    if not ok:
        return JSONResponse({"error": "not found or no changes"}, status_code=404)
    return JSONResponse({"ok": True, "id": rule_id})


@app.put("/api/learned/{learned_id}")
def update_learned(learned_id: int, payload: LearnedUpdate) -> JSONResponse:
    """Edit a learned row; a status flip also performs what that status means.

    Field edits are a plain update, but "approved" is not just a label: it is
    what writes the fact into memory. Routing it through the same helper the
    approve buttons use keeps that invariant (and its once-only guarantee)
    true no matter which client asks.
    """
    row = db.learned_row(learned_id)
    if row is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    changed = db.update_learned(
        learned_id,
        text=payload.text,
        subject=payload.subject,
        kind=payload.kind,
        source=payload.source,
        confidence=payload.confidence,
        status=None if payload.status in ("approved", "rejected") else payload.status,
    )
    if payload.status == "approved" and row["status"] != "approved":
        if db.approve_learned(learned_id) == 0:
            return JSONResponse({"error": "not found or no changes"}, status_code=404)
        changed = True
    elif payload.status == "rejected" and row["status"] != "rejected":
        if not db.reject_learned(learned_id):
            return JSONResponse({"error": "not found or no changes"}, status_code=404)
        changed = True

    if not changed:
        return JSONResponse({"error": "not found or no changes"}, status_code=404)
    return JSONResponse({"ok": True, "id": learned_id})


@app.delete("/api/learned/{learned_id}")
def delete_learned(learned_id: int) -> JSONResponse:
    if not db.delete_learned(learned_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "id": learned_id})


@app.post("/api/learned/bulk")
def bulk_learned(payload: LearnedBulk) -> JSONResponse:
    """Approve/reject/delete several candidates in one call.

    Each helper reports whether it did anything, so the count only includes
    rows that actually changed; a missing or already-final id is skipped
    rather than being reported as work done.
    """
    ids = [i for i in payload.ids if isinstance(i, int)]
    if not ids:
        return JSONResponse({"ok": True, "processed": 0})
    handlers = {
        "approve": lambda i: db.approve_learned(i) > 0,
        "reject": lambda i: db.reject_learned(i),
        "delete": lambda i: db.delete_learned(i),
    }
    act = handlers.get(payload.action)
    if act is None:
        return JSONResponse({"error": "unknown action"}, status_code=422)
    processed = sum(1 for lid in ids if act(lid))
    return JSONResponse({"ok": True, "processed": processed})


@app.put("/api/decisions/{decision_id}")
def update_decision(decision_id: int, payload: DecisionUpdate) -> JSONResponse:
    ok = db.update_decision(
        decision_id,
        topic=payload.topic,
        decision=payload.decision,
        prediction=payload.prediction,
        confidence=payload.confidence,
        review_date=payload.review_date,
        actual_outcome=payload.actual_outcome,
        resolved_at=payload.resolved_at,
    )
    if not ok:
        return JSONResponse({"error": "not found or no changes"}, status_code=404)
    return JSONResponse({"ok": True, "id": decision_id})


@app.post("/api/insights/contradictions/{a_id}/{b_id}/review")
def review_contradiction(a_id: int, b_id: int) -> JSONResponse:
    """Settle a contradiction pair so it stops reappearing in the feed.

    Neither fact is deleted and no evidence is thrown away; the pair is only
    marked as looked-at. Merging (which rewrites memory) stays a separate,
    explicit act.
    """
    if not db.dismiss_contradiction(a_id, b_id):
        return JSONResponse({"error": "one or both facts not found"}, status_code=404)
    return JSONResponse({"ok": True, "reviewed": [a_id, b_id]})


@app.delete("/api/insights/contradictions/{a_id}/{b_id}/review")
def undo_contradiction_review(a_id: int, b_id: int) -> JSONResponse:
    """Undo a dismissal so an unresolved pair shows up again."""
    if not db.reconsider_contradiction(a_id, b_id):
        return JSONResponse({"error": "not previously reviewed"}, status_code=404)
    return JSONResponse({"ok": True, "reviewed": [a_id, b_id]})


@app.post("/api/insights/contradictions/merge")
def merge_contradictions(payload: ContradictionMerge) -> JSONResponse:
    """Fold two conflicting facts into one reconciled fact.

    A merge always reduces two rows to one: the reconciled text is written
    first, and only then are both originals removed. If either original is
    already gone the merge is refused rather than silently duplicating memory.
    """
    if payload.keep_id == payload.remove_id:
        return JSONResponse({"error": "keep_id and remove_id must differ"}, status_code=400)
    conn = db.connect()
    present = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM facts WHERE id IN (?,?)", (payload.keep_id, payload.remove_id)
        ).fetchall()
    }
    if present != {payload.keep_id, payload.remove_id}:
        return JSONResponse({"error": "one or both facts not found"}, status_code=404)
    fid = db.add_fact(
        text=payload.reconciled_text,
        source=f"reconciled:keep={payload.keep_id};remove={payload.remove_id}",
        confidence=0.5 if payload.confidence is None else payload.confidence,
    )
    db.delete_fact(payload.keep_id)
    db.delete_fact(payload.remove_id)
    return JSONResponse({"ok": True, "fact_id": fid})


@app.post("/api/media/bulk/delete")
def bulk_delete_media(payload: MediaBulkDelete) -> JSONResponse:
    """Delete several media rows, unlinking only files nothing else points at.

    Delegates to the same safety rules as DELETE /api/media/{id}: the file is
    removed only when it lives under the uploads dir and no remaining row
    references it, so a de-duplicated upload shared by another row survives.
    """
    processed = 0
    for mid in [i for i in payload.ids if isinstance(i, int)]:
        path = db.media_path(mid)
        if path is None:
            continue
        if not db.delete_media(mid):
            continue
        processed += 1
        try:
            p = Path(path).resolve()
            if p.is_relative_to(uploads.UPLOADS_DIR.resolve()) and not db.media_path_in_use(path):
                p.unlink(missing_ok=True)
        except (OSError, ValueError):
            # A read-only or already-missing file must never fail the delete.
            pass
    return JSONResponse({"ok": True, "processed": processed})


# --------------------------------------------------------------- pipeline

@app.get("/api/pipeline")
async def pipeline_report() -> dict:
    """Run every pipeline stage for real and report pass/fail per stage.

    Answers "which part is broken?" without guessing: memory retrieval, the
    router, the model host, a real model completion, a real espeak-to-whisper
    round trip, TTS, and the provider chain each get their own row and hint.
    """
    return await pipeline.run_checks()


class PipelineFullIn(BaseModel):
    question: str | None = None


@app.post("/api/pipeline/full")
async def pipeline_full(payload: PipelineFullIn | None = None) -> JSONResponse:
    """One genuine end-to-end answer (slow: up to three model passes)."""
    question = (payload.question if payload else None) or pipeline.FULL_ANSWER_DEFAULT
    try:
        return JSONResponse(await pipeline.full_answer(question))
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "the full answer timed out (3 minutes)"},
            status_code=504,
        )
    except pipeline.ProviderError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    except Exception as exc:  # noqa: BLE001 - surfaced to the settings screen
        return JSONResponse(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=502
        )


# Mounted last so the API routes above are matched before the static handler.
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
