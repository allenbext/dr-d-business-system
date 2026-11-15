"""
forecast_service.py

Purpose:
Business logic for demand forecasting and forecast accuracy.

Current functionality:

1. Read weekly sales history.
2. Filter by product, region, and sales channel.
3. Restrict forecast history to COMPLETE weeks BEFORE the forecast week.
4. Fill weeks without sales with zero demand.
5. Read and update monthly seasonal settings.
6. Deseasonalize historical demand.
7. Calculate baseline demand using exponential smoothing.
8. Apply the forecast-month seasonal factor.
9. Preview a forecast WITHOUT saving it.
10. Save forecasts permanently (one per product/region/channel/week).
11. Calculate actual demand for completed forecast weeks.
12. Calculate Forecast vs Actual error.

Important forecasting rules:

Rule 1 - No data leakage.
    A forecast for a given week may only use information
    that existed BEFORE that week began.

Rule 2 - Only complete weeks.
    The week that is still in progress today is NOT used as
    history, because a half-finished week would look like
    unusually low demand.

Rule 3 - A week without sales is a week with ZERO demand.
    Weeks without any sale are added to the history with
    quantity 0. Without this, exponential smoothing would treat
    two sales weeks that are a month apart as if they were
    consecutive, and the forecast would be too high.

Rule 4 - A saved forecast never changes.
    Only one forecast can be saved for the same
    product / region / channel / week. A second attempt is
    rejected instead of silently creating a duplicate.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import psycopg

from db import get_connection


# ============================================================
# ROUND QUANTITY
# ============================================================

def round_quantity(value):
    """
    Round forecast quantities to two decimal places.
    """

    value = Decimal(str(value))

    return value.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


# ============================================================
# WEEK HELPERS
# ============================================================

def get_week_start(any_date):
    """
    Return the Monday of the week that contains any_date.

    Example:

        Saturday 2026-11-14  ->  Monday 2026-11-09
        Monday   2026-11-16  ->  Monday 2026-11-16
    """

    return any_date - timedelta(
        days=any_date.weekday()
    )


def get_next_forecast_week(today=None):
    """
    Return the Monday of NEXT week.

    This is the default week Dr. D would normally forecast.
    """

    if today is None:
        today = date.today()

    return get_week_start(today) + timedelta(days=7)


# ============================================================
# FORECAST FILTER OPTIONS
# ============================================================

def get_forecast_filter_options():
    """
    Read available regions and sales channels from sales data.

    "ALL" is added to both lists.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT DISTINCT county
                FROM sales
                WHERE county IS NOT NULL
                  AND TRIM(county) <> ''
                ORDER BY county;
                """
            )

            region_rows = cur.fetchall()

            cur.execute(
                """
                SELECT DISTINCT sales_channel
                FROM sales
                WHERE sales_channel IS NOT NULL
                  AND TRIM(sales_channel) <> ''
                ORDER BY sales_channel;
                """
            )

            channel_rows = cur.fetchall()

    regions = ["ALL"]

    for row in region_rows:
        regions.append(row[0])

    channels = ["ALL"]

    for row in channel_rows:
        channels.append(row[0])

    return {
        "regions": regions,
        "channels": channels
    }


# ============================================================
# WEEKLY SALES HISTORY
# ============================================================

def get_weekly_sales_history(
    product_id,
    sales_region="ALL",
    sales_channel="ALL",
    before_date=None,
    today=None
):
    """
    Aggregate product sales by week (Monday through Sunday).

    Parameters:

        product_id:
            Product being analyzed.

        sales_region:
            County filter or ALL.

        sales_channel:
            Channel filter or ALL.

        before_date:
            Optional cutoff date, normally the forecast week.

            Only weeks that START before the week containing
            before_date are returned.

            Example:

                forecast_week = 2026-11-02

            The last history week is 2026-10-26.

        today:
            Only used for testing. Defaults to date.today().

    Returned history:

        - contains COMPLETE weeks only (the week in progress
          today is never included);

        - is continuous: every week between the first week with
          a sale and the last complete week is present;

        - weeks without sales have quantity_sold = 0.
    """

    if today is None:
        today = date.today()

    # --------------------------------------------------------
    # HISTORY END
    #
    # history_end is EXCLUSIVE: sales on or after this Monday
    # are not used.
    #
    # It is the earlier of:
    #   - the Monday of the week in progress today;
    #   - the Monday of the week being forecast.
    # --------------------------------------------------------

    history_end = get_week_start(today)

    if before_date is not None:

        history_end = min(
            history_end,
            get_week_start(before_date)
        )

    # --------------------------------------------------------
    # READ WEEKS THAT HAVE SALES
    # --------------------------------------------------------

    query = """
        SELECT
            DATE_TRUNC('week', s.sale_date)::date AS week_start,
            SUM(si.quantity) AS quantity_sold

        FROM sale_items AS si

        JOIN sales AS s
            ON si.sale_id = s.sale_id

        WHERE si.product_id = %s
          AND s.sale_date < %s
    """

    parameters = [
        product_id,
        history_end
    ]

    if sales_region != "ALL":

        query += """
            AND s.county = %s
        """

        parameters.append(sales_region)

    if sales_channel != "ALL":

        query += """
            AND s.sales_channel = %s
        """

        parameters.append(sales_channel)

    query += """
        GROUP BY DATE_TRUNC('week', s.sale_date)::date
        ORDER BY week_start;
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(query, parameters)

            rows = cur.fetchall()

    if len(rows) == 0:

        return []

    # --------------------------------------------------------
    # FILL WEEKS WITHOUT SALES WITH ZERO
    #
    # Example:
    #
    #   Sales exist in weeks:   Oct 05, Oct 26
    #
    #   Returned history:       Oct 05 = 40
    #                           Oct 12 = 0
    #                           Oct 19 = 0
    #                           Oct 26 = 35
    # --------------------------------------------------------

    quantity_by_week = {
        row[0]: int(row[1])
        for row in rows
    }

    first_week = rows[0][0]

    last_week = history_end - timedelta(days=7)

    history = []

    current_week = first_week

    while current_week <= last_week:

        history.append(
            {
                "week_start": current_week,
                "quantity_sold": quantity_by_week.get(current_week, 0)
            }
        )

        current_week += timedelta(days=7)

    return history


