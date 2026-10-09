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


def start(files_dir, host="127.0.0.1", port=8770):
    """Start the server once. Safe to call more than once."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    os.makedirs(files_dir, exist_ok=True)
    os.environ.setdefault("ATIF_ASSISTANT_DATA_DIR", files_dir)

    import uvicorn

    from atif_assistant.app import app

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
