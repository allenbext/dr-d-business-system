"""
page_scholarship.py

Purpose:
Render the Scholarship Report page.

Sections:

1. Reporting Period (year, month, month / year-to-date view).
2. Contribution due, jars sold, eligible revenue.
3. Monthly report for the university (Excel).
4. Contribution detail.

Default period:

Dr. D reports on the 1st of each month for the month that just
ended. During the first 10 days of a month the page therefore
opens on the PREVIOUS month. After that it opens on the current
month.
"""

from datetime import date

import pandas as pd
import streamlit as st

from scholarship_service import (
    get_monthly_scholarship_details,
    get_monthly_scholarship_summary,
    get_scholarship_rate,
    get_ytd_scholarship_details,
    get_ytd_scholarship_summary
)

from ui_helpers import (
    MONTH_NAMES,
    STRETCH,
    XLSX_MIME,
    cached_scholarship_report,
    format_currency,
    get_data_version,
    page_header,
    section_label
)


# ============================================================
# DEFAULT REPORTING PERIOD
# ============================================================

def get_default_period(today):
    """
    Return (year, month) the page should open on.

    Day 1-10 of a month  -> previous month (the report that is due)
    Day 11 and later     -> current month

    Examples:

        2026-12-03 -> (2026, 11)
        2026-11-15 -> (2026, 11)
        2027-01-05 -> (2026, 12)
    """

    if today.day > 10:

        return today.year, today.month

    if today.month == 1:

        return today.year - 1, 12

    return today.year, today.month - 1


def get_due_date(year, month):
    """
    The monthly report is due on the 1st of the following month.
    """

    if month == 12:

        return date(year + 1, 1, 1)

    return date(year, month + 1, 1)


# ============================================================
# SCHOLARSHIP PAGE
# ============================================================

def render_scholarship():
    """
    Draw the Scholarship Report page.
    """

    today = date.today()

    try:

        # Example: Decimal("0.1600") -> "16%"
        scholarship_percent = f"{float(get_scholarship_rate()):.0%}"

        page_header(
            "Scholarship Report",
            f"Monitor and prepare the monthly {scholarship_percent} "
            "scholarship contribution report for Slobberin' Sauce."
        )

        default_year, default_month = get_default_period(today)

        # ====================================================
        # REPORTING PERIOD
        # ====================================================

        section_label("Reporting Period")

        filter1, filter2, filter3 = st.columns([1, 1, 1.3])

        with filter1:

            # A short list is easier than typing a year.
            year_options = list(
                range(today.year - 3, today.year + 1)
            )

            selected_year = st.selectbox(
                "Year",
                year_options,
                index=year_options.index(default_year),
                key="scholarship_year"
            )

        with filter2:

            selected_month = st.selectbox(
                "Month",
                list(MONTH_NAMES.keys()),
                index=default_month - 1,
                format_func=lambda month: MONTH_NAMES[month],
                key="scholarship_month"
            )

        with filter3:

            report_period = st.radio(
                "View",
                [
                    "This Month",
                    "Year to Date"
                ],
                horizontal=True,
                key="scholarship_view"
            )

        month_label = (
            f"{MONTH_NAMES[selected_month]} {selected_year}"
        )

        # ====================================================
        # LOAD DATA
        # ====================================================

        if report_period == "This Month":

            summary = get_monthly_scholarship_summary(
                selected_year,
                selected_month
            )

            details = get_monthly_scholarship_details(
                selected_year,
                selected_month
            )

            period_label = month_label

        else:

            summary = get_ytd_scholarship_summary(
                selected_year,
                selected_month
            )

            details = get_ytd_scholarship_details(
                selected_year,
                selected_month
            )

            period_label = f"January – {month_label}"

        st.write("")

        # ====================================================
        # KPI
        # ====================================================

        section_label(period_label)

        metric1, metric2, metric3 = st.columns([1.4, 1.3, 1.3])

        with metric1:

            st.metric(
                "Scholarship Contribution Due",
                format_currency(summary["scholarship_amount"])
            )

        with metric2:

            st.metric(
                "Slobberin' Jars Sold",
                f"{int(summary['bottles_sold']):,}"
            )

        with metric3:

            st.metric(
                "Eligible Revenue",
                format_currency(summary["eligible_revenue"])
            )

        st.caption(
            "Scholarship Contribution = "
            f"Eligible Slobberin' Sauce Revenue × {scholarship_percent}"
        )

        st.divider()

        # ====================================================
        # UNIVERSITY REPORT
        # ====================================================

        section_label("University Report")

        report_left, report_right = st.columns(
            [3, 1],
            vertical_alignment="center"
        )

        due_date = get_due_date(selected_year, selected_month)

        with report_left:

            st.subheader("Monthly Scholarship Report")

            st.write(
                f"Formal report for **{month_label}**. "
                f"Due on {due_date.strftime('%B %d, %Y')}."
            )

            # Selecting the current month shows numbers that
            # can still change until the month ends.
            if (selected_year, selected_month) == (today.year, today.month):

                st.caption(
                    f"{month_label} is not finished yet. "
                    "The numbers will change as sales are added."
                )

        with report_right:

            st.download_button(
                "Download Monthly Report",
                data=cached_scholarship_report(
                    get_data_version(),
                    selected_year,
                    selected_month
                ),
                file_name=(
                    "Dr_D_Scholarship_Report_"
                    f"{selected_year}_{selected_month:02d}_"
                    f"{MONTH_NAMES[selected_month]}.xlsx"
                ),
                mime=XLSX_MIME,
                type="primary",
                key="scholarship_report_button",
                **STRETCH
            )

        st.divider()

        # ====================================================
        # DETAILS
        # ====================================================

        section_label("Contribution Detail")

        if len(details) == 0:

            st.info(
                "No Slobberin' Sauce sales were found "
                "for the selected period."
            )

            return

        details_df = pd.DataFrame(details)

        details_df["sale_date"] = pd.to_datetime(
            details_df["sale_date"]
        ).dt.strftime("%b %d, %Y")

        for column in ("allocated_revenue", "scholarship_amount"):

            details_df[column] = details_df[column].astype(float)

        details_df = details_df.rename(
            columns={
                "sale_id": "Sale #",
                "sale_date": "Date",
                "sales_channel": "Channel",
                "payment_method": "Payment",
                "quantity": "Jars",
                "allocated_revenue": "Eligible Revenue",
                "scholarship_amount": "Scholarship"
            }
        )

        st.dataframe(
            details_df,
            hide_index=True,
            column_config={
                "Eligible Revenue": st.column_config.NumberColumn(
                    format="$%.2f"
                ),
                "Scholarship": st.column_config.NumberColumn(
                    format="$%.2f"
                )
            },
            **STRETCH
        )

        st.caption(
            f"Total for {period_label}: "
            f"{int(summary['bottles_sold']):,} jars · "
            f"{format_currency(summary['eligible_revenue'])} eligible revenue · "
            f"{format_currency(summary['scholarship_amount'])} scholarship."
        )

    except Exception as error:

        st.error(f"Could not load scholarship report: {error}")
