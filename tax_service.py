"""
tax_service.py

Purpose:
Sales tax helpers for Dr. D's Business System.

Two functions for Dr. D and his CPA:

1. NC SALES TAX BY COUNTY (monthly)

   North Carolina taxes food for home consumption at the local
   2% food rate only (no 4.75% state rate). Dr. D charges 2% on
   retail sales in North Carolina, on the sauce AND on the
   shipping charge.

   The NC return asks where each sale took place. A sale is
   sourced to the county where the customer receives it:
       - shipped order   -> county of the delivery address
       - farmers market  -> county of the market

   The monthly report groups the month's NC sales by county and
   compares the tax that was COLLECTED with the 2% that was
   EXPECTED, so typing mistakes are visible before the CPA sees
   the numbers.

2. SALES BY STATE (yearly)

   A state can require an out-of-state seller to collect its
   sales tax once the seller passes that state's "economic
   nexus" threshold. Most states use $100,000 of sales a year;
   some also count 200 orders. The thresholds differ by state
   and change over time, so the page lets Dr. D set the numbers
   he wants to watch, and flags any state that comes close.

Important:
These are bookkeeping aids, not tax advice. The rate and rules
below follow Dr. D's current practice and must be confirmed by
his CPA.

Rules used:

    Retail sale in NC      tax = 2% x (product revenue + shipping)
    Retail sale elsewhere  tax = 0   (no NC tax on out-of-state delivery)
    Wholesale              tax = 0   (sold for resale; the store
                                      collects tax from its customers)
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

import pandas as pd
from openpyxl.styles import Font

from db import get_connection


# ============================================================
# SETTINGS
# ============================================================

# Dr. D's home state. Sales delivered here are taxed in NC.
HOME_STATE = "NC"

# North Carolina local food rate (food is exempt from the
# 4.75% state rate but subject to the 2% local food rate).
NC_FOOD_TAX_RATE = Decimal("0.02")

# Default thresholds for the "Sales by State" check.
# The page lets the user change them.
DEFAULT_NEXUS_SALES = Decimal("100000")
DEFAULT_NEXUS_ORDERS = 200

# A state is flagged as "Approaching" at this share of a threshold.
APPROACHING_SHARE = Decimal("0.75")

CENT = Decimal("0.01")


def money(value):
    """
    Decimal rounded to cents (half up).
    """

    return Decimal(str(value or 0)).quantize(
        CENT,
        rounding=ROUND_HALF_UP
    )


# ============================================================
# 1. SUGGESTED TAX FOR ONE SALE
# ============================================================

def is_home_state(state):
    """
    True when the sale is delivered in North Carolina.

    An empty state is treated as NC, because sales entered by
    hand (markets, direct sales) take place in NC by default.
    """

    clean_state = (
        str(state).strip().upper()
        if state
        else ""
    )

    return clean_state in ("", HOME_STATE, "NORTH CAROLINA")


def suggest_sales_tax(
    product_revenue,
    shipping_revenue,
    sales_channel,
    state
):
    """
    Return the sales tax Dr. D would normally collect.

    Examples:
        Direct, NC, $18 product, $0 shipping  -> $0.36
        Shopify, NC, $18 product, $8 shipping -> $0.52
        Shopify, VA, $18 product, $8 shipping -> $0.00
        Wholesale, NC, $72                    -> $0.00

    This is a SUGGESTION. Dr. D can always type another amount,
    for example when cash at a market already included the tax.
    """

    if sales_channel == "Wholesale":

        return money(0)

    if not is_home_state(state):

        return money(0)

    taxable_amount = (
        money(product_revenue)
        + money(shipping_revenue)
    )

    return money(
        taxable_amount
        * NC_FOOD_TAX_RATE
    )


# ============================================================
# MONTH HELPER
# ============================================================

def month_range(year, month):
    """
    First day of the month and first day of the next month.
    """

    start = date(year, month, 1)

    if month == 12:

        end = date(year + 1, 1, 1)

    else:

        end = date(year, month + 1, 1)

    return start, end


# ============================================================
# 2. NC SALES TAX BY COUNTY (MONTH)
# ============================================================

def get_monthly_tax_by_county(year, month):
    """
    Group the month's North Carolina sales by county.

    Every row:
        county            county name ("(county missing)" if empty)
        sales             number of sales
        taxable_amount    product revenue + shipping (retail only)
        tax_collected     tax entered with the sales
        expected_tax      2% of the taxable amount
        difference        collected - expected

    Wholesale sales are not taxable and are returned separately
    in "wholesale_revenue".

    County names are cleaned so that "wake", " Wake " and
    "Wake County" are reported as one county: "Wake".
    """

    start, end = month_range(year, month)

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                WITH nc_sales AS (

                    SELECT
                        COALESCE(
                            NULLIF(
                                REGEXP_REPLACE(
                                    INITCAP(TRIM(county)),
                                    '\\s+County$',
                                    ''
                                ),
                                ''
                            ),
                            '(county missing)'
                        ) AS county_name,

                        sales_channel,
                        total_amount,
                        shipping_revenue,
                        tax_collected

                    FROM sales

                    WHERE sale_date >= %s
                      AND sale_date < %s
                      AND (
                          state IS NULL
                          OR TRIM(state) = ''
                          OR UPPER(TRIM(state)) IN (%s, 'NORTH CAROLINA')
                      )
                )

                SELECT
                    county_name,

                    COUNT(*) FILTER (
                        WHERE sales_channel <> 'Wholesale'
                    ) AS sales,

                    COALESCE(
                        SUM(total_amount + shipping_revenue) FILTER (
                            WHERE sales_channel <> 'Wholesale'
                        ),
                        0
                    ) AS taxable_amount,

                    COALESCE(
                        SUM(tax_collected) FILTER (
                            WHERE sales_channel <> 'Wholesale'
                        ),
                        0
                    ) AS tax_collected,

                    COALESCE(
                        SUM(total_amount) FILTER (
                            WHERE sales_channel = 'Wholesale'
                        ),
                        0
                    ) AS wholesale_revenue

                FROM nc_sales

                GROUP BY
                    county_name

                ORDER BY
                    county_name = '(county missing)',
                    taxable_amount DESC;
                """,
                (
                    start,
                    end,
                    HOME_STATE
                )
            )

            rows = cur.fetchall()

    counties = []

    for row in rows:

        taxable_amount = money(row[2])
        tax_collected = money(row[3])

        expected_tax = money(
            taxable_amount
            * NC_FOOD_TAX_RATE
        )

        counties.append(
            {
                "county": row[0],
                "sales": int(row[1]),
                "taxable_amount": taxable_amount,
                "tax_collected": tax_collected,
                "expected_tax": expected_tax,
                "difference": tax_collected - expected_tax,
                "wholesale_revenue": money(row[4])
            }
        )

    return counties


