# Running Atif Assistant offline on Android

Atif Assistant is a local-first web app (FastAPI + SQLite + a local front
end). The **Android APK** in [`mobile/android/`](../mobile/android/) runs the
whole stack on the phone: embedded Python, on-device speech recognition
(whisper.cpp) and an on-device reasoning model (llama.cpp), all without a
network.

## What "offline" means here

| Layer | Offline? | Notes |
|---|---|---|
| UI shell | yes | Served from the APK; no CDN, no fonts, no analytics. |
| Data (memory, evidence, uploads) | yes | SQLite + `files/` inside the app sandbox. |
| Speech in | yes | whisper.cpp + GGML small model, recorded and transcribed on-device. |
| Speech out | yes | Android system TTS through the JS bridge. |
| Reasoning | yes, with the bundled model | llama.cpp + Qwen2.5-1.5B (downloaded once from Settings or the first-run screen). Without it the app answers with the labelled offline fallback. |

## The APK (recommended path)

Build once with the toolchain in [`mobile/android/README.md`](../mobile/android/README.md),
then install the debug APK (sideload, or `adb install`). On first launch the
app offers a setup screen: download the speech model (466 MB) and the
reasoning model (1.1 GB). Both fetches happen once, resume after a dropped
connection, and never leave the device.

Everything is local afterwards: the mic records at 16 kHz, whisper
transcribes it, the pipeline routes the question, Qwen answers, and the
reply is spoken with the system voice. Cloud providers (Groq, Gemini,
OpenRouter) still work when a network and a key exist, but nothing needs
them.

Two Android platform facts shaped the design:

- **W^X**: since Android 10 the app cannot `execve()` files in its own
  writable data dir. The native binaries (`llama-server`, `whisper-cli`)
  ship as JNI libs so the installer extracts them to `nativeLibraryDir`,
  which is executable.
- **WebView has no Web Speech API**, so voice goes through a small
  `window.AndroidVoice` bridge to the native engines.

## Other options

### Termux

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

A local model still needs Ollama (`ollama serve &`, `ollama pull llama3.2`)
and `ATIF_ASSISTANT_OLLAMA_URL=http://127.0.0.1:11434`.

### Server on a computer, phone as the client

Run `./run.sh` on a computer on the same network (or Tailscale) and open the
address on the phone. The PWA installs to the home screen; reasoning uses
whatever provider the computer has.

## Packaging a zip by hand

```sh
./scripts/package_offline.sh   # -> dist/atif-assistant-offline-<date>.zip
```

The zip excludes `data/`, `.venv/` and `.git/`, so it contains no private
memory. The recipient unpacks it and runs `./run.sh`.
