-- =============================================================================
-- xero.sync_run — one row per full endpoint sync / run_endpoint_selected execution
-- Run after xero schema exists. Pair with sql/setup_integration_log.sql.
-- =============================================================================

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

IF OBJECT_ID('xero.sync_run', 'U') IS NULL
CREATE TABLE xero.sync_run (
    [run_id] NVARCHAR(80) NOT NULL,
    [correlation_id] NVARCHAR(80) NULL,
    [tenant_id] NVARCHAR(80) NULL,
    [endpoint_name] NVARCHAR(255) NULL,
    [start_time] DATETIME2 NOT NULL CONSTRAINT DF_sync_run_start DEFAULT SYSUTCDATETIME(),
    [end_time] DATETIME2 NULL,
    [status] NVARCHAR(20) NOT NULL CONSTRAINT DF_sync_run_status DEFAULT N'IN_PROGRESS',
    [total_records] INT NULL,
    [total_errors] INT NOT NULL CONSTRAINT DF_sync_run_err DEFAULT 0,
    [message] NVARCHAR(MAX) NULL,
    CONSTRAINT PK_xero_sync_run PRIMARY KEY CLUSTERED ([run_id]),
    CONSTRAINT CK_sync_run_status CHECK ([status] IN (N'IN_PROGRESS', N'SUCCESS', N'FAILED'))
);
GO

CREATE NONCLUSTERED INDEX IX_sync_run_start_time
    ON xero.sync_run ([start_time] DESC);
GO

CREATE NONCLUSTERED INDEX IX_sync_run_correlation_id
    ON xero.sync_run ([correlation_id])
    WHERE [correlation_id] IS NOT NULL;
GO

-- Optional FK (run only after backfilling sync_run for existing integration_log.run_id values):
-- ALTER TABLE xero.integration_log ADD CONSTRAINT FK_integration_log_sync_run
--     FOREIGN KEY ([run_id]) REFERENCES xero.sync_run ([run_id]);
