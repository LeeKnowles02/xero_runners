import os, time, base64, hashlib, secrets, json, webbrowser
from threading import Thread

import requests
from flask import Flask, request
from dotenv import load_dotenv

TOKEN_URL = "https://identity.xero.com/connect/token"
AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"

PORT = 8000
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = os.getenv("XERO_SCOPES") or "offline_access accounting.journals.read accounting.contacts"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TOKEN_PATH = os.path.join(DATA_DIR, "xero_tokens.json")

def b64url_nopad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

def now() -> int:
    return int(time.time())

def pkce_pair():
    verifier = b64url_nopad(os.urandom(48))
    challenge = b64url_nopad(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge

def main():
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    client_id = (os.getenv("XERO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("XERO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Missing XERO_CLIENT_ID / XERO_CLIENT_SECRET in .env")

    os.makedirs(DATA_DIR, exist_ok=True)

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{AUTHORIZE_URL}"
        f"?response_type=code"
        f"&client_id={requests.utils.quote(client_id)}"
        f"&redirect_uri={requests.utils.quote(REDIRECT_URI, safe='')}"
        f"&scope={requests.utils.quote(SCOPES)}"
        f"&state={requests.utils.quote(state)}"
        f"&code_challenge={requests.utils.quote(challenge)}"
        f"&code_challenge_method=S256"
    )

    app = Flask(__name__)
    result = {"code": None, "state": None, "error": None}

    @app.route("/callback")
    def callback():
        err = request.args.get("error")
        if err:
            result["error"] = err
            return f"OAuth error: {err}", 400
        result["code"] = request.args.get("code")
        result["state"] = request.args.get("state")
        if result["state"] != state:
            result["error"] = "state_mismatch"
            return "State mismatch", 400
        return "Auth complete. You can close this window."

    print("\nOpen this URL and click Allow once:\n")
    print(auth_url)
    webbrowser.open(auth_url)

    t = Thread(target=lambda: app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False), daemon=True)
    t.start()

    start = now()
    while now() - start < 180:
        if result["error"]:
            raise RuntimeError(f"OAuth failed: {result['error']}")
        if result["code"]:
            break
        time.sleep(0.25)

    if not result["code"]:
        raise TimeoutError("Timed out waiting for OAuth callback.")

    data = {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": verifier,
    }

    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({r.status_code}): {r.text}")

    j = r.json()
    expires_in = int(j.get("expires_in", 1800))
    payload = {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token"),
        "expires_at": now() + expires_in - 30,
        "scope": j.get("scope"),
        "token_type": j.get("token_type"),
    }

    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n✅ Tokens saved: {TOKEN_PATH}")
    print("Next: run `python app.py` and use the buttons.")

if __name__ == "__main__":
    main()
