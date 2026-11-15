"""
page_record_sale.py

Purpose:
Render the Record Sale page.

Tabs:

1. Standard Sale
   One order or one sale. A Calculation Preview on the right
   shows the revenue split, scholarship, profit and inventory
   BEFORE anything is saved.

2. Market Summary
   Event totals entered once after a Farmers Market.
   Cash and card are recorded as two sales in one transaction.

3. Recent Sales
   The latest sales with jars, and "Cancel a sale" for an
   entry that was made by mistake.

How the live preview works:

The input fields are NOT inside st.form. Streamlit therefore
redraws the page after every change and the preview is
recalculated immediately.

The values are kept in st.session_state under the keys
std_* (Standard Sale) and mkt_* (Market Summary).

The "Record" buttons use callbacks. A callback runs before the
page is drawn again, which lets it save the sale, clear the
fields and leave a confirmation message for the next draw.
"""

from datetime import date

import pandas as pd
import streamlit as st

from sale_service import (
    get_recent_sales_with_items,
    preview_sale,
    record_market_summary,
    record_sale,
    suggest_product_revenue,
    void_sale
)

from scholarship_service import get_scholarship_rate

from ui_helpers import (
    STRETCH,
    calc_rows,
    describe_jars,
    format_currency,
    page_header,
    section_label,
    set_flash,
    show_flash
)


# ============================================================
# CHOICES
#
# These lists match the CHECK constraints created by
# sql/10_reporting_views_and_constraints.sql
# ============================================================

SALES_CHANNELS = [
    "Shopify",
    "Farmers Market",
    "Wholesale",
    "Direct"
]

PAYMENT_METHODS = [
    "Shopify",
    "Cash",
    "Card",
    "Venmo",
    "Other"
]

# Payment method selected automatically when the channel changes.
DEFAULT_PAYMENT = {
    "Shopify": "Shopify",
    "Farmers Market": "Cash",
    "Wholesale": "Other",
    "Direct": "Cash"
}


# ============================================================
# STANDARD SALE: STATE
# ============================================================

def _init_standard_state():
    """
    Give every Standard Sale field a starting value.

    setdefault() only writes a value when the key does not
    exist yet, so values typed by the user are never replaced.
    """

    state = st.session_state

    state.setdefault("std_original", 0)
    state.setdefault("std_slobberin", 0)
    state.setdefault("std_revenue", 0.0)
    state.setdefault("std_channel", SALES_CHANNELS[0])
    state.setdefault("std_payment", DEFAULT_PAYMENT[SALES_CHANNELS[0]])
    state.setdefault("std_date", date.today())
    state.setdefault("std_county", "Wake")
    state.setdefault("std_state", "NC")
    state.setdefault("std_tax", 0.0)
    state.setdefault("std_ship_revenue", 0.0)
    state.setdefault("std_fee", 0.0)
    state.setdefault("std_ship_expense", 0.0)

    # True  = revenue follows the standard price automatically.
    # False = Dr. D typed his own amount; do not overwrite it.
    state.setdefault("std_revenue_auto", True)


def _reset_standard_fields():
    """
    Clear the fields that belong to ONE sale.

    Date, channel, payment, county and state stay as they are,
    which is convenient when several orders are entered in a row.
    """

    state = st.session_state

    state.std_original = 0
    state.std_slobberin = 0
    state.std_revenue = 0.0
    state.std_tax = 0.0
    state.std_ship_revenue = 0.0
    state.std_fee = 0.0
    state.std_ship_expense = 0.0
    state.std_revenue_auto = True


def _standard_suggestion():
    """
    Standard price for the jars and channel currently entered.
    """

    state = st.session_state

    return float(
        suggest_product_revenue(
            state.std_original + state.std_slobberin,
            state.std_channel
        )
    )


# ============================================================
# STANDARD SALE: CALLBACKS
# ============================================================

def _on_products_change():
    """
    Jar quantities changed: fill in the standard price,
    unless Dr. D already typed his own amount.
    """

    if st.session_state.std_revenue_auto:

        st.session_state.std_revenue = _standard_suggestion()


def _on_channel_change():
    """
    Channel changed: select the usual payment method and
    update the standard price (retail vs wholesale).
    """

    st.session_state.std_payment = DEFAULT_PAYMENT[
        st.session_state.std_channel
    ]

    _on_products_change()


