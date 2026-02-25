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
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(tokens.__dict__, f, indent=2)


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

    def ensure_valid_access_token(self) -> str:
        if not self.tokens:
            raise RuntimeError("No tokens found. Do interactive auth first.")
        if _now() >= self.tokens.expires_at:
            logger.info("Access token expired; refreshing")
            self.refresh()
        return self.tokens.access_token

    def refresh(self) -> XeroTokens:
        if not self.tokens or not self.tokens.refresh_token:
            raise RuntimeError("No refresh token available. Re-auth required.")

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
            raise RuntimeError(f"Refresh failed ({r.status_code}): {r.text}")

        j = r.json()
        expires_in = int(j.get("expires_in", 1800))

        self.tokens = XeroTokens(
            access_token=j["access_token"],
            refresh_token=j.get("refresh_token"),
            expires_at=_now() + expires_in - 30,
            scope=j.get("scope"),
            token_type=j.get("token_type"),
        )
        self.token_store.save(self.tokens)
        logger.info("Token refresh OK (expires_in=%s)", expires_in)
        return self.tokens

    def get_connections(self) -> List[Dict[str, Any]]:
        token = self.ensure_valid_access_token()
        r = requests.get(
            CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"/connections failed ({r.status_code}): {r.text}")
        return r.json()

    def ensure_tenant(self) -> str:
        if self.tenant_id:
            return self.tenant_id
        conns = self.get_connections()
        if not conns:
            raise RuntimeError("No tenants returned from /connections.")
        self.tenant_id = conns[0]["tenantId"]
        logger.info("Tenant selected: %s", self.tenant_id)
        return self.tenant_id

    def headers(self) -> Dict[str, str]:
        token = self.ensure_valid_access_token()
        tenant_id = self.ensure_tenant()
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
    Where xero_runner stores tokens by default.
    Override by setting env var XERO_TOKEN_PATH.
    """
    return os.environ.get(
        "XERO_TOKEN_PATH",
        os.path.join(os.path.expanduser("~"), ".xero_runner", "tokens.json"),
    )


def refresh_token_file_inplace(
    token_path: str,
    client_id: str,
    client_secret: str,
) -> XeroTokens:
    """
    Refreshes the access token using refresh_token from the token file,
    then writes the updated tokens back to the SAME file.

    This is safe to call from xero_jobs.py during long runs.
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
        refresh_token=j.get("refresh_token"),
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

    # If expired, optionally refresh in-place (requires secrets)
    if _now() >= int(tokens.expires_at):
        cid = client_id or os.environ.get("XERO_CLIENT_ID")
        csec = client_secret or os.environ.get("XERO_CLIENT_SECRET")
        if cid and csec:
            tokens = refresh_token_file_inplace(path, cid, csec)
        # If secrets not available, we return what we have (caller may still fail with 401)

    return {
        "Authorization": f"Bearer {tokens.access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
    }
