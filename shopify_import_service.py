"""
shopify_import_service.py

Purpose:
Import one validated Shopify order into PostgreSQL.

This is the final database-writing layer of the
Shopify integration pipeline.

Architecture:

    Shopify GraphQL API
            ↓
    shopify_service.py
            ↓
    shopify_sync_service.py
        - duplicate check
        - product mapping
        - validation
        - preview
            ↓
    shopify_import_service.py
        - sales
        - sale_items
        - inventory
        - inventory_transactions

Important:

This module is production-capable, but the Streamlit UI
does NOT call it yet.

Live Shopify order insertion remains intentionally disabled
until real Shopify credentials and product mappings are
available and verified.

The complete import is performed inside one PostgreSQL
transaction.

If any step fails, the complete transaction is rolled back.
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from db import get_connection

from shopify_sync_service import (
    SHOPIFY_SOURCE_TYPE,
    build_shopify_order_preview
)


# ============================================================
# CONSTANTS
# ============================================================

MONEY_QUANTIZER = Decimal(
    "0.01"
)


# ============================================================
# MONEY HELPER
# ============================================================

def money(
    value
):
    """
    Convert a value to Decimal currency rounded to cents.
    """

    return Decimal(
        str(
            value
        )
    ).quantize(
        MONEY_QUANTIZER,
        rounding=ROUND_HALF_UP
    )


# ============================================================
# SHOPIFY DATE PARSER
# ============================================================

def parse_shopify_sale_date(
    created_at
):
    """
    Convert Shopify createdAt into a Python date.

    Shopify typically returns ISO 8601:

        2026-11-14T18:42:11Z

    Our sales table currently stores sale_date rather than
    a full timestamp, so only the calendar date is retained.
    """

    if created_at is None:

        return date.today()


    if isinstance(
        created_at,
        datetime
    ):

        return created_at.date()


    if isinstance(
        created_at,
        date
    ):

        return created_at


    value = str(
        created_at
    ).strip()


    try:

        parsed_datetime = (
            datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00"
                )
            )
        )


        return (
            parsed_datetime.date()
        )


    except ValueError as error:

        raise ValueError(
            (
                "Could not parse Shopify order date: "
                f"{created_at}"
            )
        ) from error


# ============================================================
# VALIDATE IMPORT PREVIEW
# ============================================================

def validate_shopify_import_preview(
    preview
):
    """
    Perform final safety checks immediately before
    PostgreSQL insert.

    Raises ValueError when the order should not be imported.
    """

    # --------------------------------------------------------
    # Order ID
    # --------------------------------------------------------

    shopify_order_id = (
        preview.get(
            "shopify_order_id"
        )
    )


    if not shopify_order_id:

        raise ValueError(
            "Shopify Order ID is missing."
        )


    # --------------------------------------------------------
    # Never allow our presentation demo order to enter
    # the production database.
    # --------------------------------------------------------

    if str(
        shopify_order_id
    ).startswith(
        "DEMO-"
    ):

        raise ValueError(
            (
                "Demo Shopify orders cannot be imported "
                "into PostgreSQL."
            )
        )


    # --------------------------------------------------------
    # Duplicate
    # --------------------------------------------------------

    if preview.get(
        "already_imported"
    ):

        raise ValueError(
            (
                "This Shopify order has already been "
                "imported."
            )
        )


    # --------------------------------------------------------
    # Product mapping
    # --------------------------------------------------------

    if preview.get(
        "unmapped_items"
    ):

        raise ValueError(
            (
                "The Shopify order contains one or more "
                "unmapped product variants."
            )
        )


    # --------------------------------------------------------
    # Must contain at least one item
    # --------------------------------------------------------

    items = (
        preview.get(
            "items",
            []
        )
    )


    if len(
        items
    ) == 0:

        raise ValueError(
            "The Shopify order contains no importable items."
        )


    # --------------------------------------------------------
    # Financial status
    #
    # For the prototype, only fully paid Shopify orders
    # should become completed sales.
    # --------------------------------------------------------

    financial_status = str(
        preview.get(
            "financial_status"
        )
        or ""
    ).upper()


    if financial_status != "PAID":

        raise ValueError(
            (
                "Only PAID Shopify orders can currently "
                "be imported. "
                f"Order status: {financial_status or 'UNKNOWN'}."
            )
        )


    # --------------------------------------------------------
    # Validate every line item
    # --------------------------------------------------------

    for item in items:

        if not item.get(
            "mapped"
        ):

            raise ValueError(
                "All Shopify line items must be mapped."
            )


        if item.get(
            "product_id"
        ) is None:

            raise ValueError(
                "A mapped Shopify item is missing product_id."
            )


        quantity = int(
            item.get(
                "quantity",
                0
            )
            or 0
        )


        if quantity <= 0:

            raise ValueError(
                (
                    "Shopify item quantity must be "
                    "greater than zero."
                )
            )


        allocated_revenue = money(
            item.get(
                "allocated_revenue",
                0
            )
        )


        if allocated_revenue < 0:

            raise ValueError(
                (
                    "Shopify allocated revenue cannot "
                    "be negative."
                )
            )


    # --------------------------------------------------------
    # Reconcile order revenue with line-item revenue
    # --------------------------------------------------------

    source_product_revenue = money(
        preview.get(
            "product_revenue",
            0
        )
    )


    line_item_revenue = sum(
        (
            money(
                item[
                    "allocated_revenue"
                ]
            )

            for item in items
        ),
        Decimal(
            "0.00"
        )
    )


    difference = abs(
        source_product_revenue
        - line_item_revenue
    )


    # Small cent-level tolerance protects against unusual
    # source rounding while still catching material errors.
    if difference > Decimal(
        "0.02"
    ):

        raise ValueError(
            (
                "Shopify order revenue does not reconcile "
                "with the line-item revenue. "
                f"Order revenue: {source_product_revenue}; "
                f"Line-item revenue: {line_item_revenue}."
            )
        )


    return True


# ============================================================
# IMPORT ONE SHOPIFY ORDER
# ============================================================

def import_shopify_order(
    order
):
    """
    Import one Shopify order into PostgreSQL.

    Parameters
    ----------
    order:
        Normalized Shopify order dictionary produced by
        shopify_service.get_recent_shopify_orders().

    Process
    -------
    1. Build integration preview.
    2. Validate duplicate / mapping / financial status.
    3. Insert one sales record.
    4. Insert sale_items.
    5. Decrease current inventory.
    6. Insert inventory SALE transactions.
    7. Commit everything together.

    If any step fails:
        ROLLBACK.

    Returns
    -------
    Dictionary describing the imported sale.
    """

    # ========================================================
    # BUILD PREVIEW
    # ========================================================

    preview = (
        build_shopify_order_preview(
            order=order,
            allow_demo_mapping=False
        )
    )


    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    validate_shopify_import_preview(
        preview
    )


    # ========================================================
    # SALE-LEVEL VALUES
    # ========================================================

    shopify_order_id = (
        preview[
            "shopify_order_id"
        ]
    )


    order_name = (
        preview.get(
            "order_name"
        )
        or shopify_order_id
    )


    sale_date = (
        parse_shopify_sale_date(
            preview.get(
                "created_at"
            )
        )
    )


    product_revenue = money(
        preview[
            "product_revenue"
        ]
    )


    tax_collected = money(
        preview[
            "tax_collected"
        ]
    )


    shipping_revenue = money(
        preview[
            "shipping_revenue"
        ]
    )


    total_scholarship = money(
        preview[
            "total_scholarship"
        ]
    )


    state = (
        preview.get(
            "state"
        )
    )


    # --------------------------------------------------------
    # Shopify does not normally provide US county directly.
    #
    # We intentionally leave county NULL rather than guessing.
    # This can later be enriched from city / ZIP.
    # --------------------------------------------------------

    county = None


    # --------------------------------------------------------
    # Payment processing fee:
    # taken from the Shopify Payments transactions of the order
    # (see sum_transaction_fees in shopify_service.py).
    # It is 0.00 when the order was paid through another
    # gateway, because Shopify does not know that fee.
    # --------------------------------------------------------

    shopify_fee = money(
        preview.get(
            "shopify_fee"
        )
        or "0.00"
    )


    # --------------------------------------------------------
    # The cost of the shipping label is still not available
    # per order. Labels bought in Shopify are charged on the
    # Shopify bill for the period, not on the order.
    # --------------------------------------------------------

    shipping_expense = Decimal(
        "0.00"
    )


    # ========================================================
    # DATABASE TRANSACTION
    # ========================================================

    conn = (
        get_connection()
    )


    try:

        with conn.cursor() as cur:

            # =================================================
            # 1. INSERT SALES RECORD
            # =================================================

            cur.execute(
                """
                INSERT INTO sales (
                    sale_date,
                    sales_channel,
                    payment_method,
                    total_amount,
                    tax_collected,
                    shipping_revenue,
                    shopify_fee,
                    shipping_expense,
                    state,
                    county,
                    source_type,
                    source_reference
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )

                RETURNING sale_id;
                """,
                (
                    sale_date,

                    "Shopify",

                    "Shopify",

                    product_revenue,

                    tax_collected,

                    shipping_revenue,

                    shopify_fee,

                    shipping_expense,

                    state,

                    county,

                    SHOPIFY_SOURCE_TYPE,

                    shopify_order_id
                )
            )


            sale_id = (
                cur.fetchone()[0]
            )


            imported_items = []


            # =================================================
            # 2. PROCESS EACH PRODUCT
            # =================================================

            for item in preview[
                "items"
            ]:

                product_id = int(
                    item[
                        "product_id"
                    ]
                )


                quantity = int(
                    item[
                        "quantity"
                    ]
                )


                allocated_revenue = money(
                    item[
                        "allocated_revenue"
                    ]
                )


                scholarship_amount = money(
                    item[
                        "scholarship_amount"
                    ]
                )


                # ---------------------------------------------
                # Average realized price per jar.
                #
                # Example:
                #
                # 2 jars sold for $18
                # sale_price = $9 per jar
                #
                # This preserves discounted Shopify revenue.
                # ---------------------------------------------

                sale_price = (
                    allocated_revenue
                    / Decimal(
                        quantity
                    )
                ).quantize(
                    MONEY_QUANTIZER,
                    rounding=ROUND_HALF_UP
                )


                # =============================================
                # 2A. INSERT SALE ITEM
                # =============================================

                cur.execute(
                    """
                    INSERT INTO sale_items (
                        sale_id,
                        product_id,
                        quantity,
                        sale_price,
                        allocated_revenue,
                        scholarship_amount
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )

                    RETURNING sale_item_id;
                    """,
                    (
                        sale_id,
                        product_id,
                        quantity,
                        sale_price,
                        allocated_revenue,
                        scholarship_amount
                    )
                )


                sale_item_id = (
                    cur.fetchone()[0]
                )


                # =============================================
                # 2B. DECREASE INVENTORY
                #
                # The WHERE condition prevents inventory from
                # becoming negative.
                # =============================================

                cur.execute(
                    """
                    UPDATE inventory

                    SET
                        current_quantity =
                            current_quantity - %s

                    WHERE product_id = %s

                      AND current_quantity >= %s

                    RETURNING current_quantity;
                    """,
                    (
                        quantity,
                        product_id,
                        quantity
                    )
                )


                inventory_row = (
                    cur.fetchone()
                )


                if inventory_row is None:

                    raise ValueError(
                        (
                            "Not enough inventory to import "
                            f"Shopify order {order_name}. "
                            f"Product ID {product_id} requires "
                            f"{quantity} jar(s)."
                        )
                    )


                remaining_inventory = (
                    inventory_row[0]
                )


                # =============================================
                # 2C. INVENTORY AUDIT TRANSACTION
                # =============================================

                cur.execute(
                    """
                    INSERT INTO inventory_transactions (
                        product_id,
                        batch_id,
                        transaction_date,
                        transaction_type,
                        quantity_change,
                        sale_id,
                        notes
                    )

                    VALUES (
                        %s,
                        NULL,
                        %s,
                        'SALE',
                        %s,
                        %s,
                        %s
                    );
                    """,
                    (
                        product_id,

                        sale_date,

                        -quantity,

                        sale_id,

                        (
                            "Imported automatically from "
                            f"Shopify order {order_name}."
                        )
                    )
                )


                imported_items.append(
                    {
                        "sale_item_id":
                            sale_item_id,

                        "product_id":
                            product_id,

                        "local_product":
                            item[
                                "local_product"
                            ],

                        "quantity":
                            quantity,

                        "sale_price":
                            sale_price,

                        "allocated_revenue":
                            allocated_revenue,

                        "scholarship_amount":
                            scholarship_amount,

                        "remaining_inventory":
                            remaining_inventory
                    }
                )


        # ====================================================
        # COMMIT
        # ====================================================

        conn.commit()


    except Exception:

        # ====================================================
        # ROLLBACK
        #
        # Critical:
        # A Shopify order must never be partially imported.
        # ====================================================

        conn.rollback()

        raise


    finally:

        conn.close()


    # ========================================================
    # RESULT
    # ========================================================

    return {
        "success":
            True,

        "sale_id":
            sale_id,

        "shopify_order_id":
            shopify_order_id,

        "order_name":
            order_name,

        "sale_date":
            sale_date,

        "product_revenue":
            product_revenue,

        "tax_collected":
            tax_collected,

        "shipping_revenue":
            shipping_revenue,

        "shopify_fee":
            shopify_fee,

        "shipping_expense":
            shipping_expense,

        "total_scholarship":
            total_scholarship,

        "total_quantity":
            preview[
                "total_quantity"
            ],

        "items":
            imported_items,

        "message":
            (
                f"Shopify order {order_name} "
                f"was imported as sale #{sale_id}."
            )
    }