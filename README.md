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
├── templates/index.html  dashboard + test screen (no build step)
├── requirements.txt
├── Dockerfile
├── run_tests.sh           end-to-end curl test suite
└── .env.example           every config option, documented
```

## Going live

1. Get GSP sandbox/production keys (MasterGST, ClearTax, Vayana, Adaequare)
   or NIC direct-API credentials — see `.env.example` for where to request
   each.
2. Edit `.env`: set `EWB_API_MODE=gsp` (or `nic`) and fill in credentials.
   Set `SEED_DEMO_DATA=false`.
3. Point a TMS sync job at the `shipments` table (upsert on `invoice_no`).
4. Deploy via Docker or systemd — see `CLAUDE.md` §6 for both.

Full production checklist is in `CLAUDE.md` §6.

## Guardrails

This system files real extension requests to NIC once switched off mock
mode. Do not weaken the ±8h window checks, remove the editable
location/distance fields or compliance warning from the UI, or let any
extension attempt (success or rejection) go unlogged. See `CLAUDE.md` §7
for the full list before making changes.
