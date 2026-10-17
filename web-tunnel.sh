#!/usr/bin/env bash
# Public web URL for Atif Assistant — free, no account, no domain.
#
# Tries two methods in order:
#   1. Cloudflare quick tunnel   (https://….trycloudflare.com — nice URL, but
#      its API is unreachable from some networks)
#   2. localhost.run over SSH    (keyless, works anywhere SSH works)
#
# The URL changes on every restart — treat it like a secret. The app itself
# is protected by ATIF_ASSISTANT_WEB_PASSWORD in .env (browser login prompt).
#
# Usage:  ./run.sh            (terminal 1 — server on :8770)
#         ./web-tunnel.sh     (terminal 2 — prints the public URL)
set -uo pipefail

PORT="${ATIF_ASSISTANT_PORT:-8770}"

# Any HTTP answer means the server is up (401 counts — the password gate
# answers before routes do, and we don't have credentials yet at this point).
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health" || true)"
if [ -z "$code" ] || [ "$code" = "000" ]; then
  echo "Atif Assistant ->  server not answering on :${PORT}. Start ./run.sh first." >&2
  exit 1
fi

if [ -z "${ATIF_ASSISTANT_WEB_PASSWORD:-}" ] && [ -f .env ] && grep -q "^ATIF_ASSISTANT_WEB_PASSWORD=" .env; then
  set -a; source .env; set +a
fi
if [ -z "${ATIF_ASSISTANT_WEB_PASSWORD:-}" ]; then
  echo "Atif Assistant ->  WARNING: no ATIF_ASSISTANT_WEB_PASSWORD in .env —" >&2
  echo "                   anyone with the URL gets full access." >&2
fi

wait_for_url() { # $1 = log file, $2 = grep pattern, $3 = pid, $4 = tries
  local i=0
  while [ "$i" -lt "$4" ]; do
    sleep 1
    URL="$(grep -oE "$2" "$1" | grep -v '^https://api\.' | head -1)"
    [ -n "$URL" ] && return 0
    kill -0 "$3" 2>/dev/null || return 1
    i=$((i + 1))
  done
  return 1
}

# --- Method 1: Cloudflare quick tunnel ---------------------------------
LOG="$(mktemp -t atif-tunnel)"
cloudflared tunnel --url "http://127.0.0.1:${PORT}" >"$LOG" 2>&1 &
CF_PID=$!
if wait_for_url "$LOG" 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_PID" 25; then
  echo "Atif Assistant ->  public URL:  ${URL}" >&2
  echo "Atif Assistant ->  (Cloudflare tunnel — Ctrl+C stops)" >&2
  wait "$CF_PID"
  exit $?
fi
kill "$CF_PID" 2>/dev/null
wait "$CF_PID" 2>/dev/null
echo "Atif Assistant ->  Cloudflare unreachable from this network, falling back to SSH tunnel..." >&2

# --- Method 2: localhost.run (keyless SSH) ------------------------------
LOG2="$(mktemp -t atif-ssh-tunnel)"
ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -R "80:127.0.0.1:${PORT}" nokey@localhost.run >"$LOG2" 2>&1 &
SSH_PID=$!
if wait_for_url "$LOG2" 'https://[a-z0-9.-]+\.(lhr\.life|localhost\.run|loca\.lt)' "$SSH_PID" 25; then
  echo "Atif Assistant ->  public URL:  ${URL}" >&2
  echo "Atif Assistant ->  (SSH tunnel via localhost.run — Ctrl+C stops)" >&2
  wait "$SSH_PID"
  exit $?
fi
echo "Atif Assistant ->  both tunnel methods failed; last output:" >&2
tail -5 "$LOG2" >&2
exit 1
