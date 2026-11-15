-- ============================================================
-- 06_load_compact_demo_dataset.sql
--
-- Purpose:
-- Load a clean, compact demonstration dataset for
-- Dr. D's Business System.
--
-- IMPORTANT:
-- This is DEMO DATA. It is inspired by Dr. D's spreadsheet and
-- answers, but it is simplified and internally consistent for
-- the Project 2 presentation.
--
-- ALL DATES ARE RELATIVE TO TODAY.
--
-- The script can be run on any day and the application will
-- always show a meaningful picture:
--
--   - the Dashboard has sales in the current month;
--   - the forecast history ends with LAST week;
--   - the completed forecast (120 vs actual 110) is last week;
--   - next week's forecast is 117 jars.
--
-- >>> Run this script again shortly before the presentation
-- >>> (the same week). If the data is several weeks old, the
-- >>> weeks without sales count as zero demand and the forecast
-- >>> becomes lower. That is correct behavior for real data,
-- >>> but not what the demonstration is meant to show.
--
-- What the script does:
--
--   1. Removes all sales, inventory movements, batches and
--      forecasts. Products stay.
--   2. Resets the 12 monthly seasonal settings.
--   3. Receives one manufacturer batch per product.
--   4. Loads the demonstration sales.
--   5. Records samples and a donation.
--   6. Saves one completed forecast.
--
-- The dataset demonstrates:
--
--   Function 1  Mixed sale: $18 -> $9 / $9 -> $1.44 scholarship
--   Function 2  Inventory decreases with every sale
--   Function 3  Baseline 100 x 1.20 = 120, actual 110, difference -10
--   Bonus       Monthly scholarship report: 4 jars, $5.92
--   Also        Wholesale, Farmers Market summary (cash + card),
--               samples and donations
--
-- Safe to run more than once. It can be run at any time after
-- script 05, also after scripts 07 - 10.
-- ============================================================


BEGIN;


-- ============================================================
-- STEP 1: REMOVE CURRENT TRANSACTIONS
--
-- Product master data stays.
-- RESTART IDENTITY makes the new IDs start at 1 again.
-- ============================================================

TRUNCATE TABLE
    forecasts,
    inventory_transactions,
    inventory_batches,
    sale_items,
    sales
RESTART IDENTITY;

UPDATE inventory
SET current_quantity = 0;


-- ============================================================
-- STEP 2: DEMO CALENDAR
--
-- One row with every date the script needs.
--
-- this_week   = Monday of the current week
-- last_week   = Monday of the last COMPLETE week
-- report_month = first day of the month three months ago.
--               It contains ONLY the three scholarship demo
--               sales, so its monthly report is exactly
--               4 jars and $5.92.
--
-- A TEMPORARY table disappears automatically when the
-- database session ends.
-- ============================================================

DROP TABLE IF EXISTS demo_calendar;

CREATE TEMPORARY TABLE demo_calendar AS

