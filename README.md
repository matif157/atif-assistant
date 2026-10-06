# Raees

A personal intelligence system. Persistent memory, a Reality Engine that
labels every claim, a Challenge Mode that argues against you, and a Pattern
Radar that notices recurring behaviour before you do.

Runs on your Mac. Access it from any device with a browser. Memory stays local.

---

## Quick start

```bash
./run.sh
```

Then open **http://127.0.0.1:8770**

To enable reasoning, copy the env template and add one free API key:

```bash
cp .env.example .env
# edit .env, paste a GROQ_API_KEY
./run.sh
```

Without a key, Raees still runs: retrieval, the Pattern Radar, the brake and
memory search all work. Only free-text generation is disabled.

---

## The three features

### Reality Engine

Every substantive claim gets a label.

```
[FACT]        directly supported by evidence
[INFERENCE]   a reasoned conclusion from those facts
[ASSUMPTION]  believed but not established
[UNKNOWN]     the information cannot determine it
[PREDICTION]  likely, not certain
```

A post-generation brake in `raees/engine.py` then audits the answer:

- Any manufactured comparison or percentage is flagged and withdrawn.
- An answer with no labels at all is flagged as unverified.

### Challenge Mode

`/challenge` builds the case against your position:

```
CASE FOR · CASE AGAINST · WHAT YOU ARE OVERLOOKING
WHAT EMOTION IS DRIVING THIS · WORST CASE · BEST CASE
MOST PROBABLE · BETTER ALTERNATIVE · RECOMMENDATION
```

It is instructed to have a view and not to end with "but you decide".

### Pattern Radar

Every message is matched against stored patterns by trigger keywords. When one
fires, the response carries an intervention note.

The patterns are seeded from `asked-questions-archive`. See
`scripts/seed_memory.py` for the full list, which includes:

- **Uncertainty seeking loop** - search, compare, request certainty, doubt, repeat
- **Validation outsourcing** - borrowing self-worth from a verdict
- **Early full disclosure** - trauma shared before reciprocity
- **Score and rank seeking** - asking for numbers, then arguing with them
- **Unavailable partner selection** - choosing partners who are taken
- **Late-night contact** - messages between midnight and 04:00

Matching is deliberately conservative. Multi-word triggers must match
substantially, and generic words (`what`, `when`, `which`) are ignored, so
"what is the capital of France" does not trigger a relationship pattern.

---

## Modes

| Mode | Command | Purpose |
|---|---|---|
| Ask | default | labelled answer with retrieved memory |
| Challenge | `/challenge` | argue against the position |
| Decide | `/decide` | options, reversibility, consequences, recommendation |

Click the mode buttons or type the slash command.

---

## Memory

Seeded once from `../asked-questions-archive`:

| Source | Becomes |
|---|---|
| `CONTEXT.md` | facts (with confidence + last verified) |
| `TIMELINE.md` | episodes |
| `AGENTS.md` | rules |
| `ASK-LATER.md` | open questions |
| `PATTERN.md` | patterns |

Re-seed any time:

```bash
.venv/bin/python scripts/seed_memory.py
```

It deletes and rebuilds seeded rows, so it is safe to repeat.

Search memory from the UI with the **MEM** button.

---

## Access from any device

Raees binds to `127.0.0.1` by default. Tailscale gives you a private URL that
works on any device on your account, with no port forwarding and no auth to
build.

**One-time setup (needs your login):**

```bash
open -a Tailscale
```

Sign in, approve the Mac, then expose Raees:

```bash
tailscale serve --bg 8770
```

Raees is then reachable at `http://<your-machine-name>.<tailnet>.ts.net:8770`
from your phone or any other device signed into the same account.

Nothing is exposed to the public internet. Only devices on your tailnet can
reach it.

To undo:

```bash
tailscale serve reset
```

---

## Privacy

- The database lives in `data/raees.db` and is gitignored. It is never pushed.
- Your archive files are read at seed time only; they are not copied in.
- The PWA caches the app shell for offline opening, but `/api/*` is never
  cached, so answers are always live.
- With a cloud model key, your **questions** are sent to that provider.
  **Memory stays local.**

---

## Architecture

Deliberately one process and one file. No Postgres, no Redis, no Docker,
no Celery, no build step.

```
Browser (PWA)
   │  HTTP
   ▼
FastAPI process  ──▶  SQLite (FTS5)          raees/db.py
   │                    ▲
   │                    └── seeded from archive
   │
   ├── Reality Engine + brake        raees/engine.py
   ├── Pattern Radar                 raees/radar.py
   ├── Constitution                  raees/constitution.py
   └── Model gateway                 raees/llm.py
         └── Groq → Gemini → OpenRouter → Ollama
```

Swap SQLite for Postgres later only if you actually need it. For one user,
you almost certainly won't.

| File | Role |
|---|---|
| `raees/config.py` | env-driven settings |
| `raees/db.py` | schema, FTS5 retrieval, test isolation |
| `raees/constitution.py` | invariants, brake rules, intent classifier |
| `raees/radar.py` | pattern matching |
| `raees/llm.py` | provider failover + offline fallback |
| `raees/engine.py` | Reality Engine, Challenge, Decide |
| `raees/app.py` | API + static serving |
| `scripts/seed_memory.py` | archive → memory |
| `tests/test_core.py` | 27 tests over brake, radar, retrieval |

---

## Tests

```bash
.venv/bin/python -m tests.test_core
```

Covers the brake (fabricated rankings, missing labels), the radar (clock
tokens, false positives, generic words) and retrieval (multi-word queries,
empty queries, stopwords). The suite runs against a scratch database and
asserts the real one is unchanged.

---

## Troubleshooting

**"no model key" in the header** — `.env` is missing or has no key. Retrieval
still works.

**Blank page** — hard reload. The service worker is network-first, so this
should be rare.

**Port busy** — `RAEES_PORT=8780 ./run.sh`

**Reinstall Python** — `uv python install 3.12 && uv venv --python 3.12`

---

## Built

06 Oct 2026. v0.1.0.