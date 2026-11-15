"""
page_forecast.py

Purpose:
Render the Demand Forecast page.

Tabs:

1. Create Forecast
   Choose product, county, channel and week. The forecast is
   calculated immediately and shown BEFORE it is saved.

2. Accuracy
   Forecast vs Actual for completed weeks, and all saved
   forecasts.

3. Seasonal Settings
   Demand tier and seasonal factor for each month, edited
   directly in the table.

How the forecast is calculated (forecast_service.py):

    1. Weekly jars sold, complete weeks only,
       weeks without sales count as zero.
    2. Each week is divided by its month's seasonal factor.
    3. Exponential smoothing gives the baseline demand.
    4. Baseline x seasonal factor of the forecast month
       = forecast.
"""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from forecast_service import (
    calculate_forecast,
    find_saved_forecast,
    generate_forecast,
    get_all_seasonality,
    get_forecast_filter_options,
    get_forecast_vs_actual,
    get_next_forecast_week,
    get_saved_forecasts,
    get_week_start,
    update_completed_forecasts,
    update_seasonality
)

from inventory_service import get_current_inventory

from ui_helpers import (
    NC_STATE_RED,
    NEUTRAL_SERIES,
    STRETCH,
    option_index,
    page_header,
    section_label,
    set_flash,
    show_flash,
    style_chart
)


DEMAND_TIERS = [
    "LOW",
    "MEDIUM",
    "HIGH"
]

# How many weeks back and forward the week selector offers.
WEEKS_BACK = 8
WEEKS_FORWARD = 4


# ============================================================
# WEEK SELECTOR HELPERS
# ============================================================

def get_week_options(today):
    """
    Return the Mondays offered in the Forecast Week selector.

    Past weeks are included so an earlier forecast can be
    recreated and compared with what actually happened.
    """

    current_week = get_week_start(today)

    return [
        current_week + timedelta(weeks=offset)
        for offset in range(-WEEKS_BACK, WEEKS_FORWARD + 1)
    ]


def format_week(week_start, today):
    """
    Example:  "Nov 16 – Nov 22, 2026 (next week)"
    """

    week_end = week_start + timedelta(days=6)

    label = (
        f"{week_start.strftime('%b %d')} – "
        f"{week_end.strftime('%b %d, %Y')}"
    )

    current_week = get_week_start(today)

    if week_start == current_week:

        label += " (this week)"

    elif week_start == current_week + timedelta(weeks=1):

        label += " (next week)"

    return label


# ============================================================
# SAVE FORECAST: CALLBACK
# ============================================================

def _save_forecast():
    """
    Save the forecast currently shown on the page.
    """

    state = st.session_state

    try:

        result = generate_forecast(
            product_id=state.forecast_product_id,
            forecast_week=state.forecast_week,
            sales_region=state.forecast_region,
            sales_channel=state.forecast_channel,
            smoothing_factor=state.forecast_alpha
        )

    except Exception as error:

        set_flash(
            "forecast",
            "error",
            f"Could not save forecast: {error}"
        )

        return

    set_flash(
        "forecast",
        "success",
        f"Forecast saved: "
        f"{float(result['saved_forecast_quantity']):,.0f} jars for the "
        f"week of {result['forecast_week'].strftime('%B %d, %Y')}. "
        "It will be compared with actual sales after that week ends."
    )


# ============================================================
# CREATE FORECAST TAB
# ============================================================

