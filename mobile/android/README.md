# Atif Assistant — Android (offline, embedded Python)

This Gradle project wraps the Atif Assistant server in a fully offline
Android app. [Chaquopy](https://chaquo.com/chaquopy/) embeds Python 3.12,
the server runs on loopback (`127.0.0.1:8770`), and a `WebView` loads the
normal web front end. whisper.cpp and llama.cpp run as native binaries
shipped inside the APK; both models are fetched once from the in-app setup
screen and then live in the app's private storage.

## Build

```sh
./build_apk.sh           # debug   -> app/build/outputs/apk/debug/app-debug.apk
./build_apk.sh --release # release -> app/build/outputs/apk/release/app-release.apk
adb install -r <apk>
```

The script installs a JDK (Homebrew `openjdk@17`, no sudo), the Android SDK
command-line tools and the NDK if missing, stages the Python package and the
`web/` assets, prunes nested `__pycache__`, and builds with the committed
Gradle wrapper (8.7 — newer Gradle breaks the pinned AGP).

### Release builds

The release variant is signed, minified (R8) and resource-shrunk, and ships
arm64 only (~22 MB vs 29 MB debug). Signing reads two gitignored files in
this directory; generate the keystore once:

```sh
keytool -genkeypair -keystore release.keystore -alias atif \
  -keyalg RSA -keysize 4096 -validity 10950 \
  -storepass <password> -keypass <password> \
  -dname "CN=Atif Assistant, O=matif157, C=PK"
# then write storeFile/storePassword/keyAlias/keyPassword into
# keystore.properties (see the comments inside the example values)
```

**Back up `release.keystore` + `keystore.properties`.** Android only accepts
an update if it is signed with the same key; losing the keystore means the
installed app can never be updated and must be uninstalled (wiping its data
and models). A debug-signed APK cannot replace a release install or vice
versa — same `applicationId`, different signature → `INSTALL_FAILED_...
UPDATE_INCOMPATIBLE`; uninstall first.

R8 keeps (`app/proguard-rules.pro`) protect the Chaquopy bridge, the
`@JavascriptInterface` methods and `MainActivity`; the full stack (llama
spawn, whisper exec, downloads, setup overlay) was re-verified on an arm64
emulator running the minified release.

Native binaries are built separately (long; needs the NDK):

```sh
./build_native.sh      # llama-server + whisper-cli -> app/src/main/jniLibs/<abi>/
```

Output is staged as `libllama-server.so` / `libwhisper-cli.so` (gitignored).
They are static executables wearing a `.so` name so Gradle packages them as
JNI libs.

## How it is wired

| Piece | Role |
|---|---|
| `app/src/main/python/run_server.py` | `start(files_dir, llama_bin, whisper_bin)` exports the env vars, then runs uvicorn with `ATIF_ASSISTANT_DATA_DIR` in the app's files dir. |
| `app/src/main/java/.../MainActivity.java` | Starts Python on a thread, waits for the port, hosts the WebView, exposes the voice bridge, records audio for whisper. |
| `atif_assistant/llm.py` | `llamacpp` provider: spawns `llama-server` (port 8765) with the downloaded GGUF, OpenAI-compatible API, resumable background download. |
| `atif_assistant/stt.py` | whisper.cpp transcriber; `ATIF_ASSISTANT_WHISPER_BIN` picks the on-device binary, `ATIF_ASSISTANT_MODEL_DIR` the model store. |
| `web/` + `atif_assistant/` | Staged into `app/src/main/python/` by `build_apk.sh` (gitignored). |

## Two Android platform facts

- **W^X (API 29+)**: the app cannot `execve()` files in its own writable
  data dir — the failure is `PermissionError: [Errno 13]` at spawn time,
  and it is invisible to `run-as` (which runs in a different SELinux
  domain and can exec the same file). Native binaries therefore ship as
  JNI libs; the installer extracts them to `nativeLibraryDir`, the
  one app-owned executable location, and `MainActivity` passes those paths
  to Python.
- **No Web Speech API in WebView**: voice goes through a
  `window.AndroidVoice` bridge (`speak`, `listen`, `stop`, `available`).
  `listen()` records 16 kHz mono PCM with an energy VAD, POSTs a WAV to
  `/api/stt`, and falls back to the platform recogniser only when the
  offline stack is missing.

## Models (downloaded once, in-app)

| Model | Size | Source | Used by |
|---|---|---|---|
| `qwen2.5-1.5b.gguf` | 1.1 GB | Hugging Face `Qwen/Qwen2.5-1.5B-Instruct-GGUF` | llama-server (reasoning) |
| `ggml-small.bin` | 466 MB | Hugging Face `ggerganov/whisper.cpp` | whisper-cli (speech) |

Meta's Llama 3.2 mirrors are license-gated (HTTP 401), which is why the
reasoning model is Qwen — the strongest ungated small instruct GGUF.
Both downloads resume with HTTP Range and validate the final size, so a
dropped connection never leaves a file that looks installed.

## Verifying on an emulator

```sh
sdkmanager "system-images;android-34;google_apis;arm64-v8a"
avdmanager create avd -n atif -k "system-images;android-34;google_apis;arm64-v8a"
emulator -avd atif -no-window -no-audio -no-boot-anim -no-snapshot \
    -gpu swiftshader_indirect -memory 4096 &
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb forward tcp:18770 tcp:8770
curl -s http://127.0.0.1:18770/api/llm
```

4 GB of emulator RAM is the floor: the 1.5B model needs ~1.6 GB at load and
the 2.5 GB image OOM-kills llama-server silently (empty log, dead process).
Use `run-as ai.atif.assistant` to inspect `files/` (models, logs) — the
plain `adb shell ls /data/data/...` is permission-denied, and `run-as` can
exec the data-dir copy of a binary even though the app itself cannot
(the W^X rule above).

## Toolchain notes

- JDK: Homebrew formula `openjdk@17` (casks that need a `.pkg` installer
  fail without sudo). `build_apk.sh` finds and exports it.
- SDK: cask `android-commandlinetools` (no sudo) at
  `/opt/homebrew/share/android-commandlinetools`; NDK `26.1.10909125`.
- Gradle: committed wrapper pinned to 8.7 (Homebrew's Gradle 9 breaks
  AGP 8.5.2). Generate/update with a one-off `gradle-8.7-bin.zip`.
- Chaquopy pip pins are exact and pydantic-first: `pydantic==1.10.26`
  (v1 line; 1.10.13 breaks on Python 3.12.4+, v2 needs a native
  extension Chaquopy cannot build), then FastAPI/uvicorn/httpx/pypdf.
  The full 429-test suite was proven green under exactly these pins
  before the first APK build.
- llama.cpp must be cloned under `.native/`, not `/tmp`: its UI asset
  CMake cannot resolve paths behind macOS's `/tmp -> /private/tmp`
  symlink.
