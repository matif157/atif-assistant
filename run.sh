#!/usr/bin/env bash
# Start Atif Assistant. Loads .env if present, then runs the server.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"

# Python that definitely exists, for the JSON probe below.
TS_SOCKET_PY="python3"
command -v python3 >/dev/null 2>&1 || TS_SOCKET_PY=".venv/bin/python"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# First run on a fresh machine: the offline zip deliberately ships without
# .venv, so create it and install the pinned set before starting. No-op once
# .venv exists, so it never touches an already-working install.
if [ ! -x .venv/bin/python ]; then
  echo "Atif Assistant  ->  creating .venv and installing dependencies..." >&2
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv >/dev/null
    uv pip install --python .venv/bin/python -r requirements.lock
  else
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -r requirements.lock
  fi
fi

PORT="${ATIF_ASSISTANT_PORT:-8770}"
BIND="${ATIF_ASSISTANT_HOST:-127.0.0.1}"

# ATIF_ASSISTANT_BIND=tailnet binds to this machine's Tailscale IP instead of loopback,
# so the app is reachable from your phone without opening anything to the
# internet. If the IP is not bindable it falls back to loopback and says so,
# rather than failing to start.
if [ "${ATIF_ASSISTANT_BIND:-}" = "tailnet" ]; then
  # The state/socket directory keeps its original name so the already
  # authenticated Tailscale node identity survives the project rename.
  TS_SOCK="${TS_SOCKET:-$HOME/.local/share/raees-tailscale/tailscaled.sock}"
  TS_BIN="$(command -v tailscale || echo /opt/homebrew/bin/tailscale)"
  if [ -S "$TS_SOCK" ]; then
    TS_IP="$("$TS_BIN" --socket="$TS_SOCK" status --json 2>/dev/null \
      | "$TS_SOCKET_PY" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("Self",{}).get("TailscaleIPs") or [""])[0])' \
      2>/dev/null || true)"
    # Only bind the tailnet IP if it is actually assigned to a local
    # interface. Under `tailscaled --tun=userspace-networking` there is no
    # tun device, so the IP exists in Tailscale's userspace stack but is not
    # bindable, and binding to it fails with EADDRNOTAVAIL.
    if [ -n "$TS_IP" ] && ifconfig 2>/dev/null | grep -q "inet ${TS_IP} "; then
      BIND="$TS_IP"
      export ATIF_ASSISTANT_TAILSCALE_HOST="$TS_IP"
    elif [ -n "$TS_IP" ]; then
      # Daemon is up and authenticated, but userspace networking means there
      # is no tun device, so the tailnet IP cannot be bound. Serve proxies
      # loopback and works fine without a tun device, so point at that rather
      # than failing.
      echo "Atif Assistant  ->  Tailscale is authenticated (${TS_IP}) but in userspace mode," >&2
      echo "          so that IP is not bindable here. Starting on loopback." >&2
      echo "          For phone access, enable Serve once:" >&2
      echo "            https://login.tailscale.com/f/serve" >&2
      echo "          then:  ts serve --bg ${PORT}" >&2
    else
      echo "Atif Assistant  ->  tailnet requested but no Tailscale IP reported." >&2
      echo "          Starting on loopback instead." >&2
    fi
  else
    echo "Atif Assistant  ->  tailnet requested but no Tailscale socket found." >&2
    echo "          Starting on loopback instead." >&2
  fi
fi

if [ -n "${ATIF_ASSISTANT_TAILSCALE_HOST:-}" ] && [ "$BIND" != "127.0.0.1" ]; then
  echo "Atif Assistant  ->  http://${BIND}:${PORT}   (Tailscale: reachable from your devices)"
else
  echo "Atif Assistant  ->  http://127.0.0.1:${PORT}"
fi
echo "          local:  http://127.0.0.1:${PORT}"

exec .venv/bin/python -m uvicorn atif_assistant.app:app \
  --host "$BIND" \
  --port "$PORT"