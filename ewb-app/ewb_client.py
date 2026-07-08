"""Three swappable EWB API backends behind one interface:

    client.get_ewb(ewb_no)          -> {"ok", "ewb_no", "valid_upto_ts", "status", "raw"}
    client.extend_validity(payload) -> {"ok", "new_valid_upto_ts", "message", "raw"}

Selection is via EWB_API_MODE=mock|gsp|nic in .env (see get_client()).
Adding a new backend = new class + one entry in get_client(). Nothing else
changes. Do NOT rename the EXTENDVALIDITY payload keys — NIC and any
integrating systems depend on them exactly as documented in CLAUDE.md §2.
"""
import base64
import json
import math
import time
from datetime import datetime, timedelta
from datetime import time as dtime

import requests

import config
import database as db


def _parse_nic_datetime(value):
    """NIC/GSP typically return validUpto as 'dd/mm/YYYY HH:MM:SS AM/PM'."""
    if not value:
        return None
    for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except (ValueError, TypeError):
            continue
    return None


class MockEWBClient:
    """Simulates NIC against the local DB and enforces every rule in
    CLAUDE.md §2 (extension window, max validity, day-ceiling math). Must
    always work with zero credentials — this is the default backend and
    what ops training/demos run against.

    This client is read/validate-only: it does NOT persist the new expiry.
    app.py's do_extend() is the single writer so the audit log stays
    complete for both manual and auto extensions (see CLAUDE.md §3).
    """

    WINDOW_SECONDS = 8 * 3600
    MAX_VALIDITY_SECONDS = 360 * 24 * 3600

    def get_ewb(self, ewb_no):
        s = db.get_shipment_by_ewb(ewb_no)
        if not s:
            return {
                "ok": False, "ewb_no": str(ewb_no), "valid_upto_ts": None,
                "status": None, "raw": {"message": "EWB not found"},
            }
        return {
            "ok": True,
            "ewb_no": s["ewb_no"],
            "valid_upto_ts": s["expiry_ts"],
            "status": "CLOSED" if s["iod_status"] == "CLOSED" else "ACTIVE",
            "raw": s,
        }

    def extend_validity(self, payload):
        ewb_no = str(payload.get("ewbNo"))
        s = db.get_shipment_by_ewb(ewb_no)
        if not s:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": "EWB not found", "raw": payload,
            }

        now = time.time()
        expiry = s["expiry_ts"]
        window_start = expiry - self.WINDOW_SECONDS
        window_end = expiry + self.WINDOW_SECONDS

        if now < window_start:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": (
                    "Extension window not open yet — extension is only allowed "
                    "within 8 hours of the current validUpto"
                ),
                "raw": payload,
            }
        if now > window_end:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": (
                    "Extension window missed — this EWB is dead, a fresh e-way "
                    "bill must be generated before the vehicle moves"
                ),
                "raw": payload,
            }

        remaining_km = payload.get("remainingDistance")
        if not remaining_km or remaining_km <= 0:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": "remainingDistance must be a positive number",
                "raw": payload,
            }

        days = math.ceil(remaining_km / 200)
        new_expiry_date = (datetime.now() + timedelta(days=days)).date()
        new_expiry_ts = int(datetime.combine(new_expiry_date, dtime(23, 59, 0)).timestamp())

        max_valid_ts = s["generated_ts"] + self.MAX_VALIDITY_SECONDS
        if new_expiry_ts > max_valid_ts:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": "Maximum total validity of 360 days from generation exceeded",
                "raw": payload,
            }

        return {
            "ok": True,
            "new_valid_upto_ts": new_expiry_ts,
            "message": f"Validity extended by {days} day(s)",
            "raw": {"payload": payload, "days_added": days},
        }


