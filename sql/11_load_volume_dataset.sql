-- ============================================================
-- 11_load_volume_dataset.sql
--
-- Purpose:
-- Load a LARGE demonstration dataset (more than 10,000 records)
-- for Dr. D's Business System.
--
-- IMPORTANT:
-- This is SIMULATED DATA. It is not Dr. D's real sales history.
-- The volumes and prices follow what Dr. D described:
--
--   - retail: one jar $10, two jars $18
--   - wholesale: $6 per jar, sold by the case of 12
--   - 2% sales tax on North Carolina retail sales
--   - 16% scholarship on Slobberin' Sauce revenue
--   - a production batch of about 1,100 - 1,200 jars
--   - about 300 online orders on the day Slobberin' Sauce
--     was announced
--
-- THE STORY THE DATA TELLS (all dates are relative to today):
--
--   24 months ago   The business starts with Original Sauce:
--                   Shopify orders, Saturday farmers markets,
--                   wholesale deliveries, direct sales.
--
--    3 months ago   Three test sales of Slobberin' Sauce.
--                   They are the ONLY Slobberin' sales in that
--                   month: 4 jars, $37.00, $5.92 scholarship.
--
--    2 months ago   Slobberin' Sauce is launched. About 300
--                   online orders arrive on the first day.
--
--   Last week       Wake County Shopify demand for Slobberin'
--                   Sauce: forecast 120 jars, actual 110.
--
-- TWO DATASETS, ONE DATABASE:
--
--   06_load_compact_demo_dataset.sql   12 sales. Small enough
--                                      to check every number
--                                      by hand.
--
--   11_load_volume_dataset.sql         This script. Thousands
--                                      of sales for realistic
--                                      reports and performance.
--
-- Each script first removes all sales, inventory movements,
-- batches and forecasts. The one that is run LAST decides what
-- is in the database.
--
-- The Phase 1 demonstration numbers are the same in both:
--
--   Mixed sale $18            -> $9 / $9 -> $1.44 scholarship
--   Scholarship report month  -> 4 jars, $5.92
--   Forecast last week        -> 100 x 1.20 = 120, actual 110
--   Forecast next week        -> 97.5 x 1.20 = 117
--
-- HOW THE DATA IS LOADED (a small data pipeline):
--
--   1. GENERATE   Orders are generated into a temporary
--                 staging table (demo_orders).
--   2. TRANSFORM  Revenue is allocated between the two sauces
--                 and the scholarship is calculated, using the
--                 same rules as the application.
--   3. LOAD       sales, sale_items and inventory_transactions
--                 are filled with set-based INSERT ... SELECT.
--   4. RESTOCK    Production batches are received whenever the
--                 stock would run low, so the balance never
--                 becomes negative.
--
-- Run this script again shortly before a presentation.
-- Safe to run more than once. Requires scripts 01 - 05.
-- ============================================================


BEGIN;


-- ============================================================
-- STEP 1: REMOVE CURRENT TRANSACTIONS
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
-- STEP 2: FIXED RANDOM SEED
--
-- random() normally returns different numbers every time.
-- setseed() makes the sequence repeatable: running the script
-- twice on the same day produces exactly the same data.
-- ============================================================

SELECT setseed(0.519);


-- ============================================================
-- STEP 3: DEMO CALENDAR
--
-- One row with every date the script needs.
-- ============================================================

DROP TABLE IF EXISTS demo_calendar;

CREATE TEMPORARY TABLE demo_calendar AS

SELECT
    CURRENT_DATE AS today,

    -- Monday of the current week.
    DATE_TRUNC('week', CURRENT_DATE)::date AS this_week,

    -- Monday of the last COMPLETE week.
    (DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '7 days')::date
        AS last_week,

    -- First day of the business history.
    (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '24 months')::date
        AS history_start,

    -- Month that contains only the three Slobberin' test sales.
    (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months')::date
        AS report_month,

    -- Slobberin' Sauce launch day.
    (DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '2 months')::date
        AS launch_date;


-- ============================================================
-- STEP 4: SEASONAL SETTINGS
--
-- 4a. Reset all months to the prototype defaults.
--
-- 4b. The months since the Slobberin' launch are set to
--     HIGH / 1.20. This guarantees the Phase 1 forecast
--     numbers on any day of the year:
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

    SELECT DISTINCT EXTRACT(MONTH FROM demo_day)::int

    FROM demo_calendar,

         GENERATE_SERIES(
             launch_date,
             this_week + 20,
             INTERVAL '1 day'
         ) AS demo_day
);


-- ============================================================
-- STEP 5: STAGING TABLE
--
-- Every generator below writes its orders here first.
-- Nothing is written to the real tables until STEP 13.
--
-- load_order keeps the rows in the order they were generated.
-- ============================================================

DROP TABLE IF EXISTS demo_orders;