def _on_revenue_change():
    """
    Dr. D typed a revenue amount.

    If it differs from the standard price, automatic filling
    stops. Typing 0 switches automatic filling back on.
    """

    revenue = st.session_state.std_revenue

    st.session_state.std_revenue_auto = (
        revenue == 0
        or abs(revenue - _standard_suggestion()) < 0.005
    )


def _record_standard_sale():
    """
    Save the Standard Sale, then clear the form.
    """

    state = st.session_state

    try:

        result = record_sale(
            sale_date=state.std_date,
            total_amount=state.std_revenue,
            original_quantity=state.std_original,
            slobberin_quantity=state.std_slobberin,
            sales_channel=state.std_channel,
            payment_method=state.std_payment,
            tax_collected=state.std_tax,
            shipping_revenue=state.std_ship_revenue,
            shopify_fee=state.std_fee,
            shipping_expense=state.std_ship_expense,
            state=(
                state.std_state.strip()
                if state.std_state.strip()
                else None
            ),
            county=(
                state.std_county.strip()
                if state.std_county.strip()
                else None
            )
        )

    except Exception as error:

        # The fields stay filled in so nothing has to be retyped.
        set_flash(
            "standard",
            "error",
            f"Could not record sale: {error}"
        )

        return

    message = (
        f"Sale #{result['sale_id']} recorded: "
        f"{describe_jars(result['original_quantity'], result['slobberin_quantity'])} "
        f"for {format_currency(result['total_amount'])} "
        f"({result['sales_channel']}, {result['payment_method']}). "
        f"Slobberin' revenue {format_currency(result['slobberin_revenue'])}, "
        f"scholarship {format_currency(result['total_scholarship'])}, "
        f"estimated profit {format_currency(result['estimated_profit'])}."
    )

    set_flash("standard", "success", message)

    _reset_standard_fields()


# ============================================================
# STANDARD SALE: TAB
# ============================================================

