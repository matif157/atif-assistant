"""Model gateway.

Tries free-tier providers in order and falls back cleanly. If no provider is
reachable, Atif Assistant still answers using a local heuristic engine so the app is
never silently useless.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .config import MODEL_DEFAULTS, PROVIDER_ORDER


class ProviderError(RuntimeError):
    pass


async def _groq(model: str, messages: list[dict], **kw: Any) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise ProviderError("no GROQ_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _gemini(model: str, messages: list[dict], **kw: Any) -> str:
    key = os.environ.get("GEMINI_API_KEY")
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
        f"{model}:generateContent?key={key}"
    )
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await client.post(
            url,
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": turns,
                "generationConfig": {
                    "temperature": kw.get("temperature", 0.4),
                    "maxOutputTokens": kw.get("max_tokens", 1800),
                },
            },
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _openrouter(model: str, messages: list[dict], **kw: Any) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ProviderError("no OPENROUTER_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await client.post(
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
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _ollama(model: str, messages: list[dict], **kw: Any) -> str:
    base = os.environ.get("ATIF_ASSISTANT_OLLAMA_URL", "http://127.0.0.1:11434")
    system = "\n\n".join(
        m["content"] for m in messages if m["role"] == "system"
    )
    prompt = "\n\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m["role"] != "system"
    )
    async with httpx.AsyncClient(timeout=kw.get("timeout", 120)) as client:
        r = await client.post(
            f"{base}/api/generate",
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
        handler = HANDLERS.get(name)
        if handler is None:
            continue
        try:
            text = await handler(
                MODEL_DEFAULTS.get(name, ""), messages, temperature=temperature,
                max_tokens=max_tokens,
            )
            if text and text.strip():
                return text.strip(), name
        except Exception as exc:  # noqa: BLE001 - try the next provider
            last_error = exc
            continue

    raise ProviderError(f"no provider available: {last_error}")


async def ollama_is_up() -> bool:
    """Actually probe Ollama. Being configured is not being ready."""
    base = os.environ.get("ATIF_ASSISTANT_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/api/tags")
        return r.status_code == 200
    except Exception:
        return False


PROVIDER_KEYS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def available_providers() -> list[dict[str, Any]]:
    """Sync snapshot of provider *configuration* only.

    ``ready`` here is false for everything on purpose. A non-empty key string
    is not proof the key is accepted: a revoked or wrong-provider key (a
    ``sk-or-`` OpenRouter key pasted into GROQ_API_KEY, for instance) is still
    "configured" and would be reported ready by a presence check alone. Use
    ``probe_providers()`` for the live answer.
    """
    out = []
    for name in PROVIDER_ORDER:
        out.append(
            {
                "name": name,
                "ready": False,
                "configured": bool(os.environ.get(PROVIDER_KEYS.get(name, "")))
                if name != "ollama"
                else True,
                "note": MODEL_DEFAULTS.get(name, ""),
            }
        )
    return out


# Live probe results, cached so a status poll does not spend API quota.
_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "result": None}
_PROBE_TTL = 120.0


async def _probe_one(name: str) -> dict[str, Any]:
    """Make the smallest possible real call to one provider."""
    key = PROVIDER_KEYS.get(name)
    if name != "ollama" and not os.environ.get(key or ""):
        return {"ready": False, "configured": False, "error": "no key set"}
    if name == "ollama":
        ok = await ollama_is_up()
        return {
            "ready": ok,
            "configured": True,
            "error": None if ok else "ollama not reachable",
        }
    handler = HANDLERS.get(name)
    try:
        await handler(
            MODEL_DEFAULTS.get(name, ""),
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=1,
            timeout=6,
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
            "ready": probe["ready"],
            "configured": probe["configured"],
            "note": MODEL_DEFAULTS.get(name, ""),
            "error": probe["error"],
        }
        for name, probe in zip(PROVIDER_ORDER, probes)
    ]
    _PROBE_CACHE["at"] = now
    _PROBE_CACHE["result"] = out
    return out