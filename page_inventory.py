"""
page_inventory.py

Purpose:
Render the Inventory page.

Sections:

1. Current Inventory
   Jars, estimated value and weeks of supply per product.

2. Inventory Actions
   - Receive Batch     jars arrive from the co-packer
   - Count Inventory   compare the system with a physical count
   - Other Movement    samples, donations, broken jars, gifts,
                       replacement shipments

3. Where the Jars Went
   The inventory equation in numbers.

4. Inventory Report (Excel)

5. Audit Trail
   Batch history and every inventory movement.
"""

from datetime import date

import pandas as pd
import streamlit as st

from inventory_service import (
    TRANSACTION_LABELS,
    get_current_inventory,
    get_inventory_batches,
    get_inventory_movement_summary,
    get_inventory_reconciliation,
    get_inventory_transactions,
    receive_batch,
    record_inventory_adjustment,
    record_physical_count
)

from ui_helpers import (
    STRETCH,
    XLSX_MIME,
    cached_inventory_report,
    calc_rows,
    describe_supply,
    format_currency,
    get_data_version,
    get_weeks_of_supply,
    page_header,
    section_label,
    set_flash,
    show_flash
)


# ============================================================
# REASONS FOR A NON-SALE MOVEMENT
#
# All of them REMOVE jars from inventory.
#
# A difference found during a physical count is recorded on
# the "Count Inventory" tab instead.
# ============================================================

MOVEMENT_REASONS = {
    "Sample": "SAMPLE",
    "Donation": "DONATION",
    "Broken / Damaged": "BROKEN",
    "Gift": "GIFT",
    "Replacement Shipment": "REPLACEMENT"
}


# ============================================================
# COUNT INVENTORY: CALLBACK
# ============================================================

def _save_physical_count():
    """
    Save the physical count entered on the Count Inventory tab.
    """

    state = st.session_state

    product_id = state.count_product_id

    quantity_key = f"count_quantity_{product_id}"

    try:

        result = record_physical_count(
            product_id=product_id,
            count_date=state.count_date,
            counted_quantity=state[quantity_key],
            notes=state.get("count_notes", "")
        )

    except Exception as error:

        set_flash(
            "inventory",
            "error",
            f"Could not save the count: {error}"
        )

        return

    if result["matched"]:

        message = (
            f"{result['product_name']}: the count matches the "
            f"system ({result['counted_quantity']:,} jars). "
            "Nothing was changed."
        )

    else:

        message = (
            f"{result['product_name']}: system showed "
            f"{result['system_quantity']:,}, counted "
            f"{result['counted_quantity']:,}. "
            f"Inventory was corrected by {result['difference']:+,} "
            "jars and the correction was added to the audit trail."
        )

    set_flash("inventory", "success", message)

    # Forget the typed values so the field shows the new
    # system balance on the next draw.
    for key in (quantity_key, "count_notes"):

        if key in state:

            del state[key]


# ============================================================
# INVENTORY PAGE
# ============================================================