CREATE TEMPORARY TABLE demo_orders (
    load_order        BIGSERIAL PRIMARY KEY,
    sale_date         DATE          NOT NULL,
    sales_channel     VARCHAR(50)   NOT NULL,
    payment_method    VARCHAR(50)   NOT NULL,
    state             VARCHAR(50),
    county            VARCHAR(100),
    original_qty      INTEGER       NOT NULL,
    slobberin_qty     INTEGER       NOT NULL,
    revenue           NUMERIC(10,2) NOT NULL,
    tax               NUMERIC(10,2) NOT NULL DEFAULT 0,
    shipping_revenue  NUMERIC(10,2) NOT NULL DEFAULT 0,
    fee               NUMERIC(10,2) NOT NULL DEFAULT 0,
    shipping_expense  NUMERIC(10,2) NOT NULL DEFAULT 0
);


-- ============================================================
-- STEP 6: SHOPIFY ORDERS (WHOLE HISTORY)
--
-- Orders per day grow from about 4 to about 8 during the
-- 24 months, with random variation from day to day.
--
-- Each order gets four random numbers:
--   r_qty    how many jars (1 - 4)
--   r_place  Wake County / other NC county / other state
--   r_pick   which county or state
--   r_mix    Original only / Slobberin' only / both
--   r_ship   difference between shipping charged and paid
--
-- MATERIALIZED makes PostgreSQL calculate the random numbers
-- once per row and keep them, instead of recalculating them
-- every time the row is used.
--
-- Slobberin' Sauce is sold only after the launch date.
--
-- Wake County orders here contain Original Sauce only.
-- Wake County Slobberin' orders are generated separately in
-- STEP 7 so that their weekly totals are known exactly.
--
-- Assumptions:
--   shipping charged   $8 (1-2 jars), $10 (3-4 jars)
--   online payment fee 2.9% of the order total + $0.30
--   sales tax          2% for North Carolina, none elsewhere
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax,
    shipping_revenue,
    fee,
    shipping_expense
)

WITH days AS MATERIALIZED (

    SELECT
        d::date AS sale_date,

        FLOOR(
            (
                4
                + 4.0 * (d::date - c.history_start)
                      / (c.today - c.history_start)
            )
            * (0.5 + RANDOM())
        )::int AS orders_that_day

    FROM demo_calendar AS c,

         GENERATE_SERIES(
             c.history_start,
             c.today,
             INTERVAL '1 day'
         ) AS d
),

raw_orders AS MATERIALIZED (

    SELECT
        days.sale_date,
        RANDOM() AS r_qty,
        RANDOM() AS r_place,
        RANDOM() AS r_pick,
        RANDOM() AS r_mix,
        RANDOM() AS r_ship

    FROM days

    CROSS JOIN LATERAL
        GENERATE_SERIES(1, days.orders_that_day) AS order_number
),

placed AS (

    SELECT
        r.*,

        -- 30% Wake County, 48% other NC counties, 22% other states.
        CASE
            WHEN r_place < 0.78 THEN 'NC'
            ELSE (ARRAY['VA', 'SC', 'GA', 'TN', 'FL', 'NY', 'MI'])
                 [1 + FLOOR(r_pick * 7)::int]
        END AS state,

        CASE
            WHEN r_place < 0.30 THEN 'Wake'

            WHEN r_place < 0.78 THEN
                (ARRAY[
                    'Durham', 'Orange', 'Johnston', 'Chatham',
                    'Mecklenburg', 'Guilford', 'Forsyth',
                    'New Hanover', 'Brunswick', 'Moore', 'Harnett'
                ])[1 + FLOOR(r_pick * 11)::int]

            -- County is not recorded for other states.
            ELSE NULL
        END AS county,

        -- 35% one jar, 50% two jars, 10% three, 5% four.
        CASE
            WHEN r_qty < 0.35 THEN 1
            WHEN r_qty < 0.85 THEN 2
            WHEN r_qty < 0.95 THEN 3
            ELSE 4
        END AS total_qty

    FROM raw_orders AS r
),

mixed AS (

    SELECT
        p.*,

        CASE
            -- Before the launch: Original Sauce only.
            WHEN p.sale_date < c.launch_date THEN 0

            -- Wake County Slobberin' orders come from STEP 7.
            WHEN p.county = 'Wake' THEN 0

            -- 45% Original only.
            WHEN p.r_mix < 0.45 THEN 0

            -- 35% Slobberin' only.
            WHEN p.r_mix < 0.80 THEN p.total_qty

            -- 20% both sauces (a single jar cannot be mixed).
            WHEN p.total_qty = 1 THEN 1
            ELSE p.total_qty / 2
        END AS slobberin_qty

    FROM placed AS p,
         demo_calendar AS c
),