def _render_standard_sale(scholarship_percent):
    """
    Draw the Standard Sale tab.
    """

    _init_standard_state()

    state = st.session_state

    show_flash("standard")

    form_column, preview_column = st.columns(
        [1.7, 1],
        gap="large"
    )

    # ========================================================
    # LEFT: SALE DETAILS
    # ========================================================

    with form_column:

        section_label("Sale Details")

        with st.container(border=True):

            # ------------------------------------------------
            # WHAT WAS SOLD
            # ------------------------------------------------

            product1, product2 = st.columns(2)

            with product1:

                st.number_input(
                    "Original Sauce (jars)",
                    min_value=0,
                    step=1,
                    key="std_original",
                    on_change=_on_products_change
                )

            with product2:

                st.number_input(
                    "Slobberin' Sauce (jars)",
                    min_value=0,
                    step=1,
                    key="std_slobberin",
                    on_change=_on_products_change
                )

            money1, money2 = st.columns(2)

            with money1:

                st.number_input(
                    "Product Revenue ($)",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="std_revenue",
                    on_change=_on_revenue_change,
                    help=(
                        "Amount received for the sauce itself, "
                        "without sales tax and without shipping."
                    )
                )

            with money2:

                st.selectbox(
                    "Sales Channel",
                    SALES_CHANNELS,
                    key="std_channel",
                    on_change=_on_channel_change
                )

            total_quantity = (
                state.std_original
                + state.std_slobberin
            )

            # This caption is always drawn (with or without jars)
            # so the fields below it never change position.
            if total_quantity > 0:

                price_hint = (
                    f"Standard price for {total_quantity} "
                    f"jar{'s' if total_quantity != 1 else ''} "
                    f"({'wholesale' if state.std_channel == 'Wholesale' else 'retail'}): "
                    f"{format_currency(_standard_suggestion())}. "
                    "It is filled in automatically until you type "
                    "a different amount."
                )

            else:

                price_hint = (
                    "The standard price is filled in automatically "
                    "when you enter the jars. You can type a "
                    "different amount."
                )

            st.caption(price_hint)

            # ------------------------------------------------
            # WHEN / HOW / WHERE
            # ------------------------------------------------

            detail1, detail2 = st.columns(2)

            with detail1:

                st.date_input(
                    "Sale Date",
                    key="std_date"
                )

            with detail2:

                st.selectbox(
                    "Payment Method",
                    PAYMENT_METHODS,
                    key="std_payment"
                )

            place1, place2 = st.columns([2, 1])

            with place1:

                st.text_input(
                    "County",
                    key="std_county"
                )

            with place2:

                st.text_input(
                    "State",
                    key="std_state"
                )

            # ------------------------------------------------
            # TAX, FEES AND SHIPPING
            #
            # Open automatically for Shopify orders, because
            # every online order has these values.
            # ------------------------------------------------

            with st.expander(
                "Tax, fees and shipping",
                expanded=(state.std_channel == "Shopify")
            ):

                extra1, extra2 = st.columns(2)

                with extra1:

                    st.number_input(
                        "Sales Tax Collected ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="std_tax"
                    )

                    st.number_input(
                        "Shipping Revenue ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="std_ship_revenue",
                        help="What the customer paid for shipping."
                    )

                with extra2:

                    st.number_input(
                        "Shopify / Card Fee ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="std_fee"
                    )

                    st.number_input(
                        "Shipping Expense ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="std_ship_expense",
                        help="What you paid for the shipping label."
                    )

    # ========================================================
    # RIGHT: CALCULATION PREVIEW
    # ========================================================

    ready_to_record = False

    with preview_column:

        section_label("Calculation Preview")

        with st.container(border=True):

            if total_quantity == 0 or state.std_revenue <= 0:

                st.info(
                    "Enter the jars sold and the product revenue. "
                    "The calculation appears here before "
                    "anything is saved."
                )

            else:

                try:

                    preview = preview_sale(
                        total_amount=state.std_revenue,
                        original_quantity=state.std_original,
                        slobberin_quantity=state.std_slobberin,
                        sales_channel=state.std_channel,
                        shipping_revenue=state.std_ship_revenue,
                        shopify_fee=state.std_fee,
                        shipping_expense=state.std_ship_expense
                    )

                    # ---------------------------------------
                    # MONEY
                    # ---------------------------------------

                    rows = [
                        (
                            "Original revenue",
                            format_currency(preview["original_revenue"])
                        ),
                        (
                            "Slobberin' revenue",
                            format_currency(preview["slobberin_revenue"])
                        ),
                        (
                            f"Scholarship ({scholarship_percent})",
                            format_currency(preview["total_scholarship"]),
                            "accent"
                        ),
                        (
                            "Product cost",
                            format_currency(preview["total_product_cost"])
                        )
                    ]

                    if preview["shipping_revenue"] > 0:

                        rows.append(
                            (
                                "Shipping revenue",
                                format_currency(preview["shipping_revenue"])
                            )
                        )

                    if preview["shopify_fee"] > 0:

                        rows.append(
                            (
                                "Shopify / card fee",
                                format_currency(preview["shopify_fee"])
                            )
                        )

                    if preview["shipping_expense"] > 0:

                        rows.append(
                            (
                                "Shipping expense",
                                format_currency(preview["shipping_expense"])
                            )
                        )

                    rows.append(
                        (
                            "Estimated profit",
                            format_currency(preview["estimated_profit"]),
                            "strong"
                        )
                    )

                    # Total the customer paid: a quick way to
                    # compare with the Shopify order or receipt.
                    customer_total = (
                        float(preview["total_amount"])
                        + float(state.std_tax)
                        + float(preview["shipping_revenue"])
                    )

                    rows.append(
                        (
                            "Customer paid (with tax and shipping)",
                            format_currency(customer_total),
                            "muted"
                        )
                    )

                    calc_rows("This sale", rows)

                    st.write("")

                    # ---------------------------------------
                    # INVENTORY
                    # ---------------------------------------

                    calc_rows(
                        "Inventory after sale",
                        [
                            (
                                "Original",
                                f"{preview['original_inventory_before']:,} → "
                                f"{preview['original_inventory_after']:,}"
                            ),
                            (
                                "Slobberin'",
                                f"{preview['slobberin_inventory_before']:,} → "
                                f"{preview['slobberin_inventory_after']:,}"
                            )
                        ]
                    )

                    # ---------------------------------------
                    # CHECKS
                    # ---------------------------------------

                    if preview["price_warning"]:

                        st.warning(preview["price_warning"])

                    if preview["enough_inventory"]:

                        ready_to_record = True

                    else:

                        st.error(
                            "Not enough jars in inventory for this "
                            "sale. Receive a batch or correct the "
                            "quantity first."
                        )

                except Exception as error:

                    st.error(f"Could not calculate: {error}")

        st.button(
            "Record Sale",
            type="primary",
            on_click=_record_standard_sale,
            disabled=not ready_to_record,
            key="std_record_button",
            **STRETCH
        )


