-- =============================================================================
-- xero.integration_log — detailed audit / troubleshooting log for Xero Runner
-- Run as a user with CREATE TABLE on the target database (or merge into setup_xero_schema).
-- =============================================================================

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

IF OBJECT_ID('xero.integration_log', 'U') IS NULL
CREATE TABLE xero.integration_log (
    [id] BIGINT IDENTITY(1,1) NOT NULL,
    [created_at] DATETIME2 NOT NULL CONSTRAINT DF_integration_log_created_at DEFAULT SYSUTCDATETIME(),
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
    [status] NVARCHAR(50) NULL,
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
    CONSTRAINT PK_xero_integration_log PRIMARY KEY CLUSTERED ([id])
);
GO

CREATE NONCLUSTERED INDEX IX_integration_log_created_at
    ON xero.integration_log ([created_at] DESC);
GO

CREATE NONCLUSTERED INDEX IX_integration_log_run_id
    ON xero.integration_log ([run_id])
    WHERE [run_id] IS NOT NULL;
GO

CREATE NONCLUSTERED INDEX IX_integration_log_tenant_id
    ON xero.integration_log ([tenant_id])
    WHERE [tenant_id] IS NOT NULL;
GO
