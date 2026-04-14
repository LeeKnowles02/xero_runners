"""
Azure SQL–backed integration audit log for Xero Runner.

Writes detailed rows to xero.integration_log (see sql/setup_integration_log.sql).
Full sync executions also open/close xero.sync_run (see sql/setup_sync_run.sql).

Status vocabulary (integration_log.status — never NULL; enforced in log_event):
  SUCCESS, FAILED, IN_PROGRESS, WARNING. Legacy strings (OK/done/error/…) are normalized.

Env:
  INTEGRATION_LOG_ENABLED=1 (default) | 0 — disable DB inserts (file logging still works)
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import socket
import traceback
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

_pylog = logging.getLogger("xero_runner.integration_db_log")

PROJECT_NAME_DEFAULT = "xero_runner"
INTEGRATION_NAME_DEFAULT = "Xero"
SOURCE_SYSTEM_DEFAULT = "Xero"

# --- Standardized event outcomes (integration_log.status; never NULL) ---
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_WARNING = "WARNING"

_EVENT_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_FAILED, STATUS_IN_PROGRESS, STATUS_WARNING}
)

# Final outcomes for xero.sync_run (SUCCESS | FAILED only when complete; IN_PROGRESS while running)
_RUN_FINAL_STATUSES = frozenset({STATUS_SUCCESS, STATUS_FAILED})
_RUN_OPEN_STATUSES = frozenset({STATUS_IN_PROGRESS})

_LEGACY_STATUS_MAP = {
    "ok": STATUS_SUCCESS,
    "OK": STATUS_SUCCESS,
    "done": STATUS_SUCCESS,
    "DONE": STATUS_SUCCESS,
    "success": STATUS_SUCCESS,
    "SUCCESS": STATUS_SUCCESS,
    "completed": STATUS_SUCCESS,
    "COMPLETE": STATUS_SUCCESS,
    "error": STATUS_FAILED,
    "ERROR": STATUS_FAILED,
    "failed": STATUS_FAILED,
    "FAILED": STATUS_FAILED,
    "fail": STATUS_FAILED,
    "started": STATUS_IN_PROGRESS,
    "STARTED": STATUS_IN_PROGRESS,
    "pending": STATUS_IN_PROGRESS,
    "PENDING": STATUS_IN_PROGRESS,
    "in_progress": STATUS_IN_PROGRESS,
    "IN_PROGRESS": STATUS_IN_PROGRESS,
    "warn": STATUS_WARNING,
    "WARN": STATUS_WARNING,
    "warning": STATUS_WARNING,
    "WARNING": STATUS_WARNING,
}


def normalize_event_status(
    raw: Optional[str],
    *,
    log_level: str,
) -> str:
    """
    Map legacy or missing status to SUCCESS | FAILED | IN_PROGRESS | WARNING.
    Used so integration_log.status is never NULL and never vague (ok/done/error).
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if log_level == "ERROR":
            return STATUS_FAILED
        if log_level == "WARNING":
            return STATUS_WARNING
        return STATUS_SUCCESS
    s = str(raw).strip()
    if s in _EVENT_STATUSES:
        return s
    mapped = _LEGACY_STATUS_MAP.get(s)
    if mapped is not None:
        return mapped
    sl = s.lower()
    for k, v in _LEGACY_STATUS_MAP.items():
        if k.lower() == sl:
            return v
    return STATUS_SUCCESS


def normalize_run_final_status(raw: str) -> str:
    """sync_run completion: only SUCCESS or FAILED."""
    s = (raw or "").strip().upper()
    if s == STATUS_FAILED:
        return STATUS_FAILED
    return STATUS_SUCCESS


_SYNC_RUN_ENSURED = False

_CTX_RUN_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "integration_run_id", default=None
)
_CTX_CORRELATION_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "integration_correlation_id", default=None
)
_CTX_TENANT_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "integration_tenant_id", default=None
)

_TABLE_ENSURED = False
_ENABLED = os.getenv("INTEGRATION_LOG_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def is_enabled() -> bool:
    return _ENABLED


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:22]}"


