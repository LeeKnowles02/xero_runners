"""
Persist Xero endpoint data to Azure SQL (xero schema).
Used when Run is clicked: after writing Excel, we upsert to DB so data is in SSMS too.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("xero_runner.xero_db")


def _quote_sql_identifier(name: str) -> str:
    """Quote for SQL (handles dots): JournalLine.Description -> [JournalLine.Description]."""
    s = (name or "").strip() or "value"
    return f"[{s}]"


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

    with eng.begin() as conn:
        _ensure_table(conn, table_name, columns, pk_col)

        for row in rows:
            params = {}
            for i, c in enumerate(columns):
                v = row.get(c)
                params[f"p{i}"] = v if isinstance(v, (str, type(None))) else str(v) if v is not None else None
            select_parts = [f":p{i} AS {q(c)}" for i, c in enumerate(columns)]
            set_parts = [f"t.{q(c)} = s.{q(c)}" for c in columns if c != pk_col]
            set_parts.append("t.[UpdatedAt] = SYSUTCDATETIME()")
            set_clause = ", ".join(set_parts)
            insert_cols = ", ".join(q(c) for c in columns) + ", [UpdatedAt]"
            insert_vals = ", ".join(f"s.{q(c)}" for c in columns) + ", SYSUTCDATETIME()"
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