def render_inventory():
    """
    Draw the Inventory page.
    """

    page_header(
        "Inventory",
        "Monitor current stock, receive batches, check a physical "
        "count, and record every jar that leaves without a sale."
    )

    try:

        inventory = get_current_inventory()

        data_version = get_data_version()

        product_options = {
            item["product_name"]: item["product_id"]
            for item in inventory
        }

        quantity_by_product = {
            item["product_id"]: int(item["current_quantity"])
            for item in inventory
        }

        name_by_product = {
            item["product_id"]: item["product_name"]
            for item in inventory
        }

        show_flash("inventory")

        # ====================================================
        # CURRENT INVENTORY
        # ====================================================

        section_label("Current Inventory")

        product_columns = st.columns(len(inventory))

        total_jars = 0

        total_value = 0.0

        for index, item in enumerate(inventory):

            quantity = int(item["current_quantity"])

            total_jars += quantity

            # Value = jars x unit cost stored in the products table.
            total_value += float(item["estimated_value"])

            supply = get_weeks_of_supply(
                item["product_id"],
                quantity,
                data_version
            )

            with product_columns[index]:

                st.metric(
                    item["product_name"],
                    f"{quantity:,} jars"
                )

                st.caption(describe_supply(supply))

        summary1, summary2 = st.columns(2)

        with summary1:

            st.metric(
                "Total Jars Available",
                f"{total_jars:,}"
            )

        with summary2:

            st.metric(
                "Estimated Inventory Value",
                format_currency(total_value)
            )

        unit_costs = sorted(
            {
                format_currency(item["unit_cost"])
                for item in inventory
            }
        )

        st.caption(
            "Inventory value = jars × cost per jar "
            f"({', '.join(unit_costs)}). "
            "Weeks of supply uses next week's expected demand "
            "across all channels."
        )

        # ----------------------------------------------------
        # BALANCE VS AUDIT TRAIL
        # ----------------------------------------------------

        unbalanced = [
            row
            for row in get_inventory_reconciliation()
            if not row["balanced"]
        ]

        if len(unbalanced) == 0:

            st.caption(
                "✓ Every balance agrees with the inventory "
                "audit trail."
            )

        else:

            for row in unbalanced:

                st.warning(
                    f"{row['product_name']}: the balance is "
                    f"{row['current_quantity']:,} jars but the audit "
                    f"trail adds up to {row['ledger_quantity']:,} "
                    f"(difference {row['difference']:+,}). "
                    "The balance was changed without an audit record."
                )

        st.divider()

        # ====================================================
        # INVENTORY ACTIONS
        # ====================================================

        section_label("Inventory Actions")

        receive_tab, count_tab, movement_tab = st.tabs(
            [
                "Receive Batch",
                "Count Inventory",
                "Other Movement"
            ]
        )

        # ----------------------------------------------------
        # RECEIVE BATCH
        # ----------------------------------------------------

        with receive_tab:

            st.caption(
                "Use this when finished jars arrive from the "
                "manufacturer or co-packer."
            )

            with st.form("receive_batch_form", clear_on_submit=True):

                row1_left, row1_right = st.columns(2)

                with row1_left:

                    selected_product = st.selectbox(
                        "Product",
                        list(product_options.keys()),
                        key="batch_product"
                    )

                with row1_right:

                    quantity_received = st.number_input(
                        "Quantity Received (jars)",
                        min_value=1,
                        value=100,
                        step=1,
                        key="batch_quantity"
                    )

                row2_left, row2_right = st.columns(2)

                with row2_left:

                    received_date = st.date_input(
                        "Received Date",
                        value=date.today(),
                        key="batch_date"
                    )

                with row2_right:

                    batch_code = st.text_input(
                        "Batch Code",
                        placeholder="Example: SS-BATCH-2026-11",
                        key="batch_code"
                    )

                manufacturer = st.text_input(
                    "Manufacturer / Co-Packer",
                    placeholder="Optional",
                    key="batch_manufacturer"
                )

                batch_notes = st.text_area(
                    "Notes",
                    placeholder=(
                        "Optional production, delivery, "
                        "or quality notes."
                    ),
                    key="batch_notes"
                )

                receive_submit = st.form_submit_button(
                    "Receive Batch",
                    type="primary"
                )

            if receive_submit:

                try:

                    result = receive_batch(
                        product_id=product_options[selected_product],
                        batch_code=batch_code,
                        received_date=received_date,
                        quantity_received=quantity_received,
                        manufacturer=(
                            manufacturer
                            if manufacturer.strip()
                            else None
                        ),
                        notes=(
                            batch_notes
                            if batch_notes.strip()
                            else None
                        )
                    )

                    set_flash(
                        "inventory",
                        "success",
                        f"{quantity_received:,} jars of "
                        f"{selected_product} were received "
                        f"(batch {result['batch_code']}). "
                        f"New balance: "
                        f"{result['new_inventory_quantity']:,} jars."
                    )

                    st.rerun()

                except Exception as error:

                    st.error(f"Could not receive batch: {error}")

        # ----------------------------------------------------
        # COUNT INVENTORY
        #
        # No st.form here: the difference is shown immediately
        # while the counted number is typed.
        # ----------------------------------------------------

        with count_tab:

            st.caption(
                "Count the jars on the shelf and enter the number. "
                "The system shows the difference and corrects "
                "the balance."
            )

            count_left, count_right = st.columns(
                [1.4, 1],
                gap="large"
            )

            with count_left:

                with st.container(border=True):

                    count_row1, count_row2 = st.columns(2)

                    with count_row1:

                        st.selectbox(
                            "Product",
                            list(name_by_product.keys()),
                            format_func=lambda product_id: (
                                name_by_product[product_id]
                            ),
                            key="count_product_id"
                        )

                    with count_row2:

                        st.date_input(
                            "Count Date",
                            value=date.today(),
                            key="count_date"
                        )

                    count_product_id = st.session_state.count_product_id

                    system_quantity = quantity_by_product[
                        count_product_id
                    ]

                    # One field per product. It starts at the
                    # system balance, so "no difference" is the
                    # default.
                    quantity_key = f"count_quantity_{count_product_id}"

                    st.session_state.setdefault(
                        quantity_key,
                        system_quantity
                    )

                    st.number_input(
                        "Jars Counted",
                        min_value=0,
                        step=1,
                        key=quantity_key
                    )

                    st.text_input(
                        "Notes",
                        placeholder="Optional. Example: counted in the garage.",
                        key="count_notes"
                    )

            with count_right:

                counted_quantity = st.session_state[quantity_key]

                difference = counted_quantity - system_quantity

                with st.container(border=True):

                    calc_rows(
                        name_by_product[count_product_id],
                        [
                            (
                                "System balance",
                                f"{system_quantity:,} jars"
                            ),
                            (
                                "Physical count",
                                f"{counted_quantity:,} jars"
                            ),
                            (
                                "Difference",
                                f"{difference:+,} jars",
                                "strong"
                            )
                        ]
                    )

                    if difference == 0:

                        st.success("The count matches the system.")

                    elif difference < 0:

                        st.warning(
                            f"{abs(difference):,} jars are missing. "
                            "Saving will reduce the balance."
                        )

                    else:

                        st.warning(
                            f"{difference:,} more jars than expected. "
                            "Saving will increase the balance."
                        )

                st.button(
                    "Save Count",
                    type="primary",
                    on_click=_save_physical_count,
                    key="count_save_button",
                    **STRETCH
                )

        # ----------------------------------------------------
        # OTHER MOVEMENT
        # ----------------------------------------------------

        with movement_tab:

            st.caption(
                "Use this for samples, donations, damaged jars, "
                "gifts or replacement shipments. These remove jars "
                "from inventory without creating a sale."
            )

            with st.form("inventory_movement_form", clear_on_submit=True):

                row1_left, row1_right = st.columns(2)

                with row1_left:

                    movement_product = st.selectbox(
                        "Product",
                        list(product_options.keys()),
                        key="movement_product"
                    )

                with row1_right:

                    movement_reason = st.selectbox(
                        "Reason",
                        list(MOVEMENT_REASONS.keys()),
                        key="movement_reason"
                    )

                row2_left, row2_right = st.columns(2)

                with row2_left:

                    movement_date = st.date_input(
                        "Date",
                        value=date.today(),
                        key="movement_date"
                    )

                with row2_right:

                    movement_quantity = st.number_input(
                        "Jars Removed",
                        min_value=1,
                        value=1,
                        step=1,
                        key="movement_quantity"
                    )

                movement_notes = st.text_area(
                    "Notes",
                    placeholder="Example: 3 jars donated to NC State event.",
                    key="movement_notes"
                )

                movement_submit = st.form_submit_button(
                    "Record Movement",
                    type="primary"
                )

            if movement_submit:

                try:

                    result = record_inventory_adjustment(
                        product_id=product_options[movement_product],
                        transaction_date=movement_date,
                        transaction_type=MOVEMENT_REASONS[movement_reason],
                        quantity=movement_quantity,
                        notes=(
                            movement_notes
                            if movement_notes.strip()
                            else None
                        )
                    )

                    set_flash(
                        "inventory",
                        "success",
                        f"{movement_reason}: {movement_quantity:,} jars of "
                        f"{movement_product} removed. New balance: "
                        f"{result['new_inventory_quantity']:,} jars."
                    )

                    st.rerun()

                except Exception as error:

                    st.error(
                        f"Could not record inventory movement: {error}"
                    )

        st.divider()

        # ====================================================
        # WHERE THE JARS WENT
        # ====================================================

        section_label("Where the Jars Went")

        st.caption(
            "Received − sold − samples − donations … = jars on hand."
        )

        summary_rows = []

        for product in get_inventory_movement_summary():

            row = {"Product": product["product_name"]}

            for movement_type, label in TRANSACTION_LABELS.items():

                quantity = product["movements"].get(movement_type)

                if quantity is not None:

                    row[label] = quantity

            row["On Hand"] = product["current_quantity"]

            summary_rows.append(row)

        summary_df = pd.DataFrame(summary_rows)

        # Movement types that never happened are not shown.
        # A type used by only one product shows 0 for the other.
        movement_columns = [
            column
            for column in summary_df.columns
            if column not in ("Product", "On Hand")
        ]

        summary_df[movement_columns] = (
            summary_df[movement_columns]
            .fillna(0)
            .astype(int)
        )

        st.dataframe(
            summary_df[["Product"] + movement_columns + ["On Hand"]],
            hide_index=True,
            **STRETCH
        )

        st.divider()

        # ====================================================
        # INVENTORY REPORT
        # ====================================================

        section_label("Inventory Report")

        report_left, report_right = st.columns(
            [3, 1],
            vertical_alignment="center"
        )

        with report_left:

            st.subheader("Inventory Snapshot")

            st.write(
                "Download current inventory, manufacturer batch "
                "history, and the complete inventory movement "
                "audit trail."
            )

        with report_right:

            st.download_button(
                "Download Inventory Report",
                data=cached_inventory_report(
                    data_version,
                    date.today()
                ),
                file_name=(
                    "Dr_D_Inventory_Report_"
                    f"{date.today().strftime('%Y-%m-%d')}.xlsx"
                ),
                mime=XLSX_MIME,
                key="inventory_report_button",
                **STRETCH
            )

        st.divider()

        # ====================================================
        # AUDIT TRAIL
        # ====================================================

        section_label("Audit Trail")

        history_batch_tab, history_movement_tab = st.tabs(
            [
                "Batch History",
                "Inventory Movements"
            ]
        )

        with history_batch_tab:

            batches = get_inventory_batches()

            if len(batches) == 0:

                st.info(
                    "No manufacturer batches have been recorded."
                )

            else:

                batch_df = pd.DataFrame(batches)

                batch_df["received_date"] = pd.to_datetime(
                    batch_df["received_date"]
                ).dt.strftime("%b %d, %Y")

                batch_df = batch_df.rename(
                    columns={
                        "batch_id": "Batch ID",
                        "batch_code": "Batch Code",
                        "received_date": "Received",
                        "product_name": "Product",
                        "quantity_received": "Qty Received",
                        "manufacturer": "Manufacturer",
                        "notes": "Notes"
                    }
                )

                st.dataframe(
                    batch_df,
                    hide_index=True,
                    **STRETCH
                )

        with history_movement_tab:

            transactions = get_inventory_transactions(limit=100)

            if len(transactions) == 0:

                st.info(
                    "No inventory movements have been recorded."
                )

            else:

                movement_df = pd.DataFrame(transactions)

                movement_df["transaction_date"] = pd.to_datetime(
                    movement_df["transaction_date"]
                ).dt.strftime("%b %d, %Y")

                # Friendly names come from ONE shared list.
                movement_df["transaction_type"] = (
                    movement_df["transaction_type"]
                    .map(TRANSACTION_LABELS)
                    .fillna(movement_df["transaction_type"])
                )

                movement_df = movement_df.rename(
                    columns={
                        "transaction_id": "Movement ID",
                        "transaction_date": "Date",
                        "product_name": "Product",
                        "transaction_type": "Type",
                        "quantity_change": "Qty Change",
                        "batch_code": "Batch",
                        "sale_id": "Sale #",
                        "notes": "Notes"
                    }
                )

                st.dataframe(
                    movement_df,
                    hide_index=True,
                    **STRETCH
                )

                st.caption(
                    "The 100 most recent movements. Positive "
                    "quantities add jars, negative quantities remove "
                    "jars. Sale movements are created automatically."
                )

    except Exception as error:

        st.error(f"Could not load inventory: {error}")
