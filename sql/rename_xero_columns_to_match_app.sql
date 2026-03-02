-- =============================================================================
-- RENAME XERO TABLE COLUMNS TO MATCH THE APP (xero_jobs.py ENDPOINTS)
-- Run this on existing xero tables when columns were created with underscores
-- (e.g. Contact_ContactID) and you want them to match the app (Contact.ContactID).
-- Safe to run multiple times: renames only if the old column exists.
-- =============================================================================

-- Invoices: Contact.ContactID, Contact.Name
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'Invoices' AND COLUMN_NAME = 'Contact_ContactID')
    EXEC sp_rename 'xero.Invoices.Contact_ContactID', 'Contact.ContactID', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'Invoices' AND COLUMN_NAME = 'Contact_Name')
    EXEC sp_rename 'xero.Invoices.Contact_Name', 'Contact.Name', 'COLUMN';
GO

-- Payments: Invoice.InvoiceID, Invoice.InvoiceNumber
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'Payments' AND COLUMN_NAME = 'Invoice_InvoiceID')
    EXEC sp_rename 'xero.Payments.Invoice_InvoiceID', 'Invoice.InvoiceID', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'Payments' AND COLUMN_NAME = 'Invoice_InvoiceNumber')
    EXEC sp_rename 'xero.Payments.Invoice_InvoiceNumber', 'Invoice.InvoiceNumber', 'COLUMN';
GO

-- BankTransactions: Contact.ContactID, Contact.Name
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'BankTransactions' AND COLUMN_NAME = 'Contact_ContactID')
    EXEC sp_rename 'xero.BankTransactions.Contact_ContactID', 'Contact.ContactID', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'BankTransactions' AND COLUMN_NAME = 'Contact_Name')
    EXEC sp_rename 'xero.BankTransactions.Contact_Name', 'Contact.Name', 'COLUMN';
GO

-- JournalLines: JournalLine.*
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_AccountCode')
    EXEC sp_rename 'xero.JournalLines.JournalLine_AccountCode', 'JournalLine.AccountCode', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_Description')
    EXEC sp_rename 'xero.JournalLines.JournalLine_Description', 'JournalLine.Description', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_LineAmount')
    EXEC sp_rename 'xero.JournalLines.JournalLine_LineAmount', 'JournalLine.LineAmount', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_TaxType')
    EXEC sp_rename 'xero.JournalLines.JournalLine_TaxType', 'JournalLine.TaxType', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_TaxAmount')
    EXEC sp_rename 'xero.JournalLines.JournalLine_TaxAmount', 'JournalLine.TaxAmount', 'COLUMN';
GO
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'xero' AND TABLE_NAME = 'JournalLines' AND COLUMN_NAME = 'JournalLine_Tracking')
    EXEC sp_rename 'xero.JournalLines.JournalLine_Tracking', 'JournalLine.Tracking', 'COLUMN';
GO

-- =============================================================================
-- Done. Columns now match app names (e.g. [Contact.ContactID], [JournalLine.Description]).
-- =============================================================================
