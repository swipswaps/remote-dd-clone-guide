#!/usr/bin/env bash
# bridge-check.sh — shell-level equivalent of the Pages → localhost probe.
#
# Usage:
#   ./bridge-check.sh [port] [health-path]
#
# Example:
#   ./bridge-check.sh 8080 /health
#
# Exit code: 0 if advanced mode is available, 1 if limited.
# Never exits 1 on missing arguments — prints usage instead.
set +e

PORT="${1:-8080}"
PATH_="${2:-/health}"
URL="http://localhost:${PORT}${PATH_}"

say() { printf '%s\n' "$*"; }

say "=== pages-local bridge check ==="
say "url: $URL"
say ""

# Bounded probe: curl --max-time is the shell equivalent of AbortController.
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$URL")
CURL_RC=$?

if [ "$CURL_RC" -ne 0 ]; then
  say "advanced-mode: limited"
  say "reason: connection refused or timed out on localhost:${PORT}"
  say ""
  say "verbatim fallback the page would show:"
  say "  static mode — limited (no localhost backend — run: docker compose up -d)"
  exit 0
fi

case "$HTTP_CODE" in
  2*|3*)
    say "advanced-mode: available (HTTP $HTTP_CODE)"
    say "the Pages site will unlock advanced features on next reload."
    exit 0
    ;;
  4*|5*)
    say "advanced-mode: backend reachable but unhealthy (HTTP $HTTP_CODE)"
    say "check the container: docker compose ps && docker compose logs --tail=50"
    say ""
    say "verbatim fallback the page would show:"
    say "  Backend Offline"
    exit 1
    ;;
  *)
    say "advanced-mode: unknown response (HTTP $HTTP_CODE)"
    exit 1
    ;;
esac
