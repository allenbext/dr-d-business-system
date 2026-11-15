"""
inventory_service.py

Purpose:
This file contains inventory-related business logic.

Current functionality:

1. Read current inventory levels and their estimated value.
2. Receive a new manufacturer batch.
3. Show manufacturer batch history.
4. Show inventory transaction history.
5. Record non-sale inventory adjustments.
6. Record a physical jar count and correct the balance.
7. Summarize inventory movements by reason.
8. Check that the balance agrees with the audit trail.

Supported inventory movements include:

- OPENING_BALANCE
- RECEIPT
- SALE
- SALE_VOID
- SAMPLE
- DONATION
- BROKEN
- GIFT
- REPLACEMENT
- ADJUSTMENT

The inventory table stores the current balance.

The inventory_transactions table stores the audit trail
that explains WHY the current balance changed.

Inventory equation:

    Beginning stock
    + jars received
    - jars sold
    - samples / donations / broken / gifts / replacements
    +/- corrections
    = expected ending stock
"""

from db import get_connection


# ============================================================
# FRIENDLY NAMES FOR MOVEMENT TYPES
#
# The database stores short codes such as "BROKEN".
# Screens and Excel reports show these friendly names.
#
# Keeping the list in ONE place means app.py and
# report_service.py always show the same wording.
# ============================================================

TRANSACTION_LABELS = {
    "OPENING_BALANCE": "Opening Balance",
    "RECEIPT": "Batch Receipt",
    "SALE": "Sale",
    "SALE_VOID": "Voided Sale",
    "SAMPLE": "Sample",
    "DONATION": "Donation",
    "BROKEN": "Broken / Damaged",
    "GIFT": "Gift",
    "REPLACEMENT": "Replacement Shipment",
    "ADJUSTMENT": "Manual Correction"
}


# ============================================================
# GET CURRENT INVENTORY
# ============================================================

def get_current_inventory():
    """
    Read current inventory levels from PostgreSQL.

    Returns:
        List of dictionaries, one per product.

    Example:
        [
            {
                "product_id": 1,
                "product_name": "Dr. D's Original Sauce",
                "current_quantity": 95,
                "unit_cost": Decimal("3.00"),
                "estimated_value": Decimal("285.00")
            },
            ...
        ]

    estimated_value = current_quantity x products.unit_cost

    The unit cost is read from the products table, so the
    inventory value changes automatically if the cost per jar
    is updated there.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    p.product_id,
                    p.product_name,
                    i.current_quantity,
                    p.unit_cost,
                    (p.unit_cost * i.current_quantity)
                        AS estimated_value
                FROM inventory AS i
                JOIN products AS p
                    ON i.product_id = p.product_id
                ORDER BY p.product_id;
                """
            )

            rows = cur.fetchall()


    inventory = []

    for row in rows:

        inventory.append(
            {
                "product_id": row[0],
                "product_name": row[1],
                "current_quantity": row[2],
                "unit_cost": row[3],
                "estimated_value": row[4]
            }
        )

    return inventory


# ============================================================
# RECEIVE NEW INVENTORY BATCH
# ============================================================

def receive_batch(
    product_id,
    batch_code,
    received_date,
    quantity_received,
    manufacturer=None,
    notes=None
):
    """
    Record a new manufacturer batch.

    The function performs three connected operations:

    1. Create inventory_batches record.
    2. Create RECEIPT transaction.
    3. Increase inventory.current_quantity.

    Everything happens inside one PostgreSQL transaction.
    """

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if quantity_received <= 0:

        raise ValueError(
            "Quantity received must be greater than zero."
        )

    if not batch_code or not batch_code.strip():

        raise ValueError(
            "Batch code cannot be empty."
        )


    # --------------------------------------------------------
    # DATABASE TRANSACTION
    # --------------------------------------------------------

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # ------------------------------------------------
                # VERIFY PRODUCT EXISTS
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        product_id,
                        product_name
                    FROM products
                    WHERE product_id = %s;
                    """,
                    (
                        product_id,
                    )
                )

                product_row = cur.fetchone()

                if product_row is None:

                    raise ValueError(
                        f"Product ID {product_id} does not exist."
                    )

                product_name = product_row[1]


                # ------------------------------------------------
                # CREATE BATCH
                # ------------------------------------------------

                cur.execute(
                    """
                    INSERT INTO inventory_batches (
                        product_id,
                        batch_code,
                        received_date,
                        quantity_received,
                        manufacturer,
                        notes
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING batch_id;
                    """,
                    (
                        product_id,
                        batch_code.strip(),
                        received_date,
                        quantity_received,
                        manufacturer,
                        notes
                    )
                )

                batch_id = cur.fetchone()[0]


                # ------------------------------------------------
                # CREATE RECEIPT TRANSACTION
                # ------------------------------------------------

                cur.execute(
                    """
                    INSERT INTO inventory_transactions (
                        product_id,
                        batch_id,
                        transaction_date,
                        transaction_type,
                        quantity_change,
                        notes
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        'RECEIPT',
                        %s,
                        %s
                    )
                    RETURNING transaction_id;
                    """,
                    (
                        product_id,
                        batch_id,
                        received_date,
                        quantity_received,
                        notes
                    )
                )

                transaction_id = cur.fetchone()[0]


                # ------------------------------------------------
                # INCREASE CURRENT INVENTORY
                # ------------------------------------------------

                cur.execute(
                    """
                    UPDATE inventory
                    SET current_quantity =
                        current_quantity + %s
                    WHERE product_id = %s;
                    """,
                    (
                        quantity_received,
                        product_id
                    )
                )

                if cur.rowcount == 0:

                    raise ValueError(
                        f"No inventory record exists "
                        f"for product ID {product_id}."
                    )


                # ------------------------------------------------
                # READ NEW INVENTORY BALANCE
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        current_quantity
                    FROM inventory
                    WHERE product_id = %s;
                    """,
                    (
                        product_id,
                    )
                )

                new_quantity = cur.fetchone()[0]


            conn.commit()


        except Exception:

            conn.rollback()

            raise


    return {
        "batch_id": batch_id,
        "transaction_id": transaction_id,
        "product_id": product_id,
        "product_name": product_name,
        "batch_code": batch_code.strip(),
        "received_date": received_date,
        "quantity_received": quantity_received,
        "manufacturer": manufacturer,
        "notes": notes,
        "new_inventory_quantity": new_quantity
    }


