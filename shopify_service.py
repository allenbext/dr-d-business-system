"""
shopify_service.py

Purpose:
Low-level Shopify API client.

This module is responsible only for communication
with the Shopify GraphQL Admin API.

It does NOT write Shopify orders into PostgreSQL.
Database import logic will live in shopify_sync_service.py.

Current prototype behavior:

- Reads Shopify credentials from .env
- Reports whether the integration is configured
- Can test the connection when credentials exist
- Can fetch recent orders when credentials exist
- Safely returns "not configured" when credentials are missing

This allows the application UI and integration architecture
to be completed before Dr. D provides Shopify API access.
"""

import os
from decimal import Decimal
from datetime import datetime

import requests
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv(
    override=True
)


# ============================================================
# SHOPIFY CONFIGURATION
# ============================================================

SHOPIFY_STORE = os.getenv(
    "SHOPIFY_STORE"
)

SHOPIFY_ACCESS_TOKEN = os.getenv(
    "SHOPIFY_ACCESS_TOKEN"
)

SHOPIFY_API_VERSION = os.getenv(
    "SHOPIFY_API_VERSION",
    "2026-10"
)


# ============================================================
# CONFIGURATION STATUS
# ============================================================

def get_shopify_configuration_status():
    """
    Check whether the required Shopify configuration exists.

    Returns a dictionary that can be displayed directly
    in Streamlit.

    Important:
    The access token itself is NEVER returned.
    """

    missing_fields = []


    if not SHOPIFY_STORE:

        missing_fields.append(
            "SHOPIFY_STORE"
        )


    if not SHOPIFY_ACCESS_TOKEN:

        missing_fields.append(
            "SHOPIFY_ACCESS_TOKEN"
        )


    configured = (
        len(
            missing_fields
        )
        == 0
    )


    return {
        "configured":
            configured,

        "store":
            (
                SHOPIFY_STORE
                if SHOPIFY_STORE
                else "Not configured"
            ),

        "api_version":
            SHOPIFY_API_VERSION,

        "missing_fields":
            missing_fields
    }


# ============================================================
# SHOPIFY GRAPHQL ENDPOINT
# ============================================================

def get_shopify_graphql_url():
    """
    Build the Shopify GraphQL Admin API endpoint.

    Example:

    https://example-store.myshopify.com/admin/api/2026-10/graphql.json
    """

    status = (
        get_shopify_configuration_status()
    )


    if not status[
        "configured"
    ]:

        return None


    store = (
        SHOPIFY_STORE.strip()
    )


    # --------------------------------------------------------
    # Allow either:
    #
    # example-store
    #
    # or:
    #
    # example-store.myshopify.com
    # --------------------------------------------------------

    if not store.endswith(
        ".myshopify.com"
    ):

        store = (
            f"{store}.myshopify.com"
        )


    return (
        f"https://{store}"
        f"/admin/api/"
        f"{SHOPIFY_API_VERSION}"
        f"/graphql.json"
    )


# ============================================================
# GENERIC GRAPHQL REQUEST
# ============================================================