class GSPEWBClient:
    """Generic GSP/ASP REST backend (MasterGST-style paths). To adapt to a
    different GSP (ClearTax/Vayana/Adaequare), change ONLY this class.
    """

    TOKEN_REFRESH_AT = 5.5 * 3600

    def __init__(self):
        self.base_url = config.GSP_BASE_URL.rstrip("/")
        self.client_id = config.GSP_CLIENT_ID
        self.client_secret = config.GSP_CLIENT_SECRET
        self.gstin = config.GSP_GSTIN
        self.username = config.GSP_EWB_USERNAME
        self.password = config.GSP_EWB_PASSWORD
        self._authtoken = None
        self._token_ts = 0

    def _ensure_token(self):
        now = time.time()
        if self._authtoken and (now - self._token_ts) < self.TOKEN_REFRESH_AT:
            return self._authtoken
        resp = requests.post(
            f"{self.base_url}/authenticate",
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "gstin": self.gstin,
                "username": self.username,
                "password": self.password,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._authtoken = data.get("authtoken") or data.get("auth_token") or data.get("token")
        self._token_ts = now
        return self._authtoken

    def _headers(self):
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "gstin": self.gstin,
            "username": self.username,
            "authtoken": self._ensure_token(),
            "Content-Type": "application/json",
        }

    def get_ewb(self, ewb_no):
        try:
            resp = requests.get(
                f"{self.base_url}/GetEwayBill",
                headers=self._headers(),
                params={"ewbNo": ewb_no},
                timeout=30,
            )
            data = resp.json()
        except Exception as exc:
            return {
                "ok": False, "ewb_no": str(ewb_no), "valid_upto_ts": None,
                "status": None, "raw": {"error": str(exc)},
            }
        if not resp.ok or data.get("status") == "0" or data.get("error"):
            return {
                "ok": False, "ewb_no": str(ewb_no), "valid_upto_ts": None,
                "status": None, "raw": data,
            }
        return {
            "ok": True,
            "ewb_no": str(ewb_no),
            "valid_upto_ts": _parse_nic_datetime(data.get("validUpto")),
            "status": data.get("status"),
            "raw": data,
        }

    def extend_validity(self, payload):
        try:
            resp = requests.post(
                f"{self.base_url}/extendvalidity",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            data = resp.json()
        except Exception as exc:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": str(exc), "raw": {"error": str(exc)},
            }
        if not resp.ok or data.get("status") == "0" or data.get("error"):
            message = data.get("message") or data.get("error") or "extendvalidity failed"
            return {"ok": False, "new_valid_upto_ts": None, "message": message, "raw": data}
        return {
            "ok": True,
            "new_valid_upto_ts": _parse_nic_datetime(data.get("validUpto")),
            "message": data.get("message", "Extended"),
            "raw": data,
        }


