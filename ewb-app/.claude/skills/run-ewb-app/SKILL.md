---
name: run-ewb-app
description: Build, run, and drive the EWB Control Tower (ewb-app). Use when asked to start ewb-app, run it, take a screenshot of its dashboard, smoke-test its API (lookup/extend/auto-extend/audit log), or verify a change actually works end-to-end.
---

FastAPI server + vanilla-JS dashboard, driven via
`.claude/skills/run-ewb-app/driver.sh` — it launches the app in mock
mode (zero credentials), smoke-tests the core API flows with `curl`
(what the dashboard's JS calls under the hood), and captures a
dashboard screenshot with headless Chrome.

All paths below are relative to `ewb-app/`.

## Prerequisites

Python deps:

```bash
pip install -r requirements.txt
```

For the screenshot step, `google-chrome` (or any Chromium build) on
PATH. In this container it was already present as `google-chrome-stable`
149.0.7827.114 — if it's missing elsewhere:

```bash
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y /tmp/chrome.deb
```

No `chromium-cli` in this environment — the driver uses
`google-chrome --headless --screenshot` directly instead, which is
sufficient here (see Gotchas).

## Setup

Nothing beyond `pip install -r requirements.txt`. Mock mode needs no
`.env` — `config.py` defaults to `EWB_API_MODE=mock`,
`SEED_DEMO_DATA=true`.

## Run (agent path)

```bash
chmod +x .claude/skills/run-ewb-app/driver.sh   # first time only
.claude/skills/run-ewb-app/driver.sh all
```

This runs start → smoke → screenshot → stop in one shot: launches the
server on port 8080 against a throwaway DB seeded with the 9 demo
shipments, hits `/`, `/api/shipments`, `/api/lookup`, `/api/extend`,
`/api/logs`, `/api/auto`, writes a screenshot, then stops the server
and deletes the scratch DB. Verified output from an actual run in this
container:

```
server up on http://127.0.0.1:8080 (pid=7500, db=/tmp/ewb_driver_8080.db)
== GET / ==
  200
== GET /api/shipments ==
  shipments: 9, auto_extend: False
== GET /api/lookup?q=INV-1002 ==
  ok=True status=WINDOW
== POST /api/extend {q: INV-1002} ==
  ok=True message=Validity extended by 2 day(s)
== GET /api/logs (expect the extend above) ==
  entries: 1
== POST /api/auto {enabled:true} then GET /api/auto ==
  enabled=True
screenshot: /tmp/ewb_driver_dashboard.png
stopped
```

Steps also run independently — useful when iterating on one flow:

| command | what it does |
|---|---|
| `driver.sh start` | launch server on `:8080` (override with `EWB_DRIVER_PORT`), wait for it to answer `GET /` |
| `driver.sh smoke` | run the curl sequence above against an already-running server |
| `driver.sh screenshot [file]` | capture the dashboard to `file` (default `/tmp/ewb_driver_dashboard.png`) |
| `driver.sh stop` | kill the server, delete the scratch DB |

Screenshot lands at `/tmp/ewb_driver_dashboard.png` by default. Server
log at `/tmp/ewb_driver_server.log`, Chrome's stderr at
`/tmp/ewb_driver_chrome.log`.

To point the driver at a different port/DB (e.g. running two at once):

```bash
EWB_DRIVER_PORT=8081 .claude/skills/run-ewb-app/driver.sh all
```

## Run (human path)

```bash
cp .env.example .env
python app.py                 # http://localhost:8000, Ctrl-C to stop
```

Delete `ewb.db` to reseed demo data fresh around the current time.

## Test

```bash
./run_tests.sh
```

Starts its own server against a throwaway DB and runs 8 end-to-end
scenarios (window-boundary extension rules, auto-extend watcher,
lookup, board consistency). All 8 pass as of this writing.

---

## Gotchas

- **No `chromium-cli` in this environment.** The `run` skill's default
  web-app pattern assumes it; here the driver falls back to
  `google-chrome --headless --disable-gpu --no-sandbox --screenshot=...`
  directly. This app's UI has no client-side routing or dynamic
  interaction that changes what's on screen after load — the dashboard
  fetches and renders once — so a static post-load screenshot is a
  faithful render-proof. The "Test / Ops" tab and "Audit Log" tab are
  just `display:none` toggles over data already fetched via the same
  `/api/*` endpoints the smoke script exercises directly, so `curl`
  covers their logic more reliably than scripting a tab click would.
- **`vaGetDriverNameByIndex` / `vaInitialize failed` on stderr during
  screenshot.** Harmless — headless Chrome falling back from VA-API
  hardware video accel to software rendering. The PNG still writes
  correctly; don't treat this line as a failure.
- **Port 8080 already in use.** `driver.sh start` doesn't check for a
  stale process on the port first. If a previous run's `stop` didn't
  fire (e.g. you killed the driver mid-`smoke`), `pkill -f "app.py"`
  or use `EWB_DRIVER_PORT` to pick a fresh port.
- **The watcher thread needs real wall-clock time to fire.** If you
  extend the driver to test `/api/auto`'s actual extension behavior
  (not just the on/off toggle), you need `AUTO_CHECK_INTERVAL_SECONDS`
  set low (e.g. `3`) and a `sleep` after enabling — `run_tests.sh`
  test 6 does exactly this; the driver's smoke step deliberately only
  toggles the flag, since a full watcher-fire test takes several
  seconds better spent in `run_tests.sh`.

## Troubleshooting

- **`curl: (7) Failed to connect` right after `driver.sh start`**: the
  30s readiness poll timed out — check `/tmp/ewb_driver_server.log`
  for a Python traceback (most likely a missing dependency; re-run
  `pip install -r requirements.txt`).
- **Screenshot is a mostly-blank dark rectangle**: means the page
  loaded before `/api/shipments` returned (unlikely — the dashboard's
  `loadShipments()` fires on script load and the driver only
  screenshots after the server already answered `/api/shipments` once
  during `smoke`) — but if it happens, add a `sleep 1` before the
  `google-chrome` call in `screenshot()`.
