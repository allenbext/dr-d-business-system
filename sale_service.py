"""
sale_service.py

Purpose:
Business logic for recording sauce sales.

Current functionality:

1. Preview a sale WITHOUT saving it (calculation preview).
2. Record a standard sale.
3. Allocate revenue between products.
4. Calculate scholarship contribution.
5. Calculate product cost and estimated profit.
6. Update inventory and create inventory SALE transactions.
7. Record a Farmers Market summary (Cash + Card).
8. Suggest the expected product revenue for a sale.
9. Warn when the entered revenue looks unusual.
10. List recent sales including jars sold.
11. Void (cancel) a sale that was entered by mistake.

Important rules:

Revenue allocation (sales entered on the Record Sale page)
    Retail prices are $10 for one jar and $18 for two.
    - Even jar count: every jar is worth $9.
    - Odd jar count: one jar is the $10 single jar. It is given
      to the sauce bought in the higher quantity; the other
      jars are worth $9.
    - Wholesale: revenue is shared by jar count.
    The entered amount is shared in proportion to these
    weights, so discounts are shared fairly too.
    The Slobberin' Sauce share is rounded to cents first. The
    Original Sauce share is the remainder. Therefore the two
    shares ALWAYS add up to the sale total.
    Shopify orders do not use this rule: they are split by the
    store product actually bought (see shopify_sync_service.py).

Scholarship
    Slobberin' allocated revenue x scholarship rate,
    rounded to cents (half up).

sale_items.sale_price
    Average realized price PER JAR.
    Example: 2 jars sold for $18.00 -> sale_price = 9.00

Farmers Market summary
    Recorded as two sales (Cash and Card) inside ONE
    PostgreSQL transaction. If either part fails, neither
    sale is saved.

Voiding a sale
    Removes the sale, returns the jars to inventory, and
    leaves a permanent note in the inventory audit trail.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import get_connection


# ============================================================
# CONSTANTS
# ============================================================

# Product IDs created by 01_create_core_tables.sql.
ORIGINAL_PRODUCT_ID = 1
SLOBBERIN_PRODUCT_ID = 2

# Standard prices. They are used ONLY to suggest a revenue amount
# and to warn about unusual entries. The revenue Dr. D actually
# enters is always the amount that is saved.
RETAIL_SINGLE_PRICE = Decimal("10.00")     # one jar
RETAIL_PAIR_PRICE = Decimal("18.00")       # two jars
WHOLESALE_PRICE = Decimal("6.00")          # per jar

CENT = Decimal("0.01")


# ============================================================
# MONEY HELPER
# ============================================================

def money(value):
    """
    Convert a value to Decimal rounded to cents (half up).

    Example:
        9.005 -> 9.01
    """

    return Decimal(str(value)).quantize(
        CENT,
        rounding=ROUND_HALF_UP
    )


# ============================================================
# GET PRODUCT
# ============================================================

def get_product(product_id):
    """
    Read one product from PostgreSQL.
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
                WHERE product_id = %s;
                """,
                (product_id,)
            )

            row = cur.fetchone()

    if row is None:

        raise ValueError(
            f"Product ID {product_id} does not exist."
        )

    return {
        "product_id": row[0],
        "product_name": row[1],
        "unit_cost": row[2],
        "scholarship_rate": row[3]
    }


# ============================================================
# SCHOLARSHIP
# ============================================================

def calculate_scholarship(
    allocated_revenue,
    scholarship_rate
):
    """
    Calculate scholarship contribution.

    Formula:

        allocated revenue x scholarship rate

    Rounded to cents (half up).
    """

    return money(
        Decimal(str(allocated_revenue))
        * Decimal(str(scholarship_rate))
    )


# ============================================================
# SUGGESTED REVENUE
# ============================================================

def _retail_jar_weights(original_quantity, slobberin_quantity):
    """Return revenue weights using $9 pairs and one $10 odd jar."""

    original_quantity = int(original_quantity)
    slobberin_quantity = int(slobberin_quantity)

    if original_quantity < 0 or slobberin_quantity < 0:
        raise ValueError("Jar quantities cannot be negative.")

    if (original_quantity + slobberin_quantity) % 2 == 0:
        return (
            Decimal("9.00") * original_quantity,
            Decimal("9.00") * slobberin_quantity
        )

    if original_quantity > slobberin_quantity:
        return (
            Decimal("9.00") * (original_quantity - 1)
            + RETAIL_SINGLE_PRICE,
            Decimal("9.00") * slobberin_quantity
        )

    if slobberin_quantity > original_quantity:
        return (
            Decimal("9.00") * original_quantity,
            Decimal("9.00") * (slobberin_quantity - 1)
            + RETAIL_SINGLE_PRICE
        )

    # An odd total cannot occur when both quantities are equal.
    return (
        Decimal("9.00") * original_quantity,
        Decimal("9.00") * slobberin_quantity
    )


def suggest_product_revenue(
    total_quantity,
    sales_channel,
    original_quantity=None,
    slobberin_quantity=None
):
    """
    Suggest the expected product revenue for a sale.

    Retail (Shopify, Farmers Market, Direct):
        every complete pair is $18; if the jar count is odd, the
        extra $10 jar belongs to the sauce purchased in the higher quantity.

    Wholesale:
        $6 per jar

    This is only a SUGGESTION to save typing.
    Dr. D can always enter a different amount.
    """

    total_quantity = int(total_quantity)

    if total_quantity <= 0:
        return Decimal("0.00")

    if sales_channel == "Wholesale":
        return money(WHOLESALE_PRICE * total_quantity)

    if original_quantity is None or slobberin_quantity is None:
        pairs = total_quantity // 2
        singles = total_quantity % 2
        return money(
            RETAIL_PAIR_PRICE * pairs
            + RETAIL_SINGLE_PRICE * singles
        )

    original_weight, slobberin_weight = _retail_jar_weights(
        original_quantity,
        slobberin_quantity
    )

    return money(original_weight + slobberin_weight)


# ============================================================
# UNUSUAL PRICE WARNING
# ============================================================

def check_price_per_jar(
    total_amount,
    total_quantity,
    sales_channel
):
    """
    Return a warning text when the entered revenue looks
    unusual, or None when it looks normal.

    The warning never blocks a sale. It only helps catch
    typing mistakes such as $1,610 entered as $16,100.

    Retail:
        Expected between $9.00 and $10.00 per jar
        (two for $18 ... one for $10).

    Wholesale:
        Expected $6.00 per jar.
    """

    total_quantity = int(total_quantity)

    total_amount = Decimal(str(total_amount))

    if total_quantity <= 0 or total_amount <= 0:

        return None

    price_per_jar = total_amount / total_quantity

    if sales_channel == "Wholesale":

        if money(price_per_jar) != WHOLESALE_PRICE:

            return (
                f"Average price is ${price_per_jar:,.2f} per jar. "
                f"The usual wholesale price is "
                f"${WHOLESALE_PRICE:,.2f} per jar."
            )

        return None

    lowest = RETAIL_PAIR_PRICE / 2

    if price_per_jar < lowest or price_per_jar > RETAIL_SINGLE_PRICE:

        return (
            f"Average price is ${price_per_jar:,.2f} per jar. "
            f"Retail sales are usually between "
            f"${lowest:,.2f} and ${RETAIL_SINGLE_PRICE:,.2f} per jar. "
            f"Please check the jars and the amount."
        )

    return None


# ============================================================
# INTERNAL CALCULATION
# ============================================================

def _calculate_sale_values(
    total_amount,
    original_quantity,
    slobberin_quantity,
    shipping_revenue,
    shopify_fee,
    shipping_expense,
    original,
    slobberin,
    sales_channel="Direct"
):
    """
    Calculate all financial values for one sale.

    This helper does NOT write anything to PostgreSQL.
    """

    original_quantity = int(original_quantity)
    slobberin_quantity = int(slobberin_quantity)

    if original_quantity < 0 or slobberin_quantity < 0:

        raise ValueError(
            "Jar quantities cannot be negative."
        )

    total_quantity = (
        original_quantity
        + slobberin_quantity
    )

    if total_quantity <= 0:

        raise ValueError(
            "At least one sauce jar must be included."
        )

    total_amount = money(total_amount)
    shipping_revenue = money(shipping_revenue)
    shopify_fee = money(shopify_fee)
    shipping_expense = money(shipping_expense)

    if total_amount <= 0:

        raise ValueError(
            "Product revenue must be greater than zero."
        )

    # --------------------------------------------------------
    # REVENUE ALLOCATION
    #
    # Retail: even jar counts use $9 per jar. An odd jar count
    # assigns the $10 single jar to the higher-quantity sauce.
    # Wholesale: revenue is shared by jar count at $6 per jar.
    #
    # Slobberin' share is rounded to cents first because the
    # scholarship is calculated from it.
    #
    # Original share = total - Slobberin' share.
    #
    # This guarantees:
    #     original_revenue + slobberin_revenue = total_amount
    #
    # Example:
    #     45 Original + 132 Slobberin' for $1,610.00
    #     Slobberin' = 1610 x 132 / 177 = 1200.68
    #     Original   = 1610 - 1200.68   =  409.32
    # --------------------------------------------------------

    revenue_per_jar = (
        total_amount
        / Decimal(total_quantity)
    )

    if sales_channel == "Wholesale":
        original_weight = Decimal(original_quantity)
        slobberin_weight = Decimal(slobberin_quantity)
    else:
        original_weight, slobberin_weight = _retail_jar_weights(
            original_quantity,
            slobberin_quantity
        )

    allocation_total = original_weight + slobberin_weight

    if allocation_total <= 0:
        slobberin_revenue = money("0.00")
    else:
        slobberin_revenue = money(
            total_amount
            * slobberin_weight
            / allocation_total
        )

    original_revenue = (
        total_amount
        - slobberin_revenue
    )

    # --------------------------------------------------------
    # SCHOLARSHIP
    # --------------------------------------------------------

    original_scholarship = calculate_scholarship(
        original_revenue,
        original["scholarship_rate"]
    )

    slobberin_scholarship = calculate_scholarship(
        slobberin_revenue,
        slobberin["scholarship_rate"]
    )

    total_scholarship = (
        original_scholarship
        + slobberin_scholarship
    )

    # --------------------------------------------------------
    # PRODUCT COST
    # --------------------------------------------------------

    original_product_cost = money(
        original["unit_cost"] * original_quantity
    )

    slobberin_product_cost = money(
        slobberin["unit_cost"] * slobberin_quantity
    )

    total_product_cost = (
        original_product_cost
        + slobberin_product_cost
    )

    # --------------------------------------------------------
    # ESTIMATED PROFIT
    # --------------------------------------------------------

    estimated_profit = money(
        total_amount
        + shipping_revenue
        - shopify_fee
        - shipping_expense
        - total_product_cost
        - total_scholarship
    )

    return {
        "total_amount": total_amount,
        "total_quantity": total_quantity,
        "original_quantity": original_quantity,
        "slobberin_quantity": slobberin_quantity,
        "revenue_per_jar": revenue_per_jar,
        "original_revenue": original_revenue,
        "slobberin_revenue": slobberin_revenue,
        "original_scholarship": original_scholarship,
        "slobberin_scholarship": slobberin_scholarship,
        "total_scholarship": total_scholarship,
        "total_product_cost": total_product_cost,
        "shipping_revenue": shipping_revenue,
        "shopify_fee": shopify_fee,
        "shipping_expense": shipping_expense,
        "estimated_profit": estimated_profit
    }


# ============================================================
# PREVIEW SALE (NO DATABASE WRITE)
# ============================================================

def preview_sale(
    total_amount,
    original_quantity=0,
    slobberin_quantity=0,
    sales_channel="Farmers Market",
    shipping_revenue=0.00,
    shopify_fee=0.00,
    shipping_expense=0.00
):
    """
    Calculate what a sale WOULD do, without saving anything.

    The Streamlit page uses this to show a Calculation Preview
    before Dr. D clicks "Record Sale":

        - revenue allocated to each product
        - scholarship contribution
        - product cost and estimated profit
        - inventory before and after the sale
        - a warning when the price per jar looks unusual

    record_sale() uses exactly the same calculation, so the
    previewed numbers and the saved numbers always match.

    Raises ValueError for an incomplete entry
    (no jars or no revenue).
    """

    original = get_product(ORIGINAL_PRODUCT_ID)
    slobberin = get_product(SLOBBERIN_PRODUCT_ID)

    values = _calculate_sale_values(
        total_amount=total_amount,
        original_quantity=original_quantity,
        slobberin_quantity=slobberin_quantity,
        shipping_revenue=shipping_revenue,
        shopify_fee=shopify_fee,
        shipping_expense=shipping_expense,
        original=original,
        slobberin=slobberin,
        sales_channel=sales_channel
    )

    # --------------------------------------------------------
    # CURRENT INVENTORY
    # --------------------------------------------------------

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    product_id,
                    current_quantity
                FROM inventory
                WHERE product_id IN (%s, %s);
                """,
                (
                    ORIGINAL_PRODUCT_ID,
                    SLOBBERIN_PRODUCT_ID
                )
            )

            inventory = {
                row[0]: row[1]
                for row in cur.fetchall()
            }

    original_before = inventory.get(ORIGINAL_PRODUCT_ID, 0)
    slobberin_before = inventory.get(SLOBBERIN_PRODUCT_ID, 0)

    original_after = (
        original_before
        - values["original_quantity"]
    )

    slobberin_after = (
        slobberin_before
        - values["slobberin_quantity"]
    )

    values.update(
        {
            "original_inventory_before": original_before,
            "original_inventory_after": original_after,
            "slobberin_inventory_before": slobberin_before,
            "slobberin_inventory_after": slobberin_after,

            # False means record_sale() would be rejected.
            "enough_inventory": (
                original_after >= 0
                and slobberin_after >= 0
            ),

            # None means the price looks normal.
            "price_warning": check_price_per_jar(
                total_amount=values["total_amount"],
                total_quantity=values["total_quantity"],
                sales_channel=sales_channel
            )
        }
    )

    return values