# ============================================================
# MARKET SUMMARY: STATE
# ============================================================

def _init_market_state():
    """
    Give every Market Summary field a starting value.
    """

    state = st.session_state

    state.setdefault("mkt_date", date.today())
    state.setdefault("mkt_county", "Wake")
    state.setdefault("mkt_state", "NC")

    for key in ("mkt_cash_original", "mkt_cash_slobberin",
                "mkt_card_original", "mkt_card_slobberin"):

        state.setdefault(key, 0)

    for key in ("mkt_cash_revenue", "mkt_card_revenue",
                "mkt_cash_tax", "mkt_card_tax", "mkt_card_fee"):

        state.setdefault(key, 0.0)


def _reset_market_fields():
    """
    Clear the Market Summary numbers after they were saved.
    Date, county and state stay as they are.
    """

    state = st.session_state

    for key in ("mkt_cash_original", "mkt_cash_slobberin",
                "mkt_card_original", "mkt_card_slobberin"):

        state[key] = 0

    for key in ("mkt_cash_revenue", "mkt_card_revenue",
                "mkt_cash_tax", "mkt_card_tax", "mkt_card_fee"):

        state[key] = 0.0


# ============================================================
# MARKET SUMMARY: CALLBACK
# ============================================================

def _record_market():
    """
    Save the Market Summary, then clear the numbers.
    """

    state = st.session_state

    try:

        result = record_market_summary(
            sale_date=state.mkt_date,
            cash_original_quantity=state.mkt_cash_original,
            cash_slobberin_quantity=state.mkt_cash_slobberin,
            cash_revenue=state.mkt_cash_revenue,
            card_original_quantity=state.mkt_card_original,
            card_slobberin_quantity=state.mkt_card_slobberin,
            card_revenue=state.mkt_card_revenue,
            card_fee=state.mkt_card_fee,
            cash_tax=state.mkt_cash_tax,
            card_tax=state.mkt_card_tax,
            state=(
                state.mkt_state.strip()
                if state.mkt_state.strip()
                else None
            ),
            county=(
                state.mkt_county.strip()
                if state.mkt_county.strip()
                else None
            )
        )

    except Exception as error:

        set_flash(
            "market",
            "error",
            f"Could not record market summary: {error}"
        )

        return

    sale_numbers = []

    for part in (result["cash_sale"], result["card_sale"]):

        if part is not None:

            sale_numbers.append(f"#{part['sale_id']}")

    message = (
        f"Market summary recorded as sale "
        f"{' and '.join(sale_numbers)}: "
        f"{describe_jars(result['total_original_quantity'], result['total_slobberin_quantity'])} "
        f"for {format_currency(result['total_revenue'])}. "
        f"Scholarship {format_currency(result['total_scholarship'])}, "
        f"estimated profit {format_currency(result['estimated_profit'])}."
    )

    set_flash("market", "success", message)

    _reset_market_fields()


# ============================================================
# MARKET SUMMARY: ONE PART (CASH OR CARD)
# ============================================================

def _preview_market_part(
    label,
    original_quantity,
    slobberin_quantity,
    revenue,
    fee=0.0
):
    """
    Calculate one part (cash or card) of a market summary.

    Returns a tuple:

        (preview, problem)

    preview:
        the preview_sale() dictionary, or None when this part
        is empty or incomplete.

    problem:
        text describing an incomplete entry, or None.
    """

    quantity = original_quantity + slobberin_quantity

    if quantity == 0 and revenue <= 0:

        # Nothing entered for this part. That is allowed.
        return None, None

    if quantity == 0:

        return None, (
            f"{label}: an amount is entered but no jars."
        )

    if revenue <= 0:

        return None, (
            f"{label}: jars are entered but no amount."
        )

    preview = preview_sale(
        total_amount=revenue,
        original_quantity=original_quantity,
        slobberin_quantity=slobberin_quantity,
        sales_channel="Farmers Market",
        shopify_fee=fee
    )

    return preview, None


