-- ============================================================
-- 09_sale_price_per_jar.sql
--
-- Purpose:
-- Give sale_items.sale_price ONE clear meaning:
--
--     sale_price = average realized price PER JAR
--
-- Why:
-- Until now the column was filled in two different ways:
--
--   - manual sales and the demo dataset stored the LINE TOTAL
--     (2 jars for $18.00 -> sale_price = 18.00)
--
--   - the Shopify import stored the PRICE PER JAR
--     (2 jars for $18.00 -> sale_price = 9.00)
--
-- A column must mean the same thing in every row.
--
-- The line total is not lost. It is stored separately in:
--
--     sale_items.allocated_revenue
--
-- From now on sale_service.py and shopify_import_service.py
-- both store the price per jar.
--
-- This script converts the rows that already exist.
--
-- Safe to run more than once:
-- a row that is already per jar gives the same result again.
-- ============================================================


-- ============================================================
-- STEP 1: SHOW ROWS THAT WILL CHANGE
--
-- These are rows where sale_price is not equal to
-- allocated_revenue / quantity.
-- ============================================================

SELECT
    sale_item_id,
    sale_id,
    product_id,
    quantity,
    sale_price AS old_sale_price,
    ROUND(allocated_revenue / quantity, 2) AS new_sale_price,
    allocated_revenue

FROM sale_items

WHERE allocated_revenue IS NOT NULL
  AND sale_price <> ROUND(allocated_revenue / quantity, 2)

ORDER BY
    sale_item_id;


-- ============================================================
-- STEP 2: CONVERT TO PRICE PER JAR
--
-- Example:
--
--   120 jars, allocated_revenue = 1080.00
--   old sale_price = 1080.00
--   new sale_price = 1080.00 / 120 = 9.00
-- ============================================================

UPDATE sale_items

SET sale_price = ROUND(allocated_revenue / quantity, 2)

WHERE allocated_revenue IS NOT NULL
  AND sale_price <> ROUND(allocated_revenue / quantity, 2);


-- ============================================================
-- STEP 3: DOCUMENT THE COLUMNS INSIDE THE DATABASE
--
-- COMMENT ON stores a description in PostgreSQL itself.
-- DBeaver shows it next to the column.
-- ============================================================

COMMENT ON COLUMN sale_items.sale_price IS
    'Average realized price PER JAR (allocated_revenue / quantity).';

COMMENT ON COLUMN sale_items.allocated_revenue IS
    'Product revenue assigned to this line (line total). Scholarship is calculated from this value.';


-- ============================================================
-- CHECK RESULT
--
-- quantity x sale_price should be approximately equal to
-- allocated_revenue (a difference of a few cents is possible
-- because the price per jar is rounded).
-- ============================================================

SELECT
    si.sale_id,
    p.product_name,
    si.quantity,
    si.sale_price,
    si.allocated_revenue,
    si.scholarship_amount

FROM sale_items AS si

JOIN products AS p
    ON si.product_id = p.product_id

ORDER BY
    si.sale_id,
    si.product_id;

