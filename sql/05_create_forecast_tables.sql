-- ============================================================
-- 05_create_forecast_tables.sql
--
-- Purpose:
-- Create the database structure needed for:
--
-- 1. Seasonal demand settings by month
-- 2. Weekly saved forecasts
-- 3. Forecast vs. Actual analysis
--
-- This supports Project Function 3:
-- Seasonal Demand Forecasting & Accuracy Tracking.
--
-- Safe to run more than once:
--   - tables and indexes are created only when they are missing;
--   - a month that already has a seasonal setting keeps it.
-- ============================================================

-- ============================================================
-- TABLE 1: FORECAST_SEASONALITY
--
-- Purpose:
-- Store the editable seasonal assumption for each month.
--
-- The project requirement uses:
--
-- LOW demand
-- MEDIUM demand
-- HIGH demand
--
-- with a corresponding seasonal factor.
--
-- Example:
--
-- January
-- demand tier = LOW
-- seasonal factor = 0.80
--
-- October
-- demand tier = HIGH
-- seasonal factor = 1.20
--
-- The user will later be able to edit these values
-- through the Forecast page in Streamlit.
-- ============================================================

CREATE TABLE IF NOT EXISTS forecast_seasonality (

    -- Unique database ID.
    seasonality_id SERIAL PRIMARY KEY,

    -- Month number:
    --
    -- 1 = January
    -- 2 = February
    -- ...
    -- 12 = December
    month_number INTEGER NOT NULL
        CHECK (
            month_number BETWEEN 1 AND 12
        ),

    -- Human-readable month name.
    --
    -- We store this for easier reporting.
    month_name VARCHAR(20) NOT NULL,

    -- Demand classification required by the prototype.
    --
    -- Allowed values:
    -- LOW
    -- MEDIUM
    -- HIGH
    demand_tier VARCHAR(20) NOT NULL
        CHECK (
            demand_tier IN (
                'LOW',
                'MEDIUM',
                'HIGH'
            )
        ),

    -- Seasonal adjustment factor.
    --
    -- Examples:
    -- 0.80
    --     demand is expected to be 20% below baseline
    -- 1.00
    --     normal demand
    -- 1.20
    --     demand is expected to be 20% above baseline
    seasonal_factor NUMERIC(6,3) NOT NULL
        CHECK (
            seasonal_factor > 0
        ),

    -- Optional explanation.
    --
    -- Example:
    -- "Football season / holiday demand"
    notes TEXT,

    -- Track when this row was last modified.
    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    -- We only want one seasonality setting
    -- for each calendar month.
    UNIQUE (month_number)
);

-- ============================================================
-- TABLE 2: FORECASTS
--
-- Purpose:
-- Save each forecast permanently.
--
-- This is important because we do NOT want an old forecast
-- to change later when more sales are added.
--
-- Example:
-- On November 1:
-- Forecast for next week = 120 jars
-- Later actual demand = 110 jars
-- We still need to remember:
-- original saved forecast = 120
-- actual = 110
-- difference = -10
--
-- This is the "Forecast vs Actual" requirement.
-- ============================================================

