#!/usr/bin/env python3

import os
import sys
import argparse
import logging
from dotenv import load_dotenv

from log_utils import setup_logging
from xero_auth import XeroAuth, FileTokenStore
from xero_jobs import ensure_excel, list_endpoints, endpoint_columns, run_endpoint_selected
from state_store import JsonStateStore, utc_now_iso

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TOKEN_PATH = os.path.join(DATA_DIR, "xero_tokens.json")
EXCEL_PATH = os.path.join(DATA_DIR, "xero_endpoints.xlsx")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# ✅ MINIMAL CHANGE: ensure long-run 401 recovery reads the live token file
os.environ.setdefault("XERO_TOKEN_PATH", TOKEN_PATH)

DEFAULT_SCOPES = "offline_access accounting.journals.read accounting.contacts accounting.transactions accounting.settings"
REDIRECT_URI = "http://localhost:8000/callback"

LOG_PATH = os.path.join(DATA_DIR, "run_jobs.log")
logger = setup_logging(LOG_PATH, name="xero_runner.run_jobs")

def get_scopes() -> str:
    s = (os.getenv("XERO_SCOPES") or "").strip()
    return s if s else DEFAULT_SCOPES

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoints", default="", help="comma-separated endpoints")
    parser.add_argument("--incremental", default="1", help="1 or 0")
    args = parser.parse_args()

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    cid = (os.getenv("XERO_CLIENT_ID") or "").strip()
    csec = (os.getenv("XERO_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        raise RuntimeError("Missing XERO_CLIENT_ID / XERO_CLIENT_SECRET in .env")

    try:
        import integration_db_log
        import time as _time

        _batch_t0 = _time.perf_counter()
        integration_db_log.set_log_context(correlation_id=integration_db_log.new_correlation_id())
        integration_db_log.log_info(
            "CLI run_jobs: configuration loaded from .env; starting scheduled/manual batch",
            event_type="run_jobs.batch.started",
            module_name="run_jobs",
            function_name="main",
            status=integration_db_log.STATUS_IN_PROGRESS,
            detail=(
                "Credentials present (not logged). Each endpoint will get its own run_id inside "
                "run_endpoint_selected; use correlation_id to tie this process to integration_log rows."
            ),
        )
    except Exception:
        _batch_t0 = None  # type: ignore

    token_store = FileTokenStore(TOKEN_PATH)
    state = JsonStateStore(STATE_PATH)

    xero = XeroAuth(
        client_id=cid,
        client_secret=csec,
        scopes=get_scopes(),
        redirect_uri=REDIRECT_URI,
        token_store=token_store,
    )

    ensure_excel(EXCEL_PATH)

    incremental = args.incremental.strip() == "1"

    if args.endpoints.strip():
        endpoints = [e.strip() for e in args.endpoints.split(",") if e.strip()]
    else:
        # fallback: run all known endpoints
        endpoints = list_endpoints()

    headers = xero.headers()

    # XR-005: track endpoint failures so we can exit non-zero at the end.
    # launchd / cron / CI use the exit code to decide whether a run succeeded;
    # silently exiting 0 after partial failures masked real problems.
    failures = 0

    for ep in endpoints:
        # XR-006: refresh headers per endpoint so a long batch doesn't reuse a 30-min-stale token.
        # xero.headers() -> ensure_valid_access_token() is a cheap memory check when the token
        # is still valid; it only triggers a refresh HTTP call once expiry is reached.
        headers = xero.headers()

        cols = state.get_preset(ep) or endpoint_columns(ep)
        watermark = state.get_watermark(ep) if incremental else None

        # XR-020: capture run-start BEFORE making any HTTP calls.
        # On success we set the watermark to this timestamp (not utc_now_iso()),
        # so records modified DURING the run are still picked up by the next pull.
        run_start_iso = utc_now_iso()

        rows, status, mode, err = run_endpoint_selected(
            endpoint_name=ep,
            headers=headers,
            excel_path=EXCEL_PATH,
            selected_columns=cols,
            incremental_since_iso=watermark,
        )

        if status == "OK":
            state.set_watermark_now(ep)
        else:
            failures += 1  # XR-005

        logger.info("%s: %s rows=%s mode=%s err=%s", ep, status, rows, mode, err)
        print(f"{ep}: {status} rows={rows} mode={mode} err={err}")

    try:
        import integration_db_log
        import time as _time

        if _batch_t0 is not None:
            dur = int((_time.perf_counter() - _batch_t0) * 1000)
            integration_db_log.log_info(
                f"CLI run_jobs batch finished: {len(endpoints)} endpoint(s) processed, "
                f"{failures} failure(s)",
                event_type="run_jobs.batch.completed",
                module_name="run_jobs",
                function_name="main",
                status=integration_db_log.STATUS_SUCCESS,
                duration_ms=dur,
                detail=f"endpoints={endpoints!r}; incremental={incremental}; failures={failures}",
            )
        integration_db_log.set_log_context(clear=True)
    except Exception:
        pass

    # XR-005: tell the scheduler the truth. Any non-OK endpoint => exit non-zero.
    # launchd / cron / a future Azure Function Timer will read this exit code.
    if failures:
        logger.warning(
            "XR-005: %s of %s endpoint(s) failed. Exiting with code 1.",
            failures, len(endpoints)
        )
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            import integration_db_log

            integration_db_log.log_exception(
                "run_jobs CLI terminated with an exception",
                e,
                step_name="main",
                detail="Check .env, token file, network, and prior integration_log rows for this host.",
            )
            integration_db_log.set_log_context(clear=True)
        except Exception:
            pass
        raise
