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
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "INFO",
                    "oauth.auth.reset",
                    "User cleared stored tokens via /api/auth/reset; re-authorization required",
                    module_name="routes.auth_routes",
                    function_name="api_auth_reset",
                    status="OK",
                    detail=f"Token file removed if present: {TOKEN_PATH}; backup under {backup_dir}",
                    message="Next: user should open Authorize flow from the dashboard.",
                )
            except Exception:
                pass
            return jsonify({"ok": True, "message": "Token deleted. Re-authorize required."})
        except Exception as e:
            try:
                import integration_db_log

                integration_db_log.log_exception(
                    "Auth reset failed (file or backup error)",
                    e,
                    step_name="api_auth_reset",
                )
            except Exception:
                pass
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
        try:
            import integration_db_log

            integration_db_log.log_event(
                "INFO",
                "oauth.auth.started",
                "PKCE + state prepared; user will be redirected to Xero authorize URL",
                module_name="routes.auth_routes",
                function_name="api_auth_start",
                status="OK",
                detail=(
                    f"redirect_uri={REDIRECT_URI}; scopes_length={len(scopes)}; "
                    "auth_url returned to browser (tokens not in response body)."
                ),
                message="Next: browser opens Xero login; callback will exchange code for tokens.",
            )
        except Exception:
            pass
        return jsonify({"ok": True, "auth_url": auth_url, "redirect_uri": REDIRECT_URI, "scopes": scopes})

    @app.get("/callback")
    def callback():
        err = request.args.get("error")
        if err:
            logger.error("OAuth callback error: %s", err)
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "WARNING",
                    "oauth.callback.error",
                    f"OAuth redirect returned error query param: {err}",
                    module_name="routes.auth_routes",
                    function_name="callback",
                    status="FAILED",
                    detail="User may have denied consent or Xero returned an error. Retry auth from app.",
                )
            except Exception:
                pass
            return f"OAuth error: {err}", 400

        code = request.args.get("code")
        st = request.args.get("state")

        if not code:
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "WARNING",
                    "oauth.callback.missing_code",
                    "Callback reached without authorization code",
                    module_name="routes.auth_routes",
                    function_name="callback",
                    status="FAILED",
                )
            except Exception:
                pass
            return "Missing code", 400

        if not auth_session.get("state") or st != auth_session["state"]:
            logger.error("OAuth state mismatch (got=%s)", st)
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "WARNING",
                    "oauth.callback.state_mismatch",
                    "CSRF state does not match session; possible stale or parallel auth attempt",
                    module_name="routes.auth_routes",
                    function_name="callback",
                    status="FAILED",
                    detail="Restart authorization from the app to obtain a fresh state/PKCE pair.",
                )
            except Exception:
                pass
            return "State mismatch. Please restart auth from the app.", 400

        verifier = auth_session.get("verifier")
        if not verifier:
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "WARNING",
                    "oauth.callback.missing_verifier",
                    "PKCE verifier missing from session",
                    module_name="routes.auth_routes",
                    function_name="callback",
                    status="FAILED",
                )
            except Exception:
                pass
            return "Missing PKCE verifier. Please restart auth from the app.", 400

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        try:
            import integration_db_log

            integration_db_log.log_event(
                "INFO",
                "oauth.token.exchange.started",
                "POST to token endpoint with authorization_code (secrets not logged)",
                module_name="routes.auth_routes",
                function_name="callback",
                status="STARTED",
                request_url=TOKEN_URL,
                request_method="POST",
                detail="Using client basic auth and PKCE verifier; response will be parsed for expiry and scope only.",
            )
        except Exception:
            pass

        r = requests.post(TOKEN_URL, data=data, auth=(client_id, client_secret), timeout=30)
        if r.status_code != 200:
            logger.error("Token exchange failed (%s): %s", r.status_code, r.text)
            try:
                import integration_db_log

                integration_db_log.log_event(
                    "ERROR",
                    "oauth.token.exchange.failed",
                    f"Token endpoint returned HTTP {r.status_code}",
                    module_name="routes.auth_routes",
                    function_name="callback",
                    status="FAILED",
                    http_status_code=r.status_code,
                    response_summary=integration_db_log.sanitize_response_body(r.text, 1500),
                    detail="Verify client id/secret, redirect_uri, and that the auth code was not reused or expired.",
                )
            except Exception:
                pass
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
        try:
            import integration_db_log

            integration_db_log.log_event(
                "INFO",
                "oauth.token.exchange.completed",
                "Tokens written to disk; in-memory auth refreshed (no token values logged)",
                module_name="routes.auth_routes",
                function_name="callback",
                status="OK",
                detail=(
                    f"expires_in_s={expires_in}; token_path={TOKEN_PATH}; "
                    "Next: XeroAuth will call /connections to resolve tenant on first API use."
                ),
                record_count=None,
            )
        except Exception:
            pass

        return (
            "<html><body style='font-family: -apple-system, system-ui, sans-serif;'>"
            "<h3>✅ Authorised</h3>"
            "<p>Tokens saved. You can close this tab and return to the app.</p>"
            "<script>try{window.close();}catch(e){}</script>"
            "</body></html>"
        )
