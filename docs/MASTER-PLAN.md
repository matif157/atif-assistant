# ATIF ASSISTANT — MASTER PLAN v1.0

Status: **APPROVED · FROZEN** (2026-10-17)
Vision: **Human Life Assistant with AI — Atif with emotions, adopting the user's
thought pattern and talking way, always updating himself to become better, like
the user exactly.**
This document is the single source of truth for structure and phases. Every
phase must follow it strictly; changes to this document require an explicit
revision note at the bottom.

---

## Locked decisions

| Decision | Choice |
|---|---|
| Persona | **Full free companion** — Atif jokes, holds opinions, shows real warmth; never claims to be human or have personal experiences |
| Order | **Brain first** — foundation → soul → mirror → self-improvement → UI → life data → release |
| Voice language | **Urdu-first** — warmth and personality in Urdu/Roman-Urdu; technical answers stay English when the question is English |
| Feedback model | **Propose-then-approve** — nothing changes rules silently (constitution invariant) |
| Platforms | One codebase: Mac server (`127.0.0.1:8770`) · PWA web UI · APK (same web + Python packed) |

---

## Master structure

```text
┌──────────────────────────────────────────────────────────────┐
│  SURFACE  ·  one PWA, three renders                          │
│  Home(dashboard) · Chat · Life · Profile · Insights          │
│  + APK shell (voice bridge, biometric lock, notifications)   │
├──────────────────────────────────────────────────────────────┤
│  CONVERSATION API                                            │
│  /api/ask (streaming, phase 5) · /api/sessions · /api/feedback│
├──────────────────────────────────────────────────────────────┤
│  SOUL LAYER (new)                                            │
│  persona.py    – Atif's voice + constitution v2              │
│  emotion.py    – mood detection (en + ur + roman-urdu lexicon│
│                  + conversation context → labelled INFERENCE)│
│  style.py      – 3-dimension profile + few-shot mirroring    │
│  reflection.py – feedback → reflection → approved self-update│
├──────────────────────────────────────────────────────────────┤
│  REASONING (existing, untouched core)                        │
│  router · engine(modes) · brake · radar · pipeline · learn   │
├──────────────────────────────────────────────────────────────┤
│  MEMORY (21 tables) + NEW: user_profile · mood_history       │
│  feedback · reflections · sessions (managed)                 │
└──────────────────────────────────────────────────────────────┘
```

Message data flow: input → emotion detect → style profile + 2–4 of the user's
own past-message examples → `build_context()` (existing) → persona-calibrated
generation → save → feedback hooks → background: learn facts (existing) +
extract style deltas (new) + log mood (new).

### Constitution v2 rules (Phase 2 — the sensitive change)

Changes: identity block rewritten to the free companion; persona-slip guards
(`engine.py` 465–510 region) inverted; router social-question rule answers
warmly; `learn.py` feelings-block stays **only** for the facts channel;
rumination responses become warm + redirect.

Never breaks (unchanged invariants): truth before comfort · reality labels ·
no fabricated certainty · no invented comparisons · professional verification
for medical/legal/financial · memory never silently changes rules ·
**new:** never claim human experiences or memories Atif does not have ·
never push dependence over real people or professional help.

---

## Phases (each standalone; a missing phase breaks nothing)

| # | Phase | Deliverables | Gate |
|---|---|---|---|
| 1 | **Zero-Error Foundation** | NEW CHAT + history picker + `/api/sessions`; `/api/feedback` plumbing; audit fixes; this document; test guards for session isolation | tests green · CI · APK rebuilt · pushed |
| 2 | **Soul — full persona + emotions + Urdu-first** | constitution v2 + persona rewrite + inverted guards; `emotion.py` (en/ur/roman-urdu, context window, labelled INFERENCE); Urdu-first language resolver; mood chip + mood timeline UI; rewritten persona test suite | new soul tests · brake intact · labels intact |
| 3 | **Mirror — thought-pattern adoption** | `style.py` 3-dimension profile in `user_profile`; few-shot of user's own messages; EMA tracking (length, formality, urdu-ratio); editable Profile card UI | profile bounded in prompt · never leaks into facts |
| 4 | **Evolution — self-update loop** | thumbs/edit/regenerate signals → `reflection.py` → propose-then-approve updates; Growth tab in Insights; self-critique fed by mood+style context | zero silent rule changes |
| 5 | **Pro UI — advanced layout & interactions** | token streaming + stop/regenerate; message actions; skeletons/toasts/micro-animations (reduced-motion safe); Home dashboard; design tokens; aria-live + focus rings; Android haptics | sync tests + node check |
| 6 | **Human Life Data** | 5 stub importers completed (propose-then-approve); auto task extraction → todos; reminders + Android notification channel; routines/notes/places on Home | importer tests green |
| 7 | **Release (Phase F)** | targetSdk 36; 16 KB rebuild of llama+whisper (currently verified 4 KB); AAB; foreground service; **install on the real phone + user verification** | Play checklist |

## Execution rules

1. GitHub-first: every phase ends tests green → APK built → commit → push.
2. Never edit a test to make it pass.
3. Every personality change ships with its safety tests.
4. Propose-then-approve for anything that becomes a rule.
5. Truth labels and the brake always survive persona warmth.

## Baseline at freeze

- Tests: 474 checks green; CI green; `node --check` green.
- APK: signed v2/v3, web assets hash-verified fresh; native libs 4 KB (not 16 KB).
- Known backlog: 5 stub importers; no streaming; no notifications; no real-device install.

---

### Revisions
- v1.0 (2026-10-17): initial freeze after full audit + research
  (style: ACL 2025 few-shot/difference-aware modeling; emotion: prompt enrichment
  + uncertainty-aware ERC; self-improvement: Reflexion-style propose-approve;
  UI: 2026 streaming/feedback/skeleton patterns).
- v1.1 (2026-10-17, Phase 3): the planned `user_profile` table is realized as
  the pre-existing generic `profiles` document table (name/data) with
  `get_profile`/`set_profile` helpers; learned style lives under the document
  key `style`, user edits under `style_overrides` so learning never clobbers
  an override.
