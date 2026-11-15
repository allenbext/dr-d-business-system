-- ============================================================
-- 04_inventory_batches_and_transactions.sql
--
-- Purpose:
-- Add a proper inventory history system.
--
-- We already have:
--
-- inventory
--     = current inventory balance
--
-- Now we add:
--
-- inventory_batches
--     = batches received from the manufacturer
--
-- inventory_transactions
--     = every inventory increase or decrease
--
-- This allows us to answer:
--
-- - When did inventory arrive?
-- - Which product was received?
-- - How many jars were received?
-- - What batch did the jars belong to?
-- - Why did inventory decrease?
-- - Was inventory used for a sale, sample, donation, etc.?
--
-- Safe to run more than once:
--   - tables and indexes are created only when they are missing;
--   - the opening balance is recorded only for a product that
--     has no inventory movements yet.
-- ============================================================

-- ============================================================
-- 1. CREATE INVENTORY_BATCHES TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS inventory_batches (

    -- Unique internal PostgreSQL ID for the batch.
    batch_id SERIAL PRIMARY KEY,

    -- Product that belongs to this batch.
    -- Example:
    -- 1 = Dr. D's Original Sauce
    -- 2 = Slobberin' Sauce
    product_id INTEGER NOT NULL
        REFERENCES products(product_id),

    -- Human-readable batch identifier.
    -- This could be:
    -- BATCH-2026-001
    -- NOV-2026-ORIGINAL
    -- or a manufacturer lot number.
    --
    -- We allow Dr. D to enter the value manually.
    batch_code VARCHAR(100) NOT NULL,

    -- Date when Dr. D received the batch
    -- from the manufacturer.
    received_date DATE NOT NULL,

    -- Number of jars received in this batch.
    quantity_received INTEGER NOT NULL
        CHECK (quantity_received > 0),

    -- Optional manufacturer / supplier name.
    -- We keep this optional because there may currently
    -- be only one manufacturer.
    manufacturer VARCHAR(150),

    -- Optional notes.
    -- Examples:
    -- "Holiday production run"
    -- "Some jars had low fill"
    -- "Received 10 replacement jars"
    notes TEXT,

    -- Timestamp showing when the record
    -- was created in our system.
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Prevent the same batch code from being entered twice
    -- for the same product.
    UNIQUE (product_id, batch_code)
);

-- ============================================================
-- 2. CREATE INVENTORY_TRANSACTIONS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS inventory_transactions (

    -- Unique ID for this inventory movement.
    transaction_id SERIAL PRIMARY KEY,

    -- Product whose inventory changed.
    product_id INTEGER NOT NULL
        REFERENCES products(product_id),

    -- Batch is optional.
    -- A RECEIPT will normally have a batch_id.
    -- A sale may not always be tied to one specific batch
    -- in our first prototype.
        
    batch_id INTEGER
        REFERENCES inventory_batches(batch_id),

    -- Date of the inventory movement.
    transaction_date DATE NOT NULL,

    -- Reason inventory changed.
    -- Examples:
    -- OPENING_BALANCE
    -- RECEIPT
    -- SALE
    -- SAMPLE
    -- DONATION
    -- BROKEN
    -- GIFT
    -- REPLACEMENT
    -- ADJUSTMENT
    transaction_type VARCHAR(50) NOT NULL,

    -- Quantity change.
    -- Positive numbers increase inventory:
    -- RECEIPT +100
    -- Negative numbers decrease inventory:
    -- SALE -2
    -- SAMPLE -1
    -- DONATION -12
    quantity_change INTEGER NOT NULL
        CHECK (quantity_change <> 0),

    -- Optional connection to the sale that caused
    -- the inventory decrease.
    -- For example:
    -- Sale #25 sells two jars.
    -- inventory_transactions.sale_id = 25
    sale_id INTEGER
        REFERENCES sales(sale_id),

    -- Optional notes explaining the movement.
    notes TEXT,

    -- Timestamp showing when the transaction
    -- was entered into the database.
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. CREATE INDEXES
--
-- Indexes are not required for correctness,
-- but they make common searches faster.
-- ============================================================

-- Helps us quickly find inventory history
-- for a specific product.
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_product
ON inventory_transactions(product_id);

-- Helps us quickly find inventory history
-- by transaction date.
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_date
ON inventory_transactions(transaction_date);

-- Helps us find transactions connected
-- to a particular batch.
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_batch
ON inventory_transactions(batch_id);

-- ============================================================
-- 4. RECORD CURRENT INVENTORY AS OPENING BALANCE
--
-- IMPORTANT:
-- We already have inventory in the system from our earlier
-- tests, but inventory_transactions did not exist yet.
--
-- Therefore, we create ONE opening balance transaction
-- for each product.
-- Example:
--
-- Current inventory:
-- Original = 91
-- Slobberin = 88
--
-- We record:
--
-- OPENING_BALANCE +91
-- OPENING_BALANCE +88
--
-- We DO NOT change inventory.current_quantity here.
--
-- This simply establishes the starting point for our new
-- inventory history system.
-- ============================================================

INSERT INTO inventory_transactions (
    product_id,
    transaction_date,
    transaction_type,
    quantity_change,
    notes
)
SELECT
    product_id,
    CURRENT_DATE,
    'OPENING_BALANCE',
    current_quantity,
    'Opening balance created when inventory transaction tracking was introduced.'
FROM inventory
WHERE current_quantity <> 0

  -- Only for a product without ANY inventory movement.
  -- When the script is run again, the audit trail already
  -- exists, so no second opening balance is created.
  AND NOT EXISTS (
      SELECT 1
      FROM inventory_transactions AS it
      WHERE it.product_id = inventory.product_id
  );

-- ============================================================
-- 5. CHECK INVENTORY BATCH TABLE
-- ============================================================

SELECT *
FROM inventory_batches
ORDER BY batch_id;

-- ============================================================
-- 6. CHECK INVENTORY TRANSACTION HISTORY
-- ============================================================

SELECT
    it.transaction_id,
    it.transaction_date,
    p.product_name,
    it.transaction_type,
    it.quantity_change,
    it.batch_id,
    it.sale_id,
    it.notes
FROM inventory_transactions AS it
JOIN products AS p
    ON it.product_id = p.product_id
ORDER BY it.transaction_id;


-- ============================================================
-- 7. CHECK CURRENT INVENTORY
-- ============================================================

SELECT
    p.product_id,
    p.product_name,
    i.current_quantity
FROM inventory AS i
JOIN products AS p
    ON i.product_id = p.product_id
ORDER BY p.product_id;








