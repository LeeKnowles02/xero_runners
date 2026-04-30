"""Paths, env, and constants for Xero Runner."""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TOKEN_PATH = os.path.join(DATA_DIR, "xero_tokens.json")
EXCEL_PATH = os.path.join(DATA_DIR, "xero_endpoints.xlsx")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
LOG_PATH = os.path.join(DATA_DIR, "app.log")

os.environ.setdefault("XERO_TOKEN_PATH", TOKEN_PATH)

PORT = 8000
REDIRECT_URI = f"http://localhost:{PORT}/callback"
DEFAULT_SCOPES = "offline_access accounting.journals.read accounting.contacts accounting.transactions accounting.settings"
AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"


def ensure_creds():
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    cid = (os.getenv("XERO_CLIENT_ID") or "").strip()
    csec = (os.getenv("XERO_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        raise RuntimeError("Missing XERO_CLIENT_ID / XERO_CLIENT_SECRET in .env")
    return cid, csec


def get_scopes() -> str:
    s = (os.getenv("XERO_SCOPES") or "").strip()
    return s if s else DEFAULT_SCOPES


def get_frankfurter_settings() -> dict:
    """Frankfurter API + provider label (load .env from project root)."""
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    return {
        # Default matches Frankfurter's working "latest" endpoint on api.frankfurter.dev.
        # Override in .env (e.g. https://api.frankfurter.dev/v2/rates/2026-04-24) if you use a dated path.
        "base_url": (
            os.getenv("FRANKFURTER_BASE_URL") or "https://api.frankfurter.dev/v1/latest"
        ).strip(),
        "base": (os.getenv("FRANKFURTER_BASE") or "USD").strip().upper()[:3],
        "quotes": (os.getenv("FRANKFURTER_QUOTES") or "ZAR,GBP,EUR").strip(),
        "provider": (os.getenv("FRANKFURTER_PROVIDER") or "ECB").strip() or None,
    }
