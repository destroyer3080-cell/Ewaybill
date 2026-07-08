#!/usr/bin/env bash
# End-to-end test suite for the EWB Control Tower (mock backend).
# Starts its own server against a throwaway DB, seeds demo data plus a few
# deterministic window-boundary rows, then exercises the full API contract.
# Must pass before any commit (CLAUDE.md §5).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export EWB_API_MODE=mock
export SEED_DEMO_DATA=true
export AUTO_EXTEND_ENABLED=false
export AUTO_CHECK_INTERVAL_SECONDS=3
export APP_PORT="${APP_PORT:-8899}"
export DB_PATH="$(mktemp -u /tmp/ewb_test_XXXXXX.db)"

BASE="http://127.0.0.1:${APP_PORT}"
PASS=0
FAIL=0

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$DB_PATH" "${DB_PATH}-journal" "${DB_PATH}-wal" "${DB_PATH}-shm"
}
trap cleanup EXIT

pass() { PASS=$((PASS+1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
json_get() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "== starting server on :${APP_PORT} (DB=${DB_PATH}) =="
python3 app.py >/tmp/ewb_test_server.log 2>&1 &
SERVER_PID=$!

up=0
for i in $(seq 1 30); do
  if curl -s -o /dev/null "${BASE}/"; then up=1; break; fi
  sleep 0.5
done
if [[ "$up" -ne 1 ]]; then
  echo "server never came up; log:"
  cat /tmp/ewb_test_server.log
  exit 1
fi

echo "== seeding deterministic window-boundary rows =="
python3 - <<PYEOF
import sqlite3, time
conn = sqlite3.connect("${DB_PATH}")
now = time.time()
rows = [
    ("TEST-INWINDOW",   "900000000001", "TN01AB0001", "Chennai", "600001", 33,
     "Bengaluru", "560001", 400, now + 2 * 3600, "OPEN"),
    ("TEST-TOOEARLY",   "900000000002", "TN01AB0002", "Chennai", "600001", 33,
     "Bengaluru", "560001", 400, now + 20 * 3600, "OPEN"),
    ("TEST-TOOLATE",    "900000000003", "TN01AB0003", "Chennai", "600001", 33,
     "Bengaluru", "560001", 400, now - 20 * 3600, "OPEN"),
    ("TEST-AUTO",       "900000000004", "TN01AB0004", "Chennai", "600001", 33,
     "Bengaluru", "560001", 400, now + 1 * 3600, "OPEN"),
    ("TEST-AUTOCLOSED", "900000000005", "TN01AB0005", "Chennai", "600001", 33,
     "Bengaluru", "560001", 400, now + 1 * 3600, "CLOSED"),
]
for invoice, ewb, vehicle, fp, fpin, fstate, tp, tpin, dist, expiry, iod in rows:
    conn.execute(
        """INSERT INTO shipments
           (invoice_no, ewb_no, vehicle_no, from_place, from_pincode, from_state,
            to_place, to_pincode, distance_km, iod_status, expiry_ts, generated_ts, extensions)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (invoice, ewb, vehicle, fp, fpin, fstate, tp, tpin, dist, iod, int(expiry), int(now - 2 * 86400)),
    )
conn.commit()
conn.close()
PYEOF

echo
echo "== 1: lookup by invoice -> found, correct status =="
resp=$(curl -s "${BASE}/api/lookup?q=INV-1002")
ok=$(echo "$resp" | json_get "d['ok']")
status=$(echo "$resp" | json_get "d['status']")
if [[ "$ok" == "True" && "$status" == "WINDOW" ]]; then
  pass "lookup INV-1002 -> ok, status=WINDOW"
else
  fail "lookup INV-1002 -> ok=$ok status=$status resp=$resp"
fi

echo
echo "== 2: extend inside window -> ok, new expiry = midnight per distance math =="
resp=$(curl -s -X POST "${BASE}/api/extend" -H "Content-Type: application/json" \
  -d '{"q":"TEST-INWINDOW","remaining_km":400}')
ok=$(echo "$resp" | json_get "d['ok']")
new_expiry=$(echo "$resp" | json_get "d['shipment']['expiry_ts']")
expected=$(python3 -c "
import datetime, math
days = math.ceil(400/200)
d = (datetime.datetime.now() + datetime.timedelta(days=days)).date()
print(int(datetime.datetime.combine(d, datetime.time(23,59,0)).timestamp()))
")
if [[ "$ok" == "True" && "$new_expiry" == "$expected" ]]; then
  pass "extend in window -> ok, expiry=$new_expiry matches midnight+2d"
else
  fail "extend in window -> ok=$ok new_expiry=$new_expiry expected=$expected resp=$resp"
fi

echo
echo "== 3: extend >8h before expiry -> rejected with window message =="
resp=$(curl -s -X POST "${BASE}/api/extend" -H "Content-Type: application/json" \
  -d '{"q":"TEST-TOOEARLY","remaining_km":400}')
ok=$(echo "$resp" | json_get "d['ok']")
msg=$(echo "$resp" | json_get "d['message']")
if [[ "$ok" == "False" && "$msg" == *"window"* ]]; then
  pass "extend too early -> rejected: $msg"
else
  fail "extend too early -> ok=$ok msg=$msg resp=$resp"
fi

echo
echo "== 4: extend >8h after expiry -> rejected with fresh-EWB message =="
resp=$(curl -s -X POST "${BASE}/api/extend" -H "Content-Type: application/json" \
  -d '{"q":"TEST-TOOLATE","remaining_km":400}')
ok=$(echo "$resp" | json_get "d['ok']")
msg=$(echo "$resp" | json_get "d['message']")
if [[ "$ok" == "False" && "$msg" == *"fresh"* ]]; then
  pass "extend too late -> rejected: $msg"
else
  fail "extend too late -> ok=$ok msg=$msg resp=$resp"
fi

echo
echo "== 5: lookup unknown invoice -> ok:false with message =="
resp=$(curl -s "${BASE}/api/lookup?q=NOPE-DOES-NOT-EXIST")
ok=$(echo "$resp" | json_get "d['ok']")
if [[ "$ok" == "False" ]]; then
  pass "lookup unknown -> ok:false"
else
  fail "lookup unknown -> resp=$resp"
fi

echo
echo "== 6: auto ON -> watcher extends WINDOW+IOD-OPEN, skips IOD CLOSED =="
curl -s -X POST "${BASE}/api/auto" -H "Content-Type: application/json" -d '{"enabled":true}' >/dev/null
sleep 5
resp=$(curl -s "${BASE}/api/lookup?q=TEST-AUTO")
ext=$(echo "$resp" | json_get "d['shipment']['extensions']")
resp2=$(curl -s "${BASE}/api/lookup?q=TEST-AUTOCLOSED")
ext2=$(echo "$resp2" | json_get "d['shipment']['extensions']")
if [[ "$ext" -ge 1 && "$ext2" == "0" ]]; then
  pass "auto-extend: TEST-AUTO extended ($ext), TEST-AUTOCLOSED untouched"
else
  fail "auto-extend: TEST-AUTO ext=$ext TEST-AUTOCLOSED ext=$ext2"
fi
curl -s -X POST "${BASE}/api/auto" -H "Content-Type: application/json" -d '{"enabled":false}' >/dev/null

echo
echo "== 7: board state consistent afterwards =="
resp=$(curl -s "${BASE}/api/shipments")
count=$(echo "$resp" | json_get "len(d['shipments'])")
if [[ "$count" -eq 14 ]]; then
  pass "GET /api/shipments -> $count shipments"
else
  fail "GET /api/shipments -> unexpected count=$count"
fi

echo
echo "== 8: GET / returns 200 =="
code=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/")
if [[ "$code" == "200" ]]; then
  pass "GET / -> 200"
else
  fail "GET / -> $code"
fi

echo
echo "======================================"
echo "PASS: $PASS  FAIL: $FAIL"
echo "======================================"
[[ "$FAIL" -eq 0 ]]
