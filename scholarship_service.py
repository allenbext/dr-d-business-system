"""
scholarship_service.py

Purpose:
Provide scholarship reporting for Slobberin' Sauce.

Current functionality:

1. Monthly scholarship summary.
2. Monthly scholarship detail.
3. Year-to-date scholarship summary.
4. Year-to-date scholarship detail.
5. Current scholarship rate.

Business rule:

Slobberin' Sauce scholarship rate = 16% of allocated revenue.

The actual scholarship amount is stored in sale_items
when each sale is recorded. These reports summarize those
stored transaction values.

Where the numbers come from:

    v_scholarship_lines

    The view contains every sold line of a product whose
    products.scholarship_rate is greater than zero.

    It is created by:

        sql/10_reporting_views_and_constraints.sql

    Because the view looks at the scholarship RATE and not at
    a fixed product ID, a second licensed product would be
    included automatically.
"""

from datetime import date

from db import get_connection


# ============================================================
# PERIOD HELPER
# ============================================================

def _get_period(
    year,
    month,
    year_to_date=False
):
    """
    Return the first day of the period and the first day
    AFTER the period.

    Monthly (year_to_date=False):

        (2026, 11) -> 2026-11-01 ... 2026-12-01

    Year to date (year_to_date=True):

        (2026, 11) -> 2026-01-01 ... 2026-12-01

    Queries use:

        sale_date >= period_start AND sale_date < period_end
    """

    year = int(year)
    month = int(month)

    if year_to_date:

        period_start = date(year, 1, 1)

    else:

        period_start = date(year, month, 1)

    if month == 12:

        period_end = date(year + 1, 1, 1)

    else:

        period_end = date(year, month + 1, 1)

    return period_start, period_end


# ============================================================
# INTERNAL: SUMMARY FOR A PERIOD
# ============================================================

def _get_scholarship_summary(
    period_start,
    period_end
):
    """
    Return scholarship totals for one period.

    Returns:
        bottles_sold
        eligible_revenue
        scholarship_amount
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(quantity), 0)
                        AS bottles_sold,

                    COALESCE(SUM(allocated_revenue), 0)
                        AS eligible_revenue,

                    COALESCE(SUM(scholarship_amount), 0)
                        AS scholarship_amount

                FROM v_scholarship_lines

                WHERE sale_date >= %s
                  AND sale_date < %s;
                """,
                (
                    period_start,
                    period_end
                )
            )

            row = cur.fetchone()

    return {
        "bottles_sold": row[0],
        "eligible_revenue": row[1],
        "scholarship_amount": row[2]
    }


# ============================================================
# INTERNAL: DETAIL FOR A PERIOD
# ============================================================

def _get_scholarship_details(
    period_start,
    period_end
):
    """
    Return the individual scholarship sale lines
    for one period. Newest sales appear first.
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
                    quantity,
                    allocated_revenue,
                    scholarship_amount

                FROM v_scholarship_lines

                WHERE sale_date >= %s
                  AND sale_date < %s

                ORDER BY
                    sale_date DESC,
                    sale_id DESC;
                """,
                (
                    period_start,
                    period_end
                )
            )

            rows = cur.fetchall()

    details = []

    for row in rows:

        details.append(
            {
                "sale_id": row[0],
                "sale_date": row[1],
                "sales_channel": row[2],
                "payment_method": row[3],
                "quantity": row[4],
                "allocated_revenue": row[5],
                "scholarship_amount": row[6]
            }
        )

    return details


# ============================================================
# MONTHLY SCHOLARSHIP SUMMARY
# ============================================================

def get_monthly_scholarship_summary(
    year,
    month
):
    """
    Return monthly Slobberin' Sauce scholarship totals.

    Returns:
        bottles_sold
        eligible_revenue
        scholarship_amount
    """

    period_start, period_end = _get_period(
        year,
        month
    )

    return _get_scholarship_summary(
        period_start,
        period_end
    )


# ============================================================
# MONTHLY SCHOLARSHIP DETAILS
# ============================================================

def get_monthly_scholarship_details(
    year,
    month
):
    """
    Return individual Slobberin' Sauce sale lines
    for one selected month.
    """

    period_start, period_end = _get_period(
        year,
        month
    )

    return _get_scholarship_details(
        period_start,
        period_end
    )


# ============================================================
# YEAR-TO-DATE SCHOLARSHIP SUMMARY
# ============================================================

def get_ytd_scholarship_summary(
    year,
    through_month
):
    """
    Return scholarship totals from January 1
    through the end of the selected month.

    Example:

        year = 2026
        through_month = 11

    Includes:
        January 1, 2026 through November 30, 2026
    """

    period_start, period_end = _get_period(
        year,
        through_month,
        year_to_date=True
    )

    return _get_scholarship_summary(
        period_start,
        period_end
    )


# ============================================================
# YEAR-TO-DATE SCHOLARSHIP DETAILS
# ============================================================

def get_ytd_scholarship_details(
    year,
    through_month
):
    """
    Return individual Slobberin' sale lines from January
    through the end of the selected month.
    """

    period_start, period_end = _get_period(
        year,
        through_month,
        year_to_date=True
    )

    return _get_scholarship_details(
        period_start,
        period_end
    )


# ============================================================
# CURRENT SCHOLARSHIP RATE
# ============================================================

def get_scholarship_rate():
    """
    Return the scholarship rate stored in the products table
    (for example Decimal("0.1600") for 16%).

    Screens and reports show this value instead of a number
    typed into the code, so the displayed rate always matches
    the rate used in the calculation.

    If no product has a scholarship rate, 0 is returned.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    COALESCE(MAX(scholarship_rate), 0)

                FROM products

                WHERE scholarship_rate > 0;
                """
            )

            row = cur.fetchone()

    return row[0]