def execute_shopify_graphql(
    query,
    variables=None
):
    """
    Execute one GraphQL request against Shopify.

    Returns a normalized dictionary.

    No exception from requests is allowed to crash
    the Streamlit application.
    """

    if variables is None:

        variables = {}


    status = (
        get_shopify_configuration_status()
    )


    if not status[
        "configured"
    ]:

        return {
            "success":
                False,

            "configured":
                False,

            "message":
                (
                    "Shopify credentials are not configured."
                ),

            "data":
                None,

            "errors":
                None
        }


    url = (
        get_shopify_graphql_url()
    )


    headers = {
        "Content-Type":
            "application/json",

        "X-Shopify-Access-Token":
            SHOPIFY_ACCESS_TOKEN
    }


    payload = {
        "query":
            query,

        "variables":
            variables
    }


    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )


        # ----------------------------------------------------
        # HTTP error
        # ----------------------------------------------------

        if not response.ok:

            return {
                "success":
                    False,

                "configured":
                    True,

                "message":
                    (
                        "Shopify API request failed "
                        f"with HTTP {response.status_code}."
                    ),

                "data":
                    None,

                "errors":
                    response.text
            }


        response_json = (
            response.json()
        )


        # ----------------------------------------------------
        # GraphQL-level error
        # ----------------------------------------------------

        if response_json.get(
            "errors"
        ):

            return {
                "success":
                    False,

                "configured":
                    True,

                "message":
                    (
                        "Shopify GraphQL returned an error."
                    ),

                "data":
                    response_json.get(
                        "data"
                    ),

                "errors":
                    response_json.get(
                        "errors"
                    )
            }


        return {
            "success":
                True,

            "configured":
                True,

            "message":
                "Shopify request completed successfully.",

            "data":
                response_json.get(
                    "data"
                ),

            "errors":
                None
        }


    except requests.RequestException as error:

        return {
            "success":
                False,

            "configured":
                True,

            "message":
                (
                    "Could not connect to Shopify."
                ),

            "data":
                None,

            "errors":
                str(
                    error
                )
        }


    except ValueError as error:

        return {
            "success":
                False,

            "configured":
                True,

            "message":
                (
                    "Shopify returned an invalid JSON response."
                ),

            "data":
                None,

            "errors":
                str(
                    error
                )
        }


# ============================================================
# TEST CONNECTION
# ============================================================

def test_shopify_connection():
    """
    Test whether the configured credentials can access
    the Shopify store.

    Uses a very small GraphQL query.

    No order data is imported.
    """

    query = """
        query TestShopifyConnection {
            shop {
                name
                myshopifyDomain
            }
        }
    """


    result = (
        execute_shopify_graphql(
            query=query
        )
    )


    if not result[
        "success"
    ]:

        return result


    shop_data = (
        result[
            "data"
        ][
            "shop"
        ]
    )


    return {
        "success":
            True,

        "configured":
            True,

        "message":
            (
                "Connected to Shopify successfully."
            ),

        "shop_name":
            shop_data.get(
                "name"
            ),

        "shop_domain":
            shop_data.get(
                "myshopifyDomain"
            ),

        "errors":
            None
    }


# ============================================================
# PAYMENT PROCESSING FEE
# ============================================================

# Transaction kinds that move money FROM the customer TO the
# store. A refund also has a transaction, but it is not a fee
# charged on the sale.
FEE_TRANSACTION_KINDS = {
    "SALE",
    "CAPTURE"
}


def sum_transaction_fees(
    transactions
):
    """
    Add up the payment processing fees of one Shopify order.

    Why this is needed:
    The Shopify order does NOT contain the card processing fee.
    Shopify Payments stores the fee on each payment transaction
    of the order (OrderTransaction.fees). Dr. D used to look up
    this number by hand for every order.

    Rules:
    - Only successful SALE and CAPTURE transactions count.
    - Every fee on such a transaction is added.
    - Fees exist only for Shopify Payments. An order paid
      through another gateway (for example PayPal) has no fee
      in Shopify; the result is then 0.00 with fee_found False,
      so the user knows the fee must come from somewhere else.

    Returns:
        {
            "shopify_fee": "0.58",    text, like other amounts
            "fee_found":   True
        }
    """

    total_fee = Decimal(
        "0.00"
    )


    fee_found = False


    for transaction in (
        transactions
        or []
    ):

        if transaction.get(
            "kind"
        ) not in FEE_TRANSACTION_KINDS:

            continue


        if transaction.get(
            "status"
        ) != "SUCCESS":

            continue


        for fee in (
            transaction.get(
                "fees"
            )
            or []
        ):

            amount = (
                (
                    fee.get(
                        "amount"
                    )
                    or {}
                ).get(
                    "amount"
                )
            )


            if amount is None:

                continue


            total_fee += Decimal(
                str(
                    amount
                )
            )


            fee_found = True


    return {
        "shopify_fee":
            str(
                total_fee.quantize(
                    Decimal(
                        "0.01"
                    )
                )
            ),

        "fee_found":
            fee_found
    }