# ============================================================
# GET SEASONALITY FOR ONE MONTH
# ============================================================

def get_seasonality_for_month(month_number):
    """
    Read demand tier and seasonal factor for one month.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    month_number,
                    month_name,
                    demand_tier,
                    seasonal_factor
                FROM forecast_seasonality
                WHERE month_number = %s;
                """,
                (month_number,)
            )

            row = cur.fetchone()

    if row is None:

        raise ValueError(
            f"No seasonal setting exists for month "
            f"{month_number}."
        )

    return {
        "month_number": row[0],
        "month_name": row[1],
        "demand_tier": row[2],
        "seasonal_factor": row[3]
    }


# ============================================================
# GET ALL SEASONAL SETTINGS
# ============================================================

def get_all_seasonality():
    """
    Return all 12 monthly seasonal assumptions.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    seasonality_id,
                    month_number,
                    month_name,
                    demand_tier,
                    seasonal_factor,
                    notes
                FROM forecast_seasonality
                ORDER BY month_number;
                """
            )

            rows = cur.fetchall()

    settings = []

    for row in rows:

        settings.append(
            {
                "seasonality_id": row[0],
                "month_number": row[1],
                "month_name": row[2],
                "demand_tier": row[3],
                "seasonal_factor": row[4],
                "notes": row[5]
            }
        )

    return settings


# ============================================================
# UPDATE SEASONALITY
# ============================================================

