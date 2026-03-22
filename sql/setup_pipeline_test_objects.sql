-- =============================================================================
-- Pipeline / test objects (run once as a user with CREATE TABLE permission)
-- Use when the app login gets error 262 "CREATE TABLE permission denied".
-- =============================================================================

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

-- Connection test table (optional; app falls back to SELECT 1 only if missing)
IF OBJECT_ID('xero.ConnectionTest', 'U') IS NULL
CREATE TABLE xero.ConnectionTest (
    [ID] INT NOT NULL PRIMARY KEY,
    [TestValue] NVARCHAR(100) NOT NULL,
    [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- Test run audit log (Data Pipeline Control history)
IF OBJECT_ID('xero.TestRunLog', 'U') IS NULL
CREATE TABLE xero.TestRunLog (
    [RunRef] NVARCHAR(255) NOT NULL,
    [EndpointName] NVARCHAR(255) NOT NULL,
    [Status] NVARCHAR(50) NOT NULL,
    [RowsWritten] INT NOT NULL,
    [Details] NVARCHAR(MAX) NULL,
    [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID('xero.TestAssessmentLog', 'U') IS NULL
CREATE TABLE xero.TestAssessmentLog (
    [RunRef] NVARCHAR(255) NOT NULL,
    [Status] NVARCHAR(50) NOT NULL,
    [Summary] NVARCHAR(MAX) NOT NULL,
    [DetailsJson] NVARCHAR(MAX) NULL,
    [CreatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- Optional: grant the app user read/write (replace YourAppLogin)
-- GRANT SELECT, INSERT, DELETE, UPDATE ON SCHEMA::xero TO [YourAppLogin];
