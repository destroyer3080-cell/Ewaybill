# STATUS

Last verified: 2026-07-12, via `ewb-app/.claude/skills/run-ewb-app/driver.sh all`
and `ewb-app/run_tests.sh`. Both green.

## Live

- Dashboard, Test/Ops screen, Audit Log — all serving from `templates/index.html`
  against the FastAPI backend (`app.py`).
- `MockEWBClient` — full NIC rule simulation (±8h window, midnight expiry math,
  no-GPS defaults), zero credentials required. Default backend (`EWB_API_MODE=mock`).
- Auto-extend watcher — background thread, `do_extend(mode="AUTO")`, skips
  IOD-CLOSED rows, logs every attempt.
- `sync_tms.py` — roadmap item 1 (§8 of `CLAUDE.md`), done. Supports REST-API
  and CSV watch-dir modes, upsert on `invoice_no`, never overwrites an
  existing row's validity.
- `run-ewb-app` agent skill (`ewb-app/.claude/skills/run-ewb-app/`) — driver
  script for start/smoke/screenshot/stop, used to verify changes end-to-end
  without a human at a browser.

## Not yet live (still mock-only or unbuilt)

- `GSPEWBClient` / `NICEWBClient` — implemented per `CLAUDE.md` §3 but never
  run against real sandbox/production credentials in this environment. Needs
  real GSP or NIC keys in `.env` (`EWB_API_MODE=gsp|nic`) before trusting them.
- Roadmap items 2–6 (`CLAUDE.md` §8): WhatsApp/SMS alerts, transporter-EWB
  auto-discovery pull, multi-branch auth, Postgres migration, GPS ingestion —
  none started.

## Config as of last verification

`EWB_API_MODE=mock`, `SEED_DEMO_DATA=true` — this is the demo/training
configuration, not production. Going live means working through the
"Going live" checklist in `README.md` / `CLAUDE.md` §6, in particular
switching `SEED_DEMO_DATA=false` and supplying real GSP/NIC credentials.

## Notes for next session

- A standalone in-browser preview of the dashboard UI (mock `fetch`, no
  server) was published as a Claude Artifact during a design review; it is
  not part of this repo and has no source file here.