def update_seasonality(
    month_number,
    demand_tier,
    seasonal_factor,
    notes=None
):
    """
    Update one monthly seasonal assumption.
    """

    allowed_tiers = [
        "LOW",
        "MEDIUM",
        "HIGH"
    ]

    if demand_tier not in allowed_tiers:

        raise ValueError(
            "Demand tier must be LOW, MEDIUM, or HIGH."
        )

    factor = Decimal(str(seasonal_factor))

    if factor <= 0:

        raise ValueError(
            "Seasonal factor must be greater than zero."
        )

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE forecast_seasonality
                    SET
                        demand_tier = %s,
                        seasonal_factor = %s,
                        notes = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE month_number = %s
                    RETURNING month_name;
                    """,
                    (
                        demand_tier,
                        factor,
                        notes,
                        month_number
                    )
                )

                row = cur.fetchone()

                if row is None:

                    raise ValueError(
                        f"Month {month_number} was not found."
                    )

                month_name = row[0]

            conn.commit()

        except Exception:

            conn.rollback()

            raise

    return {
        "month_number": month_number,
        "month_name": month_name,
        "demand_tier": demand_tier,
        "seasonal_factor": factor,
        "notes": notes
    }


# ============================================================
# DESEASONALIZE HISTORY
# ============================================================

def deseasonalize_weekly_history(weekly_history):
    """
    Remove seasonal effects from weekly sales.

    Formula:

        Deseasonalized Demand
        =
        Actual Demand / Seasonal Factor

    All 12 monthly settings are read from PostgreSQL ONCE,
    not once per week.
    """

    # --------------------------------------------------------
    # LOAD SEASONAL SETTINGS ONCE
    # --------------------------------------------------------

    seasonality_by_month = {
        setting["month_number"]: setting
        for setting in get_all_seasonality()
    }

    adjusted_history = []

    for week in weekly_history:

        week_start = week["week_start"]

        quantity_sold = Decimal(
            str(week["quantity_sold"])
        )

        seasonal_setting = seasonality_by_month.get(
            week_start.month
        )

        if seasonal_setting is None:

            raise ValueError(
                f"No seasonal setting exists for month "
                f"{week_start.month}."
            )

        seasonal_factor = Decimal(
            str(seasonal_setting["seasonal_factor"])
        )

        deseasonalized_quantity = (
            quantity_sold / seasonal_factor
        )

        adjusted_history.append(
            {
                "week_start": week_start,
                "quantity_sold": quantity_sold,
                "demand_tier": seasonal_setting["demand_tier"],
                "seasonal_factor": seasonal_factor,
                "deseasonalized_quantity": round_quantity(
                    deseasonalized_quantity
                )
            }
        )

    return adjusted_history


# ============================================================
# EXPONENTIAL SMOOTHING
# ============================================================

def calculate_exponential_smoothing(
    weekly_history,
    smoothing_factor
):
    """
    Calculate baseline demand with simple
    exponential smoothing.

    Formula:

        New Forecast =
            alpha * Actual
            +
            (1 - alpha) * Previous Forecast

    The Actual value used here is the
    deseasonalized weekly quantity.
    """

    alpha = Decimal(str(smoothing_factor))

    if alpha <= 0 or alpha > 1:

        raise ValueError(
            "Smoothing factor must be greater than 0 "
            "and less than or equal to 1."
        )

    if len(weekly_history) == 0:

        raise ValueError(
            "At least one historical week is required."
        )

    # Initial forecast = first observation.
    forecast = Decimal(
        str(weekly_history[0]["deseasonalized_quantity"])
    )

    for week in weekly_history[1:]:

        actual = Decimal(
            str(week["deseasonalized_quantity"])
        )

        forecast = (
            alpha * actual
            + (Decimal("1") - alpha) * forecast
        )

    return round_quantity(forecast)


# ============================================================
# CALCULATE FORECAST (NO DATABASE WRITE)
# ============================================================

def calculate_forecast(
    product_id,
    forecast_week,
    sales_region="ALL",
    sales_channel="ALL",
    smoothing_factor=0.30
):
    """
    Calculate a forecast WITHOUT saving it.

    The Streamlit page can call this function to show the
    expected forecast before Dr. D decides to save it.

    generate_forecast() uses exactly the same calculation,
    so the previewed number and the saved number always match.
    """

    # --------------------------------------------------------
    # FORECAST WEEK MUST START ON MONDAY
    # --------------------------------------------------------

    if forecast_week.weekday() != 0:

        raise ValueError(
            "Forecast Week must be a Monday."
        )

    # --------------------------------------------------------
    # HISTORICAL DATA
    # --------------------------------------------------------

    weekly_history = get_weekly_sales_history(
        product_id=product_id,
        sales_region=sales_region,
        sales_channel=sales_channel,
        before_date=forecast_week
    )

    if len(weekly_history) == 0:

        raise ValueError(
            "No historical sales exist before the selected "
            "forecast week."
        )

    # --------------------------------------------------------
    # DESEASONALIZE
    # --------------------------------------------------------

    adjusted_history = deseasonalize_weekly_history(
        weekly_history
    )

    # --------------------------------------------------------
    # BASELINE FORECAST
    # --------------------------------------------------------

    baseline_forecast = calculate_exponential_smoothing(
        weekly_history=adjusted_history,
        smoothing_factor=smoothing_factor
    )

    # --------------------------------------------------------
    # FORECAST MONTH SEASONALITY
    # --------------------------------------------------------

    forecast_seasonality = get_seasonality_for_month(
        forecast_week.month
    )

    seasonal_factor = Decimal(
        str(forecast_seasonality["seasonal_factor"])
    )

    # --------------------------------------------------------
    # FINAL FORECAST
    # --------------------------------------------------------

    saved_forecast_quantity = round_quantity(
        Decimal(str(baseline_forecast)) * seasonal_factor
    )

    return {
        "product_id": product_id,
        "sales_region": sales_region,
        "sales_channel": sales_channel,
        "forecast_week": forecast_week,
        "smoothing_factor": Decimal(str(smoothing_factor)),
        "baseline_forecast_quantity": baseline_forecast,
        "demand_tier": forecast_seasonality["demand_tier"],
        "seasonal_factor": seasonal_factor,
        "saved_forecast_quantity": saved_forecast_quantity,
        "weekly_history": adjusted_history
    }


# ============================================================
# FIND AN ALREADY SAVED FORECAST
# ============================================================

def find_saved_forecast(
    product_id,
    forecast_week,
    sales_region="ALL",
    sales_channel="ALL"
):
    """
    Return the saved forecast for this exact
    product / region / channel / week, or None.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    forecast_id,
                    saved_forecast_quantity,
                    created_at
                FROM forecasts
                WHERE product_id = %s
                  AND sales_region = %s
                  AND sales_channel = %s
                  AND forecast_week = %s
                ORDER BY forecast_id
                LIMIT 1;
                """,
                (
                    product_id,
                    sales_region,
                    sales_channel,
                    forecast_week
                )
            )

            row = cur.fetchone()

    if row is None:

        return None

    return {
        "forecast_id": row[0],
        "saved_forecast_quantity": row[1],
        "created_at": row[2]
    }


# ============================================================
# GENERATE AND SAVE FORECAST
# ============================================================

def generate_forecast(
    product_id,
    forecast_week,
    sales_region="ALL",
    sales_channel="ALL",
    smoothing_factor=0.30
):
    """
    Generate and save a forecast.

    Only ONE forecast can be saved for the same
    product / region / channel / week.

    If one already exists, a ValueError is raised and the
    original saved forecast stays unchanged. This protects the
    Forecast vs Actual comparison.
    """

    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    existing = find_saved_forecast(
        product_id=product_id,
        forecast_week=forecast_week,
        sales_region=sales_region,
        sales_channel=sales_channel
    )

    if existing is not None:

        raise ValueError(
            "A forecast for this product, region, channel and "
            "week is already saved "
            f"(Forecast ID {existing['forecast_id']}: "
            f"{float(existing['saved_forecast_quantity']):,.0f} jars). "
            "Saved forecasts are never overwritten."
        )

    # --------------------------------------------------------
    # CALCULATE
    # --------------------------------------------------------

    result = calculate_forecast(
        product_id=product_id,
        forecast_week=forecast_week,
        sales_region=sales_region,
        sales_channel=sales_channel,
        smoothing_factor=smoothing_factor
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO forecasts (
                        product_id,
                        sales_region,
                        sales_channel,
                        forecast_week,
                        baseline_forecast_quantity,
                        saved_forecast_quantity,
                        smoothing_factor,
                        demand_tier,
                        seasonal_factor
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING forecast_id;
                    """,
                    (
                        product_id,
                        sales_region,
                        sales_channel,
                        forecast_week,
                        result["baseline_forecast_quantity"],
                        result["saved_forecast_quantity"],
                        result["smoothing_factor"],
                        result["demand_tier"],
                        result["seasonal_factor"]
                    )
                )

                forecast_id = cur.fetchone()[0]

            conn.commit()

        except psycopg.errors.UniqueViolation:

            # The database unique index (08_forecast_integrity.sql)
            # is the final safety net if two saves happen at
            # exactly the same moment.
            conn.rollback()

            raise ValueError(
                "A forecast for this product, region, channel and "
                "week is already saved. Saved forecasts are never "
                "overwritten."
            )

        except Exception:

            conn.rollback()

            raise

    result["forecast_id"] = forecast_id

    return result


