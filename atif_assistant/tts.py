"""Server-side text to speech for voices the browser does not have.

Most systems ship no Urdu voice, so the Web Speech API reads Urdu replies with
an English voice and the result is unintelligible. When a Gemini key is
configured this module synthesizes the reply on the server instead and returns
a WAV clip the browser can play. It fails soft: with no key or no quota the
caller gets `None` plus a reason, and the browser falls back to its own voices.

Between the cloud voice and espeak sits the offline neural voice ("voice
pack"): piper models for Urdu and English, fetched once (~88 MB) and run by
sherpa-onnx - the Python package on a desktop, the prebuilt C API staged into
the APK on a phone. That is what makes spoken replies sound human with no
network and no key.
"""

from __future__ import annotations

import array
import base64
import ctypes
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import llm
from .config import DATA_DIR
from .stt import find_bin

DEFAULT_MODEL = os.environ.get(
    "ATIF_ASSISTANT_TTS_MODEL", "gemini-2.5-flash-preview-tts"
)
DEFAULT_VOICE = os.environ.get("ATIF_ASSISTANT_TTS_VOICE", "Kore")
MAX_CHARS = 3000

# Offline fallback voice. espeak-ng ships an Urdu voice, which macOS lacks, so
# this is what makes spoken Urdu work with no network and no Gemini key.
ESPEAK = os.environ.get("ATIF_ASSISTANT_ESPEAK_BIN") or find_bin("espeak-ng")
_ESPEAK_VOICE = {"ur": "ur", "en": "en"}
_ESPEAK_RATE = os.environ.get("ATIF_ASSISTANT_ESPEAK_RATE", "150")

# Labels and markdown markers should not be read aloud.
_LABELS = re.compile(
    r"\[(FACT|INFERENCE|ASSUMPTION|UNKNOWN|PREDICTION)\]", re.IGNORECASE
)
_MARKUP = re.compile(r"[*_#>`]+")
_SPACE = re.compile(r"\s+")


def _clean(text: str) -> str:
    t = _LABELS.sub("", text or "")
    t = _MARKUP.sub(" ", t)
    return _SPACE.sub(" ", t).strip()


