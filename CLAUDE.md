# CLAUDE.md — EWB Control Tower

E-way bill expiry monitoring & extension system for an Indian logistics/transporter
company. Claude Code: read this file fully before writing or changing anything.
It is the single source of truth for business rules, architecture, and deploy.

---

## 1. What this system does (business context)

We are a transporter. Customers generate e-way bills (EWBs) on the NIC portal
(ewaybillgst.gov.in) for shipments we carry. EWBs have short validity
(1 day per 200 km) and expire at **midnight** of the last day. If a vehicle is
caught moving on an expired EWB, penalty under CGST Section 129 is
**200% of the tax payable** plus vehicle detention. This system prevents that:

1. **Dashboard** — shows every shipment bucketed by urgency so ops can see
   what is about to expire.
2. **Test/ops screen** — enter an invoice no or EWB no → fetch current
   validity → push an extension → validity updates on screen.
3. **Auto-extend trigger** — background watcher: `IF IOD ≠ CLOSED AND now is
   inside the extension window THEN call EXTENDVALIDITY automatically.`
   (IOD = Information of Delivery / proof of delivery flag from our TMS.)
4. **Audit log** — every extension attempt (manual or auto, success or NIC
   rejection) is recorded with the payload details.

### No-GPS policy (deliberate business decision)
We have no vehicle GPS feed yet. Therefore:
- Current location defaults to the **FROM ship-point** of the shipment.
- Remaining distance defaults to the **full route distance**.
- Reason is fixed: code **99 (Others)**, remarks **"Transit delay"**.
- These are DEFAULTS, not hard-coded: the manual screen must always keep
  location/pincode/distance/remarks editable, and the API must accept
  overrides. NEVER remove the editability or the compliance warning in the
  UI — declaring the origin as current location when the truck is mid-route
  is a misdeclaration risk the ops team must be able to correct per-call.

---

## 2. NIC compliance rules — HARD CONSTRAINTS, never violate in code

These mirror the live NIC E-way Bill system. The mock backend must enforce
them so testing matches production:

| Rule | Value |
|---|---|
| Extension window | Only from **8 hours before** to **8 hours after** `validUpto`. Outside → reject. |
| After window missed | EWB is dead. Only remedy: generate a fresh EWB before moving. Do NOT retry extension. |
| New validity math | `days = ceil(remaining_km / 200)` (regular cargo), new expiry = midnight (23:59) of day `today + days`. |
| Who can extend | Only the transporter currently assigned on the EWB (our GSTIN). |
| Part A | Immutable. Extension may only carry location, distance, vehicle/transdoc, reason. |
| Max total validity | 360 days from generation. |
| Auth token | NIC/GSP tokens live 6 hours; refresh at ≤5.5h; reuse until then. |
| Reason codes | 1 Natural calamity, 2 Law & order, 4 Transshipment, 5 Accident, 99 Others (+ remarks). |
| consignmentStatus | `M` = in movement (needs vehicleNo + place/pincode). `T` = in transit/godown (needs address lines + transitType). We use `M`. |

EXTENDVALIDITY payload shape (NIC API v1.03) — do not rename keys:

```json
{
  "ewbNo": 321008990121,
  "vehicleNo": "KL43L8812",
  "fromPlace": "Ernakulam",
  "fromState": 32,
  "fromPincode": 682016,
  "remainingDistance": 545,
  "transMode": "1",
  "transDocNo": "",
  "transDocDate": "",
  "consignmentStatus": "M",
  "transitType": "",
  "addressLine1": "", "addressLine2": "", "addressLine3": "",
  "extnRsnCode": 99,
  "extnRemarks": "Transit delay"
}
```

---

## 3. Architecture & file map

Stack: **Python 3.10+ / FastAPI / SQLite / vanilla-JS single-page UI**.
Keep it dependency-light: fastapi, uvicorn, requests, pycryptodome, python-dotenv.

```
ewb-app/
├── app.py               FastAPI app: routes, status engine, watcher thread
├── ewb_client.py        3 swappable API backends (mock | gsp | nic)
├── database.py          SQLite schema, queries, demo seed
├── config.py            loads .env
├── sync_tms.py          cron-safe TMS -> shipments upsert job (see §8 roadmap item 1)
├── templates/index.html dashboard + test screen (no build step, no framework)
├── requirements.txt
├── Dockerfile
├── run_tests.sh         end-to-end curl test suite
├── .env.example         every config option, documented
├── .env                 (gitignored) real credentials — NEVER commit
└── .claude/skills/run-ewb-app/   agent-driven launch/smoke-test/screenshot (driver.sh + SKILL.md)
```

