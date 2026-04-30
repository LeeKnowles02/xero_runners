"""API routes: status, endpoints, columns, preset, schedule, run, open_excel, scheduler_files."""
import os
import subprocess
import time

from flask import request, jsonify, send_file

from config import (
    DATA_DIR,
    BASE_DIR,
    EXCEL_PATH,
    TOKEN_PATH,
    STATE_PATH,
    REDIRECT_URI,
    get_scopes,
)
from xero_jobs import (
    list_endpoints,
    endpoint_columns,
    run_endpoint_selected,
    backup_file,
    workbook_with_only_sheet,
)
from xero_db import test_database_connection_and_seed, clear_connection_test_data, get_pipeline_history
from xero_test import run_sample_db_test, run_incremental_validation_test, clear_test_rows


def _attach_download_token_cookie(response):
    """
    Loader handshake: browser polls document.cookie for unleashed_download_token
    after file downloads (form POST or fetch with credentials).
    """
    token = request.args.get("download_token") or request.form.get("download_token")
    if token:
        response.set_cookie(
            "unleashed_download_token",
            token,
            max_age=120,
            samesite="Lax",
            path="/",
        )
    return response


def _pipeline_xero_auth_error(e: Exception, logger) -> tuple:
    msg = str(e)
    if "No tokens found" in msg or "interactive auth" in msg.lower():
        hint = " Complete OAuth first: open Dashboard and click **Re-authorize**."
        return (
            {
                "ok": False,
                "status": "FAIL",
                "error": msg + hint,
            },
            401,
        )
    return None