SELECT
    CURRENT_DATE AS today,

    DATE_TRUNC('week', CURRENT_DATE)::date AS this_week,

    (DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '7 days')::date
        AS last_week,

    (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')::date
        AS report_month;


-- ============================================================
-- STEP 3: SEASONAL SETTINGS
--
-- 3a. Reset all months to the prototype defaults:
--
--       January - February    LOW     0.80
--       March   - August      MEDIUM  1.00
--       September - December  HIGH    1.20
--
-- 3b. The months covered by the forecast demonstration are set
--     to HIGH / 1.20, whatever the calendar month is.
--
--     This guarantees the Phase 1 demonstration numbers on any
--     day of the year:
--
--       weekly sales 120 / 1.20 = baseline 100
--       baseline 100 x 1.20     = forecast 120
-- ============================================================

UPDATE forecast_seasonality
SET
    demand_tier = CASE
        WHEN month_number IN (1, 2) THEN 'LOW'
        WHEN month_number BETWEEN 3 AND 8 THEN 'MEDIUM'
        ELSE 'HIGH'
    END,

    seasonal_factor = CASE
        WHEN month_number IN (1, 2) THEN 0.800
        WHEN month_number BETWEEN 3 AND 8 THEN 1.000
        ELSE 1.200
    END,

    notes = 'Prototype seasonal assumption.',

    updated_at = CURRENT_TIMESTAMP;


UPDATE forecast_seasonality
SET
    demand_tier = 'HIGH',
    seasonal_factor = 1.200,
    notes = 'Project 2 demo seasonal assumption.',
    updated_at = CURRENT_TIMESTAMP

WHERE month_number IN (

    -- Every calendar month between the first training week
    -- (5 weeks before this week) and two weeks from now.
    SELECT DISTINCT EXTRACT(MONTH FROM demo_day)::int

    FROM demo_calendar,

         GENERATE_SERIES(
             this_week - 35,
             this_week + 20,
             INTERVAL '1 day'
         ) AS demo_day
);


-- ============================================================
-- STEP 4: HELPER FUNCTION demo_sale()
--
-- Records one complete sale exactly the way the application
-- does (sale_service.py):
--
--   1. sales row
--   2. sale_items row per product
--        - revenue is shared by jar count
--        - Slobberin' share is rounded to cents,
--          Original share is the remainder
--        - scholarship = Slobberin' revenue x scholarship rate
--        - sale_price  = average price per jar
--   3. inventory decrease
--   4. inventory SALE transaction
--
-- "pg_temp." makes the function temporary. It disappears
-- when the database session ends and is not part of the
-- permanent database design.
-- ============================================================

CREATE OR REPLACE FUNCTION pg_temp.demo_sale(
    p_sale_date         DATE,
    p_channel           VARCHAR,
    p_payment           VARCHAR,
    p_original_qty      INTEGER,
    p_slobberin_qty     INTEGER,
    p_revenue           NUMERIC,
    p_tax               NUMERIC DEFAULT 0,
    p_shipping_revenue  NUMERIC DEFAULT 0,
    p_fee               NUMERIC DEFAULT 0,
    p_shipping_expense  NUMERIC DEFAULT 0,
    p_note              TEXT    DEFAULT 'Demo sale.'
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE

    v_sale_id            INTEGER;
    v_total_qty          INTEGER := p_original_qty + p_slobberin_qty;
    v_slobberin_revenue  NUMERIC(10,2);
    v_original_revenue   NUMERIC(10,2);
    v_slobberin_rate     NUMERIC;

BEGIN

    -- --------------------------------------------------------
    -- 1. SALE HEADER
    -- --------------------------------------------------------

    INSERT INTO sales (
        sale_date,
        sales_channel,
        payment_method,
        total_amount,
        tax_collected,
        shipping_revenue,
        shopify_fee,
        shipping_expense,
        state,
        county
    )
    VALUES (
        p_sale_date,
        p_channel,
        p_payment,
        p_revenue,
        p_tax,
        p_shipping_revenue,
        p_fee,
        p_shipping_expense,
        'NC',
        'Wake'
    )
    RETURNING sale_id
    INTO v_sale_id;

    -- --------------------------------------------------------
    -- REVENUE ALLOCATION
    -- --------------------------------------------------------

    v_slobberin_revenue :=
        ROUND(p_revenue * p_slobberin_qty / v_total_qty, 2);

    v_original_revenue :=
        p_revenue - v_slobberin_revenue;

    SELECT scholarship_rate
    INTO v_slobberin_rate
    FROM products
    WHERE product_id = 2;

    -- --------------------------------------------------------
    -- 2 - 4. ORIGINAL SAUCE (product_id = 1)
    -- --------------------------------------------------------

    IF p_original_qty > 0 THEN

        INSERT INTO sale_items (
            sale_id,
            product_id,
            quantity,
            sale_price,
            allocated_revenue,
            scholarship_amount
        )
        VALUES (
            v_sale_id,
            1,
            p_original_qty,
            ROUND(v_original_revenue / p_original_qty, 2),
            v_original_revenue,
            0.00
        );

        UPDATE inventory
        SET current_quantity = current_quantity - p_original_qty
        WHERE product_id = 1;

        INSERT INTO inventory_transactions (
            product_id,
            transaction_date,
            transaction_type,
            quantity_change,
            sale_id,
            notes
        )
        VALUES (
            1,
            p_sale_date,
            'SALE',
            -p_original_qty,
            v_sale_id,
            p_note
        );

    END IF;

    -- --------------------------------------------------------
    -- 2 - 4. SLOBBERIN' SAUCE (product_id = 2)
    -- --------------------------------------------------------

    IF p_slobberin_qty > 0 THEN

        INSERT INTO sale_items (
            sale_id,
            product_id,
            quantity,
            sale_price,
            allocated_revenue,
            scholarship_amount
        )
        VALUES (
            v_sale_id,
            2,
            p_slobberin_qty,
            ROUND(v_slobberin_revenue / p_slobberin_qty, 2),
            v_slobberin_revenue,
            ROUND(v_slobberin_revenue * v_slobberin_rate, 2)
        );

        UPDATE inventory
        SET current_quantity = current_quantity - p_slobberin_qty
        WHERE product_id = 2;

        INSERT INTO inventory_transactions (
            product_id,
            transaction_date,
            transaction_type,
            quantity_change,
            sale_id,
            notes
        )
        VALUES (
            2,
            p_sale_date,
            'SALE',
            -p_slobberin_qty,
            v_sale_id,
            p_note
        );

    END IF;

    RETURN v_sale_id;

END;
$$;


-- ============================================================
-- STEP 5: MANUFACTURER BATCHES
--
-- One batch per product, received on the first day of the
-- report month (before every demo sale).
--
-- Quantities are similar in scale to Dr. D's real batches.
-- ============================================================

INSERT INTO inventory_batches (
    product_id,
    batch_code,
    received_date,
    quantity_received,
    manufacturer,
    notes
)
SELECT
    batch.product_id,
    batch.batch_code,
    c.report_month,
    batch.quantity_received,
    'Demo Co-Packer',
    batch.notes

FROM demo_calendar AS c,

     (VALUES
         (1, 'DEMO-DD-BATCH-01', 1128,
             'Demo Original Sauce production batch.'),
         (2, 'DEMO-SS-BATCH-01', 1191,
             'Demo Slobberin'' Sauce production batch.')
     ) AS batch (product_id, batch_code, quantity_received, notes);


-- Audit trail: one RECEIPT transaction per batch.

INSERT INTO inventory_transactions (
    product_id,
    batch_id,
    transaction_date,
    transaction_type,
    quantity_change,
    notes
)
SELECT
    product_id,
    batch_id,
    received_date,
    'RECEIPT',
    quantity_received,
    'Manufacturer batch received.'

FROM inventory_batches;


-- Current balance = jars received.

UPDATE inventory AS i
SET current_quantity = b.quantity_received
FROM inventory_batches AS b
WHERE i.product_id = b.product_id;


-- ============================================================
-- STEP 6: SCHOLARSHIP REPORT DEMONSTRATION
--
-- Three sales in the report month (three months ago):
--
--   1 SS for $10          -> $1.60 scholarship
--   2 SS for $18          -> $2.88 scholarship
--   Mixed DD + SS for $18 -> $1.44 scholarship
--
-- Monthly report for that month:
--
--   4 Slobberin' jars, $37.00 eligible revenue, $5.92
--
-- Arguments of demo_sale():
--   date, channel, payment,
--   Original jars, Slobberin' jars, product revenue,
--   tax, shipping revenue, fee, shipping expense, note
-- ============================================================

SELECT
    pg_temp.demo_sale(
        report_month + 19, 'Farmers Market', 'Cash',
        0, 1, 10.00,
        0.20, 0, 0, 0,
        'Demo scholarship sale: one SS jar.'
    ),

    pg_temp.demo_sale(
        report_month + 20, 'Farmers Market', 'Cash',
        0, 2, 18.00,
        0.36, 0, 0, 0,
        'Demo scholarship sale: two SS jars.'
    ),

    pg_temp.demo_sale(
        report_month + 21, 'Farmers Market', 'Card',
        1, 1, 18.00,
        0.36, 0, 0.58, 0,
        'Demo mixed sale.'
    )

FROM demo_calendar;


-- ============================================================
-- STEP 7: FORECAST TRAINING HISTORY
--
-- Four weekly Shopify / Wake County sales of Slobberin' Sauce,
-- 120 jars each, in the weeks 5, 4, 3 and 2 weeks before
-- this week.
--
--   Seasonal factor = 1.20
--   Deseasonalized  = 120 / 1.20 = 100
--   Baseline        = 100
-- ============================================================

SELECT
    pg_temp.demo_sale(
        this_week - 7 * weeks_ago, 'Shopify', 'Shopify',
        0, 120, 1080.00,
        21.60, 120.00, 32.40, 90.00,
        'Demo weekly Shopify demand.'
    )

FROM demo_calendar,
     GENERATE_SERIES(5, 2, -1) AS weeks_ago;


-- ============================================================
-- STEP 8: WHOLESALE EXAMPLE
--
-- 24 Original jars x $6 = $144, three weeks ago (Thursday).
-- No sales tax and no scholarship.
-- ============================================================

SELECT
    pg_temp.demo_sale(
        this_week - 21 + 3, 'Wholesale', 'Other',
        24, 0, 144.00,
        0, 0, 0, 0,
        'Demo wholesale sale.'
    )

FROM demo_calendar;


-- ============================================================
-- STEP 9: LAST WEEK
--
-- 9a. Actual Shopify demand for the forecast week:
--     110 Slobberin' jars (Wednesday of last week).
--
-- 9b. Farmers Market summary on Saturday of last week,
--     based directly on Dr. D's answer:
--
--       Cash:  45 DD + 132 SS, $1,610 collected
--       Card:  29 DD +  88 SS, $1,053
--
--     Cash revenue allocation:
--       SS = 1610 x 132 / 177 = $1,200.68 -> scholarship $192.11
--       DD = 1610 - 1200.68   =   $409.32
-- ============================================================

SELECT
    pg_temp.demo_sale(
        last_week + 2, 'Shopify', 'Shopify',
        0, 110, 990.00,
        19.80, 110.00, 29.70, 82.50,
        'Demo actual demand for Forecast vs Actual.'
    ),

    pg_temp.demo_sale(
        last_week + 5, 'Farmers Market', 'Cash',
        45, 132, 1610.00,
        32.20, 0, 0, 0,
        'Demo summarized Farmers Market cash sales.'
    ),

    pg_temp.demo_sale(
        last_week + 5, 'Farmers Market', 'Card',
        29, 88, 1053.00,
        21.06, 0, 31.59, 0,
        'Demo summarized Farmers Market card sales.'
    )

FROM demo_calendar;


-- ============================================================
-- STEP 10: TODAY
--
-- One mixed sale today: DD + SS = $18 -> $9 / $9 -> $1.44.
--
-- It guarantees that the Dashboard always has a sale in the
-- current month, even on the first day of a month.
--
-- Farmers Market is used so it does not change the
-- Shopify-only forecast history.
-- ============================================================

SELECT
    pg_temp.demo_sale(
        today, 'Farmers Market', 'Card',
        1, 1, 18.00,
        0.36, 0, 0.58, 0,
        'Demo mixed sale.'
    )

FROM demo_calendar;


-- ============================================================
-- STEP 11: NON-SALE INVENTORY MOVEMENTS
--
-- Inventory can decrease without creating a fake sale:
--
--   5 Slobberin' jars given as samples
--   3 Original jars donated
--
-- Both on Sunday of last week.
-- ============================================================

INSERT INTO inventory_transactions (
    product_id,
    transaction_date,
    transaction_type,
    quantity_change,
    notes
)
SELECT
    movement.product_id,
    c.last_week + 6,
    movement.transaction_type,
    movement.quantity_change,
    movement.notes

FROM demo_calendar AS c,

     (VALUES
         (2, 'SAMPLE',   -5, 'Demo product samples.'),
         (1, 'DONATION', -3, 'Demo donation.')
     ) AS movement (product_id, transaction_type, quantity_change, notes);


UPDATE inventory
SET current_quantity = current_quantity - 5
WHERE product_id = 2;

UPDATE inventory
SET current_quantity = current_quantity - 3
WHERE product_id = 1;


-- ============================================================
-- STEP 12: COMPLETED FORECAST
--
-- A forecast that was "saved" for last week:
--
--   Product:  Slobberin' Sauce
--   Region:   Wake
--   Channel:  Shopify
--
--   Baseline (four weeks of 100)   = 100
--   Seasonal factor                = 1.20
--   Saved forecast                 = 120
--   Actual sales last week         = 110
--   Difference = 110 - 120         = -10
-- ============================================================

INSERT INTO forecasts (
    product_id,
    sales_region,
    sales_channel,
    forecast_week,
    baseline_forecast_quantity,
    saved_forecast_quantity,
    smoothing_factor,
    demand_tier,
    seasonal_factor,
    actual_quantity,
    forecast_error,
    notes
)
SELECT
    2,
    'Wake',
    'Shopify',
    last_week,
    100.00,
    120.00,
    0.3000,
    'HIGH',
    1.200,
    110.00,
    -10.00,
    'Project 2 completed forecast demonstration.'

FROM demo_calendar;


COMMIT;


-- ============================================================
-- VERIFICATION 1: DEMO CALENDAR
--
-- The dates used by this run of the script.
-- ============================================================

SELECT *
FROM demo_calendar;


-- ============================================================
-- VERIFICATION 2: CURRENT INVENTORY
--
-- Expected:
--
--   Original Sauce   1128 - 1 - 24 - 45 - 29 - 1 - 3   = 1025
--   Slobberin'       1191 - 4 - 480 - 110 - 132 - 88
--                         - 1 - 5                      =  371
--
-- "ledger" is the sum of all inventory movements.
-- It must be equal to current_quantity.
-- ============================================================

SELECT
    p.product_name,
    i.current_quantity,

    (
        SELECT SUM(it.quantity_change)
        FROM inventory_transactions AS it
        WHERE it.product_id = i.product_id
    ) AS ledger

FROM inventory AS i

JOIN products AS p
    ON i.product_id = p.product_id

ORDER BY
    p.product_id;


-- ============================================================
-- VERIFICATION 3: SCHOLARSHIP REPORT MONTH
--
-- Expected:
--   ss_bottles = 4,  ss_revenue = 37.00,  scholarship = 5.92
-- ============================================================

SELECT
    TO_CHAR(c.report_month, 'FMMonth YYYY') AS report_month,
    SUM(si.quantity) AS ss_bottles,
    SUM(si.allocated_revenue) AS ss_revenue,
    SUM(si.scholarship_amount) AS scholarship

FROM demo_calendar AS c

JOIN sales AS s
    ON s.sale_date >= c.report_month
   AND s.sale_date < c.report_month + INTERVAL '1 month'

JOIN sale_items AS si
    ON s.sale_id = si.sale_id

WHERE si.product_id = 2

GROUP BY
    c.report_month;


-- ============================================================
-- VERIFICATION 4: FORECAST TRAINING HISTORY
--
-- Expected: four weeks of 120, then 110 last week.
-- ============================================================

SELECT
    DATE_TRUNC('week', s.sale_date)::date AS week_start,
    SUM(si.quantity) AS quantity_sold

FROM sales AS s

JOIN sale_items AS si
    ON s.sale_id = si.sale_id

WHERE si.product_id = 2
  AND s.sales_channel = 'Shopify'
  AND s.county = 'Wake'

GROUP BY
    DATE_TRUNC('week', s.sale_date)::date

ORDER BY
    week_start;


-- ============================================================
-- VERIFICATION 5: FORECAST VS ACTUAL
--
-- Expected:
--   baseline 100, factor 1.20, forecast 120,
--   actual 110, error -10
-- ============================================================

SELECT
    forecast_week,
    sales_region,
    sales_channel,
    baseline_forecast_quantity,
    seasonal_factor,
    saved_forecast_quantity,
    actual_quantity,
    forecast_error

FROM forecasts

ORDER BY
    forecast_week;


-- ============================================================
-- VERIFICATION 6: SALES BY CHANNEL
--
-- Expected:
--
--   Farmers Market   6 sales   $2,727.00
--   Shopify          5 sales   $5,310.00
--   Wholesale        1 sale      $144.00
-- ============================================================

SELECT
    sales_channel,
    COUNT(*) AS sale_records,
    SUM(total_amount) AS product_revenue

FROM sales

GROUP BY
    sales_channel

ORDER BY
    sales_channel;