def _render_create_forecast(inventory, filter_options):
    """
    Draw the Create Forecast tab.
    """

    today = date.today()

    state = st.session_state

    show_flash("forecast")

    section_label("Weekly Demand Forecast")

    st.caption(
        "Choose what to forecast. Only complete weeks before the "
        "selected week are used, and a week without sales counts "
        "as zero."
    )

    name_by_product = {
        item["product_id"]: item["product_name"]
        for item in inventory
    }

    quantity_by_product = {
        item["product_id"]: int(item["current_quantity"])
        for item in inventory
    }

    product_ids = list(name_by_product.keys())

    setup_column, history_column = st.columns(
        [1, 1.8],
        gap="large"
    )

    # ========================================================
    # LEFT: FORECAST SETUP
    # ========================================================

    with setup_column:

        st.subheader("Forecast Setup")

        # Slobberin' Sauce is preselected when it exists.
        slobberin_ids = [
            product_id
            for product_id, name in name_by_product.items()
            if "Slobberin" in name
        ]

        st.selectbox(
            "Product",
            product_ids,
            index=(
                product_ids.index(slobberin_ids[0])
                if slobberin_ids
                else 0
            ),
            format_func=lambda product_id: name_by_product[product_id],
            key="forecast_product_id"
        )

        st.selectbox(
            "County",
            filter_options["regions"],
            index=option_index(filter_options["regions"], "Wake"),
            key="forecast_region",
            help="ALL = every county together."
        )

        st.selectbox(
            "Sales Channel",
            filter_options["channels"],
            index=option_index(filter_options["channels"], "Shopify"),
            key="forecast_channel",
            help="ALL = every channel together."
        )

        week_options = get_week_options(today)

        st.selectbox(
            "Forecast Week (Monday – Sunday)",
            week_options,
            index=week_options.index(get_next_forecast_week(today)),
            format_func=lambda week: format_week(week, today),
            key="forecast_week"
        )

        with st.expander("Advanced forecast setting"):

            st.slider(
                "Smoothing Factor (Alpha)",
                min_value=0.05,
                max_value=1.00,
                value=0.30,
                step=0.05,
                key="forecast_alpha",
                help=(
                    "How much the newest week counts. "
                    "0.30 = the newest week is 30% of the estimate "
                    "and all earlier weeks together are 70%. "
                    "Higher values react faster but jump around more."
                )
            )

    # ========================================================
    # CALCULATE (NOTHING IS SAVED HERE)
    # ========================================================

    result = None

    problem = None

    try:

        result = calculate_forecast(
            product_id=state.forecast_product_id,
            forecast_week=state.forecast_week,
            sales_region=state.forecast_region,
            sales_channel=state.forecast_channel,
            smoothing_factor=state.forecast_alpha
        )

    except ValueError as error:

        problem = str(error)

    # ========================================================
    # RIGHT: HISTORY CHART
    # ========================================================

    with history_column:

        st.subheader("Weekly Demand Used for the Forecast")

        if result is None:

            st.info(
                "No complete weeks with sales match the selected "
                "product, county and channel before this week."
            )

        else:

            history_df = pd.DataFrame(result["weekly_history"])

            history_df["quantity_sold"] = (
                history_df["quantity_sold"].astype(float)
            )

            history_df["deseasonalized_quantity"] = (
                history_df["deseasonalized_quantity"].astype(float)
            )

            history_df["Week"] = pd.to_datetime(
                history_df["week_start"]
            ).dt.strftime("%b %d")

            chart_df = (
                history_df[
                    [
                        "Week",
                        "quantity_sold",
                        "deseasonalized_quantity"
                    ]
                ]
                .rename(
                    columns={
                        "quantity_sold": "Jars sold",
                        "deseasonalized_quantity": "Without seasonal effect"
                    }
                )
                .melt(
                    id_vars=["Week"],
                    var_name="Series",
                    value_name="Jars"
                )
            )

            history_chart = px.line(
                chart_df,
                x="Week",
                y="Jars",
                color="Series",
                markers=True,
                color_discrete_map={
                    "Jars sold": NC_STATE_RED,
                    "Without seasonal effect": NEUTRAL_SERIES
                }
            )

            history_chart.update_yaxes(title_text="Jars per week")

            st.plotly_chart(
                style_chart(
                    history_chart,
                    height=360,
                    show_legend=True
                ),
                **STRETCH
            )

            st.caption(
                "The gray line removes the seasonal effect: each "
                "week is divided by its month's seasonal factor "
                "before the baseline is calculated."
            )

    if result is None:

        if problem and "Monday" in problem:

            st.error(problem)

        return

    # ========================================================
    # FORECAST RESULT
    # ========================================================

    st.write("")

    section_label("Forecast Result")

    baseline = float(result["baseline_forecast_quantity"])

    factor = float(result["seasonal_factor"])

    forecast = float(result["saved_forecast_quantity"])

    result1, result2, result3 = st.columns(3)

    with result1:

        st.metric(
            "Baseline Demand",
            f"{baseline:,.1f} jars"
        )

    with result2:

        st.metric(
            f"{result['demand_tier']} Season "
            f"({state.forecast_week.strftime('%B')})",
            f"{factor:.2f}×"
        )

    with result3:

        st.metric(
            "Forecast for the Week",
            f"{forecast:,.0f} jars"
        )

    st.markdown(
        (
            '<div class="forecast-formula">'
            f'Baseline <strong>{baseline:,.1f}</strong> jars'
            '&nbsp;&nbsp;×&nbsp;&nbsp;'
            f'Seasonal factor <strong>{factor:.2f}</strong>'
            '&nbsp;&nbsp;=&nbsp;&nbsp;'
            f'Forecast <strong>{forecast:,.0f}</strong> jars'
            '</div>'
        ),
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # STOCK VS FORECAST
    #
    # Only meaningful when the forecast covers ALL demand
    # for the product.
    # --------------------------------------------------------

    if (
        state.forecast_region == "ALL"
        and state.forecast_channel == "ALL"
        and forecast > 0
    ):

        stock = quantity_by_product[state.forecast_product_id]

        st.caption(
            f"Current stock of "
            f"{name_by_product[state.forecast_product_id]}: "
            f"{stock:,} jars, about {stock / forecast:.1f} weeks "
            "at this rate."
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    saved = find_saved_forecast(
        product_id=state.forecast_product_id,
        forecast_week=state.forecast_week,
        sales_region=state.forecast_region,
        sales_channel=state.forecast_channel
    )

    if saved is not None:

        st.info(
            f"A forecast for this week is already saved "
            f"(Forecast ID {saved['forecast_id']}): "
            f"{float(saved['saved_forecast_quantity']):,.0f} jars. "
            "Saved forecasts are never changed, so they can be "
            "compared fairly with actual sales."
        )

    else:

        st.button(
            "Save Forecast",
            type="primary",
            on_click=_save_forecast,
            key="forecast_save_button",
            **STRETCH
        )

        st.caption(
            "Saving keeps this number unchanged. After the week "
            "ends, the Accuracy tab compares it with actual sales."
        )

    # --------------------------------------------------------
    # CALCULATION DETAIL
    # --------------------------------------------------------

    with st.expander("View the weekly calculation"):

        detail_df = history_df[
            [
                "week_start",
                "quantity_sold",
                "seasonal_factor",
                "deseasonalized_quantity"
            ]
        ].copy()

        detail_df["week_start"] = pd.to_datetime(
            detail_df["week_start"]
        ).dt.strftime("%b %d, %Y")

        detail_df["seasonal_factor"] = (
            detail_df["seasonal_factor"].astype(float)
        )

        detail_df = detail_df.rename(
            columns={
                "week_start": "Week",
                "quantity_sold": "Jars Sold",
                "seasonal_factor": "Seasonal Factor",
                "deseasonalized_quantity": "Without Seasonal Effect"
            }
        )

        st.dataframe(
            detail_df,
            hide_index=True,
            column_config={
                "Jars Sold": st.column_config.NumberColumn(
                    format="%.0f"
                ),
                "Seasonal Factor": st.column_config.NumberColumn(
                    format="%.2f"
                ),
                "Without Seasonal Effect": st.column_config.NumberColumn(
                    format="%.1f"
                )
            },
            **STRETCH
        )


# ============================================================
# ACCURACY TAB
# ============================================================

def _render_accuracy():
    """
    Draw the Accuracy tab.
    """

    section_label("Forecast Performance")

    header_left, header_right = st.columns(
        [3, 1],
        vertical_alignment="center"
    )

    with header_left:

        st.subheader("Forecast vs Actual")

        st.caption(
            "Compare each saved forecast with the jars actually "
            "sold in that week."
        )

    with header_right:

        if st.button(
            "Update Actuals",
            key="update_forecasts",
            **STRETCH
        ):

            updated = update_completed_forecasts()

            if len(updated) > 0:

                st.success(
                    f"{len(updated)} forecast(s) updated."
                )

            else:

                st.info(
                    "No finished forecast weeks need updating."
                )

    accuracy = get_forecast_vs_actual()

    if len(accuracy) > 0:

        accuracy_df = pd.DataFrame(accuracy)

        for column in ("forecast_quantity", "actual_quantity", "difference"):

            accuracy_df[column] = accuracy_df[column].astype(float)

        accuracy_df["Week"] = pd.to_datetime(
            accuracy_df["forecast_week"]
        ).dt.strftime("%b %d, %Y")

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        a1, a2, a3 = st.columns(3)

        with a1:

            st.metric(
                "Completed Forecasts",
                len(accuracy_df)
            )

        with a2:

            st.metric(
                "Average Difference",
                f"{accuracy_df['difference'].mean():+.1f} jars",
                help="Actual minus forecast. Negative = sold less than forecast."
            )

        with a3:

            st.metric(
                "Mean Absolute Error",
                f"{accuracy_df['difference'].abs().mean():.1f} jars",
                help="Average size of the miss, ignoring its direction."
            )

        st.write("")

        # ----------------------------------------------------
        # CHART
        #
        # Each forecast gets its own label (week + segment), so
        # two forecasts for the same week are never stacked.
        # ----------------------------------------------------

        accuracy_df["Label"] = (
            accuracy_df["Week"]
            + "<br>"
            + accuracy_df["product_name"]
            + "<br>"
            + accuracy_df["sales_region"]
            + " · "
            + accuracy_df["sales_channel"]
        )

        comparison_df = (
            accuracy_df[
                [
                    "Label",
                    "forecast_quantity",
                    "actual_quantity"
                ]
            ]
            .rename(
                columns={
                    "forecast_quantity": "Forecast",
                    "actual_quantity": "Actual"
                }
            )
            .melt(
                id_vars=["Label"],
                var_name="Series",
                value_name="Jars"
            )
        )

        comparison_chart = px.bar(
            comparison_df,
            x="Label",
            y="Jars",
            color="Series",
            barmode="group",
            text="Jars",
            color_discrete_map={
                "Forecast": NEUTRAL_SERIES,
                "Actual": NC_STATE_RED
            }
        )

        comparison_chart.update_traces(
            texttemplate="%{text:,.0f}",
            textposition="outside",
            cliponaxis=False
        )

        comparison_chart.update_yaxes(title_text="Jars")

        st.plotly_chart(
            style_chart(
                comparison_chart,
                height=380,
                show_legend=True
            ),
            **STRETCH
        )

        # ----------------------------------------------------
        # TABLE
        # ----------------------------------------------------

        display_accuracy = accuracy_df[
            [
                "Week",
                "product_name",
                "sales_region",
                "sales_channel",
                "forecast_quantity",
                "actual_quantity",
                "difference"
            ]
        ].rename(
            columns={
                "product_name": "Product",
                "sales_region": "County",
                "sales_channel": "Channel",
                "forecast_quantity": "Forecast",
                "actual_quantity": "Actual",
                "difference": "Difference"
            }
        )

        st.dataframe(
            display_accuracy,
            hide_index=True,
            column_config={
                "Forecast": st.column_config.NumberColumn(format="%.0f"),
                "Actual": st.column_config.NumberColumn(format="%.0f"),
                "Difference": st.column_config.NumberColumn(format="%+.0f")
            },
            **STRETCH
        )

    else:

        st.info(
            "No completed forecast comparisons are available yet. "
            "Save a forecast, and after that week ends click "
            "Update Actuals."
        )

    st.divider()

    # ========================================================
    # SAVED FORECASTS
    # ========================================================

    section_label("Forecast History")

    st.subheader("Saved Forecasts")

    saved = get_saved_forecasts()

    if len(saved) == 0:

        st.info("No forecasts have been saved yet.")

        return

    saved_df = pd.DataFrame(saved)

    saved_df["forecast_week"] = pd.to_datetime(
        saved_df["forecast_week"]
    ).dt.strftime("%b %d, %Y")

    for column in (
        "baseline_forecast_quantity",
        "seasonal_factor",
        "saved_forecast_quantity",
        "actual_quantity",
        "forecast_error",
        "smoothing_factor"
    ):

        saved_df[column] = saved_df[column].astype(float)

    saved_df = saved_df.rename(
        columns={
            "forecast_id": "Forecast ID",
            "forecast_week": "Week",
            "product_name": "Product",
            "sales_region": "County",
            "sales_channel": "Channel",
            "baseline_forecast_quantity": "Baseline",
            "demand_tier": "Demand Tier",
            "seasonal_factor": "Seasonal Factor",
            "saved_forecast_quantity": "Forecast",
            "actual_quantity": "Actual",
            "forecast_error": "Difference",
            "smoothing_factor": "Alpha"
        }
    )

    st.dataframe(
        saved_df,
        hide_index=True,
        column_config={
            "Baseline": st.column_config.NumberColumn(format="%.1f"),
            "Seasonal Factor": st.column_config.NumberColumn(format="%.2f"),
            "Forecast": st.column_config.NumberColumn(format="%.0f"),
            "Actual": st.column_config.NumberColumn(format="%.0f"),
            "Difference": st.column_config.NumberColumn(format="%+.0f"),
            "Alpha": st.column_config.NumberColumn(format="%.2f")
        },
        **STRETCH
    )

    st.caption(
        "Actual and Difference stay empty until the forecast week "
        "has ended."
    )


# ============================================================
# SEASONAL SETTINGS: CALLBACK
# ============================================================

def _save_seasonality():
    """
    Save the months that were changed in the table.
    """

    state = st.session_state

    changed_rows = state.get("seasonality_pending", [])

    try:

        for row in changed_rows:

            update_seasonality(
                month_number=row["month_number"],
                demand_tier=row["demand_tier"],
                seasonal_factor=row["seasonal_factor"],
                notes=row["notes"]
            )

    except Exception as error:

        set_flash(
            "seasonality",
            "error",
            f"Could not update seasonal settings: {error}"
        )

        return

    set_flash(
        "seasonality",
        "success",
        "Seasonal settings updated for "
        + ", ".join(row["month_name"] for row in changed_rows)
        + ". New forecasts use the new values. Saved forecasts "
        "keep the values they were created with."
    )

    # Give the table a new key so it is rebuilt from the database
    # and the old edits are forgotten.
    state["seasonality_table_version"] = (
        state.get("seasonality_table_version", 0) + 1
    )


# ============================================================
# SEASONAL SETTINGS TAB
# ============================================================

def _render_seasonal_settings():
    """
    Draw the Seasonal Settings tab.

    All 12 months are edited directly in one table.
    """

    show_flash("seasonality")

    section_label("Seasonal Demand Assumptions")

    st.subheader("Monthly Seasonal Factors")

    st.caption(
        "1.00 = normal demand. 1.20 = 20% above normal. "
        "0.80 = 20% below normal. Click a cell to change it, "
        "then click Save Seasonal Settings."
    )

    seasonality = get_all_seasonality()

    original_df = pd.DataFrame(
        [
            {
                "month_number": setting["month_number"],
                "Month": setting["month_name"],
                "Demand Tier": setting["demand_tier"],
                "Seasonal Factor": float(setting["seasonal_factor"]),
                "Notes": setting["notes"] or ""
            }
            for setting in seasonality
        ]
    )

    edited_df = st.data_editor(
        original_df,
        hide_index=True,
        num_rows="fixed",
        disabled=["Month"],
        column_order=[
            "Month",
            "Demand Tier",
            "Seasonal Factor",
            "Notes"
        ],
        column_config={
            "Demand Tier": st.column_config.SelectboxColumn(
                options=DEMAND_TIERS,
                required=True
            ),
            "Seasonal Factor": st.column_config.NumberColumn(
                min_value=0.10,
                max_value=3.00,
                step=0.05,
                format="%.2f",
                required=True
            ),
            "Notes": st.column_config.TextColumn()
        },
        # Tall enough to show all 12 months without scrolling.
        height=460,

        # The number at the end changes after every save
        # (see _save_seasonality).
        key=(
            "seasonality_editor_"
            f"{st.session_state.get('seasonality_table_version', 0)}"
        ),
        **STRETCH
    )

    # --------------------------------------------------------
    # FIND THE MONTHS THAT WERE CHANGED
    # --------------------------------------------------------

    changed_rows = []

    for index in range(len(original_df)):

        before = original_df.iloc[index]

        after = edited_df.iloc[index]

        after_notes = after["Notes"] if isinstance(after["Notes"], str) else ""

        if (
            before["Demand Tier"] != after["Demand Tier"]
            or abs(
                float(before["Seasonal Factor"])
                - float(after["Seasonal Factor"])
            ) > 0.0005
            or before["Notes"] != after_notes
        ):

            changed_rows.append(
                {
                    "month_number": int(before["month_number"]),
                    "month_name": before["Month"],
                    "demand_tier": after["Demand Tier"],
                    "seasonal_factor": float(after["Seasonal Factor"]),
                    "notes": after_notes.strip() or None
                }
            )

    if len(changed_rows) > 0:

        st.warning(
            "Not saved yet: "
            + ", ".join(row["month_name"] for row in changed_rows)
            + "."
        )

    # The callback below reads the changed months from here.
    st.session_state["seasonality_pending"] = changed_rows

    st.button(
        "Save Seasonal Settings",
        type="primary",
        disabled=(len(changed_rows) == 0),
        on_click=_save_seasonality,
        key="seasonality_save_button"
    )


# ============================================================
# FORECAST PAGE
# ============================================================

def render_forecast():
    """
    Draw the Demand Forecast page.
    """

    page_header(
        "Demand Forecast",
        "Use past sales and seasonal adjustments to plan how "
        "many jars will be needed."
    )

    try:

        inventory = get_current_inventory()

        filter_options = get_forecast_filter_options()

        forecast_tab, accuracy_tab, seasonality_tab = st.tabs(
            [
                "Create Forecast",
                "Accuracy",
                "Seasonal Settings"
            ]
        )

        with forecast_tab:

            _render_create_forecast(inventory, filter_options)

        with accuracy_tab:

            _render_accuracy()

        with seasonality_tab:

            _render_seasonal_settings()

    except Exception as error:

        st.error(f"Could not load forecast page: {error}")