priced AS (

    SELECT
        m.*,

        -- Every two jars $18, a remaining single jar $10.
        (18 * (m.total_qty / 2) + 10 * (m.total_qty % 2))::numeric
            AS revenue,

        CASE
            WHEN m.total_qty <= 2 THEN 8.00
            ELSE 10.00
        END AS shipping_revenue

    FROM mixed AS m
)

SELECT
    sale_date,
    'Shopify',
    'Shopify',
    state,
    county,
    total_qty - slobberin_qty,
    slobberin_qty,
    revenue,

    CASE
        WHEN state = 'NC' THEN ROUND(revenue * 0.02, 2)
        ELSE 0
    END,

    shipping_revenue,

    ROUND(
        (
            revenue
            + CASE WHEN state = 'NC' THEN revenue * 0.02 ELSE 0 END
            + shipping_revenue
        ) * 0.029 + 0.30,
        2
    ),

    -- The label usually costs a little less than what the
    -- customer paid, and sometimes more.
    ROUND(
        (shipping_revenue + (r_ship - 0.6) * 3)::numeric,
        2
    )

FROM priced

ORDER BY
    sale_date;


-- ============================================================
-- STEP 7: CONTROL SEGMENT FOR THE FORECAST
--
-- Slobberin' Sauce · Wake County · Shopify.
--
-- The weekly total of this segment is fixed on purpose, so the
-- forecast calculation can be checked by hand:
--
--   every complete week since the launch   120 jars
--   last week                              110 jars
--
-- Each week is made of individual orders:
--
--   120 jars = 30 orders of two Slobberin'      (60 jars)
--            + 24 mixed orders, 1 Original + 1 Slobberin'
--            + 36 orders of one Slobberin'
--
--   110 jars = 27 orders of two + 22 mixed + 34 single
--
-- The orders are spread over the seven days of the week.
-- For the current, unfinished week only the days up to today
-- are loaded.
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax,
    shipping_revenue,
    fee,
    shipping_expense
)

WITH weeks AS (

    SELECT
        w::date AS week_start,

        CASE
            WHEN w::date = c.last_week THEN 110
            ELSE 120
        END AS target_jars

    FROM demo_calendar AS c,

         GENERATE_SERIES(
             -- First Monday on or after the launch date.
             DATE_TRUNC('week', c.launch_date + 6)::date,
             c.this_week,
             INTERVAL '7 days'
         ) AS w
),

plan AS (

    SELECT
        week_start,
        target_jars / 4 AS pair_orders,
        target_jars / 5 AS mixed_orders,

        target_jars
            - 2 * (target_jars / 4)
            - target_jars / 5 AS single_orders

    FROM weeks
),

orders AS (

    -- Two Slobberin' for $18.
    SELECT
        week_start + (n % 7) AS sale_date,
        0 AS original_qty,
        2 AS slobberin_qty,
        18.00 AS revenue

    FROM plan
    CROSS JOIN LATERAL GENERATE_SERIES(1, pair_orders) AS n

    UNION ALL

    -- One Original + one Slobberin' for $18.
    SELECT
        week_start + (n % 7),
        1,
        1,
        18.00

    FROM plan
    CROSS JOIN LATERAL GENERATE_SERIES(1, mixed_orders) AS n

    UNION ALL

    -- One Slobberin' for $10.
    SELECT
        week_start + (n % 7),
        0,
        1,
        10.00

    FROM plan
    CROSS JOIN LATERAL GENERATE_SERIES(1, single_orders) AS n
)

SELECT
    o.sale_date,
    'Shopify',
    'Shopify',
    'NC',
    'Wake',
    o.original_qty,
    o.slobberin_qty,
    o.revenue,
    ROUND(o.revenue * 0.02, 2),
    8.00,
    ROUND((o.revenue * 1.02 + 8.00) * 0.029 + 0.30, 2),
    ROUND((8.00 + (RANDOM() - 0.6) * 3)::numeric, 2)

FROM orders AS o,
     demo_calendar AS c

WHERE o.sale_date <= c.today

ORDER BY
    o.sale_date;


-- ============================================================
-- STEP 8: LAUNCH DAY
--
-- About 300 additional online orders of Slobberin' Sauce on
-- the day it was announced, from North Carolina counties
-- outside Wake and from other states.
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax,
    shipping_revenue,
    fee,
    shipping_expense
)

WITH raw_orders AS MATERIALIZED (

    SELECT
        RANDOM() AS r_qty,
        RANDOM() AS r_place,
        RANDOM() AS r_pick,
        RANDOM() AS r_ship

    FROM GENERATE_SERIES(1, 300)
),