def get_tax_mismatches(year, month):
    """
    NC retail sales of the month whose tax is not 2% of
    product revenue + shipping (difference of 1 cent or more).

    These are often correct (for example cash that already
    included the tax), but they are the first place to look
    when the monthly totals do not match.
    """

    start, end = month_range(year, month)

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    sale_id,
                    sale_date,
                    sales_channel,
                    payment_method,
                    county,
                    total_amount + shipping_revenue AS taxable_amount,
                    tax_collected,
                    ROUND((total_amount + shipping_revenue) * %s, 2)
                        AS expected_tax

                FROM sales

                WHERE sale_date >= %s
                  AND sale_date < %s
                  AND sales_channel <> 'Wholesale'
                  AND (
                      state IS NULL
                      OR TRIM(state) = ''
                      OR UPPER(TRIM(state)) IN (%s, 'NORTH CAROLINA')
                  )
                  AND ABS(
                      tax_collected
                      - ROUND((total_amount + shipping_revenue) * %s, 2)
                  ) >= 0.01

                ORDER BY
                    sale_date,
                    sale_id;
                """,
                (
                    NC_FOOD_TAX_RATE,
                    start,
                    end,
                    HOME_STATE,
                    NC_FOOD_TAX_RATE
                )
            )

            rows = cur.fetchall()

    return [
        {
            "sale_id": row[0],
            "sale_date": row[1],
            "sales_channel": row[2],
            "payment_method": row[3],
            "county": row[4],
            "taxable_amount": money(row[5]),
            "tax_collected": money(row[6]),
            "expected_tax": money(row[7])
        }
        for row in rows
    ]


def summarize_tax_by_county(counties):
    """
    Totals for the monthly county report.
    """

    def total(key):

        return sum(
            (row[key] for row in counties),
            Decimal("0.00")
        )

    return {
        "counties": len(
            [
                row for row in counties
                if row["sales"] > 0
                and row["county"] != "(county missing)"
            ]
        ),
        "sales": sum(row["sales"] for row in counties),
        "taxable_amount": total("taxable_amount"),
        "tax_collected": total("tax_collected"),
        "expected_tax": total("expected_tax"),
        "difference": total("difference"),
        "wholesale_revenue": total("wholesale_revenue"),
        "missing_county_sales": sum(
            row["sales"] for row in counties
            if row["county"] == "(county missing)"
        )
    }


def create_tax_by_county_report(year, month):
    """
    Excel workbook (bytes) for the CPA:
    one row per county, with a total row.
    """

    counties = get_monthly_tax_by_county(year, month)

    summary = summarize_tax_by_county(counties)

    rows = [
        {
            "County": row["county"],
            "Sales": row["sales"],
            "Taxable Amount": float(row["taxable_amount"]),
            "Tax Collected": float(row["tax_collected"]),
            "Expected Tax (2%)": float(row["expected_tax"]),
            "Difference": float(row["difference"])
        }
        for row in counties
        if row["sales"] > 0
    ]

    rows.append(
        {
            "County": "TOTAL",
            "Sales": summary["sales"],
            "Taxable Amount": float(summary["taxable_amount"]),
            "Tax Collected": float(summary["tax_collected"]),
            "Expected Tax (2%)": float(summary["expected_tax"]),
            "Difference": float(summary["difference"])
        }
    )

    table = pd.DataFrame(rows)

    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        table.to_excel(
            writer,
            sheet_name="NC Tax by County",
            index=False,
            startrow=3
        )

        sheet = writer.sheets["NC Tax by County"]

        sheet["A1"] = (
            f"North Carolina sales tax by county, "
            f"{date(year, month, 1).strftime('%B %Y')}"
        )

        sheet["A2"] = (
            "Retail sales delivered in NC. Taxable amount = product "
            "revenue + shipping. Expected tax = 2% local food rate. "
            "Wholesale sales are excluded."
        )

        sheet["A1"].font = Font(bold=True, size=13)

        widths = {"A": 22, "B": 10, "C": 16, "D": 16, "E": 18, "F": 14}

        for column, width in widths.items():

            sheet.column_dimensions[column].width = width

        for row in sheet.iter_rows(min_row=5, min_col=3, max_col=6):

            for cell in row:

                cell.number_format = "$#,##0.00"

        last_row = sheet.max_row

        for cell in sheet[last_row]:

            cell.font = Font(bold=True)

    return buffer.getvalue()


# ============================================================
# 3. SALES BY STATE (YEAR)
# ============================================================

def get_sales_by_state(year):
    """
    Orders and gross sales per state for one calendar year.

    gross_sales = product revenue + shipping charged.
    States count their thresholds in different ways; this is the
    common measure. Sales tax is not included.
    """

    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    COALESCE(
                        NULLIF(UPPER(TRIM(state)), ''),
                        %s
                    ) AS state_code,

                    COUNT(*) AS orders,

                    SUM(total_amount + shipping_revenue) AS gross_sales

                FROM sales

                WHERE sale_date >= %s
                  AND sale_date < %s

                GROUP BY
                    state_code

                ORDER BY
                    gross_sales DESC;
                """,
                (
                    HOME_STATE,
                    start,
                    end
                )
            )

            rows = cur.fetchall()

    return [
        {
            "state": row[0],
            "orders": int(row[1]),
            "gross_sales": money(row[2])
        }
        for row in rows
    ]


