"""One screen that says which part of the model pipeline works.

A chat failure can come from any stage - retrieval, routing, the language
model host, speech in, speech out - and each one normally fails silently
inside a single request. This module runs each stage for real with its own
timing and returns a pass/fail/skip row plus a concrete fix hint, so the
broken stage points at its own repair.

Everything here is read-only: no memory is written, no question is recorded,
and a provider that is switched off is reported as skipped rather than
failed, because "off" is a deliberate choice, not a fault.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import db, engine, ollama, router, stt, tts, voice_id
from .config import PROVIDER_ORDER
from .llm import ProviderError, complete, provider_enabled, provider_status

# Questions the checks ask themselves. Fixed text keeps runs comparable.
PROBE_QUESTION = "where do I live"
# A plain trivia question: the router sends unclassified asks to "challenge"
# on purpose, but the everyday path a user hits is "ask", which is what this
# should exercise.
FULL_ANSWER_DEFAULT = "What is the capital of France? Answer in one short sentence."

REPLY_TIMEOUT = 30.0
FULL_TIMEOUT = 180.0
STT_TIMEOUT = 30.0


def _row(
    stage_id: str,
    label: str,
    state: str,
    ms: int,
    detail: str,
    hint: str | None = None,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "label": label,
        "state": state,  # pass | fail | skip
        "ms": ms,
        "detail": detail,
        "hint": hint,
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def check_core() -> dict[str, Any]:
    """Server up and the database answering queries."""
    started = time.monotonic()
    try:
        c = db.counts()
    except Exception as exc:  # noqa: BLE001 - the stage's job is to report this
        return _row("core", "Server & database", "fail", _ms(started),
                    f"{type(exc).__name__}: {exc}", "Restart the server (./run.sh).")
    return _row(
        "core", "Server & database", "pass", _ms(started),
        f"{c.get('facts', 0)} facts · {c.get('episodes', 0)} episodes · "
        f"{c.get('evidence', 0)} evidence lines",
    )


async def check_memory() -> dict[str, Any]:
    """Retrieval: the same lookup every real question starts with."""
    started = time.monotonic()
    try:
        ctx = engine.build_context(PROBE_QUESTION)
    except Exception as exc:  # noqa: BLE001
        return _row("memory", "Memory retrieval", "fail", _ms(started),
                    f"{type(exc).__name__}: {exc}",
                    "The database or search index is damaged; re-import a backup from Settings.")
    return _row(
        "memory", "Memory retrieval", "pass", _ms(started),
        f"{len(ctx.get('memories', []))} memories · "
        f"{len(ctx.get('evidence', []))} evidence lines retrieved",
    )


async def check_router() -> dict[str, Any]:
    """Intent routing - pure local logic, no model and no network."""
    started = time.monotonic()
    try:
        route = router.route("what should I do about my job application", repeat_count=0)
    except Exception as exc:  # noqa: BLE001
        return _row("router", "Intent router", "fail", _ms(started),
                    f"{type(exc).__name__}: {exc}", "This is local code; reinstall the app files.")
    return _row("router", "Intent router", "pass", _ms(started),
                f"routes a test question to '{route.mode}'")


async def check_offline_host() -> dict[str, Any]:
    """Ollama: installed, running, and the wanted model pulled."""
    started = time.monotonic()
    s = ollama.status()
    if not s.get("installed"):
        return _row("offline-host", "Offline model host", "fail", _ms(started),
                    "ollama is not installed", "brew install ollama")
    if not s.get("running"):
        return _row("offline-host", "Offline model host", "fail", _ms(started),
                    "installed but not running", "Press START LOCAL MODEL in Settings.")
    if not s.get("model_present"):
        return _row("offline-host", "Offline model host", "fail", _ms(started),
                    f"running, but {s.get('model')} is not downloaded "
                    f"(has: {', '.join(s.get('models') or []) or 'none'})",
                    "Press DOWNLOAD MODEL in Settings (or: ollama pull llama3.2:1b).")
    return _row("offline-host", "Offline model host", "pass", _ms(started),
                f"running at {s.get('url')} with {s.get('model')}")


async def check_model_reply(timeout: float = REPLY_TIMEOUT) -> dict[str, Any]:
    """One real completion - the same call every answer is built on."""
    started = time.monotonic()
    try:
        text, provider = await asyncio.wait_for(
            complete(
                [{"role": "user", "content": "Reply with exactly: OK"}],
                temperature=0.0,
                max_tokens=16,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return _row("model-reply", "Model reply", "fail", _ms(started),
                    f"no answer within {int(timeout)}s",
                    "The model is loaded but too slow; try a smaller model (llama3.2:1b).")
    except ProviderError as exc:
        return _row("model-reply", "Model reply", "fail", _ms(started),
                    str(exc),
                    "Turn a provider on in MODELS & API KEYS, or start the local model above.")
    except Exception as exc:  # noqa: BLE001
        return _row("model-reply", "Model reply", "fail", _ms(started),
                    f"{type(exc).__name__}: {exc}", "See the offline host stage above.")
    return _row("model-reply", "Model reply", "pass", _ms(started),
                f"{provider} answered {text[:40]!r}")


def check_stt() -> dict[str, Any]:
    """Offline speech-to-text, tested by actually hearing an espeak clip."""
    started = time.monotonic()
    status = stt.status()
    if not status.get("available"):
        return _row("stt", "Offline speech-to-text", "fail", _ms(started),
                    "whisper.cpp is not installed", "brew install whisper.cpp")
    if not status.get("model"):
        return _row("stt", "Offline speech-to-text", "fail", _ms(started),
                    "installed, but no speech model is downloaded",
                    "Press DOWNLOAD URDU MODEL in Settings.")
    if not tts.ESPEAK:
        return _row("stt", "Offline speech-to-text", "skip", _ms(started),
                    f"{status.get('model')} present; cannot self-test without espeak-ng",
                    "brew install espeak-ng to enable the self-test.")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "probe.wav")
        try:
            subprocess.run(
                [tts.ESPEAK, "-w", out, "testing one two"],
                capture_output=True, timeout=STT_TIMEOUT, check=True,
            )
            raw = Path(out).read_bytes()
        except Exception as exc:  # noqa: BLE001
            return _row("stt", "Offline speech-to-text", "skip", _ms(started),
                        f"could not generate a test clip ({type(exc).__name__})")
    heard = stt.transcribe(raw, lang="en")
    text = (heard.get("text") or "").strip()
    if not text:
        return _row("stt", "Offline speech-to-text", "fail", _ms(started),
                    f"whisper heard nothing ({heard.get('reason') or 'empty transcript'})",
                    "Re-download the speech model from Settings.")
    return _row("stt", "Offline speech-to-text", "pass", _ms(started),
                f'{status.get("model")} heard "{text[:40]}"')


def check_tts() -> dict[str, Any]:
    """Offline text-to-speech: synthesize a one-word clip for real."""
    started = time.monotonic()
    if not tts.available():
        return _row("tts", "Offline speech-out", "fail", _ms(started),
                    "no speech engine available", "brew install espeak-ng")
    result = tts.synthesize("OK", lang="en")
    audio = result.get("audio")
    if not audio:
        return _row("tts", "Offline speech-out", "fail", _ms(started),
                    result.get("reason") or "no audio produced",
                    "brew install espeak-ng (server/Gemini voices need a key).")
    return _row("tts", "Offline speech-out", "pass", _ms(started),
                f"{result.get('model')} produced {len(audio)} bytes")


def check_speaker() -> dict[str, Any]:
    """Speaker identification engine (advisory only, never required)."""
    started = time.monotonic()
    status = voice_id.status()
    try:
        count = len(db.list_voiceprints())
    except Exception:  # noqa: BLE001
        count = 0
    if not status.get("available"):
        return _row("speaker", "Speaker ID", "skip", _ms(started),
                    "engine not installed (optional)",
                    "Press DOWNLOAD VOICE MODEL in Settings to enable it.")
    return _row("speaker", "Speaker ID", "pass", _ms(started),
                f"engine ready · {count} voiceprint(s) saved")


def check_provider_chain() -> dict[str, Any]:
    """Which providers are on, and therefore where an answer will come from."""
    started = time.monotonic()
    parts = []
    first_on = None
    for name in PROVIDER_ORDER:
        st = provider_status(name)
        if not st["enabled"]:
            parts.append(f"{name}: off")
        else:
            parts.append(f"{name}: on ({st['model']})")
            if first_on is None:
                first_on = name
    if first_on is None:
        return _row("provider-chain", "Provider chain", "fail", _ms(started),
                    " → ".join(parts),
                    "Turn on at least one provider in MODELS & API KEYS.")
    return _row("provider-chain", "Provider chain", "pass", _ms(started),
                f"answers come from {first_on} · " + " → ".join(parts))


async def run_checks() -> dict[str, Any]:
    """Every fast stage in parallel, then the chain summary last."""
    stages = await asyncio.gather(
        check_core(),
        check_memory(),
        check_router(),
        check_offline_host(),
        check_model_reply(),
        asyncio.to_thread(check_stt),
        asyncio.to_thread(check_tts),
        asyncio.to_thread(check_speaker),
    )
    chain = check_provider_chain()
    return {"ok": all(s["state"] != "fail" for s in (*stages, chain)),
            "stages": [*stages, chain]}


async def full_answer(question: str, timeout: float = FULL_TIMEOUT) -> dict[str, Any]:
    """The genuine reply path: context, routing, then up to three model passes.

    Kept separate from the fast checks because a small local model can take
    well over a minute for answer + self-critique + repair, and because this
    is the only stage that proves an end-to-end reply actually works.
    """
    started = time.monotonic()
    route = router.route(question, repeat_count=0)
    ctx = engine.build_context(question)
    ctx["escalations"] = route.escalations
    ctx["language"] = engine.resolve_language("auto", question)
    ctx["detail"] = "normal"
    result = await asyncio.wait_for(
        engine.respond(question, mode=route.mode, ctx=ctx), timeout=timeout
    )
    return {
        "ok": True,
        "ms": _ms(started),
        "provider": result.get("provider"),
        "route": route.mode,
        "text": (result.get("text") or "")[:400],
        "critique": result.get("critique") or [],
        "labels": result.get("labels") or [],
        "note": "a real reply runs up to three model passes: answer, self-critique, repair",
    }