shaped AS (

    SELECT
        r.*,

        CASE
            WHEN r_place < 0.70 THEN 'NC'
            ELSE (ARRAY['VA', 'SC', 'GA', 'TN', 'FL', 'NY', 'MI'])
                 [1 + FLOOR(r_pick * 7)::int]
        END AS state,

        CASE
            WHEN r_place < 0.70 THEN
                (ARRAY[
                    'Durham', 'Orange', 'Johnston', 'Chatham',
                    'Mecklenburg', 'Guilford', 'Forsyth',
                    'New Hanover', 'Brunswick', 'Moore', 'Harnett'
                ])[1 + FLOOR(r_pick * 11)::int]
            ELSE NULL
        END AS county,

        CASE
            WHEN r_qty < 0.30 THEN 1
            WHEN r_qty < 0.85 THEN 2
            ELSE 4
        END AS total_qty

    FROM raw_orders AS r
)

SELECT
    c.launch_date,
    'Shopify',
    'Shopify',
    s.state,
    s.county,
    0,
    s.total_qty,
    (18 * (s.total_qty / 2) + 10 * (s.total_qty % 2))::numeric,

    CASE
        WHEN s.state = 'NC'
        THEN ROUND((18 * (s.total_qty / 2) + 10 * (s.total_qty % 2)) * 0.02, 2)
        ELSE 0
    END,

    CASE WHEN s.total_qty <= 2 THEN 8.00 ELSE 10.00 END,

    ROUND(
        (
            (18 * (s.total_qty / 2) + 10 * (s.total_qty % 2))
            * CASE WHEN s.state = 'NC' THEN 1.02 ELSE 1.00 END
            + CASE WHEN s.total_qty <= 2 THEN 8.00 ELSE 10.00 END
        ) * 0.029 + 0.30,
        2
    ),

    ROUND(
        (
            CASE WHEN s.total_qty <= 2 THEN 8.00 ELSE 10.00 END
            + (s.r_ship - 0.6) * 3
        )::numeric,
        2
    )

FROM shaped AS s,
     demo_calendar AS c;


-- ============================================================
-- STEP 9: FARMERS MARKETS
--
-- One market every Saturday, entered the way Dr. D enters it:
-- one summary for cash and one summary for card.
--
-- Jars sold at a market:
--   before the launch   Original only
--   after the launch    mostly Slobberin'
--
-- Revenue:
--   $9 per jar (two for $18) plus $1 for every jar that was
--   sold alone for $10. Between 5% and 25% of the jars are
--   sold alone.
--
-- Card fee: about 3% of the card revenue.
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax,
    fee
)

WITH markets AS MATERIALIZED (

    SELECT
        d::date AS sale_date,
        d::date >= c.launch_date AS after_launch,

        -- 60% of the markets are in Wake County.
        CASE
            WHEN RANDOM() < 0.60 THEN 'Wake'
            ELSE (ARRAY[
                'Durham', 'Orange', 'Johnston', 'Moore', 'New Hanover'
            ])[1 + FLOOR(RANDOM() * 5)::int]
        END AS county,

        RANDOM() AS r_cash_original,
        RANDOM() AS r_cash_slobberin,
        RANDOM() AS r_card_original,
        RANDOM() AS r_card_slobberin,
        RANDOM() AS r_cash_singles,
        RANDOM() AS r_card_singles

    FROM demo_calendar AS c,

         GENERATE_SERIES(
             c.history_start,
             c.today,
             INTERVAL '1 day'
         ) AS d

    -- 6 = Saturday.
    WHERE EXTRACT(DOW FROM d) = 6
),

parts AS (

    -- Cash summary.
    SELECT
        sale_date,
        county,
        'Cash' AS payment_method,

        CASE
            WHEN after_launch THEN 20 + FLOOR(r_cash_original * 40)::int
            ELSE 40 + FLOOR(r_cash_original * 60)::int
        END AS original_qty,

        CASE
            WHEN after_launch THEN 70 + FLOOR(r_cash_slobberin * 80)::int
            ELSE 0
        END AS slobberin_qty,

        r_cash_singles AS r_singles

    FROM markets

    UNION ALL

    -- Card summary.
    SELECT
        sale_date,
        county,
        'Card',

        CASE
            WHEN after_launch THEN 12 + FLOOR(r_card_original * 30)::int
            ELSE 25 + FLOOR(r_card_original * 45)::int
        END,

        CASE
            WHEN after_launch THEN 45 + FLOOR(r_card_slobberin * 60)::int
            ELSE 0
        END,

        r_card_singles

    FROM markets
),

priced AS (

    SELECT
        p.*,

        (
            9 * (original_qty + slobberin_qty)
            + FLOOR(
                (original_qty + slobberin_qty)
                * (0.05 + 0.20 * r_singles)
              )
        )::numeric AS revenue

    FROM parts AS p
)

SELECT
    sale_date,
    'Farmers Market',
    payment_method,
    'NC',
    county,
    original_qty,
    slobberin_qty,
    revenue,
    ROUND(revenue * 0.02, 2),

    CASE
        WHEN payment_method = 'Card' THEN ROUND(revenue * 0.03, 2)
        ELSE 0
    END