def get_nexus_watch(
    current_year,
    sales_threshold=DEFAULT_NEXUS_SALES,
    orders_threshold=DEFAULT_NEXUS_ORDERS
):
    """
    Compare out-of-state sales with the thresholds.

    Most states look at the current OR the previous calendar
    year, so both years are shown and the higher share counts.

    Status:
        "Over threshold"  100% or more of a threshold
        "Approaching"     75% or more
        "OK"              below 75%

    orders_threshold = 0 means "do not check the number of orders"
    (many states have dropped the 200-order rule).
    """

    sales_threshold = Decimal(str(sales_threshold))
    orders_threshold = int(orders_threshold)

    current = {
        row["state"]: row
        for row in get_sales_by_state(current_year)
    }

    previous = {
        row["state"]: row
        for row in get_sales_by_state(current_year - 1)
    }

    states = sorted(
        (set(current) | set(previous)) - {HOME_STATE}
    )

    watch = []

    for state in states:

        this_year = current.get(
            state,
            {"orders": 0, "gross_sales": Decimal("0.00")}
        )

        last_year = previous.get(
            state,
            {"orders": 0, "gross_sales": Decimal("0.00")}
        )

        shares = []

        for year_row in (this_year, last_year):

            if sales_threshold > 0:

                shares.append(
                    year_row["gross_sales"] / sales_threshold
                )

            if orders_threshold > 0:

                shares.append(
                    Decimal(year_row["orders"])
                    / Decimal(orders_threshold)
                )

        highest_share = max(shares) if shares else Decimal("0")

        if highest_share >= 1:

            status = "Over threshold"

        elif highest_share >= APPROACHING_SHARE:

            status = "Approaching"

        else:

            status = "OK"

        watch.append(
            {
                "state": state,
                "orders_this_year": this_year["orders"],
                "sales_this_year": this_year["gross_sales"],
                "orders_last_year": last_year["orders"],
                "sales_last_year": last_year["gross_sales"],
                "highest_share": highest_share,
                "status": status
            }
        )

    status_order = {"Over threshold": 0, "Approaching": 1, "OK": 2}

    watch.sort(
        key=lambda row: (
            status_order[row["status"]],
            -row["highest_share"]
        )
    )

    return watch
