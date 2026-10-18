"""Cross-instance sync: paired Atif Assistant servers share all chats.

Each instance keeps its own SQLite file; pairing two of them (peer URL +
the shared key) makes them converge. A background worker polls every peer
with POST /api/sync/swap - one round trip that pushes our unsent change
rows and pulls theirs - after every answer (wake), on an interval, and
on demand (SYNC NOW). Last-write-wins by timestamp, tombstones stop
deletions from resurrecting, and a row both sides created independently
binds instead of duplicating.

Direction is deliberately poll-driven: whichever instance can open a
TCP connection to the other runs the cycle, and the swap carries both
directions. The phone only listens on loopback, so it polls out to the
desktop (or any reachable peer) and never needs to expose itself.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from typing import Any

import httpx

from . import db
from .config import HOST, PORT

PEER_TIMEOUT = 15.0
BATCH = 500
MAX_ROUNDS = 8
MIN_INTERVAL = 10
MAX_INTERVAL = 3600

_wake = threading.Event()
_worker_started = False
_worker_lock = threading.Lock()
_last_cycle: dict[str, Any] = {
    "at": None,
    "pushed": 0,
    "pulled": 0,
    "errors": 0,
    "error": None,
}


def notify() -> None:
    """Ask the worker to run a cycle now (called after every answer)."""
    _wake.set()


def key_ok(presented: str | None) -> bool:
    """Constant-time check of the X-Sync-Key a peer presented."""
    expected = db.sync_secret()
    if not expected or not presented:
        return False
    return secrets.compare_digest(str(presented), expected)


def _peers() -> list[str]:
    try:
        raw = json.loads(db.get_setting("sync.peers", "[]") or "[]")
    except (TypeError, ValueError):
        return []
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        url = str(item).strip().rstrip("/")
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out


def enabled() -> bool:
    return db.get_setting("sync.enabled", "off") == "on"


def interval() -> int:
    try:
        value = int(db.get_setting("sync.interval", "30") or "30")
    except (TypeError, ValueError):
        value = 30
    return max(MIN_INTERVAL, min(MAX_INTERVAL, value))


def _lan_ips() -> list[str]:
    """Local network addresses another device would dial (loopback excluded)."""
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.append(ip)
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def status() -> dict[str, Any]:
    """Everything the settings row needs: identity, peers, reachability."""
    states = {s.get("peer"): s for s in db.sync_states()}
    peers = []
    for url in _peers():
        st = states.get(url) or {}
        peers.append(
            {
                "url": url,
                "peer_id": st.get("peer_id"),
                "last_at": st.get("last_at"),
                "last_error": st.get("last_error"),
                "pending": db.sync_pending(
                    int(st.get("sent_upto") or 0), st.get("peer_id")
                ),
            }
        )
    reachable = HOST not in ("127.0.0.1", "localhost")
    lan_urls = [f"http://{ip}:{PORT}" for ip in _lan_ips()]
    hint = None
    if not reachable:
        hint = (
            "This server listens on 127.0.0.1 only, so other devices cannot "
            "add it as a peer (outbound sync from here still works). Start "
            "with ATIF_ASSISTANT_BIND=lan to accept sync from other devices."
        )
    return {
        "device_id": db.sync_device_id(),
        "secret": db.sync_secret(),
        "enabled": enabled(),
        "interval": interval(),
        "peers": peers,
        "reachable": reachable,
        "host": HOST,
        "port": PORT,
        "lan_urls": lan_urls,
        "hint": hint,
        "last": dict(_last_cycle),
        "log": db.sync_log_len(),
    }


def configure(body: dict[str, Any]) -> dict[str, Any]:
    """Apply UI changes: enable, interval, add/remove peer, rotate key."""
    if body.get("enabled") is not None:
        db.set_setting("sync.enabled", "on" if body.get("enabled") else "off")
    if body.get("interval") is not None:
        try:
            iv = int(body.get("interval"))
        except (TypeError, ValueError):
            iv = interval()
        db.set_setting("sync.interval", str(max(MIN_INTERVAL, min(MAX_INTERVAL, iv))))
    if isinstance(body.get("add_peer"), str):
        url = body["add_peer"].strip().rstrip("/")
        if url.startswith(("http://", "https://")):
            peers = _peers()
            if url not in peers:
                peers.append(url)
                db.set_setting("sync.peers", json.dumps(peers))
                db.sync_state_get(url)  # materialise state row (defaults)
                db.sync_state_save(url)
    if isinstance(body.get("remove_peer"), str):
        url = body["remove_peer"].strip().rstrip("/")
        peers = [p for p in _peers() if p != url]
        db.set_setting("sync.peers", json.dumps(peers))
    if body.get("rotate"):
        db.set_setting("sync.secret", secrets.token_hex(16))
    return status()


def handle_swap(body: dict[str, Any]) -> dict[str, Any]:
    """One round trip with a peer: apply their rows, hand back ours."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    device_id = str(body.get("device_id") or "").strip()
    if not device_id or len(device_id) > 64:
        raise ValueError("device_id required")
    try:
        since = int(body.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    rows = body.get("rows") or []
    if not isinstance(rows, list) or len(rows) > BATCH * 2:
        raise ValueError("rows must be a list within limits")
    counts = (
        db.sync_apply_rows(device_id, rows) if rows
        else {"applied": 0, "skipped": 0, "dropped": 0}
    )
    # Exclude rows the REQUESTER wrote (echo suppression): their own changes
    # bounced into our log must not be handed straight back to them.
    inbox = db.sync_inbox_rows(since, device_id)
    return {
        "peer": db.sync_device_id(),
        "rows": inbox["rows"],
        "next": inbox["next"],
        "more": inbox["more"],
        "processed": counts["applied"] + counts["skipped"] + counts["dropped"],
        "applied": counts["applied"],
        "skipped": counts["skipped"],
        "dropped": counts["dropped"],
    }


def _cycle_once() -> dict[str, Any]:
    """Poll every configured peer: push what they lack, pull what we lack."""
    if not enabled():
        return {"skipped": "disabled"}
    peers = _peers()
    if not peers:
        return {"skipped": "no peers"}
    me = db.sync_device_id()
    key = db.sync_secret()
    pushed = pulled = errors = 0
    last_error = None
    with httpx.Client(timeout=PEER_TIMEOUT) as client:
        for url in peers:
            state = db.sync_state_get(url)
            peer_id = state.get("peer_id")
            sent_upto = int(state.get("sent_upto") or 0)
            recv_upto = int(state.get("recv_upto") or 0)
            try:
                for _ in range(MAX_ROUNDS):
                    out = db.sync_outbox(peer_id, sent_upto, BATCH)
                    payload = {
                        "device_id": me,
                        "since": recv_upto,
                        "rows": out["rows"],
                    }
                    resp = client.post(
                        f"{url}/api/sync/swap",
                        json=payload,
                        headers={"X-Sync-Key": key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    their_id = str(data.get("peer") or "")
                    if their_id and their_id != peer_id:
                        peer_id = their_id
                        db.sync_state_save(url, peer_id=peer_id)
                    theirs = data.get("rows") or []
                    if theirs:
                        db.sync_apply_rows(peer_id or their_id or "peer", theirs)
                    recv_upto = int(data.get("next") or recv_upto)
                    processed = int(data.get("processed") or 0)
                    if processed >= len(out["rows"]):
                        sent_upto = int(out["upto"])
                    db.sync_state_save(
                        url,
                        sent_upto=sent_upto,
                        recv_upto=recv_upto,
                        last_at=db.now(),
                        last_error=None,
                        processed=processed,
                    )
                    pushed += len(out["rows"])
                    pulled += len(theirs)
                    more = bool(out.get("full")) or bool(data.get("more"))
                    if not more:
                        break
            except Exception as exc:  # noqa: BLE001 - one peer never blocks the rest
                errors += 1
                last_error = f"{url}: {type(exc).__name__}: {exc}"[:220]
                db.sync_state_save(
                    url, last_error=last_error, last_at=db.now()
                )
    _last_cycle.update(
        at=db.now(),
        pushed=pushed,
        pulled=pulled,
        errors=errors,
        error=last_error,
    )
    try:
        from . import applog

        applog.log(
            "sync.cycle",
            pushed=pushed,
            pulled=pulled,
            errors=errors,
            peers=len(peers),
        )
    except Exception:  # noqa: BLE001 - logging must never break a cycle
        pass
    return {"pushed": pushed, "pulled": pulled, "errors": errors}


def _worker() -> None:
    """Background loop: sleep until poked or the interval elapses."""
    while True:
        _wake.wait(timeout=interval())
        _wake.clear()
        try:
            _cycle_once()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            _last_cycle["error"] = f"{type(exc).__name__}: {exc}"[:220]
            time.sleep(interval())


def ensure_worker() -> None:
    """Start the worker once (server startup; safe to call repeatedly)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="atif-sync", daemon=True).start()
        _worker_started = True