# ============================================================
# CALCULATE ACTUAL FOR ONE FORECAST
# ============================================================

def calculate_actual_for_forecast(forecast_id):
    """
    Calculate actual sales for a completed forecast week.

    Week definition:
        Monday through Sunday.
    """

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # ---------------------------------------------
                # READ SAVED FORECAST
                # ---------------------------------------------

                cur.execute(
                    """
                    SELECT
                        product_id,
                        sales_region,
                        sales_channel,
                        forecast_week,
                        saved_forecast_quantity
                    FROM forecasts
                    WHERE forecast_id = %s;
                    """,
                    (forecast_id,)
                )

                forecast_row = cur.fetchone()

                if forecast_row is None:

                    raise ValueError(
                        f"Forecast ID {forecast_id} "
                        f"does not exist."
                    )

                product_id = forecast_row[0]
                sales_region = forecast_row[1]
                sales_channel = forecast_row[2]
                forecast_week = forecast_row[3]

                saved_forecast = Decimal(
                    str(forecast_row[4])
                )

                week_end = forecast_week + timedelta(days=6)

                # ---------------------------------------------
                # ONLY COMPLETED WEEKS
                # ---------------------------------------------

                if week_end >= date.today():

                    raise ValueError(
                        "This forecast week has not finished yet."
                    )

                # ---------------------------------------------
                # ACTUAL SALES QUERY
                # ---------------------------------------------

                query = """
                    SELECT
                        COALESCE(SUM(si.quantity), 0)

                    FROM sale_items AS si

                    JOIN sales AS s
                        ON si.sale_id = s.sale_id

                    WHERE si.product_id = %s
                      AND s.sale_date >= %s
                      AND s.sale_date <= %s
                """

                parameters = [
                    product_id,
                    forecast_week,
                    week_end
                ]

                if sales_region != "ALL":

                    query += """
                        AND s.county = %s
                    """

                    parameters.append(sales_region)

                if sales_channel != "ALL":

                    query += """
                        AND s.sales_channel = %s
                    """

                    parameters.append(sales_channel)

                cur.execute(query, parameters)

                actual_quantity = Decimal(
                    str(cur.fetchone()[0])
                )

                # ---------------------------------------------
                # ERROR = ACTUAL - FORECAST
                # ---------------------------------------------

                forecast_error = round_quantity(
                    actual_quantity - saved_forecast
                )

                # ---------------------------------------------
                # SAVE ACTUAL
                #
                # Only actual_quantity and forecast_error are
                # written. The saved forecast is never touched.
                # ---------------------------------------------

                cur.execute(
                    """
                    UPDATE forecasts
                    SET
                        actual_quantity = %s,
                        forecast_error = %s
                    WHERE forecast_id = %s;
                    """,
                    (
                        actual_quantity,
                        forecast_error,
                        forecast_id
                    )
                )

            conn.commit()

        except Exception:

            conn.rollback()

            raise

    return {
        "forecast_id": forecast_id,
        "forecast_week": forecast_week,
        "week_end": week_end,
        "saved_forecast": saved_forecast,
        "actual_quantity": actual_quantity,
        "forecast_error": forecast_error
    }