def new_correlation_id() -> str:
    return f"corr_{uuid.uuid4().hex[:20]}"


def set_log_context(
    *,
    run_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    clear: bool = False,
) -> None:
    """Set correlation / run / tenant for the current async context (e.g. Flask request, job)."""
    if clear:
        _CTX_RUN_ID.set(None)
        _CTX_CORRELATION_ID.set(None)
        _CTX_TENANT_ID.set(None)
        return
    if run_id is not None:
        _CTX_RUN_ID.set(run_id)
    if correlation_id is not None:
        _CTX_CORRELATION_ID.set(correlation_id)
    if tenant_id is not None:
        _CTX_TENANT_ID.set(tenant_id)


def get_log_context() -> Dict[str, Optional[str]]:
    return {
        "run_id": _CTX_RUN_ID.get(),
        "correlation_id": _CTX_CORRELATION_ID.get(),
        "tenant_id": _CTX_TENANT_ID.get(),
    }


def _merge_context_into_row(row: Dict[str, Any]) -> None:
    ctx = get_log_context()
    if row.get("run_id") is None and ctx.get("run_id"):
        row["run_id"] = ctx["run_id"]
    if row.get("correlation_id") is None and ctx.get("correlation_id"):
        row["correlation_id"] = ctx["correlation_id"]
    if row.get("tenant_id") is None and ctx.get("tenant_id"):
        row["tenant_id"] = ctx["tenant_id"]


_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|authorization|client_secret|refresh_token|access_token|apikey|api_key)",
    re.I,
)


def sanitize_headers(headers: Optional[Dict[str, str]]) -> Optional[str]:
    if not headers:
        return None
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if _SENSITIVE_KEY_RE.search(k) or k.lower() in ("authorization", "cookie"):
            out[k] = "[REDACTED]"
        elif k.lower() == "xero-tenant-id":
            out[k] = str(v) if v else ""
        else:
            out[k] = str(v) if v is not None else ""
    try:
        s = json.dumps(out, ensure_ascii=False)
    except Exception:
        s = str(out)
    return _truncate(s, 4000)


def sanitize_params(params: Any) -> Optional[str]:
    if params is None:
        return None
    try:
        if isinstance(params, dict):
            safe = dict(params)
            for k in list(safe.keys()):
                if _SENSITIVE_KEY_RE.search(k):
                    safe[k] = "[REDACTED]"
            s = json.dumps(safe, default=str, ensure_ascii=False)
        else:
            s = json.dumps(params, default=str, ensure_ascii=False)
    except Exception:
        s = str(params)
    return _truncate(s, 4000)


def sanitize_response_body(text: Optional[str], max_len: int = 4000) -> Optional[str]:
    if text is None:
        return None
    s = str(text)
    # Mask obvious bearer tokens in JSON text
    s = re.sub(
        r'("access_token"\s*:\s*")[^"]+(")',
        r'\1[REDACTED]\2',
        s,
        flags=re.I,
    )
    s = re.sub(
        r'("refresh_token"\s*:\s*")[^"]+(")',
        r'\1[REDACTED]\2',
        s,
        flags=re.I,
    )
    return _truncate(s, max_len)


def _truncate(s: Optional[str], max_len: int = 8000) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 20] + "…(truncated)"


def payload_summary_from_obj(obj: Any, max_len: int = 2000) -> Optional[str]:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return _truncate(s, max_len)


_ALLOWED_COLUMNS = frozenset(
    {
        "project_name",
        "integration_name",
        "source_system",
        "module_name",
        "function_name",
        "log_level",
        "event_type",
        "run_id",
        "correlation_id",
        "tenant_id",
        "xero_tenant_name",
        "endpoint",
        "entity_name",
        "action",
        "step_name",
        "status",
        "message",
        "detail",
        "payload_summary",
        "record_count",
        "duration_ms",
        "http_status_code",
        "error_type",
        "error_message",
        "stack_trace",
        "request_url",
        "request_method",
        "request_params",
        "request_headers_safe",
        "response_summary",
        "response_body_safe",
        "machine_name",
        "environment",
        "created_by",
    }
)