### Status engine (single source of truth, in `app.py`; UI mirrors it)
```
CLOSED  : iod_status == CLOSED                     → no action
MISSED  : expiry < now - 8h                        → "fresh EWB needed", no extend button
WINDOW  : |expiry - now| <= 8h                     → extendable NOW (red)
SOON    : expiry <= now + 24h                      → amber
WATCH   : expiry <= now + 48h                      → yellow
OK      : else                                     → green
```

### Backend adapters (`ewb_client.py`) — common interface, never break it
```python
client.get_ewb(ewb_no)          -> {"ok", "ewb_no", "valid_upto_ts", "status", "raw"}
client.extend_validity(payload) -> {"ok", "new_valid_upto_ts", "message", "raw"}
```
- `MockEWBClient` — default. Simulates NIC against the local DB and ENFORCES
  all rules in §2. Must always work with zero credentials.
- `GSPEWBClient` — generic GSP/ASP REST (MasterGST-style paths
  `/authenticate`, `/GetEwayBill`, `/extendvalidity`; headers client_id,
  client_secret, gstin, username, password, authtoken). When adapting to a
  different GSP (ClearTax/Vayana/Adaequare), change ONLY this class.
- `NICEWBClient` — direct NIC v1.03: auth payload base64→RSA(PKCS1_v1_5) with
  NIC public key; response `sek` decrypted AES-256-ECB with the random 32-byte
  app_key; all subsequent bodies AES-256-ECB(sek) base64 under
  `{"action":"EXTENDVALIDITY","data":"..."}`. Verify exact URL paths against
  the doc version in the NIC onboarding mail before production.

Selection: `EWB_API_MODE=mock|gsp|nic` in `.env`. Adding a new backend =
new class + one entry in `get_client()`. Nothing else changes.

### Database (`database.py`)
`shipments` — invoice_no (unique), ewb_no (unique), vehicle_no, from_place,
from_pincode, from_state (GST state code, Kerala=32), to_place, to_pincode,
distance_km, iod_status (OPEN|CLOSED), expiry_ts (unix seconds = validUpto),
extensions (count).
`audit_log` — ts, mode (MANUAL|AUTO), invoice_no, ewb_no, detail.
`settings` — key/value (`auto_extend` = "0"/"1", toggled live from UI).

Demo seed: 9 shipments positioned RELATIVE TO NOW (offsets −14h, −3h, +2.4h,
+6.8h, +15h, +22h, +41h, +5h-with-IOD-CLOSED, +68h) so every UI bucket is
populated on first run. Seed only when `SEED_DEMO_DATA=true` and table empty.

### HTTP API (stable contract — other systems may integrate against it)
```
GET  /                      dashboard HTML
GET  /api/shipments         all shipments + computed status + auto flag
GET  /api/lookup?q=         by invoice OR EWB no; also refreshes validity
                            from client.get_ewb() and syncs DB to portal value
POST /api/extend            {"q", "place"?, "pin"?, "remaining_km"?, "remarks"?}
POST /api/iod               {"invoice_no", "status": "OPEN"|"CLOSED"}
GET  /api/auto              watcher state; POST /api/auto {"enabled": bool}
GET  /api/logs              audit trail, newest first
```

### Auto-extend watcher (`app.py: watcher()`)
Daemon thread, loop every `AUTO_CHECK_INTERVAL_SECONDS` (default 60):
if setting `auto_extend`=="1", for each shipment with iod OPEN and status
WINDOW → `do_extend(mode="AUTO")` with the no-GPS defaults. Wrap the whole
iteration in try/except and log the error — the watcher must NEVER die.
All extension writes (manual + auto) go through the single `do_extend()`
routine so the audit log stays complete.

---

## 4. Config (.env) — the ONLY file edited to go live

