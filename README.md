# Atif Assistant

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

Without a key, Atif Assistant still runs: retrieval, the Pattern Radar, the brake and
memory search all work. Only free-text generation is disabled.

---

## No modes. Atif Assistant routes.

There is no mode picker. You ask; Atif Assistant decides how the question deserves to
be answered, and shows you its reasoning above each reply.

| Your question looks like | Atif Assistant does | Why |
|---|---|---|
| *"does she love me more"* | CHALLENGED | Comparing feelings is not measurable. Answering it would invent certainty. |
| *"am I worth it"* | CHALLENGED | Nobody can hand out a verdict on your worth. The underlying need gets answered instead. |
| *"should I quit my job"* | DECIDED | A real decision with consequences. Options, reversibility, review date. |
| *"what is FTS5"* | ANSWERED | Knowledge question with a checkable answer. |
| *"should I see a doctor for chest pain"* | ANSWERED | Professional domain. Signposted before advising. |
| anything unrecognised | CHALLENGED | Unclassified requests default to the honest treatment, not the agreeable one. |

The route strip under each answer shows the mode and the one-line reason.

### Repetition escalation

Atif Assistant counts how often you ask each *class* of question. Ask the same class
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
injected into context ahead of the answer and surfaced in Insights. Atif Assistant must
state the conflict rather than silently pick a side.

### Memory learning

After each answer Atif Assistant reads the exchange and proposes durable facts. Three
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

A post-generation brake in `atif-assistant/engine.py` then audits the answer:

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

No `mode` field. The response carries the route Atif Assistant chose, why, the Reality
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
| `GET/POST /api/decisions` | decision ledger, due and open |
| `POST /api/decisions/{id}/resolve` | record what actually happened |
| `GET /api/evidence?q=` | full-text search over raw source lines |

---

## Memory

Seeded once from `../asked-questions-archive`:

| Source | Becomes |
|---|---|
| `CONTEXT.md` | facts (with confidence + last verified) |
| `CONTEXT-PROFESSIONAL.md` | professional identity, profile links, deployed work |
| `TIMELINE.md` | episodes |
| `AGENTS.md` | rules |
| `ASK-LATER.md` | open questions |
| `PATTERN.md` | patterns |

Re-seed any time:

```bash
.venv/bin/python scripts/seed_memory.py
```

It deletes and rebuilds seeded rows, so it is safe to repeat: running it twice
in a row leaves the database byte-identical by content hash. It also prunes
search-index entries whose parent row was deleted, so re-seeding does not leave
orphans that retrieval could cite.

Search memory from the UI with the **MEM** button.

`CONTEXT-PROFESSIONAL.md` holds the professional side: name, role, location,
every profile URL, and what is deployed where. It is a separate file because it
has a different half-life than the rest. URLs go stale; relationships do not.
Each claim carries a date it was last checked against a live source, so Atif Assistant
knows the difference between confirmed and merely claimed.

Unverified professional claims are stored as **rules**, not facts. A question is
not a fact, and storing "the Fiverr handle might be wrong" at high confidence
would let Atif Assistant assert it. Right now three are outstanding: which Fiverr handle
is live, whether the Upwork id changed, and whether to repair or retire the
InfinityFree mirror.

Session handover and prompt templates live in [`docs/SESSION-DOCS.md`](docs/SESSION-DOCS.md).

### Raw evidence

A confidence number is a claim about how much to trust something. On its own it
is an opinion. `scripts/ingest_evidence.py` loads the actual chat exports so a
stored fact can be traced back to the line it came from:

```bash
.venv/bin/python scripts/ingest_evidence.py --dry-run   # parse, write nothing
.venv/bin/python scripts/ingest_evidence.py             # ingest
```

It reads WhatsApp `.txt` exports, currently **41,634 messages** from 10 Jan to
2 Jun 2026 across 8 threads. Each line is hashed on its fields, so re-running
an unchanged export adds nothing; the second run reports 0 new. It sniffs a
prefix of each file rather than trusting the extension, because a blanket
`*.txt` sweep over a home directory picked up 848 files, 800 of them licences
and build artifacts.

Raw messages are stored verbatim on purpose. Retrieval that rewrites a
quotation is retrieval that cannot be checked. Access is local-only, the
database is gitignored, and the exports are read in place, never copied into
this repo.

Note the coverage gap: the ChatGPT export is not ingested, and no evidence
exists after 2 Jun 2026, so the 13 Jul doctor visit asserted in `AGENTS.md`
cannot be verified from raw lines yet.

---

## Decision ledger

A decision is only worth logging if you come back and check it. The ledger
stores a prediction, a confidence and a review date, then asks what actually
happened.

**LEDGER** in the header opens it. **LOG A DECISION** records one. Predictions
are stored exactly as typed and never rewritten, because the point of a
prediction is that it was made before the outcome. Resolving requires an
outcome to be written: an empty one is rejected, because resolving with a blank
string would discard the only datum that makes the entry worth keeping.

---

## Access from any device

Atif Assistant binds to `127.0.0.1` by default. Tailscale gives you a private URL that
works on any device on your account, with no port forwarding and no auth to
build.

On this machine Tailscale runs in **userspace mode**, which has no tun device.
That has one consequence worth knowing: the tailnet IP cannot be bound by a
local process, so `RAEES_BIND=tailnet` falls back to loopback and says so. Serve
proxies loopback and does not need a tun device, so it still works.

