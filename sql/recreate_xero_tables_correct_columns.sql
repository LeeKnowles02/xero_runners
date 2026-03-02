-- =============================================================================
-- RECREATE ALL XERO TABLES WITH COLUMN NAMES EXACTLY AS DISPLAYED IN THE APP
-- (Same as xero_jobs.py ENDPOINTS -> columns; dots kept e.g. JournalLine.Description)
-- =============================================================================
-- WARNING: DROPS existing xero.* tables and deletes all data. Run only if OK with that.
-- =============================================================================

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

IF OBJECT_ID('xero.Organisation', 'U') IS NOT NULL DROP TABLE xero.Organisation;
IF OBJECT_ID('xero.Journals', 'U') IS NOT NULL DROP TABLE xero.Journals;
IF OBJECT_ID('xero.JournalLines', 'U') IS NOT NULL DROP TABLE xero.JournalLines;
IF OBJECT_ID('xero.Contacts', 'U') IS NOT NULL DROP TABLE xero.Contacts;
IF OBJECT_ID('xero.Invoices', 'U') IS NOT NULL DROP TABLE xero.Invoices;
IF OBJECT_ID('xero.Payments', 'U') IS NOT NULL DROP TABLE xero.Payments;
IF OBJECT_ID('xero.BankTransactions', 'U') IS NOT NULL DROP TABLE xero.BankTransactions;
IF OBJECT_ID('xero.Accounts', 'U') IS NOT NULL DROP TABLE xero.Accounts;
IF OBJECT_ID('xero.TrackingCategories', 'U') IS NOT NULL DROP TABLE xero.TrackingCategories;
IF OBJECT_ID('xero.TaxRates', 'U') IS NOT NULL DROP TABLE xero.TaxRates;
GO

