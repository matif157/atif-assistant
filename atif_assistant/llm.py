"""Model gateway.

Tries free-tier providers in order and falls back cleanly. If no provider is
reachable, Atif Assistant still answers using a local heuristic engine so the app is
never silently useless.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import httpx

from .config import (
    DATA_DIR,
    MODEL_DEFAULTS,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABELS,
    PROVIDER_ORDER,
)


class ProviderError(RuntimeError):
    pass


async def _post_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any = None,
    attempts: int = 3,
    backoff: float = 1.5,
) -> httpx.Response:
    """POST, retrying transient overload (429/503) a few times.

    Free tiers briefly answer "high demand" or "rate limited"; a short retry
    turns those into an answer instead of a hard failure. Everything else is
    raised immediately so real errors (bad key, bad model) stay visible.
    """
    last: httpx.Response | None = None
    for i in range(attempts):
        last = await client.post(url, headers=headers, json=json)
        if last.status_code in (429, 503) and i < attempts - 1:
            await asyncio.sleep(backoff * (i + 1))
            continue
        last.raise_for_status()
        return last
    assert last is not None
    last.raise_for_status()
    return last


# --------------------------------------------------------- runtime config
#
# A key or model can be set two ways: in `.env` (read once at launch) or at
# runtime from the Settings sheet (stored in the local database). The database
# wins when a row is present - including an empty row, which means "cleared",
# so clearing a key in the UI really disables it even if `.env` still has one.

def _override(name: str, field: str) -> str | None:
    """Return the stored runtime value, or None if it was never set.

    None means "fall back to the environment". An empty string is a real value
    that intentionally blanks the setting.
    """
    try:
        from . import db

        return db.get_setting(f"provider.{name}.{field}", None)
    except Exception:  # noqa: BLE001 - config must never crash a request
        return None


def provider_key(name: str) -> str:
    """The API key for a provider: database override, else environment."""
    override = _override(name, "api_key")
    if override is not None:
        return override
    return os.environ.get(PROVIDER_ENV_KEYS.get(name, ""), "")


def provider_model(name: str) -> str:
    """The model slug for a provider: database override, else default."""
    override = _override(name, "model")
    if override is not None:
        return override
    return MODEL_DEFAULTS.get(name, "")


def provider_enabled(name: str) -> bool:
    """Whether a provider may be used. Defaults to enabled.

    A disabled provider is skipped entirely (no calls, no quota), so the user
    can force a local-only, offline setup by turning the hosted ones off.
    """
    override = _override(name, "enabled")
    if override is None:
        if name == "llamacpp":
            # On a desktop there is no llama-server binary, so this provider
            # stays out of the way entirely; on-device (binaries shipped in
            # the APK) it becomes the first choice automatically.
            return llamacpp_bin() is not None
        return True
    return str(override).strip().lower() not in {"0", "false", "off", "no"}


def ollama_url() -> str:
    """The local server URL: database override, else environment, else default."""
    override = _override("ollama", "url")
    if override is not None:
        return override
    return os.environ.get("ATIF_ASSISTANT_OLLAMA_URL", "http://127.0.0.1:11434")


# ------------------------------------------------- on-device llama.cpp
#
# The Android APK ships a llama-server executable per ABI (extracted to
# DATA_DIR/native/) and the model is downloaded into DATA_DIR/models/. The
# server is started from here, loopback-only, and used as a normal OpenAI
# compatible provider. On a machine without those files nothing here runs.

LLAMACPP_PORT = int(os.environ.get("ATIF_ASSISTANT_LLAMACPP_PORT", "8765"))


def llamacpp_url() -> str:
    """llama-server URL: database override, else environment, else loopback."""
    override = _override("llamacpp", "url")
    if override is not None:
        return override
    env = os.environ.get("ATIF_ASSISTANT_LLAMACPP_URL")
    if env:
        return env
    return f"http://127.0.0.1:{LLAMACPP_PORT}"


def llamacpp_bin() -> Path | None:
    """The llama-server executable, or None when not available.

    On-device the Java shell passes the extracted JNI-lib path via
    ``ATIF_ASSISTANT_LLAMACPP_BIN`` (nativeLibraryDir is executable; filesDir
    is not, since Android 10). Desktop looks for a locally built binary under
    DATA_DIR/native for development.
    """
    override = os.environ.get("ATIF_ASSISTANT_LLAMACPP_BIN", "")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    path = DATA_DIR / "native" / "llama-server"
    return path if path.is_file() else None


def llamacpp_model_file() -> Path | None:
    """The downloaded GGUF, or None when no complete model is on disk.

    Only size-validated files count: an interrupted download must never be
    handed to llama-server.
    """
    models = DATA_DIR / "models"
    if not models.is_dir():
        return None
    for path in sorted(models.glob("*.gguf")):
        if llm_model_ok(path):
            return path
    return None


_LLAMACPP_LOCK = threading.Lock()
_LLAMACPP: dict[str, Any] = {"proc": None, "model_id": None, "error": None}


def _llamacpp_log_path() -> Path:
    return DATA_DIR / "llama-server.log"


def ensure_llamacpp_started() -> str:
    """Start llama-server once in the background. Returns running|starting|unavailable."""
    with _LLAMACPP_LOCK:
        proc = _LLAMACPP.get("proc")
        if proc is not None and proc.poll() is None:
            return "running"
        binary = llamacpp_bin()
        model = llamacpp_model_file()
        if binary is None or model is None:
            _LLAMACPP["error"] = (
                "llama-server binary missing" if binary is None else "model not downloaded"
            )
            return "unavailable"
        try:
            log = open(_llamacpp_log_path(), "ab", buffering=0)
            env = os.environ.copy()
            libdir = str(binary.parent)
            env["LD_LIBRARY_PATH"] = (
                libdir + ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else libdir
            )
            env["GGML_BACKEND_PATH"] = libdir
            proc = subprocess.Popen(
                [
                    str(binary), "-m", str(model),
                    "--host", "127.0.0.1", "--port", str(LLAMACPP_PORT),
                    "-c", "4096",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            _LLAMACPP["proc"] = proc
            _LLAMACPP["model_id"] = None
            _LLAMACPP["error"] = None
            try:
                from . import applog

                applog.log("llamacpp.spawn", model=str(model), port=LLAMACPP_PORT)
            except Exception:  # noqa: BLE001
                pass
            return "starting"
        except Exception as exc:  # noqa: BLE001 - report, never crash the request
            _LLAMACPP["error"] = f"{type(exc).__name__}: {exc}"
            try:
                from . import applog

                applog.log("llamacpp.spawn_failed", error=_LLAMACPP["error"])
            except Exception:  # noqa: BLE001
                pass
            return "unavailable"


async def llamacpp_is_up(timeout: float = 1.5) -> bool:
    """Probe llama-server's OpenAI endpoint."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{llamacpp_url()}/v1/models")
        if r.status_code != 200:
            return False
        data = r.json().get("data") or []
        if data and not _LLAMACPP.get("model_id"):
            _LLAMACPP["model_id"] = data[0].get("id") or "local"
        return True
    except Exception:
        return False


