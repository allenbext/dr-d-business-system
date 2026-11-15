"""
report_service.py

Purpose:
Create presentation-ready Excel reports for Dr. D's
Business Management System.

Reports:

1. Complete Business Report
   - Executive Summary
   - Monthly Performance
   - Sales Detail
   - Scholarship Summary
   - Inventory Summary
   - Batch History
   - Inventory Movements
   - Forecast vs Actual
   - Seasonality

2. Monthly Scholarship Report

3. Inventory Report

Important financial definitions:

Revenue:
    Product revenue only.

Tax:
    Collected tax is NOT business revenue.

Estimated Profit:
    Product Revenue
    + Shipping Revenue
    - Product Cost
    - Scholarship Contribution
    - Shopify / Card Fees
    - Shipping Expense

The profit formula is written only once, in the database view
v_sale_financials. Scholarship numbers come from the view
v_scholarship_lines. Both views are created by:

    sql/10_reporting_views_and_constraints.sql

PostgreSQL remains the system of record.
Excel workbooks are reporting copies only.
"""

from datetime import date
from io import BytesIO

import pandas as pd

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side
)
from openpyxl.utils import get_column_letter

from db import get_connection

# One shared list of friendly names for inventory movement types.
from inventory_service import TRANSACTION_LABELS

# Scholarship rate is read from the products table.
from scholarship_service import get_scholarship_rate


# ============================================================
# DESIGN CONSTANTS
# ============================================================

NC_STATE_RED = "CC0000"

DARK_RED = "990000"

DARK_TEXT = "101828"

SECONDARY_TEXT = "667085"

LIGHT_BACKGROUND = "F7F7F7"

LIGHT_RED = "FEE4E2"

BORDER_COLOR = "D0D5DD"

WHITE = "FFFFFF"

POSITIVE_GREEN = "067647"

LIGHT_GREEN = "ECFDF3"


# ============================================================
# DATABASE QUERY HELPER
# ============================================================

def query_to_dataframe(
    query,
    parameters=None
):
    """
    Execute a PostgreSQL query and return a pandas DataFrame.
    """

    if parameters is None:

        parameters = ()


    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                query,
                parameters
            )


            rows = (
                cur.fetchall()
            )


            column_names = [
                column.name
                for column in cur.description
            ]


    return pd.DataFrame(
        rows,
        columns=column_names
    )


# ============================================================
# STANDARD BORDER
# ============================================================

def get_thin_border():
    """
    Return the standard light Excel border used in reports.
    """

    side = Side(
        style="thin",
        color=BORDER_COLOR
    )


    return Border(
        left=side,
        right=side,
        top=side,
        bottom=side
    )


# ============================================================
# GENERAL SHEET FORMATTING
# ============================================================

def format_standard_table(
    worksheet,
    header_row=1,
    currency_headers=None,
    percent_headers=None
):
    """
    Apply standard formatting to a worksheet containing
    a normal tabular report.
    """

    if currency_headers is None:

        currency_headers = []


    if percent_headers is None:

        percent_headers = []


    if worksheet.max_column == 0:

        return


    border = (
        get_thin_border()
    )


    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    for cell in worksheet[
        header_row
    ]:

        cell.fill = PatternFill(
            fill_type="solid",
            fgColor=NC_STATE_RED
        )


        cell.font = Font(
            bold=True,
            color=WHITE
        )


        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


        cell.border = (
            border
        )


    # --------------------------------------------------------
    # FIND HEADERS
    # --------------------------------------------------------

    header_lookup = {}


    for cell in worksheet[
        header_row
    ]:

        header_lookup[
            cell.value
        ] = cell.column


    # --------------------------------------------------------
    # CURRENCY
    # --------------------------------------------------------

    for header_name in currency_headers:

        if header_name not in header_lookup:

            continue


        column_number = (
            header_lookup[
                header_name
            ]
        )


        for row_number in range(
            header_row + 1,
            worksheet.max_row + 1
        ):

            worksheet.cell(
                row=row_number,
                column=column_number
            ).number_format = (
                "$#,##0.00"
            )


    # --------------------------------------------------------
    # PERCENTAGE
    # --------------------------------------------------------

    for header_name in percent_headers:

        if header_name not in header_lookup:

            continue


        column_number = (
            header_lookup[
                header_name
            ]
        )


        for row_number in range(
            header_row + 1,
            worksheet.max_row + 1
        ):

            worksheet.cell(
                row=row_number,
                column=column_number
            ).number_format = (
                "0.00%"
            )


    # --------------------------------------------------------
    # BODY BORDERS
    # --------------------------------------------------------

    for row in worksheet.iter_rows(
        min_row=header_row + 1
    ):

        for cell in row:

            cell.border = (
                border
            )


            cell.alignment = Alignment(
                vertical="top"
            )


    # --------------------------------------------------------
    # COLUMN WIDTHS
    # --------------------------------------------------------

    for column_cells in worksheet.columns:

        max_length = 0


        column_letter = (
            get_column_letter(
                column_cells[0].column
            )
        )


        for cell in column_cells:

            value = (
                ""
                if cell.value is None
                else str(
                    cell.value
                )
            )


            max_length = max(
                max_length,
                len(value)
            )


        worksheet.column_dimensions[
            column_letter
        ].width = max(
            11,
            min(
                max_length + 2,
                35
            )
        )


    worksheet.freeze_panes = (
        f"A{header_row + 1}"
    )


    if worksheet.max_row >= header_row:

        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )


# ============================================================
# SALES DETAIL DATA
# ============================================================

def get_sales_detail_report():
    """
    Return one row per product line in each sale.
    """

    query = """
        SELECT
            s.sale_id,
            s.sale_date,
            s.sales_channel,
            s.payment_method,

            p.product_name,

            si.quantity,
            si.allocated_revenue,
            si.scholarship_amount,

            p.unit_cost,

            (
                p.unit_cost
                * si.quantity
            ) AS product_cost,

            s.total_amount
                AS sale_product_revenue,

            s.tax_collected,
            s.shipping_revenue,
            s.shopify_fee,
            s.shipping_expense,

            s.state,
            s.county

        FROM sales AS s

        JOIN sale_items AS si
            ON s.sale_id = si.sale_id

        JOIN products AS p
            ON si.product_id = p.product_id

        ORDER BY
            s.sale_date DESC,
            s.sale_id DESC,
            p.product_id;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# MONTHLY PERFORMANCE DATA
# ============================================================

def get_monthly_performance_report():
    """
    Return business performance grouped by month.

    All values come from the view v_sale_financials, where
    product cost, scholarship and estimated profit are already
    calculated for every sale.

    Estimated profit uses tracked operating costs only.
    """

    query = """
        SELECT
            DATE_TRUNC('month', sale_date)::date AS month,

            COUNT(*) AS sales_count,

            SUM(jars_sold) AS jars_sold,

            SUM(product_revenue) AS product_revenue,

            SUM(shipping_revenue) AS shipping_revenue,

            SUM(tax_collected) AS tax_collected,

            SUM(product_cost) AS product_cost,

            SUM(scholarship) AS scholarship,

            SUM(shopify_fee) AS payment_fees,

            SUM(shipping_expense) AS shipping_expense,

            SUM(estimated_profit) AS estimated_profit

        FROM v_sale_financials

        GROUP BY
            DATE_TRUNC('month', sale_date)::date

        ORDER BY
            month;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# SCHOLARSHIP SUMMARY DATA