FROM priced

ORDER BY
    sale_date,
    payment_method;


-- ============================================================
-- STEP 10: WHOLESALE DELIVERIES
--
-- About three deliveries a week to stores across the state.
-- Each delivery is 1 - 3 cases of 12 jars at $6 per jar.
-- No sales tax (the store collects it from its customers).
--
-- After the launch, 40% of the deliveries are Slobberin' Sauce.
-- The scholarship on a wholesale jar is 16% of $6 = $0.96.
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue
)

WITH deliveries AS MATERIALIZED (

    SELECT
        d::date AS sale_date,
        d::date >= c.launch_date AS after_launch,
        RANDOM() AS r_happens,
        RANDOM() AS r_cases,
        RANDOM() AS r_product,

        (ARRAY[
            'Wake', 'Wake', 'Durham', 'Johnston', 'Harnett',
            'Forsyth', 'Guilford', 'New Hanover', 'Brunswick',
            'Moore', 'Chatham', 'Orange'
        ])[1 + FLOOR(RANDOM() * 12)::int] AS county

    FROM demo_calendar AS c,

         GENERATE_SERIES(
             c.history_start,
             c.today,
             INTERVAL '1 day'
         ) AS d

    -- Deliveries are made Monday through Friday.
    WHERE EXTRACT(DOW FROM d) BETWEEN 1 AND 5
),

chosen AS (

    SELECT
        d.*,
        12 * (1 + FLOOR(r_cases * 3)::int) AS jars

    FROM deliveries AS d

    -- About 60% of the weekdays have a delivery.
    WHERE r_happens < 0.60
)

SELECT
    sale_date,
    'Wholesale',
    'Other',
    'NC',
    county,

    CASE
        WHEN after_launch AND r_product < 0.40 THEN 0
        ELSE jars
    END,

    CASE
        WHEN after_launch AND r_product < 0.40 THEN jars
        ELSE 0
    END,

    (6 * jars)::numeric

FROM chosen

ORDER BY
    sale_date;


-- ============================================================
-- STEP 11: DIRECT SALES
--
-- A few jars sold directly to friends and colleagues,
-- paid in cash or by Venmo. Wake County, retail prices.
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax
)

WITH direct AS MATERIALIZED (

    SELECT
        d::date AS sale_date,
        d::date >= c.launch_date AS after_launch,
        RANDOM() AS r_happens,
        RANDOM() AS r_product,
        RANDOM() AS r_payment,
        1 + FLOOR(RANDOM() * 6)::int AS jars

    FROM demo_calendar AS c,

         GENERATE_SERIES(
             c.history_start,
             c.today,
             INTERVAL '1 day'
         ) AS d
)

SELECT
    sale_date,
    'Direct',
    CASE WHEN r_payment < 0.5 THEN 'Cash' ELSE 'Venmo' END,
    'NC',
    'Wake',
    CASE WHEN after_launch AND r_product < 0.5 THEN 0 ELSE jars END,
    CASE WHEN after_launch AND r_product < 0.5 THEN jars ELSE 0 END,
    (18 * (jars / 2) + 10 * (jars % 2))::numeric,
    ROUND((18 * (jars / 2) + 10 * (jars % 2)) * 0.02, 2)

FROM direct

-- About one direct sale every five days.
WHERE r_happens < 0.20

ORDER BY
    sale_date;


-- ============================================================
-- STEP 12: THREE SLOBBERIN' TEST SALES (REPORT MONTH)
--
-- The only Slobberin' Sauce sales in the month three months
-- ago. They give the monthly scholarship report promised in
-- Phase 1:
--
--   1 SS for $10          -> $1.60
--   2 SS for $18          -> $2.88
--   Mixed DD + SS for $18 -> $1.44
--
--   Total: 4 jars, $37.00 eligible revenue, $5.92
-- ============================================================

INSERT INTO demo_orders (
    sale_date,
    sales_channel,
    payment_method,
    state,
    county,
    original_qty,
    slobberin_qty,
    revenue,
    tax,
    fee
)
SELECT
    c.report_month + test_sale.day_offset,
    'Farmers Market',
    test_sale.payment_method,
    'NC',
    'Wake',
    test_sale.original_qty,
    test_sale.slobberin_qty,
    test_sale.revenue,
    test_sale.tax,
    test_sale.fee

FROM demo_calendar AS c,

     (VALUES
         (19, 'Cash', 0, 1, 10.00, 0.20, 0.00),
         (20, 'Cash', 0, 2, 18.00, 0.36, 0.00),
         (21, 'Card', 1, 1, 18.00, 0.36, 0.58)
     ) AS test_sale (
         day_offset,
         payment_method,
         original_qty,
         slobberin_qty,
         revenue,
         tax,
         fee
     );


