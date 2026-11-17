"""
page_dashboard.py

Purpose:
Render the Business Dashboard page.

Sections:

1. Header with "Record a Sale" and "Export Business Report".
2. This Month: Revenue, Estimated Profit, Scholarship Due.
3. Business Performance: Year to Date and All Time.
4. Available Stock and Revenue by Week.
5. Operations This Month.
6. Latest Sales (including jars sold).
"""

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_service import (
    get_monthly_dashboard_summary,
    get_financial_kpis,
    get_weekly_sales
)

from inventory_service import get_current_inventory

from sale_service import get_recent_sales_with_items

from ui_helpers import (
    NC_STATE_RED,
    STRETCH,
    XLSX_MIME,
    cached_business_report,
    describe_supply,
    format_currency,
    get_data_version,
    get_weeks_of_supply,
    kpi_card,
    page_header,
    section_label,
    style_chart
)


# ============================================================
# NAVIGATION CALLBACK
# ============================================================

def _prepare_business_report(data_version):
    """
    Remember that the user asked for the Excel report of the
    current data version. The Dashboard then builds the report
    and shows the download button.
    """

    st.session_state["dashboard_report_version"] = data_version


def _go_to_record_sale():
    """
    Open the Record Sale page.
    """

    st.session_state.page = "Record Sale"


# ============================================================
# DASHBOARD PAGE
# ============================================================