# ============================================================

def get_scholarship_report():
    """
    Return monthly scholarship totals.

    The view v_scholarship_lines contains every sold line of a
    product whose scholarship rate is greater than zero
    (today: Slobberin' Sauce).
    """

    query = """
        SELECT
            DATE_TRUNC('month', sale_date)::date AS month,

            SUM(quantity) AS slobberin_jars,

            SUM(allocated_revenue) AS eligible_revenue,

            SUM(scholarship_amount) AS scholarship_owed

        FROM v_scholarship_lines

        GROUP BY
            DATE_TRUNC('month', sale_date)::date

        ORDER BY
            month;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# INVENTORY SUMMARY DATA
# ============================================================

def get_inventory_report():
    """
    Return current inventory with estimated inventory value.
    """

    query = """
        SELECT
            p.product_id,
            p.product_name,
            p.unit_cost,
            p.scholarship_rate,

            i.current_quantity,

            (
                p.unit_cost
                * i.current_quantity
            ) AS estimated_inventory_value

        FROM inventory AS i

        JOIN products AS p
            ON i.product_id = p.product_id

        ORDER BY
            p.product_id;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# BATCH HISTORY DATA
# ============================================================

def get_batch_report():
    """
    Return manufacturer batch history.
    """

    query = """
        SELECT
            b.batch_id,
            b.batch_code,
            b.received_date,

            p.product_name,

            b.quantity_received,
            b.manufacturer,
            b.notes

        FROM inventory_batches AS b

        JOIN products AS p
            ON b.product_id = p.product_id

        ORDER BY
            b.received_date DESC,
            b.batch_id DESC;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# INVENTORY MOVEMENTS DATA
# ============================================================

def get_inventory_movement_report():
    """
    Return inventory audit trail.
    """

    query = """
        SELECT
            it.transaction_id,
            it.transaction_date,

            p.product_name,

            it.transaction_type,
            it.quantity_change,

            b.batch_code,

            it.sale_id,

            it.notes

        FROM inventory_transactions AS it

        JOIN products AS p
            ON it.product_id = p.product_id

        LEFT JOIN inventory_batches AS b
            ON it.batch_id = b.batch_id

        ORDER BY
            it.transaction_date DESC,
            it.transaction_id DESC;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# FORECAST DATA
# ============================================================