def _ensure_table(conn) -> bool:
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return True
    try:
        conn.execute(text("IF SCHEMA_ID('xero') IS NULL EXEC('CREATE SCHEMA xero');"))
        exists = conn.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'integration_log'"
            )
        ).scalar()
        if exists:
            _TABLE_ENSURED = True
            return True
        conn.execute(
            text("""
            CREATE TABLE xero.integration_log (
                [id] BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                [created_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                [project_name] NVARCHAR(255) NULL,
                [integration_name] NVARCHAR(255) NULL,
                [source_system] NVARCHAR(100) NULL,
                [module_name] NVARCHAR(255) NULL,
                [function_name] NVARCHAR(255) NULL,
                [log_level] NVARCHAR(20) NULL,
                [event_type] NVARCHAR(100) NULL,
                [run_id] NVARCHAR(80) NULL,
                [correlation_id] NVARCHAR(80) NULL,
                [tenant_id] NVARCHAR(80) NULL,
                [xero_tenant_name] NVARCHAR(512) NULL,
                [endpoint] NVARCHAR(255) NULL,
                [entity_name] NVARCHAR(255) NULL,
                [action] NVARCHAR(255) NULL,
                [step_name] NVARCHAR(255) NULL,
                [status] NVARCHAR(50) NOT NULL DEFAULT N'SUCCESS',
                [message] NVARCHAR(MAX) NULL,
                [detail] NVARCHAR(MAX) NULL,
                [payload_summary] NVARCHAR(MAX) NULL,
                [record_count] INT NULL,
                [duration_ms] INT NULL,
                [http_status_code] INT NULL,
                [error_type] NVARCHAR(255) NULL,
                [error_message] NVARCHAR(MAX) NULL,
                [stack_trace] NVARCHAR(MAX) NULL,
                [request_url] NVARCHAR(2048) NULL,
                [request_method] NVARCHAR(20) NULL,
                [request_params] NVARCHAR(MAX) NULL,
                [request_headers_safe] NVARCHAR(MAX) NULL,
                [response_summary] NVARCHAR(MAX) NULL,
                [response_body_safe] NVARCHAR(MAX) NULL,
                [machine_name] NVARCHAR(255) NULL,
                [environment] NVARCHAR(64) NULL,
                [created_by] NVARCHAR(255) NULL,
                CONSTRAINT CK_integration_log_status CHECK ([status] IN (N'SUCCESS', N'FAILED', N'IN_PROGRESS', N'WARNING'))
            );
            """)
        )
        _TABLE_ENSURED = True
        _pylog.info("Created xero.integration_log via auto-DDL")
        return True
    except ProgrammingError as e:
        _pylog.debug("integration_log table ensure skipped: %s", e)
        return False
    except Exception as e:
        _pylog.debug("integration_log table ensure failed: %s", e)
        return False


def _ensure_sync_run_table(conn) -> bool:
    """Create xero.sync_run when the app has DDL rights (see sql/setup_sync_run.sql)."""
    global _SYNC_RUN_ENSURED
    if _SYNC_RUN_ENSURED:
        return True
    try:
        conn.execute(text("IF SCHEMA_ID('xero') IS NULL EXEC('CREATE SCHEMA xero');"))
        exists = conn.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'sync_run'"
            )
        ).scalar()
        if exists:
            _SYNC_RUN_ENSURED = True
            return True
        conn.execute(
            text("""
            CREATE TABLE xero.sync_run (
                [run_id] NVARCHAR(80) NOT NULL CONSTRAINT PK_xero_sync_run PRIMARY KEY,
                [correlation_id] NVARCHAR(80) NULL,
                [tenant_id] NVARCHAR(80) NULL,
                [endpoint_name] NVARCHAR(255) NULL,
                [start_time] DATETIME2 NOT NULL CONSTRAINT DF_sync_run_start DEFAULT SYSUTCDATETIME(),
                [end_time] DATETIME2 NULL,
                [status] NVARCHAR(20) NOT NULL CONSTRAINT DF_sync_run_status DEFAULT 'IN_PROGRESS',
                [total_records] INT NULL,
                [total_errors] INT NOT NULL CONSTRAINT DF_sync_run_err DEFAULT 0,
                [message] NVARCHAR(MAX) NULL
            );
            """)
        )
        _SYNC_RUN_ENSURED = True
        _pylog.info("Created xero.sync_run via auto-DDL")
        return True
    except ProgrammingError as e:
        _pylog.debug("sync_run table ensure skipped: %s", e)
        return False
    except Exception as e:
        _pylog.debug("sync_run table ensure failed: %s", e)
        return False


