-- ============================================================
-- 10_reporting_views_and_constraints.sql
--
-- Purpose:
--
-- PART A - Reporting views
--
--   v_sale_financials
--       One row per sale with product cost, scholarship and
--       estimated profit already calculated.
--
--   v_scholarship_lines
--       One row per sold product that carries a scholarship
--       contribution (scholarship_rate > 0).
--
-- PART B - CHECK constraints
--
--   Only known values can be stored in:
--       sales.sales_channel
--       sales.payment_method
--       inventory_transactions.transaction_type
--
-- Why views:
--
--   Before this script the Estimated Profit formula was written
--   out separately in the dashboard, in the Excel summary and in
--   the monthly report. If the formula ever changes, every copy
--   would have to be changed in exactly the same way.
--
--   A VIEW is a saved query. The formula now lives in ONE place
--   in the database, and every screen and report reads from it.
--
--   Scholarship queries used "WHERE product_id = 2". The view
--   uses products.scholarship_rate > 0 instead, so a second
--   licensed product would be included automatically.
--
-- Views do not store data. They always show the current
-- content of sales, sale_items and products.
--
-- Safe to run more than once.
-- ============================================================


-- ============================================================
-- PART A.1: v_sale_financials
--
-- Estimated Profit =
--       Product Revenue
--     + Shipping Revenue
--     - Product Cost
--     - Scholarship
--     - Shopify / Card Fees
--     - Shipping Expense
--
-- Sales tax collected is NOT revenue and is NOT part of profit.
--
-- Product cost uses the CURRENT products.unit_cost.
-- ============================================================

DROP VIEW IF EXISTS v_sale_financials;

CREATE VIEW v_sale_financials AS

SELECT
    s.sale_id,
    s.sale_date,
    s.sales_channel,
    s.payment_method,
    s.state,
    s.county,

    -- Product revenue only (no tax, no shipping).
    s.total_amount AS product_revenue,

    s.tax_collected,
    s.shipping_revenue,
    s.shopify_fee,
    s.shipping_expense,

    -- Total jars in the sale (all products).
    COALESCE(SUM(si.quantity), 0) AS jars_sold,

    -- Jars x cost per jar.
    COALESCE(SUM(si.quantity * p.unit_cost), 0) AS product_cost,

    -- Scholarship stored on each sale line when it was recorded.
    COALESCE(SUM(si.scholarship_amount), 0) AS scholarship,

    (
        s.total_amount
        + s.shipping_revenue
        - s.shopify_fee
        - s.shipping_expense
        - COALESCE(SUM(si.quantity * p.unit_cost), 0)
        - COALESCE(SUM(si.scholarship_amount), 0)
    ) AS estimated_profit

FROM sales AS s

LEFT JOIN sale_items AS si
    ON s.sale_id = si.sale_id

LEFT JOIN products AS p
    ON si.product_id = p.product_id

-- sale_id is the primary key of sales, so PostgreSQL allows
-- the other columns of "s" in the SELECT list.
GROUP BY
    s.sale_id;


-- ============================================================
-- PART A.2: v_scholarship_lines
--
-- Every sold line of a product that has a scholarship rate.
-- Today that is Slobberin' Sauce (16%).
-- ============================================================

DROP VIEW IF EXISTS v_scholarship_lines;

CREATE VIEW v_scholarship_lines AS

SELECT
    si.sale_item_id,
    s.sale_id,
    s.sale_date,
    s.sales_channel,
    s.payment_method,
    p.product_id,
    p.product_name,
    p.scholarship_rate,
    si.quantity,

    -- Eligible revenue: the base of the 16% calculation.
    si.allocated_revenue,

    si.scholarship_amount

FROM sale_items AS si

JOIN sales AS s
    ON si.sale_id = s.sale_id

JOIN products AS p
    ON si.product_id = p.product_id

WHERE p.scholarship_rate > 0;


-- ============================================================
-- PART B: CHECK CONSTRAINTS
--
-- A CHECK constraint makes PostgreSQL reject a row whose value
-- is not in the allowed list. This protects reports and
-- forecasts from typos such as "Farmers market" vs
-- "Farmers Market", which would otherwise be treated as two
-- different sales channels.
--
-- The lists match the choices offered in the application.
-- NULL is still allowed.
-- ============================================================