# ============================================================
# RECORD MANUAL INVENTORY ADJUSTMENT
# ============================================================

def record_inventory_adjustment(
    product_id,
    transaction_date,
    transaction_type,
    quantity,
    notes=None
):
    """
    Record an inventory change that is NOT a normal sale
    and NOT a manufacturer receipt.

    Supported examples:

        SAMPLE
        DONATION
        BROKEN
        GIFT
        REPLACEMENT
        ADJUSTMENT

    For most transaction types, inventory decreases.

    Example:

        transaction_type = "DONATION"
        quantity = 12

    Inventory transaction stored:

        quantity_change = -12

    ADJUSTMENT is special.

    For ADJUSTMENT, the quantity may be positive or negative.

    Example:

        quantity = 5

        means:
        inventory +5

    Example:

        quantity = -3

        means:
        inventory -3
    """

    # --------------------------------------------------------
    # VALIDATE TRANSACTION TYPE
    # --------------------------------------------------------

    allowed_types = [
        "SAMPLE",
        "DONATION",
        "BROKEN",
        "GIFT",
        "REPLACEMENT",
        "ADJUSTMENT"
    ]

    if transaction_type not in allowed_types:

        raise ValueError(
            f"Unsupported inventory transaction type: "
            f"{transaction_type}"
        )


    # --------------------------------------------------------
    # VALIDATE QUANTITY
    # --------------------------------------------------------

    if quantity == 0:

        raise ValueError(
            "Inventory adjustment quantity cannot be zero."
        )


    # --------------------------------------------------------
    # DETERMINE QUANTITY CHANGE
    # --------------------------------------------------------

    if transaction_type == "ADJUSTMENT":

        # ADJUSTMENT may increase or decrease inventory.
        #
        # Example:
        # +5 if physical count shows 5 more jars.
        #
        # -3 if physical count shows 3 fewer jars.
        quantity_change = quantity

    else:

        # SAMPLE, DONATION, BROKEN, GIFT and REPLACEMENT
        # all decrease inventory.
        #
        # The user enters a positive number such as 12.
        #
        # We store it as -12.
        quantity_change = -abs(quantity)


    # --------------------------------------------------------
    # START DATABASE TRANSACTION
    # --------------------------------------------------------

    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # ------------------------------------------------
                # VERIFY PRODUCT
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        product_id,
                        product_name
                    FROM products
                    WHERE product_id = %s;
                    """,
                    (
                        product_id,
                    )
                )

                product_row = cur.fetchone()

                if product_row is None:

                    raise ValueError(
                        f"Product ID {product_id} does not exist."
                    )

                product_name = product_row[1]


                # ------------------------------------------------
                # UPDATE INVENTORY
                #
                # We prevent current_quantity from going
                # below zero.
                # ------------------------------------------------

                cur.execute(
                    """
                    UPDATE inventory
                    SET current_quantity =
                        current_quantity + %s
                    WHERE product_id = %s
                      AND current_quantity + %s >= 0;
                    """,
                    (
                        quantity_change,
                        product_id,
                        quantity_change
                    )
                )


                # If zero rows were updated,
                # the adjustment would make inventory negative.
                if cur.rowcount == 0:

                    raise ValueError(
                        "This inventory adjustment would make "
                        "the inventory balance negative."
                    )


                # ------------------------------------------------
                # CREATE INVENTORY TRANSACTION
                # ------------------------------------------------

                cur.execute(
                    """
                    INSERT INTO inventory_transactions (
                        product_id,
                        transaction_date,
                        transaction_type,
                        quantity_change,
                        notes
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING transaction_id;
                    """,
                    (
                        product_id,
                        transaction_date,
                        transaction_type,
                        quantity_change,
                        notes
                    )
                )

                transaction_id = cur.fetchone()[0]


                # ------------------------------------------------
                # READ UPDATED INVENTORY
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        current_quantity
                    FROM inventory
                    WHERE product_id = %s;
                    """,
                    (
                        product_id,
                    )
                )

                new_quantity = cur.fetchone()[0]


            conn.commit()


        except Exception:

            conn.rollback()

            raise


    return {
        "transaction_id": transaction_id,
        "product_id": product_id,
        "product_name": product_name,
        "transaction_date": transaction_date,
        "transaction_type": transaction_type,
        "quantity_change": quantity_change,
        "new_inventory_quantity": new_quantity,
        "notes": notes
    }