def _wav(pcm: bytes, rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw little-endian PCM in a WAV container the browser can play."""
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def server_available() -> bool:
    return bool(llm.provider_key("gemini")) and llm.provider_enabled("gemini")


def offline_available() -> bool:
    return bool(ESPEAK)


def available() -> bool:
    return server_available() or offline_available()


def status() -> dict[str, Any]:
    """Which speech engines are ready, for the settings screen."""
    return {
        "available": available(),
        "server": server_available(),
        "offline": offline_available(),
        "espeak": ESPEAK,
        "model": DEFAULT_MODEL if server_available() else None,
        # The offline neural voice: its engine (python package or the
        # staged C API), whether the pack is downloaded, and progress.
        "engine": _tts_engine_kind(),
        "voice_model": voice_model_present(),
        "voice_pack_bytes": TTS_PACK_BYTES,
        "download": tts_download_status(),
    }


def _via_gemini(clean: str) -> dict[str, Any]:
    key = llm.provider_key("gemini")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{DEFAULT_MODEL}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": clean}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": DEFAULT_VOICE}
                }
            },
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=120) as client:
            resp = None
            for attempt in range(3):
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code in (429, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {
            "audio": None,
            "reason": f"speech request failed: HTTP {exc.response.status_code}",
        }
    except Exception as exc:  # noqa: BLE001 - best effort, never break the reply
        return {"audio": None, "reason": f"speech request failed: {type(exc).__name__}"}

    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get(
        "parts"
    ) or []
    inline = None
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            break
    if not inline or not inline.get("data"):
        return {"audio": None, "reason": "the speech model returned no audio"}

    try:
        pcm = base64.b64decode(inline["data"])
    except Exception:  # noqa: BLE001
        return {"audio": None, "reason": "the speech model returned bad audio"}

    rate = 24000
    mime = inline.get("mimeType") or inline.get("mime_type") or ""
    match = re.search(r"rate=(\d+)", mime)
    if match:
        rate = int(match.group(1))
    return {"audio": _wav(pcm, rate=rate), "reason": None, "model": DEFAULT_MODEL}


def _via_espeak(clean: str, lang: str) -> dict[str, Any]:
    voice = _ESPEAK_VOICE.get((lang or "en").split("-")[0].lower(), "en")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "say.wav")
        try:
            subprocess.run(
                [ESPEAK, "-v", voice, "-s", str(_ESPEAK_RATE), "-w", out, clean],
                capture_output=True,
                timeout=60,
                check=True,
            )
            with open(out, "rb") as fh:
                return {"audio": fh.read(), "reason": None, "model": f"espeak-ng/{voice}"}
        except Exception as exc:  # noqa: BLE001
            return {
                "audio": None,
                "reason": f"offline speech failed: {type(exc).__name__}",
            }


def synthesize(text: str, lang: str = "en") -> dict[str, Any]:
    """Return {"audio": <wav bytes|None>, "reason": <str|None>, "model": ...}.

    Order: the natural server voice when Gemini is on and reachable, then the
    downloaded offline neural voice, then the espeak-ng fallback (which has
    Urdu) - so spoken replies work with no network and no key.
    """
    clean = _clean(text)[:MAX_CHARS]
    if not clean:
        return {"audio": None, "reason": "nothing to say"}

    reason = None
    if llm.provider_enabled("gemini") and llm.provider_key("gemini"):
        result = _via_gemini(clean)
        if result.get("audio"):
            return result
        reason = result.get("reason")
    elif not llm.provider_enabled("gemini"):
        reason = "server speech (Gemini) is turned off"
    else:
        reason = "server speech needs a Gemini key"

    voice = _via_sherpa(clean, lang)
    if voice.get("audio"):
        return voice

    if offline_available():
        result = _via_espeak(clean, lang)
        if result.get("audio"):
            return result
        reason = reason or voice.get("reason") or result.get("reason")
    else:
        reason = reason or voice.get("reason")
    return {"audio": None, "reason": reason or "speech unavailable"}


# ---------------------------------------------------------------------
# Offline neural voice ("voice pack"): two piper models from the official
# sherpa-onnx release - Urdu (ur_PK-fasih-medium) and English
# (en_US-amy-low-int8) - each self-contained with its espeak phoneme data.
# ~88 MB downloaded once; after that every reply can be spoken offline with
# a human voice. The engine is the sherpa Python package where it exists
# (desktop), or the prebuilt C API staged into the APK (phone).
TTS_DIR = DATA_DIR / "models" / "tts"
_TTS_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
TTS_ARCHIVES = (
    ("vits-piper-ur_PK-fasih-medium.tar.bz2", 67_227_718, "ur"),
    ("vits-piper-en_US-amy-low-int8.tar.bz2", 21_099_246, "en"),
)
TTS_PACK_BYTES = sum(size for _, size, _ in TTS_ARCHIVES)
# language -> (extracted directory, onnx file inside it)
_TTS_VOICE = {
    "ur": ("vits-piper-ur_PK-fasih-medium", "ur_PK-fasih-medium.onnx"),
    "en": ("vits-piper-en_US-amy-low-int8", "en_US-amy-low.onnx"),
}


def voice_files(lang: str) -> dict[str, Path] | None:
    """Installed voice for this language, as paths - or None when absent."""
    base = (lang or "en").split("-")[0].split("_")[0].lower()
    entry = _TTS_VOICE.get(base)
    if entry is None:
        return None
    d = TTS_DIR / entry[0]
    onnx = d / entry[1]
    tokens = d / "tokens.txt"
    data = d / "espeak-ng-data"
    if onnx.is_file() and tokens.is_file() and data.is_dir():
        return {"dir": d, "onnx": onnx, "tokens": tokens, "data_dir": data}
    return None


def voice_model_present() -> bool:
    """True when the whole pack (Urdu + English voices) is unpacked."""
    return all(voice_files(code) is not None for code in _TTS_VOICE)


# Loaded engines, keyed by voice directory: the first reply pays the ~1s
# model load, every later one reuses it.
_TTS_CACHE: dict[str, Any] = {}


def _build_python_engine(v: dict[str, Path]) -> tuple[Any, str] | None:
    try:
        import sherpa_onnx
    except Exception:  # noqa: BLE001 - package simply absent (phone builds)
        return None
    try:
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(v["onnx"]),
                    tokens=str(v["tokens"]),
                    data_dir=str(v["data_dir"]),
                ),
                num_threads=1,
                provider="cpu",
            ),
        )
        return (sherpa_onnx.OfflineTts(cfg), "python")
    except Exception:  # noqa: BLE001 - fall through to the native/other path
        return None


# ---- the prebuilt C API (staged into the APK by build_native.sh) ----
# Struct layouts must match c-api.h exactly; every unused model family is
# declared so the nested offsets of SherpaOnnxOfflineTtsModelConfig line up.
class _NVitsModelConfig(ctypes.Structure):
    _fields_ = [
        ("model", ctypes.c_char_p),
        ("lexicon", ctypes.c_char_p),
        ("tokens", ctypes.c_char_p),
        ("data_dir", ctypes.c_char_p),
        ("noise_scale", ctypes.c_float),
        ("noise_scale_w", ctypes.c_float),
        ("length_scale", ctypes.c_float),
        ("dict_dir", ctypes.c_char_p),
    ]


class _NMatchaModelConfig(ctypes.Structure):
    _fields_ = [
        ("acoustic_model", ctypes.c_char_p),
        ("vocoder", ctypes.c_char_p),
        ("lexicon", ctypes.c_char_p),
        ("tokens", ctypes.c_char_p),
        ("data_dir", ctypes.c_char_p),
        ("noise_scale", ctypes.c_float),
        ("length_scale", ctypes.c_float),
        ("dict_dir", ctypes.c_char_p),
    ]


class _NKokoroModelConfig(ctypes.Structure):
    _fields_ = [
        ("model", ctypes.c_char_p),
        ("voices", ctypes.c_char_p),
        ("tokens", ctypes.c_char_p),
        ("data_dir", ctypes.c_char_p),
        ("length_scale", ctypes.c_float),
        ("dict_dir", ctypes.c_char_p),
        ("lexicon", ctypes.c_char_p),
        ("lang", ctypes.c_char_p),
    ]


class _NKittenModelConfig(ctypes.Structure):
    _fields_ = [
        ("model", ctypes.c_char_p),
        ("voices", ctypes.c_char_p),
        ("tokens", ctypes.c_char_p),
        ("data_dir", ctypes.c_char_p),
        ("length_scale", ctypes.c_float),
    ]


class _NZipvoiceModelConfig(ctypes.Structure):
    _fields_ = [
        ("tokens", ctypes.c_char_p),
        ("encoder", ctypes.c_char_p),
        ("decoder", ctypes.c_char_p),
        ("vocoder", ctypes.c_char_p),
        ("data_dir", ctypes.c_char_p),
        ("lexicon", ctypes.c_char_p),
        ("feat_scale", ctypes.c_float),
        ("t_shift", ctypes.c_float),
        ("target_rms", ctypes.c_float),
        ("guidance_scale", ctypes.c_float),
    ]


class _NPocketModelConfig(ctypes.Structure):
    _fields_ = [
        ("lm_flow", ctypes.c_char_p),
        ("lm_main", ctypes.c_char_p),
        ("encoder", ctypes.c_char_p),
        ("decoder", ctypes.c_char_p),
        ("text_conditioner", ctypes.c_char_p),
        ("vocab_json", ctypes.c_char_p),
        ("token_scores_json", ctypes.c_char_p),
        ("voice_embedding_cache_capacity", ctypes.c_int32),
    ]


class _NSupertonicModelConfig(ctypes.Structure):
    _fields_ = [
        ("duration_predictor", ctypes.c_char_p),
        ("text_encoder", ctypes.c_char_p),
        ("vector_estimator", ctypes.c_char_p),
        ("vocoder", ctypes.c_char_p),
        ("tts_json", ctypes.c_char_p),
        ("unicode_indexer", ctypes.c_char_p),
        ("voice_style", ctypes.c_char_p),
    ]


class _NOfflineTtsModelConfig(ctypes.Structure):
    _fields_ = [
        ("vits", _NVitsModelConfig),
        ("num_threads", ctypes.c_int32),
        ("debug", ctypes.c_int32),
        ("provider", ctypes.c_char_p),
        ("matcha", _NMatchaModelConfig),
        ("kokoro", _NKokoroModelConfig),
        ("kitten", _NKittenModelConfig),
        ("zipvoice", _NZipvoiceModelConfig),
        ("pocket", _NPocketModelConfig),
        ("supertonic", _NSupertonicModelConfig),
    ]


class _NOfflineTtsConfig(ctypes.Structure):
    _fields_ = [
        ("model", _NOfflineTtsModelConfig),
        ("rule_fsts", ctypes.c_char_p),
        ("max_num_sentences", ctypes.c_int32),
        ("rule_fars", ctypes.c_char_p),
        ("silence_scale", ctypes.c_float),
    ]


class _NGeneratedAudio(ctypes.Structure):
    _fields_ = [
        ("samples", ctypes.POINTER(ctypes.c_float)),
        ("n", ctypes.c_int32),
        ("sample_rate", ctypes.c_int32),
    ]


def _declare_native_tts(lib: Any) -> None:
    """Bind the four TTS entry points once, exactly as c-api.h declares them."""
    if getattr(lib, "_atif_tts_api", False):
        return
    lib.SherpaOnnxCreateOfflineTts.argtypes = [ctypes.POINTER(_NOfflineTtsConfig)]
    lib.SherpaOnnxCreateOfflineTts.restype = ctypes.c_void_p
    lib.SherpaOnnxDestroyOfflineTts.argtypes = [ctypes.c_void_p]
    lib.SherpaOnnxDestroyOfflineTts.restype = None
    lib.SherpaOnnxOfflineTtsGenerate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_int32,
        ctypes.c_float,
    ]
    lib.SherpaOnnxOfflineTtsGenerate.restype = ctypes.POINTER(_NGeneratedAudio)
    lib.SherpaOnnxDestroyOfflineTtsGeneratedAudio.argtypes = [
        ctypes.POINTER(_NGeneratedAudio)
    ]
    lib.SherpaOnnxDestroyOfflineTtsGeneratedAudio.restype = None
    lib._atif_tts_api = True


def _build_native_engine(v: dict[str, Path]) -> tuple[Any, str] | None:
    from . import voice_id

    lib = voice_id._native_lib()
    if lib is None:
        return None
    try:
        _declare_native_tts(lib)
        cfg = _NOfflineTtsConfig()
        cfg.model.vits.model = str(v["onnx"]).encode("utf-8")
        cfg.model.vits.tokens = str(v["tokens"]).encode("utf-8")
        cfg.model.vits.data_dir = str(v["data_dir"]).encode("utf-8")
        cfg.model.vits.noise_scale = 0.667
        cfg.model.vits.noise_scale_w = 0.8
        cfg.model.vits.length_scale = 1.0
        cfg.model.num_threads = 1
        cfg.model.debug = 0
        cfg.model.provider = b"cpu"
        cfg.max_num_sentences = 2
        handle = lib.SherpaOnnxCreateOfflineTts(ctypes.byref(cfg))
        if not handle:
            return None
        return ((handle, lib), "native")
    except Exception:  # noqa: BLE001 - wrong arch / old lib: report, never raise
        return None


def _tts_engine(lang: str) -> tuple[Any, str] | None:
    """Loaded engine for this language's voice: (engine, "python"|"native")."""
    v = voice_files(lang)
    if v is None:
        return None
    key = str(v["dir"])
    hit = _TTS_CACHE.get(key)
    if hit is not None:
        return hit
    built = _build_python_engine(v) or _build_native_engine(v)
    if built is not None:
        _TTS_CACHE[key] = built
    return built


def _tts_engine_kind() -> str | None:
    """Which engine class this build can use, for the settings row."""
    try:
        import sherpa_onnx  # noqa: F401

        return "python"
    except Exception:  # noqa: BLE001
        pass
    from . import voice_id

    if voice_id._native_lib() is not None:
        return "native"
    return None


def _pcm16(samples: Any) -> bytes:
    """Float samples in [-1, 1] to little-endian int16."""
    out = array.array("h")
    for x in samples:
        f = float(x)
        if f > 1.0:
            f = 1.0
        elif f < -1.0:
            f = -1.0
        out.append(int(f * 32767))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def _via_sherpa(clean: str, lang: str) -> dict[str, Any]:
    """Speak with the downloaded piper voice; fails soft with a reason."""
    v = voice_files(lang)
    if v is None:
        return {"audio": None, "reason": "offline voice model not downloaded"}
    eng = _tts_engine(lang)
    if eng is None:
        return {"audio": None, "reason": "offline voice engine unavailable"}
    handle, kind = eng
    try:
        if kind == "python":
            audio = handle.generate(clean, sid=0, speed=1.0)
            pcm = _pcm16(audio.samples)
            rate = int(audio.sample_rate)
        else:
            h, lib = handle
            out = lib.SherpaOnnxOfflineTtsGenerate(
                h, clean.encode("utf-8"), 0, ctypes.c_float(1.0)
            )
            if not out:
                return {"audio": None, "reason": "the voice model returned no audio"}
            try:
                a = out.contents
                n = int(a.n)
                rate = int(a.sample_rate)
                buf = (ctypes.c_float * n).from_address(
                    ctypes.addressof(a.samples.contents)
                )
                pcm = _pcm16(buf)
            finally:
                lib.SherpaOnnxDestroyOfflineTtsGeneratedAudio(out)
        return {
            "audio": _wav(pcm, rate=rate),
            "reason": None,
            "model": f"piper/{v['dir'].name}",
        }
    except Exception as exc:  # noqa: BLE001 - never break the reply
        return {"audio": None, "reason": f"offline voice failed: {type(exc).__name__}"}


# ---- the voice pack download ---------------------------------------
_TTS_DL_LOCK = threading.Lock()
_TTS_DL: dict[str, Any] = {
    "state": "idle",  # idle | downloading | paused | ready | error
    "bytes": 0,
    "total": 0,
    "reason": None,
    "partial": 0,  # bytes already in .part files (never thrown away)
    "pause": False,
}


def tts_download_status() -> dict[str, Any]:
    with _TTS_DL_LOCK:
        out = dict(_TTS_DL)
        out.pop("pause", None)
    if out.get("state") in ("idle", "paused", "error"):
        part = 0
        for name, _, _ in TTS_ARCHIVES:
            p = TTS_DIR / (name + ".part")
            if p.is_file():
                part += p.stat().st_size
        out["partial"] = part
    return out


def tts_download_pause() -> dict[str, Any]:
    with _TTS_DL_LOCK:
        if _TTS_DL["state"] != "downloading":
            return {"ok": True, "reason": "not downloading"}
        _TTS_DL["pause"] = True
    return {"ok": True, "reason": "pausing"}


def tts_download_start() -> dict[str, Any]:
    """Download and unpack the whole voice pack in the background."""
    if voice_model_present():
        return {"ok": True, "reason": "already installed"}
    with _TTS_DL_LOCK:
        if _TTS_DL["state"] == "downloading":
            return {"ok": True, "reason": "already running"}
        _TTS_DL.update(
            {
                "state": "downloading",
                "bytes": 0,
                "total": TTS_PACK_BYTES,
                "reason": None,
                "pause": False,
            }
        )
    threading.Thread(target=_tts_download_worker, daemon=True).start()
    return {"ok": True, "started": True}


def _extract_voice_archive(archive: Path) -> None:
    """Unpack a release tarball next to the others, never outside TTS_DIR."""
    with tarfile.open(archive, "rb:bz2") as tf:
        tf.extractall(TTS_DIR, filter="data")


def _tts_download_worker() -> None:
    """Fetch both voice archives with resume and pause, unpack as we go.

    An unpacked voice counts as done, so a retry after a half-finished pack
    only fetches what is still missing. Tarballs are deleted after a clean
    unpack - a phone keeps the ~88 MB of voices, not the archive too.
    """
    import urllib.request

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    with _TTS_DL_LOCK:
        _TTS_DL["total"] = TTS_PACK_BYTES
        _TTS_DL["bytes"] = 0

    def _bump(value: int) -> None:
        with _TTS_DL_LOCK:
            _TTS_DL["bytes"] = value

    try:
        for name, size, voice_key in TTS_ARCHIVES:
            with _TTS_DL_LOCK:
                if _TTS_DL["pause"]:
                    _TTS_DL.update({"state": "paused", "reason": "paused by user"})
                    return
            if voice_files(voice_key) is not None:
                done += size
                _bump(done)
                continue
            dest = TTS_DIR / name
            tmp = TTS_DIR / (name + ".part")
            url = _TTS_RELEASE + name
            last_error = "download failed"
            for attempt in range(3):
                try:
                    have = tmp.stat().st_size if tmp.is_file() else 0
                    if have >= size * 0.99:
                        break
                    headers = {"User-Agent": "atif-assistant"}
                    if have:
                        headers["Range"] = f"bytes={have}-"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        resuming = have > 0 and getattr(resp, "status", 200) == 206
                        if have and not resuming:
                            have = 0
                        _bump(done + have)
                        mode = "ab" if have else "wb"
                        got = have
                        with open(tmp, mode) as fh:
                            while True:
                                with _TTS_DL_LOCK:
                                    if _TTS_DL["pause"]:
                                        _TTS_DL.update(
                                            {"state": "paused", "reason": "paused by user"}
                                        )
                                        return
                                chunk = resp.read(1024 * 256)
                                if not chunk:
                                    break
                                fh.write(chunk)
                                got += len(chunk)
                                _bump(done + got)
                    got = tmp.stat().st_size if tmp.is_file() else 0
                    if got < size * 0.99:
                        raise OSError(
                            f"connection ended early ({got} of {size} bytes)"
                        )
                    break
                except Exception as exc:  # noqa: BLE001 - retry, then fail soft
                    last_error = str(exc)[:200] or type(exc).__name__
                    if attempt < 2:
                        time.sleep(1.5)
            else:
                raise OSError(last_error)
            if not tmp.is_file() or tmp.stat().st_size < size * 0.99:
                raise OSError(last_error)
            tmp.replace(dest)
            _extract_voice_archive(dest)
            if voice_files(voice_key) is None:
                raise OSError(f"{name} unpacked but the voice files are missing")
            try:
                dest.unlink()
            except Exception:  # noqa: BLE001 - leftover archive is harmless
                pass
            done += size
            _bump(done)
        with _TTS_DL_LOCK:
            _TTS_DL.update(
                {"state": "ready", "reason": "installed", "partial": 0, "bytes": done}
            )
        try:
            from . import applog

            applog.log("tts.voice_pack_ready", bytes=done)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001 - keep every byte for resume
        last_error = str(exc)[:200] or type(exc).__name__
        partial = 0
        for name, _, _ in TTS_ARCHIVES:
            p = TTS_DIR / (name + ".part")
            if p.is_file():
                partial += p.stat().st_size
        reason = last_error
        if partial:
            reason = (
                f"{last_error} — progress saved ({partial // 1048576} MB), tap resume"
            )
        with _TTS_DL_LOCK:
            _TTS_DL.update({"state": "error", "reason": reason, "partial": partial})
        try:
            from . import applog

            applog.log("tts.voice_pack_failed", error=last_error, partial=partial)
        except Exception:  # noqa: BLE001
            pass
