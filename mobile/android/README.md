# Atif Assistant — Android (offline, embedded Python)

This Gradle project wraps the existing Atif Assistant server in an Android app.
[Chaquopy](https://chaquo.com/chaquopy/) embeds Python 3.12, the server runs on
loopback (`127.0.0.1:8770`), and a `WebView` loads it. **No network is needed**
for the app to work; the model is whatever local Ollama/llama.cpp endpoint you
point `ATIF_ASSISTANT_OLLAMA_URL` at, or the labelled offline fallback.

## Build

```sh
./build_apk.sh
# -> app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The script installs the JDK, Android SDK command-line tools and Gradle if they
are missing (Homebrew), accepts SDK licences, stages the Python package and the
`web/` assets, then builds.

## How it is wired

| Piece | Role |
|---|---|
| `app/src/main/python/run_server.py` | Starts uvicorn with `ATIF_ASSISTANT_DATA_DIR` set to the app's files dir. |
| `app/src/main/java/.../MainActivity.java` | Starts Python on a thread, hosts the `WebView`, exposes the voice bridge. |
| `web/` + `atif_assistant/` | Staged into `app/src/main/python/` by `build_apk.sh` (gitignored). |
| `AndroidManifest.xml` | `INTERNET` (optional providers) + `RECORD_AUDIO`; cleartext only to loopback. |

## Voice

Android WebView does not implement the Web Speech API, so the Activity exposes a
`window.AndroidVoice` bridge (`speak`, `listen`). `web/app.js` feature-detects it
and falls back to the browser engines everywhere else, so the same front end
works in Chrome, Safari and the app.

## Known risk

`pydantic` v2 depends on `pydantic-core`, a native extension. If the Chaquopy
build cannot resolve it, the fallback is to pin `pydantic==1.10.*` and adjust the
model type hints, or to run the server without FastAPI on-device. This is the
one place the build is expected to need attention.
