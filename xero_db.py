"""
Persist Xero endpoint data to Azure SQL (xero schema).
Used when Run is clicked: after writing Excel, we upsert to DB so data is in SSMS too.
"""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = logging.getLogger("xero_runner.xero_db")

# Retry on connection errors (e.g. TCP 0x20, dropped connection)
DB_WRITE_RETRIES = 3
DB_WRITE_RETRY_DELAY = 2.0
TEST_METADATA_COLUMNS = ["RunType", "RunRef", "LoadedAt", "EndpointName"]

_DDL_DENIED_HINT = (
    "This SQL login cannot CREATE/ALTER objects (e.g. error 262). "
    "Run sql/setup_pipeline_test_objects.sql (and sql/setup_xero_schema.sql for endpoint tables) as a DBA, "
    "or grant CREATE TABLE / ALTER on schema xero."
)


def _is_ddl_denied(exc: Exception) -> bool:
    parts = [str(exc).lower()]
    o = getattr(exc, "orig", None)
    if o is not None:
        parts.append(str(o).lower())
    blob = " ".join(parts)
    if "262" in blob:
        return True
    if "create table permission denied" in blob:
        return True
    if "create schema" in blob and "denied" in blob:
        return True
    if "alter table" in blob and "permission" in blob and "denied" in blob:
        return True
    if "1088" in blob and "cannot find the object" in blob:
        return True
    return False


def _xero_table_exists(conn, table_name: str) -> bool:
    """True if xero.<table_name> exists (user-visible). table_name: e.g. JournalLines, TestRunLog."""
    if not re.match(r"^[A-Za-z0-9_]+$", table_name or ""):
        return False
    oid = conn.execute(
        text("SELECT OBJECT_ID(:fqn, N'U')"),
        {"fqn": f"xero.{table_name}"},
    ).scalar()
    return oid is not None


def _quote_sql_identifier(name: str) -> str:
    """Quote for SQL (handles dots): JournalLine.Description -> [JournalLine.Description]."""
    s = (name or "").strip() or "value"
    return f"[{s}]"


