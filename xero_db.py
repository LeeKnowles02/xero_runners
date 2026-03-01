"""
Persist Xero endpoint data to Azure SQL (xero schema).
Used when Run is clicked: after writing Excel, we upsert to DB so data is in SSMS too.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("xero_runner.xero_db")


def _col_to_sql(name: str) -> str:
    """SQL-safe column name: Contact.Name -> Contact_Name."""
    return (name or "").replace(".", "_").replace(" ", "_").strip() or "value"


def col_to_sql(name: str) -> str:
    """Public alias for building row dicts in callers."""
    return _col_to_sql(name)


def _ensure_xero_schema(conn) -> None:
    """Create xero schema if it doesn't exist."""
    conn.execute(text("IF SCHEMA_ID('xero') IS NULL EXEC('CREATE SCHEMA xero');"))


def _ensure_table(conn, table_name: str, sql_columns: List[str], pk_column: str) -> None:
    """Create table xero.{table_name} if not exists with columns as NVARCHAR(MAX), pk as PK."""
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
    parts = [f"[{c}] NVARCHAR(255)" if c == pk_column else f"[{c}] NVARCHAR(MAX)" for c in sql_columns]
    cols_sql = ", ".join(parts) + ", [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()"
    sql = f"CREATE TABLE {full_name} ({cols_sql}, CONSTRAINT PK_xero_{table_name} PRIMARY KEY ([{pk_column}]));"
    conn.execute(text(sql))
    logger.info("Created table %s", full_name)


def save_endpoint_to_db(
    endpoint_name: str,
    rows: List[Dict[str, Any]],
    columns: List[str],
) -> int:
    """
    Upsert rows into xero.{endpoint_name}. Tables are created if missing.
    rows: list of dicts with keys = SQL column names (_col_to_sql(column)), values = scalars.
    columns: original column names (first is used as PK for table creation).
    Returns number of rows written. On any error, logs and returns 0 so Excel flow is unaffected.
    """
    if not rows:
        return 0
    try:
        from db import engine
        eng = engine()
    except Exception as e:
        logger.warning("DB not available (missing env or import): %s", e)
        return 0

    sql_columns = [_col_to_sql(c) for c in columns]
    pk_col = sql_columns[0]
    table_name = endpoint_name.replace(" ", "_")

    with eng.begin() as conn:
        _ensure_table(conn, table_name, sql_columns, pk_col)

        # MERGE one row at a time (simple and reliable)
        for row in rows:
            params = {}
            for c in sql_columns:
                v = row.get(c)
                params[c] = v if isinstance(v, (str, type(None))) else str(v) if v is not None else None
            set_parts = [f"t.[{c}] = s.[{c}]" for c in sql_columns if c != pk_col]
            set_parts.append("t.[UpdatedAt] = SYSUTCDATETIME()")
            set_clause = ", ".join(set_parts)
            insert_cols = ", ".join(f"[{c}]" for c in sql_columns) + ", [UpdatedAt]"
            insert_vals = ", ".join(f"s.[{c}]" for c in sql_columns) + ", SYSUTCDATETIME()"
            merge_sql = f"""
            MERGE xero.[{table_name}] AS t
            USING (SELECT {", ".join(f":{c} AS [{c}]" for c in sql_columns)}) AS s
            ON t.[{pk_col}] = s.[{pk_col}]
            WHEN MATCHED THEN UPDATE SET {set_clause}
            WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});
            """
            conn.execute(text(merge_sql), params)

    logger.info("Wrote %s rows to xero.%s", len(rows), table_name)
    return len(rows)
