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

## No modes. Raees routes.

There is no mode picker. You ask; Raees decides how the question deserves to
be answered, and shows you its reasoning above each reply.

| Your question looks like | Raees does | Why |
|---|---|---|
| *"does she love me more"* | CHALLENGED | Comparing feelings is not measurable. Answering it would invent certainty. |
| *"am I worth it"* | CHALLENGED | Nobody can hand out a verdict on your worth. The underlying need gets answered instead. |
| *"should I quit my job"* | DECIDED | A real decision with consequences. Options, reversibility, review date. |
| *"what is FTS5"* | ANSWERED | Knowledge question with a checkable answer. |
| *"should I see a doctor for chest pain"* | ANSWERED | Professional domain. Signposted before advising. |
| anything unrecognised | CHALLENGED | Unclassified requests default to the honest treatment, not the agreeable one. |

The route strip under each answer shows the mode and the one-line reason.

### Repetition escalation

Raees counts how often you ask each *class* of question. Ask the same class
three times and the loop itself becomes the subject:

> This class of question has come up 5 times. Stop re-answering it. Name the
> loop and address it directly.

The answer chip shows `ASKED 5x` so you can see the count.

### Insights

The `INSIGHTS` button shows the distribution of what you actually ask. After
a few sessions it will tell you plainly something like:

> 6 of 10 questions are comparisons between people. That is the dominant shape
> of what you ask, and it has no possible answer.

It also lists conflicting stored facts.

---

## Adversarial self-audit

Every answer is audited before you see it. A second pass tries to find the
draft's failures:

```
VERDICT: SOUND | NEEDS_REVISION
DEFECTS: numbered list
REVISION: corrected answer, or EMPTY
```

Six failure modes are checked: fabrication, sympathy drift, premise
compliance, missed question, label dishonesty, rumination enablement. A
challenge is checked for a seventh — whether it actually pushed back.

If defects are found, the revision replaces the draft. A revision that is
empty, truncated, or too short to be an answer is discarded rather than
replacing a working draft. Failures are soft: a broken audit never breaks the
answer.

Challenges get audited hardest, because the user's position is emotionally
loaded and drift toward validating is most likely there.

### The brake

After the audit, a deterministic pass runs over the final text:

| Caught | Warning |
|---|---|
| `"she loved him 40% more"` | comparison or percentage the evidence does not support |
| no Reality Engine labels | claims are unverified |
| `"but you decide"`, `"only you can know"` | handed the decision back instead of reasoning |
| `"you're doing great"`, `"your feelings are valid"` | reassurance language in place of analysis |
| challenge missing `CASE AGAINST` | the challenge did not happen |

### Contradiction detection

Subject/value pairs are extracted from every fact and indexed separately. When
two stored facts about the same subject cannot both be true, the conflict is
injected into context ahead of the answer and surfaced in Insights. Raees must
state the conflict rather than silently pick a side.

### Memory learning

After each answer Raees reads the exchange and proposes durable facts. Three
gates must all pass:

1. the model proposes it in strict `FACT | subject | statement` format
2. it is first-person and **durable** — a feeling, belief, or clinical claim
   is rejected outright
3. it is not already in memory

Anything that passes lands as a **candidate**. It is never promoted to a
curated fact, and never becomes a rule, without your explicit approval in the
LEARNED sheet. Constitution principle 06: memory may not silently change
rules.

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

Applied automatically whenever a comparison or a self-worth verdict is asked.
Builds the case against your position:

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

## API

```bash
curl -s -X POST http://127.0.0.1:8770/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"should I quit my job"}'
```

No `mode` field. The response carries the route Raees chose, why, the Reality
labels, brake warnings, self-audit notes, pattern hits, and repeat count.

| Endpoint | Purpose |
|---|---|
| `POST /api/ask` | ask a question |
| `GET /api/insights` | question distribution, reading, contradictions |
| `GET /api/learned` | memory candidates awaiting approval |
| `POST /api/learned/{id}/approve` | promote a candidate to a curated fact |
| `POST /api/learned/{id}/reject` | discard a candidate |
| `GET /api/memory?q=` | FTS5 search across all memory kinds |
| `GET /api/health` | status and counts |
| `GET /api/history/{session}` | conversation history |
| `GET/POST /api/decisions` | decision ledger |

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
   │  HTTP  —  one question, no mode
   ▼
app.py
   │
   ├── router.py      classify → pick treatment → escalate on repetition
   │        │
   │        ▼
   ├── engine.py      Reality Engine, challenge structure, decision structure
   │        │
   │        ├── pass 1   draft
   │        ├── pass 2   adversarial self-audit → revision
   │        └── pass 3   deterministic brake
   │
   ├── radar.py       pattern matching
   ├── constitution.py  invariants, rumination, intent, professional domains
   ├── learn.py       gated memory extraction → candidates → your approval
   │
   ├── db.py  ──▶  SQLite (FTS5 + claims_fts)
   │                facts · episodes · patterns · rules ·
   │                decisions · questions · learned
   │
   └── llm.py         Groq → Gemini → OpenRouter → Ollama
```

Every answer costs up to three model calls: draft, audit, and a revision if
the audit found defects. Without a key, one call is skipped and the answer is
honest about not having reasoned.

Swap SQLite for Postgres later only if you actually need it. For one user,
you almost certainly won't.

| File | Role |
|---|---|
| `raees/config.py` | env-driven settings |
| `raees/db.py` | schema, FTS5, contradictions, question ledger, test isolation |
| `raees/constitution.py` | invariants, brake rules, intent classifier |
| `raees/router.py` | mode selection and repetition escalation |
| `raees/radar.py` | pattern matching |
| `raees/llm.py` | provider failover, live Ollama probe, offline fallback |
| `raees/engine.py` | Reality Engine, challenge, decide, self-audit, brake |
| `raees/learn.py` | gated memory extraction |
| `raees/app.py` | API + static serving |
| `scripts/seed_memory.py` | archive → memory |
| `tests/test_core.py` | 81 tests |

---

## Tests

```bash
.venv/bin/python -m tests.test_core
```

81 checks across eight groups:

| Group | Covers |
|---|---|
| brake | fabricated rankings, missing labels, hedging-out, reassurance, missing challenge sections |
| router | ten routing cases, unclassified default, distress signal, repetition escalation, question classes |
| radar | clock tokens, false positives, generic words |
| retrieval | multi-word queries, empty queries, stopwords |
| contradictions | negation detection, non-negated differences excluded |
| learning gates | feelings, beliefs, clinical claims, third parties rejected; approve and reject round trips |
| extraction | strict format parsing, dedup, EMPTY marker, offline no-op |
| question ledger | counts, distribution |
| isolation | the real database is unchanged |

Every group runs against a scratch database. `test_isolation` asserts the real
one is byte-for-byte unchanged after the whole run.

---

## Troubleshooting

**"no model key" in the header** — `.env` is missing or has no key. Ollama is
probed live, so it only shows ready when actually serving. Retrieval, routing,
the brake and the radar still work.

**Blank page** — hard reload. The service worker is network-first, so this
should be rare.

**Port busy** — `RAEES_PORT=8780 ./run.sh`

**Reinstall Python** — `uv python install 3.12 && uv venv --python 3.12`

---

## Built

06 Oct 2026. v0.2.0.