# ============================================================
# MARKET SUMMARY: TAB
# ============================================================

def _render_market_summary(scholarship_percent):
    """
    Draw the Market Summary tab.
    """

    _init_market_state()

    state = st.session_state

    show_flash("market")

    form_column, preview_column = st.columns(
        [1.7, 1],
        gap="large"
    )

    # ========================================================
    # LEFT: EVENT TOTALS
    # ========================================================

    with form_column:

        section_label("Farmers Market Event")

        st.caption(
            "Enter the event totals once after the market. "
            "Cash and card are saved as two separate sales."
        )

        with st.container(border=True):

            top1, top2, top3 = st.columns([1.3, 1.3, 0.8])

            with top1:

                st.date_input(
                    "Market Date",
                    key="mkt_date"
                )

            with top2:

                st.text_input(
                    "County",
                    key="mkt_county"
                )

            with top3:

                st.text_input(
                    "State",
                    key="mkt_state"
                )

            # ------------------------------------------------
            # CASH
            # ------------------------------------------------

            st.markdown("#### Cash Sales")

            cash1, cash2, cash3 = st.columns(3)

            with cash1:

                st.number_input(
                    "Original Jars — Cash",
                    min_value=0,
                    step=1,
                    key="mkt_cash_original"
                )

            with cash2:

                st.number_input(
                    "Slobberin' Jars — Cash",
                    min_value=0,
                    step=1,
                    key="mkt_cash_slobberin"
                )

            with cash3:

                st.number_input(
                    "Cash Collected ($)",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="mkt_cash_revenue",
                    help="Product revenue, without sales tax."
                )

            # ------------------------------------------------
            # CARD
            # ------------------------------------------------

            st.markdown("#### Card Sales")

            card1, card2, card3 = st.columns(3)

            with card1:

                st.number_input(
                    "Original Jars — Card",
                    min_value=0,
                    step=1,
                    key="mkt_card_original"
                )

            with card2:

                st.number_input(
                    "Slobberin' Jars — Card",
                    min_value=0,
                    step=1,
                    key="mkt_card_slobberin"
                )

            with card3:

                st.number_input(
                    "Card Revenue ($)",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="mkt_card_revenue",
                    help="Product revenue, without sales tax."
                )

            # ------------------------------------------------
            # OPTIONAL TAX AND FEE
            # ------------------------------------------------

            with st.expander("Optional tax and card fee"):

                extra1, extra2, extra3 = st.columns(3)

                with extra1:

                    st.number_input(
                        "Cash Tax ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="mkt_cash_tax"
                    )

                with extra2:

                    st.number_input(
                        "Card Tax ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="mkt_card_tax"
                    )

                with extra3:

                    st.number_input(
                        "Card Processing Fee ($)",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="mkt_card_fee"
                    )

    # ========================================================
    # RIGHT: SUMMARY CHECK
    # ========================================================

    ready_to_record = False

    with preview_column:

        section_label("Summary Check")

        with st.container(border=True):

            try:

                cash_preview, cash_problem = _preview_market_part(
                    "Cash",
                    state.mkt_cash_original,
                    state.mkt_cash_slobberin,
                    state.mkt_cash_revenue
                )

                card_preview, card_problem = _preview_market_part(
                    "Card",
                    state.mkt_card_original,
                    state.mkt_card_slobberin,
                    state.mkt_card_revenue,
                    fee=state.mkt_card_fee
                )

                parts = [
                    ("Cash", cash_preview),
                    ("Card", card_preview)
                ]

                entered_parts = [
                    (label, preview)
                    for label, preview in parts
                    if preview is not None
                ]

                if (
                    len(entered_parts) == 0
                    and cash_problem is None
                    and card_problem is None
                ):

                    st.info(
                        "Enter the jars and the amount collected. "
                        "The revenue split and scholarship appear "
                        "here before anything is saved."
                    )

                # -------------------------------------------
                # ONE BLOCK PER PART
                # -------------------------------------------

                total_revenue = 0.0
                total_scholarship = 0.0
                total_profit = 0.0
                original_sold = 0
                slobberin_sold = 0

                for label, preview in entered_parts:

                    calc_rows(
                        f"{label}: "
                        f"{describe_jars(preview['original_quantity'], preview['slobberin_quantity'])}",
                        [
                            (
                                "Average per jar",
                                format_currency(preview["revenue_per_jar"])
                            ),
                            (
                                "Original revenue",
                                format_currency(preview["original_revenue"])
                            ),
                            (
                                "Slobberin' revenue",
                                format_currency(preview["slobberin_revenue"])
                            ),
                            (
                                f"Scholarship ({scholarship_percent})",
                                format_currency(preview["total_scholarship"]),
                                "accent"
                            )
                        ]
                    )

                    if preview["price_warning"]:

                        st.warning(
                            f"{label}: {preview['price_warning']}"
                        )

                    st.write("")

                    total_revenue += float(preview["total_amount"])
                    total_scholarship += float(preview["total_scholarship"])
                    total_profit += float(preview["estimated_profit"])
                    original_sold += preview["original_quantity"]
                    slobberin_sold += preview["slobberin_quantity"]

                # -------------------------------------------
                # EVENT TOTAL AND INVENTORY
                # -------------------------------------------

                if len(entered_parts) > 0:

                    first_preview = entered_parts[0][1]

                    original_before = first_preview[
                        "original_inventory_before"
                    ]

                    slobberin_before = first_preview[
                        "slobberin_inventory_before"
                    ]

                    original_after = original_before - original_sold
                    slobberin_after = slobberin_before - slobberin_sold

                    calc_rows(
                        "Event total",
                        [
                            (
                                "Revenue",
                                format_currency(total_revenue)
                            ),
                            (
                                "Scholarship",
                                format_currency(total_scholarship),
                                "accent"
                            ),
                            (
                                "Estimated profit",
                                format_currency(total_profit),
                                "strong"
                            ),
                            (
                                "Original inventory",
                                f"{original_before:,} → {original_after:,}",
                                "muted"
                            ),
                            (
                                "Slobberin' inventory",
                                f"{slobberin_before:,} → {slobberin_after:,}",
                                "muted"
                            )
                        ]
                    )

                    enough_inventory = (
                        original_after >= 0
                        and slobberin_after >= 0
                    )

                    if not enough_inventory:

                        st.error(
                            "Not enough jars in inventory for this "
                            "event. Check the quantities."
                        )

                    ready_to_record = (
                        enough_inventory
                        and cash_problem is None
                        and card_problem is None
                    )

                # -------------------------------------------
                # INCOMPLETE ENTRIES
                # -------------------------------------------

                for problem in (cash_problem, card_problem):

                    if problem is not None:

                        st.warning(problem)

            except Exception as error:

                st.error(f"Could not calculate: {error}")

        st.button(
            "Record Market Summary",
            type="primary",
            on_click=_record_market,
            disabled=not ready_to_record,
            key="mkt_record_button",
            **STRETCH
        )


