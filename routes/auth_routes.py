"""Auth routes: reset, start, callback."""
import json
import os
import secrets
import time

import requests
from flask import request, jsonify

from config import DATA_DIR, TOKEN_PATH, REDIRECT_URI, TOKEN_URL, AUTHORIZE_URL, get_scopes
from auth import pkce_pair, auth_session
from xero_jobs import backup_file


def register_auth_routes(app, xero, token_store, client_id, client_secret, logger):
    @app.post("/api/auth/reset")
    def api_auth_reset():
        try:
            backup_dir = os.path.join(DATA_DIR, "backups")
            backup_file(TOKEN_PATH, backup_dir, "tokens_before_reset")

            if os.path.exists(TOKEN_PATH):
                os.remove(TOKEN_PATH)

            xero.tokens = None
            xero.tenant_id = None

            logger.info("Auth reset: token deleted (%s)", TOKEN_PATH)
            return jsonify({"ok": True, "message": "Token deleted. Re-authorize required."})
        except Exception as e:
            logger.exception("Auth reset failed")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.get("/api/auth/start")
    def api_auth_start():
        verifier, challenge = pkce_pair()
        st = secrets.token_urlsafe(16)
        scopes = get_scopes()

        auth_session["verifier"] = verifier
        auth_session["state"] = st
        auth_session["created_at"] = int(time.time())
        auth_session["scopes"] = scopes

        auth_url = (
            f"{AUTHORIZE_URL}"
            f"?response_type=code"
            f"&client_id={requests.utils.quote(client_id)}"
            f"&redirect_uri={requests.utils.quote(REDIRECT_URI, safe='')}"
            f"&scope={requests.utils.quote(scopes)}"
            f"&state={requests.utils.quote(st)}"
            f"&code_challenge={requests.utils.quote(challenge)}"
            f"&code_challenge_method=S256"
        )

        logger.info("Auth start generated (scopes=%s)", scopes)
        return jsonify({"ok": True, "auth_url": auth_url, "redirect_uri": REDIRECT_URI, "scopes": scopes})

    @app.get("/callback")
    def callback():
        err = request.args.get("error")
        if err:
            logger.error("OAuth callback error: %s", err)
            return f"OAuth error: {err}", 400

        code = request.args.get("code")
        st = request.args.get("state")

        if not code:
            return "Missing code", 400

        if not auth_session.get("state") or st != auth_session["state"]:
            logger.error("OAuth state mismatch (got=%s)", st)
            return "State mismatch. Please restart auth from the app.", 400

        verifier = auth_session.get("verifier")
        if not verifier:
            return "Missing PKCE verifier. Please restart auth from the app.", 400

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        r = requests.post(TOKEN_URL, data=data, auth=(client_id, client_secret), timeout=30)
        if r.status_code != 200:
            logger.error("Token exchange failed (%s): %s", r.status_code, r.text)
            return f"Token exchange failed ({r.status_code}). Check logs.", 400

        j = r.json()
        expires_in = int(j.get("expires_in", 1800))
        payload = {
            "access_token": j["access_token"],
            "refresh_token": j.get("refresh_token"),
            "expires_at": int(time.time()) + expires_in - 30,
            "scope": j.get("scope"),
            "token_type": j.get("token_type"),
        }

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        xero.tokens = token_store.load()
        xero.tenant_id = None

        logger.info("Token exchange OK; tokens saved to %s", TOKEN_PATH)

        return (
            "<html><body style='font-family: -apple-system, system-ui, sans-serif;'>"
            "<h3>✅ Authorised</h3>"
            "<p>Tokens saved. You can close this tab and return to the app.</p>"
            "<script>try{window.close();}catch(e){}</script>"
            "</body></html>"
        )
