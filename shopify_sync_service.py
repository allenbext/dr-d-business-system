"""
shopify_sync_service.py

Purpose:
Coordinate Shopify order synchronization with PostgreSQL.

Responsibilities:

1. Check whether a Shopify order was already imported.
2. Manage Shopify variant -> local product mappings.
3. Validate Shopify order line items.
4. Build a preview of how a Shopify order would map
   into the local database.
5. Create Shopify synchronization audit records.
6. Safely handle the "not configured" state.
7. Support a demo preview without inserting fake sales.

Important:

shopify_service.py
    Handles Shopify API communication.

shopify_sync_service.py
    Handles integration logic between Shopify and PostgreSQL.

At the current prototype stage:
    - Live API structure is ready.
    - Product mappings can be managed.
    - Orders can be previewed.
    - Duplicate checks work.
    - Sync logging works.
    - Actual live order insertion is intentionally disabled.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import get_connection

from shopify_service import (
    get_shopify_configuration_status,
    get_recent_shopify_orders,
    get_demo_shopify_order
)


# ============================================================
# CONSTANTS
# ============================================================

SHOPIFY_SOURCE_TYPE = "SHOPIFY"


# ============================================================
# DUPLICATE CHECK
# ============================================================

def is_shopify_order_imported(
    shopify_order_id
):
    """
    Return True when the Shopify order already exists
    in the local sales table.

    Shopify orders will eventually use:

        source_type = 'SHOPIFY'
        source_reference = Shopify GraphQL Order ID
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT EXISTS (

                    SELECT 1

                    FROM sales

                    WHERE source_type = %s
                      AND source_reference = %s
                );
                """,
                (
                    SHOPIFY_SOURCE_TYPE,
                    shopify_order_id
                )
            )

            result = (
                cur.fetchone()
            )


    return bool(
        result[0]
    )


# ============================================================
# LOCAL PRODUCTS
# ============================================================

def get_local_products():
    """
    Return local products keyed by product_id.

    Example:

    {
        1: {
            "product_name": "Dr. D's Original Sauce",
            "unit_cost": Decimal("3.00"),
            "scholarship_rate": Decimal("0.0000")
        },

        2: {
            "product_name": "Slobberin' Sauce",
            "unit_cost": Decimal("3.00"),
            "scholarship_rate": Decimal("0.1600")
        }
    }
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    product_id,
                    product_name,
                    unit_cost,
                    scholarship_rate

                FROM products

                ORDER BY
                    product_id;
                """
            )

            rows = (
                cur.fetchall()
            )


    products = {}


    for row in rows:

        products[
            row[0]
        ] = {
            "product_name":
                row[1],

            "unit_cost":
                row[2],

            "scholarship_rate":
                row[3]
        }


    return products


# ============================================================
# ACTIVE SHOPIFY PRODUCT MAPPINGS
# ============================================================

def get_shopify_product_mappings():
    """
    Return active mappings keyed by Shopify variant ID.

    Each mapping holds the CONTENTS of one unit of the Shopify
    product (see sql/12_shopify_product_contents.sql).

    Example (the Combo product):

    {
        "gid://shopify/ProductVariant/123": {
            "original_jars": 1,
            "slobberin_jars": 1,
            "shopify_product_name": "Original AND Slobberin' Combo"
        }
    }
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    shopify_variant_id,
                    original_jars,
                    slobberin_jars,
                    shopify_product_name

                FROM shopify_product_map

                WHERE active = TRUE

                ORDER BY
                    shopify_product_map_id;
                """
            )

            rows = (
                cur.fetchall()
            )


    mappings = {}


    for row in rows:

        mappings[
            row[0]
        ] = {
            "original_jars":
                int(
                    row[1]
                ),

            "slobberin_jars":
                int(
                    row[2]
                ),

            "shopify_product_name":
                row[3]
        }


    return mappings


# ============================================================
# CONTENTS OF A SHOPIFY PRODUCT
# ============================================================

# The five products of Dr. D's Shopify store and what ONE unit
# of each holds: (Original jars, Slobberin' jars).
# The Shopify page offers these as choices when a product is
# connected.
STORE_PRODUCT_CONTENTS = {
    "Dr. D's Original, 1 jar": (1, 0),
    "Slobberin' Sauce, 1 jar": (0, 1),
    "Dr. D's Original, 2 jars": (2, 0),
    "Slobberin' Sauce, 2 jars": (0, 2),
    "Combo: 1 Original + 1 Slobberin'": (1, 1),
}


def describe_contents(
    original_jars,
    slobberin_jars
):
    """
    Describe the contents of one unit in words.

    Examples:
        (1, 1) -> "1 Original + 1 Slobberin'"
        (0, 2) -> "2 Slobberin'"
    """

    parts = []

    if original_jars:

        parts.append(
            f"{original_jars} Original"
        )

    if slobberin_jars:

        parts.append(
            f"{slobberin_jars} Slobberin'"
        )

    return " + ".join(parts) if parts else "Nothing"


def split_line_revenue(
    line_revenue,
    original_jars,
    slobberin_jars
):
    """
    Split the revenue of ONE Shopify line between the sauces.

    The split uses the contents of the product that was actually
    bought, so it is exact for every product in the store:

        Slobberin' 2-pack, $18 -> $0.00 Original, $18.00 Slobberin'
        Combo,             $18 -> $9.00 Original,  $9.00 Slobberin'
        2 x Combo,         $36 -> $18.00 / $18.00

    Inside one product both sauces have the same price, so the
    line is split by its jars. The Slobberin' share is rounded to
    cents first (the scholarship is calculated from it); the
    Original share is the remainder, so the two always add up to
    the line revenue.

    Returns (original_revenue, slobberin_revenue).
    """

    line_revenue = to_decimal(
        line_revenue
    )

    total_jars = (
        original_jars
        + slobberin_jars
    )

    if total_jars <= 0:

        raise ValueError(
            "A Shopify product must contain at least one jar."
        )

    slobberin_revenue = (
        line_revenue
        * Decimal(slobberin_jars)
        / Decimal(total_jars)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    original_revenue = (
        line_revenue
        - slobberin_revenue
    )

    return original_revenue, slobberin_revenue


# ============================================================
# MAPPING LIST FOR UI
# ============================================================

def get_shopify_mapping_rows(
    include_inactive=True
):
    """
    Return Shopify product mappings in a UI-friendly list.

    include_inactive=True:
        Show both active and inactive historical mappings.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            if include_inactive:

                cur.execute(
                    """
                    SELECT
                        spm.shopify_product_map_id,
                        spm.shopify_variant_id,
                        spm.shopify_product_name,
                        spm.original_jars,
                        spm.slobberin_jars,
                        spm.active,
                        spm.created_at,
                        spm.updated_at

                    FROM shopify_product_map AS spm

                    ORDER BY
                        spm.active DESC,
                        spm.shopify_product_map_id;
                    """
                )

            else:

                cur.execute(
                    """
                    SELECT
                        spm.shopify_product_map_id,
                        spm.shopify_variant_id,
                        spm.shopify_product_name,
                        spm.original_jars,
                        spm.slobberin_jars,
                        spm.active,
                        spm.created_at,
                        spm.updated_at

                    FROM shopify_product_map AS spm

                    WHERE spm.active = TRUE

                    ORDER BY
                        spm.shopify_product_map_id;
                    """
                )


            rows = (
                cur.fetchall()
            )


    mappings = []


    for row in rows:

        mappings.append(
            {
                "mapping_id":
                    row[0],

                "shopify_variant_id":
                    row[1],

                "shopify_product_name":
                    row[2],

                "original_jars":
                    row[3],

                "slobberin_jars":
                    row[4],

                # Text shown in the Shopify page, for example
                # "1 Original + 1 Slobberin'".
                "local_product":
                    describe_contents(
                        row[3],
                        row[4]
                    ),

                "active":
                    row[5],

                "created_at":
                    row[6],

                "updated_at":
                    row[7]
            }
        )


    return mappings


