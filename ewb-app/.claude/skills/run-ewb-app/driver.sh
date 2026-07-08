#!/usr/bin/env bash
# Driver for running & smoke-testing the EWB Control Tower (ewb-app).
#
# Launches the FastAPI app in mock mode against a scratch DB, exercises
# the core API flows with curl (this is what the dashboard's JS calls
# under the hood), and captures a dashboard screenshot with headless
# Chrome. chromium-cli is not installed in this environment, so
# `google-chrome --headless --screenshot` is the render-proof mechanism
# instead — sufficient here because the UI is a read-and-fetch SPA with
# no client-side routing: a screenshot after page load proves the render,
# and every interactive action (lookup/extend/iod/auto) is a plain JSON
# POST/GET that curl exercises directly and more reliably than scripting
# clicks would.
#
# Usage:
#   ./driver.sh start               # launch server, wait for readiness
#   ./driver.sh smoke                # run curl-based flow against a running server
#   ./driver.sh screenshot [outfile] # capture dashboard PNG (default /tmp/ewb_driver_dashboard.png)
#   ./driver.sh stop                 # stop the server, clean up scratch DB
#   ./driver.sh all                  # start -> smoke -> screenshot -> stop (default)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"   # .claude/skills/run-ewb-app -> ewb-app

PORT="${EWB_DRIVER_PORT:-8080}"
DB_PATH="${EWB_DRIVER_DB:-/tmp/ewb_driver_${PORT}.db}"
PID_FILE="/tmp/ewb_driver_${PORT}.pid"
BASE="http://127.0.0.1:${PORT}"
SCREENSHOT_DEFAULT="/tmp/ewb_driver_dashboard.png"

start() {
  cd "$APP_DIR"
  rm -f "$DB_PATH"
  EWB_API_MODE=mock SEED_DEMO_DATA=true APP_PORT="$PORT" DB_PATH="$DB_PATH" \
    nohup python3 app.py > /tmp/ewb_driver_server.log 2>&1 &
  echo $! > "$PID_FILE"
  if ! timeout 30 bash -c "until curl -sf '$BASE/' >/dev/null; do sleep 0.5; done"; then
    echo "server never came up; log:"
    cat /tmp/ewb_driver_server.log
    exit 1
  fi
  echo "server up on $BASE (pid=$(cat "$PID_FILE"), db=$DB_PATH)"
}

stop() {
  if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  rm -f "$DB_PATH"
  echo "stopped"
}

json_get() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

smoke() {
  echo "== GET / =="
  curl -s -o /dev/null -w "  %{http_code}\n" "$BASE/"

  echo "== GET /api/shipments =="
  resp=$(curl -s "$BASE/api/shipments")
  echo "  shipments: $(echo "$resp" | json_get "len(d['shipments'])"), auto_extend: $(echo "$resp" | json_get "d['auto_extend']")"

  echo "== GET /api/lookup?q=INV-1002 =="
  resp=$(curl -s "$BASE/api/lookup?q=INV-1002")
  echo "  ok=$(echo "$resp" | json_get "d['ok']") status=$(echo "$resp" | json_get "d['status']")"

  echo "== POST /api/extend {q: INV-1002} =="
  resp=$(curl -s -X POST "$BASE/api/extend" -H "Content-Type: application/json" -d '{"q":"INV-1002"}')
  echo "  ok=$(echo "$resp" | json_get "d['ok']") message=$(echo "$resp" | json_get "d['message']")"

  echo "== GET /api/logs (expect the extend above) =="
  resp=$(curl -s "$BASE/api/logs")
  echo "  entries: $(echo "$resp" | json_get "len(d['logs'])")"

  echo "== POST /api/auto {enabled:true} then GET /api/auto =="
  curl -s -X POST "$BASE/api/auto" -H "Content-Type: application/json" -d '{"enabled":true}' >/dev/null
  resp=$(curl -s "$BASE/api/auto")
  echo "  enabled=$(echo "$resp" | json_get "d['enabled']")"
  curl -s -X POST "$BASE/api/auto" -H "Content-Type: application/json" -d '{"enabled":false}' >/dev/null
}

screenshot() {
  local out="${1:-$SCREENSHOT_DEFAULT}"
  google-chrome --headless --disable-gpu --no-sandbox --window-size=1400,1400 \
    --screenshot="$out" "$BASE/" >/tmp/ewb_driver_chrome.log 2>&1
  echo "screenshot: $out"
}

cmd="${1:-all}"
case "$cmd" in
  start) start ;;
  stop) stop ;;
  smoke) smoke ;;
  screenshot) screenshot "${2:-}" ;;
  all)
    start
    smoke
    screenshot
    stop
    ;;
  *) echo "usage: $0 {start|stop|smoke|screenshot [file]|all}"; exit 2 ;;
esac