**Serve must be enabled once in the admin console** (it is off by default):

```
https://login.tailscale.com/f/serve
```

Approve the prompt for this node. Then start Atif Assistant and expose it:

```bash
./run.sh
export PATH="$HOME/.local/bin:$PATH"
ts serve --bg 8770
```

`ts` is a wrapper that passes the custom socket this installation uses. If you
are using the standard system Tailscale instead, `tailscale serve --bg 8770`
works and `ts` is unnecessary.

Atif Assistant is then reachable at `http://<your-machine-name>.<tailnet>.ts.net:8770`
from your phone or any other device signed into the same account.

Nothing is exposed to the public internet. Only devices on your tailnet can
reach it.

To undo:

```bash
ts serve reset
```

Note that the `tailscaled` process here was started by hand, so it does not come
back automatically after a restart. Re-run it, or install the Tailscale app if
you want this to survive reboots.

---

## Where this lives

The repo is at `~/Projects/atif-assistant`, not `~/Documents`. macOS protects
`~/Documents` from launchd agents, so an app living there cannot auto-start:
`run.sh` fails with `Operation not permitted` and the server never comes up,
with nothing in the log to suggest the cause.

`~/Projects` avoids that entirely and needs no Full Disk Access grant, which
matters because the alternative is granting `/bin/bash` read access to every
file on the machine just to start one app.

Both processes are LaunchAgents and come back at login:

| Label | What |
|---|---|
| `io.atif.assistant.tailscaled` | Tailscale daemon, custom socket, userspace mode |
| `io.atif.assistant.server` | this app, bound to loopback only |

```bash
launchctl kickstart -k gui/$(id -u)/io.atif.assistant.server   # restart the app
launchctl kickstart -k gui/$(id -u)/io.atif.assistant.tailscaled # restart the tunnel
launchctl list | grep atif-assistant                           # check both
```

`RAEES_ARCHIVE_DIR` in `.env` points back at the archive in `~/Documents`.
That is fine because the archive is read only when you seed, not at runtime,
and seeding runs in a shell rather than under launchd.

---

## Privacy

- The database lives in `data/atif-assistant.db` and is gitignored. It is never pushed.
- Your archive files are read at seed time only; they are not copied in.
- The PWA caches the app shell for offline opening, but `/api/*` is never
  cached, so answers are always live.
- The service worker is served from `/sw.js` at the origin root, not from
  `/static/sw.js`. Scope is derived from the script's own path, so a worker
  under `/static/` cannot control the page at `/`, and the offline shell and
  install-to-homescreen would silently do nothing. Change one without the other
  and there is no error in the browser to tell you.
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

An answer costs up to two model calls: a draft, then an adversarial audit that
returns a corrected version in the same response if it found defects. The third
stage in the diagram, the brake, is deterministic regex work and costs nothing.
Without a key the model calls are skipped entirely and the answer is honest
about not having reasoned.

Memory extraction is a separate call that runs after the answer, and only when
the reply looks like it contains a durable fact.

Swap SQLite for Postgres later only if you actually need it. For one user,
you almost certainly won't.

| File | Role |
|---|---|
| `atif-assistant/config.py` | env-driven settings |
| `atif-assistant/db.py` | schema, FTS5, contradictions, question ledger, test isolation |
| `atif-assistant/constitution.py` | invariants, brake rules, intent classifier |
| `atif-assistant/router.py` | mode selection and repetition escalation |
| `atif-assistant/radar.py` | pattern matching |
| `atif-assistant/llm.py` | provider failover, live Ollama probe, offline fallback |
| `atif-assistant/engine.py` | Reality Engine, challenge, decide, self-audit, brake |
| `atif-assistant/learn.py` | gated memory extraction |
| `atif-assistant/app.py` | API + static serving |
| `scripts/seed_memory.py` | archive → memory |
| `tests/test_core.py` | 81 tests |

---

## Tests

```bash
.venv/bin/python -m tests.test_core
```

112 checks across eleven groups:

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
| fts integrity | orphan detection, prune, re-index without duplicates |
| evidence | idempotent ingest, digest stability, duplicate refusal, orphan cleanup |
| evidence parsing | banner removal, multi-line join, timestamp normalisation, U+202F |
| isolation | the real database is unchanged, by row count and by content hash |

Every group runs against a scratch database. At the end of the run the test
suite compares the real database against a snapshot taken before it started,
both by row count and by a SHA-256 over every row. The digest is what makes the
claim meaningful: counts alone cannot distinguish "unchanged" from "one row
deleted and another added".

---

## Troubleshooting

**"no model key" in the header** — `.env` is missing or has no key. Ollama is
probed live, so it only shows ready when actually serving. Retrieval, routing,
the brake and the radar still work.

**Blank page** — hard reload. The service worker is network-first, so this
should be rare.

**Port busy** — `RAEES_PORT=8780 ./run.sh`

**Reinstall Python** — `uv python install 3.12 && uv venv --python 3.12`

**Rebuild the venv** — `requirements.lock` pins the exact dependency set the
working venv was built from, so a fresh rebuild is reproducible:

```bash
rm -rf .venv
uv venv --python 3.12
uv pip install -r requirements.lock
```

---

## Built

06 Oct 2026. v0.2.0.