class NICEWBClient:
    """Direct NIC v1.03 integration. Auth payload is base64->RSA(PKCS1_v1_5)
    encrypted with NIC's public key; the response's session encryption key
    (sek) flow and all subsequent request/response bodies are
    AES-256-ECB(sek), base64-encoded, wrapped in {"action": ..., "data": ...}.

    NOTE: exact endpoint paths and field names vary by the NIC onboarding
    doc version — verify against the current doc before production use
    (CLAUDE.md §3).
    """

    TOKEN_REFRESH_AT = 5.5 * 3600

    def __init__(self):
        self.base_url = config.NIC_BASE_URL.rstrip("/")
        self.client_id = config.NIC_CLIENT_ID
        self.client_secret = config.NIC_CLIENT_SECRET
        self.gstin = config.NIC_GSTIN
        self.username = config.NIC_USERNAME
        self.password = config.NIC_PASSWORD
        self.public_key_path = config.NIC_PUBLIC_KEY_PATH
        self._sek = None
        self._authtoken = None
        self._token_ts = 0

    def _load_public_key(self):
        from Crypto.PublicKey import RSA
        with open(self.public_key_path, "rb") as f:
            return RSA.import_key(f.read())

    def _rsa_encrypt(self, plaintext: bytes) -> str:
        from Crypto.Cipher import PKCS1_v1_5
        cipher = PKCS1_v1_5.new(self._load_public_key())
        return base64.b64encode(cipher.encrypt(plaintext)).decode()

    def _aes_encrypt(self, plaintext: bytes) -> str:
        from Crypto.Cipher import AES
        cipher = AES.new(self._sek, AES.MODE_ECB)
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len]) * pad_len
        return base64.b64encode(cipher.encrypt(padded)).decode()

    def _aes_decrypt(self, b64_ciphertext: str) -> bytes:
        from Crypto.Cipher import AES
        cipher = AES.new(self._sek, AES.MODE_ECB)
        decrypted = cipher.decrypt(base64.b64decode(b64_ciphertext))
        pad_len = decrypted[-1]
        return decrypted[:-pad_len]

    def _authenticate(self):
        from Crypto.Random import get_random_bytes
        app_key = get_random_bytes(32)
        auth_payload = {
            "action": "ACCESSTOKEN",
            "username": self.username,
            "password": self.password,
            "app_key": base64.b64encode(app_key).decode(),
        }
        encrypted_payload = self._rsa_encrypt(json.dumps(auth_payload).encode())
        resp = requests.post(
            f"{self.base_url}/authenticate",
            json={"action": "ACCESSTOKEN", "data": encrypted_payload},
            headers={
                "client-id": self.client_id,
                "client-secret": self.client_secret,
                "gstin": self.gstin,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._sek = app_key
        self._authtoken = data.get("authtoken") or data.get("sek")
        self._token_ts = time.time()

    def _ensure_token(self):
        if not self._authtoken or (time.time() - self._token_ts) >= self.TOKEN_REFRESH_AT:
            self._authenticate()

    def _headers(self):
        return {
            "client-id": self.client_id,
            "client-secret": self.client_secret,
            "gstin": self.gstin,
            "authtoken": self._authtoken,
            "Content-Type": "application/json",
        }

    def get_ewb(self, ewb_no):
        self._ensure_token()
        try:
            body = self._aes_encrypt(json.dumps({"ewbNo": ewb_no}).encode())
            resp = requests.post(
                f"{self.base_url}/GetEwayBill",
                headers=self._headers(),
                json={"action": "GETEWAYBILL", "data": body},
                timeout=30,
            )
            envelope = resp.json()
            decrypted = json.loads(self._aes_decrypt(envelope["data"]))
        except Exception as exc:
            return {
                "ok": False, "ewb_no": str(ewb_no), "valid_upto_ts": None,
                "status": None, "raw": {"error": str(exc)},
            }
        if decrypted.get("status") == "0" or decrypted.get("error"):
            return {
                "ok": False, "ewb_no": str(ewb_no), "valid_upto_ts": None,
                "status": None, "raw": decrypted,
            }
        return {
            "ok": True,
            "ewb_no": str(ewb_no),
            "valid_upto_ts": _parse_nic_datetime(decrypted.get("validUpto")),
            "status": decrypted.get("status"),
            "raw": decrypted,
        }

    def extend_validity(self, payload):
        self._ensure_token()
        try:
            body = self._aes_encrypt(json.dumps(payload).encode())
            resp = requests.post(
                f"{self.base_url}/extendvalidity",
                headers=self._headers(),
                json={"action": "EXTENDVALIDITY", "data": body},
                timeout=30,
            )
            envelope = resp.json()
            decrypted = json.loads(self._aes_decrypt(envelope["data"]))
        except Exception as exc:
            return {
                "ok": False, "new_valid_upto_ts": None,
                "message": str(exc), "raw": {"error": str(exc)},
            }
        if decrypted.get("status") == "0" or decrypted.get("error"):
            message = decrypted.get("message") or decrypted.get("error") or "EXTENDVALIDITY failed"
            return {"ok": False, "new_valid_upto_ts": None, "message": message, "raw": decrypted}
        return {
            "ok": True,
            "new_valid_upto_ts": _parse_nic_datetime(decrypted.get("validUpto")),
            "message": decrypted.get("message", "Extended"),
            "raw": decrypted,
        }


def get_client():
    mode = config.EWB_API_MODE
    if mode == "mock":
        return MockEWBClient()
    if mode == "gsp":
        return GSPEWBClient()
    if mode == "nic":
        return NICEWBClient()
    raise ValueError(f"Unknown EWB_API_MODE: {mode!r} (expected mock|gsp|nic)")
