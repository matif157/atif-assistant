# Phase 3 - Detailed Tasks (one-by-one)

1. API CRUD for facts/episodes/rules/learned (core) — DONE
2. UI CRUD for MEM/INSIGHTS/LEDGER/RULES/UPLOAD nav — DONE
3. Sidebar shows basis: facts/mem/rules used per reply — DONE
4. CALL integration polish — DONE (session bug root-caused and fixed,
   call now shows the failure reason instead of looping forever)
5. SETTINGS full CRUD where applicable — DONE (full audit: every control
   wired; RESET added as the missing delete verb, keeps API keys;
   MODEL PIPELINE diagnostics panel added)
6. Upload auto-classification — DONE (propose-then-approve: directives
   become unapproved rules, durable facts become LEARNED candidates;
   idempotent on re-upload)
7. Verification + tests + commit — DONE (429 tests green, live smoke on
   the running server: pipeline 9/9, ask with session, TTS wav, STT
   espeak→whisper round trip, upload classification)

Do each fully, verify, commit+push.