See `.env.example` for the full annotated list. Key ones:
```
EWB_API_MODE=mock            # mock | gsp | nic
GSP_BASE_URL / GSP_CLIENT_ID / GSP_CLIENT_SECRET / GSP_GSTIN
GSP_EWB_USERNAME / GSP_EWB_PASSWORD   # created at ewaybillgst.gov.in → Registration → For GSP
NIC_BASE_URL / NIC_CLIENT_ID / NIC_CLIENT_SECRET / NIC_GSTIN
NIC_USERNAME / NIC_PASSWORD / NIC_PUBLIC_KEY_PATH
AUTO_EXTEND_ENABLED=false
AUTO_CHECK_INTERVAL_SECONDS=60
AUTO_REASON_CODE=99
AUTO_REASON_REMARKS=Transit delay
APP_PORT=8000
DB_PATH=./ewb.db
SEED_DEMO_DATA=true          # false in production
```
Credential acquisition (document, don't automate):
- GSP sandbox: free keys — MasterGST signup, or ClearTax/Vayana/Adaequare trials.
- NIC sandbox: free — email ewaybill.api.helpdesk@gmail.com from the
  registered email. Production: test-summary report to nicmof@nic.in + 4
  static-IP whitelisting, then ewaybillgst.gov.in → Registration → For API.

---

## 5. Build & run commands

```bash
pip install -r requirements.txt
cp .env.example .env                 # mock mode by default
python app.py                        # dev; serves http://localhost:8000
uvicorn app:app --host 0.0.0.0 --port 8000          # explicit
./run_tests.sh                       # end-to-end suite (starts its own server)
```

`run_tests.sh` must keep covering, and must pass before any commit:
1. lookup by invoice → found, correct status
2. extend inside window → ok, new expiry = midnight per distance math
3. extend >8h before expiry → rejected with window message
4. extend >8h after expiry → rejected with "fresh EWB" message
5. lookup unknown invoice → ok:false with message
6. auto ON → watcher extends all WINDOW + IOD-OPEN rows, SKIPS IOD CLOSED
7. board state consistent afterwards
8. GET / returns 200

For fast auto-trigger testing set `AUTO_CHECK_INTERVAL_SECONDS=3` temporarily.
Delete `ewb.db` to reseed demo data fresh around the current time.

---

## 6. Deployment

### Docker (preferred)
```bash
docker build -t ewb-tower .
docker run -d --name ewb --restart unless-stopped -p 8000:8000 \
  --env-file .env -v $(pwd)/data:/app/data ewb-tower
# set DB_PATH=/app/data/ewb.db in .env so the SQLite file persists
```

### Bare VM (Ubuntu) with systemd
```
/etc/systemd/system/ewb.service:
  [Unit]
  Description=EWB Control Tower
  After=network.target
  [Service]
  WorkingDirectory=/opt/ewb-app
  ExecStart=/usr/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
  Restart=always
  EnvironmentFile=/opt/ewb-app/.env
  [Install]
  WantedBy=multi-user.target

sudo systemctl enable --now ewb
```
Put nginx/caddy in front for TLS if exposed beyond the office LAN.

### Production checklist
- [ ] `SEED_DEMO_DATA=false`
- [ ] `EWB_API_MODE=gsp` (or nic) with real credentials in `.env`
- [ ] Server has a STATIC IP (mandatory for NIC direct-mode whitelisting)
- [ ] TMS sync job filling the `shipments` table (upsert on invoice_no;
      set iod_status=CLOSED when POD/IOD is captured)
- [ ] `AUTO_EXTEND_ENABLED` decided consciously (see §7)
- [ ] Backup cron for the SQLite file (or migrate to Postgres — keep the
      same schema; only `database.py` may change)
- [ ] Host timezone = IST (expiry math uses local midnight)

---

## 7. Guardrails for Claude Code — do NOT do these

1. Do not weaken or remove the ±8h window checks, in mock OR real backends.
2. Do not remove the editable location fields or the compliance warning from
   the UI, and do not hide auto-extensions from the audit log. If a tax
   officer questions an extension, the audit trail is our defence.
3. Do not auto-generate FRESH e-way bills for MISSED shipments. Generating a
   new EWB is a human decision (goods description, values, Part A liability).
   The system only flags "fresh EWB needed".
4. Do not commit `.env`, `ewb.db`, `nic_public_key.pem`, or any credential.
5. Do not change the adapter interface (`get_ewb` / `extend_validity`) or the
   EXTENDVALIDITY payload key names — external systems and NIC depend on them.
6. Do not silently swallow NIC/GSP error responses — always surface
   `message` + `raw` to the caller and the audit log.
7. Keep the app runnable with ZERO credentials in mock mode at all times;
   that is how ops training and demos work.
8. Any new feature that files data to NIC must be truthful-by-default:
   prefill is allowed; fabricating locations/distances beyond the documented
   no-GPS defaults is not.

## 8. Roadmap (build in this order when asked)
1. ~~TMS sync job (`sync_tms.py`): cron-safe upsert from company DB → shipments.~~ DONE.
2. Alerts: WhatsApp/SMS (Twilio/Gupshup) at T-24h, T-8h (window open), and on
   AUTO failure — failure alerts are critical, silence = penalty risk.
3. "Get EWB assigned to transporter" pull (by date+state) to auto-discover
   customer-generated EWBs we haven't keyed in.
4. Multi-branch auth (branch login, branch-scoped views).
5. Postgres migration once volume > ~50k shipments.
6. GPS ingestion — when a telematics feed arrives, replace the origin-default
   with last-known position and auto-compute remaining distance (haversine to
   destination pincode). The no-GPS defaults then become the fallback only.

Current build status, what's live vs. still mock-only, and open items are
tracked in [`STATUS.md`](./STATUS.md) — keep it in sync when roadmap items
land.