-- ============================================================
-- STEP 13: TRANSFORM AND LOAD
--
-- 13a. Number the orders by date. That number becomes sale_id.
--
-- 13b. Allocate revenue and calculate scholarship, with the
--      same rules as sale_service.py:
--
--        Slobberin' revenue = ROUND(revenue x SS jars / all jars, 2)
--        Original revenue   = revenue - Slobberin' revenue
--        Scholarship        = ROUND(Slobberin' revenue x rate, 2)
--        sale_price         = revenue of the line / jars
-- ============================================================

DROP TABLE IF EXISTS demo_sales;

CREATE TEMPORARY TABLE demo_sales AS

SELECT
    ROW_NUMBER() OVER (
        ORDER BY o.sale_date, o.load_order
    )::int AS sale_id,

    o.*,

    ROUND(
        o.revenue * o.slobberin_qty
        / (o.original_qty + o.slobberin_qty),
        2
    ) AS slobberin_revenue

FROM demo_orders AS o

WHERE o.original_qty + o.slobberin_qty > 0;


-- ------------------------------------------------------------
-- LOAD: sales
-- ------------------------------------------------------------

INSERT INTO sales (
    sale_id,
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
SELECT
    sale_id,
    sale_date,
    sales_channel,
    payment_method,
    revenue,
    tax,
    shipping_revenue,
    fee,
    shipping_expense,
    state,
    county

FROM demo_sales

ORDER BY
    sale_id;


-- sale_id was inserted explicitly, so the SERIAL counter must
-- be moved forward. The next sale recorded in the application
-- then gets the next free number.

SELECT SETVAL(
    PG_GET_SERIAL_SEQUENCE('sales', 'sale_id'),
    (SELECT MAX(sale_id) FROM sales)
);


-- ------------------------------------------------------------
-- LOAD: sale_items
--
-- One line per product in the sale.
-- product_id 1 = Original, product_id 2 = Slobberin'.
-- ------------------------------------------------------------

INSERT INTO sale_items (
    sale_id,
    product_id,
    quantity,
    sale_price,
    allocated_revenue,
    scholarship_amount
)
SELECT
    line.sale_id,
    line.product_id,
    line.quantity,
    ROUND(line.allocated_revenue / line.quantity, 2),
    line.allocated_revenue,
    ROUND(line.allocated_revenue * p.scholarship_rate, 2)

FROM (

    SELECT
        sale_id,
        1 AS product_id,
        original_qty AS quantity,
        revenue - slobberin_revenue AS allocated_revenue
    FROM demo_sales
    WHERE original_qty > 0

    UNION ALL

    SELECT
        sale_id,
        2,
        slobberin_qty,
        slobberin_revenue
    FROM demo_sales
    WHERE slobberin_qty > 0

) AS line

JOIN products AS p
    ON line.product_id = p.product_id

ORDER BY
    line.sale_id,
    line.product_id;


-- ------------------------------------------------------------
-- LOAD: inventory audit trail for the sales
-- ------------------------------------------------------------

INSERT INTO inventory_transactions (
    product_id,
    transaction_date,
    transaction_type,
    quantity_change,
    sale_id,
    notes
)
SELECT
    si.product_id,
    s.sale_date,
    'SALE',
    -si.quantity,
    s.sale_id,
    'Inventory reduction from sale #' || s.sale_id || '.'

FROM sale_items AS si

JOIN sales AS s
    ON si.sale_id = s.sale_id

ORDER BY
    s.sale_id,
    si.product_id;


-- ============================================================
-- STEP 14: JARS THAT LEFT WITHOUT A SALE
--
-- Every Saturday market gives away tasting samples.
-- Now and then jars are donated, broken in shipping (and
-- replaced), or given as gifts.
--
-- Slobberin' Sauce movements start with the launch.
-- ============================================================

INSERT INTO inventory_transactions (
    product_id,
    transaction_date,
    transaction_type,
    quantity_change,
    notes
)

WITH candidates AS MATERIALIZED (

    SELECT
        p.product_id,
        d::date AS movement_date,
        EXTRACT(DOW FROM d)::int AS day_of_week,
        RANDOM() AS r_type,
        RANDOM() AS r_quantity

    FROM demo_calendar AS c

    CROSS JOIN products AS p

    CROSS JOIN LATERAL GENERATE_SERIES(
        CASE
            WHEN p.product_id = 2 THEN c.launch_date
            ELSE c.history_start
        END,
        c.today,
        INTERVAL '1 day'
    ) AS d
)

-- Tasting samples at every Saturday market.
SELECT
    product_id,
    movement_date,
    'SAMPLE',
    -(2 + FLOOR(r_quantity * 5)::int),
    'Tasting samples at the farmers market.'

FROM candidates
WHERE day_of_week = 6

UNION ALL

-- A donation about once a month.
SELECT
    product_id,
    movement_date,
    'DONATION',
    -(6 + FLOOR(r_quantity * 7)::int),
    'Donated to a community or NC State event.'

FROM candidates
WHERE day_of_week = 3
  AND r_type < 0.22

UNION ALL

-- A jar broken in shipping about every second week.
SELECT
    product_id,
    movement_date,
    'BROKEN',
    -1,
    'Jar broken in shipping.'

FROM candidates
WHERE day_of_week = 2
  AND r_type < 0.50

UNION ALL

-- The replacement jar sent to that customer two days later.
SELECT
    product_id,
    movement_date + 2,
    'REPLACEMENT',
    -1,
    'Replacement for a jar broken in shipping.'

FROM candidates
WHERE day_of_week = 2
  AND r_type < 0.50
  AND movement_date + 2 <= (SELECT today FROM demo_calendar)

UNION ALL

-- An occasional gift.
SELECT
    product_id,
    movement_date,
    'GIFT',
    -(1 + FLOOR(r_quantity * 3)::int),
    'Gift.'

FROM candidates
WHERE day_of_week = 5
  AND r_type < 0.12

ORDER BY
    2,
    1;


-- ============================================================
-- STEP 15: RESTOCK - RECEIVE PRODUCTION BATCHES
--
-- For each product the weeks are walked in order.
--
-- At the start of a week:
--   if the stock is not enough for that week's outflow plus a
--   reserve of 300 jars, a new batch of about 1,100 - 1,200
--   jars is received (two days before the week starts).
--
-- Result:
--   - the running balance never becomes negative;
--   - the number of batches follows the demand, exactly like a
--     simple reorder rule.
--
-- DO $$ ... $$ runs a block of PL/pgSQL code once.
-- ============================================================

DO $$
DECLARE

    v_product     RECORD;
    v_week        RECORD;
    v_stock       INTEGER;
    v_batch_no    INTEGER;
    v_batch_size  INTEGER;
    v_batch_id    INTEGER;
    v_received    DATE;

BEGIN

    FOR v_product IN

        SELECT
            product_id,
            CASE
                WHEN product_id = 1 THEN 'DD'
                ELSE 'SS'
            END AS code

        FROM products
        ORDER BY product_id

    LOOP

        v_stock := 0;

        v_batch_no := 0;

        -- ----------------------------------------------------
        -- Weekly outflow of this product, oldest week first.
        -- ----------------------------------------------------

        FOR v_week IN

            SELECT
                DATE_TRUNC('week', transaction_date)::date AS week_start,
                -SUM(quantity_change) AS jars_out

            FROM inventory_transactions

            WHERE product_id = v_product.product_id

            GROUP BY
                DATE_TRUNC('week', transaction_date)::date

            ORDER BY
                week_start

        LOOP

            -- ------------------------------------------------
            -- Receive batches until the week is covered.
            -- ------------------------------------------------

            WHILE v_stock < v_week.jars_out + 300 LOOP

                v_batch_no := v_batch_no + 1;

                v_batch_size := 1100 + FLOOR(RANDOM() * 100)::int;

                v_received := v_week.week_start - 2;

                INSERT INTO inventory_batches (
                    product_id,
                    batch_code,
                    received_date,
                    quantity_received,
                    manufacturer,
                    notes
                )
                VALUES (
                    v_product.product_id,
                    v_product.code || '-BATCH-'
                        || LPAD(v_batch_no::text, 2, '0'),
                    v_received,
                    v_batch_size,
                    'Demo Co-Packer',
                    'Simulated production batch.'
                )
                RETURNING batch_id
                INTO v_batch_id;

                INSERT INTO inventory_transactions (
                    product_id,
                    batch_id,
                    transaction_date,
                    transaction_type,
                    quantity_change,
                    notes
                )
                VALUES (
                    v_product.product_id,
                    v_batch_id,
                    v_received,
                    'RECEIPT',
                    v_batch_size,
                    'Manufacturer batch received.'
                );

                v_stock := v_stock + v_batch_size;

            END LOOP;

            v_stock := v_stock - v_week.jars_out;

        END LOOP;

    END LOOP;

END;
$$;


-- ============================================================
-- STEP 16: CURRENT BALANCE
--
-- The balance of each product is the sum of all its movements.
-- ============================================================

UPDATE inventory AS i
SET current_quantity = movement.total

FROM (
    SELECT
        product_id,
        SUM(quantity_change) AS total
    FROM inventory_transactions
    GROUP BY product_id
) AS movement

WHERE i.product_id = movement.product_id;


-- ============================================================
-- STEP 17: COMPLETED FORECAST
--
-- Slobberin' Sauce · Wake · Shopify · last week.
--
--   Every earlier week: 120 jars / 1.20 = 100  -> baseline 100
--   Saved forecast  = 100 x 1.20 = 120
--   Actual          = 110
--   Difference      = -10
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


-- Refresh the statistics PostgreSQL uses to plan queries
-- after a large load.

ANALYZE;


-- ============================================================
-- VERIFICATION 1: RECORD COUNTS
--
-- The project requires more than 10,000 records.
-- ============================================================

SELECT 'products' AS table_name, COUNT(*) AS records FROM products
UNION ALL
SELECT 'sales', COUNT(*) FROM sales
UNION ALL
SELECT 'sale_items', COUNT(*) FROM sale_items
UNION ALL
SELECT 'inventory', COUNT(*) FROM inventory
UNION ALL
SELECT 'inventory_batches', COUNT(*) FROM inventory_batches
UNION ALL
SELECT 'inventory_transactions', COUNT(*) FROM inventory_transactions
UNION ALL
SELECT 'forecast_seasonality', COUNT(*) FROM forecast_seasonality
UNION ALL
SELECT 'forecasts', COUNT(*) FROM forecasts
UNION ALL
SELECT
    'TOTAL',
    (SELECT COUNT(*) FROM products)
    + (SELECT COUNT(*) FROM sales)
    + (SELECT COUNT(*) FROM sale_items)
    + (SELECT COUNT(*) FROM inventory)
    + (SELECT COUNT(*) FROM inventory_batches)
    + (SELECT COUNT(*) FROM inventory_transactions)
    + (SELECT COUNT(*) FROM forecast_seasonality)
    + (SELECT COUNT(*) FROM forecasts);


-- ============================================================
-- VERIFICATION 2: SALES BY CHANNEL
-- ============================================================

SELECT
    sales_channel,
    COUNT(*) AS sale_records,
    SUM(jars_sold) AS jars_sold,
    SUM(product_revenue) AS product_revenue,
    SUM(scholarship) AS scholarship,
    SUM(estimated_profit) AS estimated_profit

FROM (
    SELECT
        s.sale_id,
        s.sales_channel,
        s.total_amount AS product_revenue,
        SUM(si.quantity) AS jars_sold,
        SUM(si.scholarship_amount) AS scholarship,

        s.total_amount
            + s.shipping_revenue
            - s.shopify_fee
            - s.shipping_expense
            - SUM(si.quantity * p.unit_cost)
            - SUM(si.scholarship_amount) AS estimated_profit

    FROM sales AS s
    JOIN sale_items AS si ON s.sale_id = si.sale_id
    JOIN products AS p ON si.product_id = p.product_id

    GROUP BY
        s.sale_id
) AS per_sale

GROUP BY
    sales_channel

ORDER BY
    sales_channel;


-- ============================================================
-- VERIFICATION 3: INVENTORY
--
-- "ledger" (the sum of all movements) must be equal to
-- current_quantity, and "lowest_balance" must not be negative.
-- ============================================================

SELECT
    p.product_name,
    i.current_quantity,
    ledger.total AS ledger,
    ledger.batches,
    ledger.lowest_balance

FROM inventory AS i

JOIN products AS p
    ON i.product_id = p.product_id

JOIN (
    SELECT
        product_id,
        SUM(quantity_change) AS total,
        COUNT(*) FILTER (WHERE transaction_type = 'RECEIPT') AS batches,
        MIN(running_balance) AS lowest_balance

    FROM (
        SELECT
            product_id,
            transaction_type,
            quantity_change,

            SUM(quantity_change) OVER (
                PARTITION BY product_id
                ORDER BY transaction_date, quantity_change DESC, transaction_id
            ) AS running_balance

        FROM inventory_transactions
    ) AS running

    GROUP BY
        product_id
) AS ledger
    ON i.product_id = ledger.product_id

ORDER BY
    p.product_id;


-- ============================================================
-- VERIFICATION 4: SCHOLARSHIP REPORT MONTH
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
-- VERIFICATION 5: FORECAST CONTROL SEGMENT
--
-- Slobberin' Sauce · Wake · Shopify, complete weeks only.
--
-- Expected: 120 jars in every week, 110 in the last week.
-- ============================================================

SELECT
    DATE_TRUNC('week', s.sale_date)::date AS week_start,
    COUNT(*) AS orders,
    SUM(si.quantity) AS slobberin_jars

FROM sales AS s

JOIN sale_items AS si
    ON s.sale_id = si.sale_id

WHERE si.product_id = 2
  AND s.sales_channel = 'Shopify'
  AND s.county = 'Wake'
  AND s.sale_date < (SELECT this_week FROM demo_calendar)

GROUP BY
    DATE_TRUNC('week', s.sale_date)::date

ORDER BY
    week_start;


-- ============================================================
-- VERIFICATION 6: FORECAST VS ACTUAL
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


