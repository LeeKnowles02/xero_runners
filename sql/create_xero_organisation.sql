-- Run this in SSMS against your database (e.g. unleashed_runner) to create
-- the xero schema and Organisation table. Use a login that has CREATE rights.
-- After this, run the Organisation endpoint again in the app; data will MERGE into this table.

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

IF OBJECT_ID('xero.Organisation', 'U') IS NULL
CREATE TABLE xero.Organisation (
    [OrganisationID]   NVARCHAR(255) NOT NULL,
    [Name]             NVARCHAR(MAX) NULL,
    [BaseCurrency]     NVARCHAR(MAX) NULL,
    [CountryCode]      NVARCHAR(MAX) NULL,
    [Version]          NVARCHAR(MAX) NULL,
    [OrganisationEntityType] NVARCHAR(MAX) NULL,
    [FinancialYearEndDay]    NVARCHAR(MAX) NULL,
    [FinancialYearEndMonth] NVARCHAR(MAX) NULL,
    [PeriodLockDate]   NVARCHAR(MAX) NULL,
    [EndOfYearLockDate] NVARCHAR(MAX) NULL,
    [CreatedDateUTC]   NVARCHAR(MAX) NULL,
    [Timezone]         NVARCHAR(MAX) NULL,
    [UpdatedAt]        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Organisation PRIMARY KEY ([OrganisationID])
);
GO
