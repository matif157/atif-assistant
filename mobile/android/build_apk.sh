#!/usr/bin/env bash
# Build the fully-offline Atif Assistant APK.
#
# The APK embeds Python (via Chaquopy) and the whole atif_assistant package, so
# the server runs on the phone and no network is needed. This script:
#   1. makes sure a real JDK, the Android SDK and Gradle are available,
#   2. stages the Python package + web assets next to run_server.py,
#   3. builds a debug APK.
#
# Everything here is idempotent; re-running only does the missing steps.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"          # repo root (…/atif-assistant)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
BREW="$(command -v brew || echo /opt/homebrew/bin/brew)"

log() { printf '\n== %s\n' "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- 1. JDK
if ! (java -version 2>&1 | grep -q version); then
  log "Installing a JDK (Temurin 17) with Homebrew"
  "$BREW" install --cask temurin@17
  export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
fi

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

log "Accepting SDK licenses and installing platform/build-tools"
yes | sdkmanager --licenses >/dev/null 2>&1 || true
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" >/dev/null

# ------------------------------------------------------------- 3. Gradle
if ! need_cmd gradle; then
  if [ -x "$ANDROID_SDK_ROOT/gradle/bin/gradle" ]; then
    PATH="$ANDROID_SDK_ROOT/gradle/bin:$PATH"
  else
    log "Installing Gradle with Homebrew"
    "$BREW" install gradle
  fi
fi

# ------------------------------------------- 4. Stage Python + web assets
log "Staging atif_assistant and web/ into the app's python sources"
PYDEST="app/src/main/python"
rm -rf "$PYDEST/atif_assistant" "$PYDEST/web"
cp -R "$ROOT/atif_assistant" "$PYDEST/atif_assistant"
rm -rf "$PYDEST/atif_assistant/__pycache__"
cp -R "$ROOT/web" "$PYDEST/web"
printf 'ATIF_ASSISTANT_DATA_DIR is set at runtime to app files dir\n' > /dev/null

# ------------------------------------------------------------- 5. Build
log "Building debug APK"
gradle --no-daemon assembleDebug

APK="app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK" ]; then
  log "Done: $APK"
  echo "Install with:  adb install -r $APK"
else
  echo "Build finished but no APK found at $APK" >&2
  exit 1
fi