-- ------------------------------------------------------------
-- STEP B.0: SHOW VALUES THAT WOULD VIOLATE THE NEW RULES
--
-- Each query should return NO rows.
--
-- If a query returns rows, correct those values first
-- (or add the value to the list below). Otherwise the
-- ALTER TABLE statement for that column will fail and the
-- existing data will stay unchanged.
-- ------------------------------------------------------------

SELECT DISTINCT sales_channel AS unknown_sales_channel
FROM sales
WHERE sales_channel NOT IN (
    'Shopify', 'Farmers Market', 'Wholesale', 'Direct'
);

SELECT DISTINCT payment_method AS unknown_payment_method
FROM sales
WHERE payment_method NOT IN (
    'Shopify', 'Cash', 'Card', 'Venmo', 'Other'
);

SELECT DISTINCT transaction_type AS unknown_transaction_type
FROM inventory_transactions
WHERE transaction_type NOT IN (
    'OPENING_BALANCE', 'RECEIPT', 'SALE', 'SALE_VOID',
    'SAMPLE', 'DONATION', 'BROKEN', 'GIFT',
    'REPLACEMENT', 'ADJUSTMENT'
);


-- ------------------------------------------------------------
-- STEP B.1: SALES CHANNEL
-- ------------------------------------------------------------

ALTER TABLE sales
DROP CONSTRAINT IF EXISTS chk_sales_channel;

ALTER TABLE sales
ADD CONSTRAINT chk_sales_channel
CHECK (
    sales_channel IN (
        'Shopify',
        'Farmers Market',
        'Wholesale',
        'Direct'
    )
);


-- ------------------------------------------------------------
-- STEP B.2: PAYMENT METHOD
-- ------------------------------------------------------------

ALTER TABLE sales
DROP CONSTRAINT IF EXISTS chk_payment_method;

ALTER TABLE sales
ADD CONSTRAINT chk_payment_method
CHECK (
    payment_method IN (
        'Shopify',
        'Cash',
        'Card',
        'Venmo',
        'Other'
    )
);


-- ------------------------------------------------------------
-- STEP B.3: INVENTORY TRANSACTION TYPE
-- ------------------------------------------------------------

ALTER TABLE inventory_transactions
DROP CONSTRAINT IF EXISTS chk_inventory_transaction_type;

ALTER TABLE inventory_transactions
ADD CONSTRAINT chk_inventory_transaction_type
CHECK (
    transaction_type IN (
        'OPENING_BALANCE',
        'RECEIPT',
        'SALE',
        'SALE_VOID',
        'SAMPLE',
        'DONATION',
        'BROKEN',
        'GIFT',
        'REPLACEMENT',
        'ADJUSTMENT'
    )
);


-- ============================================================
-- CHECK RESULT 1: PROFIT BY MONTH FROM THE VIEW
-- ============================================================

SELECT
    DATE_TRUNC('month', sale_date)::date AS month,
    COUNT(*) AS sales_count,
    SUM(jars_sold) AS jars_sold,
    SUM(product_revenue) AS product_revenue,
    SUM(scholarship) AS scholarship,
    SUM(estimated_profit) AS estimated_profit

FROM v_sale_financials

GROUP BY
    DATE_TRUNC('month', sale_date)::date

ORDER BY
    month;


-- ============================================================
-- CHECK RESULT 2: SCHOLARSHIP BY MONTH FROM THE VIEW
-- ============================================================

SELECT
    DATE_TRUNC('month', sale_date)::date AS month,
    SUM(quantity) AS jars,
    SUM(allocated_revenue) AS eligible_revenue,
    SUM(scholarship_amount) AS scholarship

FROM v_scholarship_lines

GROUP BY
    DATE_TRUNC('month', sale_date)::date

ORDER BY
    month;


-- ============================================================
-- CHECK RESULT 3: THE THREE NEW CONSTRAINTS
-- ============================================================

SELECT
    conrelid::regclass AS table_name,
    conname AS constraint_name

FROM pg_constraint

WHERE conname IN (
    'chk_sales_channel',
    'chk_payment_method',
    'chk_inventory_transaction_type'
)

ORDER BY
    conname;