# ============================================================
# UPDATE COMPLETED FORECASTS
# ============================================================

def update_completed_forecasts():
    """
    Calculate actual sales for all completed forecasts
    that do not already have actual_quantity.
    """

    today = date.today()

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    forecast_id,
                    forecast_week
                FROM forecasts
                WHERE actual_quantity IS NULL
                ORDER BY forecast_week;
                """
            )

            rows = cur.fetchall()

    updated_forecasts = []

    for row in rows:

        forecast_id = row[0]
        forecast_week = row[1]

        week_end = forecast_week + timedelta(days=6)

        if week_end < today:

            result = calculate_actual_for_forecast(
                forecast_id
            )

            updated_forecasts.append(result)

    return updated_forecasts


# ============================================================
# GET SAVED FORECASTS
# ============================================================

def get_saved_forecasts():
    """
    Return all saved forecasts.

    The dictionary keys match the column names of the
    forecasts table, so the Streamlit page can rename them
    to friendly headers.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    f.forecast_id,
                    f.forecast_week,
                    p.product_name,
                    f.sales_region,
                    f.sales_channel,
                    f.baseline_forecast_quantity,
                    f.demand_tier,
                    f.seasonal_factor,
                    f.saved_forecast_quantity,
                    f.actual_quantity,
                    f.forecast_error,
                    f.smoothing_factor
                FROM forecasts AS f

                JOIN products AS p
                    ON f.product_id = p.product_id

                ORDER BY
                    f.forecast_week DESC,
                    f.forecast_id DESC;
                """
            )

            rows = cur.fetchall()

    forecasts = []

    for row in rows:

        forecasts.append(
            {
                "forecast_id": row[0],
                "forecast_week": row[1],
                "product_name": row[2],
                "sales_region": row[3],
                "sales_channel": row[4],
                "baseline_forecast_quantity": row[5],
                "demand_tier": row[6],
                "seasonal_factor": row[7],
                "saved_forecast_quantity": row[8],
                "actual_quantity": row[9],
                "forecast_error": row[10],
                "smoothing_factor": row[11]
            }
        )

    return forecasts


# ============================================================
# GET FORECAST VS ACTUAL
# ============================================================

def get_forecast_vs_actual():
    """
    Return completed forecasts with actual demand.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    f.forecast_id,
                    f.forecast_week,
                    p.product_name,
                    f.sales_region,
                    f.sales_channel,
                    f.saved_forecast_quantity,
                    f.actual_quantity,
                    f.forecast_error
                FROM forecasts AS f

                JOIN products AS p
                    ON f.product_id = p.product_id

                WHERE f.actual_quantity IS NOT NULL

                ORDER BY
                    f.forecast_week,
                    f.forecast_id;
                """
            )

            rows = cur.fetchall()

    results = []

    for row in rows:

        results.append(
            {
                "forecast_id": row[0],
                "forecast_week": row[1],
                "product_name": row[2],
                "sales_region": row[3],
                "sales_channel": row[4],
                "forecast_quantity": row[5],
                "actual_quantity": row[6],
                "difference": row[7]
            }
        )

    return results