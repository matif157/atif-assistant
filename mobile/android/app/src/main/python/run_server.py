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


def start(files_dir, llama_bin="", host="127.0.0.1", port=8770):
    """Start the server once. Safe to call more than once.

    ``llama_bin`` is the absolute path of the extracted llama-server JNI lib
    (empty on desktop or on ABIs without the binary). It has to be exported
    before ``atif_assistant.llm`` is imported so the on-device provider can
    find it.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    os.makedirs(files_dir, exist_ok=True)
    os.environ.setdefault("ATIF_ASSISTANT_DATA_DIR", files_dir)
    if llama_bin:
        os.environ["ATIF_ASSISTANT_LLAMACPP_BIN"] = llama_bin

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

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