# ============================================================
# INTERNAL DATABASE INSERT
# ============================================================

def _insert_sale(
    cur,
    sale_date,
    total_amount,
    original_quantity,
    slobberin_quantity,
    sales_channel,
    payment_method,
    tax_collected,
    shipping_revenue,
    shopify_fee,
    shipping_expense,
    state,
    county,
    original,
    slobberin
):
    """
    Insert one complete sale using an EXISTING cursor.

    This helper is important because it lets multiple sales
    participate in one database transaction.

    Used by:
    - record_sale()
    - record_market_summary()
    """

    tax_collected = money(tax_collected)

    values = _calculate_sale_values(
        total_amount=total_amount,
        original_quantity=original_quantity,
        slobberin_quantity=slobberin_quantity,
        shipping_revenue=shipping_revenue,
        shopify_fee=shopify_fee,
        shipping_expense=shipping_expense,
        original=original,
        slobberin=slobberin,
        sales_channel=sales_channel
    )

    # ========================================================
    # INSERT SALE HEADER
    # ========================================================

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
            county
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING sale_id;
        """,
        (
            sale_date,
            sales_channel,
            payment_method,
            values["total_amount"],
            tax_collected,
            values["shipping_revenue"],
            values["shopify_fee"],
            values["shipping_expense"],
            state,
            county
        )
    )

    sale_id = cur.fetchone()[0]

    # ========================================================
    # ONE LINE PER PRODUCT
    #
    # The same three steps are repeated for each product that
    # is part of the sale:
    #
    #   1. sale_items row
    #   2. inventory decrease (with a negative-stock guard)
    #   3. inventory audit transaction
    # ========================================================

    lines = [
        (
            original,
            values["original_quantity"],
            values["original_revenue"],
            values["original_scholarship"]
        ),
        (
            slobberin,
            values["slobberin_quantity"],
            values["slobberin_revenue"],
            values["slobberin_scholarship"]
        )
    ]

    for product, quantity, allocated_revenue, scholarship in lines:

        if quantity == 0:

            continue

        # ----------------------------------------------------
        # 1. SALE ITEM
        #
        # sale_price = average realized price PER JAR.
        # ----------------------------------------------------

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
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (
                sale_id,
                product["product_id"],
                quantity,
                money(allocated_revenue / quantity),
                allocated_revenue,
                scholarship
            )
        )

        # ----------------------------------------------------
        # 2. INVENTORY GUARD
        #
        # The WHERE condition prevents inventory from
        # becoming negative.
        # ----------------------------------------------------

        cur.execute(
            """
            UPDATE inventory
            SET current_quantity = current_quantity - %s
            WHERE product_id = %s
              AND current_quantity >= %s;
            """,
            (
                quantity,
                product["product_id"],
                quantity
            )
        )

        if cur.rowcount == 0:

            raise ValueError(
                f"Not enough {product['product_name']} inventory."
            )

        # ----------------------------------------------------
        # 3. INVENTORY AUDIT TRAIL
        # ----------------------------------------------------

        cur.execute(
            """
            INSERT INTO inventory_transactions (
                product_id,
                transaction_date,
                transaction_type,
                quantity_change,
                sale_id,
                notes
            )
            VALUES (%s, %s, 'SALE', %s, %s, %s);
            """,
            (
                product["product_id"],
                sale_date,
                -quantity,
                sale_id,
                f"Inventory reduction from sale #{sale_id}."
            )
        )

    # ========================================================
    # RETURN RESULT
    # ========================================================

    return {
        "sale_id": sale_id,
        "sale_date": sale_date,
        "sales_channel": sales_channel,
        "payment_method": payment_method,
        "total_amount": values["total_amount"],
        "original_quantity": values["original_quantity"],
        "slobberin_quantity": values["slobberin_quantity"],
        "original_revenue": values["original_revenue"],
        "slobberin_revenue": values["slobberin_revenue"],
        "original_scholarship": values["original_scholarship"],
        "slobberin_scholarship": values["slobberin_scholarship"],
        "total_scholarship": values["total_scholarship"],
        "total_product_cost": values["total_product_cost"],
        "tax_collected": tax_collected,
        "shipping_revenue": values["shipping_revenue"],
        "shopify_fee": values["shopify_fee"],
        "shipping_expense": values["shipping_expense"],
        "state": state,
        "county": county,
        "estimated_profit": values["estimated_profit"]
    }


# ============================================================
# STANDARD SALE
# ============================================================

def record_sale(
    total_amount,
    original_quantity=0,
    slobberin_quantity=0,
    sales_channel="Farmers Market",
    payment_method="Cash",
    tax_collected=0.00,
    shipping_revenue=0.00,
    shopify_fee=0.00,
    shipping_expense=0.00,
    state=None,
    county=None,
    sale_date=None
):
    """
    Record one standard sale.
    """

    if sale_date is None:

        sale_date = date.today()

    original = get_product(ORIGINAL_PRODUCT_ID)
    slobberin = get_product(SLOBBERIN_PRODUCT_ID)

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                result = _insert_sale(
                    cur=cur,
                    sale_date=sale_date,
                    total_amount=total_amount,
                    original_quantity=original_quantity,
                    slobberin_quantity=slobberin_quantity,
                    sales_channel=sales_channel,
                    payment_method=payment_method,
                    tax_collected=tax_collected,
                    shipping_revenue=shipping_revenue,
                    shopify_fee=shopify_fee,
                    shipping_expense=shipping_expense,
                    state=state,
                    county=county,
                    original=original,
                    slobberin=slobberin
                )

            conn.commit()

        except Exception:

            conn.rollback()

            raise

    return result


# ============================================================
# FARMERS MARKET SUMMARY
# ============================================================

def record_market_summary(
    sale_date,
    cash_original_quantity,
    cash_slobberin_quantity,
    cash_revenue,
    card_original_quantity,
    card_slobberin_quantity,
    card_revenue,
    card_fee=0.00,
    cash_tax=0.00,
    card_tax=0.00,
    state="NC",
    county=None
):
    """
    Record one Farmers Market event summary.

    Dr. D can enter:

    CASH:
        - Original jars
        - Slobberin' jars
        - Cash collected

    CARD:
        - Original jars
        - Slobberin' jars
        - Card revenue
        - Card processing fee

    The system creates up to two sales:
        1. Cash
        2. Card

    Both sales happen inside ONE PostgreSQL transaction.

    If one fails, the entire market summary rolls back.
    """

    cash_total_quantity = (
        cash_original_quantity
        + cash_slobberin_quantity
    )

    card_total_quantity = (
        card_original_quantity
        + card_slobberin_quantity
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    if cash_total_quantity == 0 and card_total_quantity == 0:

        raise ValueError(
            "Enter at least one jar sold."
        )

    if cash_total_quantity > 0 and Decimal(str(cash_revenue)) <= 0:

        raise ValueError(
            "Cash revenue must be greater than zero "
            "when cash jars were sold."
        )

    if card_total_quantity > 0 and Decimal(str(card_revenue)) <= 0:

        raise ValueError(
            "Card revenue must be greater than zero "
            "when card jars were sold."
        )

    original = get_product(ORIGINAL_PRODUCT_ID)
    slobberin = get_product(SLOBBERIN_PRODUCT_ID)

    cash_result = None
    card_result = None

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # =============================================
                # CASH SUMMARY
                # =============================================

                if cash_total_quantity > 0:

                    cash_result = _insert_sale(
                        cur=cur,
                        sale_date=sale_date,
                        total_amount=cash_revenue,
                        original_quantity=cash_original_quantity,
                        slobberin_quantity=cash_slobberin_quantity,
                        sales_channel="Farmers Market",
                        payment_method="Cash",
                        tax_collected=cash_tax,
                        shipping_revenue=0,
                        shopify_fee=0,
                        shipping_expense=0,
                        state=state,
                        county=county,
                        original=original,
                        slobberin=slobberin
                    )

                # =============================================
                # CARD SUMMARY
                # =============================================

                if card_total_quantity > 0:

                    card_result = _insert_sale(
                        cur=cur,
                        sale_date=sale_date,
                        total_amount=card_revenue,
                        original_quantity=card_original_quantity,
                        slobberin_quantity=card_slobberin_quantity,
                        sales_channel="Farmers Market",
                        payment_method="Card",
                        tax_collected=card_tax,
                        shipping_revenue=0,
                        shopify_fee=card_fee,
                        shipping_expense=0,
                        state=state,
                        county=county,
                        original=original,
                        slobberin=slobberin
                    )

            conn.commit()

        except Exception:

            conn.rollback()

            raise

    # ========================================================
    # COMBINED MARKET TOTALS
    # ========================================================

    total_revenue = Decimal("0.00")
    total_scholarship = Decimal("0.00")
    total_profit = Decimal("0.00")

    for part in (cash_result, card_result):

        if part is not None:

            total_revenue += part["total_amount"]
            total_scholarship += part["total_scholarship"]
            total_profit += part["estimated_profit"]

    return {
        "sale_date": sale_date,
        "cash_sale": cash_result,
        "card_sale": card_result,
        "total_original_quantity": (
            cash_original_quantity
            + card_original_quantity
        ),
        "total_slobberin_quantity": (
            cash_slobberin_quantity
            + card_slobberin_quantity
        ),
        "total_revenue": total_revenue,
        "total_scholarship": total_scholarship,
        "estimated_profit": total_profit
    }


# ============================================================
# RECENT SALES (WITH JARS)
# ============================================================

def get_recent_sales_with_items(limit=20):
    """
    Return the most recent sales, one row per sale,
    including how many jars of each sauce were sold.

    Used by:
        - the Dashboard "Latest Sales" table
        - the "Void a sale" selector
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    s.sale_id,
                    s.sale_date,
                    s.sales_channel,
                    s.payment_method,
                    s.total_amount,
                    s.tax_collected,
                    s.state,
                    s.county,

                    COALESCE(
                        SUM(si.quantity) FILTER (
                            WHERE si.product_id = %s
                        ),
                        0
                    ) AS original_quantity,

                    COALESCE(
                        SUM(si.quantity) FILTER (
                            WHERE si.product_id = %s
                        ),
                        0
                    ) AS slobberin_quantity,

                    COALESCE(
                        SUM(si.scholarship_amount),
                        0
                    ) AS scholarship

                FROM sales AS s

                LEFT JOIN sale_items AS si
                    ON s.sale_id = si.sale_id

                GROUP BY
                    s.sale_id

                ORDER BY
                    s.sale_date DESC,
                    s.sale_id DESC

                LIMIT %s;
                """,
                (
                    ORIGINAL_PRODUCT_ID,
                    SLOBBERIN_PRODUCT_ID,
                    limit
                )
            )

            rows = cur.fetchall()

    sales = []

    for row in rows:

        sales.append(
            {
                "sale_id": row[0],
                "sale_date": row[1],
                "sales_channel": row[2],
                "payment_method": row[3],
                "product_revenue": row[4],
                "tax_collected": row[5],
                "state": row[6],
                "county": row[7],
                "original_quantity": int(row[8]),
                "slobberin_quantity": int(row[9]),
                "scholarship": row[10]
            }
        )

    return sales


# ============================================================
# VOID SALE
# ============================================================

def void_sale(
    sale_id,
    reason=None
):
    """
    Cancel a sale that was entered by mistake.

    Everything happens inside ONE PostgreSQL transaction:

    1. The jars are returned to inventory.

    2. A SALE_VOID transaction (+jars) is added to the inventory
       audit trail. Its note records the sale number, date,
       channel, amount and reason.

    3. The original SALE transactions stay in the audit trail,
       but they are disconnected from the sale and marked
       as voided.

    4. The sale and its sale_items are deleted.

    Result:

    - Revenue, scholarship, profit and forecast reports no
      longer include the sale. No report query has to change.

    - The inventory audit trail still shows that the sale
      existed and why it was cancelled.
    """

    void_date = date.today()

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # ---------------------------------------------
                # READ THE SALE
                #
                # FOR UPDATE locks the row so the same sale
                # cannot be voided twice at the same moment.
                # ---------------------------------------------

                cur.execute(
                    """
                    SELECT
                        sale_date,
                        sales_channel,
                        payment_method,
                        total_amount
                    FROM sales
                    WHERE sale_id = %s
                    FOR UPDATE;
                    """,
                    (sale_id,)
                )

                sale_row = cur.fetchone()

                if sale_row is None:

                    raise ValueError(
                        f"Sale #{sale_id} does not exist."
                    )

                sale_date = sale_row[0]
                sales_channel = sale_row[1]
                payment_method = sale_row[2]
                total_amount = sale_row[3]

                note = (
                    f"Voided sale #{sale_id} "
                    f"({sale_date}, {sales_channel}, "
                    f"{payment_method}, ${total_amount:,.2f})."
                )

                if reason and reason.strip():

                    note += f" Reason: {reason.strip()}"

                # ---------------------------------------------
                # READ THE PRODUCTS IN THE SALE
                # ---------------------------------------------

                cur.execute(
                    """
                    SELECT
                        si.product_id,
                        p.product_name,
                        si.quantity
                    FROM sale_items AS si
                    JOIN products AS p
                        ON si.product_id = p.product_id
                    WHERE si.sale_id = %s
                    ORDER BY si.product_id;
                    """,
                    (sale_id,)
                )

                items = cur.fetchall()

                returned = []

                for product_id, product_name, quantity in items:

                    # -----------------------------------------
                    # 1. RETURN JARS TO INVENTORY
                    # -----------------------------------------

                    cur.execute(
                        """
                        UPDATE inventory
                        SET current_quantity = current_quantity + %s
                        WHERE product_id = %s
                        RETURNING current_quantity;
                        """,
                        (
                            quantity,
                            product_id
                        )
                    )

                    new_quantity = cur.fetchone()[0]

                    # -----------------------------------------
                    # 2. AUDIT TRAIL: SALE_VOID
                    # -----------------------------------------

                    cur.execute(
                        """
                        INSERT INTO inventory_transactions (
                            product_id,
                            transaction_date,
                            transaction_type,
                            quantity_change,
                            notes
                        )
                        VALUES (%s, %s, 'SALE_VOID', %s, %s);
                        """,
                        (
                            product_id,
                            void_date,
                            quantity,
                            note
                        )
                    )

                    returned.append(
                        {
                            "product_id": product_id,
                            "product_name": product_name,
                            "quantity_returned": quantity,
                            "new_inventory_quantity": new_quantity
                        }
                    )

                # ---------------------------------------------
                # 3. KEEP THE ORIGINAL SALE MOVEMENTS
                #
                # They are disconnected from the sale
                # (sale_id = NULL) so the sale can be deleted,
                # and their note explains what happened.
                # ---------------------------------------------

                cur.execute(
                    """
                    UPDATE inventory_transactions
                    SET
                        sale_id = NULL,
                        notes = COALESCE(notes, '')
                                || ' [Sale #' || %s || ' was voided on '
                                || %s || '.]'
                    WHERE sale_id = %s;
                    """,
                    (
                        str(sale_id),
                        str(void_date),
                        sale_id
                    )
                )

                # ---------------------------------------------
                # 4. DELETE THE SALE
                # ---------------------------------------------

                cur.execute(
                    """
                    DELETE FROM sale_items
                    WHERE sale_id = %s;
                    """,
                    (sale_id,)
                )

                cur.execute(
                    """
                    DELETE FROM sales
                    WHERE sale_id = %s;
                    """,
                    (sale_id,)
                )

            conn.commit()

        except Exception:

            conn.rollback()

            raise

    return {
        "sale_id": sale_id,
        "sale_date": sale_date,
        "sales_channel": sales_channel,
        "payment_method": payment_method,
        "total_amount": total_amount,
        "returned": returned,
        "note": note
    }