def start_sync_run(
    run_id: str,
    *,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    endpoint_name: Optional[str] = None,
) -> None:
    """
    One row per full endpoint/sync execution. Status starts IN_PROGRESS; call complete_sync_run when done.
    """
    if not _ENABLED or not run_id:
        return
    ctx = get_log_context()
    cid = correlation_id if correlation_id is not None else ctx.get("correlation_id")
    tid = tenant_id if tenant_id is not None else ctx.get("tenant_id")
    try:
        from db import engine

        eng = engine()
        with eng.begin() as conn:
            if not _ensure_sync_run_table(conn):
                chk = conn.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'sync_run'"
                    )
                ).scalar()
                if not chk:
                    _pylog.debug("sync_run table missing; start_sync_run skipped")
                    return
            conn.execute(
                text("""
                IF NOT EXISTS (SELECT 1 FROM xero.sync_run WHERE run_id = :run_id)
                INSERT INTO xero.sync_run (
                    run_id, correlation_id, tenant_id, endpoint_name, start_time, end_time, status, total_records, total_errors
                ) VALUES (
                    :run_id, :correlation_id, :tenant_id, :endpoint_name, SYSUTCDATETIME(), NULL, 'IN_PROGRESS', NULL, 0
                );
                """),
                {
                    "run_id": run_id,
                    "correlation_id": cid,
                    "tenant_id": tid,
                    "endpoint_name": endpoint_name,
                },
            )
    except Exception as e:
        _pylog.debug("start_sync_run failed: %s", e)


def complete_sync_run(
    run_id: str,
    *,
    final_status: str,
    total_records: int,
    total_errors: int,
    message: Optional[str] = None,
) -> None:
    """
    Close a sync_run row. final_status must be SUCCESS or FAILED (critical failure → FAILED).
    """
    if not _ENABLED or not run_id:
        return
    fs = normalize_run_final_status(final_status)
    if fs not in _RUN_FINAL_STATUSES:
        fs = STATUS_FAILED
    try:
        from db import engine

        eng = engine()
        with eng.begin() as conn:
            if not _ensure_sync_run_table(conn):
                chk = conn.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'sync_run'"
                    )
                ).scalar()
                if not chk:
                    return
            conn.execute(
                text("""
                UPDATE xero.sync_run
                SET end_time = SYSUTCDATETIME(),
                    status = :status,
                    total_records = :total_records,
                    total_errors = :total_errors,
                    message = :msg
                WHERE run_id = :run_id
                """),
                {
                    "run_id": run_id,
                    "status": fs,
                    "total_records": total_records,
                    "total_errors": max(0, int(total_errors)),
                    "msg": message,
                },
            )
    except Exception as e:
        _pylog.debug("complete_sync_run failed: %s", e)


