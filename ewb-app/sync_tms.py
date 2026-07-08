"""Cron-safe TMS -> shipments sync job (CLAUDE.md §6, §8 roadmap item 1).

Pulls shipment records from the company TMS — either a REST API or CSV
exports dropped in a watch directory — and upserts them into the local
`shipments` table on invoice_no. Only TMS-owned fields (vehicle, route,
distance, IOD status) are written on an update; EWB validity (expiry_ts /
generated_ts / extensions) is never touched here, so a sync run can never
clobber an authoritative NIC value with stale or blank data. A brand-new
invoice_no needs a validity to seed the row — sourced from the TMS record
if it captured one (valid_upto / generated_at columns), otherwise from a
live portal lookup by ewb_no. If neither is available the row is skipped
with a clear warning rather than fabricated (CLAUDE.md §7 rule 8).

Usage:
    python sync_tms.py                  # run configured TMS_SYNC_MODE once
    python sync_tms.py --mode api       # force an API pull regardless of .env
    python sync_tms.py --mode csv       # sweep TMS_CSV_WATCH_DIR for *.csv
    python sync_tms.py --csv FILE       # one-off import of a single CSV file
    python sync_tms.py --dry-run        # validate and report, write nothing

CSV columns (header row required): invoice_no, ewb_no, vehicle_no,
from_place, from_pincode, from_state, to_place, to_pincode, distance_km,
iod_status, valid_upto, generated_at. The last two are optional and only
consulted when inserting a shipment for the first time; accepted formats
are epoch seconds or "YYYY-MM-DD[THH:MM:SS]" / "DD/MM/YYYY[ HH:MM:SS]".

API mode expects the same field names as JSON, as a top-level array or
wrapped under "shipments" / "data" / "results".

Exit codes: 0 = clean run, 1 = one or more records failed, 2 = bad
configuration, 3 = another sync_tms.py run is already in progress.
"""
import argparse
import csv
import fcntl
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import config
import database as db
from ewb_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_tms")

REQUIRED_FIELDS = [
    "invoice_no", "ewb_no", "vehicle_no", "from_place",
    "from_pincode", "from_state", "to_place", "to_pincode", "distance_km",
]


