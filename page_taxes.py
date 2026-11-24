"""
page_taxes.py

Purpose:
Render the Sales Tax page.

Tabs:

1. NC Tax by County
   The month's North Carolina retail sales grouped by county:
   taxable amount, tax collected, expected 2% and the
   difference. Downloadable as Excel for the CPA.

2. Sales by State
   Orders and sales per state for this year and last year,
   compared with economic nexus thresholds that Dr. D can set.
   A state that comes close is flagged, so he learns early that
   he may have to register there.

The calculations live in tax_service.py.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from tax_service import (
    APPROACHING_SHARE,
    DEFAULT_NEXUS_ORDERS,
    DEFAULT_NEXUS_SALES,
    create_tax_by_county_report,
    get_monthly_tax_by_county,
    get_nexus_watch,
    get_tax_mismatches,
    summarize_tax_by_county
)

from ui_helpers import (
    MONTH_NAMES,
    STRETCH,
    XLSX_MIME,
    format_currency,
    get_data_version,
    kpi_card,
    page_header,
    section_label
)


# ============================================================
# CACHED EXCEL FILE
# ============================================================

@st.cache_data(show_spinner=False, max_entries=24)
def _cached_tax_report(data_version, year, month):
    """
    County tax workbook as bytes. Rebuilt only when the data
    changed (data_version) or another month is chosen.
    """

    return create_tax_by_county_report(year, month)


# ============================================================
# DEFAULT MONTH
# ============================================================

def _default_period(today):
    """
    The tax return is filed for the month that just ended.
    During the first 20 days of a month the page therefore opens
    on the PREVIOUS month; after that on the current month.
    """

    if today.day > 20:

        return today.year, today.month

    if today.month == 1:

        return today.year - 1, 12

    return today.year, today.month - 1


# ============================================================
# TAB 1: NC TAX BY COUNTY
# ============================================================

def _render_county_tab(today):
    """
    Draw the NC Tax by County tab.
    """

    default_year, default_month = _default_period(today)

    section_label("Reporting Month")

    filter1, filter2, _ = st.columns([1, 1, 1.3])

    with filter1:

        year_options = list(range(today.year - 3, today.year + 1))

        year = st.selectbox(
            "Year",
            year_options,
            index=year_options.index(default_year),
            key="tax_year"
        )

    with filter2:

        month = st.selectbox(
            "Month",
            list(MONTH_NAMES.keys()),
            index=default_month - 1,
            format_func=lambda number: MONTH_NAMES[number],
            key="tax_month"
        )

    counties = get_monthly_tax_by_county(year, month)

    summary = summarize_tax_by_county(counties)

    period = f"{MONTH_NAMES[month]} {year}"

    if summary["sales"] == 0:

        st.info(f"No North Carolina retail sales in {period}.")

        return

    # --------------------------------------------------------
    # KPIs
    # --------------------------------------------------------

    st.write("")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    with kpi1:

        kpi_card(
            "Tax Collected",
            format_currency(summary["tax_collected"]),
            "primary"
        )

    with kpi2:

        kpi_card(
            "Taxable Sales",
            format_currency(summary["taxable_amount"]),
            "secondary",
            note="Product + shipping, NC retail"
        )

    with kpi3:

        kpi_card(
            "Counties",
            f"{summary['counties']}",
            "secondary",
            note=f"{summary['sales']} sales"
        )

    with kpi4:

        difference = summary["difference"]

        kpi_card(
            "Difference from 2%",
            format_currency(difference),
            "secondary",
            note=(
                "Matches the 2% rate"
                if abs(difference) < Decimal("0.05")
                else "See the sales listed below"
            )
        )

    # --------------------------------------------------------
    # WARNINGS
    # --------------------------------------------------------

    if summary["missing_county_sales"] > 0:

        st.warning(
            f"{summary['missing_county_sales']} NC sale(s) in "
            f"{period} have no county. Add the county so the tax "
            "is reported for the right place."
        )

    # --------------------------------------------------------
    # TABLE
    # --------------------------------------------------------

    st.write("")

    section_label("Tax by County")

    table = pd.DataFrame(
        [
            {
                "County": row["county"],
                "Sales": row["sales"],
                "Taxable Amount": float(row["taxable_amount"]),
                "Tax Collected": float(row["tax_collected"]),
                "Expected 2%": float(row["expected_tax"]),
                "Difference": float(row["difference"])
            }
            for row in counties
            if row["sales"] > 0
        ]
    )

    st.dataframe(
        table,
        hide_index=True,
        column_config={
            column: st.column_config.NumberColumn(format="$%.2f")
            for column in (
                "Taxable Amount",
                "Tax Collected",
                "Expected 2%",
                "Difference"
            )
        },
        **STRETCH
    )

    st.caption(
        "A sale belongs to the county where the customer receives "
        "it: the delivery address for shipped orders, the market "
        "location for farmers markets. Taxable amount = product "
        "revenue + shipping. Wholesale sales "
        f"({format_currency(summary['wholesale_revenue'])} this "
        "month) are not taxable and are not included. Out-of-state "
        "orders carry no NC tax."
    )

    # --------------------------------------------------------
    # SALES WHERE THE TAX IS NOT 2%
    # --------------------------------------------------------

    mismatches = get_tax_mismatches(year, month)

    if mismatches:

        with st.expander(
            f"Sales where the tax is not 2% ({len(mismatches)})"
        ):

            st.caption(
                "Often correct, for example when the cash collected "
                "already included the tax. Check these first if the "
                "totals do not match."
            )

            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Sale #": row["sale_id"],
                            "Date": row["sale_date"].strftime("%b %d, %Y"),
                            "Channel": row["sales_channel"],
                            "Payment": row["payment_method"],
                            "County": row["county"],
                            "Taxable Amount": float(row["taxable_amount"]),
                            "Tax Collected": float(row["tax_collected"]),
                            "Expected 2%": float(row["expected_tax"])
                        }
                        for row in mismatches
                    ]
                ),
                hide_index=True,
                column_config={
                    column: st.column_config.NumberColumn(format="$%.2f")
                    for column in (
                        "Taxable Amount",
                        "Tax Collected",
                        "Expected 2%"
                    )
                },
                **STRETCH
            )

    # --------------------------------------------------------
    # DOWNLOAD
    # --------------------------------------------------------

    report_bytes = _cached_tax_report(
        get_data_version(),
        year,
        month
    )

    st.download_button(
        "Download County Tax Report",
        data=report_bytes,
        file_name=f"NC_Sales_Tax_by_County_{year}-{month:02d}.xlsx",
        mime=XLSX_MIME,
        type="primary",
        key="tax_download"
    )

    st.caption(
        "Bookkeeping aid for the CPA. The 2% food rate and the "
        "county rules should be confirmed by the CPA."
    )


# ============================================================
# TAB 2: SALES BY STATE
# ============================================================

def _render_state_tab(today):
    """
    Draw the Sales by State tab.
    """

    section_label("Thresholds to Watch")

    st.caption(
        "A state can require an out-of-state seller to collect its "
        "sales tax after the seller passes that state's threshold. "
        "Most states use $100,000 of sales a year; some also count "
        "200 orders. Thresholds differ by state and change, so check "
        "the state's own rule before acting."
    )

    limit1, limit2, _ = st.columns([1, 1, 1.3])

    with limit1:

        sales_threshold = st.number_input(
            "Sales threshold ($ per year)",
            min_value=0,
            step=10000,
            value=int(DEFAULT_NEXUS_SALES),
            key="nexus_sales"
        )

    with limit2:

        orders_threshold = st.number_input(
            "Order threshold (0 = ignore)",
            min_value=0,
            step=50,
            value=DEFAULT_NEXUS_ORDERS,
            key="nexus_orders"
        )

    watch = get_nexus_watch(
        today.year,
        sales_threshold,
        orders_threshold
    )

    if len(watch) == 0:

        st.info("No sales outside North Carolina yet.")

        return

    flagged = [
        row for row in watch
        if row["status"] != "OK"
    ]

    if flagged:

        names = ", ".join(row["state"] for row in flagged)

        st.warning(
            f"Check these states: {names}. They have reached "
            f"{APPROACHING_SHARE:.0%} or more of a threshold. "
            "Ask the CPA whether Dr. D must register there."
        )

    else:

        st.success(
            "No state is close to the thresholds. Out-of-state "
            "orders need no sales tax for now."
        )

    st.write("")

    section_label("Sales Outside North Carolina")

    table = pd.DataFrame(
        [
            {
                "State": row["state"],
                f"Orders {today.year}": row["orders_this_year"],
                f"Sales {today.year}": float(row["sales_this_year"]),
                f"Orders {today.year - 1}": row["orders_last_year"],
                f"Sales {today.year - 1}": float(row["sales_last_year"]),
                "Of Threshold": float(row["highest_share"]) * 100,
                "Status": row["status"]
            }
            for row in watch
        ]
    )

    st.dataframe(
        table,
        hide_index=True,
        column_config={
            f"Sales {today.year}": st.column_config.NumberColumn(format="$%.2f"),
            f"Sales {today.year - 1}": st.column_config.NumberColumn(format="$%.2f"),
            "Of Threshold": st.column_config.NumberColumn(
                format="%.0f%%"
            )
        },
        **STRETCH
    )

    st.caption(
        "Sales = product revenue + shipping charged, without tax. "
        "\"Of Threshold\" is the highest share of the sales or order "
        "threshold in this year or last year."
    )


# ============================================================
# SALES TAX PAGE
# ============================================================

def render_taxes():
    """
    Draw the Sales Tax page.
    """

    today = date.today()

    page_header(
        "Sales Tax",
        "North Carolina tax by county for the CPA, and a check on "
        "sales to other states."
    )

    try:

        county_tab, state_tab = st.tabs(
            [
                "NC Tax by County",
                "Sales by State"
            ]
        )

        with county_tab:

            _render_county_tab(today)

        with state_tab:

            _render_state_tab(today)

    except Exception as error:

        st.error(f"Could not load Sales Tax: {error}")