def log_event(
    log_level: str,
    event_type: str,
    message: str,
    *,
    project_name: str = PROJECT_NAME_DEFAULT,
    integration_name: str = INTEGRATION_NAME_DEFAULT,
    source_system: str = SOURCE_SYSTEM_DEFAULT,
    module_name: Optional[str] = None,
    function_name: Optional[str] = None,
    **fields: Any,
) -> None:
    """
    Insert one row into xero.integration_log. Unknown kwargs are ignored.
    Context (run_id, correlation_id, tenant_id) is merged from contextvars when omitted.
    """
    row: Dict[str, Any] = {
        "project_name": project_name,
        "integration_name": integration_name,
        "source_system": source_system,
        "module_name": module_name,
        "function_name": function_name,
        "log_level": log_level,
        "event_type": event_type,
        "message": message,
    }
    for k, v in fields.items():
        if k in _ALLOWED_COLUMNS and v is not None:
            row[k] = v
    _merge_context_into_row(row)
    if row.get("machine_name") is None:
        try:
            row["machine_name"] = socket.gethostname()[:255]
        except Exception:
            row["machine_name"] = None
    if row.get("environment") is None:
        row["environment"] = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "development")[:64]
    # integration_log.status is required: SUCCESS | FAILED | IN_PROGRESS | WARNING
    row["status"] = normalize_event_status(row.get("status"), log_level=log_level)
    _insert_row(row)


def _insert_row(row: Dict[str, Any]) -> None:
    if not _ENABLED:
        return
    try:
        from db import engine

        eng = engine()
    except Exception as e:
        _pylog.debug("integration DB log skipped (engine): %s", e)
        return

    cols = [c for c in _ALLOWED_COLUMNS if c in row and row[c] is not None]
    # Note: 0 and False are kept (not None)
    if not cols:
        return
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(f"[{c}]" for c in cols)
    sql = f"INSERT INTO xero.integration_log ({col_list}) VALUES ({placeholders})"
    params = {c: row[c] for c in cols}
    try:
        with eng.begin() as conn:
            if not _ensure_table(conn):
                # Table missing and DDL failed — try insert anyway (DBA may have created it)
                chk = conn.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'integration_log'"
                    )
                ).scalar()
                if not chk:
                    _pylog.debug("integration_log table not present; log row dropped")
                    return
            conn.execute(text(sql), params)
    except ProgrammingError as e:
        _pylog.debug("integration log insert failed (SQL): %s", e)
    except Exception as e:
        _pylog.debug("integration log insert failed: %s", e)


def log_debug(message: str, **kwargs: Any) -> None:
    et = kwargs.pop("event_type", "debug")
    log_event("DEBUG", et, message, **kwargs)


def log_info(message: str, **kwargs: Any) -> None:
    et = kwargs.pop("event_type", "info")
    log_event("INFO", et, message, **kwargs)


def log_warning(message: str, **kwargs: Any) -> None:
    et = kwargs.pop("event_type", "warning")
    log_event("WARNING", et, message, **kwargs)


def log_error(
    message: str,
    *,
    exc: Optional[BaseException] = None,
    **kwargs: Any,
) -> None:
    et = kwargs.pop("event_type", "error")
    if exc is not None:
        kwargs.setdefault("error_type", type(exc).__name__)
        kwargs.setdefault("error_message", str(exc))
        kwargs.setdefault("stack_trace", _truncate("".join(traceback.format_exception(exc)), 12000))
    kwargs.setdefault("status", STATUS_FAILED)
    log_event("ERROR", et, message, **kwargs)


