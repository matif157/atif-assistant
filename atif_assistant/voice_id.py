"""Offline speaker identification from short voice samples.

Uses sherpa-onnx speaker-embedding models (CAM++ / WeSpeaker). Entirely
optional: if sherpa-onnx or the model is missing the app keeps working and this
module simply reports itself unavailable. Identification is always a labelled
guess with a confidence - it never changes memory on its own.

The module is deliberately API-only at the edges: it returns plain floats and
dicts and never touches the database, so it stays easy to test in isolation.
"""

from __future__ import annotations

import io
import os
import threading
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


def _get_extractor():
    """Build (and cache) the sherpa-onnx embedding extractor, or None."""
    global _extractor, _extractor_model
    name = model_name()
    if _extractor is not None and _extractor_model == name:
        return _extractor
    path = model_path()
    if not path.exists():
        return None
    try:
        import sherpa_onnx
    except Exception:  # noqa: BLE001 - missing dependency is expected
        return None
    try:
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(path), num_threads=1, debug=False, provider="cpu"
        )
        if not config.validate():
            return None
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        if not extractor.is_ready:
            return None
    except Exception:  # noqa: BLE001 - a bad model should not crash the app
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
    """Fetch a speaker-embedding model into the shared model directory."""
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
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "reason": "downloaded file was empty"}
        tmp.replace(dest)
    except Exception as exc:  # noqa: BLE001
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "reason": str(exc)}
    return {"ok": True, "model": name, "path": str(dest), "bytes": dest.stat().st_size}


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
