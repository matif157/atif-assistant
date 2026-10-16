#!/usr/bin/env bash
# Build the fully-offline Atif Assistant APK.
#
# The APK embeds Python (via Chaquopy) and the whole atif_assistant package, so
# the server runs on the phone and no network is needed. This script:
#   1. makes sure a real JDK, the Android SDK and Gradle are available,
#   2. stages the Python package + web assets next to run_server.py,
#   3. builds a debug APK (default) or a signed, minified release APK
#      (--release; needs ../release.keystore + ../keystore.properties).
#
# Everything here is idempotent; re-running only does the missing steps.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"          # repo root (…/atif-assistant)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
BREW="$(command -v brew || echo /opt/homebrew/bin/brew)"
RELEASE=0
[ "${1:-}" = "--release" ] && RELEASE=1

log() { printf '\n== %s\n' "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- 1. JDK
# A Homebrew *formula* (openjdk), never a cask: cask .pkg installers need an
# interactive sudo, which breaks scripted/remote builds.
find_java_home() {
  [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ] && return 0
  JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null)" && [ -x "$JAVA_HOME/bin/java" ] && return 0
  for c in /opt/homebrew/opt/openjdk@17 /opt/homebrew/opt/openjdk; do
    if [ -x "$c/bin/java" ]; then JAVA_HOME="$c"; return 0; fi
  done
  return 1
}
if ! find_java_home; then
  log "Installing a JDK (OpenJDK 17) with Homebrew"
  HOMEBREW_NO_INSTALL_CLEANUP=1 "$BREW" install openjdk@17
  JAVA_HOME=/opt/homebrew/opt/openjdk@17
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"

# ---------------------------------------------------------- 2. Android SDK
if [ -z "$SDK" ] || [ ! -d "$SDK" ]; then
  if [ -d /opt/homebrew/share/android-commandlinetools ]; then
    SDK=/opt/homebrew/share/android-commandlinetools
  else
    log "Installing Android command-line tools with Homebrew"
    "$BREW" install --cask android-commandlinetools
    SDK=/opt/homebrew/share/android-commandlinetools
  fi
fi
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
export PATH="$SDK/platform-tools:$SDK/cmdline-tools/latest/bin:$PATH"

log "Accepting SDK licenses and installing platform/build-tools/NDK"
yes | sdkmanager --licenses >/dev/null 2>&1 || true
# NDK 26.1: what AGP 8.5 defaults to; also the toolchain llama.cpp/whisper
# will be cross-compiled with in M2/M3.
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" "ndk;26.1.10909125" >/dev/null

# ------------------------------------------------------------- 3. Gradle
# Build with the committed wrapper (pinned Gradle 8.7, what AGP 8.5.2
# expects) so the machine's own Gradle version can never break the build.
if [ ! -x ./gradlew ]; then
  echo "gradlew wrapper missing — run:  gradle wrapper --gradle-version 8.7" >&2
  exit 1
fi

# ------------------------------------------- 4. Stage Python + web assets
log "Staging atif_assistant and web/ into the app's python sources"
PYDEST="app/src/main/python"
rm -rf "$PYDEST/atif_assistant" "$PYDEST/web"
cp -R "$ROOT/atif_assistant" "$PYDEST/atif_assistant"
find "$PYDEST/atif_assistant" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp -R "$ROOT/web" "$PYDEST/web"

if [ ! -f app/src/main/jniLibs/arm64-v8a/libllama-server.so ]; then
  echo "NOTE: no llama-server staged (on-device model will be unavailable)." >&2
  echo "      Build it with:  ./build_native.sh" >&2
fi

# ------------------------------------------------------------- 5. Build
if [ "$RELEASE" = "1" ]; then
  if [ ! -f release.keystore ] || [ ! -f keystore.properties ]; then
    echo "Release build needs release.keystore + keystore.properties (gitignored)." >&2
    echo "Generate them once with keytool; see mobile/android/README.md." >&2
    exit 1
  fi
  log "Building signed release APK (arm64, minified)"
  ./gradlew --no-daemon assembleRelease
  APK="app/build/outputs/apk/release/app-release.apk"
else
  log "Building debug APK"
  ./gradlew --no-daemon assembleDebug
  APK="app/build/outputs/apk/debug/app-debug.apk"
fi

if [ -f "$APK" ]; then
  log "Done: $APK ($(du -h "$APK" | cut -f1))"
  echo "Install with:  adb install -r $APK"
else
  echo "Build finished but no APK found at $APK" >&2
  exit 1
fi
