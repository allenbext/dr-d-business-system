-- ============================================================
-- 08_forecast_integrity.sql
--
-- Purpose:
-- Guarantee that only ONE forecast can be saved for the same
--
--     product / region / sales channel / forecast week
--
-- Why:
-- The project requirement says that a saved forecast must not
-- change after it is created. If the "Generate & Save Forecast"
-- button is clicked twice, the forecasts table would contain two
-- rows for the same week, and Forecast vs Actual would show the
-- same week twice.
--
-- This script:
--   1. Shows duplicates that already exist (if any).
--   2. Removes the duplicates, keeping the FIRST saved forecast.
--   3. Creates a UNIQUE index so duplicates cannot be saved again.
--
-- Safe to run more than once.
-- ============================================================


-- ============================================================
-- STEP 1: SHOW EXISTING DUPLICATES
--
-- If this query returns no rows, there is nothing to clean up.
-- ============================================================

SELECT
    product_id,
    sales_region,
    sales_channel,
    forecast_week,
    COUNT(*) AS saved_copies

FROM forecasts

GROUP BY
    product_id,
    sales_region,
    sales_channel,
    forecast_week

HAVING COUNT(*) > 1

ORDER BY
    forecast_week;


-- ============================================================
-- STEP 2: REMOVE DUPLICATES
--
-- For every product / region / channel / week we keep the row
-- with the SMALLEST forecast_id. That is the forecast that was
-- saved first, which is the "original" forecast.
--
-- Later copies are deleted.
-- ============================================================

DELETE FROM forecasts AS later_copy

USING forecasts AS original

WHERE later_copy.product_id    = original.product_id
  AND later_copy.sales_region  = original.sales_region
  AND later_copy.sales_channel = original.sales_channel
  AND later_copy.forecast_week = original.forecast_week
  AND later_copy.forecast_id   > original.forecast_id;


-- ============================================================
-- STEP 3: UNIQUE INDEX
--
-- From now on PostgreSQL itself rejects a second forecast for
-- the same product / region / channel / week.
--
-- forecast_service.py checks this before saving and shows a
-- friendly message. The index is the final safety net.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_forecasts_segment_week

ON forecasts (
    product_id,
    sales_region,
    sales_channel,
    forecast_week
);


-- ============================================================
-- CHECK RESULT
--
-- The new index should appear in this list.
-- ============================================================

SELECT
    indexname,
    indexdef

FROM pg_indexes

WHERE tablename = 'forecasts'

ORDER BY
    indexname;

