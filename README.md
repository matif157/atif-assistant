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

A post-generation brake in `atif_assistant/engine.py` then audits the answer:

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
| `POST /api/location` | ingest one GPS fix (idempotent; folds into a place) |
| `GET /api/location` | recent fixes |
| `GET /api/places` | clustered places and visit counts |
| `POST /api/places/{id}/name` | give a place a name and kind |
| `GET /api/routines` | observed place/routine candidates |
| `POST /api/routines/derive` | rebuild routines from stored visits |
| `POST /api/upload` | ingest a file (base64/text JSON); readable files become memory |
| `POST /api/plan` | draft a strict plan from an upload or text; stores checkable rules |
| `GET /api/rules` | every stored rule, enforced first |
| `POST /api/rules/{id}/approve` | enforce a candidate rule |
| `DELETE /api/rules/{id}` | remove a rule |
| `POST /api/tts` | synthesize a spoken reply (WAV) for languages with no device voice |
| `POST /api/stt` | transcribe a recorded clip locally (whisper.cpp), for offline speech |
| `GET /api/speech` | what the offline speech stack has (model in use, engines ready) |
| `POST /api/speech/model` | download a better offline model (default `small`, best for Urdu) |
| `GET /api/media/{id}/content` | locate a stored upload on disk |
| `GET /api/export` | download the curated memory as JSON |
| `POST /api/import` | restore a backup, add-only (never deletes or overwrites) |
| `GET /api/providers` | provider config with masked keys and live readiness |
| `POST /api/providers/{name}` | set or clear a provider key/model/url, or toggle it on/off |
| `POST /api/providers/{name}/test` | test one provider (optionally with unsaved values) |
| `POST /api/providers/test` | test every provider |
| `GET/POST /api/settings` | stored key/value settings |
| `GET/POST /api/notes` | quick notes |
| `GET/POST /api/works` | tracked projects |
| `GET/POST /api/media` | media references |
| `GET/POST /api/social/accounts` | linked social accounts |
| `GET /api/social/posts` | synced posts |

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
local process, so `ATIF_ASSISTANT_BIND=tailnet` falls back to loopback and says so. Serve
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

`ATIF_ASSISTANT_ARCHIVE_DIR` in `.env` points back at the archive in `~/Documents`.
That is fine because the archive is read only when you seed, not at runtime,
and seeding runs in a shell rather than under launchd.

---

## Location and routines

Location is opt-in and local. Fixes arrive at `POST /api/location` from a
shortcut or an exported trace, are de-duplicated by a content digest, and are
folded into a place when they land within the existing place's radius
(default 150 m). A place is only *named* when you name it, or when you pass
`?geocode=1` and the network lookup succeeds.

`POST /api/routines/derive` groups visits by place, weekday and 3-hour bucket.
A bucket with enough visits becomes a **candidate** routine with a confidence
equal to distinct matching days over the place's total days. Candidates are
surfaced to the model only when a question is about location.

Two hard limits, by design:

- **Where and when are observed. Why is not.** GPS never tells you a reason, so
  the system never attaches one. Ask "why was I there" and the honest answer is
  that it is not recorded - only that you were.
- **No live tracking.** Nothing polls the phone. You push fixes in; the app does
  not pull them, and there is no background location service.

---

## Uploading files

`POST /api/upload` takes JSON (`{filename, content_b64, related_to, kind?}`),
so no multipart dependency is needed. Files land in `data/uploads/` keyed by
their sha256, so the same file is stored once.

Readable files are **actually read** into memory and become searchable evidence
plus a dated episode:

| Read locally | How |
|---|---|
| `.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.yml`, `.ini`, `.log`, `.srt` | decoded directly |
| `.html`, `.xml`, `.svg` | tags stripped, entities unescaped |
| `.pdf` | text layer via `pypdf` |
| `.docx`, `.pptx`, `.xlsx` | zipped XML via the standard library |
| WhatsApp `.txt` exports | parsed into a clean transcript with a participant summary |
| images, scanned PDFs | transcribed and described by **Gemini vision** when a Gemini key is set |
| voice notes (`.mp3`, `.m4a`, `.wav`, ...) | transcribed by **Groq Whisper** when a Groq key is set |
| images, scans, audio with no key | stored and referenced only |

