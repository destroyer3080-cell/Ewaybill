"""FastAPI app: routes, status engine, and the auto-extend watcher thread.

See CLAUDE.md §3 for the status engine and API contract — both are treated
as stable and mirrored by the UI, so change them deliberately.
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import database as db
from ewb_client import get_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ewb")

app = FastAPI(title="EWB Control Tower")
client = get_client()

TEMPLATES_DIR = Path(__file__).parent / "templates"

# --- status engine (single source of truth; UI mirrors this) ---
WINDOW_SECONDS = 8 * 3600
SOON_SECONDS = 24 * 3600
WATCH_SECONDS = 48 * 3600


def compute_status(shipment: dict, now: float) -> str:
    if shipment["iod_status"] == "CLOSED":
        return "CLOSED"
    expiry = shipment["expiry_ts"]
    if expiry < now - WINDOW_SECONDS:
        return "MISSED"
    if abs(expiry - now) <= WINDOW_SECONDS:
        return "WINDOW"
    if expiry <= now + SOON_SECONDS:
        return "SOON"
    if expiry <= now + WATCH_SECONDS:
        return "WATCH"
    return "OK"


def build_payload(shipment: dict, place=None, pin=None, remaining_km=None,
                   remarks=None, reason_code=None) -> dict:
    """No-GPS defaults per CLAUDE.md §1: current location = FROM ship-point,
    remaining distance = full route distance, reason 99/"Transit delay".
    These are overridable — never hard-code them away from the caller.
    """
    ewb_no = shipment["ewb_no"]
    return {
        "ewbNo": int(ewb_no) if ewb_no.isdigit() else ewb_no,
        "vehicleNo": shipment["vehicle_no"],
        "fromPlace": place or shipment["from_place"],
        "fromState": shipment["from_state"],
        "fromPincode": int(pin) if pin else int(shipment["from_pincode"]),
        "remainingDistance": remaining_km if remaining_km is not None else shipment["distance_km"],
        "transMode": "1",
        "transDocNo": "",
        "transDocDate": "",
        "consignmentStatus": "M",
        "transitType": "",
        "addressLine1": "", "addressLine2": "", "addressLine3": "",
        "extnRsnCode": reason_code or config.AUTO_REASON_CODE,
        "extnRemarks": remarks or config.AUTO_REASON_REMARKS,
    }


def do_extend(shipment: dict, mode: str, place=None, pin=None,
              remaining_km=None, remarks=None) -> dict:
    """Single writer for every extension attempt (manual or auto, success or
    NIC rejection) so the audit log always stays complete (CLAUDE.md §1, §7).
    """
    payload = build_payload(shipment, place, pin, remaining_km, remarks)
    resp = client.extend_validity(payload)
    now = time.time()

    if resp["ok"] and resp.get("new_valid_upto_ts"):
        db.set_expiry(shipment["ewb_no"], resp["new_valid_upto_ts"], bump_extensions=True)

    detail = json.dumps({
        "payload": payload,
        "ok": resp["ok"],
        "message": resp.get("message"),
        "new_valid_upto_ts": resp.get("new_valid_upto_ts"),
        "raw": resp.get("raw"),
    })
    db.insert_audit(now, mode, shipment["invoice_no"], shipment["ewb_no"], detail)
    return resp


# --- auto-extend watcher ---
def watcher():
    while True:
        try:
            if db.get_setting("auto_extend", "0") == "1":
                now = time.time()
                for s in db.list_shipments():
                    if s["iod_status"] != "OPEN":
                        continue
                    if compute_status(s, now) == "WINDOW":
                        do_extend(s, mode="AUTO")
        except Exception:
            logger.exception("watcher iteration failed")
        time.sleep(config.AUTO_CHECK_INTERVAL_SECONDS)


@app.on_event("startup")
def on_startup():
    db.init_db()
    threading.Thread(target=watcher, daemon=True).start()
    logger.info("EWB Control Tower started (mode=%s)", config.EWB_API_MODE)


# --- request models ---
class ExtendRequest(BaseModel):
    q: str
    place: Optional[str] = None
    pin: Optional[str] = None
    remaining_km: Optional[float] = None
    remarks: Optional[str] = None


class IODRequest(BaseModel):
    invoice_no: str
    status: str


class AutoRequest(BaseModel):
    enabled: bool


# --- routes ---
@app.get("/")
def index():
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/api/shipments")
def api_shipments():
    now = time.time()
    out = []
    for s in db.list_shipments():
        s = dict(s)
        s["status"] = compute_status(s, now)
        out.append(s)
    return {
        "shipments": out,
        "auto_extend": db.get_setting("auto_extend", "0") == "1",
        "now": now,
    }


@app.get("/api/lookup")
def api_lookup(q: str):
    shipment = db.find_shipment(q)
    if not shipment:
        return {"ok": False, "message": "No shipment found for that invoice or EWB number"}

    portal = client.get_ewb(shipment["ewb_no"])
    if portal["ok"] and portal.get("valid_upto_ts"):
        db.set_expiry(shipment["ewb_no"], portal["valid_upto_ts"], bump_extensions=False)
        shipment = db.get_shipment_by_ewb(shipment["ewb_no"])

    now = time.time()
    return {
        "ok": True,
        "shipment": shipment,
        "status": compute_status(shipment, now),
        "portal": portal,
    }


@app.post("/api/extend")
def api_extend(req: ExtendRequest):
    shipment = db.find_shipment(req.q)
    if not shipment:
        raise HTTPException(status_code=404, detail="No shipment found for that invoice or EWB number")

    resp = do_extend(
        shipment, mode="MANUAL",
        place=req.place, pin=req.pin,
        remaining_km=req.remaining_km, remarks=req.remarks,
    )
    shipment = db.get_shipment_by_ewb(shipment["ewb_no"])
    return {
        "ok": resp["ok"],
        "message": resp.get("message"),
        "shipment": shipment,
        "status": compute_status(shipment, time.time()),
    }


@app.post("/api/iod")
def api_iod(req: IODRequest):
    if req.status not in ("OPEN", "CLOSED"):
        raise HTTPException(status_code=400, detail="status must be OPEN or CLOSED")
    shipment = db.get_shipment_by_invoice(req.invoice_no)
    if not shipment:
        raise HTTPException(status_code=404, detail="Unknown invoice_no")
    db.set_iod_status(req.invoice_no, req.status)
    return {"ok": True}


@app.get("/api/auto")
def api_auto_get():
    return {"enabled": db.get_setting("auto_extend", "0") == "1"}


@app.post("/api/auto")
def api_auto_set(req: AutoRequest):
    db.set_setting("auto_extend", "1" if req.enabled else "0")
    return {"enabled": req.enabled}


@app.get("/api/logs")
def api_logs():
    return {"logs": db.list_audit()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=config.APP_PORT, reload=False)