CREATE TABLE IF NOT EXISTS forecasts (

    -- Unique forecast ID.
    forecast_id SERIAL PRIMARY KEY,

    -- Product being forecast.
    -- Example:
    -- 1 = Original
    -- 2 = Slobberin'
    product_id INTEGER NOT NULL
        REFERENCES products(product_id),

    -- Geographic segment.
    -- For our prototype we can use county as the region.
    -- Example:
    -- Wake
    -- Durham
    -- ALL
    sales_region VARCHAR(100) NOT NULL,

    -- Sales channel segment.
    --
    -- Examples:
    -- Shopify
    -- Farmers Market
    -- Wholesale
    -- ALL
    sales_channel VARCHAR(50) NOT NULL,

    -- First day of the week being forecast.
    --
    -- We will treat Monday as the beginning
    -- of a forecast week.
    forecast_week DATE NOT NULL,

    -- ========================================================
    -- BASELINE FORECAST
    --
    -- Forecast BEFORE applying the seasonal factor.
    --
    -- Example:
    -- Exponential smoothing baseline = 100 jars
    -- ========================================================

    baseline_forecast_quantity NUMERIC(10,2) NOT NULL
        CHECK (
            baseline_forecast_quantity >= 0
        ),

    -- ========================================================
    -- SAVED FINAL FORECAST
    --
    -- Baseline forecast AFTER seasonality is applied.
    -- Project example:
    -- baseline = 100
    -- seasonal factor = 1.20
    -- saved forecast = 120
    -- ========================================================

    saved_forecast_quantity NUMERIC(10,2) NOT NULL
        CHECK (
            saved_forecast_quantity >= 0
        ),

    -- ========================================================
    -- SMOOTHING FACTOR
    -- Alpha used by exponential smoothing.
    -- Alpha must be between 0 and 1.
    -- Example:
    -- 0.30
    -- ========================================================

    smoothing_factor NUMERIC(5,4) NOT NULL
        CHECK (
            smoothing_factor > 0
            AND smoothing_factor <= 1
        ),

    -- Demand tier copied into the saved forecast.
    --
    -- IMPORTANT:
    -- We save it here even though it also exists
    -- in forecast_seasonality.
    --
    -- Why?
    --
    -- Because seasonal settings may change later.
    -- Historical forecasts must preserve the assumptions
    -- that were used at the time the forecast was created.
    demand_tier VARCHAR(20) NOT NULL
        CHECK (
            demand_tier IN (
                'LOW',
                'MEDIUM',
                'HIGH'
            )
        ),

    -- Seasonal factor used for THIS forecast.
    -- Again, this is saved as a snapshot so that
    -- historical forecasts remain auditable.
    seasonal_factor NUMERIC(6,3) NOT NULL
        CHECK (
            seasonal_factor > 0
        ),

    -- Actual quantity sold during the forecast week.
    -- This is NULL when the week has not been completed yet.
    -- Later the system can calculate actual sales from
    -- sales + sale_items and update this value.
    actual_quantity NUMERIC(10,2)
        CHECK (
            actual_quantity IS NULL
            OR actual_quantity >= 0
        ),

    -- Difference between actual and forecast.
    --
    -- Example:
    --
    -- Forecast = 120
    -- Actual = 110
    --
    -- forecast_error = -10
    --
    -- Negative:
    -- actual demand was below forecast.
    --
    -- Positive:
    -- actual demand was above forecast.
    forecast_error NUMERIC(10,2),

    -- When this forecast was created.
    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    -- Optional notes.
    notes TEXT
);


-- ============================================================
-- INDEXES
--
-- These will make forecast filtering faster later.
-- ============================================================

-- Search forecasts by product.
CREATE INDEX IF NOT EXISTS idx_forecasts_product
ON forecasts(product_id);

-- Search forecasts by week.
CREATE INDEX IF NOT EXISTS idx_forecasts_week
ON forecasts(forecast_week);

-- Search forecasts by region.
CREATE INDEX IF NOT EXISTS idx_forecasts_region
ON forecasts(sales_region);

-- Search forecasts by sales channel.
CREATE INDEX IF NOT EXISTS idx_forecasts_channel
ON forecasts(sales_channel);


-- ============================================================
-- INSERT INITIAL MONTHLY SEASONAL SETTINGS
--
-- These are PROTOTYPE DEFAULTS only.
--
-- They are not meant to represent verified historical demand.
-- Dr. D will eventually edit these assumptions.
--
-- We start with:
--
-- LOW    = 0.80
-- MEDIUM = 1.00
-- HIGH   = 1.20
--
-- This gives us useful values for demonstrating the system.
-- ============================================================

INSERT INTO forecast_seasonality (
    month_number,
    month_name,
    demand_tier,
    seasonal_factor,
    notes
)
VALUES

    (
        1,
        'January',
        'LOW',
        0.800,
        'Prototype seasonal assumption.'
    ),

    (
        2,
        'February',
        'LOW',
        0.800,
        'Prototype seasonal assumption.'
    ),

    (
        3,
        'March',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        4,
        'April',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        5,
        'May',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        6,
        'June',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        7,
        'July',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        8,
        'August',
        'MEDIUM',
        1.000,
        'Prototype seasonal assumption.'
    ),

    (
        9,
        'September',
        'HIGH',
        1.200,
        'Prototype seasonal assumption.'
    ),

    (
        10,
        'October',
        'HIGH',
        1.200,
        'Prototype seasonal assumption.'
    ),

    (
        11,
        'November',
        'HIGH',
        1.200,
        'Prototype seasonal assumption.'
    ),

    (
        12,
        'December',
        'HIGH',
        1.200,
        'Prototype seasonal assumption.'
    )

-- month_number is UNIQUE. If a month already has a setting
-- (for example one that was edited in the application),
-- that setting is kept and the default is not inserted.
ON CONFLICT (month_number) DO NOTHING;


-- ============================================================
-- CHECK 1:
-- View monthly seasonal settings.
-- ============================================================

SELECT
    seasonality_id,
    month_number,
    month_name,
    demand_tier,
    seasonal_factor,
    notes
FROM forecast_seasonality
ORDER BY month_number;



-- ============================================================
-- CHECK 2:
-- Forecast table should currently be empty.
-- ============================================================

SELECT *
FROM forecasts
ORDER BY forecast_id;





