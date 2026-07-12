# EWB Control Tower

E-way bill (EWB) expiry monitoring & extension system for a transporter.
Watches every shipment's EWB validity, flags what's about to expire, and
can auto-extend inside NIC's ±8h extension window to avoid the 200% CGST
Section 129 penalty for moving goods on an expired EWB.

Full business rules, NIC compliance constraints, and architecture are
documented in [`CLAUDE.md`](./CLAUDE.md) — read that for the "why" behind
anything below.

## Quick start (mock mode, zero credentials)

```bash
cd ewb-app
pip install -r requirements.txt
cp .env.example .env          # mock mode by default
python app.py                 # serves http://localhost:8000
```

Open `http://localhost:8000` — the dashboard comes pre-seeded with 9 demo
shipments spread across every urgency bucket (MISSED / WINDOW / SOON /
WATCH / OK / CLOSED). Mock mode simulates the NIC portal locally, so no
GSP/NIC credentials are needed to explore the app.

Explicit uvicorn invocation, if you prefer:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Run the test suite

```bash
cd ewb-app
./run_tests.sh
```

Starts its own server against a throwaway DB and runs the full end-to-end
suite: window-boundary extension rules, auto-extend watcher behavior,
lookup, and board consistency. Must pass before any commit.

To reseed demo data around the current time, delete `ewb.db` and restart.

## Project layout

```
ewb-app/
├── app.py               FastAPI app: routes, status engine, watcher thread
├── ewb_client.py         3 swappable API backends (mock | gsp | nic)
├── database.py           SQLite schema, queries, demo seed
├── config.py              loads .env
├── sync_tms.py           cron-safe TMS -> shipments upsert job
├── templates/index.html  dashboard + test screen (no build step)
├── requirements.txt
├── Dockerfile
├── run_tests.sh           end-to-end curl test suite
├── .env.example           every config option, documented
└── .claude/skills/run-ewb-app/   driver.sh + SKILL.md — launch/smoke-test/screenshot for agent use
```

## Running via the agent skill

For agent-driven runs (start server, curl-smoke the core API flows, capture
a dashboard screenshot) without touching the human quick-start above:

```bash
cd ewb-app
.claude/skills/run-ewb-app/driver.sh all
```

See [`ewb-app/.claude/skills/run-ewb-app/SKILL.md`](./ewb-app/.claude/skills/run-ewb-app/SKILL.md)
for the individual `start` / `smoke` / `screenshot` / `stop` steps.

## Syncing shipments from the TMS

`sync_tms.py` upserts shipments from the company TMS into the local DB on
`invoice_no`. It never touches EWB validity (`expiry_ts`/`generated_ts`) on
an existing row — only `/api/lookup` and an extension can change that — so
a sync run can't silently overwrite an authoritative NIC value. On a
brand-new invoice it needs a validity to seed the row, either from the TMS
record (`valid_upto` column) or a live portal lookup by `ewb_no`; if
neither is available the row is skipped with a warning rather than
fabricated.

Two source modes, picked via `TMS_SYNC_MODE` in `.env` (or `--mode`):

```bash
cd ewb-app

# REST API pull — TMS_API_URL returns a JSON array (or {"shipments": [...]})
python sync_tms.py --mode api

# CSV watch-dir sweep — processes every *.csv in TMS_CSV_WATCH_DIR, then
# moves each to TMS_CSV_ARCHIVE_DIR (clean) or TMS_CSV_ERROR_DIR (any row
# failed) so cron never reprocesses the same file
python sync_tms.py --mode csv

# one-off import of a single file, e.g. for an ops team manual upload
python sync_tms.py --csv /path/to/export.csv

# validate without writing
python sync_tms.py --dry-run
```

CSV header: `invoice_no, ewb_no, vehicle_no, from_place, from_pincode,
from_state, to_place, to_pincode, distance_km, iod_status, valid_upto,
generated_at` (the last two are optional, only used on first insert).

A file lock (`TMS_SYNC_LOCK_PATH`) keeps overlapping cron runs from
stepping on each other — a second run exits immediately with code 3.
Exit codes: `0` clean, `1` some records failed, `2` bad config, `3`
already running.

## Going live

1. Get GSP sandbox/production keys (MasterGST, ClearTax, Vayana, Adaequare)
   or NIC direct-API credentials — see `.env.example` for where to request
   each.
2. Edit `.env`: set `EWB_API_MODE=gsp` (or `nic`) and fill in credentials.
   Set `SEED_DEMO_DATA=false`.
3. Schedule `sync_tms.py` on cron to keep `shipments` filled from the TMS.
4. Deploy via Docker or systemd — see `CLAUDE.md` §6 for both.

Full production checklist is in `CLAUDE.md` §6.

## Guardrails

This system files real extension requests to NIC once switched off mock
mode. Do not weaken the ±8h window checks, remove the editable
location/distance fields or compliance warning from the UI, or let any
extension attempt (success or rejection) go unlogged. See `CLAUDE.md` §7
for the full list before making changes.