async def _wait_llamacpp(timeout: float) -> bool:
    """Wait for a freshly spawned server to accept requests (model load)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        proc = _LLAMACPP.get("proc")
        if proc is None or proc.poll() is not None:
            return False
        if await llamacpp_is_up():
            return True
        await asyncio.sleep(0.5)
    return False


async def _llamacpp(model: str, messages: list[dict], **kw: Any) -> str:
    state = ensure_llamacpp_started()
    if state == "unavailable":
        raise ProviderError(_LLAMACPP.get("error") or "on-device model not available")
    # A cold start loads the whole GGUF into RAM; give it room, but a dead
    # process fails fast instead of burning the whole budget.
    wait = kw.get("timeout") if kw.get("timeout") else 90.0
    if not await llamacpp_is_up(timeout=0.5) and not await _wait_llamacpp(wait):
        raise ProviderError(_LLAMACPP.get("error") or "llama-server did not start")
    base = llamacpp_url()
    model_id = _LLAMACPP.get("model_id") or model or "local"
    async with httpx.AsyncClient(timeout=kw.get("timeout") or 300.0) as client:
        r = await client.post(
            f"{base}/v1/chat/completions",
            json={
                "model": model_id,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def mask_key(key: str) -> str:
    """A safe hint for the UI. Never returns enough to reconstruct the key."""
    if not key:
        return ""
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


async def _groq(model: str, messages: list[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("groq")
    if not key:
        raise ProviderError("no GROQ_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(
            client,
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        return r.json()["choices"][0]["message"]["content"]


async def _gemini(model: str, messages: list[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("gemini")
    if not key:
        raise ProviderError("no GEMINI_API_KEY")
    system = "\n\n".join(
        m["content"] for m in messages if m["role"] == "system"
    )
    turns = [
        {
            "role": "user" if m["role"] == "user" else "model",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
        if m["role"] != "system"
    ]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body: dict[str, Any] = {
        "contents": turns,
        "generationConfig": {
            "temperature": kw.get("temperature", 0.4),
            "maxOutputTokens": kw.get("max_tokens", 1800),
        },
    }
    # A readiness ping has no system turn; sending an empty systemInstruction
    # part makes Gemini reject an otherwise-valid key.
    if system.strip():
        body["systemInstruction"] = {"parts": [{"text": system}]}
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(client, url, headers={"x-goog-api-key": key}, json=body)
        data = r.json()
        # A thinking model handed a tiny token budget returns a candidate with
        # no text parts. Treat that as an empty answer, not a crash.
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)


async def _openrouter(model: str, messages: list[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("openrouter")
    if not key:
        raise ProviderError("no OPENROUTER_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(
            client,
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "http://localhost:8770",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        return r.json()["choices"][0]["message"]["content"]


async def _ollama(model: str, messages: list[dict], **kw: Any) -> str:
    base = kw.get("base") or ollama_url()
    key = kw.get("key") or provider_key("ollama")
    system = "\n\n".join(
        m["content"] for m in messages if m["role"] == "system"
    )
    prompt = "\n\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m["role"] != "system"
    )
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=kw.get("timeout", 120)) as client:
        r = await client.post(
            f"{base}/api/generate",
            headers=headers,
            json={
                "model": model,
                "system": system,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": kw.get("temperature", 0.4),
                    # Ollama's default context can be smaller than our system
                    # prompt plus retrieved memory; an overflowing prompt is
                    # silently truncated and the model rambles.
                    "num_ctx": kw.get("num_ctx", 4096),
                },
            },
        )
        r.raise_for_status()
        return r.json()["response"]


HANDLERS = {
    "llamacpp": _llamacpp,
    "groq": _groq,
    "gemini": _gemini,
    "openrouter": _openrouter,
    "ollama": _ollama,
}


async def complete(
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int = 1800,
) -> tuple[str, str]:
    """Return (text, provider_used). Raises if every provider fails."""
    last_error: Exception | None = None

    for name in PROVIDER_ORDER:
        if not provider_enabled(name):
            continue
        handler = HANDLERS.get(name)
        if handler is None:
            continue
        try:
            text = await handler(
                provider_model(name), messages, temperature=temperature,
                max_tokens=max_tokens,
            )
            if text and text.strip():
                return text.strip(), name
        except Exception as exc:  # noqa: BLE001 - try the next provider
            last_error = exc
            continue

    raise ProviderError(f"no provider available: {last_error}")


async def ollama_is_up(url: str | None = None) -> bool:
    """Actually probe Ollama. Being configured is not being ready."""
    base = url or ollama_url()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/api/tags")
        return r.status_code == 200
    except Exception:
        return False


# Live probe results, cached so a status poll does not spend API quota.
_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "result": None}
_PROBE_TTL = 120.0


def invalidate_probe_cache() -> None:
    """Drop the cached probe so the next status call reflects a config change."""
    _PROBE_CACHE["at"] = 0.0
    _PROBE_CACHE["result"] = None


def provider_status(name: str) -> dict[str, Any]:
    """Configuration (not readiness) for one provider, with a masked key."""
    key = provider_key(name)
    configured = name in ("ollama", "llamacpp") or bool(key)
    out = {
        "name": name,
        "label": PROVIDER_LABELS.get(name, name),
        "configured": configured,
        "enabled": provider_enabled(name),
        "model": provider_model(name),
        "key_set": bool(key),
        "key_hint": mask_key(key),
        "ready": False,
        "error": None,
    }
    if name == "ollama":
        out["url"] = ollama_url()
    if name == "llamacpp":
        out["url"] = llamacpp_url()
        out["binary"] = llamacpp_bin() is not None
        out["model_file"] = (
            llamacpp_model_file().name if llamacpp_model_file() else None
        )
    return out


def available_providers() -> list[dict[str, Any]]:
    """Sync snapshot of provider *configuration* only.

    ``ready`` here is false for everything on purpose. A non-empty key string
    is not proof the key is accepted: a revoked or wrong-provider key (a
    ``sk-or-`` OpenRouter key pasted into GROQ_API_KEY, for instance) is still
    "configured" and would be reported ready by a presence check alone. Use
    ``probe_providers()`` for the live answer.
    """
    return [provider_status(name) for name in visible_providers()]


def visible_providers() -> list[str]:
    """Providers worth showing. The on-device LLM only exists where it shipped.

    Desktop keeps its original four rows; on a phone the binary is always
    extracted, so llamacpp appears there as soon as the app installs.
    """
    return [
        name
        for name in PROVIDER_ORDER
        if not (name == "llamacpp" and llamacpp_bin() is None)
    ]


async def _probe_one(name: str) -> dict[str, Any]:
    """Make the smallest possible real call to one provider."""
    if not provider_enabled(name):
        configured = name == "llamacpp" or name == "ollama" or bool(provider_key(name))
        return {"ready": False, "configured": configured, "error": "disabled"}
    if name == "llamacpp":
        if llamacpp_model_file() is None:
            return {
                "ready": False,
                "configured": True,
                "error": "model not downloaded",
            }
        ensure_llamacpp_started()
        ok = await llamacpp_is_up(timeout=2.0)
        return {
            "ready": ok,
            "configured": True,
            "error": None if ok else "starting",
        }
    if name == "ollama":
        ok = await ollama_is_up()
        return {
            "ready": ok,
            "configured": True,
            "error": None if ok else "ollama not reachable",
        }
    if not provider_key(name):
        return {"ready": False, "configured": False, "error": "no key set"}
    handler = HANDLERS.get(name)
    try:
        await handler(
            provider_model(name),
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=16,
            timeout=12,
        )
        # A 2xx reply proves the key and endpoint work. Do not require non-empty
        # text: a reasoning model handed max_tokens=1 spends the whole budget on
        # reasoning and returns empty content, which is readiness, not failure.
        return {"ready": True, "configured": True, "error": None}
    except httpx.HTTPStatusError as exc:
        return {
            "ready": False,
            "configured": True,
            "error": f"HTTP {exc.response.status_code}",
        }
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        return {"ready": False, "configured": True, "error": type(exc).__name__}


async def probe_providers(force: bool = False) -> list[dict[str, Any]]:
    """Live readiness for every provider, cached for ``_PROBE_TTL`` seconds."""
    import time

    now = time.monotonic()
    if (
        not force
        and _PROBE_CACHE["result"] is not None
        and now - _PROBE_CACHE["at"] < _PROBE_TTL
    ):
        return _PROBE_CACHE["result"]

    import asyncio

    names = visible_providers()
    probes = await asyncio.gather(*(_probe_one(n) for n in names))
    out = [
        {
            "name": name,
            "label": PROVIDER_LABELS.get(name, name),
            "ready": probe["ready"],
            "configured": probe["configured"],
            "enabled": provider_enabled(name),
            "note": provider_model(name),
            "error": probe["error"],
        }
        for name, probe in zip(names, probes)
    ]
    _PROBE_CACHE["at"] = now
    _PROBE_CACHE["result"] = out
    return out


async def test_provider(
    name: str,
    api_key: str | None = None,
    model: str | None = None,
    url: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Test one provider with optional unsaved overrides.

    Used by the Settings sheet's TEST button so a key can be checked before it
    is stored. Results are never cached, and the key is never echoed back.
    """
    import time

    if name not in HANDLERS:
        return {"ready": False, "error": "unknown provider", "provider": name}

    use_model = model or provider_model(name)
    started = time.monotonic()
    try:
        if name == "ollama":
            ok = await ollama_is_up(url or ollama_url())
            return {
                "provider": name,
                "ready": ok,
                "model": use_model,
                "error": None if ok else "not reachable",
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        if not (api_key or provider_key(name)):
            return {
                "provider": name,
                "ready": False,
                "model": use_model,
                "error": "no key set",
                "latency_ms": 0,
            }
        await HANDLERS[name](
            use_model,
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=1,
            timeout=timeout,
            key=api_key or None,
        )
        return {
            "provider": name,
            "ready": True,
            "model": use_model,
            "error": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            body = ""
        return {
            "provider": name,
            "ready": False,
            "model": use_model,
            "error": f"HTTP {exc.response.status_code}" + (f": {body[:120]}" if body else ""),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        return {
            "provider": name,
            "ready": False,
            "model": use_model,
            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

# ------------------------------------------------------- model download
#
# One tap fetches the small quantised model into DATA_DIR/models/ so the
# phone can answer with no internet from then on. The download runs on a
# background thread and reports progress here; the UI only polls.

LLM_MODEL_DEFAULT = "qwen2.5-1.5b"

# Public (ungated) GGUF. Meta's Llama 3.2 mirrors are all license-gated with
# HTTP 401, so a phone-side one-tap download must use an open repo; Qwen2.5
# is the strongest small instruct model that is genuinely fetchable without an
# account. Q4_K_M = ~1.1 GB on disk, ~1.7 GB RAM while running; the 0.5B is
# the quick set for low-RAM devices and flaky connections.
#
# Ordered mirror chain: Hugging Face first, hf-mirror as the proxy fallback,
# ModelScope (in Asia) last. A flaky link walks down the chain instead of
# dying on the first host.
LLM_MODEL_URLS: dict[str, list[str]] = {
    "qwen2.5-1.5b": [
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF"
        "/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF"
        "/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "https://www.modelscope.cn/api/v1/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/repo"
        "?FilePath=qwen2.5-1.5b-instruct-q4_k_m.gguf",
    ],
    "qwen2.5-0.5b": [
        "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "https://hf-mirror.com/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "https://www.modelscope.cn/api/v1/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF/repo"
        "?FilePath=qwen2.5-0.5b-instruct-q4_k_m.gguf",
    ],
}

# Exact byte length from the source repo. A model file is only trusted when
# it reaches this size (99% tolerance) - a dropped connection used to leave a
# half-written file that looked installed.
LLM_MODEL_EXPECTED = {
    "qwen2.5-1.5b": 1_117_320_736,
    "qwen2.5-0.5b": 491_400_032,
}

# UI-facing sizes (MiB) for the Quick/Full set labels.
LLM_MODEL_MIB = {"qwen2.5-1.5b": 1066, "qwen2.5-0.5b": 469}

# Minimum download attempts before giving up (each rotates the mirror).
# Tests lower this to keep failure paths fast.
_DL_ATTEMPTS = 6


def llm_model_ok(path: Path | None, name: str | None = None) -> bool:
    """True only for a model file that reached its expected size."""
    if path is None or not path.is_file():
        return False
    expected = LLM_MODEL_EXPECTED.get(name or path.stem, 0)
    if not expected:
        return path.stat().st_size >= 100_000_000
    return path.stat().st_size >= int(expected * 0.99)


_LLM_DL_LOCK = threading.Lock()
_LLM_DL: dict[str, Any] = {
    "state": "idle",  # idle | downloading | paused | ready | error
    "name": None,
    "bytes": 0,
    "total": 0,
    "reason": None,
    "partial": 0,  # bytes already on disk in .part (never thrown away)
    "pause": False,
}


def llm_model_status() -> dict[str, Any]:
    """Binary, model file, server and download state for the UI."""
    with _LLM_DL_LOCK:
        download = dict(_LLM_DL)
        download.pop("pause", None)
    proc = _LLAMACPP.get("proc")
    model = llamacpp_model_file()
    # Report partial bytes even when idle/paused (after a process death) so
    # the UI can offer "resume from X MB" instead of starting from zero.
    if download.get("state") in ("idle", "paused", "error") and download.get("name"):
        part = _part_file(str(download["name"]))
        if part.is_file():
            download["partial"] = part.stat().st_size
    return {
        "binary": llamacpp_bin() is not None,
        "model": {
            "present": model is not None,
            "file": model.name if model else None,
            "size": model.stat().st_size if model else None,
        },
        "server": (
            "running"
            if proc is not None and proc.poll() is None
            else ("stopped" if proc is not None else "never")
        ),
        "error": _LLAMACPP.get("error"),
        "download": download,
        "options": sorted(LLM_MODEL_URLS),
        "default": LLM_MODEL_DEFAULT,
    }


def _part_file(name: str) -> Path:
    return DATA_DIR / "models" / f"{name}.gguf.part"


def llm_download_start(name: str | None = None) -> dict[str, Any]:
    """Start the model download in the background; never blocks the caller."""
    name = name or LLM_MODEL_DEFAULT
    if name not in LLM_MODEL_URLS:
        return {"ok": False, "reason": f"unknown model {name!r}"}
    dest = DATA_DIR / "models" / f"{name}.gguf"
    if llm_model_ok(dest, name):
        return {"ok": True, "reason": "already installed"}
    with _LLM_DL_LOCK:
        if _LLM_DL["state"] == "downloading":
            return {"ok": True, "reason": "already running"}
        _LLM_DL.update(
            {
                "state": "downloading",
                "name": name,
                "bytes": 0,
                "total": 0,
                "reason": None,
                "pause": False,
            }
        )
    threading.Thread(
        target=_llm_download_worker, args=(name,), daemon=True
    ).start()
    return {"ok": True, "started": True}


def llm_download_pause() -> dict[str, Any]:
    """Ask the running download to stop, keeping the partial file."""
    with _LLM_DL_LOCK:
        if _LLM_DL["state"] != "downloading":
            return {"ok": True, "reason": "not downloading"}
        _LLM_DL["pause"] = True
    return {"ok": True, "reason": "pausing"}


def _llm_urls(name: str) -> list[str]:
    """Mirror chain for a model: custom override (settings/env) first, then
    the built-in Hugging Face → hf-mirror → ModelScope chain."""
    urls = list(LLM_MODEL_URLS[name])
    try:
        from . import db

        custom = db.get_setting("model.custom_url", "") or os.environ.get(
            "ATIF_ASSISTANT_LLM_MODEL_URL", ""
        )
    except Exception:  # noqa: BLE001 - settings must never break a download
        custom = os.environ.get("ATIF_ASSISTANT_LLM_MODEL_URL", "")
    if custom:
        urls.insert(0, custom)
    return urls


def _llm_download_worker(name: str) -> None:
    """Fetch the GGUF with resume + mirror fallback.

    Three rules, all learned from a phone on a flaky connection:
      * the .part file is NEVER deleted - every failed session keeps its
        bytes so the next one continues instead of starting over;
      * each attempt rotates to the next mirror in the chain, so one dead
        host cannot kill the download;
      * a stall (no data for 60 s) aborts the attempt instead of hanging.
    """
    import time
    import urllib.request

    urls = _llm_urls(name)
    expected = LLM_MODEL_EXPECTED.get(name, 0)
    dest = DATA_DIR / "models" / f"{name}.gguf"
    tmp = dest.with_suffix(".gguf.part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = "download failed"
    attempts = max(_DL_ATTEMPTS, len(urls) * 2)
    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        try:
            with _LLM_DL_LOCK:
                if _LLM_DL["pause"]:
                    _LLM_DL.update({"state": "paused", "reason": "paused by user"})
                    return
            have = tmp.stat().st_size if tmp.is_file() else 0
            if expected and have >= expected * 0.99:
                tmp.rename(dest)  # a prior attempt finished; nothing to fetch
                with _LLM_DL_LOCK:
                    _LLM_DL.update({"state": "ready", "reason": "installed"})
                return
            headers = {"User-Agent": "atif-assistant"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                resuming = have > 0 and getattr(resp, "status", 200) == 206
                clen = int(resp.headers.get("Content-Length") or 0)
                if have and not resuming:
                    have = 0  # server ignored Range: restart clean
                total = expected or (clen + (have if resuming else 0))
                with _LLM_DL_LOCK:
                    _LLM_DL.update({"total": total, "bytes": have})
                done = have
                mode = "ab" if have else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        with _LLM_DL_LOCK:
                            if _LLM_DL["pause"]:
                                _LLM_DL.update(
                                    {"state": "paused", "reason": "paused by user"}
                                )
                                return
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        with _LLM_DL_LOCK:
                            _LLM_DL["bytes"] = done
            got = tmp.stat().st_size if tmp.is_file() else 0
            if expected and got < expected * 0.99:
                raise OSError(
                    f"connection ended early ({got} of {expected} bytes)"
                )
            if not expected and total and got < total * 0.99:
                raise OSError(f"connection ended early ({got} of {total} bytes)")
            tmp.rename(dest)
            with _LLM_DL_LOCK:
                _LLM_DL.update({"state": "ready", "reason": "installed", "partial": 0})
            try:
                from . import applog

                applog.log("llm.model_ready", name=name, bytes=dest.stat().st_size)
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception as exc:  # noqa: BLE001 - rotate mirror, then fail soft
            last_error = str(exc)[:200] or type(exc).__name__
            if attempt < attempts - 1:
                time.sleep(1.5)
                continue
        break
    # Keep every byte: the next start resumes from here instead of zero.
    partial = tmp.stat().st_size if tmp.is_file() else 0
    reason = last_error
    if partial:
        reason = f"{last_error} — progress saved ({partial // 1048576} MB), tap resume"
    with _LLM_DL_LOCK:
        _LLM_DL.update({"state": "error", "reason": reason, "partial": partial})
    try:
        from . import applog

        applog.log("llm.model_failed", name=name, error=last_error, partial=partial)
    except Exception:  # noqa: BLE001
        pass
