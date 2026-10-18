"""Offline speaker identification from short voice samples.

Uses sherpa-onnx speaker-embedding models (CAM++ / WeSpeaker). Two engine
paths: the ``sherpa-onnx`` Python package (desktop), or - when the package is
absent - the official prebuilt C library shipped inside the Android APK,
bound with ctypes (the package has no Android wheel for the app's Python).
Entirely optional: if neither engine or the model is missing the app keeps
working and this module simply reports itself unavailable. Identification is
always a labelled guess with a confidence - it never changes memory on its
own.

The module is deliberately API-only at the edges: it returns plain floats and
dicts and never touches the database, so it stays easy to test in isolation.
"""

from __future__ import annotations

import ctypes
import io
import os
import threading
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any, Iterable

DEFAULT_MODEL = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_BASE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
)
MODEL_URLS = {
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx": MODEL_BASE_URL
    + "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx": MODEL_BASE_URL
    + "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
}
DEFAULT_THRESHOLD = 0.5
SAMPLE_RATE = 16000

_lock = threading.Lock()
_extractor = None
_extractor_model: str | None = None


def model_dir() -> Path:
    """Shared model directory (same one the Whisper models live in)."""
    from . import stt

    return stt.model_dir()


def model_name() -> str:
    return os.environ.get("ATIF_ASSISTANT_VOICE_MODEL", DEFAULT_MODEL)


def model_path() -> Path:
    return model_dir() / model_name()