# ============================================================
# RECENT SALES: CALLBACK
# ============================================================

def _void_selected_sale():
    """
    Cancel the sale selected in "Cancel a sale".
    """

    state = st.session_state

    sale_id = state.get("void_sale_id")

    if sale_id is None:

        return

    if not state.get("void_confirm", False):

        set_flash(
            "recent",
            "warning",
            "Tick the confirmation box before cancelling a sale."
        )

        return

    try:

        result = void_sale(
            sale_id,
            reason=state.get("void_reason", "")
        )

    except Exception as error:

        set_flash(
            "recent",
            "error",
            f"Could not cancel sale: {error}"
        )

        return

    returned = ", ".join(
        f"{item['quantity_returned']} {item['product_name']}"
        for item in result["returned"]
    )

    set_flash(
        "recent",
        "success",
        f"Sale #{sale_id} "
        f"({format_currency(result['total_amount'])}) was cancelled. "
        f"Returned to inventory: {returned}."
    )

    # Reset the selector for the next draw.
    for key in ("void_sale_id", "void_confirm", "void_reason"):

        if key in state:

            del state[key]


# ============================================================
# RECENT SALES: TAB
# ============================================================

def _render_recent_sales():
    """
    Draw the Recent Sales tab.
    """

    show_flash("recent")

    section_label("Recent Sales")

    recent_sales = get_recent_sales_with_items(limit=20)

    if len(recent_sales) == 0:

        st.info("No sales have been recorded yet.")

        return

    # --------------------------------------------------------
    # TABLE
    # --------------------------------------------------------

    recent_df = pd.DataFrame(recent_sales)

    recent_df["sale_date"] = pd.to_datetime(
        recent_df["sale_date"]
    ).dt.strftime("%b %d, %Y")

    for column in ("product_revenue", "tax_collected", "scholarship"):

        recent_df[column] = recent_df[column].astype(float)

    recent_df = recent_df[
        [
            "sale_id",
            "sale_date",
            "sales_channel",
            "payment_method",
            "original_quantity",
            "slobberin_quantity",
            "product_revenue",
            "tax_collected",
            "scholarship",
            "county"
        ]
    ].rename(
        columns={
            "sale_id": "Sale #",
            "sale_date": "Date",
            "sales_channel": "Channel",
            "payment_method": "Payment",
            "original_quantity": "Original Jars",
            "slobberin_quantity": "Slobberin' Jars",
            "product_revenue": "Revenue",
            "tax_collected": "Tax",
            "scholarship": "Scholarship",
            "county": "County"
        }
    )

    st.dataframe(
        recent_df,
        hide_index=True,
        column_config={
            "Revenue": st.column_config.NumberColumn(format="$%.2f"),
            "Tax": st.column_config.NumberColumn(format="$%.2f"),
            "Scholarship": st.column_config.NumberColumn(format="$%.2f")
        },
        **STRETCH
    )

    st.caption("The 20 most recent sales, newest first.")

    # --------------------------------------------------------
    # CANCEL A SALE
    # --------------------------------------------------------

    st.write("")

    section_label("Cancel a Sale Entered by Mistake")

    with st.container(border=True):

        st.caption(
            "Cancelling removes the sale from revenue, scholarship "
            "and forecast reports and returns the jars to inventory. "
            "A note stays in the inventory audit trail."
        )

        labels = {
            sale["sale_id"]: (
                f"#{sale['sale_id']} · "
                f"{sale['sale_date'].strftime('%b %d, %Y')} · "
                f"{sale['sales_channel']} · {sale['payment_method']} · "
                f"{format_currency(sale['product_revenue'])} · "
                f"{describe_jars(sale['original_quantity'], sale['slobberin_quantity'])}"
            )
            for sale in recent_sales
        }

        cancel1, cancel2 = st.columns([1.6, 1])

        with cancel1:

            # Nothing is preselected, so a sale can never be
            # cancelled by accident.
            st.selectbox(
                "Sale to cancel",
                list(labels.keys()),
                index=None,
                placeholder="Choose a sale",
                format_func=lambda sale_id: labels[sale_id],
                key="void_sale_id"
            )

        with cancel2:

            st.text_input(
                "Reason",
                placeholder="Example: entered twice",
                key="void_reason"
            )

        st.checkbox(
            "Yes, cancel this sale and return the jars to inventory.",
            key="void_confirm"
        )

        # The button works only after a sale is chosen AND the
        # confirmation box is ticked.
        st.button(
            "Cancel Sale",
            on_click=_void_selected_sale,
            disabled=not (
                st.session_state.get("void_sale_id") is not None
                and st.session_state.get("void_confirm", False)
            ),
            key="void_button"
        )


# ============================================================
# RECORD SALE PAGE
# ============================================================

def render_record_sale():
    """
    Draw the Record Sale page.
    """

    page_header(
        "Record Sale",
        "Enter one sale, or the totals of a Farmers Market "
        "after the event."
    )

    try:

        # Example: Decimal("0.1600") -> "16%"
        scholarship_percent = f"{float(get_scholarship_rate()):.0%}"

        standard_tab, market_tab, recent_tab = st.tabs(
            [
                "Standard Sale",
                "Market Summary",
                "Recent Sales"
            ]
        )

        with standard_tab:

            _render_standard_sale(scholarship_percent)

        with market_tab:

            _render_market_summary(scholarship_percent)

        with recent_tab:

            _render_recent_sales()

    except Exception as error:

        st.error(f"Could not load Record Sale: {error}")
