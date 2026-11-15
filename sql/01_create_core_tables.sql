-- ============================================================
-- 01_create_core_tables.sql
-- Purpose:
-- Create the first core tables for Dr. D's business database.
-- These tables will store:
--   1. Products
--   2. Sales
--   3. Items inside each sale
--   4. Current inventory
--
-- Safe to run more than once:
--   - CREATE TABLE IF NOT EXISTS skips a table that already exists;
--   - the two products and their starting inventory are added
--     only when they are missing.
-- Existing data is never changed.
-- ============================================================

-- ============================================================
-- TABLE 1: products
-- This table stores the product catalog.
-- For now, we will add:
--   - Dr. D's Original Sauce
--   - Slobberin' Sauce
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    -- Unique ID for each product.
    -- SERIAL automatically generates values 1, 2, 3, ...
    -- PRIMARY KEY means each product_id must be unique.
    product_id SERIAL PRIMARY KEY,

    -- Product name.
    -- VARCHAR(100) means text up to 100 characters.
    -- NOT NULL means the name is required.
    product_name VARCHAR(100) NOT NULL,

    -- Cost to Dr. D for one unit of the product.
    -- For sauce, we currently assume $3.00 per jar.
    -- NUMERIC(10,2) is appropriate for money:
    -- up to 10 total digits, with 2 digits after the decimal point.
    unit_cost NUMERIC(10,2) NOT NULL,

    -- Scholarship rate associated with the product.
    -- Original Sauce = 0.00
    -- Slobberin' Sauce = 0.16
    --
    -- DEFAULT 0 means PostgreSQL will automatically use 0
    -- if no scholarship rate is provided.
    scholarship_rate NUMERIC(5,4) NOT NULL DEFAULT 0
);

-- ============================================================
-- TABLE 2: sales
-- This table stores one record for each sale/order.
--
-- Example:
-- Sale #1
-- Date: 2026-11-12
-- Channel: Farmers Market
-- Payment Method: Cash
-- Total Amount: $18.00
--
-- The individual products inside the sale will NOT be stored here.
-- They will be stored in the sale_items table.
-- ============================================================

CREATE TABLE IF NOT EXISTS sales (
    -- Unique ID for each sale.
    -- PostgreSQL generates this automatically.
    sale_id SERIAL PRIMARY KEY,

    -- Date when the sale happened.
    -- DATE stores values such as 2026-11-12.
    -- NOT NULL means every sale must have a date.
    sale_date DATE NOT NULL,

    -- Where the sale came from.
    -- Examples:
    -- Shopify
    -- Farmers Market
    -- Wholesale
    sales_channel VARCHAR(50),

    -- How the customer paid.
    -- Examples:
    -- Cash
    -- Card
    -- Shopify
    payment_method VARCHAR(50),

    -- Total amount of the sale.
    -- Example: 18.00
    total_amount NUMERIC(10,2) NOT NULL
);


-- ============================================================
-- TABLE 3: sale_items
-- This table stores the products included inside each sale.
-- One sale can contain multiple products.
-- Example:
-- Sale #10
--   1 Original Sauce
--   1 Slobberin' Sauce
-- Instead of creating many product columns inside "sales",
-- we store one row per product sold.
-- ============================================================

