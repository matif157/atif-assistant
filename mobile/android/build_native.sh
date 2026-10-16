#!/usr/bin/env bash
# Build the native on-device binaries (llama-server, later whisper-cli) with
# the Android NDK. Output lands in app/src/main/jniLibs/<abi>/libllama-server.so
# so the installer extracts it to nativeLibraryDir - the only app-owned path
# Android allows execve() from (filesDir is W^X-blocked since API 29).
#
# The llama.cpp tree lives in .native/ (gitignored) because its CMake UI
# script cannot handle build paths behind macOS's /tmp -> /private/tmp
# symlink.
set -euo pipefail
cd "$(dirname "$0")"

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}}"
NDK="$SDK/ndk/26.1.10909125"
SRC=".native/llama.cpp"
ABI="${1:-arm64-v8a}"
OUT="app/src/main/jniLibs/$ABI"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"

log() { printf '\n== %s\n' "$*"; }

[ -f "$NDK/build/cmake/android.toolchain.cmake" ] || {
  echo "NDK not found at $NDK — run build_apk.sh once first" >&2
  exit 1
}

# ---------------------------------------------------------------- llama.cpp
if [ ! -d "$SRC" ]; then
  log "Cloning llama.cpp (shallow)"
  mkdir -p .native
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$SRC"
fi

log "Building llama-server for $ABI"
# Flags follow docs/android.md + the Android CI workflow: no OpenMP (needs
# libomp outside the NDK stable API set), no llamafile/openssl/curl, no
# host-native CPU flags. GGML_CPU_ARM_ARCH targets armv8.2 CPUs with dotprod
# and fp16 (2017+ big cores, every phone that can run a 1B model).
cmake -S "$SRC" -B "$SRC/build-$ABI" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI="$ABI" \
  -DANDROID_PLATFORM=android-24 \
  -DANDROID_STL=c++_static \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DGGML_LLAMAFILE=OFF \
  -DLLAMA_OPENSSL=OFF \
  -DLLAMA_CURL=OFF \
  -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 \
  -DGGML_CCACHE=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_BUILD_TOOLS=ON \
  -DLLAMA_BUILD_UI=OFF
cmake --build "$SRC/build-$ABI" --target llama-server -j "$JOBS"

log "Staging into $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"
# The lib prefix / .so suffix is what lets Gradle package it as a JNI lib;
# the file itself is a static executable, not a shared object.
cp "$SRC/build-$ABI/bin/llama-server" "$OUT/libllama-server.so"
# Present only when backends build as shared modules; harmless otherwise.
find "$SRC/build-$ABI/bin" -name "libggml-*.so" -exec cp {} "$OUT/" \; 2>/dev/null || true
STRIP="$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip"
if [ -f "$STRIP" ]; then
  for f in "$OUT"/*; do "$STRIP" "$f" 2>/dev/null || true; done
fi
ls -lh "$OUT"
log "Done: llama-server staged for $ABI"

# --------------------------------------------------------------- whisper.cpp
WSRC=".native/whisper.cpp"
if [ ! -d "$WSRC" ]; then
  log "Cloning whisper.cpp (shallow)"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WSRC"
fi

log "Building whisper-cli for $ABI"
cmake -S "$WSRC" -B "$WSRC/build-$ABI" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI="$ABI" \
  -DANDROID_PLATFORM=android-24 \
  -DANDROID_STL=c++_static \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DGGML_CCACHE=OFF \
  -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 \
  -DWHISPER_SDL2=OFF \
  -DBUILD_SHARED_LIBS=OFF
cmake --build "$WSRC/build-$ABI" --target whisper-cli -j "$JOBS"

log "Staging whisper-cli into $OUT"
cp "$WSRC/build-$ABI/bin/whisper-cli" "$OUT/libwhisper-cli.so"
if [ -f "$STRIP" ]; then
  "$STRIP" "$OUT/libwhisper-cli.so" 2>/dev/null || true
fi
ls -lh "$OUT"
log "Done: whisper-cli staged for $ABI"