def render_dashboard():
    """
    Draw the Dashboard page.
    """

    today = date.today()

    try:

        # ====================================================
        # LOAD DATA
        # ====================================================

        summary = get_monthly_dashboard_summary(
            today.year,
            today.month
        )

        financial_kpis = get_financial_kpis(today)

        weekly_sales = get_weekly_sales(
            today.year,
            today.month
        )

        recent_sales = get_recent_sales_with_items(limit=5)

        inventory = get_current_inventory()

        data_version = get_data_version()

        # ====================================================
        # HEADER
        # ====================================================

        header_left, header_action, header_export = st.columns(
            [3.2, 1, 1.3],
            vertical_alignment="center"
        )

        with header_left:

            page_header(
                "Business Dashboard",
                f"Business performance at a glance · "
                f"{today.strftime('%B %d, %Y')}"
            )

        with header_action:

            st.button(
                "Record a Sale",
                type="primary",
                on_click=_go_to_record_sale,
                key="dashboard_record_sale",
                **STRETCH
            )

        with header_export:

            # The Excel workbook contains every sale, so building
            # it takes a few seconds. It is therefore NOT built
            # while the Dashboard is drawn. It is built only when
            # the user asks for it:
            #
            #   step 1  "Prepare Business Report"  -> builds the file
            #   step 2  "Download Business Report" -> saves the file
            #
            # The prepared file belongs to one data version. After
            # a new sale or inventory movement the button goes
            # back to step 1, so an outdated report is never
            # downloaded.
            report_is_ready = (
                st.session_state.get("dashboard_report_version")
                == data_version
            )

            if report_is_ready:

                with st.spinner("Preparing report..."):

                    report_bytes = cached_business_report(
                        data_version,
                        today
                    )

                st.download_button(
                    "Download Business Report",
                    data=report_bytes,
                    file_name=(
                        "Dr_D_Business_Report_"
                        f"{today.strftime('%Y-%m-%d')}.xlsx"
                    ),
                    mime=XLSX_MIME,
                    key="dashboard_export",
                    **STRETCH
                )

            else:

                st.button(
                    "Prepare Business Report",
                    on_click=_prepare_business_report,
                    args=(data_version,),
                    key="dashboard_prepare_report",
                    **STRETCH
                )

        # ====================================================
        # THIS MONTH
        # ====================================================

        section_label(
            f"This Month · {today.strftime('%B %Y')}"
        )

        primary1, primary2, primary3 = st.columns(3)

        with primary1:

            kpi_card(
                "Revenue",
                format_currency(financial_kpis["month_revenue"])
            )

        with primary2:

            kpi_card(
                "Estimated Profit",
                format_currency(financial_kpis["month_profit"])
            )

        with primary3:

            kpi_card(
                "Scholarship Contribution Due",
                format_currency(summary["scholarship_owed"])
            )

        st.write("")

        # ====================================================
        # BUSINESS PERFORMANCE
        # ====================================================

        section_label("Business Performance")

        secondary1, secondary2, secondary3, secondary4 = st.columns(4)

        with secondary1:

            kpi_card(
                "Revenue — Year to Date",
                format_currency(financial_kpis["ytd_revenue"]),
                style="secondary"
            )

        with secondary2:

            kpi_card(
                "Profit — Year to Date",
                format_currency(financial_kpis["ytd_profit"]),
                style="secondary"
            )

        with secondary3:

            kpi_card(
                "All-Time Revenue",
                format_currency(financial_kpis["all_time_revenue"]),
                style="secondary"
            )

        with secondary4:

            kpi_card(
                "All-Time Profit",
                format_currency(financial_kpis["all_time_profit"]),
                style="secondary"
            )

        st.caption(
            "Estimated Profit = product revenue + shipping revenue "
            "− product cost − scholarship − Shopify/card fees "
            "− shipping expense. Sales tax is not counted as revenue."
        )

        st.divider()

        # ====================================================
        # INVENTORY + REVENUE TREND
        # ====================================================

        inventory_column, trend_column = st.columns(
            [1, 1.8],
            gap="large"
        )

        # ----------------------------------------------------
        # AVAILABLE STOCK
        # ----------------------------------------------------

        with inventory_column:

            section_label("Inventory")

            st.subheader("Available Stock")

            total_inventory = 0

            inventory_html = '<div class="dashboard-panel">'

            for item in inventory:

                quantity = int(item["current_quantity"])

                total_inventory += quantity

                supply = get_weeks_of_supply(
                    item["product_id"],
                    quantity,
                    data_version
                )

                inventory_html += (
                    '<div class="inventory-product">'
                    f'<div class="inventory-name">{item["product_name"]}</div>'
                    f'<div class="inventory-value">{quantity:,} jars</div>'
                    f'<div class="inventory-name">{describe_supply(supply)}</div>'
                    '</div>'
                )

            inventory_html += (
                '<div class="inventory-total">'
                'Total inventory: '
                f'<strong>{total_inventory:,} jars</strong>'
                '</div>'
                '</div>'
            )

            st.markdown(
                inventory_html,
                unsafe_allow_html=True
            )

        # ----------------------------------------------------
        # REVENUE BY WEEK
        # ----------------------------------------------------

        with trend_column:

            section_label("Sales Trend")

            st.subheader("Revenue by Week")

            if len(weekly_sales) > 0:

                weekly_df = pd.DataFrame(weekly_sales)

                weekly_df["product_sales"] = (
                    weekly_df["product_sales"].astype(float)
                )

                weekly_df["Week"] = (
                    "Week of "
                    + pd.to_datetime(
                        weekly_df["week_start"]
                    ).dt.strftime("%b %d")
                )

                # Exact dollar amount printed above each bar.
                weekly_df["Label"] = weekly_df["product_sales"].map(
                    lambda value: f"${value:,.0f}"
                )

                revenue_chart = px.bar(
                    weekly_df,
                    x="Week",
                    y="product_sales",
                    text="Label"
                )

                revenue_chart.update_traces(
                    marker_color=NC_STATE_RED,
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="%{x}<br>%{text}<extra></extra>"
                )

                revenue_chart.update_yaxes(
                    title_text="Product Revenue ($)",
                    tickprefix="$",
                    tickformat=",.0f"
                )

                st.plotly_chart(
                    style_chart(revenue_chart, height=330),
                    **STRETCH
                )

            else:

                st.info(
                    "No sales have been recorded "
                    "for the current month."
                )

        st.divider()

        # ====================================================
        # OPERATIONS THIS MONTH
        # ====================================================

        section_label("Operations This Month")

        operating1, operating2, operating3 = st.columns(3)

        with operating1:

            kpi_card(
                "Slobberin' Jars Sold",
                f"{int(summary['slobberin_bottles']):,}",
                style="operational"
            )

        with operating2:

            kpi_card(
                "Sales Tax Collected",
                format_currency(summary["tax_collected"]),
                style="operational"
            )

        with operating3:

            kpi_card(
                "Shipping Revenue",
                format_currency(summary["shipping_revenue"]),
                style="operational"
            )

        st.divider()

        # ====================================================
        # LATEST SALES
        # ====================================================

        section_label("Recent Activity")

        st.subheader("Latest Sales")

        if len(recent_sales) > 0:

            recent_df = pd.DataFrame(recent_sales)

            recent_df["sale_date"] = pd.to_datetime(
                recent_df["sale_date"]
            ).dt.strftime("%b %d, %Y")

            for column in ("product_revenue", "scholarship"):

                recent_df[column] = recent_df[column].astype(float)

            recent_df = recent_df[
                [
                    "sale_date",
                    "sales_channel",
                    "payment_method",
                    "original_quantity",
                    "slobberin_quantity",
                    "product_revenue",
                    "scholarship",
                    "county"
                ]
            ].rename(
                columns={
                    "sale_date": "Date",
                    "sales_channel": "Channel",
                    "payment_method": "Payment",
                    "original_quantity": "Original Jars",
                    "slobberin_quantity": "Slobberin' Jars",
                    "product_revenue": "Revenue",
                    "scholarship": "Scholarship",
                    "county": "County"
                }
            )

            st.dataframe(
                recent_df,
                hide_index=True,
                column_config={
                    "Revenue": st.column_config.NumberColumn(
                        format="$%.2f"
                    ),
                    "Scholarship": st.column_config.NumberColumn(
                        format="$%.2f"
                    )
                },
                **STRETCH
            )

            st.caption(
                "The 5 most recent sales. The full list and the option "
                "to cancel a sale are on Record Sale → Recent Sales."
            )

        else:

            st.info("No sales have been recorded yet.")

    except Exception as error:

        st.error(f"Could not load dashboard: {error}")