# ============================================================
# GET INVENTORY BATCH HISTORY
# ============================================================

def get_inventory_batches():
    """
    Return all manufacturer batches.

    Newest batches appear first.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    b.batch_id,
                    b.batch_code,
                    b.received_date,
                    p.product_name,
                    b.quantity_received,
                    b.manufacturer,
                    b.notes
                FROM inventory_batches AS b
                JOIN products AS p
                    ON b.product_id = p.product_id
                ORDER BY
                    b.received_date DESC,
                    b.batch_id DESC;
                """
            )

            rows = cur.fetchall()


    batches = []

    for row in rows:

        batches.append(
            {
                "batch_id": row[0],
                "batch_code": row[1],
                "received_date": row[2],
                "product_name": row[3],
                "quantity_received": row[4],
                "manufacturer": row[5],
                "notes": row[6]
            }
        )

    return batches


# ============================================================
# GET INVENTORY TRANSACTION HISTORY
# ============================================================

def get_inventory_transactions(limit=100):
    """
    Return recent inventory movements.

    Possible transaction types include:

    OPENING_BALANCE
    RECEIPT
    SALE
    SALE_VOID
    SAMPLE
    DONATION
    BROKEN
    GIFT
    REPLACEMENT
    ADJUSTMENT
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    it.transaction_id,
                    it.transaction_date,
                    p.product_name,
                    it.transaction_type,
                    it.quantity_change,
                    b.batch_code,
                    it.sale_id,
                    it.notes
                FROM inventory_transactions AS it
                JOIN products AS p
                    ON it.product_id = p.product_id
                LEFT JOIN inventory_batches AS b
                    ON it.batch_id = b.batch_id
                ORDER BY
                    it.transaction_id DESC
                LIMIT %s;
                """,
                (
                    limit,
                )
            )

            rows = cur.fetchall()


    transactions = []

    for row in rows:

        transactions.append(
            {
                "transaction_id": row[0],
                "transaction_date": row[1],
                "product_name": row[2],
                "transaction_type": row[3],
                "quantity_change": row[4],
                "batch_code": row[5],
                "sale_id": row[6],
                "notes": row[7]
            }
        )

    return transactions


# ============================================================
# RECORD PHYSICAL COUNT
# ============================================================