def get_forecast_report():
    """
    Return saved forecasts.
    """

    query = """
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


    return query_to_dataframe(
        query
    )


# ============================================================
# SEASONALITY DATA
# ============================================================

def get_seasonality_report():
    """
    Return seasonal assumptions.
    """

    query = """
        SELECT
            month_number,
            month_name,
            demand_tier,
            seasonal_factor,
            notes

        FROM forecast_seasonality

        ORDER BY
            month_number;
    """


    return query_to_dataframe(
        query
    )


# ============================================================
# EXECUTIVE KPI DATA
# ============================================================

def get_executive_summary_data():
    """
    Calculate summary KPIs used on the first worksheet.

    Periods:

        This Month    first day of the month through today
        Year to Date  January 1 through today
        All Time      everything through today

    FILTER (WHERE ...) makes an aggregate include only the
    rows that match the condition.
    """

    today = (
        date.today()
    )

    month_start = today.replace(
        day=1
    )

    year_start = today.replace(
        month=1,
        day=1
    )


    # --------------------------------------------------------
    # REVENUE AND PROFIT
    # --------------------------------------------------------

    query = """
        SELECT
            COALESCE(
                SUM(product_revenue)
                    FILTER (WHERE sale_date >= %(month_start)s),
                0
            ) AS month_revenue,

            COALESCE(
                SUM(estimated_profit)
                    FILTER (WHERE sale_date >= %(month_start)s),
                0
            ) AS month_profit,

            COALESCE(
                SUM(product_revenue)
                    FILTER (WHERE sale_date >= %(year_start)s),
                0
            ) AS ytd_revenue,

            COALESCE(
                SUM(estimated_profit)
                    FILTER (WHERE sale_date >= %(year_start)s),
                0
            ) AS ytd_profit,

            COALESCE(
                SUM(product_revenue),
                0
            ) AS all_time_revenue,

            COALESCE(
                SUM(estimated_profit),
                0
            ) AS all_time_profit

        FROM v_sale_financials

        WHERE sale_date <= %(today)s;
    """


    financial_df = (
        query_to_dataframe(
            query,
            {
                "month_start": month_start,
                "year_start": year_start,
                "today": today
            }
        )
    )


    # --------------------------------------------------------
    # MONTH SCHOLARSHIP
    #
    # Whole calendar month of today.
    # --------------------------------------------------------

    scholarship_query = """
        SELECT
            COALESCE(
                SUM(scholarship_amount),
                0
            ) AS scholarship_owed

        FROM v_scholarship_lines

        WHERE DATE_TRUNC('month', sale_date)
              = DATE_TRUNC('month', %(today)s::date);
    """


    scholarship_df = (
        query_to_dataframe(
            scholarship_query,
            {
                "today": today
            }
        )
    )


    # --------------------------------------------------------
    # CURRENT INVENTORY
    # --------------------------------------------------------

    inventory_df = (
        get_inventory_report()
    )


    row = (
        financial_df.iloc[0]
    )


    return {
        "month_revenue":
            float(row["month_revenue"]),

        "month_profit":
            float(row["month_profit"]),

        "ytd_revenue":
            float(row["ytd_revenue"]),

        "ytd_profit":
            float(row["ytd_profit"]),

        "all_time_revenue":
            float(row["all_time_revenue"]),

        "all_time_profit":
            float(row["all_time_profit"]),

        "scholarship_owed":
            float(
                scholarship_df.iloc[0]["scholarship_owed"]
            ),

        "total_inventory":
            int(
                inventory_df["current_quantity"].sum()
            ),

        "inventory_value":
            float(
                inventory_df["estimated_inventory_value"].sum()
            )
    }


# ============================================================
# EXECUTIVE SUMMARY SHEET
# ============================================================

def create_executive_summary_sheet(
    workbook,
    monthly_df,
    inventory_df,
    executive
):
    """
    Create the polished Executive Summary worksheet.

    Layout:

        Top:
            Revenue This Month
            Estimated Profit This Month
            Scholarship Contribution Due

        Second row:
            Revenue YTD
            Profit YTD
            All-Time Revenue
            All-Time Profit
            Current Inventory
            Inventory Value

        Middle:
            Current Inventory table
            Revenue / Profit chart

        Bottom:
            Monthly Performance table
            Scholarship trend chart
    """

    sheet = workbook.create_sheet(
        "Executive Summary",
        0
    )


    # ========================================================
    # WORKSHEET VIEW
    # ========================================================

    sheet.sheet_view.showGridLines = False

    sheet.sheet_view.zoomScale = 90


    sheet.page_setup.orientation = (
        "landscape"
    )

    sheet.page_setup.fitToWidth = 1

    sheet.page_setup.fitToHeight = 1

    sheet.sheet_properties.pageSetUpPr.fitToPage = (
        True
    )


    # ========================================================
    # COLUMN WIDTHS
    #
    # Important:
    # No narrow spacer column is used anymore.
    # Every column can safely contain report data.
    # ========================================================

    column_widths = {
        "A": 18,
        "B": 16,
        "C": 16,
        "D": 18,
        "E": 4,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
        "J": 14,
        "K": 14,
        "L": 14
    }


    for column, width in column_widths.items():

        sheet.column_dimensions[
            column
        ].width = width


    # ========================================================
    # COMMON STYLES
    # ========================================================

    border = get_thin_border()


    red_fill = PatternFill(
        fill_type="solid",
        fgColor=NC_STATE_RED
    )


    light_fill = PatternFill(
        fill_type="solid",
        fgColor=LIGHT_BACKGROUND
    )


    light_red_fill = PatternFill(
        fill_type="solid",
        fgColor=LIGHT_RED
    )


    # ========================================================
    # TITLE
    # ========================================================

    sheet.merge_cells(
        "A1:L1"
    )


    sheet["A1"] = (
        "DR. D'S BUSINESS PERFORMANCE REPORT"
    )


    sheet["A1"].font = Font(
        size=20,
        bold=True,
        color=NC_STATE_RED
    )


    sheet["A1"].alignment = Alignment(
        horizontal="center",
        vertical="center"
    )


    sheet.row_dimensions[1].height = 30


    sheet.merge_cells(
        "A2:L2"
    )


    sheet["A2"] = (
        "Executive Summary · "
        f"Generated {date.today().strftime('%B %d, %Y')}"
    )


    sheet["A2"].font = Font(
        size=10,
        color=SECONDARY_TEXT
    )


    sheet["A2"].alignment = Alignment(
        horizontal="center"
    )


    # ========================================================
    # PRIMARY KPI CARDS
    # ========================================================

    primary_cards = [
        {
            "label_range": "A4:D4",
            "value_range": "A5:D7",
            "label": "REVENUE — THIS MONTH",
            "value": executive[
                "month_revenue"
            ]
        },

        {
            "label_range": "E4:H4",
            "value_range": "E5:H7",
            "label": "ESTIMATED PROFIT — THIS MONTH",
            "value": executive[
                "month_profit"
            ]
        },

        {
            "label_range": "I4:L4",
            "value_range": "I5:L7",
            "label": "SCHOLARSHIP CONTRIBUTION DUE",
            "value": executive[
                "scholarship_owed"
            ]
        }
    ]


    for card in primary_cards:

        sheet.merge_cells(
            card[
                "label_range"
            ]
        )


        sheet.merge_cells(
            card[
                "value_range"
            ]
        )


        label_cell = sheet[
            card[
                "label_range"
            ].split(":")[0]
        ]


        value_cell = sheet[
            card[
                "value_range"
            ].split(":")[0]
        ]


        label_cell.value = (
            card[
                "label"
            ]
        )


        label_cell.fill = (
            red_fill
        )


        label_cell.font = Font(
            bold=True,
            color=WHITE
        )


        label_cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


        value_cell.value = (
            float(
                card[
                    "value"
                ]
            )
        )


        value_cell.number_format = (
            "$#,##0.00"
        )


        value_cell.fill = (
            light_red_fill
        )


        value_cell.font = Font(
            size=20,
            bold=True,
            color=DARK_TEXT
        )


        value_cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


    sheet.row_dimensions[4].height = 22

    sheet.row_dimensions[5].height = 26

    sheet.row_dimensions[6].height = 26

    sheet.row_dimensions[7].height = 26


    # ========================================================
    # SECONDARY KPI SECTION
    # ========================================================

    sheet.merge_cells(
        "A9:L9"
    )


    sheet["A9"] = (
        "BUSINESS PERFORMANCE"
    )


    sheet["A9"].font = Font(
        bold=True,
        color=NC_STATE_RED
    )


    sheet["A9"].alignment = Alignment(
        horizontal="left"
    )


    # Two columns per KPI.
    secondary_kpis = [
        {
            "start_col": 1,
            "label": "Revenue — Year to Date",
            "value": executive[
                "ytd_revenue"
            ],
            "format": "$#,##0.00"
        },

        {
            "start_col": 3,
            "label": "Profit — Year to Date",
            "value": executive[
                "ytd_profit"
            ],
            "format": "$#,##0.00"
        },

        {
            "start_col": 5,
            "label": "All-Time Revenue",
            "value": executive[
                "all_time_revenue"
            ],
            "format": "$#,##0.00"
        },

        {
            "start_col": 7,
            "label": "All-Time Profit",
            "value": executive[
                "all_time_profit"
            ],
            "format": "$#,##0.00"
        },

        {
            "start_col": 9,
            "label": "Current Inventory",
            "value": executive[
                "total_inventory"
            ],
            "format": '#,##0 "jars"'
        },

        {
            "start_col": 11,
            "label": "Inventory Value",
            "value": executive[
                "inventory_value"
            ],
            "format": "$#,##0.00"
        }
    ]


    for kpi in secondary_kpis:

        start_col = (
            kpi[
                "start_col"
            ]
        )


        end_col = (
            start_col + 1
        )


        sheet.merge_cells(
            start_row=10,
            start_column=start_col,
            end_row=10,
            end_column=end_col
        )


        sheet.merge_cells(
            start_row=11,
            start_column=start_col,
            end_row=12,
            end_column=end_col
        )


        label_cell = sheet.cell(
            row=10,
            column=start_col
        )


        value_cell = sheet.cell(
            row=11,
            column=start_col
        )


        label_cell.value = (
            kpi[
                "label"
            ]
        )


        label_cell.fill = (
            light_fill
        )


        label_cell.font = Font(
            bold=True,
            color=SECONDARY_TEXT
        )


        label_cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


        value_cell.value = (
            kpi[
                "value"
            ]
        )


        value_cell.number_format = (
            kpi[
                "format"
            ]
        )


        value_cell.font = Font(
            size=13,
            bold=True,
            color=DARK_TEXT
        )


        value_cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


    sheet.row_dimensions[10].height = 22

    sheet.row_dimensions[11].height = 22

    sheet.row_dimensions[12].height = 22


    # ========================================================
    # CURRENT INVENTORY
    # ========================================================

    sheet.merge_cells(
        "A15:D15"
    )


    sheet["A15"] = (
        "CURRENT INVENTORY"
    )


    sheet["A15"].font = Font(
        bold=True,
        color=NC_STATE_RED
    )


    inventory_headers = [
        "Product",
        "Current Jars",
        "Unit Cost",
        "Estimated Value"
    ]


    for column_number, header in enumerate(
        inventory_headers,
        start=1
    ):

        cell = sheet.cell(
            row=16,
            column=column_number,
            value=header
        )


        cell.fill = (
            red_fill
        )


        cell.font = Font(
            bold=True,
            color=WHITE
        )


        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


        cell.border = (
            border
        )


    inventory_row = 17


    for _, row in inventory_df.iterrows():

        sheet.cell(
            row=inventory_row,
            column=1,
            value=row[
                "product_name"
            ]
        )


        sheet.cell(
            row=inventory_row,
            column=2,
            value=int(
                row[
                    "current_quantity"
                ]
            )
        )


        sheet.cell(
            row=inventory_row,
            column=3,
            value=float(
                row[
                    "unit_cost"
                ]
            )
        ).number_format = (
            "$#,##0.00"
        )


        sheet.cell(
            row=inventory_row,
            column=4,
            value=float(
                row[
                    "estimated_inventory_value"
                ]
            )
        ).number_format = (
            "$#,##0.00"
        )


        for column_number in range(
            1,
            5
        ):

            sheet.cell(
                row=inventory_row,
                column=column_number
            ).border = (
                border
            )


        inventory_row += 1


    # --------------------------------------------------------
    # Inventory total row
    # --------------------------------------------------------

    sheet.cell(
        row=inventory_row,
        column=1,
        value="TOTAL"
    )


    sheet.cell(
        row=inventory_row,
        column=2,
        value=int(
            executive[
                "total_inventory"
            ]
        )
    )


    sheet.cell(
        row=inventory_row,
        column=4,
        value=float(
            executive[
                "inventory_value"
            ]
        )
    ).number_format = (
        "$#,##0.00"
    )


    for column_number in range(
        1,
        5
    ):

        cell = sheet.cell(
            row=inventory_row,
            column=column_number
        )


        cell.fill = (
            light_fill
        )


        cell.font = Font(
            bold=True
        )


        cell.border = (
            border
        )


    # ========================================================
    # MONTHLY PERFORMANCE
    # ========================================================

    monthly_title_row = (
        inventory_row + 3
    )


    sheet.merge_cells(
        start_row=monthly_title_row,
        start_column=1,
        end_row=monthly_title_row,
        end_column=4
    )


    sheet.cell(
        row=monthly_title_row,
        column=1,
        value="MONTHLY PERFORMANCE"
    )


    sheet.cell(
        row=monthly_title_row,
        column=1
    ).font = Font(
        bold=True,
        color=NC_STATE_RED
    )


    monthly_header_row = (
        monthly_title_row
        + 1
    )


    monthly_headers = [
        "Month",
        "Revenue",
        "Estimated Profit",
        "Scholarship"
    ]


    for column_number, header in enumerate(
        monthly_headers,
        start=1
    ):

        cell = sheet.cell(
            row=monthly_header_row,
            column=column_number,
            value=header
        )


        cell.fill = (
            red_fill
        )


        cell.font = Font(
            bold=True,
            color=WHITE
        )


        cell.alignment = Alignment(
            horizontal="center"
        )


        cell.border = (
            border
        )


    monthly_start_row = (
        monthly_header_row
        + 1
    )


    for row_offset, (
        _,
        row
    ) in enumerate(
        monthly_df.iterrows()
    ):

        current_row = (
            monthly_start_row
            + row_offset
        )


        sheet.cell(
            row=current_row,
            column=1,
            value=row[
                "month"
            ]
        ).number_format = (
            "mmm yyyy"
        )


        sheet.cell(
            row=current_row,
            column=2,
            value=float(
                row[
                    "product_revenue"
                ]
            )
        ).number_format = (
            "$#,##0.00"
        )


        sheet.cell(
            row=current_row,
            column=3,
            value=float(
                row[
                    "estimated_profit"
                ]
            )
        ).number_format = (
            "$#,##0.00"
        )


        sheet.cell(
            row=current_row,
            column=4,
            value=float(
                row[
                    "scholarship"
                ]
            )
        ).number_format = (
            "$#,##0.00"
        )


        for column_number in range(
            1,
            5
        ):

            sheet.cell(
                row=current_row,
                column=column_number
            ).border = (
                border
            )


    # ========================================================
    # MONTHLY TOTAL
    # ========================================================

    monthly_total_row = (
        monthly_start_row
        + len(
            monthly_df
        )
    )


    sheet.cell(
        row=monthly_total_row,
        column=1,
        value="TOTAL"
    )


    sheet.cell(
        row=monthly_total_row,
        column=2,
        value=float(
            monthly_df[
                "product_revenue"
            ].sum()
        )
    ).number_format = (
        "$#,##0.00"
    )


    sheet.cell(
        row=monthly_total_row,
        column=3,
        value=float(
            monthly_df[
                "estimated_profit"
            ].sum()
        )
    ).number_format = (
        "$#,##0.00"
    )


    sheet.cell(
        row=monthly_total_row,
        column=4,
        value=float(
            monthly_df[
                "scholarship"
            ].sum()
        )
    ).number_format = (
        "$#,##0.00"
    )


    for column_number in range(
        1,
        5
    ):

        cell = sheet.cell(
            row=monthly_total_row,
            column=column_number
        )


        cell.fill = (
            light_fill
        )


        cell.font = Font(
            bold=True
        )


        cell.border = (
            border
        )


    # ========================================================
    # CHART 1
    # MONTHLY REVENUE + PROFIT
    # ========================================================

    if len(
        monthly_df
    ) > 0:

        last_data_row = (
            monthly_start_row
            + len(
                monthly_df
            )
            - 1
        )


        revenue_chart = (
            BarChart()
        )


        revenue_chart.type = (
            "col"
        )


        revenue_chart.style = (
            10
        )


        revenue_chart.title = (
            "Monthly Revenue and Estimated Profit"
        )


        revenue_chart.y_axis.title = (
            "Dollars"
        )


        revenue_chart.x_axis.title = (
            "Month"
        )


        revenue_data = Reference(
            sheet,
            min_col=2,
            max_col=3,
            min_row=monthly_header_row,
            max_row=last_data_row
        )


        revenue_categories = Reference(
            sheet,
            min_col=1,
            min_row=monthly_start_row,
            max_row=last_data_row
        )


        revenue_chart.add_data(
            revenue_data,
            titles_from_data=True
        )


        revenue_chart.set_categories(
            revenue_categories
        )


        # More compact than the previous version.
        revenue_chart.height = (
            6.8
        )


        revenue_chart.width = (
            12.5
        )


        sheet.add_chart(
            revenue_chart,
            "F15"
        )


        # ====================================================
        # CHART 2
        # SCHOLARSHIP
        # ====================================================

        scholarship_chart = (
            LineChart()
        )


        scholarship_chart.style = (
            13
        )


        scholarship_chart.title = (
            "Monthly Scholarship Contribution"
        )


        scholarship_chart.y_axis.title = (
            "Dollars"
        )


        scholarship_chart.x_axis.title = (
            "Month"
        )


        scholarship_data = Reference(
            sheet,
            min_col=4,
            min_row=monthly_header_row,
            max_row=last_data_row
        )


        scholarship_chart.add_data(
            scholarship_data,
            titles_from_data=True
        )


        scholarship_chart.set_categories(
            revenue_categories
        )


        scholarship_chart.height = (
            6.5
        )


        scholarship_chart.width = (
            12.5
        )


        sheet.add_chart(
            scholarship_chart,
            "F30"
        )


    # ========================================================
    # FINANCIAL DEFINITION NOTE
    # ========================================================

    note_row = max(
        44,
        monthly_total_row + 3
    )


    sheet.merge_cells(
        start_row=note_row,
        start_column=1,
        end_row=note_row,
        end_column=12
    )


    note_cell = sheet.cell(
        row=note_row,
        column=1
    )


    note_cell.value = (
        "Estimated Profit = Product Revenue "
        "+ Shipping Revenue "
        "− Product Cost "
        "− Scholarship Contribution "
        "− Payment Fees "
        "− Shipping Expense. "
        "Sales tax collected is excluded from revenue."
    )


    note_cell.font = Font(
        size=9,
        italic=True,
        color=SECONDARY_TEXT
    )


    note_cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
        wrap_text=True
    )


    sheet.row_dimensions[
        note_row
    ].height = 30


    return sheet


# ============================================================
# COMPLETE BUSINESS REPORT
# ============================================================

def create_excel_report():
    """
    Create the complete Business Report workbook.

    The first worksheet is a polished Executive Summary.

    Detailed transaction sheets are retained so the workbook
    remains auditable and useful for analysis.
    """

    # ========================================================
    # LOAD DATA
    # ========================================================

    executive = (
        get_executive_summary_data()
    )


    monthly_df = (
        get_monthly_performance_report()
    )


    sales_df = (
        get_sales_detail_report()
    )


    scholarship_df = (
        get_scholarship_report()
    )


    inventory_df = (
        get_inventory_report()
    )


    batches_df = (
        get_batch_report()
    )


    movements_df = (
        get_inventory_movement_report()
    )


    forecasts_df = (
        get_forecast_report()
    )


    seasonality_df = (
        get_seasonality_report()
    )


    # ========================================================
    # FRIENDLY COLUMN NAMES
    # ========================================================

    monthly_export = (
        monthly_df.rename(
            columns={
                "month":
                    "Month",

                "sales_count":
                    "Sales Count",

                "jars_sold":
                    "Jars Sold",

                "product_revenue":
                    "Product Revenue",

                "shipping_revenue":
                    "Shipping Revenue",

                "tax_collected":
                    "Tax Collected",

                "product_cost":
                    "Product Cost",

                "scholarship":
                    "Scholarship",

                "payment_fees":
                    "Payment Fees",

                "shipping_expense":
                    "Shipping Expense",

                "estimated_profit":
                    "Estimated Profit"
            }
        )
    )


    sales_export = (
        sales_df.rename(
            columns={
                "sale_id":
                    "Sale ID",

                "sale_date":
                    "Date",

                "sales_channel":
                    "Channel",

                "payment_method":
                    "Payment",

                "product_name":
                    "Product",

                "quantity":
                    "Quantity",

                "allocated_revenue":
                    "Allocated Revenue",

                "scholarship_amount":
                    "Scholarship",

                "unit_cost":
                    "Unit Cost",

                "product_cost":
                    "Product Cost",

                "sale_product_revenue":
                    "Sale Product Revenue",

                "tax_collected":
                    "Tax Collected",

                "shipping_revenue":
                    "Shipping Revenue",

                "shopify_fee":
                    "Payment Fee",

                "shipping_expense":
                    "Shipping Expense",

                "state":
                    "State",

                "county":
                    "County"
            }
        )
    )


    scholarship_export = (
        scholarship_df.rename(
            columns={
                "month":
                    "Month",

                "slobberin_jars":
                    "Slobberin' Jars",

                "eligible_revenue":
                    "Eligible Revenue",

                "scholarship_owed":
                    "Scholarship Owed"
            }
        )
    )


    inventory_export = (
        inventory_df.rename(
            columns={
                "product_id":
                    "Product ID",

                "product_name":
                    "Product",

                "unit_cost":
                    "Unit Cost",

                "scholarship_rate":
                    "Scholarship Rate",

                "current_quantity":
                    "Current Jars",

                "estimated_inventory_value":
                    "Estimated Value"
            }
        )
    )


    batch_export = (
        batches_df.rename(
            columns={
                "batch_id":
                    "Batch ID",

                "batch_code":
                    "Batch Code",

                "received_date":
                    "Received",

                "product_name":
                    "Product",

                "quantity_received":
                    "Qty Received",

                "manufacturer":
                    "Manufacturer",

                "notes":
                    "Notes"
            }
        )
    )


    # Friendly names come from ONE shared list in
    # inventory_service.py (includes "Voided Sale").
    movement_labels = (
        TRANSACTION_LABELS
    )


    movement_export = (
        movements_df.copy()
    )


    if not movement_export.empty:

        movement_export[
            "transaction_type"
        ] = (
            movement_export[
                "transaction_type"
            ]
            .map(
                movement_labels
            )
            .fillna(
                movement_export[
                    "transaction_type"
                ]
            )
        )


    movement_export = (
        movement_export.rename(
            columns={
                "transaction_id":
                    "Movement ID",

                "transaction_date":
                    "Date",

                "product_name":
                    "Product",

                "transaction_type":
                    "Type",

                "quantity_change":
                    "Qty Change",

                "batch_code":
                    "Batch",

                "sale_id":
                    "Sale ID",

                "notes":
                    "Notes"
            }
        )
    )


    forecast_export = (
        forecasts_df.rename(
            columns={
                "forecast_id":
                    "Forecast ID",

                "forecast_week":
                    "Week",

                "product_name":
                    "Product",

                "sales_region":
                    "Region",

                "sales_channel":
                    "Channel",

                "baseline_forecast_quantity":
                    "Baseline Forecast",

                "demand_tier":
                    "Demand Tier",

                "seasonal_factor":
                    "Seasonal Factor",

                "saved_forecast_quantity":
                    "Forecast",

                "actual_quantity":
                    "Actual",

                "forecast_error":
                    "Difference",

                "smoothing_factor":
                    "Smoothing Factor"
            }
        )
    )


    seasonality_export = (
        seasonality_df.rename(
            columns={
                "month_number":
                    "Month #",

                "month_name":
                    "Month",

                "demand_tier":
                    "Demand Tier",

                "seasonal_factor":
                    "Seasonal Factor",

                "notes":
                    "Notes"
            }
        )
    )


    # ========================================================
    # CREATE WORKBOOK
    # ========================================================

    output = (
        BytesIO()
    )


    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        # ----------------------------------------------------
        # Supporting sheets first.
        #
        # Executive Summary will then be inserted as sheet 1.
        # ----------------------------------------------------

        monthly_export.to_excel(
            writer,
            sheet_name=(
                "Monthly Performance"
            ),
            index=False
        )


        sales_export.to_excel(
            writer,
            sheet_name=(
                "Sales Detail"
            ),
            index=False
        )


        scholarship_export.to_excel(
            writer,
            sheet_name=(
                "Scholarship Summary"
            ),
            index=False
        )


        inventory_export.to_excel(
            writer,
            sheet_name=(
                "Inventory Summary"
            ),
            index=False
        )


        batch_export.to_excel(
            writer,
            sheet_name=(
                "Batch History"
            ),
            index=False
        )


        movement_export.to_excel(
            writer,
            sheet_name=(
                "Inventory Movements"
            ),
            index=False
        )


        forecast_export.to_excel(
            writer,
            sheet_name=(
                "Forecast vs Actual"
            ),
            index=False
        )


        seasonality_export.to_excel(
            writer,
            sheet_name=(
                "Seasonality"
            ),
            index=False
        )


        workbook = (
            writer.book
        )


        # ====================================================
        # EXECUTIVE SUMMARY
        # ====================================================

        create_executive_summary_sheet(
            workbook=workbook,
            monthly_df=monthly_df,
            inventory_df=inventory_df,
            executive=executive
        )


        # ====================================================
        # FORMAT MONTHLY PERFORMANCE
        # ====================================================

        monthly_sheet = (
            workbook[
                "Monthly Performance"
            ]
        )


        format_standard_table(
            monthly_sheet,
            currency_headers=[
                "Product Revenue",
                "Shipping Revenue",
                "Tax Collected",
                "Product Cost",
                "Scholarship",
                "Payment Fees",
                "Shipping Expense",
                "Estimated Profit"
            ]
        )


        monthly_sheet[
            "A:A"
        ][0].number_format = (
            "mmm yyyy"
        )


        for row_number in range(
            2,
            monthly_sheet.max_row + 1
        ):

            monthly_sheet.cell(
                row=row_number,
                column=1
            ).number_format = (
                "mmm yyyy"
            )


        # ====================================================
        # FORMAT SALES DETAIL
        # ====================================================

        sales_sheet = (
            workbook[
                "Sales Detail"
            ]
        )


        format_standard_table(
            sales_sheet,
            currency_headers=[
                "Allocated Revenue",
                "Scholarship",
                "Unit Cost",
                "Product Cost",
                "Sale Product Revenue",
                "Tax Collected",
                "Shipping Revenue",
                "Payment Fee",
                "Shipping Expense"
            ]
        )


        # ====================================================
        # FORMAT SCHOLARSHIP SUMMARY
        # ====================================================

        scholarship_sheet = (
            workbook[
                "Scholarship Summary"
            ]
        )


        format_standard_table(
            scholarship_sheet,
            currency_headers=[
                "Eligible Revenue",
                "Scholarship Owed"
            ]
        )


        for row_number in range(
            2,
            scholarship_sheet.max_row + 1
        ):

            scholarship_sheet.cell(
                row=row_number,
                column=1
            ).number_format = (
                "mmm yyyy"
            )


        # ====================================================
        # FORMAT INVENTORY SUMMARY
        # ====================================================

        inventory_sheet = (
            workbook[
                "Inventory Summary"
            ]
        )


        format_standard_table(
            inventory_sheet,
            currency_headers=[
                "Unit Cost",
                "Estimated Value"
            ],
            percent_headers=[
                "Scholarship Rate"
            ]
        )


        # ====================================================
        # FORMAT BATCH HISTORY
        # ====================================================

        batch_sheet = (
            workbook[
                "Batch History"
            ]
        )


        format_standard_table(
            batch_sheet
        )


        # ====================================================
        # FORMAT INVENTORY MOVEMENTS
        # ====================================================

        movement_sheet = (
            workbook[
                "Inventory Movements"
            ]
        )


        format_standard_table(
            movement_sheet
        )


        # ====================================================
        # FORMAT FORECAST
        # ====================================================

        forecast_sheet = (
            workbook[
                "Forecast vs Actual"
            ]
        )


        format_standard_table(
            forecast_sheet
        )


        # ====================================================
        # FORMAT SEASONALITY
        # ====================================================

        seasonality_sheet = (
            workbook[
                "Seasonality"
            ]
        )


        format_standard_table(
            seasonality_sheet
        )


        # ====================================================
        # TAB COLORS
        # ====================================================

        workbook[
            "Executive Summary"
        ].sheet_properties.tabColor = (
            NC_STATE_RED
        )


        workbook[
            "Monthly Performance"
        ].sheet_properties.tabColor = (
            NC_STATE_RED
        )


        workbook[
            "Scholarship Summary"
        ].sheet_properties.tabColor = (
            DARK_RED
        )


        workbook[
            "Inventory Summary"
        ].sheet_properties.tabColor = (
            DARK_RED
        )


        # ====================================================
        # OPEN WORKBOOK ON EXECUTIVE SUMMARY
        # ====================================================

        workbook.active = (
            workbook.sheetnames.index(
                "Executive Summary"
            )
        )


    output.seek(0)


    return output


# ============================================================
# MONTHLY SCHOLARSHIP EXPORT DATA
# ============================================================

def get_monthly_scholarship_export_data(
    year,
    month
):
    """
    Return summary and transaction detail for the formal
    monthly scholarship report.

    Data comes from the view v_scholarship_lines.
    """

    # --------------------------------------------------------
    # REPORTING PERIOD
    #
    # first_day       = first day of the selected month
    # next_first_day  = first day of the following month
    # --------------------------------------------------------

    year = int(year)

    month = int(month)

    first_day = date(
        year,
        month,
        1
    )

    if month == 12:

        next_first_day = date(
            year + 1,
            1,
            1
        )

    else:

        next_first_day = date(
            year,
            month + 1,
            1
        )


    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(quantity), 0),
                    COALESCE(SUM(allocated_revenue), 0),
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


            summary_row = (
                cur.fetchone()
            )


            cur.execute(
                """
                SELECT
                    sale_date,
                    sale_id,
                    sales_channel,
                    payment_method,
                    quantity,
                    allocated_revenue,
                    scholarship_amount

                FROM v_scholarship_lines

                WHERE sale_date >= %s
                  AND sale_date < %s

                ORDER BY
                    sale_date,
                    sale_id;
                """,
                (
                    first_day,
                    next_first_day
                )
            )


            detail_rows = (
                cur.fetchall()
            )


    return {
        "bottles_sold":
            summary_row[0],

        "eligible_revenue":
            summary_row[1],

        "scholarship_owed":
            summary_row[2],

        # Read from the products table (for example 0.16).
        "scholarship_rate":
            float(
                get_scholarship_rate()
            ),

        "details":
            detail_rows
    }


# ============================================================
# MONTHLY SCHOLARSHIP REPORT
# ============================================================

def create_monthly_scholarship_report(
    year,
    month,
    month_name
):
    """
    Create the formal monthly university scholarship report.
    """

    data = (
        get_monthly_scholarship_export_data(
            year,
            month
        )
    )


    workbook = (
        Workbook()
    )


    worksheet = (
        workbook.active
    )


    worksheet.title = (
        "Monthly Scholarship Report"
    )


    worksheet.sheet_view.showGridLines = (
        False
    )


    worksheet.page_setup.orientation = (
        "landscape"
    )


    worksheet.page_setup.fitToWidth = (
        1
    )


    worksheet.sheet_properties.pageSetUpPr.fitToPage = (
        True
    )


    widths = {
        "A": 16,
        "B": 12,
        "C": 22,
        "D": 18,
        "E": 12,
        "F": 20,
        "G": 20
    }


    for column, width in widths.items():

        worksheet.column_dimensions[
            column
        ].width = width


    # ========================================================
    # TITLE
    # ========================================================

    worksheet.merge_cells(
        "A1:G1"
    )


    worksheet[
        "A1"
    ] = (
        "DR. D'S SLOBBERIN' SAUCE"
    )


    worksheet[
        "A1"
    ].font = Font(
        size=18,
        bold=True,
        color=NC_STATE_RED
    )


    worksheet[
        "A1"
    ].alignment = Alignment(
        horizontal="center"
    )


    worksheet.merge_cells(
        "A2:G2"
    )


    worksheet[
        "A2"
    ] = (
        "MONTHLY SCHOLARSHIP REPORT"
    )


    worksheet[
        "A2"
    ].font = Font(
        size=14,
        bold=True,
        color=DARK_TEXT
    )


    worksheet[
        "A2"
    ].alignment = Alignment(
        horizontal="center"
    )


    worksheet.merge_cells(
        "A4:G4"
    )


    worksheet[
        "A4"
    ] = (
        f"Reporting Period: "
        f"{month_name} {year}"
    )


    worksheet[
        "A4"
    ].font = Font(
        bold=True,
        color=SECONDARY_TEXT
    )


    worksheet[
        "A4"
    ].alignment = Alignment(
        horizontal="center"
    )


    # ========================================================
    # SCHOLARSHIP DUE
    # ========================================================

    worksheet.merge_cells(
        "A6:G6"
    )


    worksheet[
        "A6"
    ] = (
        "SCHOLARSHIP CONTRIBUTION DUE"
    )


    worksheet[
        "A6"
    ].fill = PatternFill(
        fill_type="solid",
        fgColor=NC_STATE_RED
    )


    worksheet[
        "A6"
    ].font = Font(
        bold=True,
        color=WHITE
    )


    worksheet[
        "A6"
    ].alignment = Alignment(
        horizontal="center"
    )


    worksheet.merge_cells(
        "A7:G8"
    )


    worksheet[
        "A7"
    ] = float(
        data[
            "scholarship_owed"
        ]
    )


    worksheet[
        "A7"
    ].number_format = (
        "$#,##0.00"
    )


    worksheet[
        "A7"
    ].fill = PatternFill(
        fill_type="solid",
        fgColor=LIGHT_RED
    )


    worksheet[
        "A7"
    ].font = Font(
        size=24,
        bold=True,
        color=NC_STATE_RED
    )


    worksheet[
        "A7"
    ].alignment = Alignment(
        horizontal="center",
        vertical="center"
    )


    # ========================================================
    # SUMMARY
    # ========================================================

    summary_items = [
        (
            "A10:B10",
            "A11:B11",
            "Slobberin' Jars Sold",
            int(
                data[
                    "bottles_sold"
                ]
            ),
            None
        ),

        (
            "C10:D10",
            "C11:D11",
            "Eligible Revenue",
            float(
                data[
                    "eligible_revenue"
                ]
            ),
            "$#,##0.00"
        ),

        (
            "E10:G10",
            "E11:G11",
            "Scholarship Rate",
            data[
                "scholarship_rate"
            ],
            "0.00%"
        )
    ]


    for (
        label_range,
        value_range,
        label,
        value,
        number_format
    ) in summary_items:

        worksheet.merge_cells(
            label_range
        )


        worksheet.merge_cells(
            value_range
        )


        label_cell = worksheet[
            label_range.split(
                ":"
            )[0]
        ]


        value_cell = worksheet[
            value_range.split(
                ":"
            )[0]
        ]


        label_cell.value = (
            label
        )


        value_cell.value = (
            value
        )


        label_cell.font = Font(
            bold=True,
            color=SECONDARY_TEXT
        )


        value_cell.font = Font(
            size=14,
            bold=True
        )


        label_cell.alignment = Alignment(
            horizontal="center"
        )


        value_cell.alignment = Alignment(
            horizontal="center"
        )


        if number_format is not None:

            value_cell.number_format = (
                number_format
            )


    # ========================================================
    # DETAIL
    # ========================================================

    worksheet.merge_cells(
        "A13:G13"
    )


    worksheet[
        "A13"
    ] = (
        "CONTRIBUTION DETAIL"
    )


    worksheet[
        "A13"
    ].font = Font(
        bold=True,
        color=NC_STATE_RED
    )


    headers = [
        "Date",
        "Sale ID",
        "Channel",
        "Payment",
        "Jars",
        "Eligible Revenue",
        "Scholarship"
    ]


    border = (
        get_thin_border()
    )


    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=14,
            column=column_number,
            value=header
        )


        cell.fill = PatternFill(
            fill_type="solid",
            fgColor=NC_STATE_RED
        )


        cell.font = Font(
            bold=True,
            color=WHITE
        )


        cell.border = (
            border
        )


    current_row = 15


    for detail in data[
        "details"
    ]:

        values = [
            detail[0],
            detail[1],
            detail[2],
            detail[3],
            detail[4],
            float(
                detail[5]
            ),
            float(
                detail[6]
            )
        ]


        for column_number, value in enumerate(
            values,
            start=1
        ):

            cell = worksheet.cell(
                row=current_row,
                column=column_number,
                value=value
            )


            cell.border = (
                border
            )


        worksheet.cell(
            row=current_row,
            column=1
        ).number_format = (
            "mmm d, yyyy"
        )


        worksheet.cell(
            row=current_row,
            column=6
        ).number_format = (
            "$#,##0.00"
        )


        worksheet.cell(
            row=current_row,
            column=7
        ).number_format = (
            "$#,##0.00"
        )


        current_row += 1


    # ========================================================
    # TOTAL
    # ========================================================

    worksheet.merge_cells(
        start_row=current_row,
        start_column=1,
        end_row=current_row,
        end_column=4
    )


    worksheet.cell(
        row=current_row,
        column=1,
        value="TOTAL"
    )


    worksheet.cell(
        row=current_row,
        column=5,
        value=int(
            data[
                "bottles_sold"
            ]
        )
    )


    worksheet.cell(
        row=current_row,
        column=6,
        value=float(
            data[
                "eligible_revenue"
            ]
        )
    ).number_format = (
        "$#,##0.00"
    )


    worksheet.cell(
        row=current_row,
        column=7,
        value=float(
            data[
                "scholarship_owed"
            ]
        )
    ).number_format = (
        "$#,##0.00"
    )


    for column_number in range(
        1,
        8
    ):

        cell = worksheet.cell(
            row=current_row,
            column=column_number
        )


        cell.fill = PatternFill(
            fill_type="solid",
            fgColor=LIGHT_BACKGROUND
        )


        cell.font = Font(
            bold=True
        )


        cell.border = (
            border
        )


    note_row = (
        current_row + 2
    )


    worksheet.merge_cells(
        start_row=note_row,
        start_column=1,
        end_row=note_row,
        end_column=7
    )


    worksheet.cell(
        row=note_row,
        column=1,
        value=(
            "Scholarship Calculation: "
            "Eligible Slobberin' Sauce Revenue × "
            f"{data['scholarship_rate']:.0%} "
            "= Scholarship Contribution Due"
        )
    )


    worksheet.cell(
        row=note_row,
        column=1
    ).font = Font(
        italic=True,
        color=SECONDARY_TEXT
    )


    worksheet.cell(
        row=note_row,
        column=1
    ).alignment = Alignment(
        horizontal="center"
    )


    output = (
        BytesIO()
    )


    workbook.save(
        output
    )


    output.seek(0)


    return output


# ============================================================
# INVENTORY REPORT
# ============================================================

def create_inventory_report():
    """
    Create the standalone Inventory Report.
    """

    inventory_df = (
        get_inventory_report()
    )


    batch_df = (
        get_batch_report()
    )


    movement_df = (
        get_inventory_movement_report()
    )


    # Friendly names come from ONE shared list in
    # inventory_service.py (includes "Voided Sale").
    movement_labels = (
        TRANSACTION_LABELS
    )


    if not movement_df.empty:

        movement_df[
            "transaction_type"
        ] = (
            movement_df[
                "transaction_type"
            ]
            .map(
                movement_labels
            )
            .fillna(
                movement_df[
                    "transaction_type"
                ]
            )
        )


    workbook = (
        Workbook()
    )


    summary_sheet = (
        workbook.active
    )


    summary_sheet.title = (
        "Inventory Summary"
    )


    summary_sheet.sheet_view.showGridLines = (
        False
    )


    widths = {
        "A": 28,
        "B": 18,
        "C": 18,
        "D": 22
    }


    for column, width in widths.items():

        summary_sheet.column_dimensions[
            column
        ].width = width


    summary_sheet.merge_cells(
        "A1:D1"
    )


    summary_sheet[
        "A1"
    ] = (
        "DR. D'S INVENTORY REPORT"
    )


    summary_sheet[
        "A1"
    ].font = Font(
        size=18,
        bold=True,
        color=NC_STATE_RED
    )


    summary_sheet[
        "A1"
    ].alignment = Alignment(
        horizontal="center"
    )


    total_jars = int(
        inventory_df[
            "current_quantity"
        ].sum()
    )


    total_value = float(
        inventory_df[
            "estimated_inventory_value"
        ].sum()
    )


    summary_sheet.merge_cells(
        "A4:B4"
    )


    summary_sheet[
        "A4"
    ] = (
        "TOTAL JARS IN INVENTORY"
    )


    summary_sheet.merge_cells(
        "A5:B6"
    )


    summary_sheet[
        "A5"
    ] = (
        total_jars
    )


    summary_sheet.merge_cells(
        "C4:D4"
    )


    summary_sheet[
        "C4"
    ] = (
        "ESTIMATED INVENTORY VALUE"
    )


    summary_sheet.merge_cells(
        "C5:D6"
    )


    summary_sheet[
        "C5"
    ] = (
        total_value
    )


    summary_sheet[
        "C5"
    ].number_format = (
        "$#,##0.00"
    )


    for reference in [
        "A4",
        "C4"
    ]:

        summary_sheet[
            reference
        ].fill = PatternFill(
            fill_type="solid",
            fgColor=NC_STATE_RED
        )


        summary_sheet[
            reference
        ].font = Font(
            bold=True,
            color=WHITE
        )


        summary_sheet[
            reference
        ].alignment = Alignment(
            horizontal="center"
        )


    for reference in [
        "A5",
        "C5"
    ]:

        summary_sheet[
            reference
        ].fill = PatternFill(
            fill_type="solid",
            fgColor=LIGHT_RED
        )


        summary_sheet[
            reference
        ].font = Font(
            size=20,
            bold=True,
            color=NC_STATE_RED
        )


        summary_sheet[
            reference
        ].alignment = Alignment(
            horizontal="center",
            vertical="center"
        )


    headers = [
        "Product",
        "Current Jars",
        "Unit Cost",
        "Estimated Value"
    ]


    border = (
        get_thin_border()
    )


    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = summary_sheet.cell(
            row=9,
            column=column_number,
            value=header
        )


        cell.fill = PatternFill(
            fill_type="solid",
            fgColor=NC_STATE_RED
        )


        cell.font = Font(
            bold=True,
            color=WHITE
        )


        cell.border = (
            border
        )


    row_number = (
        10
    )


    for _, row in inventory_df.iterrows():

        values = [
            row[
                "product_name"
            ],

            int(
                row[
                    "current_quantity"
                ]
            ),

            float(
                row[
                    "unit_cost"
                ]
            ),

            float(
                row[
                    "estimated_inventory_value"
                ]
            )
        ]


        for column_number, value in enumerate(
            values,
            start=1
        ):

            cell = summary_sheet.cell(
                row=row_number,
                column=column_number,
                value=value
            )


            cell.border = (
                border
            )


        summary_sheet.cell(
            row=row_number,
            column=3
        ).number_format = (
            "$#,##0.00"
        )


        summary_sheet.cell(
            row=row_number,
            column=4
        ).number_format = (
            "$#,##0.00"
        )


        row_number += 1


    # ========================================================
    # BATCH HISTORY SHEET
    # ========================================================

    batch_sheet = (
        workbook.create_sheet(
            "Batch History"
        )
    )


    batch_export = (
        batch_df.rename(
            columns={
                "batch_id":
                    "Batch ID",

                "batch_code":
                    "Batch Code",

                "received_date":
                    "Received",

                "product_name":
                    "Product",

                "quantity_received":
                    "Qty Received",

                "manufacturer":
                    "Manufacturer",

                "notes":
                    "Notes"
            }
        )
    )


    for column_number, column_name in enumerate(
        batch_export.columns,
        start=1
    ):

        batch_sheet.cell(
            row=1,
            column=column_number,
            value=column_name
        )


    for row_index, row in enumerate(
        batch_export.itertuples(
            index=False
        ),
        start=2
    ):

        for column_number, value in enumerate(
            row,
            start=1
        ):

            batch_sheet.cell(
                row=row_index,
                column=column_number,
                value=value
            )


    format_standard_table(
        batch_sheet
    )


    # ========================================================
    # MOVEMENTS SHEET
    # ========================================================

    movement_sheet = (
        workbook.create_sheet(
            "Inventory Movements"
        )
    )


    movement_export = (
        movement_df.rename(
            columns={
                "transaction_id":
                    "Movement ID",

                "transaction_date":
                    "Date",

                "product_name":
                    "Product",

                "transaction_type":
                    "Type",

                "quantity_change":
                    "Qty Change",

                "batch_code":
                    "Batch",

                "sale_id":
                    "Sale ID",

                "notes":
                    "Notes"
            }
        )
    )


    for column_number, column_name in enumerate(
        movement_export.columns,
        start=1
    ):

        movement_sheet.cell(
            row=1,
            column=column_number,
            value=column_name
        )


    for row_index, row in enumerate(
        movement_export.itertuples(
            index=False
        ),
        start=2
    ):

        for column_number, value in enumerate(
            row,
            start=1
        ):

            movement_sheet.cell(
                row=row_index,
                column=column_number,
                value=value
            )


    format_standard_table(
        movement_sheet
    )


    output = (
        BytesIO()
    )


    workbook.save(
        output
    )


    output.seek(0)


    return output