# ============================================================
# RECENT ORDERS QUERY
# ============================================================

def get_recent_shopify_orders(
    first=10
):
    """
    Fetch recent Shopify orders.

    This function only retrieves and normalizes API data.

    It does NOT insert orders into PostgreSQL.

    The future sync service will use this function.
    """

    query = """
        query GetRecentOrders($first: Int!) {

            orders(
                first: $first,
                sortKey: CREATED_AT,
                reverse: true
            ) {

                edges {

                    node {

                        id

                        name

                        createdAt

                        displayFinancialStatus

                        displayFulfillmentStatus

                        subtotalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }

                        totalTaxSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }

                        totalShippingPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }

                        shippingAddress {
                            provinceCode
                            city
                            zip
                        }

                        app {
                            name
                        }

                        transactions(
                            first: 20
                        ) {

                            kind

                            status

                            gateway

                            fees {

                                amount {
                                    amount
                                    currencyCode
                                }
                            }
                        }

                        lineItems(
                            first: 100
                        ) {

                            edges {

                                node {

                                    id

                                    name

                                    quantity

                                    variant {

                                        id

                                        title

                                        product {
                                            title
                                        }
                                    }

                                    originalUnitPriceSet {
                                        shopMoney {
                                            amount
                                            currencyCode
                                        }
                                    }

                                    discountedTotalSet {
                                        shopMoney {
                                            amount
                                            currencyCode
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """


    result = (
        execute_shopify_graphql(
            query=query,
            variables={
                "first":
                    first
            }
        )
    )


    if not result[
        "success"
    ]:

        return result


    edges = (
        result[
            "data"
        ][
            "orders"
        ][
            "edges"
        ]
    )


    normalized_orders = []


    for edge in edges:

        node = (
            edge[
                "node"
            ]
        )


        # The payment processing fee is not part of the order
        # itself. It is stored on the payment transactions.
        fee_summary = (
            sum_transaction_fees(
                node.get(
                    "transactions"
                )
            )
        )


        line_items = []


        for line_edge in (
            node[
                "lineItems"
            ][
                "edges"
            ]
        ):

            line_node = (
                line_edge[
                    "node"
                ]
            )


            variant = (
                line_node.get(
                    "variant"
                )
            )


            line_items.append(
                {
                    "line_item_id":
                        line_node.get(
                            "id"
                        ),

                    "name":
                        line_node.get(
                            "name"
                        ),

                    "quantity":
                        line_node.get(
                            "quantity"
                        ),

                    "shopify_variant_id":
                        (
                            variant.get(
                                "id"
                            )
                            if variant
                            else None
                        ),

                    "variant_title":
                        (
                            variant.get(
                                "title"
                            )
                            if variant
                            else None
                        ),

                    "product_title":
                        (
                            variant[
                                "product"
                            ].get(
                                "title"
                            )
                            if (
                                variant
                                and variant.get(
                                    "product"
                                )
                            )
                            else None
                        ),

                    "original_unit_price":
                        (
                            line_node[
                                "originalUnitPriceSet"
                            ][
                                "shopMoney"
                            ][
                                "amount"
                            ]
                        ),

                    "discounted_total":
                        (
                            line_node[
                                "discountedTotalSet"
                            ][
                                "shopMoney"
                            ][
                                "amount"
                            ]
                        )
                }
            )


        normalized_orders.append(
            {
                "shopify_order_id":
                    node.get(
                        "id"
                    ),

                "order_name":
                    node.get(
                        "name"
                    ),

                "created_at":
                    node.get(
                        "createdAt"
                    ),

                "financial_status":
                    node.get(
                        "displayFinancialStatus"
                    ),

                "fulfillment_status":
                    node.get(
                        "displayFulfillmentStatus"
                    ),

                "product_revenue":
                    (
                        node[
                            "subtotalPriceSet"
                        ][
                            "shopMoney"
                        ][
                            "amount"
                        ]
                    ),

                "tax_collected":
                    (
                        node[
                            "totalTaxSet"
                        ][
                            "shopMoney"
                        ][
                            "amount"
                        ]
                    ),

                "shipping_revenue":
                    (
                        node[
                            "totalShippingPriceSet"
                        ][
                            "shopMoney"
                        ][
                            "amount"
                        ]
                    ),

                "state":
                    (
                        node[
                            "shippingAddress"
                        ].get(
                            "provinceCode"
                        )
                        if node.get(
                            "shippingAddress"
                        )
                        else None
                    ),

                "city":
                    (
                        node[
                            "shippingAddress"
                        ].get(
                            "city"
                        )
                        if node.get(
                            "shippingAddress"
                        )
                        else None
                    ),

                "postal_code":
                    (
                        node[
                            "shippingAddress"
                        ].get(
                            "zip"
                        )
                        if node.get(
                            "shippingAddress"
                        )
                        else None
                    ),

                "order_source":
                    (
                        node[
                            "app"
                        ].get(
                            "name"
                        )
                        if node.get(
                            "app"
                        )
                        else None
                    ),

                "shopify_fee":
                    fee_summary[
                        "shopify_fee"
                    ],

                "fee_found":
                    fee_summary[
                        "fee_found"
                    ],

                "line_items":
                    line_items
            }
        )


    return {
        "success":
            True,

        "configured":
            True,

        "message":
            (
                f"Retrieved "
                f"{len(normalized_orders)} "
                f"Shopify order(s)."
            ),

        "orders":
            normalized_orders,

        "retrieved_at":
            datetime.now()
    }


