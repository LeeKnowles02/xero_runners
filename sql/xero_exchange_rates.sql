-- =============================================================================
-- Xero Runner: Exchange rates (Frankfurter) + process audit log
-- Run against Azure SQL as a user with CREATE TABLE on the database.
-- =============================================================================

IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'xero')
BEGIN
    EXEC('CREATE SCHEMA xero');
END
GO

IF OBJECT_ID('xero.ExchangeRates', 'U') IS NULL
BEGIN
    CREATE TABLE xero.ExchangeRates (
        ExchangeRateID BIGINT IDENTITY(1,1) NOT NULL,
        RateDate DATE NOT NULL,
        BaseCurrency CHAR(3) NOT NULL,
        QuoteCurrency CHAR(3) NOT NULL,
        Rate DECIMAL(18,8) NOT NULL,
        Provider VARCHAR(50) NULL,
        SourceSystem VARCHAR(50) NOT NULL CONSTRAINT DF_ExchangeRates_SourceSystem DEFAULT 'Frankfurter',
        LoadedAtUTC DATETIME2 NOT NULL CONSTRAINT DF_ExchangeRates_LoadedAtUTC DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_xero_ExchangeRates PRIMARY KEY CLUSTERED (ExchangeRateID),
        CONSTRAINT UQ_xero_ExchangeRates_RateDate_Base_Quote_Provider UNIQUE (
            RateDate,
            BaseCurrency,
            QuoteCurrency,
            Provider
        )
    );
END
GO

IF OBJECT_ID('xero.ProcessLog', 'U') IS NULL
BEGIN
    CREATE TABLE xero.ProcessLog (
        LogID BIGINT IDENTITY(1,1) NOT NULL,
        ProcessName VARCHAR(150) NOT NULL,
        ActionName VARCHAR(150) NOT NULL,
        Status VARCHAR(20) NOT NULL,
        Detail NVARCHAR(MAX) NULL,
        ErrorMessage NVARCHAR(MAX) NULL,
        StartedAtUTC DATETIME2 NOT NULL CONSTRAINT DF_ProcessLog_StartedAtUTC DEFAULT SYSUTCDATETIME(),
        FinishedAtUTC DATETIME2 NULL,
        CONSTRAINT PK_xero_ProcessLog PRIMARY KEY CLUSTERED (LogID),
        CONSTRAINT CK_xero_ProcessLog_Status CHECK (Status IN ('STARTED', 'SUCCESS', 'FAILED'))
    );
END
GO