def record_physical_count(
    product_id,
    count_date,
    counted_quantity,
    notes=None
):
    """
    Compare the system balance with the jars Dr. D actually
    counted, and correct the balance if they differ.

    Example:

        System balance   = 366 jars
        Physical count   = 364 jars
        Difference       = -2 jars

    The function then:

    1. Creates an ADJUSTMENT transaction of -2 with a note
       that records both numbers.
    2. Sets inventory.current_quantity to 364.

    If the count matches the system balance, nothing is
    changed and no transaction is created.

    Everything happens inside one PostgreSQL transaction.
    """

    counted_quantity = int(counted_quantity)

    if counted_quantity < 0:

        raise ValueError(
            "Counted quantity cannot be negative."
        )


    with get_connection() as conn:

        try:

            with conn.cursor() as cur:

                # ------------------------------------------------
                # READ AND LOCK THE CURRENT BALANCE
                #
                # FOR UPDATE prevents a sale from changing the
                # balance while the count is being recorded.
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        p.product_name,
                        i.current_quantity
                    FROM inventory AS i
                    JOIN products AS p
                        ON i.product_id = p.product_id
                    WHERE i.product_id = %s
                    FOR UPDATE OF i;
                    """,
                    (
                        product_id,
                    )
                )

                row = cur.fetchone()

                if row is None:

                    raise ValueError(
                        f"No inventory record exists "
                        f"for product ID {product_id}."
                    )

                product_name = row[0]

                system_quantity = row[1]

                difference = (
                    counted_quantity
                    - system_quantity
                )

                transaction_id = None


                # ------------------------------------------------
                # CORRECT THE BALANCE ONLY IF IT DIFFERS
                # ------------------------------------------------

                if difference != 0:

                    full_note = (
                        f"Physical count: system showed "
                        f"{system_quantity}, counted "
                        f"{counted_quantity} "
                        f"(difference {difference:+d})."
                    )

                    if notes and notes.strip():

                        full_note += f" {notes.strip()}"


                    cur.execute(
                        """
                        INSERT INTO inventory_transactions (
                            product_id,
                            transaction_date,
                            transaction_type,
                            quantity_change,
                            notes
                        )
                        VALUES (
                            %s,
                            %s,
                            'ADJUSTMENT',
                            %s,
                            %s
                        )
                        RETURNING transaction_id;
                        """,
                        (
                            product_id,
                            count_date,
                            difference,
                            full_note
                        )
                    )

                    transaction_id = cur.fetchone()[0]


                    cur.execute(
                        """
                        UPDATE inventory
                        SET current_quantity = %s
                        WHERE product_id = %s;
                        """,
                        (
                            counted_quantity,
                            product_id
                        )
                    )


            conn.commit()


        except Exception:

            conn.rollback()

            raise


    return {
        "product_id": product_id,
        "product_name": product_name,
        "count_date": count_date,
        "system_quantity": system_quantity,
        "counted_quantity": counted_quantity,
        "difference": difference,

        # True when the count agreed with the system.
        "matched": difference == 0,

        # None when no correction was needed.
        "transaction_id": transaction_id
    }


# ============================================================
# INVENTORY MOVEMENT SUMMARY
# ============================================================

def get_inventory_movement_summary():
    """
    Summarize all inventory movements by product and reason.

    This is the inventory equation in numbers:

        received - sold - samples - donations ... = on hand

    Returns one dictionary per product.

    Example:

        {
            "product_id": 2,
            "product_name": "Slobberin' Sauce",
            "movements": {
                "RECEIPT": 1191,
                "SALE": -815,
                "SAMPLE": -5
            },
            "current_quantity": 371
        }
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    p.product_id,
                    p.product_name,
                    i.current_quantity,
                    it.transaction_type,
                    SUM(it.quantity_change) AS total_change

                FROM products AS p

                JOIN inventory AS i
                    ON p.product_id = i.product_id

                LEFT JOIN inventory_transactions AS it
                    ON p.product_id = it.product_id

                GROUP BY
                    p.product_id,
                    p.product_name,
                    i.current_quantity,
                    it.transaction_type

                ORDER BY
                    p.product_id,
                    it.transaction_type;
                """
            )

            rows = cur.fetchall()


    summary = {}

    for row in rows:

        product_id = row[0]

        if product_id not in summary:

            summary[product_id] = {
                "product_id": product_id,
                "product_name": row[1],
                "current_quantity": row[2],
                "movements": {}
            }

        # A product without any movement has transaction_type NULL.
        if row[3] is not None:

            summary[product_id]["movements"][row[3]] = int(row[4])


    return list(
        summary.values()
    )


# ============================================================
# INVENTORY RECONCILIATION CHECK
# ============================================================

def get_inventory_reconciliation():
    """
    Check that the current balance agrees with the audit trail.

    For every product:

        ledger_quantity = SUM(inventory_transactions.quantity_change)

    should be equal to:

        inventory.current_quantity

    A difference means the balance was changed without an
    audit record (for example by editing the table by hand).

    Returns one dictionary per product.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    p.product_id,
                    p.product_name,
                    i.current_quantity,

                    COALESCE(
                        SUM(it.quantity_change),
                        0
                    ) AS ledger_quantity

                FROM products AS p

                JOIN inventory AS i
                    ON p.product_id = i.product_id

                LEFT JOIN inventory_transactions AS it
                    ON p.product_id = it.product_id

                GROUP BY
                    p.product_id,
                    p.product_name,
                    i.current_quantity

                ORDER BY
                    p.product_id;
                """
            )

            rows = cur.fetchall()


    results = []

    for row in rows:

        current_quantity = row[2]

        ledger_quantity = int(row[3])

        results.append(
            {
                "product_id": row[0],
                "product_name": row[1],
                "current_quantity": current_quantity,
                "ledger_quantity": ledger_quantity,
                "difference": (
                    current_quantity
                    - ledger_quantity
                ),
                "balanced": (
                    current_quantity
                    == ledger_quantity
                )
            }
        )

    return results