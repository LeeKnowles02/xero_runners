from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from db import get_engine

engine = get_engine()

with engine.begin() as conn:
    conn.execute(text("SELECT 1 AS ok;"))
    conn.execute(text("""
        IF OBJECT_ID('xero.TestConnection', 'U') IS NULL
        CREATE TABLE xero.TestConnection (
            Id INT NOT NULL PRIMARY KEY,
            Name NVARCHAR(100) NULL
        );
    """))
    conn.execute(text("MERGE xero.TestConnection AS t USING (SELECT 1 AS Id, 'hello' AS Name) s ON t.Id=s.Id WHEN MATCHED THEN UPDATE SET Name=s.Name WHEN NOT MATCHED THEN INSERT (Id,Name) VALUES (s.Id,s.Name);"))
    row = conn.execute(text("SELECT TOP 1 * FROM xero.TestConnection WHERE Id=1;")).fetchone()

print("DB OK:", row)