def register_api(app, xero, state, logger):
    @app.post("/api/pipeline/db_connection_test")
    def api_pipeline_db_connection_test():
        try:
            result = test_database_connection_and_seed()
            return jsonify({"ok": True, "status": "PASS", **result})
        except Exception as e:
            logger.exception("Database connection test failed")
            return jsonify({"ok": False, "status": "FAIL", "error": str(e)}), 500

    @app.post("/api/pipeline/clear_connection_test")
    def api_pipeline_clear_connection_test():
        try:
            clear_connection_test_data()
            return jsonify({"ok": True, "status": "PASS", "message": "Connection test data cleared."})
        except Exception as e:
            logger.exception("Clear connection test data failed")
            return jsonify({"ok": False, "status": "FAIL", "error": str(e)}), 500

    @app.post("/api/pipeline/sample_db_test")
    def api_pipeline_sample_db_test():
        payload = request.get_json(force=True) or {}
        endpoint = payload.get("endpoint") or "JournalLines"
        try:
            headers = xero.headers()
            result = run_sample_db_test(headers=headers, endpoint_name=endpoint, max_journals=10)
            return jsonify({"ok": True, **result})
        except Exception as e:
            auth = _pipeline_xero_auth_error(e, logger)
            if auth:
                return jsonify(auth[0]), auth[1]
            logger.exception("Sample DB test failed")
            return jsonify({"ok": False, "status": "FAIL", "error": str(e)}), 500

    @app.post("/api/pipeline/incremental_validation_test")
    def api_pipeline_incremental_validation_test():
        payload = request.get_json(force=True) or {}
        endpoint = payload.get("endpoint") or "JournalLines"
        try:
            headers = xero.headers()
            result = run_incremental_validation_test(headers=headers, endpoint_name=endpoint)
            return jsonify({"ok": result.get("status") == "PASS", **result})
        except Exception as e:
            auth = _pipeline_xero_auth_error(e, logger)
            if auth:
                return jsonify(auth[0]), auth[1]
            logger.exception("Incremental validation test failed")
            return jsonify({"ok": False, "status": "FAIL", "error": str(e)}), 500

    @app.post("/api/pipeline/clear_test_rows")
    def api_pipeline_clear_test_rows():
        payload = request.get_json(force=True) or {}
        endpoint = payload.get("endpoint") or "JournalLines"
        try:
            result = clear_test_rows(endpoint_name=endpoint)
            return jsonify({"ok": True, **result})
        except Exception as e:
            logger.exception("Clear test rows failed")
            return jsonify({"ok": False, "status": "FAIL", "error": str(e)}), 500

    @app.get("/api/pipeline/history")
    def api_pipeline_history():
        limit = int(request.args.get("limit", "20"))
        try:
            history = get_pipeline_history(limit=limit)
            return jsonify({"ok": True, "status": "PASS", **history})
        except Exception as e:
            logger.exception("Load pipeline history failed")
            return jsonify(
                {
                    "ok": False,
                    "status": "FAIL",
                    "error": str(e),
                    "runs": [],
                    "assessments": [],
                    "history_notes": [str(e)],
                }
            ), 500

    @app.get("/api/status")
    def api_status():
        token_state = "missing"
        tenant_id = None
        expires_at = None

        if xero.tokens:
            expires_at = xero.tokens.expires_at
            token_state = "expired/needs-refresh" if time.time() >= xero.tokens.expires_at else "valid"
            try:
                tenant_id = xero.ensure_tenant()
            except Exception:
                tenant_id = None

        return jsonify({
            "app": "Xero Runner",
            "token_state": token_state,
            "tenant_id": tenant_id,
            "expires_at": expires_at,
            "scopes": get_scopes(),
            "redirect_uri": REDIRECT_URI,
            "token_path": TOKEN_PATH,
            "excel_path": EXCEL_PATH,
            "state_path": STATE_PATH,
        })

    @app.get("/api/endpoints")
    def api_endpoints():
        return jsonify({"endpoints": list_endpoints()})

    @app.get("/api/columns")
    def api_columns():
        endpoint = request.args.get("endpoint", "")
        try:
            cols = endpoint_columns(endpoint)
            preset = state.get_preset(endpoint)
            watermark = state.get_watermark(endpoint)
            return jsonify({"endpoint": endpoint, "columns": cols, "preset": preset, "watermark": watermark})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/preset")
    def api_preset():
        payload = request.get_json(force=True)
        endpoint = payload.get("endpoint")
        columns = payload.get("columns")
        if not isinstance(columns, list):
            return jsonify({"ok": False, "error": "columns must be a list"}), 400
        state.set_preset(endpoint, columns)
        return jsonify({"ok": True, "endpoint": endpoint, "columns": columns})

    @app.get("/api/schedule")
    def api_get_schedule():
        return jsonify(state.get_schedule())

    @app.post("/api/schedule")
    def api_set_schedule():
        payload = request.get_json(force=True)
        schedule = {
            "enabled": bool(payload.get("enabled", False)),
            "interval_minutes": int(payload.get("interval_minutes", 720)),
            "endpoints": payload.get("endpoints", []),
            "incremental": bool(payload.get("incremental", True)),
        }
        state.set_schedule(schedule)
        return jsonify({"ok": True, "schedule": schedule})

    @app.post("/api/run")
    def api_run():
        payload = request.get_json(force=True)
        endpoint = payload.get("endpoint")
        columns = payload.get("columns")
        incremental = bool(payload.get("incremental", False))
        _t0 = time.perf_counter()

        # DB audit: UI-triggered sync — correlates with xero_jobs run_id via request X-Correlation-ID.
        try:
            import integration_db_log

            integration_db_log.log_ui_action(
                route="/api/run",
                action="endpoint.run.requested",
                payload_summary=integration_db_log.payload_summary_from_obj(
                    {"endpoint": endpoint, "incremental": incremental, "has_column_override": bool(columns)}
                ),
                status=integration_db_log.STATUS_IN_PROGRESS,
                message=(
                    f"Dashboard requested a sync for endpoint={endpoint!r}; incremental={incremental}. "
                    "Next: resolve preset columns, read incremental watermark, obtain Xero headers (tenant), "
                    "then run_endpoint_selected (API + DB + workbook)."
                ),
                function_name="api_run",
            )
        except Exception:
            pass

        try:
            if not columns:
                columns = state.get_preset(endpoint) or endpoint_columns(endpoint)
            if isinstance(columns, list) and columns:
                state.set_preset(endpoint, columns)

            watermark = state.get_watermark(endpoint) if incremental else None

            headers = xero.headers()
            try:
                import integration_db_log

                integration_db_log.set_log_context(tenant_id=headers.get("xero-tenant-id"))
            except Exception:
                pass

            rows, status, mode, err = run_endpoint_selected(
                endpoint_name=endpoint,
                headers=headers,
                excel_path=EXCEL_PATH,
                selected_columns=columns,
                incremental_since_iso=watermark,
            )

            new_watermark = None
            if status == "OK":
                new_watermark = state.set_watermark_now(endpoint)

            logger.info("Run complete endpoint=%s status=%s rows=%s mode=%s", endpoint, status, rows, mode)

            try:
                import integration_db_log

                dur = int((time.perf_counter() - _t0) * 1000)
                integration_db_log.log_ui_action(
                    route="/api/run",
                    action="endpoint.run.completed",
                    payload_summary=integration_db_log.payload_summary_from_obj(
                        {"endpoint": endpoint, "status": status, "mode": mode, "err": err}
                    ),
                    status=integration_db_log.STATUS_SUCCESS if status == "OK" else integration_db_log.STATUS_FAILED,
                    message=(
                        f"UI sync finished: endpoint={endpoint!r}; http/sync status={status}; mode={mode}; "
                        f"rows_written={rows}; worker_error={err!r}. "
                        "If status is not OK, inspect integration_log for the same correlation_id and the "
                        "endpoint.run rows; verify tenant and token refresh."
                    ),
                    duration_ms=dur,
                    function_name="api_run",
                    tenant_id=headers.get("xero-tenant-id"),
                    detail=(
                        f"incremental_since_iso={watermark!r}; watermark_after={new_watermark!r}; "
                        f"excel_path={EXCEL_PATH}"
                    ),
                    record_count=rows if status == "OK" else None,
                )
            except Exception:
                pass

            return jsonify({
                "ok": status == "OK",
                "endpoint": endpoint,
                "status": status,
                "mode": mode,
                "rows_written": rows,
                "error": err,
                "excel_path": EXCEL_PATH,
                "columns": columns,
                "watermark_after": new_watermark,
            })
        except Exception as e:
            try:
                import integration_db_log

                dur = int((time.perf_counter() - _t0) * 1000)
                integration_db_log.log_exception(
                    "UI /api/run raised an exception (before successful JSON response)",
                    e,
                    endpoint=str(endpoint),
                    step_name="api_run",
                    detail="Check token/tenant, endpoint name, and column preset; see stack_trace.",
                    duration_ms=dur,
                )
                integration_db_log.log_ui_action(
                    route="/api/run",
                    action="endpoint.run.failed",
                    payload_summary=integration_db_log.payload_summary_from_obj({"endpoint": endpoint}),
                    status="FAILED",
                    message=f"Unhandled exception in api_run: {type(e).__name__}: {e}",
                    duration_ms=dur,
                    function_name="api_run",
                )
            except Exception:
                pass
            logger.exception("Run failed endpoint=%s", endpoint)
            return jsonify({"ok": False, "endpoint": endpoint, "status": "FAILED", "error": str(e)}), 500

    @app.get("/api/download_excel")
    def api_download_excel():
        """
        Send the Excel file so the browser downloads it.
        If query param endpoint= is set (e.g. ?endpoint=JournalLines), send only that endpoint's sheet
        with filename xero_<Endpoint>.xlsx. Otherwise send the full workbook.
        """
        endpoint = request.args.get("endpoint", "").strip()
        if endpoint:
            buf = workbook_with_only_sheet(EXCEL_PATH, endpoint)
            if buf is None:
                return jsonify({"ok": False, "error": f"No sheet for endpoint '{endpoint}' yet. Run that endpoint first."}), 404
            safe_name = endpoint.replace("/", "-").replace("\\", "-")[:50]
            return _attach_download_token_cookie(
                send_file(
                    buf,
                    as_attachment=True,
                    download_name=f"xero_{safe_name}.xlsx",
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            )
        if not os.path.isfile(EXCEL_PATH):
            return jsonify({"ok": False, "error": "Excel file not found. Run an endpoint first."}), 404
        return _attach_download_token_cookie(
            send_file(
                EXCEL_PATH,
                as_attachment=True,
                download_name="xero_endpoints.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )

    @app.post("/api/open_excel")
    def api_open_excel():
        """Open the Excel file in the default app (macOS: open, Windows: start)."""
        try:
            if not os.path.isfile(EXCEL_PATH):
                return jsonify({"ok": False, "error": "Excel file not found. Run an endpoint first."}), 404
            if os.name == "nt":
                os.startfile(EXCEL_PATH)
            else:
                subprocess.run(["open", EXCEL_PATH], check=False)
            return jsonify({"ok": True, "opened": EXCEL_PATH})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/api/scheduler_files")
    def api_scheduler_files():
        schedule = state.get_schedule()
        interval_minutes = int(schedule.get("interval_minutes", 720))
        endpoints = schedule.get("endpoints", [])
        incremental = bool(schedule.get("incremental", True))

        label = "com.paulnelson.xerorunner"
        launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(launch_agents_dir, exist_ok=True)

        plist_path = os.path.join(launch_agents_dir, f"{label}.plist")
        log_path = os.path.join(DATA_DIR, "scheduler.log")

        python_bin = os.path.join(BASE_DIR, ".venv", "bin", "python")
        run_jobs = os.path.join(BASE_DIR, "run_jobs.py")

        start_interval = max(60, interval_minutes * 60)

        args = [python_bin, run_jobs]
        if endpoints:
            args += ["--endpoints", ",".join(endpoints)]
        args += ["--incremental", "1" if incremental else "0"]

        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
      {''.join(f'<string>{a}</string>' for a in args)}
    </array>
    <key>StartInterval</key><integer>{start_interval}</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>{log_path}</string>
    <key>StandardErrorPath</key><string>{log_path}</string>
    <key>WorkingDirectory</key><string>{BASE_DIR}</string>
  </dict>
</plist>
"""

        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist)

        commands = {
            "load": f"launchctl load -w '{plist_path}'",
            "unload": f"launchctl unload -w '{plist_path}'",
            "tail_log": f"tail -n 200 -f '{log_path}'",
        }

        logger.info("Scheduler files generated: %s", plist_path)

        return jsonify({
            "ok": True,
            "plist_path": plist_path,
            "log_path": log_path,
            "commands": commands,
            "schedule": schedule,
        })