# ============================================================
# DEMO ORDER
# ============================================================

def get_demo_shopify_order():
    """
    Return a mock Shopify order for UI demonstration.

    Important:
    This is clearly marked as DEMO data.

    The demo order is NOT written to PostgreSQL.
    """

    return {
        "shopify_order_id":
            "DEMO-SHOPIFY-ORDER-1001",

        "order_name":
            "#DEMO-1001",

        "created_at":
            datetime.now().isoformat(),

        "financial_status":
            "PAID",

        "fulfillment_status":
            "FULFILLED",

        # One Combo ($18) and one Slobberin' 2-pack ($18):
        # 1 Original + 3 Slobberin' jars.
        # Tax, shipping and fee are taken from a similar
        # four-jar order in Dr. D's October spreadsheet.
        "product_revenue":
            "36.00",

        "tax_collected":
            "1.04",

        "shipping_revenue":
            "16.00",

        "state":
            "NC",

        "city":
            "Raleigh",

        "postal_code":
            "27607",

        "order_source":
            "Online Store",

        # Demo value. A real order takes the fee from its
        # Shopify Payments transaction.
        "shopify_fee":
            "1.84",

        "fee_found":
            True,

        "line_items": [
            {
                "line_item_id":
                    "DEMO-LINE-1",

                "name":
                    "Dr. D's Original Barbeque Sauce AND Slobberin' Sauce Combo",

                "quantity":
                    1,

                "shopify_variant_id":
                    "DEMO-COMBO-VARIANT",

                "variant_title":
                    "Default Title",

                "product_title":
                    "Original AND Slobberin' Combo (2 jars)",

                "original_unit_price":
                    "18.00",

                "discounted_total":
                    "18.00"
            },

            {
                "line_item_id":
                    "DEMO-LINE-2",

                "name":
                    "Slobberin' Sauce (2 - 16 ounce jars)",

                "quantity":
                    1,

                "shopify_variant_id":
                    "DEMO-SLOBBERIN-2-JARS-VARIANT",

                "variant_title":
                    "Default Title",

                "product_title":
                    "Slobberin' Sauce (2 jars)",

                "original_unit_price":
                    "18.00",

                "discounted_total":
                    "18.00"
            }
        ]
    }