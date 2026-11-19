-- ============================================================
-- 12_shopify_product_contents.sql
--
-- Purpose:
-- Record how many jars of each sauce one Shopify product holds.
--
-- WHY THIS IS NEEDED
--
-- Dr. D's Shopify store sells five products:
--
--   Shopify product                          Original  Slobberin'
--   ---------------------------------------  --------  ----------
--   Dr. D's Original (1 jar)        $10          1          0
--   Slobberin' Sauce (1 jar)        $10          0          1
--   Dr. D's Original (2 jars)       $18          2          0
--   Slobberin' Sauce (2 jars)       $18          0          2
--   Original AND Slobberin' Combo   $18          1          1
--
-- Before this script, one Shopify product could be connected to
-- ONE local product only, and one unit was counted as ONE jar.
-- That gave wrong results for the store's own products:
--
--   - A 2-jar pack lowered inventory by 1 jar instead of 2.
--   - A Combo was counted as one sauce only, so its scholarship
--     was $0.00 or $2.88 instead of $1.44.
--
-- After this script, every connection stores the CONTENTS of one
-- unit: original_jars and slobberin_jars. A Combo is 1 + 1.
--
-- The application then splits the revenue of each Shopify line
-- by its own contents. Example: Combo $18 -> $9 Original and
-- $9 Slobberin', scholarship 16% of $9 = $1.44.
--
-- WHAT THE SCRIPT CHANGES
--
--   1. Adds original_jars and slobberin_jars.
--   2. Fills them for existing connections from product_id
--      (one jar of the connected sauce, as before).
--   3. Makes product_id optional, because a Combo belongs to
--      both sauces. product_id is kept for existing rows.
--   4. Adds a rule: no negative jars, at least one jar in total.
--
-- Safe to run more than once. Requires script 07.
-- ============================================================


BEGIN;


-- ============================================================
-- STEP 1: NEW COLUMNS
-- ============================================================

ALTER TABLE shopify_product_map
    ADD COLUMN IF NOT EXISTS original_jars INTEGER NOT NULL DEFAULT 0;

ALTER TABLE shopify_product_map
    ADD COLUMN IF NOT EXISTS slobberin_jars INTEGER NOT NULL DEFAULT 0;


-- ============================================================
-- STEP 2: FILL EXISTING CONNECTIONS
--
-- Only rows that have no contents yet (0 + 0) are changed.
-- product_id 1 = Original, product_id 2 = Slobberin'.
-- ============================================================

UPDATE shopify_product_map
SET
    original_jars  = CASE WHEN product_id = 1 THEN 1 ELSE 0 END,
    slobberin_jars = CASE WHEN product_id = 2 THEN 1 ELSE 0 END,
    updated_at     = CURRENT_TIMESTAMP

WHERE original_jars = 0
  AND slobberin_jars = 0;


-- ============================================================
-- STEP 3: product_id BECOMES OPTIONAL
--
-- A Combo holds both sauces, so it has no single product.
-- The foreign key stays: when product_id is filled in, it must
-- still point to an existing product.
-- ============================================================

ALTER TABLE shopify_product_map
    ALTER COLUMN product_id DROP NOT NULL;


-- ============================================================
-- STEP 4: CONTENTS RULE
--
-- ADD CONSTRAINT has no IF NOT EXISTS, so the constraint is
-- created only when it is missing.
-- ============================================================

DO $$
BEGIN

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_shopify_product_map_contents'
    ) THEN

        ALTER TABLE shopify_product_map
            ADD CONSTRAINT chk_shopify_product_map_contents
            CHECK (
                original_jars >= 0
                AND slobberin_jars >= 0
                AND original_jars + slobberin_jars > 0
            );

    END IF;

END;
$$;


COMMENT ON COLUMN shopify_product_map.original_jars IS
    'Jars of Dr. D''s Original Sauce in ONE unit of this Shopify product.';

COMMENT ON COLUMN shopify_product_map.slobberin_jars IS
    'Jars of Slobberin'' Sauce in ONE unit of this Shopify product.';


COMMIT;


-- ============================================================
-- CHECK
--
-- Every connection with its contents.
-- ============================================================

SELECT
    shopify_variant_id,
    shopify_product_name,
    original_jars,
    slobberin_jars,
    active

FROM shopify_product_map

ORDER BY
    shopify_product_map_id;

