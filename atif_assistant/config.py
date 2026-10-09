"""Atif Assistant configuration.

Everything is environment-driven so secrets never live in the repo.
Data stays local: the SQLite file is gitignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ATIF_ASSISTANT_DATA_DIR", ROOT / "data"))
WEB_DIR = ROOT / "web"
# Uploaded files land here. Local only, gitignored with the rest of data/.
UPLOADS_DIR = Path(os.environ.get("ATIF_ASSISTANT_UPLOADS_DIR", DATA_DIR / "uploads"))

# The SQLite database. Local only, never committed.
DB_PATH = DATA_DIR / "atif-assistant.db"

# Where the seeded archive lives. Read-only input.
ARCHIVE_DIR = Path(
    os.environ.get(
        "ATIF_ASSISTANT_ARCHIVE_DIR",
        ROOT.parent / "asked-questions-archive",
    )
)

PORT = int(os.environ.get("ATIF_ASSISTANT_PORT", "8770"))
HOST = os.environ.get("ATIF_ASSISTANT_HOST", "127.0.0.1")

# Tailscale funnel/serve hostname is advertised for convenience only.
TAILSCALE_HOST = os.environ.get("ATIF_ASSISTANT_TAILSCALE_HOST", "")


def _provider_order() -> list[str]:
    raw = os.environ.get(
        "ATIF_ASSISTANT_PROVIDERS",
        "groq,gemini,openrouter,ollama",
    )
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


PROVIDER_ORDER = _provider_order()

# Environment variable that holds each provider's key. An empty/missing value
# means "not configured"; the UI can also override these at runtime (see llm.py).
PROVIDER_ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

MODEL_DEFAULTS = {
    "groq": os.environ.get("ATIF_ASSISTANT_GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini": os.environ.get("ATIF_ASSISTANT_GEMINI_MODEL", "gemini-2.0-flash"),
    "openrouter": os.environ.get(
        "ATIF_ASSISTANT_OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
    ),
    "ollama": os.environ.get("ATIF_ASSISTANT_OLLAMA_MODEL", "llama3.2"),
}

PROVIDER_LABELS = {
    "groq": "Groq",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Local / Ollama",
}

# Retrieval
RETRIEVAL_LIMIT = int(os.environ.get("ATIF_ASSISTANT_RETRIEVAL_LIMIT", "5"))

# Pattern Radar: how many matching patterns to surface per message.
PATTERN_LIMIT = int(os.environ.get("ATIF_ASSISTANT_PATTERN_LIMIT", "2"))

DATA_DIR.mkdir(parents=True, exist_ok=True)