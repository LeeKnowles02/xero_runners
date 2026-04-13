#!/usr/bin/env python3

import os
import json
import time
import threading
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import requests

TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"

logger = logging.getLogger("xero_runner.xero_auth")


def _now() -> int:
    return int(time.time())


@dataclass
class XeroTokens:
    access_token: str
    refresh_token: Optional[str]
    expires_at: int
    scope: Optional[str] = None
    token_type: Optional[str] = None


class FileTokenStore:
    """Local token store for a Mac single-user setup."""
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> Optional[XeroTokens]:
        with self._lock:
            if not os.path.exists(self.path):
                return None
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return XeroTokens(
                access_token=raw["access_token"],
                refresh_token=raw.get("refresh_token"),
                expires_at=int(raw["expires_at"]),
                scope=raw.get("scope"),
                token_type=raw.get("token_type"),
            )

    def save(self, tokens: XeroTokens) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(tokens.__dict__, f, indent=2)
            os.replace(tmp, self.path)


class XeroAuth:
    """
    Token manager:
    - refreshes silently
    - obtains tenantId from /connections
    """
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: str,
        redirect_uri: str,
        token_store: FileTokenStore,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.redirect_uri = redirect_uri
        self.token_store = token_store

        self.tokens: Optional[XeroTokens] = self.token_store.load()
        self.tenant_id: Optional[str] = None
        try:
            import integration_db_log

            if self.tokens:
                integration_db_log.log_info(
                    "OAuth token file loaded; access token present (value not logged)",
                    event_type="auth.token.loaded",
                    module_name="xero_auth",
                    function_name="XeroAuth.__init__",
                    detail=f"token_path={self.token_store.path}; expires_at_epoch={self.tokens.expires_at}",
                )
            else:
                integration_db_log.log_warning(
                    "No token file or empty tokens — authorize via Dashboard → Re-authorize",
                    event_type="auth.token.missing",
                    module_name="xero_auth",
                    function_name="XeroAuth.__init__",
                    detail=f"token_path={self.token_store.path}",
                )
        except Exception:
            pass

    def ensure_valid_access_token(self) -> str:
        if not self.tokens:
            try:
                import integration_db_log

                integration_db_log.log_error(
                    "Cannot call Xero API: no tokens on disk. Next: complete OAuth (Re-authorize).",
                    event_type="auth.token.missing",
                    module_name="xero_auth",
                    function_name="ensure_valid_access_token",
                )
            except Exception:
                pass
            raise RuntimeError("No tokens found. Do interactive auth first.")
        if _now() >= self.tokens.expires_at:
            logger.info("Access token expired; refreshing")
            try:
                import integration_db_log

                integration_db_log.log_info(
                    "Access token expired — calling refresh() before API use",
                    event_type="auth.token.expired",
                    module_name="xero_auth",
                    function_name="ensure_valid_access_token",
                    detail=f"expires_at_epoch={self.tokens.expires_at}; now_epoch={_now()}",
                )
            except Exception:
                pass
            self.refresh()
        return self.tokens.access_token

    def refresh(self) -> XeroTokens:
        if not self.tokens or not self.tokens.refresh_token:
            try:
                import integration_db_log

                integration_db_log.log_error(
                    "Refresh aborted: no refresh_token in store — full re-auth required",
                    event_type="auth.token.refresh.failed",
                    module_name="xero_auth",
                    function_name="refresh",
                )
            except Exception:
                pass
            raise RuntimeError("No refresh token available. Re-auth required.")

        try:
            import integration_db_log

            integration_db_log.log_info(
                "Token refresh started: POST to identity.xero.com/connect/token (refresh_token redacted in logs)",
                event_type="auth.token.refresh.started",
                module_name="xero_auth",
                function_name="refresh",
                request_url=TOKEN_URL,
                request_method="POST",
            )
        except Exception:
            pass

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens.refresh_token,
        }
        r = requests.post(
            TOKEN_URL,
            data=data,
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        if r.status_code != 200:
            try:
                import integration_db_log

                integration_db_log.log_error(
                    f"Token refresh HTTP error: status={r.status_code}",
                    event_type="auth.token.refresh.failed",
                    module_name="xero_auth",
                    function_name="refresh",
                    http_status_code=r.status_code,
                    response_body_safe=integration_db_log.sanitize_response_body(r.text[:4000]),
                    detail="Check XERO_CLIENT_ID/SECRET, refresh_token validity, and clock skew",
                )
            except Exception:
                pass
            raise RuntimeError(f"Refresh failed ({r.status_code}): {r.text}")

        j = r.json()
        expires_in = int(j.get("expires_in", 1800))

        self.tokens = XeroTokens(
            access_token=j["access_token"],
            refresh_token=j.get("refresh_token") or self.tokens.refresh_token,
            expires_at=_now() + expires_in - 30,
            scope=j.get("scope"),
            token_type=j.get("token_type"),
        )
        self.token_store.save(self.tokens)
        logger.info("Token refresh OK (expires_in=%s)", expires_in)
        try:
            import integration_db_log

            integration_db_log.log_info(
                f"Token refresh completed; new access token saved; expires_in={expires_in}s",
                event_type="auth.token.refresh.completed",
                module_name="xero_auth",
                function_name="refresh",
                status="OK",
                duration_ms=None,
                detail="Tokens persisted to disk; Authorization header not logged",
            )
        except Exception:
            pass
        return self.tokens

    def get_connections(self) -> List[Dict[str, Any]]:
        try:
            import integration_db_log

            integration_db_log.log_info(
                "Fetching Xero tenant connections: GET api.xero.com/connections",
                event_type="auth.connections.started",
                module_name="xero_auth",
                function_name="get_connections",
                request_url=CONNECTIONS_URL,
                request_method="GET",
            )
        except Exception:
            pass
        token = self.ensure_valid_access_token()
        r = requests.get(
            CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            try:
                import integration_db_log

                integration_db_log.log_error(
                    f"/connections failed with HTTP {r.status_code}",
                    event_type="auth.connections.failed",
                    module_name="xero_auth",
                    function_name="get_connections",
                    http_status_code=r.status_code,
                    response_body_safe=integration_db_log.sanitize_response_body(r.text[:2000]),
                )
            except Exception:
                pass
            raise RuntimeError(f"/connections failed ({r.status_code}): {r.text}")
        data = r.json()
        try:
            import integration_db_log

            integration_db_log.log_info(
                f"Received {len(data)} connection(s) from Xero",
                event_type="auth.connections.completed",
                module_name="xero_auth",
                function_name="get_connections",
                record_count=len(data),
                status="OK",
                payload_summary=integration_db_log.payload_summary_from_obj(
                    [
                        {"tenantId": c.get("tenantId"), "tenantName": c.get("tenantName"), "tenantType": c.get("tenantType")}
                        for c in (data[:5] if isinstance(data, list) else [])
                    ]
                ),
            )
        except Exception:
            pass
        return data

    def ensure_tenant(self) -> str:
        if self.tenant_id:
            try:
                import integration_db_log

                integration_db_log.set_log_context(tenant_id=self.tenant_id)
            except Exception:
                pass
            return self.tenant_id
        conns = self.get_connections()
        if not conns:
            try:
                import integration_db_log

                integration_db_log.log_error(
                    "No Xero organisations returned — check app permissions and connections",
                    event_type="auth.tenant.none",
                    module_name="xero_auth",
                    function_name="ensure_tenant",
                )
            except Exception:
                pass
            raise RuntimeError("No tenants returned from /connections.")
        self.tenant_id = conns[0]["tenantId"]
        tname = conns[0].get("tenantName") or conns[0].get("TenantName")
        logger.info("Tenant selected: %s", self.tenant_id)
        try:
            import integration_db_log

            integration_db_log.set_log_context(tenant_id=self.tenant_id)
            integration_db_log.log_info(
                f"Active tenant resolved: tenant_id={self.tenant_id}; tenant_name={tname}",
                event_type="auth.tenant.selected",
                module_name="xero_auth",
                function_name="ensure_tenant",
                tenant_id=self.tenant_id,
                xero_tenant_name=((tname or "")[:512]) or None,
                detail="First connection in list is used; check Xero connections if wrong org",
            )
        except Exception:
            pass
        return self.tenant_id

    def headers(self) -> Dict[str, str]:
        token = self.ensure_valid_access_token()
        tenant_id = self.ensure_tenant()
        try:
            import integration_db_log

            integration_db_log.set_log_context(tenant_id=tenant_id)
            integration_db_log.log_debug(
                "Built Xero API headers: xero-tenant-id set; Bearer token not logged",
                event_type="auth.headers.ready",
                module_name="xero_auth",
                function_name="headers",
                tenant_id=tenant_id,
            )
        except Exception:
            pass
        return {
            "Authorization": f"Bearer {token}",
            "xero-tenant-id": tenant_id,
            "Accept": "application/json",
        }


# ---------------------------
# Helpers for long-running jobs
# ---------------------------

def default_token_path() -> str:
    """
    Default token path for xero_runner.
    Override by setting env var XERO_TOKEN_PATH.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get(
        "XERO_TOKEN_PATH",
        os.path.join(base_dir, "data", "xero_tokens.json"),
    )


def refresh_token_file_inplace(
    token_path: str,
    client_id: str,
    client_secret: str,
) -> XeroTokens:
    """
    Refreshes the access token using refresh_token from the token file,
    then writes the updated tokens back to the SAME file.
    """
    store = FileTokenStore(token_path)
    tokens = store.load()
    if not tokens or not tokens.refresh_token:
        raise RuntimeError(f"No refresh_token available in token file: {token_path}")

    data = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
    r = requests.post(TOKEN_URL, data=data, auth=(client_id, client_secret), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Refresh failed ({r.status_code}): {r.text}")

    j = r.json()
    expires_in = int(j.get("expires_in", 1800))

    new_tokens = XeroTokens(
        access_token=j["access_token"],
        refresh_token=j.get("refresh_token") or tokens.refresh_token,
        expires_at=_now() + expires_in - 30,
        scope=j.get("scope"),
        token_type=j.get("token_type"),
    )
    store.save(new_tokens)
    logger.info("Token file refresh OK (expires_in=%s) path=%s", expires_in, token_path)
    return new_tokens


def headers_from_token_file(
    tenant_id: str,
    token_path: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, str]:
    """
    Rebuild API headers by re-reading the stored token file.

    If the access token is expired AND client credentials are available,
    this will refresh the token IN PLACE and then build headers.
    """
    path = token_path or default_token_path()
    store = FileTokenStore(path)
    tokens = store.load()
    if not tokens or not tokens.access_token:
        raise RuntimeError(f"No access token in token file: {path}")

    if _now() >= int(tokens.expires_at):
        cid = client_id or os.environ.get("XERO_CLIENT_ID")
        csec = client_secret or os.environ.get("XERO_CLIENT_SECRET")
        if cid and csec:
            tokens = refresh_token_file_inplace(path, cid, csec)

    return {
        "Authorization": f"Bearer {tokens.access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
    }