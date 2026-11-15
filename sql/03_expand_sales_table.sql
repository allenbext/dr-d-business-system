-- ============================================================
-- 03_expand_sales_table.sql
--
-- Purpose:
-- Add the financial and location fields that Dr. D currently
-- records manually in his spreadsheet.
--
-- We are adding:
--   - tax_collected
--   - shipping_revenue
--   - shopify_fee
--   - shipping_expense
--   - state
--   - county
--
-- sale_date already exists in the sales table,
-- so we do NOT add it again.
--
-- Safe to run more than once:
-- ADD COLUMN IF NOT EXISTS skips a column that already exists.
-- ============================================================

-- ============================================================
-- 1. TAX COLLECTED
--
-- This is the sales tax collected from the customer.
--
-- Important:
-- This is not business revenue.
-- Dr. D collects it and later reports/remits it.
--
-- Example:
-- Customer pays $18.00 + $0.36 tax
-- tax_collected = 0.36
--
-- DEFAULT 0 means older sales and sales without tax
-- will automatically have 0.00.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS tax_collected NUMERIC(10,2)
NOT NULL DEFAULT 0.00;

-- ============================================================
-- 2. SHIPPING REVENUE
--
-- This is the amount the CUSTOMER pays Dr. D for shipping.
--
-- Example:
-- Customer pays $8.00 for shipping
-- shipping_revenue = 8.00
--
-- This is different from shipping_expense below.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS shipping_revenue NUMERIC(10,2)
NOT NULL DEFAULT 0.00;

-- ============================================================
-- 3. SHOPIFY FEE
--
-- This is the actual transaction/payment processing fee
-- charged by Shopify.
--
-- Example:
-- Shopify charges $0.58 for the transaction
-- shopify_fee = 0.58
--
-- For cash transactions this will normally be 0.00.
--
-- Before Shopify API integration, Dr. D can enter this manually.
-- Later we will try to import it automatically from Shopify.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS shopify_fee NUMERIC(10,2)
NOT NULL DEFAULT 0.00;

-- ============================================================
-- 4. SHIPPING EXPENSE
--
-- This is what Dr. D actually pays for the shipping label.
--
-- Example:
-- Customer paid $8.00 shipping
-- Dr. D paid Shopify $6.25 for the label
--
-- shipping_revenue = 8.00
-- shipping_expense = 6.25
--
-- For an in-person Farmers Market sale this is normally 0.00.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS shipping_expense NUMERIC(10,2)
NOT NULL DEFAULT 0.00;

-- ============================================================
-- 5. STATE
--
-- State associated with the sale.
--
-- Examples:
-- NC
-- VA
-- SC
--
-- This will later help with accounting/tax reporting.
--
-- We allow NULL for now because some existing test records
-- do not have location information.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS state VARCHAR(50);

-- ============================================================
-- 6. COUNTY
--
-- County associated with the sale.
--
-- Example:
-- Wake
-- Durham
-- Orange
--
-- Dr. D needs this information for his CPA / tax reporting.
--
-- We allow NULL because:
--   - existing test records do not have county information
--   - county may not always be relevant for out-of-state sales
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS county VARCHAR(100);

-- ============================================================
-- CHECK RESULT
--
-- Show the sales table including the new columns.
-- ============================================================

SELECT *
FROM sales
ORDER BY sale_id;






