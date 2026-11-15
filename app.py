"""
app.py

Main Streamlit application for Dr. D's Business System.

Start the application from the project folder:

    streamlit run app.py

This file only does three things:

1. Page configuration and styles.
2. The sidebar navigation.
3. Opening the selected page.

Every page lives in its own file:

    page_dashboard.py      Dashboard
    page_record_sale.py    Record Sale
                             - Standard Sale
                             - Market Summary
                             - Recent Sales / cancel a sale
    page_inventory.py      Inventory
                             - Receive Batch
                             - Count Inventory
                             - Other Movement
    page_scholarship.py    Scholarship Report
    page_forecast.py       Demand Forecast
                             - Create Forecast
                             - Accuracy
                             - Seasonal Settings
    shopify_ui.py          Shopify (future integration)

Shared styles and helpers:

    ui_helpers.py

Colors of input fields and buttons:

    .streamlit/config.toml
"""

import streamlit as st


# ============================================================
# PAGE CONFIG
#
# Must be the first Streamlit command.
# ============================================================

st.set_page_config(
    page_title="Dr. D's Business System",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# PAGES AND HELPERS
# ============================================================

from ui_helpers import STRETCH, inject_css

from page_dashboard import render_dashboard
from page_record_sale import render_record_sale
from page_inventory import render_inventory
from page_scholarship import render_scholarship
from page_forecast import render_forecast
from shopify_ui import render_shopify_page


# ============================================================
# NAVIGATION
#
# Section title -> pages in that section.
# Page name     -> function that draws the page.
# ============================================================

NAVIGATION = {
    "Overview": [
        "Dashboard"
    ],
    "Operations": [
        "Record Sale",
        "Inventory"
    ],
    "Reports & Planning": [
        "Scholarship",
        "Forecast"
    ],
    "Settings": [
        "Shopify"
    ]
}

PAGES = {
    "Dashboard": render_dashboard,
    "Record Sale": render_record_sale,
    "Inventory": render_inventory,
    "Scholarship": render_scholarship,
    "Forecast": render_forecast,
    "Shopify": render_shopify_page
}


# ============================================================
# STYLES
# ============================================================

inject_css()


# ============================================================
# CURRENT PAGE
#
# The selected page is remembered in st.session_state, so it
# stays selected while the user works on that page.
# ============================================================

if st.session_state.get("page") not in PAGES:

    st.session_state.page = "Dashboard"


def _open_page(page_name):
    """
    Sidebar button callback: remember the selected page.
    """

    st.session_state.page = page_name


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("Dr. D's")

st.sidebar.caption("Business Management System")

st.sidebar.divider()

for section_name, page_names in NAVIGATION.items():

    st.sidebar.markdown(
        f'<div class="sidebar-section">{section_name}</div>',
        unsafe_allow_html=True
    )

    for page_name in page_names:

        st.sidebar.button(
            page_name,
            key=f"nav_{page_name}",

            # The selected page is shown as a solid red button.
            type=(
                "primary"
                if st.session_state.page == page_name
                else "secondary"
            ),
            on_click=_open_page,
            args=(page_name,),
            **STRETCH
        )

st.sidebar.divider()

st.sidebar.caption("ISE 519 · Project 2")


# ============================================================
# OPEN THE SELECTED PAGE
# ============================================================

PAGES[st.session_state.page]()
