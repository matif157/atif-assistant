"""Model gateway.

Tries free-tier providers in order and falls back cleanly. If no provider is
reachable, Atif Assistant still answers using a local heuristic engine so the app is
never silently useless.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from .config import (
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
        return True
    return str(override).strip().lower() not in {"0", "false", "off", "no"}


def ollama_url() -> str:
    """The local server URL: database override, else environment, else default."""
    override = _override("ollama", "url")
    if override is not None:
        return override
    return os.environ.get("ATIF_ASSISTANT_OLLAMA_URL", "http://127.0.0.1:11434")


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
                "options": {"temperature": kw.get("temperature", 0.4)},
            },
        )
        r.raise_for_status()
        return r.json()["response"]


HANDLERS = {
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
    configured = name == "ollama" or bool(key)
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
    return out


def available_providers() -> list[dict[str, Any]]:
    """Sync snapshot of provider *configuration* only.

    ``ready`` here is false for everything on purpose. A non-empty key string
    is not proof the key is accepted: a revoked or wrong-provider key (a
    ``sk-or-`` OpenRouter key pasted into GROQ_API_KEY, for instance) is still
    "configured" and would be reported ready by a presence check alone. Use
    ``probe_providers()`` for the live answer.
    """
    return [provider_status(name) for name in PROVIDER_ORDER]


async def _probe_one(name: str) -> dict[str, Any]:
    """Make the smallest possible real call to one provider."""
    if not provider_enabled(name):
        configured = name == "ollama" or bool(provider_key(name))
        return {"ready": False, "configured": configured, "error": "disabled"}
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

    probes = await asyncio.gather(*(_probe_one(n) for n in PROVIDER_ORDER))
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
        for name, probe in zip(PROVIDER_ORDER, probes)
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