"""
Xero Runner – entry point.
Run with: python app.py
"""
import os
import webbrowser

from flask import Flask

from config import (
    PORT,
    REDIRECT_URI,
    TOKEN_PATH,
    STATE_PATH,
    EXCEL_PATH,
    DATA_DIR,
    ensure_creds,
    get_scopes,
    LOG_PATH,
)
from log_utils import setup_logging
from xero_auth import XeroAuth, FileTokenStore
from xero_jobs import ensure_excel
from state_store import JsonStateStore
from routes import register_routes

# Bootstrap
client_id, client_secret = ensure_creds()
token_store = FileTokenStore(TOKEN_PATH)
state = JsonStateStore(STATE_PATH)
logger = setup_logging(LOG_PATH, name="xero_runner")

xero = XeroAuth(
    client_id=client_id,
    client_secret=client_secret,
    scopes=get_scopes(),
    redirect_uri=REDIRECT_URI,
    token_store=token_store,
)
ensure_excel(EXCEL_PATH)

# DB audit: app lifecycle (no secrets — client id/secret are never logged).
try:
    import integration_db_log

    integration_db_log.log_info(
        "Application startup: Flask app constructed; config and paths loaded. "
        "Next: register routes, then listen. If sync fails, check integration_log for correlation_id from API responses.",
        event_type="app.lifecycle.startup",
        module_name="app",
        function_name="<module>",
        status=integration_db_log.STATUS_SUCCESS,
        detail=(
            f"PORT={PORT}; REDIRECT_URI={REDIRECT_URI}; "
            f"DATA_DIR={DATA_DIR}; TOKEN_PATH={TOKEN_PATH}; EXCEL_PATH={EXCEL_PATH}; "
            f"STATE_PATH={STATE_PATH}; LOG_PATH={LOG_PATH}; "
            f"scopes_length={len(get_scopes())}; oauth_credentials_present=yes"
        ),
    )
except Exception:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "dev-xero-runner-flask-secret-change-me"
register_routes(app, xero, state, token_store, client_id, client_secret, logger)

if __name__ == "__main__":
    url = f"http://localhost:{PORT}"
    print(f"\nXero Runner running at {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host="127.0.0.1", port=PORT, debug=False)
