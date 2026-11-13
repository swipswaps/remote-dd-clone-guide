#!/usr/bin/env bash
# bridge-check.sh — probe the local clone backend from the shell.
# Usage: bash scripts/bridge-check.sh [port] [token]
set +e

PORT="${1:-8080}"
TOKEN="${2:-}"
if [ -z "$TOKEN" ] && [ -f .env ]; then
  TOKEN=$(grep -E '^BACKEND_TOKEN=' .env | cut -d= -f2-)
fi

BASE="http://127.0.0.1:${PORT}"
say() { printf '%s\n' "$*"; }

say "=== bridge-check ==="
say "base:  $BASE"
say "token: $( [ -n "$TOKEN" ] && echo 'set' || echo '(not set)' )"
say ""

say "--- /health (no auth) ---"
HEALTH=$(curl -sS --max-time 3 "$BASE/health" 2>&1)
case "$HEALTH" in
  *'"status":"ok"'*) say "OK: $HEALTH" ;;
  *)                  say "FAIL: backend not reachable at $BASE"
                      say "      $HEALTH"
                      say "      start it with: docker compose up -d"
                      exit 0 ;;
esac
say ""

if [ -z "$TOKEN" ]; then
  say "skipping authed endpoints — no token."
  exit 0
fi

say "--- /devices (auth) ---"
curl -sS --max-time 5 -H "Authorization: Bearer $TOKEN" "$BASE/devices" 2>&1
say ""

say "--- /status (auth) ---"
curl -sS --max-time 5 -H "Authorization: Bearer $TOKEN" "$BASE/status" 2>&1
say ""