CREATE TABLE IF NOT EXISTS sale_items (

    -- Unique ID for each line item.
    -- Example:
    -- sale_item_id 1 = Original Sauce in Sale #10
    -- sale_item_id 2 = Slobberin' Sauce in Sale #10
    sale_item_id SERIAL PRIMARY KEY,

    -- Identifies which sale this item belongs to.
    -- Example:
    -- sale_id = 10
    -- This will connect to sales.sale_id.
    sale_id INTEGER NOT NULL,

    -- Identifies which product was sold.
    -- Example:
    -- product_id = 1 → Original Sauce
    -- product_id = 2 → Slobberin' Sauce
    product_id INTEGER NOT NULL,

    -- Number of units sold for this product.
    -- CHECK (quantity > 0) prevents invalid values
    -- such as 0 or -5.
    quantity INTEGER NOT NULL CHECK (quantity > 0),

    -- Price associated with this item.
    -- Example:
    -- one jar = 10.00
    -- two-jar bundle = 18.00
    sale_price NUMERIC(10,2) NOT NULL,

    -- Revenue assigned to this product.
    -- This is especially important for mixed sales.
     -- Example:
    -- Original + Slobberin' bundle = $18
    -- Original allocated revenue = $9
    -- Slobberin' allocated revenue = $9
    allocated_revenue NUMERIC(10,2),

    -- Scholarship amount calculated for this line item.
    -- Example:
    -- Slobberin' allocated revenue = $9
    -- Scholarship rate = 16%
    -- Scholarship amount = $1.44
    -- Original Sauce would normally have 0 here.
    scholarship_amount NUMERIC(10,2),

    -- --------------------------------------------------------
    -- FOREIGN KEY:
    -- Connects sale_items.sale_id to sales.sale_id.
    -- This means a sale item cannot reference a sale
    -- that does not exist.
    -- --------------------------------------------------------
    CONSTRAINT fk_sale
        FOREIGN KEY (sale_id)
        REFERENCES sales(sale_id),

    -- --------------------------------------------------------
    -- FOREIGN KEY:
    -- Connects sale_items.product_id to products.product_id.
    -- This prevents us from recording a sale for a product
    -- that is not in our product catalog.
    -- --------------------------------------------------------
    CONSTRAINT fk_product
        FOREIGN KEY (product_id)
        REFERENCES products(product_id)
);

-- ============================================================
-- TABLE 4: inventory
-- This table stores the current inventory quantity
-- for each product.
-- Example:
-- Product 1 → 100 jars
-- Product 2 → 100 jars
-- Later, when a sale is recorded,
-- Python will reduce these values automatically.
-- ============================================================

CREATE TABLE IF NOT EXISTS inventory (
    -- product_id is also the PRIMARY KEY here.
    -- That means each product can have only one
    -- current inventory record.
    product_id INTEGER PRIMARY KEY,

    -- Current number of units available.
    -- DEFAULT 0 means a new product starts at 0
    -- unless we specify another quantity.
    -- CHECK prevents inventory from becoming negative.
    current_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (current_quantity >= 0),

    -- --------------------------------------------------------
    -- FOREIGN KEY:
    -- Connects inventory.product_id to products.product_id.
    -- This means inventory can exist only for products
    -- already stored in the products table.
    -- --------------------------------------------------------
    CONSTRAINT fk_inventory_product
        FOREIGN KEY (product_id)
        REFERENCES products(product_id)
);


-- ============================================================
-- INSERT INITIAL PRODUCTS
-- Now we add the two sauce products.
-- ============================================================

-- The products are added only when the products table is EMPTY.
--
-- On a new database this creates:
--   product_id 1 = Dr. D's Original Sauce
--   product_id 2 = Slobberin' Sauce
--
-- When the script is run again, the table is not empty,
-- so nothing is inserted and no duplicates are created.

INSERT INTO products (
    product_name,
    unit_cost,
    scholarship_rate
)
SELECT
    new_product.product_name,
    new_product.unit_cost,
    new_product.scholarship_rate

FROM (
    VALUES
        -- Original Sauce:
        -- Unit cost = $3.00
        -- No NC State scholarship contribution
        ('Dr. D''s Original Sauce', 3.00, 0.00),

        -- Slobberin' Sauce:
        -- Unit cost = $3.00
        -- 16% scholarship contribution
        ('Slobberin'' Sauce', 3.00, 0.16)

) AS new_product (product_name, unit_cost, scholarship_rate)

WHERE NOT EXISTS (
    SELECT 1
    FROM products
);

-- ============================================================
-- INSERT TEST INVENTORY
-- For now, we start with 100 jars of each sauce.
-- We are using this only for testing.
-- Later we can replace these values with real inventory.
-- ============================================================

-- One inventory row is created for every product that does
-- not have one yet.
--
-- ON CONFLICT (product_id) DO NOTHING means:
-- if the product already has an inventory row, leave it as it is.
-- A current balance is therefore never reset to 100.

INSERT INTO inventory (
    product_id,
    current_quantity
)
SELECT
    product_id,
    100

FROM products

ON CONFLICT (product_id) DO NOTHING;

-- ============================================================
-- TEST QUERIES
-- ============================================================


-- Show all products.
SELECT *
FROM products;


-- Show current inventory.
SELECT *
FROM inventory;


















