"""
Xero Runner – entry point.
Run with: python app.py
"""
import webbrowser

from flask import Flask

from config import (
    PORT,
    REDIRECT_URI,
    TOKEN_PATH,
    STATE_PATH,
    EXCEL_PATH,
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

app = Flask(__name__)
register_routes(app, xero, state, token_store, client_id, client_secret, logger)

if __name__ == "__main__":
    url = f"http://localhost:{PORT}"
    print(f"\nXero Runner running at {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host="127.0.0.1", port=PORT, debug=False)
