# Dr. D's Business Management System

ISE 519 Project — Database Applications in Industrial & Systems Engineering
Team 5: Alena Bobneva, Aniket Pawar, Mahesh Ghodake

A PostgreSQL + Python + Streamlit prototype that replaces the manual
spreadsheet used to run Dr. D's Original Barbeque Sauce and
NC State Slobberin' Sauce.

Sales are entered once. Inventory, the 16% NC State scholarship
contribution, profit, reports and the demand forecast are updated
automatically.


## The business problem

Dr. D sells two products through Shopify, wholesale accounts, farmers
markets and direct sales. Slobberin' Sauce is licensed by NC State:
16% of its revenue goes to student scholarships and is reported to the
Collegiate Licensing Company on the 1st of every month.

Today every order is typed into a spreadsheet by hand: sale price, tax,
Shopify fee, shipping revenue, shipping expense, scholarship, jars sold,
state and county. Inventory is kept separately in Shopify and in the
spreadsheet. Mixed sales (one Original + one Slobberin' for $18) make
the scholarship calculation easy to get wrong.


## What the system does

| Phase 1 function | Where in the application |
|---|---|
| 1. Automated sale entry and scholarship calculation | Record Sale → Standard Sale, Market Summary |
| 2. Automatic inventory tracking | Every recorded sale; Inventory page |
| 3. Seasonal demand forecasting and accuracy tracking | Forecast → Create Forecast, Accuracy, Seasonal Settings |
| Bonus 4. Monthly scholarship report | Scholarship page, Excel report |

Added beyond the Phase 1 scope:

- Farmers Market summary: jars and cash/card totals entered once after the event.
- Calculation Preview before a sale is saved, with a warning for an unusual price per jar.
- Cancel a sale entered by mistake, with a note in the inventory audit trail.
- Manufacturer batches, samples, donations, damaged jars, gifts, replacement shipments.
- Physical inventory count with automatic correction.
- Inventory audit trail and reconciliation check.
- Dashboard with revenue, estimated profit and scholarship due.
- Excel reports: Business Report, Monthly Scholarship Report, Inventory Report.
- Shopify integration layer (prepared; live import is switched off until store credentials are provided).


## Architecture

```
Manual entry        Farmers Market summary        Shopify (future)
      \                      |                        /
       +---------------------+-----------------------+
                             |
                    Python service layer
        (sale, inventory, scholarship, forecast, report)
                             |
                        PostgreSQL
                  (the system of record)
                             |
        Streamlit pages  ·  Excel reports  ·  Dashboard
```

- **PostgreSQL** stores everything and enforces the rules (keys, CHECK constraints, unique indexes, views).
- **Service files** contain the business logic. Each write is one database transaction: a sale, its line items, the inventory decrease and the audit record are saved together or not at all.
- **Streamlit pages** only collect input and display results.
- **Excel** is a reporting copy, never the source of data.


## Technology

Python · Streamlit · PostgreSQL · psycopg 3 · pandas · Plotly · openpyxl · requests · python-dotenv

DBeaver is used to run the SQL scripts and inspect the database.


## Project structure

```
app.py                      Sidebar navigation; opens the selected page
ui_helpers.py               Styles, cards, formatting, cached Excel reports

page_dashboard.py           Dashboard
page_record_sale.py         Record Sale (Standard, Market Summary, Recent Sales)
page_inventory.py           Inventory (Receive Batch, Count, Other Movement)
page_scholarship.py         Scholarship Report
page_forecast.py            Demand Forecast
shopify_ui.py               Shopify page

sale_service.py             Record / preview / cancel sales, revenue allocation
inventory_service.py        Batches, movements, physical count, reconciliation
scholarship_service.py      Scholarship summaries and detail
forecast_service.py         Exponential smoothing with seasonal factors
dashboard_service.py        Dashboard KPIs
report_service.py           Excel reports

shopify_service.py          Shopify GraphQL Admin API client
shopify_sync_service.py     Duplicate check, product mapping, order preview
shopify_import_service.py   Writes a Shopify order to the database (not enabled)

db.py                       PostgreSQL connection (reads .env)
.env.example                Template for the local .env file
.streamlit/config.toml      Theme and toolbar settings
requirements.txt            Python packages
sql/                        Database scripts 01 - 11 (see sql/README.md)
```


## Database

| Table | Purpose |
|---|---|
| `products` | Product catalog with unit cost and scholarship rate |
| `sales` | One row per sale: date, channel, payment, revenue, tax, fees, shipping, location, source |
| `sale_items` | Products inside a sale: jars, price per jar, allocated revenue, scholarship |
| `inventory` | Current balance per product |
| `inventory_batches` | Batches received from the co-packer |
| `inventory_transactions` | Audit trail of every inventory movement |
| `forecast_seasonality` | Demand tier and seasonal factor for each month |
| `forecasts` | Saved forecasts with actual sales and difference |
| `shopify_product_map` | Shopify variant → local product |
| `shopify_sync_log` | History of synchronization attempts |

| View | Purpose |
|---|---|
| `v_sale_financials` | One row per sale with product cost, scholarship and estimated profit. The profit formula exists only here. |
| `v_scholarship_lines` | Sold lines of products whose scholarship rate is greater than zero |

Integrity rules enforced by the database:

- Foreign keys between sales, sale items, products, inventory and forecasts.
- `CHECK` constraints: positive quantities, non-negative inventory, allowed sales channels, payment methods, inventory movement types and demand tiers.
- Unique index: one Shopify order can be imported only once.
- Unique index: one saved forecast per product / region / channel / week.


## Business rules

**Revenue.** `sales.total_amount` is product revenue only. Sales tax is stored separately and is not revenue.

**Revenue allocation.** Both sauces have the same price, so the revenue of a mixed sale is shared by jar count. The Slobberin' share is rounded to cents; the Original share is the remainder, so the two always add up to the sale total.

**Scholarship.** Slobberin' allocated revenue × 16% (rate stored in `products.scholarship_rate`), based on the revenue actually received.

| Sale | Slobberin' revenue | Scholarship |
|---|---|---|
| 1 Slobberin' for $10 | $10.00 | $1.60 |
| 2 Slobberin' for $18 | $18.00 | $2.88 |
| 1 Original + 1 Slobberin' for $18 | $9.00 | $1.44 |
| Wholesale Slobberin' at $6 | $6.00 | $0.96 |

**Estimated profit.** Product revenue + shipping revenue − product cost − scholarship − Shopify/card fees − shipping expense. It is an operating estimate; overhead such as mileage, event fees and packaging is outside the system.

**Forecast.** Weekly jars sold (complete weeks only; a week without sales counts as zero) are divided by the seasonal factor of their month, smoothed with exponential smoothing (default α = 0.30), and multiplied by the seasonal factor of the forecast month. A saved forecast never changes; after the week ends it is compared with actual sales.

```
new estimate = α × this week's demand + (1 − α) × previous estimate
forecast     = baseline × seasonal factor
```


## Installation

Developed with Python 3.14 on Windows. The scripts and pages were also
tested with Python 3.13, PostgreSQL 16 and Streamlit 1.67.

1. Create and activate a virtual environment, then install the packages:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Create an empty PostgreSQL database named `dr_d_business`.

3. Copy `.env.example` to `.env` and enter the PostgreSQL user name and password. The `.env` file is ignored by Git and must never be committed.

4. Run the scripts in the `sql/` folder in numerical order, 01 through 11 (see `sql/README.md`).

5. Start the application from the project folder:

   ```powershell
   streamlit run app.py
   ```


## Demonstration data

`sql/06_load_compact_demo_dataset.sql` removes all transactions and loads a small, internally consistent dataset. **All dates are relative to the day the script is run**, so the Dashboard, the forecast history and the completed forecast always line up with "today".

Run the script again shortly before a demonstration (in the same week). It can be run at any time after the other scripts.

`sql/11_load_volume_dataset.sql` loads the large dataset instead: two years of simulated history with about 6,000 sales and about 19,000 records in all tables (Shopify orders one by one, Saturday market summaries, wholesale deliveries, direct sales, samples and donations, production batches). It keeps the same control numbers: the scholarship report month has 4 jars and $5.92, the completed forecast is 120 vs 110, and the next-week forecast is 117. The script that is run last decides which dataset is in the database. The table below describes the compact dataset; inventory and channel totals are different in the large one.

All of this data is simulated. It is not Dr. D's real sales history.

After loading:

| Check | Expected |
|---|---|
| Original Sauce inventory | 1,025 jars |
| Slobberin' Sauce inventory | 371 jars |
| Scholarship report, three months ago | 4 jars · $37.00 · $5.92 |
| Completed forecast, last week | baseline 100 × 1.20 = 120, actual 110, difference −10 |
| Forecast for next week (Slobberin', Wake, Shopify) | 97.5 × 1.20 = 117 |


## Demonstration walk-through

1. **Dashboard** — revenue, estimated profit and scholarship due this month; stock and weeks of supply.
2. **Record Sale → Standard Sale** — enter 1 Original + 1 Slobberin'. The revenue fills in as $18.00. The preview shows $9.00 / $9.00, scholarship $1.44 and inventory 1,025 → 1,024 and 371 → 370. Click Record Sale.
3. **Record Sale → Market Summary** — cash 45 Original + 132 Slobberin', $1,610. The check shows $9.10 per jar, Slobberin' revenue $1,200.68 and scholarship $192.11. Type $16,100 to show the unusual-price warning.
4. **Record Sale → Recent Sales** — the new sales with jars; cancel one to show that the jars return to inventory.
5. **Inventory** — both products decreased automatically; Count Inventory; Where the Jars Went; audit trail.
6. **Scholarship** — select the month three months ago: 4 jars, $5.92. Download the monthly report.
7. **Forecast → Create Forecast** — Slobberin', Wake, Shopify. Last week shows the saved forecast of 120. Next week shows 117; save it.
8. **Forecast → Accuracy** — forecast 120, actual 110, difference −10.
9. **Shopify** — not connected; demo order preview; product mapping.
10. **Dashboard → Export Business Report** — the Executive Summary sheet.


## Shopify integration status

The integration layer is implemented: API client, product mapping, duplicate protection, order preview, synchronization log and a transactional import function. Because the store owner has not provided API credentials, live order import is intentionally switched off and the page demonstrates the workflow with a demo order that is never saved.

To connect a store later, add `SHOPIFY_STORE` and `SHOPIFY_ACCESS_TOKEN` to `.env`.


## Known limitations and next steps

- Sales tax is entered by hand; it is not calculated from the county rate.
- Product cost uses the current `unit_cost`; a cost change is applied to past sales as well.
- Batches are recorded when received, but sales are not assigned to a specific batch.
- The forecast uses simple exponential smoothing with manually set seasonal factors; it does not model a trend.
- The Shopify import does not yet retrieve payment fees, shipping-label cost or county.
- Cancelling a sale deletes it; the record of the cancellation is kept in the inventory audit trail.
- The prototype runs on one computer for one user; there is no login.
