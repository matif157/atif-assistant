# Atif Assistant - Evolution Summary
Date: 2026-10-14

## Completed
- Phases 1A-4 done; full CRUD API+UI; docs archived
- 429/0 tests passing, server healthy on :8770
- Offline STT (whisper.cpp), speaker ID (sherpa-onnx), Ollama (llama3.2:3b)
- CALL: session bug root-caused (accidental deletion in 5a4c7b2), fixed;
  call/hands-free show the failure reason instead of silent looping
- Settings: full CRUD audit + RESET (keeps API keys) + MODEL PIPELINE
  panel that runs every stage for real (memory, router, host, model
  reply, espeak→whisper round trip, TTS, speaker, provider chain)
- Uploads: readable files auto-propose rules (approved=0) and LEARNED
  candidates; propose-then-approve, idempotent on re-upload
- Model quality (Phase 4): llama3.2:3b default; a SOUND self-critique can
  no longer revise, knowledge questions skip the adversarial pass, braked
  revisions never replace the draft, bare "[UNKNOWN]" tokens are repaired,
  memory recall routes to ask, repeat-escalation only fires on the
  emotionally-loaded question classes
- Live smoke verified: pipeline 9/9, /api/ask with session, TTS, STT

## Known limits
- (none blocking) llama3.2:3b is now the default local model; the answer
  path no longer lets a SOUND self-critique or a braked revision replace
  a good draft, knowledge questions skip the adversarial pass, and bare
  "[UNKNOWN]" tokens are repaired instead of shipped.

## Next (candidate Phase 5 - pick one)
- Connectors (Gmail/Drive, read-only propose-approve)
- Task extraction (auto todos from chats/uploads)
- Polish/deploy (APK build, Urdu TTS quality)

System stable. Continue as needed.