Anything else - or an image, scan or voice note with no matching key - is stored
and referenced only. The response reports `read`, `read_chars`, `text_source`,
and `read_reason`, and the UI says whether the file was read or merely stored.
Nothing is guessed from bytes. Matching evidence lines are also offered to the
model on `/api/ask`, so the assistant can answer from a file you uploaded. Use
the **UPLOAD** button.

## Strict plans and rules

After a readable upload, **MAKE STRICT PLAN** (or `POST /api/plan` with a
`media_id` or raw `text`) asks the model to draft a short title and up to eight
concrete, checkable rules grounded only in that document. In strict mode those
rules are approved immediately and injected into every later answer as standing
commitments, so the assistant holds you to the plan instead of quietly dropping
it. Non-strict rules wait as candidates.

**RULES** in the header lists them, lets you enforce a candidate, and lets you
remove any rule. Nothing is added silently: an empty or unactionable document
produces a title with no rules, and with no provider the endpoint returns `503`
rather than inventing a plan.

---

## Offline and Android

The app is a PWA. See [`docs/OFFLINE-ANDROID.md`](docs/OFFLINE-ANDROID.md) for
installing it on a phone (Termux or Tailscale), using a local Ollama model, and
the honest note on why there is no signed APK yet. Build a portable bundle with
`./scripts/package_offline.sh` (excludes `data/`, `.venv/`, `.git/`).

---

## Voice call (hands-free)

The **CALL** button (top bar) starts a hands-free voice conversation:

1. it listens through the microphone,
2. sends what it heard as a normal question (same routing, labels and brake),
3. reads the answer aloud, then
4. listens again - until you tap **END CALL**.

The on-screen orb shows the live state (LISTENING / THINKING / SPEAKING). Tap the
orb while it is speaking to **interrupt** and take the turn back.

**Reply language is automatic by default.** **Settings → REPLY LANGUAGE** offers
*Automatic (match what I speak)*, *English* and *اردو (Urdu)*. On *Automatic* the
answer follows the language you actually wrote or spoke — Urdu script or Roman
Urdu get an Urdu answer, English gets English — so nobody has to remember to
change a setting before speaking Urdu. Pick English or Urdu to pin the reply
language regardless of the question. The spoken voice follows the resolved reply
language (so an Urdu answer is always read in Urdu), with a script test on the
answer as a final guard. **LANGUAGE / زبان** is the interface language and text
direction; **MICROPHONE LANGUAGE** is what you are understood to be speaking.

Most systems ship **no Urdu voice**, so the browser would read Urdu text with an
English voice and it comes out as gibberish. When the language has no matching
device voice the reply is synthesized **on the server** instead (`/api/tts`,
Gemini speech) and played back as audio; a device voice is used only when one
matches. If the Gemini voice is turned off or unreachable, `/api/tts` falls back
to the **offline `espeak-ng` voice** (which has Urdu), so spoken replies still
work with no network and no key. This also makes **TEST VOICE** work for Urdu.
Speaking a question with the mic makes the assistant answer **out loud** even if
SPEAK REPLIES is off, so the mic button is a real voice assistant. The Android bridge (`AndroidVoice`) is
used inside the app, otherwise the browser Web Speech API. Speech recognition
needs HTTPS (or localhost) and mic permission; browsers without it show a clear
message instead of failing silently. A stuck text-to-speech engine cannot stall
the call: a word-count fallback releases the loop if the speech event never
arrives.

### Offline speech (no internet, Urdu included)

The browser's Web Speech API sends audio to Google, so it cannot recognise
speech offline. If **whisper.cpp** and a GGML model are installed, Atif
Assistant records the clip and transcribes it **on the server** instead:

```sh
brew install whisper.cpp espeak-ng
mkdir -p ~/.local/share/atif-assistant/models
curl -L -o ~/.local/share/atif-assistant/models/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

The **small** model is preferred because it is markedly more accurate for Urdu
than **base**; if only base is present the app still uses it. **Settings →
SPEECH RECOGNITION** shows what is installed and, when only a weaker model is
present, offers a one-tap **DOWNLOAD URDU MODEL** (fetches `small` via
`POST /api/speech/model`). `GET /api/speech` reports the current model.

**Settings → SPEECH RECOGNITION** then offers *Automatic* (use the offline
engine whenever it is installed), *Browser (online)* or *On-device (offline)*.
The choice applies to both the mic button and the call, and the call becomes
possible even in browsers with no built-in recogniser. `/api/health` reports
`speech.offline_in` (recognition) and `speech.offline_out` (speech synthesis) so
the app knows what is available. Everything fails soft: if the tool or model is
missing, the browser recogniser is used and a clear reason is shown.

The server locates `whisper-cli` and `espeak-ng` even under launchd's minimal
`PATH` (it also searches `/opt/homebrew/bin` and `/usr/local/bin`), and the
LaunchAgent sets a PATH for good measure. Model and binary paths are
overridable with `ATIF_ASSISTANT_WHISPER_MODEL`, `ATIF_ASSISTANT_MODEL_DIR`,
`ATIF_ASSISTANT_WHISPER_BIN` and `ATIF_ASSISTANT_ESPEAK_BIN`.

The call stays **on-brand**: it is not a chatty companion. Social
pleasantries ("how are you", "what's your name", greetings) are routed to a single
direct labelled line - never "I'm good, what about you?" - and a brake fires if
the model ever slips into small talk or a fake-persona reply.

---

## Models & API keys

Atif Assistant tries providers in order (`groq → gemini → openrouter → ollama`)
and falls back to an offline answer if none is reachable. **Settings → MODELS &
API KEYS** manages them without editing files: each provider has an on/off
**toggle**, a key field, a model field, a **TEST** button, and there is a
**TEST ALL**. A key can be tested before it is saved.

The toggle is stored as `provider.<name>.enabled`; a **disabled provider is
skipped entirely** — no call, no quota — and is never probed. Turning all hosted
providers off leaves only local Ollama, which gives a **private, offline chat**:
answers keep working with the network gone. (The toggle is why the same masked
keys can stay saved while a provider is parked.)


Resolution order for a key or model is **saved setting → `.env` → built-in
default**. Saving an empty key (or CLEAR) stores a blank, which *is* an override,
so clearing a key in the UI really disables it even if `.env` still holds one.

Keys are stored in the local, gitignored database and are **never returned** by
the API — only a masked hint (`…last4`). They are also excluded from
`/api/settings` and from `EXPORT DATA` backups. This is a local-only app on your
machine; the values are not encrypted at rest.

Defaults are chosen to actually work on a free account:

| Provider | Default model | Note |
|---|---|---|
| Groq | `openai/gpt-oss-120b` | free tier, fastest; also powers Whisper transcription |
| Gemini | `gemini-3.8-flash` | multimodal: chat fallback *and* image/scan reading |
| OpenRouter | `nvidia/nemotron-3-super-120b-a12b:free` | key works, but free models rate-limit (`429`) until the account has credits |
| Ollama | `llama3.2:1b` | local and offline, ~1.3 GB, ~1 GB RAM; set the URL too |

Gemini keys are sent as the `x-goog-api-key` header (query-string keys are
rejected by newer keys). Transient `429`/`503` "high demand" replies are retried
a few times before a provider is skipped, so a busy free tier degrades to the
next provider instead of failing outright.

### A small local model

For offline use, a lite local model is plenty: it only has to follow the
labelled format, not write essays.

```bash
brew install ollama
brew services start ollama
ollama pull llama3.2:1b
```

`llama3.2:1b` (~1.3 GB, runs in about 1 GB of RAM) is the sweet spot on an 8 GB
Mac. `qwen2.5:0.5b` (~400 MB) is the smallest usable option if space or memory is
tight. Ollama runs last in the failover order, so remote providers are used when
reachable and the app keeps working when the network is gone.

---

## Backup

**Settings → EXPORT DATA** downloads a JSON snapshot of the curated memory
(facts, episodes, patterns, rules, decisions, learned candidates, notes, works,
media metadata, places, location points, routines, settings). **IMPORT DATA**
restores one. Import is add-only and de-duplicated: it can add missing memory
but can never delete or overwrite what is already there (an existing setting is
left untouched, so a restored backup cannot flip a live preference), meaning a
malformed backup cannot damage the live database. Raw chat transcripts and raw
source lines are intentionally not included.

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
| `atif_assistant/config.py` | env-driven settings |
| `atif_assistant/db.py` | schema, FTS5, contradictions, question ledger, backup, test isolation |
| `atif_assistant/constitution.py` | invariants, brake rules, intent classifier |
| `atif_assistant/router.py` | mode selection and repetition escalation |
| `atif_assistant/radar.py` | pattern matching |
| `atif_assistant/llm.py` | provider failover, live Ollama probe, offline fallback |
| `atif_assistant/engine.py` | Reality Engine, challenge, decide, self-audit, brake |
| `atif_assistant/learn.py` | gated memory extraction |
| `atif_assistant/location.py` | place naming / geocoding |
| `atif_assistant/uploads.py` | file ingest → memory |
| `atif_assistant/extract.py` | text/PDF/Office/WhatsApp extraction |
| `atif_assistant/vision.py` | images and scans via a vision model (Gemini) |
| `atif_assistant/transcribe.py` | voice notes via Groq Whisper |
| `atif_assistant/tts.py` | server speech (Gemini) with an offline `espeak-ng` fallback |
| `atif_assistant/stt.py` | offline speech recognition via whisper.cpp |
| `atif_assistant/plan.py` | document → strict checkable plan |
| `atif_assistant/app.py` | API + static serving |
| `scripts/seed_memory.py` | archive → memory |
| `scripts/ingest_evidence.py` | chat exports → raw evidence |
| `tests/test_core.py` | 332 checks |

---

## Tests

```bash
.venv/bin/python -m tests.test_core
```

332 checks across twenty-eight groups:

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
| critique parsing | self-audit verdict parsing, defect extraction |
| isolation | the real database is unchanged, by row count and by content hash |
| remote web | index served at root, service worker scope, manifest |
| extended API | memory/evidence/decisions/notes/works/media/social endpoints |
| location | ingest dedup, place clustering, naming, routine derivation |
| uploads | sha256 dedupe, text→evidence+episode, media-library listing |
| extract | text/markup/PDF/docx/xlsx decoded; WhatsApp parsed; unreadable files report a reason |
| upload reading | readable uploads report read + chars and reach evidence search; images report read=false |
| read fallbacks | images go to the vision model, audio to transcription when configured; honest reason when not |
| plan | document → grounded TITLE/RULE draft; strict rules enforced, candidates approvable, rules removable |
| tts | server speech for voice-less languages, offline `espeak-ng` fallback, label stripping, valid WAV, honest 503 when it cannot |
| stt | offline recognition language mapping, missing tool/model fail soft, `/api/stt` transcript and honest 503, health reports the engines |
| backup | export snapshot, add-only de-duplicated import, bad-file rejection |
| providers | key/model precedence, masking, settings/export redaction, save/clear, on/off toggle, TEST endpoint |
| ask endpoint | every question class routes to the honest mode; exchange persisted; repeat counting |
| misc endpoints | memory search, evidence, decision resolve + 404 guards, learned approve/reject, media content |
| structure guard | Reality Engine labels + CASE AGAINST enforced; revision repaired or rejected |

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

**Port busy** — `ATIF_ASSISTANT_PORT=8780 ./run.sh`

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