import os
import urllib.parse
from sqlalchemy import create_engine, text

_ENGINE = None

def get_engine():
    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    username = os.getenv("AZURE_SQL_USERNAME")
    password = os.getenv("AZURE_SQL_PASSWORD")

    if not all([server, database, username, password]):
        missing = [k for k in ["AZURE_SQL_SERVER","AZURE_SQL_DATABASE","AZURE_SQL_USERNAME","AZURE_SQL_PASSWORD"] if not os.getenv(k)]
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    # ODBC Driver 18 + required Azure encryption settings
    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    connect_args = urllib.parse.quote_plus(odbc)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={connect_args}", fast_executemany=True)
    return engine

def engine():
    """Single source of truth for the DB engine. Lazy-init on first use."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = get_engine()
    return _ENGINE

def smoke_test(engine):
    with engine.begin() as conn:
        conn.execute(text("SELECT 1 AS ok;"))