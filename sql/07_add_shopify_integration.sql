-- ============================================================
-- 07_add_shopify_integration.sql
--
-- Purpose:
-- Prepare PostgreSQL for future Shopify integration.
--
-- Safe to run even if some columns/tables already exist.
-- ============================================================


-- ============================================================
-- 0. PREPARE SALES TABLE FOR EXTERNAL SOURCES
--
-- source_type tells us where the sale came from:
--
-- MANUAL
-- SHOPIFY
-- etc.
--
-- source_reference stores the unique external record ID.
-- For Shopify this will be the Shopify Order GraphQL ID.
-- ============================================================

ALTER TABLE sales
ADD COLUMN IF NOT EXISTS
    source_type VARCHAR(50)
    DEFAULT 'MANUAL';


ALTER TABLE sales
ADD COLUMN IF NOT EXISTS
    source_reference VARCHAR(255);


-- ============================================================
-- 1. SHOPIFY PRODUCT MAP
-- ============================================================

CREATE TABLE IF NOT EXISTS shopify_product_map (

    shopify_product_map_id SERIAL PRIMARY KEY,

    shopify_variant_id VARCHAR(255) NOT NULL UNIQUE,

    product_id INTEGER NOT NULL,

    shopify_product_name VARCHAR(255),

    active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_shopify_product_map_product

        FOREIGN KEY (
            product_id
        )

        REFERENCES products (
            product_id
        )
);


-- ============================================================
-- 2. SHOPIFY SYNC LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS shopify_sync_log (

    sync_id SERIAL PRIMARY KEY,

    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMP,

    status VARCHAR(30) NOT NULL DEFAULT 'STARTED',

    orders_found INTEGER NOT NULL DEFAULT 0,

    orders_imported INTEGER NOT NULL DEFAULT 0,

    orders_skipped INTEGER NOT NULL DEFAULT 0,

    orders_failed INTEGER NOT NULL DEFAULT 0,

    message TEXT,

    CONSTRAINT chk_shopify_sync_status

        CHECK (
            status IN (
                'STARTED',
                'SUCCESS',
                'PARTIAL',
                'FAILED'
            )
        ),

    CONSTRAINT chk_shopify_sync_counts

        CHECK (
            orders_found >= 0
            AND orders_imported >= 0
            AND orders_skipped >= 0
            AND orders_failed >= 0
        )
);


-- ============================================================
-- 3. DUPLICATE PROTECTION
--
-- One external order should only appear once in sales.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_sales_source_reference

ON sales (
    source_type,
    source_reference
)

WHERE source_reference IS NOT NULL;


-- ============================================================
-- 4. INDEX FOR SOURCE LOOKUPS
-- ============================================================

CREATE INDEX IF NOT EXISTS
    idx_sales_source_type

ON sales (
    source_type
);


-- ============================================================
-- 5. INDEX FOR SYNC HISTORY
-- ============================================================

CREATE INDEX IF NOT EXISTS
    idx_shopify_sync_log_started_at

ON shopify_sync_log (
    started_at DESC
);


-- ============================================================
-- 6. INDEX FOR ACTIVE PRODUCT MAPPINGS
-- ============================================================

CREATE INDEX IF NOT EXISTS
    idx_shopify_product_map_active

ON shopify_product_map (
    active
);


-- ============================================================
-- 7. VALIDATION
-- ============================================================

SELECT
    column_name,
    data_type

FROM information_schema.columns

WHERE table_name = 'sales'

  AND column_name IN (
      'source_type',
      'source_reference'
  )

ORDER BY
    column_name;


SELECT
    table_name

FROM information_schema.tables

WHERE table_schema = 'public'

  AND table_name IN (
      'shopify_product_map',
      'shopify_sync_log'
  )

ORDER BY
    table_name;


SELECT
    indexname,
    indexdef

FROM pg_indexes

WHERE tablename = 'sales'

  AND indexname IN (
      'uq_sales_source_reference',
      'idx_sales_source_type'
  )

ORDER BY
    indexname;
















