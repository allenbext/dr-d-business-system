# Database Setup

Run the SQL scripts in numerical order on an empty database
named `dr_d_business`.

| # | Script | What it does |
|---|---|---|
| 01 | `01_create_core_tables.sql` | Creates `products`, `sales`, `sale_items` and `inventory`; adds the two sauces. |
| 02 | `02_test_sale_transaction.sql` | Records one mixed sale by hand to show how the tables work together in a transaction. |
| 03 | `03_expand_sales_table.sql` | Adds tax, shipping, fee, state and county to `sales`. |
| 04 | `04_inventory_batches_and_transactions.sql` | Adds manufacturer batches and the inventory audit trail. |
| 05 | `05_create_forecast_tables.sql` | Adds monthly seasonal settings and saved forecasts. |
| 06 | `06_load_compact_demo_dataset.sql` | Removes all transactions and loads the demonstration dataset. All dates are relative to the day the script is run. |
| 07 | `07_add_shopify_integration.sql` | Adds Shopify product mapping, synchronization log and external-source tracking. |
| 08 | `08_forecast_integrity.sql` | Allows only one saved forecast per product / region / channel / week. |
| 09 | `09_sale_price_per_jar.sql` | Makes `sale_items.sale_price` the average price per jar in every row. |
| 10 | `10_reporting_views_and_constraints.sql` | Creates the views `v_sale_financials` and `v_scholarship_lines`; adds CHECK constraints for sales channel, payment method and inventory movement type. |

## Which scripts can be run again

- **06** can be run at any time to reset the demonstration data. Run it again shortly before a presentation so the dates line up with the current week.
- **07, 08, 09 and 10** are safe to run more than once.
- **01 – 05** create tables and are meant to be run once on an empty database.

## Check after setup

The last queries of script 06 show the expected results:
inventory 1,025 and 371 jars, the scholarship report month with
4 jars and $5.92, and the completed forecast 120 vs actual 110.
