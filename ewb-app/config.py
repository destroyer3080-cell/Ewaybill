"""Loads configuration from .env. See .env.example for the full annotated list."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- backend selection ---
EWB_API_MODE = os.getenv("EWB_API_MODE", "mock").strip().lower()  # mock | gsp | nic

# --- GSP/ASP backend ---
GSP_BASE_URL = os.getenv("GSP_BASE_URL", "")
GSP_CLIENT_ID = os.getenv("GSP_CLIENT_ID", "")
GSP_CLIENT_SECRET = os.getenv("GSP_CLIENT_SECRET", "")
GSP_GSTIN = os.getenv("GSP_GSTIN", "")
GSP_EWB_USERNAME = os.getenv("GSP_EWB_USERNAME", "")
GSP_EWB_PASSWORD = os.getenv("GSP_EWB_PASSWORD", "")

# --- NIC direct backend ---
NIC_BASE_URL = os.getenv("NIC_BASE_URL", "")
NIC_CLIENT_ID = os.getenv("NIC_CLIENT_ID", "")
NIC_CLIENT_SECRET = os.getenv("NIC_CLIENT_SECRET", "")
NIC_GSTIN = os.getenv("NIC_GSTIN", "")
NIC_USERNAME = os.getenv("NIC_USERNAME", "")
NIC_PASSWORD = os.getenv("NIC_PASSWORD", "")
NIC_PUBLIC_KEY_PATH = os.getenv("NIC_PUBLIC_KEY_PATH", "")

# --- auto-extend watcher ---
AUTO_EXTEND_ENABLED = _bool("AUTO_EXTEND_ENABLED", "false")
AUTO_CHECK_INTERVAL_SECONDS = int(os.getenv("AUTO_CHECK_INTERVAL_SECONDS", "60"))
AUTO_REASON_CODE = int(os.getenv("AUTO_REASON_CODE", "99"))
AUTO_REASON_REMARKS = os.getenv("AUTO_REASON_REMARKS", "Transit delay")

# --- app ---
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DB_PATH = os.getenv("DB_PATH", "./ewb.db")
SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", "true")

# --- TMS sync job (sync_tms.py) ---
TMS_SYNC_MODE = os.getenv("TMS_SYNC_MODE", "csv").strip().lower()  # api | csv
TMS_API_URL = os.getenv("TMS_API_URL", "")
TMS_API_KEY = os.getenv("TMS_API_KEY", "")
TMS_API_TIMEOUT_SECONDS = int(os.getenv("TMS_API_TIMEOUT_SECONDS", "30"))
TMS_CSV_WATCH_DIR = os.getenv("TMS_CSV_WATCH_DIR", "./tms_incoming")
TMS_CSV_ARCHIVE_DIR = os.getenv("TMS_CSV_ARCHIVE_DIR", "./tms_processed")
TMS_CSV_ERROR_DIR = os.getenv("TMS_CSV_ERROR_DIR", "./tms_errors")
TMS_SYNC_LOCK_PATH = os.getenv("TMS_SYNC_LOCK_PATH", "./sync_tms.lock")
