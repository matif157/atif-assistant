"""Raees configuration.

Everything is environment-driven so secrets never live in the repo.
Data stays local: the SQLite file is gitignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RAEES_DATA_DIR", ROOT / "data"))
WEB_DIR = ROOT / "web"

# The SQLite database. Local only, never committed.
DB_PATH = DATA_DIR / "raees.db"

# Where the seeded archive lives. Read-only input.
ARCHIVE_DIR = Path(
    os.environ.get(
        "RAEES_ARCHIVE_DIR",
        ROOT.parent / "asked-questions-archive",
    )
)

PORT = int(os.environ.get("RAEES_PORT", "8770"))
HOST = os.environ.get("RAEES_HOST", "127.0.0.1")

# Tailscale funnel/serve hostname is advertised for convenience only.
TAILSCALE_HOST = os.environ.get("RAEES_TAILSCALE_HOST", "")


def _provider_order() -> list[str]:
    raw = os.environ.get(
        "RAEES_PROVIDERS",
        "groq,gemini,openrouter,ollama",
    )
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


PROVIDER_ORDER = _provider_order()

MODEL_DEFAULTS = {
    "groq": os.environ.get("RAEES_GROQ_MODEL", "llama-3.3-70b-versatile"),
    "gemini": os.environ.get("RAEES_GEMINI_MODEL", "gemini-2.0-flash"),
    "openrouter": os.environ.get(
        "RAEES_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct"
    ),
    "ollama": os.environ.get("RAEES_OLLAMA_MODEL", "llama3.2"),
}

# Retrieval
RETRIEVAL_LIMIT = int(os.environ.get("RAEES_RETRIEVAL_LIMIT", "5"))

# Pattern Radar: how many matching patterns to surface per message.
PATTERN_LIMIT = int(os.environ.get("RAEES_PATTERN_LIMIT", "2"))

DATA_DIR.mkdir(parents=True, exist_ok=True)