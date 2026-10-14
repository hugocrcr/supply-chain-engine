"""
Démo SupplyStack pour distributeurs — point d'entrée.

Un distributeur généraliste fictif, des données générées, aucune base :
c'est ce qu'on montre en partage d'écran au deuxième appel, quand le prospect
demande à quoi ressemble l'abonnement.

Lancer :
    .venv/bin/streamlit run distrib/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# `streamlit run` ajoute ce dossier au chemin d'import, mais pas AppTest ni
# certains hébergeurs : on ne compte pas dessus.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui  # noqa: E402

st.set_page_config(page_title="SupplyStack — Acme Industrial Supply (demo)", page_icon="📦", layout="wide")
ui.inject_css()
ui.sidebar(ui.get_model())

PAGES = [
    st.Page("views/overview.py", title="Overview", icon=":material/space_dashboard:", default=True),
    st.Page("views/season_shift.py", title="Seasonal reorder points", icon=":material/partly_cloudy_day:"),
    st.Page("views/buy_list.py", title="This week's buy list", icon=":material/shopping_cart:"),
    st.Page("views/dead_stock.py", title="Dead stock & returns", icon=":material/inventory_2:"),
    st.Page("views/suppliers.py", title="Suppliers", icon=":material/local_shipping:"),
]

# Streamlit efface l'état d'un widget absent d'une exécution : on garde en vie les filtres des
# pages pour qu'un changement de page ou de liste ne remette pas le SKU / fournisseur à zéro.
for _k in ("season_shift_mode", "season_shift_sku_lower", "season_shift_sku_raise", "buy_list_vendor",
           "dead_stock_vendor", "dead_stock_line", "suppliers_segment"):
    if _k in st.session_state:
        st.session_state[_k] = st.session_state[_k]

st.navigation(PAGES).run()