# --- record normalization (shared by both sources) ---
def _parse_datetime_field(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip()
    if value.isdigit():
        return int(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError(f"unrecognized date/time value: {value!r}")


def normalize_record(raw: dict) -> dict:
    missing = [f for f in REQUIRED_FIELDS if not str(raw.get(f, "")).strip()]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    iod_status = str(raw.get("iod_status") or "OPEN").strip().upper()
    if iod_status not in ("OPEN", "CLOSED"):
        raise ValueError(f"iod_status must be OPEN or CLOSED, got {iod_status!r}")

    try:
        distance_km = float(raw["distance_km"])
        from_state = int(raw["from_state"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric field: {exc}")
    if distance_km <= 0:
        raise ValueError("distance_km must be > 0")

    record = {
        "invoice_no": str(raw["invoice_no"]).strip(),
        "ewb_no": str(raw["ewb_no"]).strip(),
        "vehicle_no": str(raw["vehicle_no"]).strip(),
        "from_place": str(raw["from_place"]).strip(),
        "from_pincode": str(raw["from_pincode"]).strip(),
        "from_state": from_state,
        "to_place": str(raw["to_place"]).strip(),
        "to_pincode": str(raw["to_pincode"]).strip(),
        "distance_km": distance_km,
        "iod_status": iod_status,
    }

    valid_upto = _parse_datetime_field(raw.get("valid_upto"))
    if valid_upto is not None:
        generated_at = _parse_datetime_field(raw.get("generated_at"))
        record["expiry_ts"] = valid_upto
        # Only used as a soft ceiling for the 360-day max-validity check —
        # never affects the compliance-critical ±8h extension window. An
        # unknown generation date defaults to "now", which only ever makes
        # that ceiling check MORE permissive, never fabricates a rejection.
        record["generated_ts"] = generated_at if generated_at is not None else int(time.time())

    return record


def sync_record(raw: dict, client, dry_run: bool = False) -> str:
    record = normalize_record(raw)
    existing = db.get_shipment_by_invoice(record["invoice_no"])

    if not existing and "expiry_ts" not in record:
        portal = client.get_ewb(record["ewb_no"])
        if portal.get("ok") and portal.get("valid_upto_ts"):
            record["expiry_ts"] = portal["valid_upto_ts"]
            record["generated_ts"] = int(time.time())
        else:
            raise ValueError(
                f"no EWB validity available for new invoice {record['invoice_no']} "
                f"(ewb {record['ewb_no']}) — TMS record lacks valid_upto and the "
                f"configured portal ({config.EWB_API_MODE}) has no matching EWB"
            )

    if dry_run:
        return "would-insert" if not existing else "would-update"
    return db.upsert_shipment_from_tms(record)


def run_sync(rows, client, dry_run: bool = False):
    counts = {}
    errors = []
    for i, raw in enumerate(rows, start=1):
        invoice_hint = str(raw.get("invoice_no") or f"<row {i}>")
        try:
            outcome = sync_record(raw, client, dry_run=dry_run)
            counts[outcome] = counts.get(outcome, 0) + 1
            logger.info("%s: %s", invoice_hint, outcome)
        except Exception as exc:
            counts["error"] = counts.get("error", 0) + 1
            errors.append((invoice_hint, str(exc)))
            logger.error("%s: FAILED — %s", invoice_hint, exc)
    return counts, errors


# --- CSV source ---
def read_csv_records(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def _move(path: Path, dest_dir: Path):
    dest = dest_dir / f"{path.stem}.{int(time.time())}{path.suffix}"
    path.rename(dest)


def run_one_csv_file(path: str, client, dry_run: bool = False):
    rows = list(read_csv_records(path))
    return run_sync(rows, client, dry_run=dry_run)


def sweep_csv_dir(client, dry_run: bool = False):
    watch_dir = Path(config.TMS_CSV_WATCH_DIR)
    archive_dir = Path(config.TMS_CSV_ARCHIVE_DIR)
    error_dir = Path(config.TMS_CSV_ERROR_DIR)
    watch_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
        error_dir.mkdir(parents=True, exist_ok=True)

    total_counts = {}
    total_errors = []
    csv_files = sorted(watch_dir.glob("*.csv"))
    if not csv_files:
        logger.info("no CSV files found in %s", watch_dir)

    for csv_path in csv_files:
        logger.info("processing %s", csv_path.name)
        try:
            rows = list(read_csv_records(csv_path))
        except Exception as exc:
            logger.error("%s: unreadable CSV — %s", csv_path.name, exc)
            total_errors.append((csv_path.name, f"unreadable CSV: {exc}"))
            total_counts["error"] = total_counts.get("error", 0) + 1
            if not dry_run:
                _move(csv_path, error_dir)
            continue

        counts, errors = run_sync(rows, client, dry_run=dry_run)
        for k, v in counts.items():
            total_counts[k] = total_counts.get(k, 0) + v
        total_errors.extend(errors)

        if not dry_run:
            _move(csv_path, error_dir if errors else archive_dir)

    return total_counts, total_errors


# --- API source ---
def fetch_api_records():
    if not config.TMS_API_URL:
        raise RuntimeError("TMS_API_URL is not configured")
    headers = {}
    if config.TMS_API_KEY:
        headers["Authorization"] = f"Bearer {config.TMS_API_KEY}"
    resp = requests.get(config.TMS_API_URL, headers=headers, timeout=config.TMS_API_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("shipments") or data.get("data") or data.get("results") or []
    return data


# --- locking (cron-safe: never let two runs stomp on each other) ---
def acquire_lock():
    lock_file = open(config.TMS_SYNC_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file


def main():
    parser = argparse.ArgumentParser(description="Sync shipments from the TMS into the EWB Control Tower DB.")
    parser.add_argument("--mode", choices=["api", "csv"], help="override TMS_SYNC_MODE from .env")
    parser.add_argument("--csv", metavar="FILE", help="one-off import of a single CSV file (no watch-dir sweep or archiving)")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing to the DB")
    args = parser.parse_args()

    db.init_db()
    client = get_client()

    lock = acquire_lock()
    if lock is None:
        logger.warning("another sync_tms.py run is already in progress — exiting")
        sys.exit(3)

    try:
        if args.csv:
            counts, errors = run_one_csv_file(args.csv, client, dry_run=args.dry_run)
        else:
            mode = args.mode or config.TMS_SYNC_MODE
            if mode == "api":
                try:
                    rows = fetch_api_records()
                except Exception as exc:
                    logger.error("TMS API fetch failed: %s", exc)
                    sys.exit(2)
                counts, errors = run_sync(rows, client, dry_run=args.dry_run)
            elif mode == "csv":
                counts, errors = sweep_csv_dir(client, dry_run=args.dry_run)
            else:
                logger.error("unknown TMS_SYNC_MODE=%r (expected api|csv)", mode)
                sys.exit(2)
    finally:
        lock.close()

    logger.info("sync complete: %s", counts or "nothing to do")
    if errors:
        logger.warning("%d record(s) failed:", len(errors))
        for invoice, msg in errors:
            logger.warning("  %s: %s", invoice, msg)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
