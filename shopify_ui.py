"""
shopify_ui.py

Purpose:
Render the Shopify page (sidebar: Settings -> Shopify).

Sections:

1. Connection status and the two actions:
   Test Shopify Connection / Sync New Orders.
2. Demo Order Preview: how a real Shopify order would be
   processed.
3. Product Mapping (collapsed): connect Shopify variants to
   local products.
4. Synchronization History (collapsed).

Important:
Demo data is never inserted into sales.
Live Shopify order import remains intentionally disabled
until real store credentials are available and verified.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from shopify_service import (
    get_shopify_configuration_status,
    test_shopify_connection
)

from shopify_sync_service import (
    deactivate_shopify_product_mapping,
    get_demo_shopify_preview,
    get_last_successful_shopify_sync,
    get_shopify_mapping_rows,
    get_shopify_product_mappings,
    get_shopify_sync_history,
    reactivate_shopify_product_mapping,
    run_shopify_sync_check,
    save_shopify_product_mapping,
    STORE_PRODUCT_CONTENTS
)

from ui_helpers import (
    STRETCH,
    calc_rows,
    format_currency,
    page_header,
    section_label,
    status_badge
)


# ============================================================
# FORMAT HELPER
# ============================================================

def format_datetime(value):
    """
    Format a datetime for display.
    """

    if value is None:

        return "Never"

    if isinstance(value, str):

        try:

            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        except ValueError:

            return value

    return value.strftime("%b %d, %Y %I:%M %p")


# ============================================================
# SHOPIFY PAGE
# ============================================================

def render_shopify_page():
    """
    Draw the Shopify page.
    """

    page_header(
        "Shopify",
        "Online orders can be brought in automatically and passed "
        "through the same sales, scholarship and inventory steps "
        "as a sale entered by hand."
    )

    try:

        configuration = get_shopify_configuration_status()

        last_successful_sync = get_last_successful_shopify_sync()

        active_mappings = get_shopify_product_mappings()

        # ====================================================
        # CONNECTION STATUS
        # ====================================================

        section_label("Connection")

        status_column, action_column = st.columns(
            [1.5, 1],
            gap="large"
        )

        with status_column:

            with st.container(border=True):

                if configuration["configured"]:

                    connection_badge = status_badge(
                        "Credentials configured",
                        "green"
                    )

                else:

                    connection_badge = status_badge(
                        "Not connected",
                        "gray"
                    )

                if last_successful_sync is None:

                    last_sync_text = "Never"

                else:

                    last_sync_text = format_datetime(
                        last_successful_sync["completed_at"]
                    )

                calc_rows(
                    "Status",
                    [
                        ("Shopify connection", connection_badge),
                        ("Store", configuration["store"]),
                        (
                            "Products connected to Shopify",
                            str(len(active_mappings))
                        ),
                        ("Last successful sync", last_sync_text)
                    ]
                )

        with action_column:

            test_clicked = st.button(
                "Test Shopify Connection",
                key="shopify_test_connection",
                **STRETCH
            )

            sync_clicked = st.button(
                "Sync New Orders",
                type="primary",
                key="shopify_sync_orders",
                **STRETCH
            )

            st.caption(
                "Prototype: orders are checked and previewed. "
                "Saving live orders stays switched off until the "
                "store credentials are provided and verified."
            )

        if not configuration["configured"]:

            st.info(
                "Shopify API credentials have not been provided yet. "
                "The integration is built and ready: once the store "
                "name and access token are added to the .env file, "
                "this page can talk to the live Shopify store."
            )

        # ====================================================
        # TEST CONNECTION
        # ====================================================

        if test_clicked:

            result = test_shopify_connection()

            if result["success"]:

                st.success(
                    "Connected successfully to "
                    f"{result.get('shop_name')} "
                    f"({result.get('shop_domain')})."
                )

            elif not result["configured"]:

                st.warning(
                    "The connection cannot be tested because the "
                    "Shopify credentials have not been added yet."
                )

            else:

                st.error(result["message"])

        # ====================================================
        # SYNC CHECK
        # ====================================================

        if sync_clicked:

            result = run_shopify_sync_check()

            if result["success"]:

                st.success(result["message"])

                result1, result2, result3 = st.columns(3)

                with result1:

                    st.metric(
                        "Orders Found",
                        result.get("orders_found", 0)
                    )

                with result2:

                    st.metric(
                        "Ready for Import",
                        result.get("orders_ready", 0)
                    )

                with result3:

                    st.metric(
                        "Already Imported",
                        result.get("orders_skipped", 0)
                    )

            elif not result["configured"]:

                st.warning(
                    "Orders cannot be synchronized because the "
                    "Shopify credentials have not been added yet. "
                    "The attempt was recorded in the "
                    "synchronization history."
                )

            else:

                st.error(result["message"])

        st.divider()

        # ====================================================
        # DEMO ORDER PREVIEW
        # ====================================================

        section_label("Demo Order Preview")

        st.markdown(
            status_badge("DEMO DATA — NOT IMPORTED", "red"),
            unsafe_allow_html=True
        )

        st.caption(
            "Shows how a real Shopify order would be processed. "
            "This demo order is never saved."
        )

        preview = get_demo_shopify_preview()

        demo1, demo2, demo3, demo4, demo5 = st.columns(5)

        with demo1:

            st.metric(
                "Product Revenue",
                format_currency(preview["product_revenue"])
            )

        with demo2:

            st.metric(
                "Tax Collected",
                format_currency(preview["tax_collected"])
            )

        with demo3:

            st.metric(
                "Shipping Revenue",
                format_currency(preview["shipping_revenue"])
            )

        with demo4:

            st.metric(
                "Shopify Fee",
                format_currency(preview["shopify_fee"])
            )

        with demo5:

            st.metric(
                "Scholarship",
                format_currency(preview["total_scholarship"])
            )

        st.caption(
            "The Shopify fee is read from the order's Shopify "
            "Payments transaction, so it no longer has to be looked "
            "up by hand. Orders paid through another payment provider "
            "have no fee in Shopify and show $0.00."
        )

        item_rows = []

        for item in preview["items"]:

            scholarship_rate = item["scholarship_rate"]

            item_rows.append(
                {
                    "Shopify Product": item["shopify_product"],
                    "Sauce": item["local_product"],
                    "Jars": item["quantity"],
                    "Revenue": float(item["allocated_revenue"]),
                    "Scholarship Rate": (
                        f"{float(scholarship_rate) * 100:.0f}%"
                        if scholarship_rate is not None
                        else "Not connected"
                    ),
                    "Scholarship": (
                        float(item["scholarship_amount"])
                        if item["scholarship_amount"] is not None
                        else None
                    ),
                    "Inventory Change": item["inventory_change"]
                }
            )

        st.dataframe(
            pd.DataFrame(item_rows),
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
            "When live import is switched on, each order is checked "
            "for duplicates, matched to local products, saved as a "
            "sale, and the scholarship and inventory are updated "
            "automatically."
        )

        st.divider()

        # ====================================================
        # SETUP (COLLAPSED)
        # ====================================================

        section_label("Setup")

        # ----------------------------------------------------
        # PRODUCT MAPPING
        # ----------------------------------------------------

        with st.expander("Connect Shopify products to local products"):

            st.caption(
                "Each Shopify product must be connected before its "
                "orders can be imported. The connection says how many "
                "jars of each sauce ONE unit holds, so a 2-jar pack "
                "lowers inventory by 2 and a Combo is split $9 / $9 "
                "between the sauces. The Variant ID comes from the "
                "Shopify store."
            )

            with st.form("shopify_mapping_form", clear_on_submit=True):

                mapping_col1, mapping_col2 = st.columns(2)

                with mapping_col1:

                    variant_id = st.text_input(
                        "Shopify Variant ID",
                        placeholder="gid://shopify/ProductVariant/123456789"
                    )

                with mapping_col2:

                    # The five products of Dr. D's store.
                    selected_contents = st.selectbox(
                        "What one unit holds",
                        list(STORE_PRODUCT_CONTENTS.keys())
                    )

                shopify_product_name = st.text_input(
                    "Shopify Product Name",
                    placeholder="Optional. Shown in this list only."
                )

                mapping_submit = st.form_submit_button(
                    "Save Product Connection",
                    type="primary"
                )

            if mapping_submit:

                try:

                    original_jars, slobberin_jars = (
                        STORE_PRODUCT_CONTENTS[selected_contents]
                    )

                    mapping_result = save_shopify_product_mapping(
                        shopify_variant_id=variant_id,
                        original_jars=original_jars,
                        slobberin_jars=slobberin_jars,
                        shopify_product_name=shopify_product_name
                    )

                    st.success(
                        "Shopify variant connected: one unit = "
                        f"{mapping_result['local_product']}."
                    )

                except Exception as error:

                    st.error(f"Could not save: {error}")

            mapping_rows = get_shopify_mapping_rows(
                include_inactive=True
            )

            if len(mapping_rows) == 0:

                st.info(
                    "No Shopify products have been connected yet. "
                    "The real Variant IDs become available once the "
                    "store is connected."
                )

            else:

                mapping_df = pd.DataFrame(mapping_rows)

                st.dataframe(
                    mapping_df[
                        [
                            "shopify_variant_id",
                            "shopify_product_name",
                            "local_product",
                            "active",
                            "updated_at"
                        ]
                    ].rename(
                        columns={
                            "shopify_variant_id": "Shopify Variant ID",
                            "shopify_product_name": "Shopify Product",
                            "local_product": "One Unit Holds",
                            "active": "Active",
                            "updated_at": "Last Updated"
                        }
                    ),
                    hide_index=True,
                    **STRETCH
                )

                mapping_options = {
                    (
                        f"{row['shopify_variant_id']} "
                        f"→ {row['local_product']}"
                    ): row
                    for row in mapping_rows
                }

                selected_mapping_label = st.selectbox(
                    "Connection to switch on or off",
                    list(mapping_options.keys()),
                    key="mapping_status_selection"
                )

                selected_mapping = mapping_options[
                    selected_mapping_label
                ]

                action_left, action_right = st.columns(2)

                with action_left:

                    if st.button(
                        "Switch On",
                        key="activate_shopify_mapping",
                        **STRETCH
                    ):

                        try:

                            reactivate_shopify_product_mapping(
                                selected_mapping["shopify_variant_id"]
                            )

                            st.rerun()

                        except Exception as error:

                            st.error(f"Could not switch on: {error}")

                with action_right:

                    if st.button(
                        "Switch Off",
                        key="deactivate_shopify_mapping",
                        **STRETCH
                    ):

                        try:

                            deactivate_shopify_product_mapping(
                                selected_mapping["shopify_variant_id"]
                            )

                            st.rerun()

                        except Exception as error:

                            st.error(f"Could not switch off: {error}")

        # ----------------------------------------------------
        # SYNCHRONIZATION HISTORY
        # ----------------------------------------------------

        with st.expander("Synchronization history"):

            history = get_shopify_sync_history(limit=10)

            if len(history) == 0:

                st.info(
                    "No synchronization attempts have been "
                    "recorded yet."
                )

            else:

                history_df = pd.DataFrame(history)

                for column in ("started_at", "completed_at"):

                    history_df[column] = history_df[column].apply(
                        format_datetime
                    )

                # "FAILED" here usually only means "not connected yet".
                history_df["status"] = history_df["status"].map(
                    {
                        "STARTED": "Started",
                        "SUCCESS": "Completed",
                        "PARTIAL": "Partly completed",
                        "FAILED": "Not completed"
                    }
                ).fillna(history_df["status"])

                st.dataframe(
                    history_df.rename(
                        columns={
                            "sync_id": "Sync #",
                            "started_at": "Started",
                            "completed_at": "Finished",
                            "status": "Result",
                            "orders_found": "Orders Found",
                            "orders_imported": "Imported",
                            "orders_skipped": "Skipped",
                            "orders_failed": "Failed",
                            "message": "Message"
                        }
                    ),
                    hide_index=True,
                    **STRETCH
                )

    except Exception as error:

        st.error(f"Could not load the Shopify page: {error}")
