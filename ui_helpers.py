"""
ui_helpers.py

Purpose:
Shared building blocks used by every Streamlit page.

Contents:

1. Colors and small constants.
2. Global CSS (one place for the whole application).
3. Text helpers: page header, section label, KPI card,
   calculation rows.
4. Formatting helpers.
5. Flash messages (a message that survives one page refresh).
6. Cached Excel reports (built only when the data changed).
7. Chart styling.
8. Weeks-of-supply estimate.

Why this file exists:

app.py used to contain the CSS, the helpers and all five pages
in one 4,600-line file. Each page now lives in its own small
file (page_*.py) and imports what it needs from here.
"""

import inspect
from datetime import date

import streamlit as st

from db import get_connection

from forecast_service import (
    calculate_forecast,
    get_next_forecast_week
)

from report_service import (
    create_excel_report,
    create_monthly_scholarship_report,
    create_inventory_report
)


# ============================================================
# COLORS
# ============================================================

NC_STATE_RED = "#CC0000"
DARK_TEXT = "#101828"
BODY_TEXT = "#344054"
MUTED_TEXT = "#475467"
NEUTRAL_SERIES = "#98A2B3"
BORDER = "#E5E7EB"


# ============================================================
# CONSTANTS
# ============================================================

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December"
}

XLSX_MIME = (
    "application/"
    "vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)

# ------------------------------------------------------------
# FULL-WIDTH ELEMENTS
#
# Newer Streamlit versions use   width="stretch"
# Older Streamlit versions use   use_container_width=True
#
# STRETCH holds whichever spelling the installed version
# understands, so pages can simply write:
#
#     st.button("Save", **STRETCH)
# ------------------------------------------------------------

if "width" in inspect.signature(st.button).parameters:

    STRETCH = {"width": "stretch"}

else:

    STRETCH = {"use_container_width": True}


# ============================================================
# GLOBAL CSS
# ============================================================

def inject_css():
    """
    Add the application styles to the page.

    Colors of input fields and primary buttons come from
    .streamlit/config.toml. This CSS only adds what the theme
    cannot do: the dark sidebar, cards, and readable captions.
    """

    st.markdown(
        """
        <style>

        /* ==================================================
           PAGE
           ================================================== */

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1450px;
        }

        h1 {
            font-weight: 800 !important;
            letter-spacing: -0.035em;
        }

        h2, h3, h4 {
            font-weight: 700 !important;
        }

        /* Captions: darker and slightly larger, easier to read. */

        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            color: #475467 !important;
            font-size: 0.92rem !important;
            opacity: 1 !important;
        }

        .page-subtitle {
            color: #475467;
            font-size: 1.05rem;
            margin-top: -0.55rem;
            margin-bottom: 1.7rem;
        }

        .section-label {
            color: #CC0000;
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            margin-bottom: 0.35rem;
        }

        hr {
            margin-top: 2rem !important;
            margin-bottom: 2rem !important;
        }


        /* ==================================================
           SIDEBAR
           ================================================== */

        [data-testid="stSidebar"] {
            background-color: #171717 !important;
            border-right: none !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: #F4F4F4 !important;
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
            color: #B3B8C2 !important;
        }

        [data-testid="stSidebar"] hr {
            border-color: #333333 !important;
            margin-top: 1.2rem !important;
            margin-bottom: 1.2rem !important;
        }

        .sidebar-section {
            color: #A3A8B3;
            font-size: 0.70rem;
            font-weight: 800;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            margin-top: 1rem;
            margin-bottom: 0.35rem;
        }

        /* Navigation buttons: full width, text on the LEFT. */

        [data-testid="stSidebar"] .stButton {
            margin-bottom: 0.15rem;
        }

        [data-testid="stSidebar"] .stButton > button {
            width: 100% !important;
            min-height: 2.4rem !important;
            display: flex !important;
            justify-content: flex-start !important;
            text-align: left !important;
            padding-left: 0.9rem !important;
            padding-right: 0.9rem !important;
            border-radius: 7px !important;
            box-shadow: none !important;
        }

        [data-testid="stSidebar"] .stButton > button > div,
        [data-testid="stSidebar"] .stButton > button span {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            text-align: left !important;
        }

        [data-testid="stSidebar"] .stButton > button p {
            color: inherit !important;
            font-size: 0.95rem !important;
            font-weight: 600 !important;
            text-align: left !important;
            width: 100% !important;
        }

        /* Page that is NOT selected. */

        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
            background-color: transparent !important;
            color: #E5E7EB !important;
            border: 1px solid transparent !important;
        }

        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
            background-color: #262626 !important;
            color: #FFFFFF !important;
        }

        /* Selected page. */

        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
            background-color: #CC0000 !important;
            color: #FFFFFF !important;
            border: 1px solid #CC0000 !important;
        }


        /* ==================================================
           BUTTONS IN THE MAIN AREA
           ================================================== */

        [data-testid="stMain"] .stButton > button,
        [data-testid="stMain"] .stDownloadButton > button,
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] > button {
            border-radius: 8px !important;
            font-weight: 700 !important;
            box-shadow: none !important;
            min-height: 2.6rem !important;
        }

        /* The main action of a screen is always solid red. */

        [data-testid="stMain"] [data-testid="stBaseButton-primary"],
        [data-testid="stMain"] [data-testid="stBaseButton-primaryFormSubmit"] {
            background-color: #CC0000 !important;
            border: 1px solid #CC0000 !important;
            color: #FFFFFF !important;
        }

        [data-testid="stMain"] [data-testid="stBaseButton-primary"] *,
        [data-testid="stMain"] [data-testid="stBaseButton-primaryFormSubmit"] * {
            color: #FFFFFF !important;
        }

        [data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover,
        [data-testid="stMain"] [data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background-color: #A90000 !important;
            border-color: #A90000 !important;
        }

        [data-testid="stMain"] [data-testid="stBaseButton-primary"]:disabled {
            background-color: #E5B3B3 !important;
            border-color: #E5B3B3 !important;
        }

        /* Less important actions are white with a gray outline. */

        [data-testid="stMain"] [data-testid="stBaseButton-secondary"] {
            background-color: #FFFFFF !important;
            border: 1px solid #D0D5DD !important;
            color: #344054 !important;
        }


        /* ==================================================
           CARDS
           ================================================== */

        .dashboard-kpi {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 18px 20px;
            min-height: 108px;
            box-shadow:
                0 1px 2px rgba(16, 24, 40, 0.03),
                0 3px 8px rgba(16, 24, 40, 0.04);
        }

        .dashboard-kpi-primary {
            border-top: 4px solid #CC0000;
        }

        .dashboard-kpi-primary .dashboard-kpi-label {
            color: #344054;
            font-size: 0.98rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }

        .dashboard-kpi-primary .dashboard-kpi-value {
            color: #101828;
            font-size: 2rem;
            line-height: 1.1;
            font-weight: 800;
        }

        .dashboard-kpi-secondary,
        .dashboard-kpi-operational {
            min-height: 90px;
            padding: 15px 18px;
        }

        .dashboard-kpi-secondary .dashboard-kpi-label,
        .dashboard-kpi-operational .dashboard-kpi-label {
            color: #475467;
            font-size: 0.88rem;
            font-weight: 650;
            margin-bottom: 0.25rem;
        }

        .dashboard-kpi-secondary .dashboard-kpi-value,
        .dashboard-kpi-operational .dashboard-kpi-value {
            color: #101828;
            font-size: 1.5rem;
            line-height: 1.1;
            font-weight: 750;
        }

        .dashboard-kpi-note {
            color: #475467;
            font-size: 0.85rem;
            margin-top: 0.35rem;
        }

        .dashboard-panel {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 20px;
            box-shadow:
                0 1px 2px rgba(16, 24, 40, 0.03),
                0 3px 8px rgba(16, 24, 40, 0.04);
        }

        .inventory-product {
            padding: 13px 0;
            border-bottom: 1px solid #EAECF0;
        }

        .inventory-name {
            color: #475467;
            font-size: 0.9rem;
            font-weight: 650;
        }

        .inventory-value {
            color: #101828;
            font-size: 1.65rem;
            font-weight: 800;
        }

        .inventory-total {
            color: #475467;
            font-size: 0.9rem;
            margin-top: 12px;
        }

        /* Streamlit metric cards. */

        div[data-testid="stMetric"] {
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 12px !important;
            padding: 18px 20px !important;
            box-shadow:
                0 1px 2px rgba(16, 24, 40, 0.03),
                0 3px 8px rgba(16, 24, 40, 0.04);
        }

        div[data-testid="stMetricLabel"] p {
            color: #475467 !important;
            font-size: 0.88rem !important;
            font-weight: 700 !important;
        }

        div[data-testid="stMetricValue"] {
            color: #101828 !important;
            font-weight: 800 !important;
        }


        /* ==================================================
           CALCULATION PREVIEW ROWS
           ================================================== */

        .calc-title {
            color: #101828;
            font-size: 1.05rem;
            font-weight: 750;
            margin-bottom: 0.4rem;
        }

        .calc-row {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding: 8px 0;
            border-bottom: 1px solid #EAECF0;
            color: #344054;
            font-size: 0.97rem;
        }

        .calc-row .calc-value {
            color: #101828;
            font-weight: 700;
            white-space: nowrap;
        }

        .calc-row.calc-strong {
            border-bottom: none;
            border-top: 2px solid #101828;
            font-weight: 750;
            color: #101828;
        }

        .calc-row.calc-strong .calc-value {
            font-size: 1.15rem;
            font-weight: 800;
        }

        .calc-row.calc-accent .calc-value {
            color: #CC0000;
        }

        .calc-row.calc-muted {
            color: #475467;
            font-size: 0.9rem;
        }


        /* ==================================================
           SMALL STATUS BADGE
           ================================================== */

        .status-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 4px 11px;
            font-size: 0.8rem;
            font-weight: 750;
        }

        .status-badge.badge-gray {
            background: #F2F4F7;
            color: #344054;
            border: 1px solid #D0D5DD;
        }

        .status-badge.badge-green {
            background: #ECFDF3;
            color: #067647;
            border: 1px solid #ABEFC6;
        }

        .status-badge.badge-red {
            background: #FEE4E2;
            color: #B42318;
            border: 1px solid #FECDCA;
        }


        /* ==================================================
           FORMS, TABLES, TABS, CHARTS
           ================================================== */

        [data-testid="stForm"] {
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 12px !important;
            padding: 1.4rem !important;
        }

        [data-testid="stWidgetLabel"] p {
            color: #344054 !important;
            font-weight: 600 !important;
            font-size: 0.95rem !important;
        }

        button[data-baseweb="tab"] p {
            font-weight: 650 !important;
            font-size: 1rem !important;
        }

        [data-testid="stPlotlyChart"] {
            background-color: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 10px;
        }

        .forecast-formula {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 16px 20px;
            text-align: center;
            font-size: 1.05rem;
            margin-top: 8px;
            margin-bottom: 12px;
            color: #344054;
        }

        .forecast-formula strong {
            color: #CC0000;
            font-size: 1.2rem;
        }

        </style>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# TEXT HELPERS
# ============================================================

def page_header(title, subtitle=None):
    """
    Render a page title with an optional subtitle.
    """

    st.title(title)

    if subtitle:

        st.markdown(
            f'<div class="page-subtitle">{subtitle}</div>',
            unsafe_allow_html=True
        )


def section_label(text):
    """
    Render a small red section label.
    """

    st.markdown(
        f'<div class="section-label">{text}</div>',
        unsafe_allow_html=True
    )


def kpi_card(title, value, style="primary", note=None):
    """
    Render a KPI card.

    Styles:
        primary
        secondary
        operational

    The HTML is kept on one line because Streamlit Markdown
    may show deeply indented HTML as a code block.
    """

    note_html = ""

    if note:

        note_html = f'<div class="dashboard-kpi-note">{note}</div>'

    st.markdown(
        (
            f'<div class="dashboard-kpi dashboard-kpi-{style}">'
            f'<div class="dashboard-kpi-label">{title}</div>'
            f'<div class="dashboard-kpi-value">{value}</div>'
            f'{note_html}'
            f'</div>'
        ),
        unsafe_allow_html=True
    )


def calc_rows(title, rows):
    """
    Render a small "label ..... value" table.

    rows is a list of tuples:

        (label, value)
        (label, value, style)

    style can be:
        "strong"   bold total line
        "accent"   red value
        "muted"    smaller gray line
    """

    html = f'<div class="calc-title">{title}</div>'

    for row in rows:

        label = row[0]
        value = row[1]

        style = ""

        if len(row) > 2 and row[2]:

            style = f" calc-{row[2]}"

        html += (
            f'<div class="calc-row{style}">'
            f'<span>{label}</span>'
            f'<span class="calc-value">{value}</span>'
            f'</div>'
        )

    st.markdown(
        html,
        unsafe_allow_html=True
    )


def status_badge(text, color="gray"):
    """
    Return the HTML of a small rounded status label.

    color: "gray", "green" or "red"
    """

    return (
        f'<span class="status-badge badge-{color}">{text}</span>'
    )


# ============================================================
# FORMATTING HELPERS
# ============================================================

def format_currency(value):
    """
    Format a number as US currency:  1234.5 -> $1,234.50
    """

    return f"${float(value):,.2f}"


def format_jars(quantity):
    """
    Format a jar count:  1 -> "1 jar",  1025 -> "1,025 jars"
    """

    quantity = int(quantity)

    if quantity == 1:

        return "1 jar"

    return f"{quantity:,} jars"


def describe_jars(original_quantity, slobberin_quantity):
    """
    Short text for the products in a sale.

    Example:  "1 Original + 2 Slobberin'"
    """

    parts = []

    if int(original_quantity) > 0:

        parts.append(f"{int(original_quantity)} Original")

    if int(slobberin_quantity) > 0:

        parts.append(f"{int(slobberin_quantity)} Slobberin'")

    return " + ".join(parts) if parts else "no jars"


def option_index(options, preferred_value):
    """
    Return the index of preferred_value in options.

    If the preferred value does not exist,
    return 0 (the first option).
    """

    if preferred_value in options:

        return options.index(preferred_value)

    return 0


# ============================================================
# FLASH MESSAGES
#
# A button callback runs BEFORE the page is drawn again.
# The callback stores its result here, and the page shows it
# once on the next draw.
# ============================================================

def set_flash(name, kind, message):
    """
    Store a message for the next page draw.

    kind: "success", "error", "warning" or "info"
    """

    st.session_state[f"flash_{name}"] = (kind, message)


def show_flash(name):
    """
    Show (once) the message stored by set_flash().

    The message is written into a container that is ALWAYS
    created, with or without a message. The elements below it
    therefore keep their position, and open expanders or tabs
    are not reset when a message appears.
    """

    slot = st.container()

    flash = st.session_state.pop(f"flash_{name}", None)

    if flash is None:

        return

    kind, message = flash

    with slot:

        if kind == "success":

            st.success(message)

        elif kind == "error":

            st.error(message)

        elif kind == "warning":

            st.warning(message)

        else:

            st.info(message)


# ============================================================
# DATA VERSION
# ============================================================

def get_data_version():
    """
    Return a short text that changes whenever the business
    data changes (a new sale, a voided sale, an inventory
    movement, a forecast, a seasonal setting, a product cost).

    It is used as the cache key of the Excel reports:
    the same version -> the report built earlier is reused.

    One small query is much cheaper than rebuilding a
    nine-sheet Excel workbook every time the page is drawn.
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM sales),
                    (SELECT COALESCE(MAX(sale_id), 0) FROM sales),
                    (SELECT COUNT(*) FROM inventory_transactions),
                    (SELECT COALESCE(MAX(transaction_id), 0)
                       FROM inventory_transactions),
                    (SELECT COUNT(*) FROM inventory_batches),
                    (SELECT COUNT(*) FROM forecasts),
                    (SELECT COUNT(actual_quantity) FROM forecasts),
                    (SELECT COALESCE(MAX(updated_at)::text, '')
                       FROM forecast_seasonality),
                    (SELECT COALESCE(SUM(unit_cost + scholarship_rate), 0)::text
                       FROM products);
                """
            )

            row = cur.fetchone()

    return "|".join(str(value) for value in row)


# ============================================================
# CACHED EXCEL REPORTS
#
# st.cache_data remembers the result for a given set of
# arguments. The data version is one of the arguments, so a
# report is rebuilt only after the data has changed.
# ============================================================

@st.cache_data(show_spinner=False, max_entries=5)
def cached_business_report(data_version, report_date):
    """
    Complete Business Report workbook as bytes.
    """

    return create_excel_report().getvalue()


@st.cache_data(show_spinner=False, max_entries=24)
def cached_scholarship_report(data_version, year, month):
    """
    Monthly Scholarship Report workbook as bytes.
    """

    return create_monthly_scholarship_report(
        year=year,
        month=month,
        month_name=MONTH_NAMES[month]
    ).getvalue()


@st.cache_data(show_spinner=False, max_entries=5)
def cached_inventory_report(data_version, report_date):
    """
    Inventory Report workbook as bytes.
    """

    return create_inventory_report().getvalue()


# ============================================================
# CHART STYLING
# ============================================================

def style_chart(figure, height=330, show_legend=False):
    """
    Apply the application look to a Plotly chart:
    white background, light grid, readable font, and a legend
    placed above the chart so its text is never cut off.
    """

    figure.update_layout(
        height=height,
        showlegend=show_legend,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(
            color=BODY_TEXT,
            size=13
        ),
        margin=dict(
            l=20,
            r=20,
            t=40 if show_legend else 20,
            b=20
        ),
        legend=dict(
            title_text="",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        )
    )

    figure.update_xaxes(
        showgrid=False,
        title_text=None
    )

    figure.update_yaxes(
        gridcolor="#EAECF0",
        zeroline=False,

        # Always start at zero so differences are not exaggerated.
        rangemode="tozero"
    )

    return figure


# ============================================================
# WEEKS OF SUPPLY
# ============================================================

@st.cache_data(show_spinner=False, max_entries=20)
def _expected_weekly_demand(data_version, product_id, forecast_week):
    """
    Expected jars per week for one product across ALL regions
    and ALL sales channels, or None when there is no history.
    """

    try:

        result = calculate_forecast(
            product_id=product_id,
            forecast_week=forecast_week,
            sales_region="ALL",
            sales_channel="ALL"
        )

    except ValueError:

        return None

    return float(result["saved_forecast_quantity"])


def get_weeks_of_supply(product_id, current_quantity, data_version):
    """
    Estimate how long the current stock will last.

    Returns a dictionary:

        {
            "weekly_demand": 148.5,
            "weeks": 2.5
        }

    or None when demand cannot be estimated
    (no sales history, or expected demand is zero).

    The demand is the forecast for NEXT week across all regions
    and channels, with the default smoothing factor.
    """

    weekly_demand = _expected_weekly_demand(
        data_version,
        product_id,
        get_next_forecast_week(date.today())
    )

    if weekly_demand is None or weekly_demand <= 0:

        return None

    return {
        "weekly_demand": weekly_demand,
        "weeks": float(current_quantity) / weekly_demand
    }


def describe_supply(supply):
    """
    Turn get_weeks_of_supply() into one short sentence.
    """

    if supply is None:

        return "Not enough sales history to estimate supply."

    weeks = supply["weeks"]

    if weeks < 1:

        duration = "less than 1 week"

    else:

        duration = f"about {weeks:.1f} weeks"

    return (
        f"Lasts {duration} at the expected "
        f"{supply['weekly_demand']:,.0f} jars per week."
    )
