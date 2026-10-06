"""Model gateway.

Tries free-tier providers in order and falls back cleanly. If no provider is
reachable, Raees still answers using a local heuristic engine so the app is
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
    async with httpx.AsyncClient(timeout=60) as client:
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
    async with httpx.AsyncClient(timeout=60) as client:
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
    async with httpx.AsyncClient(timeout=60) as client:
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
    base = os.environ.get("RAEES_OLLAMA_URL", "http://127.0.0.1:11434")
    system = "\n\n".join(
        m["content"] for m in messages if m["role"] == "system"
    )
    prompt = "\n\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m["role"] != "system"
    )
    async with httpx.AsyncClient(timeout=120) as client:
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
    base = os.environ.get("RAEES_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/api/tags")
        return r.status_code == 200
    except Exception:
        return False


def available_providers() -> list[dict[str, Any]]:
    """Sync snapshot of provider configuration.

    Ollama reports ready=False here because reachability cannot be checked
    without I/O. Use ``ready_providers()`` for the live check.
    """
    keys = {
        "groq": "GROQ_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    out = []
    for name in PROVIDER_ORDER:
        if name == "ollama":
            out.append(
                {
                    "name": name,
                    "ready": False,
                    "note": "local - probed live at request time",
                }
            )
        else:
            out.append(
                {
                    "name": name,
                    "ready": bool(os.environ.get(keys.get(name, ""))),
                    "note": MODEL_DEFAULTS.get(name, ""),
                }
            )
    return out