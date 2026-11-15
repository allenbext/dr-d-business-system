"""
dashboard_service.py

Purpose:
Provide business summary data for the Streamlit Dashboard.

Current functionality:

1. Monthly dashboard summary
2. Weekly product sales
3. Recent sales
4. Revenue KPI:
   - This Month
   - Year to Date
   - All Time
5. Estimated Profit KPI:
   - This Month
   - Year to Date
   - All Time

Where the numbers come from:

    v_sale_financials
        One row per sale. Product cost, scholarship and
        estimated profit are already calculated there.

    v_scholarship_lines
        Sold lines of products that carry a scholarship
        contribution.

Both views are created by:

    sql/10_reporting_views_and_constraints.sql

Important financial definitions:

Revenue:
    Product sales only.
    Tax collected is NOT revenue.

Estimated Profit:
    Product Revenue
    + Shipping Revenue
    - Product Cost
    - Scholarship
    - Shopify / Card Fees
    - Shipping Expense

The formula itself is written only once, inside the view.

This is an operational estimate based on the costs currently
tracked by the prototype.

It is not intended to represent full accounting net income
because other overhead costs may exist outside the system.
"""

from datetime import date

from db import get_connection


# ============================================================
# MONTH RANGE HELPER
# ============================================================

def get_month_range(
    year,
    month
):
    """
    Return the first day of a month and the first day of the
    NEXT month.

    Example:

        get_month_range(2026, 11)
        -> (2026-11-01, 2026-12-01)

    Queries then use:

        sale_date >= first_day AND sale_date < next_first_day
    """

    first_day = date(
        int(year),
        int(month),
        1
    )

    if int(month) == 12:

        next_first_day = date(
            int(year) + 1,
            1,
            1
        )

    else:

        next_first_day = date(
            int(year),
            int(month) + 1,
            1
        )

    return first_day, next_first_day


# ============================================================
# MONTHLY DASHBOARD SUMMARY
# ============================================================

def get_monthly_dashboard_summary(
    year,
    month
):
    """
    Return financial and sales totals for one month.
    """

    first_day, next_first_day = get_month_range(
        year,
        month
    )

    with get_connection() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # SALES-LEVEL TOTALS
            # ------------------------------------------------

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(product_revenue), 0),
                    COALESCE(SUM(tax_collected), 0),
                    COALESCE(SUM(shipping_revenue), 0),
                    COALESCE(SUM(shopify_fee), 0),
                    COALESCE(SUM(shipping_expense), 0)

                FROM v_sale_financials

                WHERE sale_date >= %s
                  AND sale_date < %s;
                """,
                (
                    first_day,
                    next_first_day
                )
            )

            sales_row = cur.fetchone()

            # ------------------------------------------------
            # SCHOLARSHIP PRODUCT TOTALS (SLOBBERIN')
            # ------------------------------------------------

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(quantity), 0),
                    COALESCE(SUM(scholarship_amount), 0)

                FROM v_scholarship_lines

                WHERE sale_date >= %s
                  AND sale_date < %s;
                """,
                (
                    first_day,
                    next_first_day
                )
            )

            scholarship_row = cur.fetchone()

    return {
        "product_sales": sales_row[0],
        "tax_collected": sales_row[1],
        "shipping_revenue": sales_row[2],
        "shopify_fees": sales_row[3],
        "shipping_expense": sales_row[4],
        "slobberin_bottles": scholarship_row[0],
        "scholarship_owed": scholarship_row[1]
    }


# ============================================================
# FINANCIAL KPI
# ============================================================

def get_financial_kpis(
    as_of_date=None
):
    """
    Calculate Revenue and Estimated Profit for:

    - Current Month   (first day of the month through as_of_date)
    - Year to Date    (January 1 through as_of_date)
    - All Time        (everything through as_of_date)

    FILTER (WHERE ...) is standard PostgreSQL syntax that makes
    an aggregate count only the rows matching a condition.
    """

    if as_of_date is None:

        as_of_date = date.today()

    month_start = as_of_date.replace(day=1)

    year_start = as_of_date.replace(month=1, day=1)

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    COALESCE(
                        SUM(product_revenue)
                            FILTER (WHERE sale_date >= %(month_start)s),
                        0
                    ) AS month_revenue,

                    COALESCE(
                        SUM(product_revenue)
                            FILTER (WHERE sale_date >= %(year_start)s),
                        0
                    ) AS ytd_revenue,

                    COALESCE(
                        SUM(product_revenue),
                        0
                    ) AS all_time_revenue,

                    COALESCE(
                        SUM(estimated_profit)
                            FILTER (WHERE sale_date >= %(month_start)s),
                        0
                    ) AS month_profit,

                    COALESCE(
                        SUM(estimated_profit)
                            FILTER (WHERE sale_date >= %(year_start)s),
                        0
                    ) AS ytd_profit,

                    COALESCE(
                        SUM(estimated_profit),
                        0
                    ) AS all_time_profit

                FROM v_sale_financials

                WHERE sale_date <= %(as_of_date)s;
                """,
                {
                    "month_start": month_start,
                    "year_start": year_start,
                    "as_of_date": as_of_date
                }
            )

            row = cur.fetchone()

    return {
        "month_revenue": row[0],
        "ytd_revenue": row[1],
        "all_time_revenue": row[2],
        "month_profit": row[3],
        "ytd_profit": row[4],
        "all_time_profit": row[5]
    }


# ============================================================
# WEEKLY SALES
# ============================================================

def get_weekly_sales(
    year,
    month
):
    """
    Return product revenue grouped by week
    for the sales of one month.
    """

    first_day, next_first_day = get_month_range(
        year,
        month
    )

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    DATE_TRUNC('week', sale_date)::date AS week_start,
                    COALESCE(SUM(product_revenue), 0) AS product_sales

                FROM v_sale_financials

                WHERE sale_date >= %s
                  AND sale_date < %s

                GROUP BY
                    DATE_TRUNC('week', sale_date)::date

                ORDER BY
                    week_start;
                """,
                (
                    first_day,
                    next_first_day
                )
            )

            rows = cur.fetchall()

    weekly_sales = []

    for row in rows:

        weekly_sales.append(
            {
                "week_start": row[0],
                "product_sales": row[1]
            }
        )

    return weekly_sales


# ============================================================
# RECENT SALES
# ============================================================

def get_recent_sales(
    limit=10
):
    """
    Return recent sale records.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    sale_id,
                    sale_date,
                    sales_channel,
                    payment_method,
                    product_revenue,
                    tax_collected,
                    state,
                    county

                FROM v_sale_financials

                ORDER BY
                    sale_date DESC,
                    sale_id DESC

                LIMIT %s;
                """,
                (limit,)
            )

            rows = cur.fetchall()

    sales = []

    for row in rows:

        sales.append(
            {
                "sale_id": row[0],
                "sale_date": row[1],
                "sales_channel": row[2],
                "payment_method": row[3],
                "product_revenue": row[4],
                "tax_collected": row[5],
                "state": row[6],
                "county": row[7]
            }
        )

    return sales