def threshold() -> float:
    try:
        return float(os.environ.get("ATIF_ASSISTANT_VOICE_THRESHOLD", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


# ---------------------------------------------------------------- native engine
# The phone cannot pip-install sherpa-onnx: its Android wheels only target
# Python 3.14 while the app builds against 3.12, and Chaquopy refuses native
# source builds by design. Instead the APK stages the official prebuilt C
# library (jniLibs, staged by build_native.sh) and this path binds it with
# ctypes - the same pattern as the on-device whisper-cli binary.
# ATIF_ASSISTANT_SHERPA_LIBS is exported by run_server from the JNI library
# directory when the two shared objects are present.

_NATIVE_ENV = "ATIF_ASSISTANT_SHERPA_LIBS"
_native_cache: dict[str, Any] = {}


class _NativeConfig(ctypes.Structure):
    """Mirror of SherpaOnnxSpeakerEmbeddingExtractorConfig (c-api.h)."""

    _fields_ = [
        ("model", ctypes.c_char_p),
        ("num_threads", ctypes.c_int32),
        ("debug", ctypes.c_int32),
        ("provider", ctypes.c_char_p),
    ]


def _has_python_package() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("sherpa_onnx") is not None
    except Exception:  # noqa: BLE001 - absent package is a normal state
        return False


def _native_lib() -> Any:
    """Load (once per directory) the prebuilt C library, or None."""
    lib_dir = os.environ.get(_NATIVE_ENV, "")
    if not lib_dir:
        return None
    if lib_dir in _native_cache:
        return _native_cache[lib_dir]
    lib = None
    try:
        # Preload the dependencies by absolute path so the Android linker
        # resolves the C API's DT_NEEDED entries from the same directory.
        for name in ("libc++_shared.so", "libonnxruntime.so"):
            try:
                ctypes.CDLL(
                    os.path.join(lib_dir, name), mode=ctypes.RTLD_GLOBAL
                )
            except OSError:
                pass
        lib = ctypes.CDLL(os.path.join(lib_dir, "libsherpa-onnx-c-api.so"))
        _declare_native_api(lib)
    except Exception:  # noqa: BLE001 - engine absent = engine unavailable
        lib = None
    _native_cache[lib_dir] = lib
    return lib


def _declare_native_api(lib: Any) -> None:
    """Attach argtypes/restypes once (a mis-typed pointer here can crash)."""
    void_p = ctypes.c_void_p
    create = lib.SherpaOnnxCreateSpeakerEmbeddingExtractor
    create.argtypes = [ctypes.POINTER(_NativeConfig)]
    create.restype = void_p
    destroy = lib.SherpaOnnxDestroySpeakerEmbeddingExtractor
    destroy.argtypes = [void_p]
    destroy.restype = None
    dim = lib.SherpaOnnxSpeakerEmbeddingExtractorDim
    dim.argtypes = [void_p]
    dim.restype = ctypes.c_int32
    create_stream = lib.SherpaOnnxSpeakerEmbeddingExtractorCreateStream
    create_stream.argtypes = [void_p]
    create_stream.restype = void_p
    is_ready = lib.SherpaOnnxSpeakerEmbeddingExtractorIsReady
    is_ready.argtypes = [void_p, void_p]
    is_ready.restype = ctypes.c_int32
    compute = lib.SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding
    compute.argtypes = [void_p, void_p]
    compute.restype = ctypes.POINTER(ctypes.c_float)
    free_vec = lib.SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding
    free_vec.argtypes = [ctypes.POINTER(ctypes.c_float)]
    free_vec.restype = None
    accept = lib.SherpaOnnxOnlineStreamAcceptWaveform
    accept.argtypes = [void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_float), ctypes.c_int32]
    accept.restype = None
    finish = lib.SherpaOnnxOnlineStreamInputFinished
    finish.argtypes = [void_p]
    finish.restype = None
    free_stream = lib.SherpaOnnxDestroyOnlineStream
    free_stream.argtypes = [void_p]
    free_stream.restype = None


class _NativeStream:
    """Duck-typed twin of sherpa_onnx.SpeakerEmbeddingExtractorStream."""

    def __init__(self, lib: Any, handle: int) -> None:
        self._lib = lib
        self._h = handle

    def accept_waveform(self, sample_rate: int, samples: Any) -> None:
        # samples is a float32 numpy array (voice_id.embed guarantees it).
        n = len(samples)
        if n == 0:
            return
        ptr = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._lib.SherpaOnnxOnlineStreamAcceptWaveform(
            self._h, int(sample_rate), ptr, int(n)
        )

    def input_finished(self) -> None:
        self._lib.SherpaOnnxOnlineStreamInputFinished(self._h)

    def __del__(self) -> None:  # noqa: D105 - refcount frees the handle
        try:
            self._lib.SherpaOnnxDestroyOnlineStream(self._h)
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass


class _NativeExtractor:
    """Duck-typed twin of sherpa_onnx.SpeakerEmbeddingExtractor (ctypes)."""

    def __init__(self, lib: Any, handle: int) -> None:
        self._lib = lib
        self._h = handle

    @property
    def dim(self) -> int:
        return int(self._lib.SherpaOnnxSpeakerEmbeddingExtractorDim(self._h))

    def create_stream(self) -> _NativeStream:
        handle = self._lib.SherpaOnnxSpeakerEmbeddingExtractorCreateStream(self._h)
        if not handle:
            raise RuntimeError("sherpa native: could not create stream")
        return _NativeStream(self._lib, handle)

    def compute(self, stream: _NativeStream) -> list[float]:
        if not self._lib.SherpaOnnxSpeakerEmbeddingExtractorIsReady(
            self._h, stream._h
        ):
            return []
        vec = self._lib.SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding(
            self._h, stream._h
        )
        if not vec:
            return []
        dim = int(self._lib.SherpaOnnxSpeakerEmbeddingExtractorDim(self._h))
        buf = ctypes.cast(vec, ctypes.POINTER(ctypes.c_float * dim)).contents
        out = [float(x) for x in buf]
        self._lib.SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding(vec)
        return out


def _native_extractor(path: Path) -> Any:
    """Build the ctypes-backed extractor for a model file, or None."""
    lib = _native_lib()
    if lib is None:
        return None
    try:
        cfg = _NativeConfig(
            model=str(path).encode("utf-8"),
            num_threads=1,
            debug=0,
            provider=b"cpu",
        )
        handle = lib.SherpaOnnxCreateSpeakerEmbeddingExtractor(ctypes.byref(cfg))
        if not handle:
            return None
        if lib.SherpaOnnxSpeakerEmbeddingExtractorDim(handle) <= 0:
            lib.SherpaOnnxDestroySpeakerEmbeddingExtractor(handle)
            return None
        return _NativeExtractor(lib, handle)
    except Exception:  # noqa: BLE001 - a bad model must not crash the app
        return None


def _get_extractor():
    """Build (and cache) the embedding extractor, or None.

    The sherpa-onnx Python package wins when importable (desktop); otherwise
    the prebuilt C library from the APK provides the same interface via
    ctypes. Missing package AND missing native libs = no engine.
    """
    global _extractor, _extractor_model
    name = model_name()
    if _extractor is not None and _extractor_model == name:
        return _extractor
    path = model_path()
    if not path.exists():
        return None
    extractor = None
    sherpa_onnx = None
    try:
        import sherpa_onnx as _sherpa_onnx

        sherpa_onnx = _sherpa_onnx
    except Exception:  # noqa: BLE001 - missing dependency is expected
        sherpa_onnx = None
    if sherpa_onnx is not None:
        try:
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(path), num_threads=1, debug=False, provider="cpu"
            )
            if config.validate():
                built = sherpa_onnx.SpeakerEmbeddingExtractor(config)
                if built.is_ready:
                    extractor = built
        except Exception:  # noqa: BLE001 - a bad model should not crash the app
            extractor = None
    if extractor is None:
        extractor = _native_extractor(path)
    if extractor is None:
        return None
    _extractor = extractor
    _extractor_model = name
    return extractor


def available() -> bool:
    return _get_extractor() is not None


def status() -> dict[str, Any]:
    """Small, JSON-friendly description of the engine for /api/health."""
    path = model_path()
    extractor = _get_extractor()
    info: dict[str, Any] = {
        "available": extractor is not None,
        "model": model_name(),
        "model_present": path.exists(),
        # Lets the UI split "model not downloaded" from "engine not shipped"
        # instead of one misleading catch-all message.
        "package": _has_python_package(),
        "native": _native_lib() is not None,
        "model_dir": str(model_dir()),
        "models": sorted(MODEL_URLS),
        "threshold": threshold(),
    }
    if extractor is not None:
        try:
            info["dim"] = int(extractor.dim)
        except Exception:  # noqa: BLE001
            pass
    return info