-- Organisation
CREATE TABLE xero.Organisation (
    [OrganisationID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL, [BaseCurrency] NVARCHAR(MAX) NULL, [CountryCode] NVARCHAR(MAX) NULL,
    [Version] NVARCHAR(MAX) NULL, [OrganisationEntityType] NVARCHAR(MAX) NULL,
    [FinancialYearEndDay] NVARCHAR(MAX) NULL, [FinancialYearEndMonth] NVARCHAR(MAX) NULL,
    [PeriodLockDate] NVARCHAR(MAX) NULL, [EndOfYearLockDate] NVARCHAR(MAX) NULL,
    [CreatedDateUTC] NVARCHAR(MAX) NULL, [Timezone] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Organisation PRIMARY KEY ([OrganisationID]));
GO

-- Journals
CREATE TABLE xero.Journals (
    [JournalID] NVARCHAR(255) NOT NULL,
    [JournalNumber] NVARCHAR(MAX) NULL, [JournalDate] NVARCHAR(MAX) NULL, [CreatedDateUTC] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL, [SourceID] NVARCHAR(MAX) NULL, [SourceType] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Journals PRIMARY KEY ([JournalID]));
GO

-- JournalLines (column names exactly as in app: JournalLine.AccountCode etc.)
CREATE TABLE xero.JournalLines (
    [JournalID] NVARCHAR(255) NOT NULL,
    [JournalNumber] NVARCHAR(MAX) NULL, [JournalDate] NVARCHAR(MAX) NULL,
    [SourceType] NVARCHAR(MAX) NULL, [SourceID] NVARCHAR(MAX) NULL,
    [JournalLine.AccountCode] NVARCHAR(MAX) NULL, [JournalLine.Description] NVARCHAR(MAX) NULL,
    [JournalLine.LineAmount] NVARCHAR(MAX) NULL, [JournalLine.TaxType] NVARCHAR(MAX) NULL,
    [JournalLine.TaxAmount] NVARCHAR(MAX) NULL, [JournalLine.Tracking] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_JournalLines PRIMARY KEY ([JournalID]));
GO

-- Contacts
CREATE TABLE xero.Contacts (
    [ContactID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL, [EmailAddress] NVARCHAR(MAX) NULL, [ContactStatus] NVARCHAR(MAX) NULL,
    [IsCustomer] NVARCHAR(MAX) NULL, [IsSupplier] NVARCHAR(MAX) NULL, [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Contacts PRIMARY KEY ([ContactID]));
GO

-- Invoices (Contact.ContactID, Contact.Name as in app)
CREATE TABLE xero.Invoices (
    [InvoiceID] NVARCHAR(255) NOT NULL,
    [InvoiceNumber] NVARCHAR(MAX) NULL, [Type] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL,
    [Date] NVARCHAR(MAX) NULL, [DueDate] NVARCHAR(MAX) NULL, [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [Contact.ContactID] NVARCHAR(MAX) NULL, [Contact.Name] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL, [SubTotal] NVARCHAR(MAX) NULL, [TotalTax] NVARCHAR(MAX) NULL,
    [Total] NVARCHAR(MAX) NULL, [AmountDue] NVARCHAR(MAX) NULL, [AmountPaid] NVARCHAR(MAX) NULL,
    [AmountCredited] NVARCHAR(MAX) NULL, [CurrencyCode] NVARCHAR(MAX) NULL, [ExchangeRate] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Invoices PRIMARY KEY ([InvoiceID]));
GO

-- Payments (Invoice.InvoiceID, Invoice.InvoiceNumber as in app)
CREATE TABLE xero.Payments (
    [PaymentID] NVARCHAR(255) NOT NULL,
    [Invoice.InvoiceID] NVARCHAR(MAX) NULL, [Invoice.InvoiceNumber] NVARCHAR(MAX) NULL,
    [Date] NVARCHAR(MAX) NULL, [Amount] NVARCHAR(MAX) NULL, [Reference] NVARCHAR(MAX) NULL,
    [CurrencyRate] NVARCHAR(MAX) NULL, [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Payments PRIMARY KEY ([PaymentID]));
GO

-- BankTransactions (Contact.ContactID, Contact.Name as in app)
CREATE TABLE xero.BankTransactions (
    [BankTransactionID] NVARCHAR(255) NOT NULL,
    [Type] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL, [Date] NVARCHAR(MAX) NULL, [Reference] NVARCHAR(MAX) NULL,
    [Contact.ContactID] NVARCHAR(MAX) NULL, [Contact.Name] NVARCHAR(MAX) NULL,
    [SubTotal] NVARCHAR(MAX) NULL, [TotalTax] NVARCHAR(MAX) NULL, [Total] NVARCHAR(MAX) NULL,
    [CurrencyCode] NVARCHAR(MAX) NULL, [ExchangeRate] NVARCHAR(MAX) NULL, [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_BankTransactions PRIMARY KEY ([BankTransactionID]));
GO

-- Accounts
CREATE TABLE xero.Accounts (
    [AccountID] NVARCHAR(255) NOT NULL,
    [Code] NVARCHAR(MAX) NULL, [Name] NVARCHAR(MAX) NULL, [Type] NVARCHAR(MAX) NULL, [Class] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL, [TaxType] NVARCHAR(MAX) NULL, [EnablePaymentsToAccount] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Accounts PRIMARY KEY ([AccountID]));
GO

-- TrackingCategories
CREATE TABLE xero.TrackingCategories (
    [TrackingCategoryID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL, [Options] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_TrackingCategories PRIMARY KEY ([TrackingCategoryID]));
GO

-- TaxRates
CREATE TABLE xero.TaxRates (
    [TaxType] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL, [ReportTaxType] NVARCHAR(MAX) NULL,
    [CanApplyToAssets] NVARCHAR(MAX) NULL, [CanApplyToEquity] NVARCHAR(MAX) NULL, [CanApplyToExpenses] NVARCHAR(MAX) NULL,
    [CanApplyToLiabilities] NVARCHAR(MAX) NULL, [CanApplyToRevenue] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_TaxRates PRIMARY KEY ([TaxType]));
GO
