-- Run this in SSMS against your database (e.g. unleashed_runner).
-- Creates xero schema and all endpoint tables. Paste into a new query and press F5.

IF SCHEMA_ID('xero') IS NULL
    EXEC('CREATE SCHEMA xero');
GO

-- Organisation
IF OBJECT_ID('xero.Organisation', 'U') IS NULL
CREATE TABLE xero.Organisation (
    [OrganisationID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL,
    [BaseCurrency] NVARCHAR(MAX) NULL,
    [CountryCode] NVARCHAR(MAX) NULL,
    [Version] NVARCHAR(MAX) NULL,
    [OrganisationEntityType] NVARCHAR(MAX) NULL,
    [FinancialYearEndDay] NVARCHAR(MAX) NULL,
    [FinancialYearEndMonth] NVARCHAR(MAX) NULL,
    [PeriodLockDate] NVARCHAR(MAX) NULL,
    [EndOfYearLockDate] NVARCHAR(MAX) NULL,
    [CreatedDateUTC] NVARCHAR(MAX) NULL,
    [Timezone] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Organisation PRIMARY KEY ([OrganisationID])
);
GO

-- Journals
IF OBJECT_ID('xero.Journals', 'U') IS NULL
CREATE TABLE xero.Journals (
    [JournalID] NVARCHAR(255) NOT NULL,
    [JournalNumber] NVARCHAR(MAX) NULL,
    [JournalDate] NVARCHAR(MAX) NULL,
    [CreatedDateUTC] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL,
    [SourceID] NVARCHAR(MAX) NULL,
    [SourceType] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Journals PRIMARY KEY ([JournalID])
);
GO

-- JournalLines (composite PK: JournalID + row identity; we use JournalLine_AccountCode as part of row)
IF OBJECT_ID('xero.JournalLines', 'U') IS NULL
CREATE TABLE xero.JournalLines (
    [JournalID] NVARCHAR(255) NOT NULL,
    [JournalNumber] NVARCHAR(MAX) NULL,
    [JournalDate] NVARCHAR(MAX) NULL,
    [SourceType] NVARCHAR(MAX) NULL,
    [SourceID] NVARCHAR(MAX) NULL,
    [JournalLine_AccountCode] NVARCHAR(MAX) NULL,
    [JournalLine_Description] NVARCHAR(MAX) NULL,
    [JournalLine_LineAmount] NVARCHAR(MAX) NULL,
    [JournalLine_TaxType] NVARCHAR(MAX) NULL,
    [JournalLine_TaxAmount] NVARCHAR(MAX) NULL,
    [JournalLine_Tracking] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_JournalLines PRIMARY KEY ([JournalID])
);
GO

-- Contacts
IF OBJECT_ID('xero.Contacts', 'U') IS NULL
CREATE TABLE xero.Contacts (
    [ContactID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL,
    [EmailAddress] NVARCHAR(MAX) NULL,
    [ContactStatus] NVARCHAR(MAX) NULL,
    [IsCustomer] NVARCHAR(MAX) NULL,
    [IsSupplier] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Contacts PRIMARY KEY ([ContactID])
);
GO

-- Invoices
IF OBJECT_ID('xero.Invoices', 'U') IS NULL
CREATE TABLE xero.Invoices (
    [InvoiceID] NVARCHAR(255) NOT NULL,
    [InvoiceNumber] NVARCHAR(MAX) NULL,
    [Type] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL,
    [Date] NVARCHAR(MAX) NULL,
    [DueDate] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [Contact_ContactID] NVARCHAR(MAX) NULL,
    [Contact_Name] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL,
    [SubTotal] NVARCHAR(MAX) NULL,
    [TotalTax] NVARCHAR(MAX) NULL,
    [Total] NVARCHAR(MAX) NULL,
    [AmountDue] NVARCHAR(MAX) NULL,
    [AmountPaid] NVARCHAR(MAX) NULL,
    [AmountCredited] NVARCHAR(MAX) NULL,
    [CurrencyCode] NVARCHAR(MAX) NULL,
    [ExchangeRate] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Invoices PRIMARY KEY ([InvoiceID])
);
GO

-- Payments
IF OBJECT_ID('xero.Payments', 'U') IS NULL
CREATE TABLE xero.Payments (
    [PaymentID] NVARCHAR(255) NOT NULL,
    [Invoice_InvoiceID] NVARCHAR(MAX) NULL,
    [Invoice_InvoiceNumber] NVARCHAR(MAX) NULL,
    [Date] NVARCHAR(MAX) NULL,
    [Amount] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL,
    [CurrencyRate] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Payments PRIMARY KEY ([PaymentID])
);
GO

-- BankTransactions
IF OBJECT_ID('xero.BankTransactions', 'U') IS NULL
CREATE TABLE xero.BankTransactions (
    [BankTransactionID] NVARCHAR(255) NOT NULL,
    [Type] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL,
    [Date] NVARCHAR(MAX) NULL,
    [Reference] NVARCHAR(MAX) NULL,
    [Contact_ContactID] NVARCHAR(MAX) NULL,
    [Contact_Name] NVARCHAR(MAX) NULL,
    [SubTotal] NVARCHAR(MAX) NULL,
    [TotalTax] NVARCHAR(MAX) NULL,
    [Total] NVARCHAR(MAX) NULL,
    [CurrencyCode] NVARCHAR(MAX) NULL,
    [ExchangeRate] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_BankTransactions PRIMARY KEY ([BankTransactionID])
);
GO

-- Accounts
IF OBJECT_ID('xero.Accounts', 'U') IS NULL
CREATE TABLE xero.Accounts (
    [AccountID] NVARCHAR(255) NOT NULL,
    [Code] NVARCHAR(MAX) NULL,
    [Name] NVARCHAR(MAX) NULL,
    [Type] NVARCHAR(MAX) NULL,
    [Class] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL,
    [TaxType] NVARCHAR(MAX) NULL,
    [EnablePaymentsToAccount] NVARCHAR(MAX) NULL,
    [UpdatedDateUTC] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_Accounts PRIMARY KEY ([AccountID])
);
GO

-- TrackingCategories
IF OBJECT_ID('xero.TrackingCategories', 'U') IS NULL
CREATE TABLE xero.TrackingCategories (
    [TrackingCategoryID] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL,
    [Options] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_TrackingCategories PRIMARY KEY ([TrackingCategoryID])
);
GO

-- TaxRates (TaxType can repeat for different names; use TaxType + Name as PK for uniqueness)
IF OBJECT_ID('xero.TaxRates', 'U') IS NULL
CREATE TABLE xero.TaxRates (
    [TaxType] NVARCHAR(255) NOT NULL,
    [Name] NVARCHAR(MAX) NULL,
    [Status] NVARCHAR(MAX) NULL,
    [ReportTaxType] NVARCHAR(MAX) NULL,
    [CanApplyToAssets] NVARCHAR(MAX) NULL,
    [CanApplyToEquity] NVARCHAR(MAX) NULL,
    [CanApplyToExpenses] NVARCHAR(MAX) NULL,
    [CanApplyToLiabilities] NVARCHAR(MAX) NULL,
    [CanApplyToRevenue] NVARCHAR(MAX) NULL,
    [UpdatedAt] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_xero_TaxRates PRIMARY KEY ([TaxType])
);
GO