def _get_table_columns(conn, table_name: str) -> List[str]:
    """Return list of column names for xero.{table_name} (excluding UpdatedAt)."""
    r = conn.execute(
        text("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = :tname AND COLUMN_NAME <> 'UpdatedAt'
            ORDER BY ORDINAL_POSITION
        """),
        {"tname": table_name},
    )
    return [row[0] for row in r]


def _row_value(row: Dict[str, Any], col: str) -> Any:
    """Get value for column from row; accept either 'Contact.ContactID' or 'Contact_ContactID'."""
    v = row.get(col)
    if v is not None:
        return v
    alt = col.replace(".", "_")
    return row.get(alt)


def _ensure_xero_schema(conn) -> None:
    """Create xero schema if it doesn't exist."""
    conn.execute(text("IF SCHEMA_ID('xero') IS NULL EXEC('CREATE SCHEMA xero');"))


def _ensure_table(conn, table_name: str, columns: List[str], pk_column: str) -> None:
    """Create table if not exists. columns = exact names as displayed (e.g. JournalLine.Description)."""
    _ensure_xero_schema(conn)
    full_name = f"xero.[{table_name}]"
    check = conn.execute(
        text(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = :tname"
        ),
        {"tname": table_name},
    ).scalar()
    if check:
        return
    q = _quote_sql_identifier
    parts = [f"{q(c)} NVARCHAR(255)" if c == pk_column else f"{q(c)} NVARCHAR(MAX)" for c in columns]
    cols_sql = ", ".join(parts) + ", [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()"
    sql = f"CREATE TABLE {full_name} ({cols_sql}, CONSTRAINT PK_xero_{table_name} PRIMARY KEY ({q(pk_column)}));"
    conn.execute(text(sql))
    logger.info("Created table %s", full_name)


def _ensure_test_metadata_columns(conn, table_name: str) -> bool:
    """
    Ensure RunType / RunRef / LoadedAt / EndpointName exist on xero.<table_name>.
    Returns False if any ALTER failed (no permission or table missing).
    """
    if not re.match(r"^[A-Za-z0-9_]+$", table_name or ""):
        return False
    fqn = f"xero.{table_name}"
    ok = True
    for col in TEST_METADATA_COLUMNS:
        try:
            conn.execute(
                text(f"""
                    IF COL_LENGTH(:fqn, :cname) IS NULL
                    ALTER TABLE xero.[{table_name}] ADD [{col}] NVARCHAR(255) NULL;
                """),
                {"fqn": fqn, "cname": col},
            )
        except ProgrammingError as e:
            logger.warning("Could not add column %s on %s: %s", col, fqn, e)
            ok = False
    return ok


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_ref(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{int(time.time() * 1000) % 100000}"


def test_database_connection_and_seed() -> Dict[str, Any]:
    """Prove connectivity with SELECT 1; seed ConnectionTest only if CREATE is allowed."""
    from db import engine

    eng = engine()
    with eng.begin() as conn:
        conn.execute(text("SELECT 1 AS ok"))

    try:
        with eng.begin() as conn:
            try:
                _ensure_xero_schema(conn)
            except ProgrammingError as e:
                if _is_ddl_denied(e):
                    return {
                        "ok": True,
                        "rows_written": 0,
                        "message": (
                            "Database connection successful (query OK). "
                            "Could not create schema xero: " + _DDL_DENIED_HINT
                        ),
                        "ddl_skipped": True,
                    }
                raise
            conn.execute(
                text("""
                IF OBJECT_ID('xero.ConnectionTest', 'U') IS NULL
                CREATE TABLE xero.ConnectionTest (
                    [ID] INT NOT NULL PRIMARY KEY,
                    [TestValue] NVARCHAR(100) NOT NULL,
                    [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                );
            """)
            )
            conn.execute(text("DELETE FROM xero.ConnectionTest;"))
            for i in range(1, 11):
                conn.execute(
                    text(
                        "INSERT INTO xero.ConnectionTest ([ID], [TestValue], [CreatedAt]) VALUES (:id, :val, SYSUTCDATETIME());"
                    ),
                    {"id": i, "val": f"TEST_ROW_{i}"},
                )
    except ProgrammingError as e:
        if _is_ddl_denied(e):
            return {
                "ok": True,
                "rows_written": 0,
                "message": (
                    "Database connection successful (query OK). "
                    "Could not create or write ConnectionTest: " + _DDL_DENIED_HINT
                ),
                "ddl_skipped": True,
            }
        raise
    return {
        "ok": True,
        "rows_written": 10,
        "message": "Database connection successful. 10 test rows written.",
    }


def clear_connection_test_data() -> int:
    from db import engine
    eng = engine()
    with eng.begin() as conn:
        conn.execute(text("""
            IF OBJECT_ID('xero.ConnectionTest', 'U') IS NOT NULL
            DELETE FROM xero.ConnectionTest;
        """))
    return 1


def delete_test_rows(endpoint_name: str) -> Dict[str, Any]:
    """
    Delete TEST rows for an endpoint table. Does not CREATE tables.
    Returns rows_deleted and an optional note (e.g. missing table / DDL denied).
    """
    from db import engine

    eng = engine()
    table_name = endpoint_name.replace(" ", "_")
    with eng.begin() as conn:
        if not _xero_table_exists(conn, table_name):
            return {
                "rows_deleted": 0,
                "note": (
                    f"xero.{table_name} was not found. Create endpoint tables with sql/setup_xero_schema.sql "
                    "before clearing or writing TEST rows."
                ),
            }

        meta_ok = _ensure_test_metadata_columns(conn, table_name)
        if not meta_ok:
            try:
                have = set(_get_table_columns(conn, table_name))
            except Exception:
                have = set()
            missing = [c for c in TEST_METADATA_COLUMNS if c not in have]
            if missing:
                return {
                    "rows_deleted": 0,
                    "note": (
                        f"Missing columns on xero.{table_name}: {missing}. {_DDL_DENIED_HINT}"
                    ),
                }

        try:
            r = conn.execute(
                text(
                    f"DELETE FROM xero.[{table_name}] WHERE [RunType] = 'TEST' AND [EndpointName] = :ep"
                ),
                {"ep": endpoint_name},
            )
        except ProgrammingError as e:
            logger.warning("delete_test_rows DELETE failed: %s", e)
            return {"rows_deleted": 0, "note": str(e)}

    return {"rows_deleted": int(r.rowcount or 0), "note": None}


def insert_test_rows(endpoint_name: str, rows: List[Dict[str, Any]], columns: List[str], run_ref: Optional[str] = None) -> Dict[str, Any]:
    if not rows:
        return {"rows_written": 0, "run_ref": run_ref or _run_ref("TEST")}
    run_ref = run_ref or _run_ref("TEST")
    loaded_at = _utc_iso()
    enriched = []
    for row in rows:
        r = dict(row)
        r["RunType"] = "TEST"
        r["RunRef"] = run_ref
        r["LoadedAt"] = loaded_at
        r["EndpointName"] = endpoint_name
        enriched.append(r)
    try:
        save_endpoint_to_db(endpoint_name, enriched, columns + TEST_METADATA_COLUMNS)
    except ProgrammingError as e:
        if _is_ddl_denied(e):
            raise RuntimeError(_DDL_DENIED_HINT + " Original error: " + str(e)) from e
        raise
    return {"rows_written": len(enriched), "run_ref": run_ref, "loaded_at": loaded_at}


def log_run(endpoint_name: str, run_ref: str, status: str, rows_written: int, details: Optional[str] = None) -> None:
    from db import engine

    eng = engine()
    try:
        with eng.begin() as conn:
            try:
                _ensure_xero_schema(conn)
            except ProgrammingError as e:
                logger.debug("log_run schema ensure: %s", e)
            try:
                conn.execute(
                    text("""
                    IF OBJECT_ID('xero.TestRunLog', 'U') IS NULL
                    CREATE TABLE xero.TestRunLog (
                        [RunRef] NVARCHAR(255) NOT NULL,
                        [EndpointName] NVARCHAR(255) NOT NULL,
                        [Status] NVARCHAR(50) NOT NULL,
                        [RowsWritten] INT NOT NULL,
                        [Details] NVARCHAR(MAX) NULL,
                        [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                    );
                """)
                )
            except ProgrammingError as e:
                logger.warning("log_run: could not create TestRunLog (DDL denied?): %s", e)
            if not _xero_table_exists(conn, "TestRunLog"):
                return
            conn.execute(
                text("""
                    INSERT INTO xero.TestRunLog ([RunRef], [EndpointName], [Status], [RowsWritten], [Details], [CreatedAt])
                    VALUES (:run_ref, :endpoint, :status, :rows_written, :details, SYSUTCDATETIME());
                """),
                {
                    "run_ref": run_ref,
                    "endpoint": endpoint_name,
                    "status": status,
                    "rows_written": rows_written,
                    "details": details,
                },
            )
    except ProgrammingError as e:
        logger.warning("log_run insert failed: %s", e)


def log_assessment(run_ref: str, status: str, summary: str, details_json: str) -> None:
    from db import engine

    eng = engine()
    try:
        with eng.begin() as conn:
            try:
                _ensure_xero_schema(conn)
            except ProgrammingError as e:
                logger.debug("log_assessment schema ensure: %s", e)
            try:
                conn.execute(
                    text("""
                    IF OBJECT_ID('xero.TestAssessmentLog', 'U') IS NULL
                    CREATE TABLE xero.TestAssessmentLog (
                        [RunRef] NVARCHAR(255) NOT NULL,
                        [Status] NVARCHAR(50) NOT NULL,
                        [Summary] NVARCHAR(MAX) NOT NULL,
                        [DetailsJson] NVARCHAR(MAX) NULL,
                        [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                    );
                """)
                )
            except ProgrammingError as e:
                logger.warning("log_assessment: could not create TestAssessmentLog (DDL denied?): %s", e)
            if not _xero_table_exists(conn, "TestAssessmentLog"):
                return
            conn.execute(
                text("""
                    INSERT INTO xero.TestAssessmentLog ([RunRef], [Status], [Summary], [DetailsJson], [CreatedAt])
                    VALUES (:run_ref, :status, :summary, :details_json, SYSUTCDATETIME());
                """),
                {
                    "run_ref": run_ref,
                    "status": status,
                    "summary": summary,
                    "details_json": details_json,
                },
            )
    except ProgrammingError as e:
        logger.warning("log_assessment insert failed: %s", e)


def get_pipeline_history(limit: int = 20) -> Dict[str, Any]:
    """Read log tables only; never CREATE (works with read-only / no-DDL logins)."""
    from db import engine

    eng = engine()
    run_rows: List[Dict[str, Any]] = []
    assessment_rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    lim = int(limit)

    with eng.begin() as conn:
        if _xero_table_exists(conn, "TestRunLog"):
            try:
                rr = conn.execute(
                    text("""
                        SELECT TOP (:lim) [RunRef], [EndpointName], [Status], [RowsWritten], [Details], [CreatedAt]
                        FROM xero.TestRunLog
                        ORDER BY [CreatedAt] DESC;
                    """),
                    {"lim": lim},
                )
                for row in rr:
                    run_rows.append(
                        {
                            "run_ref": row[0],
                            "endpoint_name": row[1],
                            "status": row[2],
                            "rows_written": int(row[3] or 0),
                            "details": row[4],
                            "created_at": str(row[5]) if row[5] is not None else None,
                        }
                    )
            except ProgrammingError as e:
                notes.append(f"Could not read xero.TestRunLog: {e}")
        else:
            notes.append(
                "xero.TestRunLog does not exist. A DBA can create it with sql/setup_pipeline_test_objects.sql."
            )

        if _xero_table_exists(conn, "TestAssessmentLog"):
            try:
                ar = conn.execute(
                    text("""
                        SELECT TOP (:lim) [RunRef], [Status], [Summary], [CreatedAt]
                        FROM xero.TestAssessmentLog
                        ORDER BY [CreatedAt] DESC;
                    """),
                    {"lim": lim},
                )
                for row in ar:
                    assessment_rows.append(
                        {
                            "run_ref": row[0],
                            "status": row[1],
                            "summary": row[2],
                            "created_at": str(row[3]) if row[3] is not None else None,
                        }
                    )
            except ProgrammingError as e:
                notes.append(f"Could not read xero.TestAssessmentLog: {e}")
        else:
            notes.append(
                "xero.TestAssessmentLog does not exist. A DBA can create it with sql/setup_pipeline_test_objects.sql."
            )

    return {
        "runs": run_rows,
        "assessments": assessment_rows,
        "history_notes": notes if notes else None,
    }


def save_endpoint_to_db(
    endpoint_name: str,
    rows: List[Dict[str, Any]],
    columns: List[str],
) -> int:
    """
    Upsert rows into xero.{endpoint_name}. Tables are created if missing.
    rows: list of dicts with keys = exact column names as displayed (e.g. JournalLine.Description).
    columns: same list, first is PK.
    """
    if not rows:
        return 0
    try:
        from db import engine
        eng = engine()
    except Exception as e:
        logger.warning("DB not available (missing env or import): %s", e)
        return 0

    pk_col = columns[0]
    table_name = endpoint_name.replace(" ", "_")
    q = _quote_sql_identifier

    last_err = None
    for attempt in range(DB_WRITE_RETRIES):
        try:
            with eng.begin() as conn:
                _ensure_table(conn, table_name, columns, pk_col)
                _ = _ensure_test_metadata_columns(conn, table_name)

                try:
                    table_cols = _get_table_columns(conn, table_name)
                except Exception:
                    table_cols = columns
                if not table_cols:
                    table_cols = columns
                pk_col = table_cols[0]

                for row in rows:
                    params = {}
                    for i, c in enumerate(table_cols):
                        v = _row_value(row, c)
                        params[f"p{i}"] = v if isinstance(v, (str, type(None))) else str(v) if v is not None else None
                    select_parts = [f":p{i} AS {q(c)}" for i, c in enumerate(table_cols)]
                    set_parts = [f"t.{q(c)} = s.{q(c)}" for c in table_cols if c != pk_col]
                    set_parts.append("t.[UpdatedAt] = SYSUTCDATETIME()")
                    set_clause = ", ".join(set_parts)
                    insert_cols = ", ".join(q(c) for c in table_cols) + ", [UpdatedAt]"
                    insert_vals = ", ".join(f"s.{q(c)}" for c in table_cols) + ", SYSUTCDATETIME()"
                    merge_sql = f"""
                    MERGE xero.[{table_name}] AS t
                    USING (SELECT {", ".join(select_parts)}) AS s
                    ON t.{q(pk_col)} = s.{q(pk_col)}
                    WHEN MATCHED THEN UPDATE SET {set_clause}
                    WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});
                    """
                    conn.execute(text(merge_sql), params)
            logger.info("Wrote %s rows to xero.%s", len(rows), table_name)
            return len(rows)
        except OperationalError as e:
            last_err = e
            if attempt < DB_WRITE_RETRIES - 1:
                logger.warning("DB write attempt %s/%s failed (will retry): %s", attempt + 1, DB_WRITE_RETRIES, e)
                time.sleep(DB_WRITE_RETRY_DELAY)
            else:
                raise
        except Exception as e:
            last_err = e
            if attempt < DB_WRITE_RETRIES - 1 and ("08S01" in str(getattr(e, "orig", "")) or "TCP" in str(e)):
                logger.warning("DB connection error (will retry): %s", e)
                time.sleep(DB_WRITE_RETRY_DELAY)
            else:
                raise
