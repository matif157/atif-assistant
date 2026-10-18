"""Entry point the Android app calls to run the embedded server.

Chaquopy imports this module and calls ``start(files_dir)`` on a background
thread. ``files_dir`` is writable app storage, so the SQLite database, the
WAL files and any uploads live there and survive app restarts.

The web assets (``web/``) and the ``atif_assistant`` package are staged next to
this file by ``build_apk.sh`` before the Gradle build.
"""

import os
import threading

_started = False
_lock = threading.Lock()


def start(files_dir, llama_bin="", whisper_bin="", host="127.0.0.1", port=8770):
    """Start the server once. Safe to call more than once.

    ``llama_bin`` / ``whisper_bin`` are absolute paths of the extracted JNI
    libs (empty on desktop or on ABIs without the binaries). They have to be
    exported before ``atif_assistant`` is imported so the on-device providers
    can find them. Models live in files_dir/models for both stacks.

    Any failure clears the started guard again, so the UI's RETRY button can
    call ``start()`` after a port conflict, a bad environment or an import
    error instead of silently doing nothing forever.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True
    try:
        _boot(files_dir, llama_bin, whisper_bin, host, port)
    except BaseException as exc:  # noqa: BLE001 - reset, log, then re-raise
        with _lock:
            _started = False
        try:
            from atif_assistant.applog import log

            log("server.boot_failed", type=type(exc).__name__, error=str(exc)[:200])
        except Exception:  # noqa: BLE001 - logging must not mask the failure
            pass
        raise


def _boot(files_dir, llama_bin, whisper_bin, host, port) -> None:
    """Everything ``start()`` does once it owns the started guard."""
    os.makedirs(files_dir, exist_ok=True)
    os.environ.setdefault("ATIF_ASSISTANT_DATA_DIR", files_dir)
    os.environ.setdefault("ATIF_ASSISTANT_MODEL_DIR", os.path.join(files_dir, "models"))
    if llama_bin:
        os.environ["ATIF_ASSISTANT_LLAMACPP_BIN"] = llama_bin
    if whisper_bin:
        os.environ["ATIF_ASSISTANT_WHISPER_BIN"] = whisper_bin
    # The sherpa-onnx speaker engine (voice_id's ctypes path) rides in the
    # same nativeLibraryDir as the JNI binaries; absent on desktop.
    sherpa_dir = os.path.dirname(whisper_bin or llama_bin or "")
    if sherpa_dir and os.path.isfile(os.path.join(sherpa_dir, "libsherpa-onnx-c-api.so")):
        os.environ["ATIF_ASSISTANT_SHERPA_LIBS"] = sherpa_dir

    # Warm the on-device llama-server (binary + model present) so the first
    # question does not pay the model-load cost. Purely best effort: no
    # model yet, no problem - the provider starts lazily on first use.
    try:
        from atif_assistant import llm as _llm

        _llm.ensure_llamacpp_started()
    except Exception:  # noqa: BLE001 - never block the server boot
        pass

    import uvicorn

    from atif_assistant.app import app
    from atif_assistant.applog import log

    log(
        "server.boot",
        data_dir=files_dir,
        llama_bin=bool(llama_bin),
        whisper_bin=bool(whisper_bin),
    )

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
