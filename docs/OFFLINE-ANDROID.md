# Running Atif Assistant offline on Android

Atif Assistant is a local-first web app (FastAPI + SQLite + a PWA front end).
There is **no signed APK** yet: building one needs the Android SDK, Java,
Gradle and an internet connection to fetch dependencies, none of which are
available on the build machine. This document gives the honest, working paths
instead.

## What "offline" means here

| Layer | Offline? | Notes |
|---|---|---|
| UI shell (PWA) | yes | `web/sw.js` caches the shell; `/api/*` is never cached. |
| Data (memory, evidence, uploads) | yes | SQLite + `data/uploads/` on the device. |
| Reasoning | only with a local model | Needs Ollama (or a compatible local endpoint). Without it the app answers with the labelled offline fallback. |

## Option A — Termux (fully offline on the phone)

1. Install [Termux](https://f-droid.org/packages/com.termux/) from F-Droid.
2. In Termux:
   ```sh
   pkg update && pkg install -y python git
   git clone https://github.com/matif157/atif-assistant.git
   cd atif-assistant
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.lock   # needs internet once
   ./run.sh
   ```
3. Open `http://127.0.0.1:8770` in Chrome and choose **Add to Home screen**.
   After the first load the shell opens offline; the local server keeps the
   data on the device.

### Local model (no cloud, no key)

```sh
# in another Termux session
pkg install -y ollama
ollama serve &
ollama pull llama3.2
export ATIF_ASSISTANT_OLLAMA_URL=http://127.0.0.1:11434
export ATIF_ASSISTANT_OLLAMA_MODEL=llama3.2
```
Ollama on a phone is heavy; a small model (e.g. `llama3.2:1b`) is realistic.

## Option B — server on a computer, phone as the client

Run `./run.sh` on a computer on the same network (or Tailscale) and open the
address on the phone. The PWA installs to the home screen; reasoning uses
whatever provider/Ollama the computer has.

## Option C — build the offline APK (Chaquopy)

A ready-to-build Android project lives in [`mobile/android/`](../mobile/android/).
It embeds Python 3.12 with Chaquopy, runs the server on `127.0.0.1:8770`, and
hosts the web UI in a `WebView`, so the app works with no network. Build it:

```sh
cd mobile/android
./build_apk.sh          # -> app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Voice in the app uses the native Android TTS/recognizer through a JS bridge,
because WebView does not implement the Web Speech API. The one build risk is
`pydantic-core` (a native extension); see `mobile/android/README.md`.

## Packaging a zip by hand

```sh
./scripts/package_offline.sh   # -> dist/atif-assistant-offline-<date>.zip
```

The zip excludes `data/`, `.venv/` and `.git/`, so it contains no private
memory. The recipient unpacks it and runs `./run.sh`.