def log_exception(
    message: str,
    exc: BaseException,
    *,
    endpoint: Optional[str] = None,
    step_name: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Structured failure log with type, message, stack, optional endpoint/step."""
    log_error(
        message,
        exc=exc,
        event_type=kwargs.pop("event_type", "exception"),
        endpoint=endpoint,
        step_name=step_name,
        **kwargs,
    )


def log_http_response(
    *,
    request_url: str,
    request_method: str,
    request_params: Any,
    request_headers: Dict[str, str],
    status_code: int,
    duration_ms: int,
    response_text: Optional[str] = None,
    event_type: str = "api.http.response",
    message: Optional[str] = None,
    record_count_hint: Optional[int] = None,
    response_summary: Optional[str] = None,
    step_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    tenant_id: Optional[str] = None,
    empty_result_warning: bool = False,
) -> None:
    """Log a completed HTTP call with safe headers and truncated body."""
    body_safe = sanitize_response_body(response_text) if response_text else None
    if message is None:
        message = f"{request_method} {request_url} completed with HTTP {status_code} in {duration_ms}ms"
    summ = response_summary
    if summ is None and response_text and status_code == 200:
        try:
            j = json.loads(response_text)
            if isinstance(j, dict):
                keys = list(j.keys())[:12]
                summ = f"JSON keys: {keys}"
                for k in ("Journals", "Contacts", "Invoices", "Organisations", "Payments"):
                    if k in j and isinstance(j[k], list):
                        summ += f"; {k}_count={len(j[k])}"
                        break
        except Exception:
            summ = f"body_len={len(response_text)}"

    if status_code < 400:
        evt_status = STATUS_WARNING if empty_result_warning else STATUS_SUCCESS
        log_ll = "WARNING" if empty_result_warning else "INFO"
    else:
        evt_status = STATUS_FAILED
        log_ll = "ERROR" if status_code >= 500 else "WARNING"

    log_event(
        log_ll,
        event_type,
        message,
        status=evt_status,
        request_url=_truncate(request_url, 2048),
        request_method=request_method,
        request_params=sanitize_params(request_params),
        request_headers_safe=sanitize_headers(request_headers),
        http_status_code=status_code,
        duration_ms=duration_ms,
        response_body_safe=body_safe,
        response_summary=_truncate(summ, 2000) if summ else None,
        record_count=record_count_hint,
        step_name=step_name,
        endpoint=endpoint,
        tenant_id=tenant_id,
        module_name="xero_jobs",
        function_name="_get_json",
    )


def log_db_write(
    *,
    schema_table: str,
    operation: str,
    rows_affected: Optional[int],
    duration_ms: Optional[int],
    status: str,
    message: str,
    detail: Optional[str] = None,
    error: Optional[BaseException] = None,
    step_name: Optional[str] = None,
) -> None:
    kw: Dict[str, Any] = {
        "entity_name": schema_table,
        "action": operation,
        "step_name": step_name or "db.write",
        "status": status,
        "detail": detail,
        "record_count": rows_affected,
        "duration_ms": duration_ms,
        "module_name": "xero_db",
        "function_name": "save_endpoint_to_db",
    }
    if error:
        kw["error_type"] = type(error).__name__
        kw["error_message"] = str(error)
        kw["stack_trace"] = _truncate("".join(traceback.format_exception(error)), 12000)
    kw["status"] = normalize_event_status(kw["status"], log_level="ERROR" if error else "INFO")
    lvl = "ERROR" if error else "INFO"
    log_event(lvl, "db.write", message, **kw)


def log_workbook_event(
    *,
    action: str,
    excel_path: str,
    status: str,
    message: str,
    duration_ms: Optional[int] = None,
    detail: Optional[str] = None,
    step_name: Optional[str] = None,
) -> None:
    ns = normalize_event_status(status, log_level="INFO")
    log_event(
        "INFO",
        "workbook",
        message,
        action=action,
        step_name=step_name or "excel",
        status=ns,
        detail=detail or _truncate(excel_path, 500),
        duration_ms=duration_ms,
        module_name="xero_jobs",
        function_name="workbook",
    )


def log_ui_action(
    *,
    route: str,
    action: str,
    payload_summary: Optional[str],
    status: str,
    message: str,
    duration_ms: Optional[int] = None,
    function_name: str = "request",
    tenant_id: Optional[str] = None,
    detail: Optional[str] = None,
    record_count: Optional[int] = None,
) -> None:
    ns = normalize_event_status(status, log_level="INFO")
    if ns == STATUS_FAILED:
        lvl = "ERROR"
    elif ns == STATUS_WARNING:
        lvl = "WARNING"
    elif ns == STATUS_IN_PROGRESS:
        lvl = "INFO"
    else:
        lvl = "INFO"
    log_event(
        lvl,
        "ui.action",
        message,
        endpoint=route,
        action=action,
        payload_summary=payload_summary,
        status=ns,
        duration_ms=duration_ms,
        module_name="routes.api",
        function_name=function_name,
        tenant_id=tenant_id,
        detail=detail,
        record_count=record_count,
    )
