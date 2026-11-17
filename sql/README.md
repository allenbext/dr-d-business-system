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
| 11 | `11_load_volume_dataset.sql` | Removes all transactions and loads the large simulated dataset: two years of history, about 19,000 records. All dates are relative to the day the script is run. |

## Running the scripts again

Every script can be run more than once without an error.

- **01, 03, 04, 05** create tables, columns and indexes only when they
  are missing (`IF NOT EXISTS`). The two products, their inventory rows
  and the 12 seasonal settings are inserted only when they are missing.
  Existing data is not changed.
- **06** removes all transactions and reloads the demonstration data.
  Run it again shortly before a presentation so the dates line up with
  the current week.
- **07, 08, 09, 10** only add what is missing.
- **11** removes all transactions and reloads the large dataset. The
  random numbers use a fixed seed, so two runs on the same day give
  exactly the same data. Run it again shortly before a presentation.
- **02** is a learning script. Each run records one more test sale and
  lowers the inventory by one jar per product without an audit record.
  Do not run it by itself on a database that is in use. Script 06
  removes the test sale again.

Running the complete set 01 – 11 again on an existing database ends in
the same state as a new installation.

## Two datasets

Scripts 06 and 11 each replace all transactions. The one that is run
last decides what is in the database.

| | 06 compact | 11 volume |
|---|---|---|
| Sales | 12 | about 6,000 |
| Records in all tables | about 70 | about 19,000 |
| Purpose | every number can be checked by hand | realistic reports, query performance |
| Scholarship report month | 4 jars, $5.92 | 4 jars, $5.92 |
| Completed forecast | 120 vs 110 | 120 vs 110 |
| Next-week forecast | 117 | 117 |

The data in both scripts is simulated. It is not Dr. D's real sales
history.

## Database dump

`dr_d_business_dump.sql` in the project root is a complete copy of the
database (structure and data) made with `pg_dump` after script 11.
To restore it into an empty database:

```
psql -U postgres -d dr_d_business -f dr_d_business_dump.sql
```

The dump contains fixed dates. For a live demonstration run script 11
instead, so the dates line up with the current week.

## Check after setup

The last queries of script 06 show the expected results:
inventory 1,025 and 371 jars, the scholarship report month with
4 jars and $5.92, and the completed forecast 120 vs actual 110.

The last queries of script 11 show the record count of every table
(the total is above 10,000), sales by channel, the inventory balance
compared with the audit trail, the same scholarship report month
(4 jars, $5.92) and the same completed forecast (120 vs 110).
