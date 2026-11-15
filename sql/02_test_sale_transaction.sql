
-- ============================================================
-- 02_test_sale_transaction.sql
--
-- Purpose:
-- Test how the core database tables work together.
--
-- We will record one mixed sale:
--   1 Dr. D's Original Sauce
--   1 Slobberin' Sauce
--   Total sale price = $18.00
--
-- Since this is a mixed 2-jar sale:
--   Original revenue = $9.00
--   Slobberin' revenue = $9.00
--
-- Scholarship:
--   $9.00 × 16% = $1.44
--
-- Inventory should decrease by 1 for each product.
-- ============================================================


-- ============================================================
-- STEP 1: Start a database transaction
--
-- BEGIN means:
-- "Treat all the following actions as one unit of work."
--
-- This is important because recording a sale involves
-- several tables.
--
-- We do NOT want a situation where:
--   - the sale is saved,
--   - but inventory fails to update.
--
-- With a transaction, all steps either succeed together
-- or can be rolled back together.
-- ============================================================

BEGIN;


-- ============================================================
-- STEP 2: Create the sale
--
-- This creates ONE sale/order in the sales table.
--
-- We use:
--   Farmers Market
--   Cash
--
-- only as sample values for now.
-- ============================================================

INSERT INTO sales (
    sale_date,
    sales_channel,
    payment_method,
    total_amount
)
VALUES (
    CURRENT_DATE,       -- Today's date
    'Farmers Market',   -- Where the sale happened
    'Cash',             -- How the customer paid
    18.00               -- Total sale amount
);


-- ============================================================
-- STEP 3: Add Original Sauce to the sale
--
-- currval(...) returns the ID of the sale
-- that PostgreSQL just created above.
--
-- Because sale_id is SERIAL, PostgreSQL automatically
-- generated the new sale ID for us.
--
-- product_id = 1 → Original Sauce
-- quantity = 1
-- allocated revenue = $9
-- scholarship = $0
-- ============================================================

INSERT INTO sale_items (
    sale_id,
    product_id,
    quantity,
    sale_price,
    allocated_revenue,
    scholarship_amount
)
VALUES (
    currval('sales_sale_id_seq'),
    1,
    1,
    9.00,
    9.00,
    0.00
);


-- ============================================================
-- STEP 4: Add Slobberin' Sauce to the same sale
--
-- product_id = 2 → Slobberin' Sauce
--
-- The customer paid $18 for the mixed 2-jar sale.
-- Half of that revenue belongs to Slobberin':
--
-- $18 / 2 = $9
--
-- Scholarship:
--
-- $9 × 0.16 = $1.44
-- ============================================================

INSERT INTO sale_items (
    sale_id,
    product_id,
    quantity,
    sale_price,
    allocated_revenue,
    scholarship_amount
)
VALUES (
    currval('sales_sale_id_seq'),
    2,
    1,
    9.00,
    9.00,
    1.44
);


-- ============================================================
-- STEP 5: Reduce Original Sauce inventory
--
-- current_quantity = current_quantity - 1
--
-- Before:
-- 100
--
-- After:
-- 99
-- ============================================================

UPDATE inventory
SET current_quantity = current_quantity - 1
WHERE product_id = 1;


-- ============================================================
-- STEP 6: Reduce Slobberin' Sauce inventory
--
-- Before:
-- 100
--
-- After:
-- 99
-- ============================================================

UPDATE inventory
SET current_quantity = current_quantity - 1
WHERE product_id = 2;


-- ============================================================
-- STEP 7: Save the transaction
--
-- COMMIT permanently saves all changes made since BEGIN.
-- ============================================================

COMMIT;


-- ============================================================
-- STEP 8: Check the sale
--
-- This query combines:
--   sales
--   sale_items
--   products
--
-- JOIN lets us see readable product names instead
-- of only product IDs.
-- ============================================================

SELECT
    s.sale_id,
    s.sale_date,
    s.sales_channel,
    s.payment_method,
    s.total_amount,

    p.product_name,

    si.quantity,
    si.sale_price,
    si.allocated_revenue,
    si.scholarship_amount

FROM sales AS s

JOIN sale_items AS si
    ON s.sale_id = si.sale_id

JOIN products AS p
    ON si.product_id = p.product_id

ORDER BY s.sale_id, si.sale_item_id;


-- ============================================================
-- STEP 9: Check inventory
--
-- JOIN inventory with products so we see product names.
-- ============================================================

SELECT
    p.product_name,
    i.current_quantity

FROM inventory AS i

JOIN products AS p
    ON i.product_id = p.product_id

ORDER BY p.product_id;