def download_model(name: str | None = None) -> dict[str, Any]:
    """Fetch a speaker-embedding model into the shared model directory.

    Same rule as the LLM and whisper downloaders: the .part file is never
    deleted on failure, so a retry resumes with a Range request instead of
    starting over.
    """
    name = name or DEFAULT_MODEL
    if name not in MODEL_URLS:
        return {"ok": False, "reason": f"unknown model {name!r}"}
    dest = model_dir() / name
    if dest.exists() and dest.stat().st_size > 0:
        return {"ok": True, "model": name, "path": str(dest), "bytes": dest.stat().st_size}
    url = MODEL_URLS[name]
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    last_reason = "download failed"
    for attempt in range(4):
        try:
            have = tmp.stat().st_size if tmp.is_file() else 0
            headers = {"User-Agent": "atif-assistant"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                resuming = have > 0 and getattr(resp, "status", 200) == 206
                clen = int(resp.headers.get("Content-Length") or 0)
                if have and not resuming:
                    have = 0  # server ignored Range: restart clean
                total = clen + (have if resuming else 0)
                with open(tmp, "ab" if have else "wb") as fh:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
            got = tmp.stat().st_size if tmp.is_file() else 0
            if got == 0:
                return {"ok": False, "reason": "downloaded file was empty", "model": name}
            if total and got < total * 0.99:
                raise OSError(f"connection ended early ({got} of {total} bytes)")
            tmp.replace(dest)
            return {
                "ok": True,
                "model": name,
                "path": str(dest),
                "bytes": dest.stat().st_size,
            }
        except Exception as exc:  # noqa: BLE001 - keep the bytes, retry
            last_reason = str(exc)[:200] or type(exc).__name__
            if attempt < 3:
                time.sleep(1.5)
                continue
        break
    partial = tmp.stat().st_size if tmp.is_file() else 0
    reason = last_reason
    if partial:
        reason = f"{last_reason} - progress saved ({partial} bytes), retry to resume"
    return {"ok": False, "reason": reason, "model": name, "partial": partial}


def decode_wav(data: bytes) -> tuple[Any, int] | tuple[None, int]:
    """Decode a PCM-16 WAV clip into a float32 numpy array at its rate."""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return None, SAMPLE_RATE
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
    except Exception:  # noqa: BLE001
        return None, SAMPLE_RATE
    if width != 2 or not frames:
        return None, rate or SAMPLE_RATE
    samples = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate or SAMPLE_RATE


def _resample(samples, rate: int):
    if rate == SAMPLE_RATE:
        return samples
    import numpy as np

    if len(samples) == 0:
        return samples
    target = max(1, int(round(len(samples) * SAMPLE_RATE / rate)))
    src_idx = np.linspace(0, len(samples) - 1, num=len(samples))
    dst_idx = np.linspace(0, len(samples) - 1, num=target)
    return np.interp(dst_idx, src_idx, samples).astype("float32")


def embed(samples, rate: int = SAMPLE_RATE) -> list[float] | None:
    """Return a unit-length speaker embedding for a clip, or None."""
    extractor = _get_extractor()
    if extractor is None:
        return None
    import numpy as np

    samples = np.asarray(samples, dtype="float32").reshape(-1)
    if len(samples) < SAMPLE_RATE * 0.3:
        return None
    samples = _resample(samples, rate)
    try:
        with _lock:
            stream = extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            stream.input_finished()
            vec = list(extractor.compute(stream))
    except Exception:  # noqa: BLE001
        return None
    if not vec:
        return None
    return normalize([float(x) for x in vec])


def embed_wav(data: bytes) -> list[float] | None:
    samples, rate = decode_wav(data)
    if samples is None:
        return None
    return embed(samples, rate)


def normalize(vec: Iterable[float]) -> list[float]:
    vals = [float(x) for x in vec]
    norm = sum(v * v for v in vals) ** 0.5
    if norm <= 0:
        return vals
    return [v / norm for v in vals]


def identify(embedding: list[float] | None, prints: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best matching saved person for an embedding, with a confidence.

    Both sides are normalised, so the dot product is the cosine similarity. The
    result is labelled ``known`` only when it clears the threshold.
    """
    if not embedding or not prints:
        return None
    query = normalize(embedding)
    best: dict[str, Any] | None = None
    for person in prints:
        ref = person.get("embedding")
        if not ref or len(ref) != len(query):
            continue
        ref_n = normalize(ref)
        score = sum(a * b for a, b in zip(query, ref_n))
        if best is None or score > best["score"]:
            best = {
                "id": person.get("id"),
                "name": person.get("name"),
                "score": round(score, 4),
            }
    if best is None:
        return None
    best["known"] = best["score"] >= threshold()
    best["threshold"] = threshold()
    return best