# ============================================================
# SAVE / UPDATE PRODUCT MAPPING
# ============================================================

def save_shopify_product_mapping(
    shopify_variant_id,
    original_jars,
    slobberin_jars,
    shopify_product_name=None
):
    """
    Insert or update a Shopify product connection.

    A connection says what ONE unit of a Shopify product holds:

        original_jars   jars of Dr. D's Original Sauce
        slobberin_jars  jars of Slobberin' Sauce

    Examples from the store:
        Slobberin' Sauce (1 jar)   -> 0, 1
        Original (2 jars)          -> 2, 0
        Combo                      -> 1, 1

    If the Shopify variant ID already exists:
        - the contents and the Shopify product name are updated
        - the connection is reactivated
        - updated_at is refreshed

    product_id is still filled in when the product holds only
    one sauce, so older reports that read it keep working.
    A Combo holds both sauces and has no single product_id.
    """

    variant_id = (
        shopify_variant_id.strip()
        if shopify_variant_id
        else ""
    )


    if not variant_id:

        raise ValueError(
            "Shopify Variant ID is required."
        )


    original_jars = int(
        original_jars
    )

    slobberin_jars = int(
        slobberin_jars
    )


    if original_jars < 0 or slobberin_jars < 0:

        raise ValueError(
            "Jar counts cannot be negative."
        )


    if original_jars + slobberin_jars == 0:

        raise ValueError(
            "A Shopify product must contain at least one jar."
        )


    # One sauce only -> that product. Both sauces -> none.
    if slobberin_jars == 0:

        product_id = 1

    elif original_jars == 0:

        product_id = 2

    else:

        product_id = None


    clean_product_name = (
        shopify_product_name.strip()
        if (
            shopify_product_name
            and shopify_product_name.strip()
        )
        else None
    )


    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO shopify_product_map (
                    shopify_variant_id,
                    product_id,
                    original_jars,
                    slobberin_jars,
                    shopify_product_name,
                    active
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    TRUE
                )

                ON CONFLICT (
                    shopify_variant_id
                )

                DO UPDATE SET
                    product_id =
                        EXCLUDED.product_id,

                    original_jars =
                        EXCLUDED.original_jars,

                    slobberin_jars =
                        EXCLUDED.slobberin_jars,

                    shopify_product_name =
                        EXCLUDED.shopify_product_name,

                    active =
                        TRUE,

                    updated_at =
                        CURRENT_TIMESTAMP

                RETURNING
                    shopify_product_map_id;
                """,
                (
                    variant_id,
                    product_id,
                    original_jars,
                    slobberin_jars,
                    clean_product_name
                )
            )


            mapping_id = (
                cur.fetchone()[0]
            )


        conn.commit()


    return {
        "mapping_id":
            mapping_id,

        "shopify_variant_id":
            variant_id,

        "original_jars":
            original_jars,

        "slobberin_jars":
            slobberin_jars,

        "local_product":
            describe_contents(
                original_jars,
                slobberin_jars
            )
    }


# ============================================================
# DEACTIVATE PRODUCT MAPPING
# ============================================================

def deactivate_shopify_product_mapping(
    shopify_variant_id
):
    """
    Deactivate a Shopify mapping without deleting history.

    We prefer deactivation over DELETE because the mapping
    may be relevant for audit/history later.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE shopify_product_map

                SET
                    active = FALSE,
                    updated_at = CURRENT_TIMESTAMP

                WHERE shopify_variant_id = %s

                RETURNING
                    shopify_product_map_id;
                """,
                (
                    shopify_variant_id,
                )
            )


            row = (
                cur.fetchone()
            )


        conn.commit()


    if row is None:

        raise ValueError(
            "Shopify product mapping was not found."
        )


    return {
        "mapping_id":
            row[0],

        "shopify_variant_id":
            shopify_variant_id,

        "active":
            False
    }


# ============================================================
# REACTIVATE PRODUCT MAPPING
# ============================================================

def reactivate_shopify_product_mapping(
    shopify_variant_id
):
    """
    Reactivate a previously disabled Shopify mapping.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE shopify_product_map

                SET
                    active = TRUE,
                    updated_at = CURRENT_TIMESTAMP

                WHERE shopify_variant_id = %s

                RETURNING
                    shopify_product_map_id;
                """,
                (
                    shopify_variant_id,
                )
            )


            row = (
                cur.fetchone()
            )


        conn.commit()


    if row is None:

        raise ValueError(
            "Shopify product mapping was not found."
        )


    return {
        "mapping_id":
            row[0],

        "shopify_variant_id":
            shopify_variant_id,

        "active":
            True
    }


# ============================================================
# SYNC LOG — START
# ============================================================

def start_shopify_sync():
    """
    Insert a STARTED synchronization record.

    Returns:
        sync_id
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO shopify_sync_log (
                    status,
                    message
                )

                VALUES (
                    'STARTED',
                    'Shopify synchronization started.'
                )

                RETURNING sync_id;
                """
            )


            sync_id = (
                cur.fetchone()[0]
            )


        conn.commit()


    return sync_id


# ============================================================
# SYNC LOG — COMPLETE
# ============================================================

def complete_shopify_sync(
    sync_id,
    status,
    orders_found=0,
    orders_imported=0,
    orders_skipped=0,
    orders_failed=0,
    message=None
):
    """
    Finish one Shopify sync audit record.

    Expected final status:
        SUCCESS
        PARTIAL
        FAILED
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE shopify_sync_log

                SET
                    completed_at =
                        CURRENT_TIMESTAMP,

                    status =
                        %s,

                    orders_found =
                        %s,

                    orders_imported =
                        %s,

                    orders_skipped =
                        %s,

                    orders_failed =
                        %s,

                    message =
                        %s

                WHERE sync_id = %s;
                """,
                (
                    status,
                    orders_found,
                    orders_imported,
                    orders_skipped,
                    orders_failed,
                    message,
                    sync_id
                )
            )


        conn.commit()


# ============================================================
# RECENT SYNC HISTORY
# ============================================================

def get_shopify_sync_history(
    limit=10
):
    """
    Return recent Shopify synchronization attempts.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    sync_id,
                    started_at,
                    completed_at,
                    status,
                    orders_found,
                    orders_imported,
                    orders_skipped,
                    orders_failed,
                    message

                FROM shopify_sync_log

                ORDER BY
                    started_at DESC

                LIMIT %s;
                """,
                (
                    limit,
                )
            )


            rows = (
                cur.fetchall()
            )


    history = []


    for row in rows:

        history.append(
            {
                "sync_id":
                    row[0],

                "started_at":
                    row[1],

                "completed_at":
                    row[2],

                "status":
                    row[3],

                "orders_found":
                    row[4],

                "orders_imported":
                    row[5],

                "orders_skipped":
                    row[6],

                "orders_failed":
                    row[7],

                "message":
                    row[8]
            }
        )


    return history


# ============================================================
# LAST SUCCESSFUL SYNC
# ============================================================

def get_last_successful_shopify_sync():
    """
    Return the most recent successful Shopify sync.

    Returns None when no successful sync exists.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    sync_id,
                    started_at,
                    completed_at,
                    orders_found,
                    orders_imported,
                    orders_skipped,
                    orders_failed,
                    message

                FROM shopify_sync_log

                WHERE status = 'SUCCESS'

                ORDER BY
                    completed_at DESC

                LIMIT 1;
                """
            )


            row = (
                cur.fetchone()
            )


    if row is None:

        return None


    return {
        "sync_id":
            row[0],

        "started_at":
            row[1],

        "completed_at":
            row[2],

        "orders_found":
            row[3],

        "orders_imported":
            row[4],

        "orders_skipped":
            row[5],

        "orders_failed":
            row[6],

        "message":
            row[7]
    }


# ============================================================
# DECIMAL HELPER
# ============================================================

def to_decimal(
    value
):
    """
    Convert Shopify numeric strings to Decimal.
    """

    if value is None:

        return Decimal(
            "0.00"
        )


    return Decimal(
        str(
            value
        )
    )


# ============================================================
# BUILD ORDER PREVIEW
# ============================================================

def build_shopify_order_preview(
    order,
    allow_demo_mapping=False
):
    """
    Validate and normalize one Shopify order.

    Nothing is written to PostgreSQL.

    Returns:
        duplicate status
        mapping status
        product quantities
        allocated revenue
        scholarship
        inventory movements
    """

    shopify_order_id = (
        order.get(
            "shopify_order_id"
        )
    )


    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    already_imported = False


    if shopify_order_id:

        already_imported = (
            is_shopify_order_imported(
                shopify_order_id
            )
        )


    # --------------------------------------------------------
    # PRODUCT INFORMATION
    # --------------------------------------------------------

    product_mappings = (
        get_shopify_product_mappings()
    )


    local_products = (
        get_local_products()
    )


    # --------------------------------------------------------
    # DEMO-ONLY MAPPING
    #
    # This is never inserted into shopify_product_map.
    # --------------------------------------------------------

    demo_mappings = {}


    if allow_demo_mapping:

        demo_mappings = {
            "DEMO-COMBO-VARIANT":
                {
                    "original_jars":
                        1,

                    "slobberin_jars":
                        1,

                    "shopify_product_name":
                        "Original AND Slobberin' Combo"
                },

            "DEMO-SLOBBERIN-2-JARS-VARIANT":
                {
                    "original_jars":
                        0,

                    "slobberin_jars":
                        2,

                    "shopify_product_name":
                        "Slobberin' Sauce (2 jars)"
                }
        }


    preview_items = []

    unmapped_items = []

    total_quantity = (
        0
    )


    total_scholarship = (
        Decimal(
            "0.00"
        )
    )


    # ========================================================
    # PROCESS LINE ITEMS
    # ========================================================

    for line_item in order.get(
        "line_items",
        []
    ):

        variant_id = (
            line_item.get(
                "shopify_variant_id"
            )
        )


        mapping = (
            product_mappings.get(
                variant_id
            )
        )


        if (
            mapping is None
            and allow_demo_mapping
        ):

            mapping = (
                demo_mappings.get(
                    variant_id
                )
            )


        # Number of Shopify units on this line
        # (for example 2 x Combo).
        units = int(
            line_item.get(
                "quantity",
                0
            )
            or 0
        )


        discounted_total = (
            to_decimal(
                line_item.get(
                    "discounted_total"
                )
            )
        )


        # ----------------------------------------------------
        # UNMAPPED SHOPIFY VARIANT
        #
        # The contents are unknown, so the line cannot be
        # counted in jars. The order cannot be imported until
        # the product is connected.
        # ----------------------------------------------------

        if mapping is None:

            total_quantity += (
                units
            )


            unmapped_items.append(
                {
                    "shopify_variant_id":
                        variant_id,

                    "product_title":
                        line_item.get(
                            "product_title"
                        ),

                    "variant_title":
                        line_item.get(
                            "variant_title"
                        ),

                    "quantity":
                        units,

                    "discounted_total":
                        discounted_total
                }
            )


            preview_items.append(
                {
                    "mapped":
                        False,

                    "shopify_variant_id":
                        variant_id,

                    "shopify_product":
                        line_item.get(
                            "product_title"
                        ),

                    "product_id":
                        None,

                    "local_product":
                        None,

                    "quantity":
                        units,

                    "allocated_revenue":
                        discounted_total,

                    "scholarship_rate":
                        None,

                    "scholarship_amount":
                        None,

                    "inventory_change":
                        -units
                }
            )


            continue


        # ----------------------------------------------------
        # CONTENTS OF THIS LINE
        #
        # jars = Shopify units x jars in one unit
        #
        # Example: 2 x Combo -> 2 Original + 2 Slobberin'
        # ----------------------------------------------------

        line_original_jars = (
            units
            * mapping[
                "original_jars"
            ]
        )


        line_slobberin_jars = (
            units
            * mapping[
                "slobberin_jars"
            ]
        )


        original_revenue, slobberin_revenue = (
            split_line_revenue(
                discounted_total,
                mapping[
                    "original_jars"
                ],
                mapping[
                    "slobberin_jars"
                ]
            )
        )


        # ----------------------------------------------------
        # ONE LOCAL ITEM PER SAUCE IN THIS LINE
        #
        # A Combo line becomes two items: one Original and one
        # Slobberin'. Each item becomes one sale_items row, one
        # inventory decrease and one audit record at import.
        # ----------------------------------------------------

        for product_id, jars, revenue in (
            (1, line_original_jars, original_revenue),
            (2, line_slobberin_jars, slobberin_revenue)
        ):

            if jars == 0:

                continue


            local_product = (
                local_products.get(
                    product_id
                )
            )


            if local_product is None:

                unmapped_items.append(
                    {
                        "shopify_variant_id":
                            variant_id,

                        "product_title":
                            line_item.get(
                                "product_title"
                            ),

                        "quantity":
                            jars,

                        "reason":
                            (
                                f"Product {product_id} does not "
                                "exist in the products table."
                            )
                    }
                )


                continue


            scholarship_rate = (
                Decimal(
                    str(
                        local_product[
                            "scholarship_rate"
                        ]
                    )
                )
            )


            scholarship_amount = (
                revenue
                * scholarship_rate
            ).quantize(
                Decimal(
                    "0.01"
                ),

                # Same rounding rule as sale_service.py (half up).
                rounding=ROUND_HALF_UP
            )


            total_scholarship += (
                scholarship_amount
            )


            total_quantity += (
                jars
            )


            preview_items.append(
                {
                    "mapped":
                        True,

                    "shopify_variant_id":
                        variant_id,

                    "shopify_product":
                        line_item.get(
                            "product_title"
                        ),

                    "product_id":
                        product_id,

                    "local_product":
                        local_product[
                            "product_name"
                        ],

                    # Jars of this sauce, not Shopify units.
                    "quantity":
                        jars,

                    "allocated_revenue":
                        revenue,

                    "scholarship_rate":
                        scholarship_rate,

                    "scholarship_amount":
                        scholarship_amount,

                    "inventory_change":
                        -jars
                }
            )


    # ========================================================
    # IMPORT READINESS
    # ========================================================

    valid_for_import = (
        not already_imported
        and len(
            unmapped_items
        ) == 0
        and len(
            preview_items
        ) > 0
    )


    return {
        "shopify_order_id":
            shopify_order_id,

        "order_name":
            order.get(
                "order_name"
            ),

        "created_at":
            order.get(
                "created_at"
            ),

        "financial_status":
            order.get(
                "financial_status"
            ),

        "fulfillment_status":
            order.get(
                "fulfillment_status"
            ),

        "already_imported":
            already_imported,

        "valid_for_import":
            valid_for_import,

        "product_revenue":
            to_decimal(
                order.get(
                    "product_revenue"
                )
            ),

        "tax_collected":
            to_decimal(
                order.get(
                    "tax_collected"
                )
            ),

        "shipping_revenue":
            to_decimal(
                order.get(
                    "shipping_revenue"
                )
            ),

        # Payment processing fee from the Shopify Payments
        # transactions of the order (0.00 if none was found).
        "shopify_fee":
            to_decimal(
                order.get(
                    "shopify_fee"
                )
            ),

        "fee_found":
            bool(
                order.get(
                    "fee_found"
                )
            ),

        # Where the order was created, for example
        # "Online Store" or "Point of Sale".
        "order_source":
            order.get(
                "order_source"
            ),

        "state":
            order.get(
                "state"
            ),

        "city":
            order.get(
                "city"
            ),

        "postal_code":
            order.get(
                "postal_code"
            ),

        "total_quantity":
            total_quantity,

        "total_scholarship":
            total_scholarship,

        "items":
            preview_items,

        "unmapped_items":
            unmapped_items
    }


# ============================================================
# DEMO PREVIEW
# ============================================================

def get_demo_shopify_preview():
    """
    Build a demo preview.

    Demo data is NEVER inserted into PostgreSQL.
    """

    demo_order = (
        get_demo_shopify_order()
    )


    return (
        build_shopify_order_preview(
            order=demo_order,
            allow_demo_mapping=True
        )
    )


# ============================================================
# PREVIEW RECENT LIVE ORDERS
# ============================================================

def preview_recent_shopify_orders(
    first=10
):
    """
    Retrieve recent live Shopify orders and prepare previews.

    No sales are inserted.
    """

    configuration = (
        get_shopify_configuration_status()
    )


    if not configuration[
        "configured"
    ]:

        return {
            "success":
                False,

            "configured":
                False,

            "message":
                "Shopify credentials are not configured.",

            "orders":
                []
        }


    result = (
        get_recent_shopify_orders(
            first=first
        )
    )


    if not result[
        "success"
    ]:

        return {
            "success":
                False,

            "configured":
                True,

            "message":
                result[
                    "message"
                ],

            "orders":
                [],

            "errors":
                result.get(
                    "errors"
                )
        }


    previews = []


    for order in result[
        "orders"
    ]:

        previews.append(
            build_shopify_order_preview(
                order=order,
                allow_demo_mapping=False
            )
        )


    return {
        "success":
            True,

        "configured":
            True,

        "message":
            (
                f"Prepared "
                f"{len(previews)} "
                f"Shopify order preview(s)."
            ),

        "orders":
            previews,

        "retrieved_at":
            result.get(
                "retrieved_at"
            )
    }


# ============================================================
# SAFE SYNC CHECK
# ============================================================

def run_shopify_sync_check():
    """
    Run the prototype Shopify synchronization workflow.

    Current behavior:

    1. Create sync audit record.
    2. Check credentials.
    3. Retrieve recent orders when connected.
    4. Check duplicate orders.
    5. Check product mappings.
    6. Report orders ready for import.
    7. DO NOT insert live orders yet.
    """

    sync_id = (
        start_shopify_sync()
    )


    configuration = (
        get_shopify_configuration_status()
    )


    # ========================================================
    # NOT CONFIGURED
    # ========================================================

    if not configuration[
        "configured"
    ]:

        message = (
            "Shopify credentials are not configured. "
            "Integration structure is ready, but live "
            "synchronization is unavailable."
        )


        complete_shopify_sync(
            sync_id=sync_id,
            status="FAILED",
            orders_found=0,
            orders_imported=0,
            orders_skipped=0,
            orders_failed=0,
            message=message
        )


        return {
            "success":
                False,

            "configured":
                False,

            "sync_id":
                sync_id,

            "message":
                message,

            "orders_found":
                0,

            "orders_imported":
                0,

            "orders_skipped":
                0,

            "orders_failed":
                0
        }


    # ========================================================
    # RETRIEVE LIVE ORDER PREVIEWS
    # ========================================================

    preview_result = (
        preview_recent_shopify_orders(
            first=25
        )
    )


    if not preview_result[
        "success"
    ]:

        message = (
            preview_result[
                "message"
            ]
        )


        complete_shopify_sync(
            sync_id=sync_id,
            status="FAILED",
            orders_found=0,
            orders_imported=0,
            orders_skipped=0,
            orders_failed=0,
            message=message
        )


        return {
            "success":
                False,

            "configured":
                True,

            "sync_id":
                sync_id,

            "message":
                message,

            "orders_found":
                0,

            "orders_imported":
                0,

            "orders_skipped":
                0,

            "orders_failed":
                0
        }


    orders = (
        preview_result[
            "orders"
        ]
    )


    orders_found = (
        len(
            orders
        )
    )


    already_imported_count = sum(
        1
        for order in orders
        if order[
            "already_imported"
        ]
    )


    unmapped_count = sum(
        1
        for order in orders
        if len(
            order[
                "unmapped_items"
            ]
        ) > 0
    )


    ready_count = sum(
        1
        for order in orders
        if order[
            "valid_for_import"
        ]
    )


    message = (
        f"Shopify preview completed. "
        f"{orders_found} order(s) found; "
        f"{ready_count} ready for import; "
        f"{already_imported_count} already imported; "
        f"{unmapped_count} contain unmapped products. "
        f"Prototype live import is currently disabled."
    )


    complete_shopify_sync(
        sync_id=sync_id,
        status="SUCCESS",
        orders_found=orders_found,
        orders_imported=0,
        orders_skipped=(
            already_imported_count
        ),
        orders_failed=0,
        message=message
    )


    return {
        "success":
            True,

        "configured":
            True,

        "sync_id":
            sync_id,

        "message":
            message,

        "orders_found":
            orders_found,

        "orders_ready":
            ready_count,

        "orders_imported":
            0,

        "orders_skipped":
            already_imported_count,

        "orders_with_unmapped_products":
            unmapped_count,

        "orders":
            orders
    }