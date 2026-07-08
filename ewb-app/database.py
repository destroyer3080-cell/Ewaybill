"""SQLite schema, queries, and demo seed for the EWB Control Tower.

Every function opens and closes its own short-lived connection so the
watcher thread and FastAPI request threads never share a sqlite3.Connection
object (which is not safe across threads).
"""
import sqlite3
import time
from datetime import datetime, timedelta

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no    TEXT UNIQUE NOT NULL,
    ewb_no        TEXT UNIQUE NOT NULL,
    vehicle_no    TEXT NOT NULL,
    from_place    TEXT NOT NULL,
    from_pincode  TEXT NOT NULL,
    from_state    INTEGER NOT NULL,
    to_place      TEXT NOT NULL,
    to_pincode    TEXT NOT NULL,
    distance_km   REAL NOT NULL,
    iod_status    TEXT NOT NULL DEFAULT 'OPEN',
    expiry_ts     INTEGER NOT NULL,
    generated_ts  INTEGER NOT NULL,
    extensions    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    mode        TEXT NOT NULL,
    invoice_no  TEXT,
    ewb_no      TEXT,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        cur = conn.execute("SELECT value FROM settings WHERE key = 'auto_extend'")
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('auto_extend', ?)",
                ("1" if config.AUTO_EXTEND_ENABLED else "0",),
            )
            conn.commit()
    finally:
        conn.close()

    if config.SEED_DEMO_DATA:
        _seed_demo_data()


def _seed_demo_data():
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM shipments").fetchone()["n"]
        if count > 0:
            return

        now = time.time()
        # (invoice, ewb, vehicle, from_place, from_pin, from_state, to_place,
        #  to_pin, distance_km, offset_hours, iod_status)
        rows = [
            ("INV-1001", "321008990101", "KL43L8812", "Ernakulam", "682016", 32,
             "Coimbatore", "641001", 190, -14.0, "OPEN"),   # MISSED
            ("INV-1002", "321008990102", "KL07AB1234", "Kochi", "682001", 32,
             "Madurai", "625001", 320, -3.0, "OPEN"),       # WINDOW (past, still open)
            ("INV-1003", "321008990103", "KL01CD5678", "Kozhikode", "673001", 32,
             "Bengaluru", "560001", 420, 2.4, "OPEN"),      # WINDOW
            ("INV-1004", "321008990104", "KL10EF9012", "Thrissur", "680001", 32,
             "Chennai", "600001", 560, 6.8, "OPEN"),        # WINDOW (near edge)
            ("INV-1005", "321008990105", "KL05GH3456", "Palakkad", "678001", 32,
             "Hyderabad", "500001", 780, 15.0, "OPEN"),     # SOON
            ("INV-1006", "321008990106", "KL02IJ7890", "Kollam", "691001", 32,
             "Mangaluru", "575001", 350, 22.0, "OPEN"),     # SOON
            ("INV-1007", "321008990107", "KL08KL2345", "Alappuzha", "688001", 32,
             "Pune", "411001", 1180, 41.0, "OPEN"),         # WATCH
            ("INV-1008", "321008990108", "KL06MN6789", "Kottayam", "686001", 32,
             "Mumbai", "400001", 1350, 5.0, "CLOSED"),      # CLOSED (IOD done)
            ("INV-1009", "321008990109", "KL04OP0123", "Kannur", "670001", 32,
             "Goa", "403001", 610, 68.0, "OPEN"),           # OK
        ]

        for (invoice, ewb, vehicle, from_place, from_pin, from_state, to_place,
             to_pin, distance_km, offset_h, iod_status) in rows:
            expiry_ts = int(now + offset_h * 3600)
            # generated well before expiry so the 360-day ceiling is nowhere near
            generated_ts = int(now - 2 * 24 * 3600)
            conn.execute(
                """INSERT INTO shipments
                   (invoice_no, ewb_no, vehicle_no, from_place, from_pincode,
                    from_state, to_place, to_pincode, distance_km, iod_status,
                    expiry_ts, generated_ts, extensions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (invoice, ewb, vehicle, from_place, from_pin, from_state,
                 to_place, to_pin, distance_km, iod_status, expiry_ts,
                 generated_ts),
            )
        conn.commit()
    finally:
        conn.close()


def upsert_shipment_from_tms(record: dict) -> str:
    """Insert a new shipment or update its TMS-owned fields (vehicle, route,
    distance, IOD status) on invoice_no. EWB-portal-owned fields (expiry_ts,
    generated_ts, extensions) are never touched on an update — only
    /api/lookup and do_extend() may change those, so a TMS sync can never
    silently clobber an authoritative NIC validity with stale or blank data.

    For a brand-new invoice_no, `record` must also carry expiry_ts and
    generated_ts (sync_tms.py is responsible for sourcing these truthfully —
    from the TMS record if it captured them, or a live portal lookup —
    never fabricate them; see CLAUDE.md §7 rule 8).

    Returns "inserted" or "updated".
    """
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM shipments WHERE invoice_no = ?", (record["invoice_no"],)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE shipments SET
                     ewb_no = ?, vehicle_no = ?, from_place = ?, from_pincode = ?,
                     from_state = ?, to_place = ?, to_pincode = ?, distance_km = ?,
                     iod_status = ?
                   WHERE invoice_no = ?""",
                (record["ewb_no"], record["vehicle_no"], record["from_place"],
                 record["from_pincode"], record["from_state"], record["to_place"],
                 record["to_pincode"], record["distance_km"], record["iod_status"],
                 record["invoice_no"]),
            )
            conn.commit()
            return "updated"
        else:
            conn.execute(
                """INSERT INTO shipments
                   (invoice_no, ewb_no, vehicle_no, from_place, from_pincode,
                    from_state, to_place, to_pincode, distance_km, iod_status,
                    expiry_ts, generated_ts, extensions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (record["invoice_no"], record["ewb_no"], record["vehicle_no"],
                 record["from_place"], record["from_pincode"], record["from_state"],
                 record["to_place"], record["to_pincode"], record["distance_km"],
                 record["iod_status"], record["expiry_ts"], record["generated_ts"]),
            )
            conn.commit()
            return "inserted"
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def list_shipments():
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM shipments ORDER BY expiry_ts ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_shipment_by_invoice(invoice_no: str):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM shipments WHERE invoice_no = ?", (invoice_no,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_shipment_by_ewb(ewb_no: str):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM shipments WHERE ewb_no = ?", (str(ewb_no),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_shipment(q: str):
    """Lookup by invoice_no OR ewb_no."""
    s = get_shipment_by_invoice(q)
    if s:
        return s
    return get_shipment_by_ewb(q)


def set_expiry(ewb_no: str, expiry_ts: int, bump_extensions: bool = False):
    conn = _connect()
    try:
        if bump_extensions:
            conn.execute(
                "UPDATE shipments SET expiry_ts = ?, extensions = extensions + 1 "
                "WHERE ewb_no = ?",
                (int(expiry_ts), str(ewb_no)),
            )
        else:
            conn.execute(
                "UPDATE shipments SET expiry_ts = ? WHERE ewb_no = ?",
                (int(expiry_ts), str(ewb_no)),
            )
        conn.commit()
    finally:
        conn.close()


def set_iod_status(invoice_no: str, status: str):
    conn = _connect()
    try:
        conn.execute(
            "UPDATE shipments SET iod_status = ? WHERE invoice_no = ?",
            (status, invoice_no),
        )
        conn.commit()
    finally:
        conn.close()


def insert_audit(ts: float, mode: str, invoice_no: str, ewb_no: str, detail: str):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO audit_log (ts, mode, invoice_no, ewb_no, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(ts), mode, invoice_no, ewb_no, detail),
        )
        conn.commit()
    finally:
        conn.close()


def list_audit(limit: int = 500):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY ts DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
