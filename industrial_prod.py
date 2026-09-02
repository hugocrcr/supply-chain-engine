"""
SupplyStack — Industrial Supply Chain Intelligence Engine
Streamlit Dashboard + AI Assistant — INDUSTRIAL MODE

Connects to Supabase Postgres (MECAPRO demo / industrial clients).
Reads from the same DB that the n8n industrial pipeline writes to.

── UI: "Aurora" light theme ──────────────────────────────────────────────────
Same visual system as the DTC dashboard: airy violet-accented light theme,
KPI cards with status dot + traffic-light value + delta + sparkline, Aurora
panels, sortable tables, 2:1 executive layout with right rail.

── Client switches ───────────────────────────────────────────────────────────
CLIENT_LANG   "fr" | "en"       — all UI labels
CLIENT_NAME   display name
CURRENCY      currency symbol used in every formatter
"""

import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import psycopg2
import re
import os
import hmac
import uuid
from datetime import datetime, date, timedelta

# ═══════════════════════════════════════════════════════════════════════════
# CLIENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
CLIENT_LANG = "fr"                      # "fr" or "en"
CLIENT_NAME = "MECAPRO Industries"
CLIENT_INITIALS = "MI"
CURRENCY = "€"

# ── PARAMÈTRES DE VALORISATION — à calibrer par client à l'installation ──────
# R5 : tout coefficient de valorisation est un paramètre, jamais une constante
# en dur. Valeurs par défaut ci-dessous, recalibrées client par client.
COUT_HORAIRE_MO          = 38.0   # € / h, main-d'œuvre chargée
COUT_HORAIRE_MACHINE     = 45.0   # € / h, poste standard (surchargeable par poste)
TAUX_ABSORPTION_DEMANDE  = 0.60   # part de la capacité libérée réellement vendable
TAUX_POSSESSION_ANNUEL   = 0.18   # coût de portage du capital immobilisé
JOURS_OUVRES_AN          = 220
HEURES_OUVERTURE_JOUR    = 15.0   # 2 équipes
PART_SURTRAITEMENT_NONVA = 0.25   # part du temps hors VA comptée en sur-traitement
TAUX_ARRETS_PLANIFIES    = 0.05   # part d'ouverture en arrêts planifiés (requis = ouverture × (1 − taux))

# Doctrine David §5 — la valorisation de la capacité passe par l'arbre E1→E6.
MARGE_COUT_VARIABLE_UNITAIRE = 45.0   # € / pièce, marge sur coût variable (contrôle de gestion)
SEUIL_CONTRAINTE             = 0.95   # taux de charge au-delà duquel un poste est contraint
# TAUX_ABSORPTION_DEMANDE reste utilisé, mais UNIQUEMENT en repli quand E5/E6
# ne peuvent trancher (charge/capacité absentes) — méthode 'absorption_globale'.

# ── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=f"SupplyStack — {CLIENT_NAME}",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══════════════════════════════════════════════════════════════════════════
# ACCESS CONTROL
# ───────────────────────────────────────────────────────────────────────────
# Portable across hosts: reads the password from Streamlit secrets when
# available, otherwise from an environment variable. Migrating to Render or a
# VPS therefore requires no code change — only where the secret is stored.
#
#   Streamlit Cloud : Manage app → Settings → Secrets
#                     dashboard_password = "..."
#   Render / VPS    : environment variable DASHBOARD_PASSWORD
#
# Leave both unset to disable the gate (local development).
# ═══════════════════════════════════════════════════════════════════════════
def _expected_password():
    try:
        pwd = st.secrets.get("dashboard_password", "")
    except Exception:
        pwd = ""
    return pwd or os.environ.get("DASHBOARD_PASSWORD", "")


def require_access():
    """Block the whole app behind a password. No-op if none is configured."""
    expected = _expected_password()
    if not expected:
        return  # gate disabled

    if st.session_state.get("_authenticated"):
        return

    if CLIENT_LANG == "fr":
        title = "Accès au tableau de bord"
        sub = f"Espace client {CLIENT_NAME}"
        field = "Mot de passe"
        button = "Se connecter"
        wrong = "Mot de passe incorrect."
        footer = "Accès fourni par SupplyStack Consulting. En cas de perte, contactez votre référent."
    else:
        title = "Dashboard access"
        sub = f"{CLIENT_NAME} client area"
        field = "Password"
        button = "Sign in"
        wrong = "Incorrect password."
        footer = "Access provided by SupplyStack Consulting. Lost it? Contact your account manager."

    st.markdown(f"""
    <div style="max-width:420px;margin:12vh auto 0;text-align:center;">
      <div style="width:52px;height:52px;border-radius:15px;margin:0 auto 18px;
           background:linear-gradient(135deg,#6355ff,#9d8bff);color:#fff;
           display:flex;align-items:center;justify-content:center;
           font-size:24px;font-weight:800;
           box-shadow:0 10px 22px -10px rgba(99,85,255,0.7);">S</div>
      <div style="font-size:9.5px;font-weight:600;letter-spacing:0.18em;color:#a5aec4;">SUPPLYSTACK</div>
      <div style="font-size:20px;font-weight:800;color:#0f172a;margin-top:6px;">{title}</div>
      <div style="font-size:13px;color:#64748b;margin-top:4px;">{sub}</div>
    </div>
    """, unsafe_allow_html=True)

    _l, _c, _r = st.columns([1, 2, 1])
    with _c:
        with st.form("access_form", clear_on_submit=False):
            entered = st.text_input(field, type="password", label_visibility="collapsed",
                                    placeholder=field)
            ok = st.form_submit_button(button, use_container_width=True)
        if ok:
            if hmac.compare_digest((entered or "").strip(), expected.strip()):
                st.session_state["_authenticated"] = True
                st.rerun()
            else:
                st.markdown(
                    f'<div style="background:#fdecec;border-left:4px solid #e5484d;color:#b42318;'
                    f'padding:10px 14px;border-radius:10px;font-size:13px;font-weight:600;'
                    f'margin-top:10px;">{wrong}</div>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:11.5px;color:#94a3b8;text-align:center;'
            f'margin-top:22px;line-height:1.5;">{footer}</div>',
            unsafe_allow_html=True)

    st.stop()


require_access()


# ── CREDENTIALS ───────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": "aws-0-eu-central-1.pooler.supabase.com",
    "port": 6543,
    "database": "postgres",
    "user": st.secrets["supabase_mecapro_user"],
    "password": st.secrets["supabase_mecapro_password_ro"],
    "sslmode": "require",
    "connect_timeout": 15,
    "options": "-c statement_timeout=15000",
}

ANTHROPIC_API_KEY = (st.secrets.get("anthropic_api_key", "")
                     or st.secrets.get("ANTHROPIC_API_KEY", ""))


# ── SUPABASE CONNECTION ───────────────────────────────────────────────────────
@st.cache_resource
def get_connection():
    """Persistent DB connection (autocommit — read-only workload)."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


@st.cache_data(ttl=300)
def run_query(query):
    """Execute a SQL query and return results as a DataFrame."""
    conn = get_connection()
    try:
        return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Database error: {e}")
        st.cache_resource.clear()
        return pd.DataFrame()


def run_query_uncached(query):
    """Execute a SQL query without caching (used by AI assistant)."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return pd.read_sql(query, conn)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        st.cache_resource.clear()
        conn = get_connection()
        return pd.read_sql(query, conn)
    except Exception as e:
        st.cache_resource.clear()
        raise e


def table_exists(name):
    """Check whether a table exists in the public schema."""
    try:
        df = run_query(
            "SELECT 1 FROM information_schema.tables "
            f"WHERE table_schema='public' AND table_name='{name}' LIMIT 1"
        )
        return not df.empty
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# LABELS (i18n)
# ═══════════════════════════════════════════════════════════════════════════
T_ALL = {
    "fr": {
        "header_sub": "Tableau de bord — Stocks et approvisionnements industriels",
        "tab_exec": "📊 Tableau exécutif",
        "tab_stock": "📦 Détail des stocks",
        "tab_supplier": "🚚 Fournisseurs",
        "tab_reorder": "🔄 Réapprovisionnement",
        "tab_ai": "🤖 Assistant IA",
        "tab_health": "🏥 Santé des données",
        "tab_diag": "🔧 Diagnostic paramétrage",
        "tab_whatif": "🧪 Simulateur",
        "diag_title": "🔧 Diagnostic du paramétrage",
        "diag_caption": "Comparaison entre ce qui est réglé dans votre ERP et ce que la demande réelle impose.",
        "diag_alerts": "Qualité des alertes de stock bas",
        "diag_ss": "Stock de sécurité : paramétré vs calculé",
        "diag_lt": "Fiabilité des délais d'approvisionnement",
        "diag_no_params": "Les paramètres ERP ne sont pas chargés dans la base. Cet écran compare le paramétrage du client à nos calculs — il nécessite les colonnes moq, erp_safety_stock, erp_reorder_point et erp_lead_time_days.",
        "exec_title": "Vue exécutive",
        "exec_sub": "Santé du fonds de roulement sur vos références, magasins et familles",
        "legend_healthy": "Sain",
        "legend_watch": "À surveiller",
        "legend_risk": "À risque",
        "kpi_dead": "Stock dormant",
        "kpi_excess": "Stock excédentaire",
        "kpi_total": "Stock total",
        "kpi_holding": "Coût de détention / an",
        "kpi_turnover": "Rotation des stocks",
        "kpi_recover": "Cash récupérable",
        "kpi_bfr": "BFR immobilisé",
        "kpi_otd": "OTD fournisseurs",
        "kpi_coverage": "Couverture moyenne",
        "kpi_stockout": "Réfs à risque de rupture",
        "help_dead": "Références sans mouvement depuis trop longtemps : de la trésorerie figée. ↑ plus de cash bloqué (rouge) · ↓ cash libéré (vert).",
        "help_excess": "Stock détenu au-delà du besoin réel. ↑ surstock qui s'aggrave (rouge) · ↓ surstock résorbé (vert).",
        "help_total": "Valeur totale de l'inventaire. ↓ moins de capital immobilisé (vert) · ↑ plus de cash figé (rouge).",
        "help_holding": "Coût annuel de possession du stock (financement, stockage, obsolescence). ↓ économies (vert) · ↑ plus de coût (rouge).",
        "help_turnover": "Nombre de fois où le stock est renouvelé dans l'année. ↑ meilleure rotation (vert) · ↓ stock qui dort (rouge).",
        "help_recover": "Trésorerie récupérable en écoulant le stock dormant et excédentaire. ↑ plus d'opportunité (vert) · ↓ opportunité réduite (rouge).",
        "help_bfr": "Cash immobilisé dans le stock (fonds de roulement bloqué). ↓ cash libéré (vert) · ↑ plus de cash bloqué (rouge).",
        "help_otd": "Part des commandes fournisseurs livrées à l'heure. ↑ fournisseurs plus fiables (vert) · ↓ délais qui dérivent (rouge).",
        "help_coverage": "Jours de demande couverts par le stock actuel. ↓ stock plus tendu (vert) · ↑ tendance au surstock (rouge).",
        "help_stockout": "Références risquant de passer sous le seuil de sécurité avant le prochain réappro.",
        "chart_dead_family": "Valeur du stock dormant par famille",
        "chart_type_mix": "Répartition par type d'article",
        "chart_abcxyz": "Matrice ABC × XYZ",
        "chart_trend": "Évolution du stock total",
        "rail_ai": "ASSISTANT IA",
        "rail_alerts": "Alertes récentes",
        "rail_reorder": "Réappro prioritaires",
        "live": "en direct",
        "no_data": "Aucune donnée disponible.",
        "run_pipeline": "Lancez le pipeline KPI quotidien pour alimenter la tendance.",
        "not_enough_hist": "Pas assez d'historique pour afficher une tendance.",
        "dead_refs": "Réfs dormantes",
        "excess_refs": "Réfs excédentaires",
        "below_rop": "Sous point de commande",
        "abc_split": "Répartition ABC",
        "top_dead": "Top 20 des références dormantes",
        "coverage_dist": "Couverture vs valeur immobilisée",
        "supplier_seg": "Segmentation automatique des fournisseurs",
        "supplier_top": "Fournisseurs les plus à risque",
        "supplier_detail": "Détail par fournisseur",
        "reorder_table": "Références à réapprovisionner",
        "search_product": "🔍  Filtrer par désignation ou code article…",
        "all_actions": "Toutes les actions",
        "all_types": "Tous les types",
        "showing": "Affichage de",
        "of": "sur",
        "refs": "références",
        "sort_hint": "cliquez sur un en-tête pour trier",
        "ai_title": "🤖 Analyste supply chain industrielle",
        "ai_caption": "Posez vos questions sur vos stocks, mouvements, commandes fournisseurs et paramètres ERP en langage naturel.",
        "ai_test": "Tester la connexion à l'IA",
        "ai_check": "🔌 Vérification de la connexion",
        "ai_try": "Essayez de demander",
        "ai_placeholder": "Posez une question sur vos données supply chain…",
        "ai_send": "Envoyer",
        "ai_clear": "🗑️ Effacer la conversation",
        "ai_thinking": "Analyse de vos données…",
        "ai_see_data": "📊 Voir les données",
        "health_title": "🏥 Moniteur de santé des données",
        "health_caption": "Contrôles qualité automatiques exécutés à chaque cycle d'ingestion.",
        "health_freshness": "Fraîcheur des données",
        "health_audit": "Audit qualité — dernier cycle",
        "health_valuation": "Écart de valorisation vs ERP",
        "health_params": "Paramètres ERP vs calculés",
        "col_product": "Désignation",
        "col_code": "Code article",
        "col_type": "Type",
        "col_family": "Famille",
        "col_warehouse": "Magasin",
        "col_stock": "Stock",
        "col_cost": "PMP",
        "col_value": "Valeur",
        "col_days_nomvt": "Jours sans mvt",
        "col_coverage": "Couverture (j)",
        "col_trapped": "Immobilisé",
        "col_excess": "Excédent",
        "col_action": "Action",
        "col_supplier": "Fournisseur",
        "col_orders": "Commandes",
        "col_lt": "Délai réel (j)",
        "col_ltstd": "Écart-type",
        "col_cv": "Variabilité",
        "col_otd": "OTD %",
        "col_risk": "Score risque",
        "col_category": "Catégorie",
        "col_abc": "ABC",
        "col_xyz": "XYZ",
        "col_ss_erp": "SS ERP",
        "col_ss_calc": "SS calculé",
        "col_rop_erp": "PC ERP",
        "col_rop_calc": "PC calculé",
        "col_qty": "Qté à commander",
        "col_days_out": "Jours avant rupture",
        "act_liquidate": "Liquider",
        "act_stop": "Stopper réappro",
        "act_reorder": "Commander",
        "act_hold": "Conserver",
        "date_note": "Commandes fournisseurs réceptionnées entre",
    },
    "en": {
        "header_sub": "Dashboard — Industrial inventory and procurement",
        "tab_exec": "📊 Executive",
        "tab_stock": "📦 Inventory detail",
        "tab_supplier": "🚚 Suppliers",
        "tab_reorder": "🔄 Reordering",
        "tab_ai": "🤖 AI Assistant",
        "tab_health": "🏥 Data health",
        "tab_diag": "🔧 Parameter diagnosis",
        "tab_whatif": "🧪 What-if simulator",
        "diag_title": "🔧 Parameter diagnosis",
        "diag_caption": "Comparison between what is configured in your ERP and what real demand requires.",
        "diag_alerts": "Low-stock alert quality",
        "diag_ss": "Safety stock: configured vs calculated",
        "diag_lt": "Lead time reliability",
        "diag_no_params": "ERP parameters are not loaded in the database. This screen compares the client's configuration against our calculations — it requires the moq, erp_safety_stock, erp_reorder_point and erp_lead_time_days columns.",
        "exec_title": "Executive view",
        "exec_sub": "Working-capital health across your references, warehouses and families",
        "legend_healthy": "Healthy",
        "legend_watch": "Watch",
        "legend_risk": "At risk",
        "kpi_dead": "Dead stock",
        "kpi_excess": "Excess stock",
        "kpi_total": "Total inventory",
        "kpi_holding": "Holding cost / year",
        "kpi_turnover": "Inventory turnover",
        "kpi_recover": "Recoverable cash",
        "kpi_bfr": "Working capital tied",
        "kpi_otd": "Supplier OTD",
        "kpi_coverage": "Avg coverage",
        "kpi_stockout": "Stockout-risk refs",
        "help_dead": "References with no movement for too long — cash frozen on the shelf. ↑ more cash locked (red) · ↓ cash freed (green).",
        "help_excess": "Stock held beyond real coverage needs. ↑ overstock worsening (red) · ↓ overstock cleared (green).",
        "help_total": "Total inventory value. ↓ less capital tied up (green) · ↑ more cash frozen (red).",
        "help_holding": "Annual cost of holding stock (financing, storage, obsolescence). ↓ savings (green) · ↑ more cost (red).",
        "help_turnover": "How many times stock is renewed per year. ↑ turns faster (green) · ↓ sitting idle (red).",
        "help_recover": "Cash you could free up by clearing dead and excess stock. ↑ more opportunity (green) · ↓ shrinking (red).",
        "help_bfr": "Cash tied up in inventory (working capital locked). ↓ cash freed (green) · ↑ more cash locked (red).",
        "help_otd": "Share of supplier orders delivered on time. ↑ more reliable (green) · ↓ slipping lead times (red).",
        "help_coverage": "Days of demand the current stock covers. ↓ leaner stock (green) · ↑ drifting to overstock (red).",
        "help_stockout": "References that may drop below the safety threshold before the next replenishment.",
        "chart_dead_family": "Dead stock value by family",
        "chart_type_mix": "Breakdown by article type",
        "chart_abcxyz": "ABC × XYZ matrix",
        "chart_trend": "Total inventory trend",
        "rail_ai": "AI ASSISTANT",
        "rail_alerts": "Recent alerts",
        "rail_reorder": "Priority reorders",
        "live": "live",
        "no_data": "No data available.",
        "run_pipeline": "Run the daily KPI pipeline to populate the trend.",
        "not_enough_hist": "Not enough history to show a trend.",
        "dead_refs": "Dead refs",
        "excess_refs": "Excess refs",
        "below_rop": "Below reorder point",
        "abc_split": "ABC split",
        "top_dead": "Top 20 dead references",
        "coverage_dist": "Coverage vs tied-up value",
        "supplier_seg": "Automatic supplier segmentation",
        "supplier_top": "Highest-risk suppliers",
        "supplier_detail": "Supplier detail",
        "reorder_table": "References to reorder",
        "search_product": "🔍  Filter by description or article code…",
        "all_actions": "All actions",
        "all_types": "All types",
        "showing": "Showing",
        "of": "of",
        "refs": "references",
        "sort_hint": "click any column header to sort",
        "ai_title": "🤖 Industrial supply chain analyst",
        "ai_caption": "Ask about inventory, movements, purchase orders and ERP parameters in plain language.",
        "ai_test": "Test AI connection",
        "ai_check": "🔌 Connection check",
        "ai_try": "Try asking",
        "ai_placeholder": "Ask a question about your supply chain data…",
        "ai_send": "Send",
        "ai_clear": "🗑️ Clear conversation",
        "ai_thinking": "Analysing your data…",
        "ai_see_data": "📊 View data",
        "health_title": "🏥 Data health monitor",
        "health_caption": "Automated quality checks run on every ingestion cycle.",
        "health_freshness": "Data freshness",
        "health_audit": "Quality audit — latest run",
        "health_valuation": "Valuation gap vs ERP",
        "health_params": "ERP vs calculated parameters",
        "col_product": "Description",
        "col_code": "Article code",
        "col_type": "Type",
        "col_family": "Family",
        "col_warehouse": "Warehouse",
        "col_stock": "Stock",
        "col_cost": "Unit cost",
        "col_value": "Value",
        "col_days_nomvt": "Days no mvt",
        "col_coverage": "Coverage (d)",
        "col_trapped": "Tied up",
        "col_excess": "Excess",
        "col_action": "Action",
        "col_supplier": "Supplier",
        "col_orders": "Orders",
        "col_lt": "Actual LT (d)",
        "col_ltstd": "Std dev",
        "col_cv": "Variability",
        "col_otd": "OTD %",
        "col_risk": "Risk score",
        "col_category": "Category",
        "col_abc": "ABC",
        "col_xyz": "XYZ",
        "col_ss_erp": "SS ERP",
        "col_ss_calc": "SS calc",
        "col_rop_erp": "ROP ERP",
        "col_rop_calc": "ROP calc",
        "col_qty": "Qty to order",
        "col_days_out": "Days to stockout",
        "act_liquidate": "Liquidate",
        "act_stop": "Stop reordering",
        "act_reorder": "Reorder",
        "act_hold": "Hold",
        "date_note": "Purchase orders received between",
    },
}
T = T_ALL[CLIENT_LANG]

# Article type display names
TYPE_NAMES = {
    "fr": {
        "PF": "Produits finis", "SF": "Semi-finis", "COMP": "Composants",
        "MP": "Matières premières", "CONS": "Consommables", "EMB": "Emballages",
        "PDR": "Pièces de rechange", "NA": "Non classé",
    },
    "en": {
        "PF": "Finished goods", "SF": "Semi-finished", "COMP": "Components",
        "MP": "Raw materials", "CONS": "Consumables", "EMB": "Packaging",
        "PDR": "Spare parts", "NA": "Unclassified",
    },
}
TN = TYPE_NAMES[CLIENT_LANG]

CATEGORY_NAMES = {
    "fr": {
        "critical": "Critique", "unstable": "Instable", "weak": "Faible",
        "acceptable": "Acceptable", "solid": "Solide", "no_promised_data": "Données manquantes",
    },
    "en": {
        "critical": "Critical", "unstable": "Unstable", "weak": "Weak",
        "acceptable": "Acceptable", "solid": "Solid", "no_promised_data": "Missing data",
    },
}
CN = CATEGORY_NAMES[CLIENT_LANG]


# ── AURORA THEME / STYLING ────────────────────────────────────────────────────
AURORA_PRIMARY = "#6355ff"
STATUS = {
    "kpi-danger":  {"dot": "#e5484d", "val": "#e5484d", "spark": "#f4a8aa"},
    "kpi-warning": {"dot": "#f79009", "val": "#f79009", "spark": "#f7c88a"},
    "kpi-success": {"dot": "#12b76a", "val": "#12b76a", "spark": "#9fdcbf"},
    "kpi-info":    {"dot": "#3b82f6", "val": "#0f172a", "spark": "#bcd0f5"},
    "":            {"dot": "#94a3b8", "val": "#0f172a", "spark": "#cbd5e1"},
}

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@500;600&display=swap');

    html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea {
        font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif !important;
    }
    .stApp { background: #f5f6fb; }
    .block-container { padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px; }

    h1, h2, h3, .stSubheader { color: #0f172a !important; letter-spacing: -0.01em; }
    .stApp h3 { font-weight: 700; font-size: 16px !important; }

    /* ── Aurora KPI card ─────────────────────────────────────────────────── */
    .kpi-card {
        background: #ffffff;
        border: 1px solid rgba(15,23,42,0.06);
        border-radius: 16px;
        padding: 16px 17px;
        min-height: 118px;
        display: flex;
        flex-direction: column;
        gap: 11px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 12px 28px -20px rgba(15,23,42,0.22);
    }
    .kpi-top { display: flex; align-items: center; gap: 7px; }
    .kpi-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
    .kpi-label {
        font-size: 10px; font-weight: 600; letter-spacing: 0.07em;
        text-transform: uppercase; color: #94a3b8; line-height: 1.2;
    }
    .kpi-i {
        position: relative; margin-left: auto; flex: none; width: 15px; height: 15px;
        display: inline-flex; align-items: center; justify-content: center;
        border-radius: 50%; background: #eef0f6; color: #94a3b8;
        border: 1px solid rgba(15,23,42,0.05);
        font-size: 10px; font-weight: 700; font-style: normal;
        font-family: Georgia, 'Times New Roman', serif; line-height: 1; cursor: help;
        transition: background .15s, color .15s; outline: none;
    }
    .kpi-i:hover, .kpi-i:focus { background: #6355ff; color: #ffffff; border-color: #6355ff; }
    /* styled hover popover — replaces the native title tooltip */
    .kpi-tip {
        position: absolute; top: calc(100% + 9px); right: -7px; width: 232px;
        background: #ffffff; color: #475569;
        border: 1px solid rgba(15,23,42,0.08);
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
        font-size: 11.5px; font-weight: 500; font-style: normal; line-height: 1.55;
        letter-spacing: normal; text-transform: none; text-align: left;
        padding: 11px 13px; border-radius: 12px;
        box-shadow: 0 12px 28px -14px rgba(15,23,42,0.28);
        opacity: 0; visibility: hidden; transform: translateY(-4px);
        transition: opacity .16s ease, transform .16s ease;
        z-index: 9999; pointer-events: none; white-space: normal;
    }
    .kpi-tip::before {
        content: ""; position: absolute; bottom: 100%; right: 11px;
        border: 6px solid transparent; border-bottom-color: #ffffff;
    }
    .kpi-tip::after {
        content: ""; position: absolute; bottom: calc(100% + 1px); right: 10px;
        border: 7px solid transparent; border-bottom-color: rgba(15,23,42,0.08); z-index: -1;
    }
    .kpi-i:hover .kpi-tip, .kpi-i:focus .kpi-tip {
        opacity: 1; visibility: visible; transform: translateY(0);
    }
    /* let the popover escape the KPI row/column instead of being clipped */
    [data-testid="column"], [data-testid="stHorizontalBlock"] { overflow: visible !important; }
    .kpi-value { font-size: 27px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.05; }
    .kpi-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
    .kpi-delta { font-size: 12px; font-weight: 700; }

    .kpi-danger  .kpi-dot { background: #e5484d; } .kpi-danger  .kpi-value { color: #e5484d; }
    .kpi-warning .kpi-dot { background: #f79009; } .kpi-warning .kpi-value { color: #f79009; }
    .kpi-success .kpi-dot { background: #12b76a; } .kpi-success .kpi-value { color: #12b76a; }
    .kpi-info    .kpi-dot { background: #3b82f6; } .kpi-info    .kpi-value { color: #0f172a; }
    .kpi-card    .kpi-dot { background: #94a3b8; }

    /* ── Aurora panel ────────────────────────────────────────────────────── */
    .aurora-panel {
        background: #ffffff; border: 1px solid rgba(15,23,42,0.06);
        border-radius: 18px; padding: 18px 20px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 16px 36px -26px rgba(15,23,42,0.2);
    }
    .stPlotlyChart {
        background: #ffffff; border: 1px solid rgba(15,23,42,0.06);
        border-radius: 18px; padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 16px 36px -26px rgba(15,23,42,0.2);
    }
    [data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid rgba(15,23,42,0.06); }

    /* ── Tabs ────────────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 26px; border-bottom: 1px solid rgba(15,23,42,0.08); background: transparent;
    }
    .stTabs [data-baseweb="tab"] { padding: 12px 0; font-size: 13.5px; font-weight: 600; color: #64748b; }
    .stTabs [aria-selected="true"] { color: #6355ff !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: #6355ff !important; height: 2.5px; }
    .stTabs [data-baseweb="tab-border"] { background-color: transparent; }

    .stButton > button {
        border-radius: 11px; border: 1px solid rgba(15,23,42,0.08);
        background: #ffffff; color: #475569; font-weight: 600; font-size: 12.5px;
    }
    .stButton > button:hover { border-color: #6355ff; color: #6355ff; }

    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}

    /* ═══ KILL THE SCRIPT-RUNNING DIM OVERLAY ══════════════════════════════ */
    .stApp[data-scriptrunstate="running"],
    .stApp[data-scriptrunstate="rerunning"],
    .stApp[data-teststate="running"] { opacity: 1 !important; }
    .stApp[data-scriptrunstate="running"] .main,
    .stApp[data-scriptrunstate="rerunning"] .main,
    .stApp[data-scriptrunstate="running"] section[data-testid="stMain"],
    .stApp[data-scriptrunstate="rerunning"] section[data-testid="stMain"],
    .stApp[data-teststate="running"] section[data-testid="stMain"] {
        opacity: 1 !important; filter: none !important; pointer-events: auto !important;
    }
    [data-testid="stStatusWidget"] { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }

    @keyframes fadeInUp { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    [data-testid="stChatMessage"] { animation: fadeInUp 0.25s ease-out; }

    .stApp[data-script-run-state="running"],
    .stApp[data-script-run-state="rerunning"],
    body[data-scriptrunstate="running"],
    body[data-scriptrunstate="rerunning"] { opacity: 1 !important; }

    .stButton > button:focus:not(:active),
    .stButton > button[data-testid="baseButton-secondary"]:disabled {
        opacity: 1 !important; color: #475569 !important; background: #ffffff !important;
    }
    div[data-testid="stAppViewBlockContainer"] { opacity: 1 !important; }
    iframe[title="streamlit_dim"] { display: none !important; }

    /* ── Force LIGHT on native widgets ───────────────────────────────────── */
    [data-testid="stDataFrame"], [data-testid="stTable"] { background:#ffffff !important; }
    div[data-baseweb="select"] > div { background:#ffffff !important; border-color:rgba(15,23,42,0.12) !important; }
    div[data-baseweb="select"] * { color:#0f172a !important; -webkit-text-fill-color:#0f172a !important; }
    ul[role="listbox"] { background:#ffffff !important; }
    li[role="option"] { color:#0f172a !important; background:#ffffff !important; }
    li[role="option"]:hover { background:#f1f2f8 !important; }
    .stDateInput input, .stTextInput input, div[data-baseweb="input"] input {
        background:#ffffff !important; color:#0f172a !important; -webkit-text-fill-color:#0f172a !important;
        border-color:rgba(15,23,42,0.12) !important;
    }
    [data-testid="stChatMessage"] { background:#ffffff !important; border:1px solid rgba(15,23,42,0.06) !important; border-radius:14px; }
    [data-testid="stChatMessage"] * { color:#0f172a !important; }
    [data-testid="stExpander"] details { background:#ffffff !important; border:1px solid rgba(15,23,42,0.08) !important; border-radius:12px; }
    [data-testid="stExpander"] summary, [data-testid="stExpander"] p, [data-testid="stExpander"] li,
    [data-testid="stExpander"] span, [data-testid="stExpander"] strong, [data-testid="stExpander"] h1,
    [data-testid="stExpander"] h2, [data-testid="stExpander"] h3 { color:#0f172a !important; }
    [data-testid="stExpanderDetails"], .streamlit-expanderContent { max-height:440px; overflow:auto; }
    [data-testid="stCaptionContainer"] * { color:#64748b !important; }
    [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { color:#0f172a; }

    /* ── Right-rail list styling ─────────────────────────────────────────── */
    .rail-title { display:flex; align-items:center; justify-content:space-between; margin-bottom:2px; }
    .rail-title h4 { margin:0; font-size:15px; font-weight:700; color:#0f172a; }
    .rail-title span { font-size:11px; font-weight:600; color:#6355ff; }
    .alert-row { display:flex; gap:12px; padding:11px 0; border-top:1px solid #f1f2f8; }
    .alert-bar { width:5px; flex:none; border-radius:3px; align-self:stretch; }
    .alert-body { flex:1; min-width:0; display:flex; flex-direction:column; gap:6px; }
    .alert-text { font-size:12.5px; font-weight:600; color:#0f172a; line-height:1.35; }
    .alert-meta { display:flex; align-items:center; gap:8px; }
    .alert-tag { font-size:9.5px; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; padding:2px 7px; border-radius:5px; }
    .alert-time { font-size:11px; font-weight:500; color:#94a3b8; }
    .reo-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-top:1px solid #f1f2f8; }
    .reo-name { font-size:12.5px; font-weight:700; color:#0f172a; }
    .reo-sub { font-size:11px; font-weight:500; color:#94a3b8; }
    .reo-qty { font-size:12.5px; font-weight:700; color:#0f172a; text-align:right; }
    .reo-pri { font-size:9.5px; font-weight:600; text-transform:uppercase; padding:2px 8px; border-radius:5px; display:inline-block; margin-top:4px; }

    iframe[title*="streamlit"] { display: block; margin-bottom: -8px !important; }
    div:has(> iframe[title*="streamlit"]) + div { margin-top: 0 !important; }
    div:has(> iframe[title*="streamlit"]) + div [data-testid="stExpander"] { margin-top: -20px !important; }
</style>
""", unsafe_allow_html=True)


# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────
def format_currency(value):
    if value is None or pd.isna(value):
        return f"0 {CURRENCY}"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f} M{CURRENCY}"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:,.0f} k{CURRENCY}"
    return f"{value:,.0f} {CURRENCY}"


def format_number(value, decimals=0):
    if value is None or pd.isna(value):
        return "0"
    if decimals == 0:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:,.{decimals}f}".replace(",", " ")


def format_pct(value):
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.1f}%"


def sparkline_svg(series, color, w=74, h=24):
    try:
        vals = [float(v) for v in series if v is not None and not pd.isna(v)]
    except (TypeError, ValueError):
        return ""
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1
    n = len(vals)
    pts = " ".join(
        f"{i * (w / (n - 1)):.0f},{h - 2 - ((v - mn) / rng) * (h - 4):.1f}"
        for i, v in enumerate(vals)
    )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def kpi_card(label, value, card_class="", delta="", delta_color="", spark="", small=False, info=""):
    foot = ""
    if delta or spark:
        dcol = delta_color or "#64748b"
        delta_html = f'<span class="kpi-delta" style="color:{dcol}">{delta}</span>' if delta else "<span></span>"
        foot = f'<div class="kpi-foot">{delta_html}{spark}</div>'
    vstyle = "font-size:15px;line-height:1.25;white-space:normal;word-break:break-word;" if small else ""
    info_html = (f'<span class="kpi-i" tabindex="0">i'
                 f'<span class="kpi-tip">{_esc(info)}</span></span>') if info else ""
    return f"""
    <div class="kpi-card {card_class}">
        <div class="kpi-top"><span class="kpi-dot"></span><span class="kpi-label">{label}</span>{info_html}</div>
        <div class="kpi-value" style="{vstyle}">{value}</div>
        {foot}
    </div>
    """


def style_fig(fig, height=360, legend=False):
    fig.update_layout(
        height=height,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#334155", size=12.5),
        margin=dict(l=0, r=12, t=10, b=34),
        xaxis=dict(gridcolor="#eef0f6", zeroline=False, linecolor="#eef0f6", automargin=True,
                   tickfont=dict(color="#475569", size=12), title_font=dict(color="#64748b", size=12)),
        yaxis=dict(gridcolor="#eef0f6", zeroline=False, linecolor="#eef0f6", automargin=True,
                   tickfont=dict(color="#334155", size=12.5), title_font=dict(color="#64748b", size=12)),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=-0.22, x=0, font=dict(size=11.5, color="#334155")),
        hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#fff", family="Plus Jakarta Sans")),
    )
    return fig


def _esc(v):
    s = "" if v is None else str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(s):
    return _esc(str(s)).replace('"', "&quot;")


def render_table(df, formats=None, aligns=None, cell_style=None, index=False,
                 height=None, wrap=None, zebra=True, raw_html=None):
    if df is None or len(df) == 0:
        st.markdown(f'<div style="padding:14px;color:#94a3b8;font-size:13px;">{T["no_data"]}</div>',
                    unsafe_allow_html=True)
        return
    formats = formats or {}
    aligns = aligns or {}
    cell_style = cell_style or {}
    wrap = set(wrap or [])
    cols = list(df.columns)

    _raw = set(raw_html or [])          # colonnes dont le HTML est déjà construit

    def fmt(col, v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        if col in _raw:                  # badge déjà assaini par le code appelant
            return str(v)
        f = formats.get(col)
        if f is None:
            return _esc(v)
        try:
            return _esc(f(v)) if callable(f) else _esc(f.format(v))
        except Exception:
            return _esc(v)

    def align(col):
        if col in aligns:
            return aligns[col]
        try:
            if pd.api.types.is_numeric_dtype(df[col]):
                return "right"
        except Exception:
            pass
        return "left"

    head = ""
    if index:
        head += ('<th style="position:sticky;top:0;z-index:1;background:#f8f9fc;color:#94a3b8;font-weight:600;'
                 'font-size:11px;padding:11px 12px;border-bottom:1px solid #e6e8f0;text-align:right;">#</th>')
    for c in cols:
        head += (f'<th style="position:sticky;top:0;z-index:1;background:#f8f9fc;color:#64748b;font-weight:600;'
                 f'font-size:11px;letter-spacing:.04em;text-transform:uppercase;padding:11px 14px;'
                 f'border-bottom:1px solid #e6e8f0;text-align:{align(c)};white-space:nowrap;">{_esc(c)}</th>')

    body = ""
    for i, (_, r) in enumerate(df.iterrows()):
        rbg = "#fbfbfe" if (zebra and i % 2) else "#ffffff"
        body += "<tr>"
        if index:
            body += (f'<td style="padding:10px 12px;border-bottom:1px solid #f1f2f8;color:#94a3b8;'
                     f'font-size:12px;text-align:right;background:{rbg};">{i}</td>')
        for c in cols:
            extra = ""
            if c in cell_style:
                try:
                    extra = cell_style[c](r[c]) or ""
                except Exception:
                    extra = ""
            ws = "normal;word-break:break-word;" if c in wrap else "nowrap;"
            body += (f'<td style="padding:10px 14px;border-bottom:1px solid #f1f2f8;color:#0f172a;'
                     f'font-size:13px;text-align:{align(c)};white-space:{ws}background:{rbg};{extra}">{fmt(c, r[c])}</td>')
        body += "</tr>"

    h = f"max-height:{height}px;" if height else ""
    st.markdown(
        f'<div style="border:1px solid #e6e8f0;border-radius:14px;overflow:auto;{h}background:#fff;'
        f'box-shadow:0 1px 2px rgba(15,23,42,0.04);"><table style="width:100%;border-collapse:collapse;'
        f"font-family:'Plus Jakarta Sans',sans-serif;\"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def sortable_table(df, formats=None, aligns=None, cell_style=None, height=560,
                   wrap=None, index=False):
    """Light HTML table with Excel-style click-to-sort column headers."""
    if df is None or len(df) == 0:
        st.markdown(f'<div style="padding:14px;color:#94a3b8;font-size:13px;">{T["no_data"]}</div>',
                    unsafe_allow_html=True)
        return
    formats = formats or {}
    aligns = aligns or {}
    cell_style = cell_style or {}
    wrap = set(wrap or [])
    cols = list(df.columns)

    def isnum(c):
        try:
            return pd.api.types.is_numeric_dtype(df[c])
        except Exception:
            return False

    def disp(c, v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        f = formats.get(c)
        if f is None:
            return _esc(v)
        try:
            return _esc(f(v)) if callable(f) else _esc(f.format(v))
        except Exception:
            return _esc(v)

    ths = ""
    col_offset = 1 if index else 0
    if index:
        ths += ('<th onclick="sortT(0)" style="text-align:right;color:#94a3b8;">'
                '#<span class="arw" id="arw0">&#8597;</span></th>')
    for j, c in enumerate(cols):
        actual_j = j + col_offset
        al = aligns.get(c, "right" if isnum(c) else "left")
        ths += ('<th onclick="sortT(%d)" style="text-align:%s;">%s'
                '<span class="arw" id="arw%d">&#8597;</span></th>'
                % (actual_j, al, _esc(c), actual_j))

    trs = ""
    for i, (_, r) in enumerate(df.iterrows()):
        tds = ""
        if index:
            tds += ('<td data-v="%d" style="text-align:right;color:#94a3b8;'
                    'font-size:12px;white-space:nowrap;">%d</td>' % (i, i))
        for c in cols:
            v = r[c]
            al = aligns.get(c, "right" if isnum(c) else "left")
            if isnum(c) and not (v is None or (isinstance(v, float) and pd.isna(v))):
                dv = _attr(float(v))
            else:
                dv = _attr(str(v).lower() if v is not None else "")
            extra = ""
            if c in cell_style:
                try:
                    extra = cell_style[c](v) or ""
                except Exception:
                    extra = ""
            ws = ("white-space:normal;word-break:break-word;" if c in wrap else "white-space:nowrap;")
            tds += ('<td data-v="%s" style="text-align:%s;%s%s">%s</td>'
                    % (dv, al, ws, extra, disp(c, v)))
        trs += "<tr>%s</tr>" % tds

    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap');
    *{box-sizing:border-box}
    body{margin:0;font-family:'Plus Jakarta Sans',system-ui,sans-serif;background:transparent;}
    .wrap{border:1px solid #e6e8f0;border-radius:14px;overflow:auto;max-height:%dpx;background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.04);}
    table{width:100%%;border-collapse:collapse;}
    th{position:sticky;top:0;z-index:1;background:#f8f9fc;color:#64748b;font-weight:600;font-size:11px;letter-spacing:.04em;text-transform:uppercase;padding:11px 14px;border-bottom:1px solid #e6e8f0;cursor:pointer;user-select:none;white-space:nowrap;}
    th:hover{color:#6355ff;background:#f1f2f8;}
    .arw{margin-left:6px;font-size:10px;color:#94a3b8;opacity:.5;}
    td{padding:10px 14px;border-bottom:1px solid #f1f2f8;color:#0f172a;font-size:13px;}
    tr:nth-child(even) td{background:#fbfbfe;}
    </style>
    """ % int(height - 20)

    script = """
    <script>
    function sortT(col){
      var t=document.getElementById('st'), tb=t.tBodies[0];
      var rows=Array.prototype.slice.call(tb.rows);
      var cur=t.getAttribute('data-col'), dir=t.getAttribute('data-dir')||'desc';
      if(String(col)===cur){dir=(dir==='asc')?'desc':'asc';}else{dir='desc';}
      t.setAttribute('data-col',col); t.setAttribute('data-dir',dir);
      rows.sort(function(a,b){
        var x=a.cells[col].getAttribute('data-v'), y=b.cells[col].getAttribute('data-v');
        var nx=parseFloat(x), ny=parseFloat(y), num=(!isNaN(nx)&&!isNaN(ny));
        var c = num ? (nx-ny) : (x<y?-1:(x>y?1:0));
        return dir==='asc'?c:-c;
      });
      rows.forEach(function(r){tb.appendChild(r);});
      var all=document.getElementsByClassName('arw');
      for(var i=0;i<all.length;i++){all[i].innerHTML='&#8597;';all[i].style.opacity=.5;all[i].style.color='#94a3b8';}
      var a=document.getElementById('arw'+col);
      if(a){a.innerHTML=(dir==='asc')?'&#8593;':'&#8595;';a.style.opacity=1;a.style.color='#6355ff';}
    }
    </script>
    """

    html = (css + '<div class="wrap"><table id="st"><thead><tr>' + ths
            + '</tr></thead><tbody>' + trs + '</tbody></table></div>' + script)
    components.html(html, height=height, scrolling=False)


def alert_box(kind, text):
    palette = {
        "success": ("#e7f7ef", "#0f7a4d", "#12b76a"),
        "warning": ("#fef3e2", "#a15c07", "#f79009"),
        "error":   ("#fdecec", "#b42318", "#e5484d"),
        "info":    ("#eaf1fe", "#1d4ed8", "#3b82f6"),
    }
    bg, fg, bar = palette.get(kind, palette["info"])
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {bar};color:{fg};'
        f'padding:11px 15px;border-radius:10px;font-size:13px;font-weight:600;margin:4px 0;">{text}</div>',
        unsafe_allow_html=True,
    )


def _bg_days_out(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v < 14:
        return "background:#fdecec;color:#b42318;font-weight:700;"
    if v < 30:
        return "background:#fef3e2;color:#a15c07;font-weight:700;"
    return "background:#e7f7ef;color:#0f7a4d;"


def _bg_action(v):
    s = str(v)
    if s in (T["act_reorder"], "Reorder", "Commander"):
        return "background:#fdecec;color:#b42318;font-weight:700;"
    if s in (T["act_liquidate"], "Liquidate", "Liquider"):
        return "background:#fef3e2;color:#a15c07;font-weight:700;"
    if s in (T["act_stop"], "Stop reordering", "Stopper réappro"):
        return "background:#fef3e2;color:#a15c07;font-weight:700;"
    return "background:#e7f7ef;color:#0f7a4d;"


def _bg_category(v):
    s = str(v)
    if s in ("critical", CN["critical"]):
        return "background:#fdecec;color:#b42318;font-weight:700;"
    if s in ("unstable", CN["unstable"]):
        return "background:#fef0e6;color:#b45309;font-weight:700;"
    if s in ("weak", CN["weak"]):
        return "background:#fef3e2;color:#a15c07;font-weight:600;"
    if s in ("acceptable", CN["acceptable"]):
        return "background:#eaf1fe;color:#1d4ed8;font-weight:600;"
    if s in ("solid", CN["solid"]):
        return "background:#e7f7ef;color:#0f7a4d;font-weight:600;"
    return ""


def _bg_variance(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if abs(v) > 20:
        return "background:#fdecec;color:#b42318;font-weight:700;"
    if abs(v) > 5:
        return "background:#fef3e2;color:#a15c07;font-weight:600;"
    return ""


@st.cache_data(ttl=300)
def get_kpi_history():
    """Recent daily industrial KPI snapshots for sparklines + deltas."""
    return run_query("""
        SELECT kpi_date, dead_stock_value, excess_stock_value, total_stock_value,
               annual_holding_cost, working_capital_tied, recoverable_cash_est,
               stock_turnover_ratio, supplier_otd_rate, avg_coverage_days
        FROM daily_kpis_industrial
        ORDER BY kpi_date ASC
        LIMIT 60
    """)


def kpi_deltas(hist):
    """Day-over-day delta per metric -> {key: (text, color)}."""
    out = {}
    if hist is None or hist.empty or len(hist) < 2:
        return out
    last, prev = hist.iloc[-1], hist.iloc[-2]
    # good_down=True  → a DECREASE is good (green when ↓, red when ↑)
    # good_down=False → an INCREASE is good (green when ↑, red when ↓)
    # Every metric has a defined good-direction, so grey is reserved for flat
    # (~0%) movements only — no KPI is permanently grey while it actually moves.
    spec = {
        "dead_stock_value": True,        # less dead stock = cash freed
        "excess_stock_value": True,      # less overstock = cash freed
        "annual_holding_cost": True,     # cheaper to hold = better
        "working_capital_tied": True,    # less capital immobilised = better
        "total_stock_value": True,       # lower trapped inventory = better (mission)
        "avg_coverage_days": True,       # shorter coverage = less overstock here
        "stock_turnover_ratio": False,   # rotate faster = better
        "supplier_otd_rate": False,      # more on-time = better
        "recoverable_cash_est": False,   # more identified opportunity = better
    }
    for col, good_down in spec.items():
        try:
            a, b = prev.get(col), last.get(col)
            if a in (None, 0) or pd.isna(a) or pd.isna(b):
                continue
            pct = (float(b) - float(a)) / abs(float(a)) * 100
            # No material change → neutral grey, flat arrow (never green/red on ~0%).
            if abs(pct) < 0.05:
                out[col] = ("→ 0.0%", "#94a3b8")
                continue
            up = pct > 0
            arrow = "↑" if up else "↓"
            good = (not up) if good_down else up
            color = "#12b76a" if good else "#e5484d"
            out[col] = (f"{arrow} {abs(pct):.1f}%", color)
        except (TypeError, ValueError):
            continue
    return out


# ── AI ASSISTANT: SAFETY + TOOLS ─────────────────────────────────────────────
def is_safe_query(sql):
    """Only allow read-only SELECT queries."""
    sql_clean = sql.strip().lower().split(";")[0]
    if not sql_clean.startswith("select") and not sql_clean.startswith("with"):
        return False
    forbidden = [
        r"\binsert\b", r"\bupdate\b", r"\bdelete\b", r"\bdrop\b",
        r"\balter\b", r"\bcreate\b", r"\btruncate\b", r"\bgrant\b",
        r"\brevoke\b", r"\bexec\b", r"\bexecute\b",
    ]
    return not any(re.search(p, sql_clean) for p in forbidden)


DATABASE_SCHEMA = """
DATABASE SCHEMA (PostgreSQL / Supabase) — INDUSTRIAL MODE:

TABLE: inventory  (one row per article × warehouse)
- article_code (text) — ERP article reference
- product_name (text) — description
- sku (text) — same as article_code, unique key
- article_type (text) — PF (finished goods) / SF (semi-finished) / COMP (components)
    / MP (raw materials) / CONS (consumables) / EMB (packaging) / PDR (spare parts) / NA
- article_family (text), category (text) — product family
- warehouse (text) — storage location
- current_stock (numeric), stock_available, stock_reserved, stock_blocked, stock_in_qc
- unit_of_measure (text)
- unit_cost (numeric) — weighted average cost (PMP/CMUP)
- unit_price (numeric) — selling price
- erp_stock_value (numeric) — valuation as reported by the ERP
- moq (numeric), order_multiple (numeric)
- erp_safety_stock, erp_reorder_point, erp_lead_time_days — parameters AS SET IN THE ERP
- supplier_name (text)
- last_movement_date (timestamp), days_since_movement (int)
- avg_daily_consumption (numeric) — from issue movements over 365d
- consumption_stddev (numeric), coefficient_variation (numeric)
- coverage_days (numeric) — current_stock / avg_daily_consumption
- abc_class (text) — A/B/C by annual consumption value (Pareto 80/15/5)
- xyz_class (text) — X (CV<0.5 regular) / Y (0.5-1.0) / Z (>1.0 erratic)
- actual_lead_time_days (numeric) — MEASURED from real receipts
- lead_time_stddev (numeric) — lead time variability, drives safety stock
- calculated_safety_stock, calculated_reorder_point — OUR recomputed values
- is_dead_stock (bool) — no movement beyond the threshold for its article_type
- is_excess (bool) — coverage above the type's target
- is_stockout_risk (bool) — coverage below the type's alert level
- trapped_value (numeric) — value locked in dead stock
- excess_value (numeric) — value above target coverage
- annual_holding_cost (numeric) — value × holding rate for its type

TABLE: article_types  (thresholds per article type — this is what makes the analysis smart)
- code (text) — PF / SF / COMP / MP / CONS / EMB / PDR / NA
- label_fr, label_en (text)
- dead_stock_days (int) — dormancy threshold; PDR = 1095 days (3y), PF = ~180
- target_coverage_days (int) — target coverage
- stockout_alert_days (int) — alert level
- holding_cost_rate (numeric) — annual holding cost rate

TABLE: stock_movements  (~75k rows, 12 months of history)
- movement_id (text, unique), movement_date (timestamp)
- article_code (text), article_name (text)
- movement_type (text) — issue / receipt / transfer / adjustment / scrap
- quantity (numeric, always positive), unit_of_measure, warehouse
- document_ref, document_type, unit_cost

TABLE: purchase_orders  (~3k lines)
- po_id (text), po_line (int) — unique together
- order_date (date), promised_date (date), received_date (date)
- supplier_name (text), supplier_code (text)
- article_code, article_name
- quantity_ordered, quantity_received, unit_of_measure, unit_price, currency
- po_status (text)

TABLE: orders  (customer orders)
- order_id (text), order_date (timestamp), product_name, category
- quantity, unit_price, total_amount, customer_segment, order_region

TABLE: daily_kpis_industrial  (one snapshot row per day)
- kpi_date (date)
- total_stock_value, total_stock_value_erp, valuation_gap_pct
- dead_stock_value, dead_stock_ref_count, dead_stock_pct
- excess_stock_value, excess_stock_ref_count
- working_capital_tied, annual_holding_cost, recoverable_cash_est
- stock_turnover_ratio, avg_coverage_days
- stockout_ref_count, stockout_risk_ref_count
- supplier_otd_rate, avg_lead_time_deviation
- total_active_refs, movements_count_24h

TABLE: data_quality_log
- audit_date, table_name, issue_code, issue_label_en, issue_label_fr
- affected_rows (int), severity (text: 'critical' | 'warning')

VIEW: v_supplier_scorecard_robust  (supplier segmentation, works even without promised_date)
- supplier_name, commandes_total
- lt_moyen (avg lead time), lt_stddev, cv_lead_time (variability coefficient)
- pct_avec_promised, otd_when_measurable, pct_livraison_partielle
- risk_score (0-100, higher = worse)
- supplier_category — critical / unstable / weak / acceptable / solid / no_promised_data

OTHER VIEWS: v_dead_stock, v_excess_stock, v_stockout_risk, v_abc_xyz_matrix, v_parameter_drift

KEY DEFINITIONS (industrial context):
- Dead stock: no movement beyond the article type's own threshold. Spare parts (PDR)
  legitimately sit 3 years without moving — flagging them as dead is a classic false positive.
- Safety stock formula used: SS = Z × sqrt(LT × sigma_demand² + demand² × sigma_LT²)
  with Z = 2.05 (class A), 1.65 (B), 1.28 (C).
- Lead time VARIABILITY (lt_stddev / cv_lead_time), not the average, is what drives
  required safety stock. Most SMEs set "2 weeks" once and never revisit it.
- Parameter drift: gap between erp_lead_time_days and actual_lead_time_days, or between
  erp_safety_stock and calculated_safety_stock. Large gaps mean the ERP is placing
  orders on stale assumptions.
- OTD: received_date <= promised_date. Below 85% is weak, below 70% is a real problem.
- Recoverable cash: 55% of dead stock value (liquidation discount) + 85% of excess
  (you just stop reordering).
"""

if CLIENT_LANG == "fr":
    SYSTEM_PROMPT = f"""Vous êtes l'analyste IA intégré à SupplyStack, une plateforme d'intelligence supply chain destinée aux PME et ETI industrielles. Vous répondez aux questions sur les stocks, mouvements, commandes fournisseurs et paramètres ERP du client en interrogeant sa base de données en direct.

{DATABASE_SCHEMA}

RÈGLES :
1. Utilisez l'outil query_database pour répondre avec des données réelles. N'inventez jamais de chiffres.
2. Seules les requêtes SELECT sont autorisées. L'outil rejette tout le reste.
3. Donnez des réponses concrètes et actionnables avec des montants chiffrés en euros. Ne vous contentez pas de rapporter les chiffres — interprétez-les et recommandez des actions.
4. Raisonnez en industriel, pas en e-commerce. Une pièce de rechange qui ne bouge pas pendant 2 ans est normale ; un produit fini qui ne bouge pas 6 mois est un problème. Utilisez toujours article_types pour contextualiser un seuil.
5. Reliez les métriques entre elles : une forte variabilité de délai fournisseur (lt_stddev) impose un stock de sécurité plus élevé ; un paramètre ERP obsolète cause à la fois du surstock et des ruptures ; les articles classés Z ne peuvent pas être pilotés par une formule standard.
6. Formatez les montants clairement (12 400 € plutôt que 12400.0).
7. Réponses concises — 2 à 4 paragraphes courts. Commencez par la réponse, puis le contexte, puis la recommandation.
8. Si une question est ambiguë, faites une hypothèse raisonnable et énoncez-la.
9. Si la donnée manque, dites précisément quelle colonne ou quel export ERP serait nécessaire.
10. Répondez TOUJOURS en français, avec la ponctuation française.
11. LIMITE STRICTE : 2 requêtes SQL maximum par réponse. Après 2 requêtes, vous DEVEZ répondre avec les données disponibles.
12. Pour les questions larges, posez UNE requête exhaustive avec JOINs et CTEs plutôt que d'enchaîner les allers-retours.
13. Utilisez le vocabulaire métier français : référence, article, famille, magasin, dépôt, PMP, point de commande, stock de sécurité, délai d'approvisionnement, couverture.

Exemple de bonne réponse :
"Votre stock dormant représente 206 550 € sur 50 références, soit 5,3 % de la valeur totale. Point important : aucune pièce de rechange n'est concernée — leur seuil de dormance est fixé à 3 ans, ce qui évite 200 faux positifs qu'un outil générique aurait signalés. Le vrai sujet est sur les composants : 294 références en surstock pour 202 672 €. Recommandation : gelez les réapprovisionnements sur ces 294 références pendant un trimestre, cela libère l'essentiel des 202 k€ sans aucune remise commerciale."
"""
else:
    SYSTEM_PROMPT = f"""You are the AI analyst embedded in SupplyStack, a supply chain intelligence platform for industrial SMEs and mid-caps. You answer questions about the client's inventory, movements, purchase orders and ERP parameters by querying their live database.

{DATABASE_SCHEMA}

RULES:
1. Use the query_database tool to answer with real data. Never invent figures.
2. Only SELECT queries are allowed. The tool rejects anything else.
3. Give concrete, actionable answers with figures in euros. Don't just report numbers — interpret them and recommend actions.
4. Reason like an industrial planner, not an e-commerce operator. A spare part sitting still for two years is normal; a finished good sitting still for six months is a problem. Always contextualise thresholds using article_types.
5. Connect metrics: high supplier lead time variability (lt_stddev) forces higher safety stock; a stale ERP parameter causes both overstock and stockouts; Z-class items cannot be driven by a standard formula.
6. Format amounts clearly (€12,400 rather than 12400.0).
7. Keep answers concise — 2 to 4 short paragraphs. Answer first, then context, then recommendation.
8. If a question is ambiguous, make a reasonable assumption and state it.
9. If data is missing, say precisely which column or ERP export would be needed.
10. STRICT LIMIT: 2 SQL queries maximum per answer. After 2 queries you MUST answer with what you have.
11. For broad questions, issue ONE exhaustive query with JOINs and CTEs rather than chaining round trips.
"""

TOOLS = [
    {
        "name": "query_database",
        "description": "Execute a read-only SQL SELECT query against the industrial supply chain PostgreSQL database. Returns results as JSON. Use this to answer any question about inventory, stock movements, purchase orders, suppliers, ERP parameters or KPIs with real data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A PostgreSQL SELECT query. Only SELECT statements are allowed. Use LIMIT for large result sets (max 50 rows).",
                }
            },
            "required": ["sql"],
        },
    }
]


def execute_tool_call(sql):
    if not is_safe_query(sql):
        return "ERROR: Only SELECT queries are allowed. Query rejected for safety.", None
    try:
        df = run_query_uncached(sql)
        if df.empty:
            return "Query returned no results.", None
        df_limited = df.head(50)
        return df_limited.to_json(orient="records", date_format="iso"), df_limited
    except Exception as e:
        return f"ERROR executing query: {str(e)}", None


def _format_api_error(e):
    if e.status_code == 529:
        return ("⚠️ Les serveurs d'Anthropic sont actuellement surchargés. Merci de réessayer dans une minute."
                if CLIENT_LANG == "fr" else
                "⚠️ Anthropic servers are currently overloaded. Please retry in a minute.")
    if e.status_code == 429:
        return ("⚠️ Limite de débit atteinte. Patientez quelques secondes puis réessayez."
                if CLIENT_LANG == "fr" else "⚠️ Rate limit reached. Wait a few seconds and retry.")
    if e.status_code == 401:
        return ("⚠️ Clé API rejetée. Vérifiez `anthropic_api_key` dans les secrets Streamlit."
                if CLIENT_LANG == "fr" else "⚠️ API key rejected. Check `anthropic_api_key` in Streamlit secrets.")
    return f"⚠️ AI request failed ({e.status_code}): {getattr(e, 'message', str(e))}"


def ask_claude(user_question, conversation_history, text_placeholder=None, system_prompt=None):
    """Send question to Claude with streaming + tool calling."""
    try:
        import anthropic
    except ImportError:
        msg = "The 'anthropic' package is not installed. Run: pip install anthropic>=0.40"
        if text_placeholder is not None:
            text_placeholder.markdown(msg)
        return msg, []

    if not ANTHROPIC_API_KEY:
        msg = ("⚠️ Clé API Anthropic non configurée. Streamlit Cloud → Manage app → Settings → Secrets, "
               "ajoutez : anthropic_api_key = \"sk-ant-...\""
               if CLIENT_LANG == "fr" else
               "⚠️ Anthropic API key not configured. Streamlit Cloud → Manage app → Settings → Secrets, "
               "add: anthropic_api_key = \"sk-ant-...\"")
        if text_placeholder is not None:
            text_placeholder.markdown(msg)
        return msg, []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=45.0, max_retries=3)

    system_param = [{
        "type": "text",
        "text": system_prompt or SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    fallback_chain = [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
    ]

    messages = [{"role": m["role"], "content": m["content"]} for m in conversation_history]
    messages.append({"role": "user", "content": user_question})

    dataframes = []
    max_iterations = 6
    model_used = None

    for _iteration in range(max_iterations):
        streamed_ok = False
        final_message = None
        accumulated_text = ""

        for model in fallback_chain:
            try:
                accumulated_text = ""
                with client.messages.stream(
                    model=model,
                    max_tokens=6000,
                    system=system_param,
                    tools=TOOLS,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        accumulated_text += text
                        if text_placeholder is not None:
                            text_placeholder.markdown(
                                accumulated_text + " <span style='color:#6355ff;opacity:0.7'>▊</span>",
                                unsafe_allow_html=True,
                            )
                    final_message = stream.get_final_message()
                streamed_ok = True
                model_used = model
                break
            except anthropic.APIStatusError as e:
                if e.status_code in (429, 529):
                    continue
                err = _format_api_error(e)
                if text_placeholder is not None:
                    text_placeholder.markdown(err)
                return err, dataframes
            except Exception as e:
                err = f"⚠️ Unexpected error contacting the AI: {e}"
                if text_placeholder is not None:
                    text_placeholder.markdown(err)
                return err, dataframes

        if not streamed_ok:
            err = ("⚠️ Tous les modèles d'IA sont actuellement surchargés. Réessayez dans une minute."
                   if CLIENT_LANG == "fr" else
                   "⚠️ All AI models are currently overloaded. Retry in a minute.")
            if text_placeholder is not None:
                text_placeholder.markdown(err)
            return err, dataframes

        if final_message.stop_reason == "tool_use":
            if text_placeholder is not None:
                querying = ("Interrogation de votre base de données…" if CLIENT_LANG == "fr"
                            else "Querying your database…")
                text_placeholder.markdown(
                    f"🔍 <span style='color:#6355ff;font-weight:600'>{querying}</span>",
                    unsafe_allow_html=True,
                )
            messages.append({"role": "assistant", "content": final_message.content})
            tool_results = []
            for block in final_message.content:
                if block.type == "tool_use":
                    sql = block.input.get("sql", "")
                    try:
                        result_str, df = execute_tool_call(sql)
                        if df is not None:
                            dataframes.append((sql, df))
                    except Exception as e:
                        result_str = f"ERROR executing query: {str(e)}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            final_answer = accumulated_text
            if model_used and model_used != "claude-haiku-4-5-20251001":
                final_answer += (
                    f"\n\n<sub style='color:#94a3b8;'>⚡ Answered by {model_used}</sub>"
                )
            if text_placeholder is not None:
                text_placeholder.markdown(final_answer, unsafe_allow_html=True)
            return final_answer, dataframes

    fallback_msg = ("L'assistant a fait trop d'étapes. Essayez de reformuler votre question."
                    if CLIENT_LANG == "fr" else
                    "The assistant took too many steps. Try rephrasing your question.")
    if text_placeholder is not None:
        text_placeholder.markdown(fallback_msg)
    return fallback_msg, dataframes


# ── AURORA HEADER ─────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex; align-items:center; gap:16px; padding:4px 2px 20px; margin-bottom:6px;">
    <div style="width:40px; height:40px; border-radius:12px;
         background:linear-gradient(135deg,#6355ff,#9d8bff);
         display:flex; align-items:center; justify-content:center; font-size:19px; font-weight:800; color:#fff;
         box-shadow:0 8px 18px -8px rgba(99,85,255,0.7);">S</div>
    <div style="display:flex; flex-direction:column; gap:2px;">
        <span style="font-size:9.5px; font-weight:600; letter-spacing:0.18em; color:#a5aec4;">SUPPLYSTACK · INDUSTRIAL</span>
        <span style="font-size:22px; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">{T['header_sub']}</span>
    </div>
    <div style="flex:1;"></div>
    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px; margin-right:6px;">
        <span style="font-size:13px; font-weight:700; color:#0f172a;">{CLIENT_NAME}</span>
        <span style="font-size:11px; font-weight:500; color:#94a3b8;">{datetime.now().strftime('%d/%m/%Y %H:%M')}</span>
    </div>
    <div style="width:38px; height:38px; border-radius:50%;
         background:linear-gradient(135deg,#6355ff,#c084fc);
         display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#fff;">{CLIENT_INITIALS}</div>
</div>
""", unsafe_allow_html=True)

# ── DATE RANGE BOUNDS (the selector itself lives in the Suppliers tab) ───────
_bounds = run_query("SELECT MIN(order_date)::date AS mn, MAX(order_date)::date AS mx FROM purchase_orders")
if not _bounds.empty and _bounds.iloc[0]["mx"] is not None:
    DATA_MIN = pd.to_datetime(_bounds.iloc[0]["mn"]).date()
    DATA_MAX = pd.to_datetime(_bounds.iloc[0]["mx"]).date()
else:
    DATA_MAX = date.today()
    DATA_MIN = DATA_MAX - timedelta(days=365)

if CLIENT_LANG == "fr":
    PRESETS = {
        "Tout l'historique": None, "12 derniers mois": 365, "6 derniers mois": 182,
        "90 derniers jours": 90, "Période personnalisée…": "custom",
    }
    ALL_LABEL = "Tout l'historique"
    CUSTOM_LABEL = "Période personnalisée…"
else:
    PRESETS = {
        "All history": None, "Last 12 months": 365, "Last 6 months": 182,
        "Last 90 days": 90, "Custom range…": "custom",
    }
    ALL_LABEL = "All history"
    CUSTOM_LABEL = "Custom range…"

# ── NAVIGATION ────────────────────────────────────────────────────────────────
# A radio backed by session_state rather than st.tabs. Two reasons:
#   1. st.tabs resets to the first tab on every rerun, so any button click
#      (AI suggestions, form submit, filters) bounced the user back to the
#      executive view.
#   2. st.tabs renders every tab body on every run — all seven sets of queries
#      fired to display one screen. Here only the selected page executes.
# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTION MODULE — impact économique des gaspillages industriels
#
# Règles de conception (spec build v1.0) :
#   R1  aucun euro stocké : montant = quantité physique × règle de valorisation
#   R2  aucun TRS stocké : D, P, Q agrégés sur les temps, TRS toujours calculé
#   R3  un événement → exactement une nature économique
#   R4  les trois natures ne s'additionnent jamais dans un même indicateur
#   R5  tout coefficient de valorisation est un paramètre (bloc config en tête)
#   R6  écran sans données = message d'indisponibilité, jamais zéros ni erreur
#
# Source actuelle : jeu de démonstration en dur (MECAPRO). Le câblage Supabase
# (schéma prod_* v2) remplacera ces dictionnaires un onglet à la fois.
# ══════════════════════════════════════════════════════════════════════════════
_PF = (CLIENT_LANG == "fr")

P_SYNTH   = "📊 " + ("Synthèse production" if _PF else "Production overview")
P_FLOW    = "🗺️ " + ("Cartographie de flux" if _PF else "Flow map")
P_MUDA    = "🗑️ " + ("Les huit mudas" if _PF else "The eight wastes")
P_POSTE   = "🏭 " + ("Détail par poste" if _PF else "By workstation")
P_ACTIONS = "📋 " + ("Plan d'actions" if _PF else "Action plan")
P_SUIVI   = "📈 " + ("Suivi" if _PF else "Tracking")
P_AI      = "🤖 " + ("Assistant IA production" if _PF else "Production AI assistant")
PROD_PAGES = [P_SYNTH, P_FLOW, P_MUDA, P_POSTE, P_ACTIONS, P_AI, P_SUIVI]

# ── Les trois natures économiques (R3/R4) — jamais combinées ─────────────────
N_CONST = ("Pertes économiques constatées" if _PF else "Booked economic losses")
N_CAPA  = ("Capacité valorisée non exploitée" if _PF else "Unexploited valued capacity")
N_CAPI  = ("Capital immobilisé" if _PF else "Capital tied up")
PROD_NATURE_COLOR = {N_CONST: "#e5484d", N_CAPA: "#f79009", N_CAPI: "#6355ff"}

st.markdown("""
<style>
    .kpi-capital .kpi-dot { background: #6355ff; } .kpi-capital .kpi-value { color: #6355ff; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# DOCTRINE ET FONCTION DE VALORISATION  (dictionnaire de données §1, §3.5, §5)
#
# valoriser_evenement() est le POINT UNIQUE de conversion d'une quantité
# physique en euros. Aucun autre endroit du code ne le fait.
#
# Invariant §5.4 : un événement produit AU PLUS UNE ligne par nature économique.
# Un même arrêt peut coûter des heures payées (constate) ET du manque à produire
# (capacite) — ce ne sont pas les mêmes euros — mais jamais deux fois la même.
# ══════════════════════════════════════════════════════════════════════════════
NAT_CONST, NAT_CAPA, NAT_CAPI = "constate", "capacite", "capital"
# Correspondance code interne -> libellé affiché (défini APRÈS N_CONST/N_CAPA/N_CAPI)
NATURE_UI = {NAT_CONST: N_CONST, NAT_CAPA: N_CAPA, NAT_CAPI: N_CAPI}

PROD_DOCTRINE = {
    "defauts":        dict(fr="Défauts", en="Defects", unite="pieces", nature=NAT_CONST),
    "attente":        dict(fr="Attente", en="Waiting", unite="heures", nature=NAT_CAPA),
    "transport":      dict(fr="Transport", en="Transport", unite="heures", nature=NAT_CAPA),
    "sur_traitement": dict(fr="Sur-traitement", en="Over-processing", unite="heures", nature=NAT_CAPA),
    "mouvements":     dict(fr="Mouvements", en="Motion", unite="heures", nature=NAT_CAPA),
    "competences":    dict(fr="Sous-utilisation des compétences", en="Skill under-use", unite="heures", nature=NAT_CAPA),
    "surproduction":  dict(fr="Surproduction", en="Overproduction", unite="unites", nature=NAT_CAPI),
    "stocks_encours": dict(fr="Stocks / encours", en="Inventory / WIP", unite="unites", nature=NAT_CAPI),
}
# NATURE_UI est renseigné juste après la définition de N_CONST / N_CAPA / N_CAPI

METHODES_FINES = {"E3_cout_direct", "E5_non_contraint", "E6_recuperable",
                  "E6_perte_ferme", "E2_aucune_ressource", "portage", "defauts_directs"}


def indice_confiance(source, niveau_cout):
    """§1.3 — ★★★ = mesuré/système ET coût client validé. ★ = dès qu'un axe est estimatif."""
    s = (source or "E").upper()
    n = (niveau_cout or "C").upper()
    if s in ("M", "S") and n == "A":
        return 3
    if (s in ("M", "S") and n == "B") or (s == "E" and n == "A"):
        return 2
    return 1


def etoiles(conf):
    return "★" * int(conf) + "☆" * (3 - int(conf))


def valoriser_evenement(ev, poste, mesure, cfg=None):
    """Quantité physique -> euros, selon l'arbre E1→E6 du dictionnaire §5.

    ev     : type_muda, quantite, unite, duree_arret_h, ressource_bloquee,
             operateur_reaffecte, recuperable_avant_echeance, source, niveau_cout,
             cout_unitaire (mudas 'capital'), rebut_pcs / retouche_h (défauts)
    poste  : cout_horaire_mo, cout_horaire_machine, nb_operateurs, nb_machines
    mesure : charge_requise_h, capacite_nette_h, temps_cycle_effectif_s

    Retourne une liste de lignes {nature, montant, methode, confiance} —
    au plus une par nature (invariant §5.4)."""
    c = cfg or dict(marge=MARGE_COUT_VARIABLE_UNITAIRE, seuil=SEUIL_CONTRAINTE,
                    absorption=TAUX_ABSORPTION_DEMANDE, possession=TAUX_POSSESSION_ANNUEL)
    muda = ev["type_muda"]
    doc = PROD_DOCTRINE.get(muda, dict(nature=NAT_CAPA))
    src, niv = ev.get("source", "E"), ev.get("niveau_cout", "C")
    conf = int(ev.get("confiance") or indice_confiance(src, niv))
    L = lambda nature, montant, methode, cf=None: dict(
        nature=nature, montant=float(max(montant, 0.0)), methode=methode, confiance=int(cf or conf))

    # ── Capital immobilisé : valeur × taux de portage ────────────────────────
    if doc["nature"] == NAT_CAPI:
        val = float(ev["quantite"]) * float(ev.get("cout_unitaire", 0.0))
        return [L(NAT_CAPI, val * c["possession"], "portage")]

    # ── Défauts : décaissement réel (matière au coût cumulé + retouche payée) ─
    if muda == "defauts":
        mat = float(ev.get("rebut_pcs", 0.0)) * float(ev.get("cout_unitaire", 0.0))
        mo = float(ev.get("retouche_h", 0.0)) * float(poste.get("cout_horaire_mo", COUT_HORAIRE_MO)) \
            * float(poste.get("nb_operateurs", 1))
        return [L(NAT_CONST, mat + mo, "defauts_directs")]

    # ── Mudas de temps : E1 → E6 ─────────────────────────────────────────────
    duree = float(ev.get("duree_arret_h") or ev.get("quantite") or 0.0)
    ressource = str(ev.get("ressource_bloquee") or "les_deux")
    reaffecte = bool(ev.get("operateur_reaffecte", False))

    # E2 — aucune ressource bloquée : 0 €, résultat VALIDE (pas une absence de données)
    if ressource == "aucune":
        return [L(doc["nature"], 0.0, "E2_aucune_ressource")]

    lignes = []
    # E3 — coût direct : l'opérateur est immobilisé et n'a pas été réaffecté
    if not reaffecte:
        mo_h = float(poste.get("cout_horaire_mo", COUT_HORAIRE_MO)) * float(poste.get("nb_operateurs", 1))
        lignes.append(L(NAT_CONST, duree * mo_h, "E3_cout_direct"))

    # E4/E5/E6 — capacité, seulement si la machine est bloquée
    if ressource in ("machine", "les_deux"):
        charge = mesure.get("charge_requise_h")
        capa = mesure.get("capacite_nette_h")
        cycle_eff = float(mesure.get("temps_cycle_effectif_s") or 0.0)
        if charge and capa and float(capa) > 0:
            taux = float(charge) / float(capa)
            if taux < c["seuil"]:
                # E5 — poste non contraint : le travail se termine quand même
                lignes.append(L(NAT_CAPA, 0.0, "E5_non_contraint"))
            elif ev.get("recuperable_avant_echeance"):
                # E6 — la perte est rattrapée avant l'échéance
                lignes.append(L(NAT_CAPA, 0.0, "E6_recuperable"))
            else:
                # E4 puis E6 — perte ferme de production sur un poste contraint
                pieces = (duree * 3600.0 / cycle_eff) if cycle_eff > 0 else 0.0
                nbm = float(poste.get("nb_machines", 1) or 1)
                if nbm > 1:
                    pieces /= nbm
                lignes.append(L(NAT_CAPA, pieces * c["marge"], "E6_perte_ferme"))
        else:
            # Repli §5.3 — charge/capacité inconnues : ancienne méthode, confiance ★
            poste_h = (float(poste.get("cout_horaire_machine", COUT_HORAIRE_MACHINE))
                       + float(poste.get("cout_horaire_mo", COUT_HORAIRE_MO)) * float(poste.get("nb_operateurs", 1)))
            lignes.append(L(NAT_CAPA, duree * poste_h * c["absorption"], "absorption_globale", 1))

    # Invariant §5.4 — au plus une ligne par nature
    vues, out = set(), []
    for l in lignes:
        if l["nature"] in vues:
            continue
        vues.add(l["nature"])
        out.append(l)
    return out


# ── Paramètres de la campagne de mesure (relevés terrain, pas des coefficients)
PROD_CAMPAGNE = {
    "campagne": "T1",
    "demande_client_jour": 191,      # pièces / jour
    "production_reelle_jour": 178,   # pièces / jour constatées
    "otif_client": 0.932,            # OTIF client mesuré
    "taux_surproduction": 0.05,      # estimation terrain (part produite au-delà de la demande)
    "heures_competences_an": 640.0,  # heures qualifiées sur tâches sans valeur (déclaratif)
}


@st.cache_data(show_spinner=False)
def prod_demo():
    """Relevés terrain de démonstration — ligne Carter aluminium, 9 postes.
    Les temps annuels (requis, fonctionnement) sont dérivés des taux observés
    pour rester cohérents avec R2 : les ratios affichés sont recalculés depuis
    les temps, jamais stockés."""
    families = pd.DataFrame([
        {"product_family": "Carter aluminium", "standard_cost": 85, "material_cost": 32,
         "annual_volume": 42000, "sale_price": 140},
    ])
    steps = pd.DataFrame([
        # ordre, poste, atelier, famille, cyc_nominal_s, va_s, chg_min, lot, wip, scrap, rework, D, P, ops, mach€/h, mo€/h, transp_s, motion_s, nb_mach, ouv_h/j
        (1, "Débit / Sciage",  "Découpe",       "Carter aluminium",  45, 20, 25, 200, 45, .02,  .01, .82, .88, 1,   35, 32,  8,  6, 1, 8.0),
        (2, "Tournage",        "Usinage",       "Carter aluminium", 120, 75, 40, 150, 40, .03,  .02, .75, .84, 1,   55, 34,  6,  8, 2, 8.0),
        (3, "Fraisage",        "Usinage",       "Carter aluminium",  95, 60, 45, 150, 45, .025, .03, .78, .86, 1,   60, 34,  6,  7, 1, 8.0),
        (4, "Perçage",         "Usinage",       "Carter aluminium",  40, 28, 20, 150, 30, .015, .01, .85, .90, 1,   30, 32,  5,  5, 1, 8.0),
        (5, "Ébavurage",       "Parachèvement", "Carter aluminium",  60, 22, 10, 100, 40, .01,  .04, .90, .80, 2,    8, 30, 10, 14, 1, 8.0),
        (6, "Lavage",          "Parachèvement", "Carter aluminium",  35, 15,  8, 300, 30, .005, .0,  .93, .88, 0.5, 20, 30,  6,  5, 1, 8.0),
        (7, "Contrôle",        "Contrôle",      "Carter aluminium",  50, 10,  5,  50, 25, .0,   .05, .95, .82, 1,    5, 33,  4,  6, 1, 8.0),
        (8, "Assemblage",      "Assemblage",    "Carter aluminium", 140, 95, 15,  80, 55, .02,  .03, .88, .85, 2,   12, 32,  8, 12, 1, 8.0),
        (9, "Conditionnement", "Expédition",    "Carter aluminium",  30, 12,  5, 500, 20, .002, .0,  .96, .90, 1,    6, 29, 12,  8, 1, 8.0),
    ], columns=["step_order", "step_name", "workshop", "product_family", "cycle_time_sec",
                "value_added_sec", "changeover_min", "batch_size", "wip_units", "scrap_rate",
                "rework_rate", "availability_rate", "performance_rate", "operators",
                "machine_hourly_cost", "labour_hourly_cost", "transport_sec", "motion_sec",
                "nb_machines", "ouverture_h_jour"])
    steps["ligne"] = "Ligne Carter"
    return steps, families


def _prod_core(s, lp, evts_db=None):
    """Moteur unique de calcul — alimenté soit par la démo, soit par la base.
    temps → ratios (R2), quantités physiques → euros (R1), une nature par muda
    (R3), aucun total inter-natures (R4).
    s  : relevés par poste ; lp : paramètres de ligne (économie produit, demande)."""
    s = s.sort_values("step_order").reset_index(drop=True)
    vol = float(lp["annual_volume"]); sc = float(lp["standard_cost"]); mat = float(lp["material_cost"])
    D, P = s["availability_rate"], s["performance_rate"]
    ops, lab, mach = s["operators"], s["labour_hourly_cost"], s["machine_hourly_cost"]
    poste_h = mach + lab * ops
    s["poste_hourly"] = poste_h

    # ── Quantités & temps annuels (base physique, R1/R2) ────────────────────
    s["quality_rate"] = (1 - s["scrap_rate"]) * (1 - s["rework_rate"])
    s["pieces_bonnes"] = float(vol)
    s["pieces_produites"] = vol / s["quality_rate"]
    s["temps_fonctionnement_h"] = s["pieces_produites"] * s["cycle_time_sec"] / P / 3600.0
    s["temps_requis_h"] = s["temps_fonctionnement_h"] / D
    s["temps_ouverture_h"] = s["temps_requis_h"] / (1 - TAUX_ARRETS_PLANIFIES)
    s["trs"] = D * P * s["quality_rate"]
    s["eff_cycle"] = s["cycle_time_sec"] / (D * P)          # cycle effectif complet (affichage)
    s["cycle_perf"] = s["cycle_time_sec"] / P               # cycle dégradé performance (capacité)

    # ── Goulot par taux de charge (spec 2.4) ────────────────────────────────
    demande = float(lp["demande"])
    s["capacite_nette_jour"] = (s["ouverture_h_jour"] * 3600.0 * s["nb_machines"] * D) / s["cycle_perf"]
    s["taux_charge"] = demande / s["capacite_nette_jour"]

    # ── Quantités physiques par muda ────────────────────────────────────────
    s["rebut_pcs"] = s["pieces_produites"] * s["scrap_rate"]
    s["retouche_pcs"] = s["pieces_produites"] * s["rework_rate"]
    s["rework_h"] = s["retouche_pcs"] * s["value_added_sec"] / 3600.0
    s["downtime_h"] = s["temps_requis_h"] - s["temps_fonctionnement_h"]
    s["transport_h"] = s["pieces_produites"] * s["transport_sec"] / 3600.0
    s["motion_h"] = s["pieces_produites"] * s["motion_sec"] / 3600.0
    nonva = (s["cycle_time_sec"] - s["value_added_sec"]).clip(lower=0)
    s["surtraitement_h"] = s["pieces_produites"] * (PART_SURTRAITEMENT_NONVA * nonva) / 3600.0
    s["wip_value"] = s["wip_units"] * sc

    # ── Valorisation : TOUT passe par valoriser_evenement (dictionnaire §5) ──
    tot_va = s["value_added_sec"].sum()
    s["cost_at_step"] = mat + (s["value_added_sec"].cumsum() / tot_va) * (sc - mat)
    # Charge/capacité par poste : ce sont elles qui permettent à E5 de trancher.
    # Charge et capacité annuelles — MÊME définition que le taux de charge affiché
    # comme goulot, sinon E5 trancherait sur un critère différent de l'écran.
    s["capacite_nette_h"] = s["ouverture_h_jour"] * JOURS_OUVRES_AN * s["nb_machines"] * D
    s["charge_requise_h"] = demande * JOURS_OUVRES_AN * s["cycle_perf"] / 3600.0

    _evts = []            # journal des événements valorisés (base des mudas)
    for _, r in (s.iterrows() if evts_db is None else []):
        poste = dict(cout_horaire_mo=r["labour_hourly_cost"], cout_horaire_machine=r["machine_hourly_cost"],
                     nb_operateurs=r["operators"], nb_machines=r["nb_machines"])
        mesure = dict(charge_requise_h=r["charge_requise_h"], capacite_nette_h=r["capacite_nette_h"],
                      temps_cycle_effectif_s=r["eff_cycle"])
        base = dict(poste=r["step_name"], workshop=r["workshop"],
                    source=r.get("source", "M"), niveau_cout=r.get("niveau_cout", "B"))
        # défauts — décaissement réel, rebut valorisé au coût cumulé de l'étape
        _evts.append((dict(type_muda="defauts", quantite=r["rebut_pcs"] + r["retouche_pcs"],
                           unite="pieces", occurrences=int(max(1, r["rebut_pcs"] / 12)),
                           rebut_pcs=r["rebut_pcs"], retouche_h=r["rework_h"],
                           cout_unitaire=r["cost_at_step"], **base), poste, mesure))
        # mudas de temps — l'arbre E1→E6 décide si la capacité vaut quelque chose
        # Distinction de doctrine (§5.1) :
        #  · attente = l'opérateur est OISIF et payé -> coût direct constaté (E3)
        #    + test de capacité si la machine est bloquée
        #  · transport / mouvements / sur-traitement = heures TRAVAILLÉES sans valeur.
        #    Les supprimer ne rembourse aucun salaire, cela libère de la capacité :
        #    pas de coût MO (opérateur occupé), on passe directement à E5/E6.
        for muda, h, ress, reaff in [("attente", r["downtime_h"], "les_deux", False),
                                     ("transport", r["transport_h"], "machine", True),
                                     ("mouvements", r["motion_h"], "machine", True),
                                     ("sur_traitement", r["surtraitement_h"], "machine", True)]:
            _evts.append((dict(type_muda=muda, quantite=h, unite="heures", duree_arret_h=h,
                               occurrences=int(max(1, h / 2)), ressource_bloquee=ress,
                               operateur_reaffecte=reaff, **base), poste, mesure))
        # encours devant le poste — capital immobilisé
        # Encours valorisés au coût CUMULÉ à l'étape (cohérent avec le chemin base) :
        # une pièce en attente devant l'assemblage vaut plus qu'une devant le sciage.
        _evts.append((dict(type_muda="stocks_encours", quantite=r["wip_units"], unite="unites",
                           occurrences=1, cout_unitaire=r["cost_at_step"], **base), poste, mesure))

    # Grandeurs de LIGNE (une seule fois, jamais par poste)
    surprod_units = float(lp["surprod_units"])
    comp_h = float(lp["comp_h"])
    _line_poste = dict(cout_horaire_mo=COUT_HORAIRE_MO, cout_horaire_machine=COUT_HORAIRE_MACHINE,
                       nb_operateurs=1, nb_machines=1)
    if evts_db is not None:
        _evts = evts_db            # événements qualifiés lus en base (§3.4)
        surprod_units = float(sum(e[0]["quantite"] for e in evts_db if e[0]["type_muda"] == "surproduction"))
        comp_h = float(sum(e[0]["quantite"] for e in evts_db if e[0]["type_muda"] == "competences"))
    else:
        _evts.append((dict(type_muda="surproduction", quantite=surprod_units, unite="unites",
                           occurrences=14, cout_unitaire=sc, poste=None, workshop=None,
                           source="E", niveau_cout="C"), _line_poste, {}))
        # Compétences : heures qualifiées sur tâches sans valeur — travaillées, donc
        # capacité (repli absorption : aucune charge/capacité rattachée à un poste).
        _evts.append((dict(type_muda="competences", quantite=comp_h, unite="heures", duree_arret_h=comp_h,
                           occurrences=210, ressource_bloquee="machine", operateur_reaffecte=True,
                           poste=None, workshop=None, source="E", niveau_cout="C"), _line_poste, {}))

    # Exécution de la valorisation — point unique de conversion en euros
    _lig = []
    for ev, poste, mesure in _evts:
        for l in valoriser_evenement(ev, poste, mesure):
            _lig.append(dict(poste=ev.get("poste"), workshop=ev.get("workshop"),
                             type_muda=ev["type_muda"], quantite=float(ev["quantite"]),
                             unite=ev["unite"], occurrences=int(ev.get("occurrences", 1)),
                             heures=float(ev.get("duree_arret_h") or 0.0), **l))
    lignes = pd.DataFrame(_lig)

    # Report par poste (pour les tableaux et le graphe par atelier)
    _pv = lignes[lignes["poste"].notna()].pivot_table(
        index="poste", columns="nature", values="montant", aggfunc="sum").reindex(s["step_name"]).fillna(0.0)
    for _n, _c in [(NAT_CONST, "m_defauts"), (NAT_CAPA, "m_capacite"), (NAT_CAPI, "m_stocks")]:
        s[_c] = (_pv[_n].values if _n in _pv.columns else 0.0)
    m_surprod = float(lignes.loc[lignes["type_muda"] == "surproduction", "montant"].sum())
    m_comp = float(lignes.loc[lignes["type_muda"] == "competences", "montant"].sum())
    # Totaux par nature : lus sur les lignes valorisées, jamais recomposés ailleurs
    _nat_tot = lignes.groupby("nature")["montant"].sum()
    _tot = lambda n: float(_nat_tot.get(n, 0.0))

    # ── TRS pondéré ligne (spec 2.2 : agréger les temps, pas les ratios) ────
    d_l = s["temps_fonctionnement_h"].sum() / s["temps_requis_h"].sum()
    p_l = (s["pieces_produites"] * s["cycle_time_sec"]).sum() / 3600.0 / s["temps_fonctionnement_h"].sum()
    q_l = s["pieces_bonnes"].sum() / s["pieces_produites"].sum()
    trs_l = d_l * p_l * q_l

    # ── SMED (potentiel par poste, valorisé dans le simulateur) ─────────────
    s["nb_changements_an"] = vol / s["batch_size"]
    s["smed_h_50"] = 0.5 * s["nb_changements_an"] * s["changeover_min"] / 60.0

    # ── Flux ────────────────────────────────────────────────────────────────
    va_s_piece = float(s["value_added_sec"].sum())
    lead_s_piece = float((s["cycle_time_sec"] * (1 + s["wip_units"])).sum())
    flow_eff = va_s_piece / lead_s_piece if lead_s_piece else 0.0
    lead_h = lead_s_piece / 3600.0
    lead_days = lead_h / HEURES_OUVERTURE_JOUR
    takt_s = HEURES_OUVERTURE_JOUR * 3600.0 / demande

    bi = s["taux_charge"].idxmax()

    # ── Les huit mudas, reconstitués depuis les événements valorisés ────────
    # Chaque ligne porte sa quantité physique, sa nature UNIQUE, la méthode de
    # valorisation retenue (E5/E6 ou repli) et l'indice de confiance.
    F = (lambda a, b: a if _PF else b)
    _g = lignes.groupby(["type_muda", "nature"]).agg(
        qty=("quantite", "sum"), occurrences=("occurrences", "sum"),
        heures=("heures", "sum"), value=("montant", "sum"),
        confiance=("confiance", "min")).reset_index()
    # méthode dominante d'un couple (muda, nature), pondérée par le montant
    _meth = (lignes.groupby(["type_muda", "nature", "methode"])["montant"].sum()
             .reset_index().sort_values("montant", ascending=False)
             .drop_duplicates(subset=["type_muda", "nature"])
             .set_index(["type_muda", "nature"])["methode"])

    _UNI = {"pieces": F("pièces", "pieces"), "heures": F("heures", "hours"), "unites": F("unités", "units")}
    rows = []
    for _, r in _g.iterrows():
        key, nat = r["type_muda"], r["nature"]
        doc = PROD_DOCTRINE.get(key, {})
        uni = _UNI.get(doc.get("unite", "heures"), doc.get("unite", ""))
        if key == "defauts":
            lbl = (f"{s['rebut_pcs'].sum():,.0f} " + F("rebuts + ", "scrapped + ")
                   + f"{s['retouche_pcs'].sum():,.0f} " + F("retouches", "reworked"))
        elif doc.get("unite") == "heures":
            lbl = f"{r['qty']:,.0f} h"
        else:
            lbl = f"{r['qty']:,.0f} {uni}"
        rows.append(dict(key=key, muda=(doc.get("fr") if _PF else doc.get("en")) or key,
                         qty=float(r["qty"]), qty_label=lbl, unite=uni,
                         occurrences=int(r["occurrences"]), heures=float(r["heures"]),
                         value=float(r["value"]), confiance=int(r["confiance"]),
                         methode=str(_meth.get((key, nat), "—")),
                         nature=NATURE_UI[nat]))
    mudas = pd.DataFrame(rows).sort_values("value", ascending=False).reset_index(drop=True)

    # récupérabilité (démo : indices saisis ; gain constaté = campagne suivante, R6)
    _evit = {"defauts": .62, "attente": .70, "transport": .55, "sur_traitement": .40,
             "mouvements": .50, "stocks_encours": .65, "surproduction": .60, "competences": .45}
    _effort = {"defauts": 3.5, "attente": 2.5, "transport": 2.0, "sur_traitement": 3.0,
               "mouvements": 1.5, "stocks_encours": 2.0, "surproduction": 2.5, "competences": 2.0}
    mudas["evitable"] = mudas["key"].map(_evit) * mudas["value"]
    mudas["objectif"] = 0.65 * mudas["evitable"]
    mudas["effort"] = mudas["key"].map(_effort)

    k = dict(
        constate=_tot(NAT_CONST), capacite=_tot(NAT_CAPA), capital=_tot(NAT_CAPI),
        d_l=float(d_l), p_l=float(p_l), q_l=float(q_l), trs=float(trs_l),
        takt_s=float(takt_s), demande=demande,
        prod_reelle=float(lp["prod_reelle"]),
        otif=float(lp["otif"]),
        goulot=str(s.loc[bi, "step_name"]), goulot_charge=float(s.loc[bi, "taux_charge"]),
        flow_eff=float(flow_eff), lead_days=float(lead_days), lead_h=float(lead_h),
        va_s=float(va_s_piece),
        encours_units=float(s["wip_units"].sum()), encours=float(s["wip_value"].sum()),
        rebut_pcs=float(s["rebut_pcs"].sum()), retouche_pcs=float(s["retouche_pcs"].sum()),
        rework_h=float(s["rework_h"].sum()), m_surprod=float(m_surprod), m_comp=float(m_comp),
        surprod_units=float(surprod_units), comp_h=float(comp_h),
    )
    return s, mudas, k


def _prod_demo_frames():
    """Jeu de démonstration -> (relevés par poste, paramètres de ligne)."""
    steps, fams = prod_demo()
    f = fams.iloc[0]
    s = steps.merge(fams, on="product_family", how="left")
    lp = dict(annual_volume=float(f["annual_volume"]), standard_cost=float(f["standard_cost"]),
              material_cost=float(f["material_cost"]),
              demande=float(PROD_CAMPAGNE["demande_client_jour"]),
              prod_reelle=float(PROD_CAMPAGNE["production_reelle_jour"]),
              otif=float(PROD_CAMPAGNE["otif_client"]),
              surprod_units=float(f["annual_volume"]) * PROD_CAMPAGNE["taux_surproduction"],
              comp_h=float(PROD_CAMPAGNE["heures_competences_an"]))
    return s, lp


def _prod_read(sql):
    """Lecture silencieuse (pas de bandeau d'erreur) : renvoie None si les
    tables prod_* n'existent pas encore. La connexion est en autocommit, donc
    une sonde en échec ne bloque pas les requêtes suivantes."""
    try:
        return pd.read_sql(sql, get_connection())
    except Exception:
        return None


def _prod_db_frames():
    """Back end prod_* -> (relevés par poste, paramètres de ligne, campagne, événements).
    R1/R2 : la base ne stocke que des temps, des pièces et des quantités physiques ;
    les taux et les euros sont reconstruits ici. Les événements arrivent QUALIFIÉS
    (ressource bloquée, réaffectation, source, niveau de coût) : c'est ce qui permet
    à l'arbre E1→E6 de trancher au lieu de retomber sur le repli."""
    camp = _prod_read("SELECT * FROM prod_campagnes ORDER BY date_debut DESC LIMIT 1")
    if camp is None or camp.empty:
        return None
    cid = str(camp.iloc[0]["campagne_id"]).replace("'", "''")
    mes = _prod_read("SELECT m.*, p.poste, p.atelier, p.ligne, p.nb_machines_paralleles, "
                     "p.temps_ouverture_h_jour, p.cout_horaire_machine, p.cout_horaire_mo, "
                     "p.operators, p.nb_operateurs "
                     "FROM prod_mesures m JOIN prod_postes p ON p.poste_id = m.poste_id "
                     "WHERE m.campagne_id = '" + cid + "' ORDER BY m.poste_id")
    ev = _prod_read("SELECT * FROM prod_evenements WHERE campagne_id = '" + cid + "'")
    if mes is None or mes.empty or ev is None or ev.empty:
        return None
    # Encours : mesurés POSTE PAR POSTE dans prod_mesures.wip_units (source complète).
    # prod_encours décrit les liaisons inter-opérations pour la cartographie — s'en
    # servir ici raterait l'encours du premier poste, qui n'a pas de liaison amont.
    if "wip_units" in mes.columns and "stocks_encours" not in set(ev["type_muda"]):
        _w = mes[["poste_id", "wip_units"]].copy()
        _w["wip_units"] = pd.to_numeric(_w["wip_units"], errors="coerce").fillna(0.0)
        _w = _w[_w["wip_units"] > 0]
        if not _w.empty:
            ev = pd.concat([ev, pd.DataFrame({
                "campagne_id": cid, "poste_id": _w["poste_id"], "type_muda": "stocks_encours",
                "quantite": _w["wip_units"], "unite": "unites", "occurrences": 1,
                "source": "M", "niveau_cout": "B"})], ignore_index=True)

    _f = lambda v, d=0.0: (float(v) if pd.notna(v) else d)
    ev = ev.assign(quantite=pd.to_numeric(ev["quantite"], errors="coerce").fillna(0.0))
    _has = lambda c: c in ev.columns

    def qty(poste, muda, note=None):
        m = (ev["poste_id"] == poste) & (ev["type_muda"] == muda)
        if note is not None:
            m &= ev["commentaire"].fillna("").str.contains(note, case=False)
        return float(ev.loc[m, "quantite"].sum())

    # ── Relevés par poste : les taux se déduisent des temps mesurés ──────────
    rows = []
    for i, r in mes.reset_index(drop=True).iterrows():
        pid = r["poste_id"]
        prod_i = _f(r["pieces_produites"], 1.0) or 1.0
        fonc = _f(r["temps_fonctionnement_h"], 1.0) or 1.0
        req = _f(r["temps_requis_h"], 1.0) or 1.0
        nom = _f(r["temps_cycle_nominal_s"])
        rows.append({
            "step_order": i + 1, "step_name": r["poste"], "workshop": r["atelier"],
            "ligne": r["ligne"] if pd.notna(r["ligne"]) else "—",
            "poste_id": pid,
            "cycle_time_sec": nom,
            "value_added_sec": _f(r.get("value_added_sec")),
            "changeover_min": _f(r.get("changeover_min")),
            "batch_size": _f(r.get("batch_size"), 1.0) or 1.0,
            "wip_units": _f(r.get("wip_units")),
            "availability_rate": fonc / req,
            "performance_rate": (prod_i * nom / 3600.0) / fonc,
            "scrap_rate": qty(pid, "defauts", "rebut") / prod_i,
            "rework_rate": qty(pid, "defauts", "retouche") / prod_i,
            "transport_sec": qty(pid, "transport") * 3600.0 / prod_i,
            "motion_sec": qty(pid, "mouvements") * 3600.0 / prod_i,
            "operators": _f(r.get("nb_operateurs"), _f(r.get("operators"), 1.0)) or 1.0,
            "machine_hourly_cost": _f(r.get("cout_horaire_machine"), COUT_HORAIRE_MACHINE),
            "labour_hourly_cost": _f(r.get("cout_horaire_mo"), COUT_HORAIRE_MO),
            "nb_machines": _f(r.get("nb_machines_paralleles"), 1.0) or 1.0,
            "ouverture_h_jour": _f(r.get("temps_ouverture_h_jour"), HEURES_OUVERTURE_JOUR),
            "source": (r.get("source") if pd.notna(r.get("source")) else "M"),
            # charge/capacité ERP quand elles existent : sans elles E5 ne peut trancher
            "db_charge_h": (_f(r.get("charge_requise_h")) if pd.notna(r.get("charge_requise_h")) else None),
            "db_capa_h": (_f(r.get("capacite_nette_h")) if pd.notna(r.get("capacite_nette_h")) else None),
        })
    s = pd.DataFrame(rows)

    c0 = camp.iloc[0]
    lp = dict(annual_volume=_f(c0.get("volume_annuel"), float(pd.to_numeric(mes["pieces_bonnes"], errors="coerce").max())),
              standard_cost=_f(c0.get("cout_standard_unitaire")),
              material_cost=_f(c0.get("cout_matiere_unitaire")),
              demande=_f(c0.get("demande_client_jour"), 1.0) or 1.0,
              prod_reelle=_f(c0.get("production_reelle_jour")),
              otif=_f(c0.get("otif_client")),
              surprod_units=float(ev.loc[ev["type_muda"] == "surproduction", "quantite"].sum()),
              comp_h=float(ev.loc[ev["type_muda"] == "competences", "quantite"].sum()))
    if lp["standard_cost"] <= 0:
        return None
    return s, lp, str(c0["campagne_id"]), ev


def _prod_db_events(s, lp, ev):
    """Événements de prod_evenements -> triplets (ev, poste, mesure) pour la
    valorisation. Les champs de qualification absents prennent un défaut prudent :
    l'arbre bascule alors sur le repli et l'indice de confiance tombe à ★."""
    _f = lambda v, d=0.0: (float(v) if pd.notna(v) else d)
    idx = s.set_index("poste_id") if "poste_id" in s.columns else s.set_index("step_name")
    tot_va = s["value_added_sec"].sum() or 1.0
    cost_at = (lp["material_cost"] + (s["value_added_sec"].cumsum() / tot_va)
               * (lp["standard_cost"] - lp["material_cost"]))
    cost_at.index = idx.index
    out = []
    for _, e in ev.iterrows():
        pid = e.get("poste_id")
        muda = str(e["type_muda"])
        known = pd.notna(pid) and pid in idx.index
        if known:
            r = idx.loc[pid]
            poste = dict(cout_horaire_mo=r["labour_hourly_cost"], cout_horaire_machine=r["machine_hourly_cost"],
                         nb_operateurs=r["operators"], nb_machines=r["nb_machines"])
            charge = r["db_charge_h"] if r["db_charge_h"] else (
                lp["demande"] * JOURS_OUVRES_AN * (r["cycle_time_sec"] / max(r["performance_rate"], 1e-9)) / 3600.0)
            capa = r["db_capa_h"] if r["db_capa_h"] else (
                r["ouverture_h_jour"] * JOURS_OUVRES_AN * r["nb_machines"] * r["availability_rate"])
            mesure = dict(charge_requise_h=charge, capacite_nette_h=capa,
                          temps_cycle_effectif_s=r["cycle_time_sec"] / max(r["availability_rate"] * r["performance_rate"], 1e-9))
            # Encours valorisés au coût CUMULÉ à l'étape (une pièce en attente devant
            # l'assemblage vaut plus qu'une pièce devant le sciage), jamais au standard plein.
            cu = float(cost_at.loc[pid])
            wname, pname = r["workshop"], r["step_name"]
        else:
            poste = dict(cout_horaire_mo=COUT_HORAIRE_MO, cout_horaire_machine=COUT_HORAIRE_MACHINE,
                         nb_operateurs=1, nb_machines=1)
            mesure, cu, wname, pname = {}, lp["standard_cost"], None, None

        note = str(e.get("commentaire") or "")
        qte = float(e["quantite"])
        d = dict(type_muda=muda, quantite=qte, unite=str(e.get("unite") or "heures"),
                 occurrences=int(_f(e.get("occurrences"), 1.0)), poste=pname, workshop=wname,
                 cout_unitaire=cu,
                 source=(e.get("source") if pd.notna(e.get("source")) else "E"),
                 niveau_cout=(e.get("niveau_cout") if pd.notna(e.get("niveau_cout")) else "C"))
        if muda == "defauts":
            if "retouche" in note.lower() and known:
                d.update(rebut_pcs=0.0, retouche_h=qte * float(r["value_added_sec"]) / 3600.0)
            else:
                d.update(rebut_pcs=qte, retouche_h=0.0)
        else:
            d.update(duree_arret_h=_f(e.get("duree_arret_h"), qte),
                     ressource_bloquee=(e.get("ressource_bloquee") if pd.notna(e.get("ressource_bloquee"))
                                        else ("les_deux" if muda == "attente" else "machine")),
                     operateur_reaffecte=(bool(e["operateur_reaffecte"]) if pd.notna(e.get("operateur_reaffecte"))
                                          else (muda != "attente")),
                     recuperable_avant_echeance=(bool(e["recuperable_avant_echeance"])
                                                 if pd.notna(e.get("recuperable_avant_echeance")) else False))
        out.append((d, poste, mesure))
    return out


@st.cache_data(ttl=300, show_spinner=False)
def prod_compute():
    """Base si les tables prod_* sont alimentées, sinon jeu de démonstration.
    Même moteur (_prod_core) et même doctrine E1→E6 dans les deux cas."""
    db = _prod_db_frames()
    if db is not None:
        s0, lp0, cid, ev = db
        s, mudas, k = _prod_core(s0, lp0, evts_db=_prod_db_events(s0, lp0, ev))
        k["source"], k["campagne"] = "db", cid
        return s, mudas, k
    s0, lp0 = _prod_demo_frames()
    s, mudas, k = _prod_core(s0, lp0)
    k["source"], k["campagne"] = "demo", PROD_CAMPAGNE["campagne"]
    return s, mudas, k


# ── PLAN D'ACTIONS : persistance en base (dictionnaire §3.7, spec §4.4-5) ───
# Lecture par la connexion lecture seule ; écriture par un rôle DISTINCT limité
# à prod_actions. Sans secrets d'écriture, l'écran reste consultable + export CSV.
PROD_STATUTS_DB = ["a_lancer", "en_cours", "cloturee", "abandonnee"]
PROD_STATUTS_UI = (["À lancer", "En cours", "Clôturée", "Abandonnée"] if _PF
                   else ["To start", "In progress", "Closed", "Dropped"])
_ST_UI2DB = dict(zip(PROD_STATUTS_UI, PROD_STATUTS_DB))
_ST_DB2UI = dict(zip(PROD_STATUTS_DB, PROD_STATUTS_UI))


def _prod_write_conn():
    """Connexion d'écriture (rôle supplystack_actions). None si non configurée."""
    try:
        user = st.secrets.get("supabase_actions_user", "")
        pwd = st.secrets.get("supabase_actions_password", "")
    except Exception:
        user = pwd = ""
    if not user or not pwd:
        return None
    cfg = dict(DB_CONFIG)
    cfg["user"], cfg["password"] = user, pwd
    conn = psycopg2.connect(**cfg)
    conn.autocommit = False          # transaction explicite : tout ou rien
    return conn


def prod_actions_writable():
    try:
        return bool(st.secrets.get("supabase_actions_user", ""))
    except Exception:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def prod_actions_load():
    """Plan d'actions depuis la base. None si la table est absente."""
    return _prod_read("SELECT action_id, libelle, poste_id, type_muda, cause_code, "
                      "potentiel_accessible, objectif_retenu, gain_constate, responsable, "
                      "echeance, statut, date_constat FROM prod_actions ORDER BY action_id")


@st.cache_data(ttl=300, show_spinner=False)
def _prod_poste_map():
    """poste -> poste_id et l'inverse, pour traduire l'affichage en clés."""
    df = _prod_read("SELECT poste_id, poste FROM prod_postes ORDER BY poste_id")
    if df is None or df.empty:
        return {}, {}
    return (dict(zip(df["poste"], df["poste_id"])), dict(zip(df["poste_id"], df["poste"])))


def prod_actions_save(rows):
    """Remplace le plan en base, dans UNE transaction (jamais d'état partiel)."""
    conn = _prod_write_conn()
    if conn is None:
        return False, ("Écriture non configurée : ajoutez supabase_actions_user / "
                       "supabase_actions_password dans les secrets." if _PF else
                       "Write not configured: add supabase_actions_user / "
                       "supabase_actions_password to the secrets.")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM prod_actions")
            for r in rows:
                cur.execute(
                    "INSERT INTO prod_actions (libelle, poste_id, type_muda, cause_code, "
                    "potentiel_accessible, objectif_retenu, gain_constate, responsable, "
                    "echeance, statut, date_constat) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r["libelle"], r["poste_id"], r["type_muda"], r["cause_code"],
                     r["potentiel_accessible"], r["objectif_retenu"], r["gain_constate"],
                     r["responsable"], r["echeance"], r["statut"], r["date_constat"]))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def prod_aggregate(level):
    """TRS pondéré multi-niveaux (spec 2.2) : usine → atelier → ligne → poste.
    Toujours agrégé sur les temps sous-jacents, jamais moyenne de ratios."""
    s, _, _ = prod_compute()
    keymap = {("Usine" if _PF else "Plant"): None,
              ("Atelier" if _PF else "Workshop"): "workshop",
              ("Ligne" if _PF else "Line"): "ligne",
              ("Poste" if _PF else "Station"): "step_name"}
    col = keymap.get(level)
    g = s.assign(_u=(CLIENT_NAME if col is None else s[col]),
                 _prodnom_h=s["pieces_produites"] * s["cycle_time_sec"] / 3600.0)
    t = g.groupby("_u").agg(fonct=("temps_fonctionnement_h", "sum"),
                            requis=("temps_requis_h", "sum"),
                            prodnom=("_prodnom_h", "sum"),
                            bonnes=("pieces_bonnes", "sum"),
                            produites=("pieces_produites", "sum")).reset_index()
    agg = pd.DataFrame({level: t["_u"],
                        "D": t["fonct"] / t["requis"],
                        "P": t["prodnom"] / t["fonct"],
                        "Q": t["bonnes"] / t["produites"]})
    agg["TRS"] = agg["D"] * agg["P"] * agg["Q"]
    return agg.sort_values("TRS").reset_index(drop=True)


# ── Moteur de recommandation (spec 2.3) ──────────────────────────────────────
def composante_dominante(d, p, q):
    """Retourne la composante la plus dégradée et son écart en points."""
    ecarts = {("Disponibilité" if _PF else "Availability"): 1 - d,
              ("Performance" if _PF else "Performance"): 1 - p,
              ("Qualité" if _PF else "Quality"): 1 - q}
    nom = max(ecarts, key=ecarts.get)
    return nom, round(ecarts[nom] * 100, 1)


PISTES = {
    ("Disponibilité" if _PF else "Availability"):
        ("pannes, réglages, changements de série, attente matière, absence opérateur" if _PF
         else "breakdowns, setups, changeovers, material starvation, operator absence"),
    ("Performance" if _PF else "Performance"):
        ("micro-arrêts, cadence réelle sous nominale, usure outil, standard opératoire, alimentation du poste" if _PF
         else "micro-stops, real rate below nominal, tool wear, work standard, station feeding"),
    ("Qualité" if _PF else "Quality"):
        ("rebut, retouche, dérive process, matière fournisseur" if _PF
         else "scrap, rework, process drift, supplier material"),
}


def prod_unavailable(msg):
    """R6 : un écran sans données affiche un message d'indisponibilité sobre."""
    st.markdown('<div style="background:#f8f9fc;border:1px dashed rgba(15,23,42,0.15);'
                'border-radius:12px;padding:22px 18px;text-align:center;font-size:13px;'
                'color:#64748b;margin:6px 0 14px;">' + msg + '</div>', unsafe_allow_html=True)


def prod_natures_note():
    txt = ("Trois natures économiques distinctes, jamais additionnées. Les pertes constatées sont des "
           "décaissements réels. La capacité n'est chiffrée que sur les postes réellement contraints "
           f"(taux de charge ≥ {SEUIL_CONTRAINTE*100:.0f} %) et non rattrapables : ailleurs le travail se termine "
           "quand même, la perte vaut 0 €. Le capital immobilisé est un coût de portage "
           f"({TAUX_POSSESSION_ANNUEL*100:.0f} %/an), pas une perte."
           if _PF else
           "Three distinct economic natures, never summed. Booked losses are real cash out. Capacity is "
           f"valued only on genuinely constrained stations (load ≥ {SEUIL_CONTRAINTE*100:.0f}%) that cannot catch up: "
           "elsewhere the work still gets done, so the loss is €0. Capital tied up is a carrying cost "
           f"({TAUX_POSSESSION_ANNUEL*100:.0f}%/yr), not a loss.")
    st.markdown('<div style="background:#fff7ed;border-left:4px solid #f59e0b;border-radius:8px;'
                'padding:9px 13px;font-size:12px;color:#92400e;margin:2px 0 14px;">⚠️ ' + txt + '</div>',
                unsafe_allow_html=True)


def methode_badge(methode, confiance):
    """Distingue visuellement une valorisation fine (E1→E6) d'un repli (§5.3)."""
    fine = methode in METHODES_FINES
    lib = {"E3_cout_direct": ("Coût direct" if _PF else "Direct cost"),
           "E5_non_contraint": ("Poste non contraint" if _PF else "Station not constrained"),
           "E6_recuperable": ("Rattrapé avant échéance" if _PF else "Caught up before due date"),
           "E6_perte_ferme": ("Perte ferme sur contrainte" if _PF else "Firm loss on constraint"),
           "E2_aucune_ressource": ("Aucune ressource bloquée" if _PF else "No resource blocked"),
           "portage": ("Coût de portage" if _PF else "Carrying cost"),
           "defauts_directs": ("Décaissement direct" if _PF else "Direct cash out"),
           "absorption_globale": ("Repli — absorption globale" if _PF else "Fallback — global absorption"),
           }.get(methode, methode)
    col = "#0f7a4d" if fine else "#a15c07"
    bg = "#e7f7ef" if fine else "#fef3e2"
    return (f'<span style="background:{bg};color:{col};font-size:10.5px;font-weight:600;'
            f'padding:2px 7px;border-radius:5px;white-space:nowrap;">{lib}</span>'
            f' <span style="color:#f59e0b;font-size:11px;">{etoiles(confiance)}</span>')


def _trs_class(v):
    return "kpi-danger" if v < 0.65 else ("kpi-warning" if v < 0.80 else "kpi-success")


def _delta_txt(pct):
    """Variation d'impact : à la baisse = vert (moins de gaspillage)."""
    if pct is None:
        return "", ""
    if abs(pct) < 0.05:
        return "→ 0.0%", "#94a3b8"
    up = pct > 0
    return (("↑" if up else "↓") + f" {abs(pct):.1f}%"), ("#e5484d" if up else "#12b76a")


# ── ASSISTANT IA PRODUCTION ──────────────────────────────────────────────────
# Même moteur que l'assistant logistique (ask_claude), prompt système dédié au
# schéma prod_* et aux règles R1-R4. R6 : indisponible tant que le back end
# production (production_backend_v2.sql) n'est pas chargé.
PROD_DB_SCHEMA = f"""
DATABASE SCHEMA (PostgreSQL / Supabase) — PRODUCTION MODULE (tables prod_*):

prod_campagnes — measurement campaigns (one field survey each)
- campagne_id (PK), date_debut, date_fin, perimetre, auteur, methode_releve
- demande_client_jour, production_reelle_jour, otif_client

prod_postes — workstations
- poste_id (PK), poste, atelier, ligne, nb_machines_paralleles
- temps_ouverture_h_jour, cout_horaire_machine, cout_horaire_mo

prod_mesures — R2: raw TIMES and PIECES per (campagne, poste). No stored ratio.
- temps_requis_h, temps_fonctionnement_h, pieces_produites, pieces_bonnes
- temps_cycle_nominal_s, temps_cycle_effectif_s

prod_evenements — R1: PHYSICAL quantities per muda. No stored euro.
- campagne_id, poste_id (NULL = line-level), type_muda -> prod_doctrine
- quantite, unite, occurrences, cause_code, commentaire

prod_doctrine — the product's valuation doctrine (same for every client)
- type_muda (PK), libelle, unite_primaire, nature ('constate'|'capacite'|'capital')
- formule (valuation rule), regle_anti_doublon

prod_encours — WIP between operations: poste_amont, poste_aval, pieces,
  cout_standard_unitaire, attente_moyenne_h

prod_actions — the action plan: libelle, poste_id, type_muda, cause_code,
  potentiel_accessible, objectif_retenu, gain_constate, responsable, echeance,
  statut ('a_lancer'|'en_cours'|'cloturee'|'abandonnee'), date_constat

PREFER THESE VIEWS (they apply the aggregation rules correctly):
- v_prod_trs_poste — D (disponibilite), P (performance), Q (qualite), trs per poste & campagne
- v_prod_trs_agrege — TIME-WEIGHTED D/P/Q/TRS by niveau ('atelier'|'ligne'|'usine')
- v_prod_charge_poste — demande_client_jour, capacite_nette_jour, taux_charge (bottleneck = max)
- v_prod_impact_nature — physical quantity + occurrences per muda and nature (NO euros, NO combined total)
- v_prod_pareto_causes — quantities by cause_code (may be empty if causes not yet coded)
- v_prod_suivi_campagnes — weighted D/P/Q/TRS per campaign (trend)

VALUATION PARAMETERS (calibrated for this client):
- COUT_HORAIRE_MO = {COUT_HORAIRE_MO} €/h (loaded labour)
- COUT_HORAIRE_MACHINE = {COUT_HORAIRE_MACHINE} €/h default (prod_postes overrides per poste)
- MARGE_COUT_VARIABLE_UNITAIRE = {MARGE_COUT_VARIABLE_UNITAIRE} €/piece (contribution margin)
- SEUIL_CONTRAINTE = {SEUIL_CONTRAINTE} — load rate above which a station is a real constraint
- TAUX_POSSESSION_ANNUEL = {TAUX_POSSESSION_ANNUEL} — 'capital' nature = value × this rate
- TAUX_ABSORPTION_DEMANDE = {TAUX_ABSORPTION_DEMANDE} — FALLBACK ONLY (see E5/E6 below)

VALUATION DOCTRINE — the E1→E6 tree. This REPLACED the global absorption rate as the
main method. Never present absorption as the rule; it is the degraded fallback.
- E1/E2 qualify the event: which resource was actually blocked (ressource_bloquee) and
  whether the operator was reassigned (operateur_reaffecte). 'aucune' => 0 €, a VALID result.
- E3 direct cost: an operator idle and NOT reassigned = hours actually paid => 'constate'.
  Hours that were WORKED but add no value (transport, motion, over-processing) are NOT a
  cash-out: removing them refunds no salary, it frees capacity => capacity path.
- E4 pieces lost = duree_arret_h × 3600 / temps_cycle_effectif_s, divided by
  nb_machines_paralleles when the station has several machines.
- E5 constraint test: taux_charge = charge_requise_h / capacite_nette_h. If it is BELOW
  {SEUIL_CONTRAINTE}, the station is not a constraint: the work still gets done, so the
  capacity is worth 0 €. Saying "0 €" here is a correct, defensible answer.
- E6 recovery: if the loss can be caught up before the due date, capacity = 0 €.
  Otherwise capacity = pieces lost × MARGE_COUT_VARIABLE_UNITAIRE => 'capacite'.
- FALLBACK: if charge_requise_h or capacite_nette_h is missing, E5/E6 cannot decide.
  Then and only then: hours × hourly cost × TAUX_ABSORPTION_DEMANDE, method
  'absorption_globale', confidence forced to ★. Say explicitly that it is a fallback.

CONFIDENCE (source M/S/E × cost level A/B/C):
★★★ = measured or system-extracted AND validated client cost. ★★ = one axis degraded.
★ = anything estimated (E) or parametric (C), including every 'absorption_globale' figure.
A ★ figure must never be presented with the same assurance as a ★★★ one.

NON-NEGOTIABLE RULES (they define the product's credibility):
- R4: NEVER add the three natures ('constate', 'capacite', 'capital') into one total.
- R1: always give the PHYSICAL quantity first (hours, pieces, units), then its valuation
  and the method that produced it.
- One event yields AT MOST ONE line per nature — never count the same hours twice
  (paid hours + OEE loss + lost output would be triple counting).
- 'capacite' euros are foregone potential, not booked savings. 'capital' euros are a
  carrying cost, not a loss.
- Scrap is valued at the cost ACCUMULATED up to the step, never at full standard cost.
"""

if _PF:
    PROD_SYSTEM_PROMPT = f"""Vous êtes l'analyste IA du module PRODUCTION de SupplyStack, plateforme d'intelligence industrielle pour PME/ETI. Vous répondez aux questions sur le TRS, les gaspillages (mudas), le goulot, le flux et le plan d'actions en interrogeant la base du client en direct.

{PROD_DB_SCHEMA}

RÈGLES :
1. Utilisez l'outil query_database (SELECT uniquement). N'inventez jamais de chiffres.
2. Préférez les vues v_prod_* : elles appliquent les pondérations correctes. Ne moyennez JAMAIS des ratios de TRS entre postes — utilisez v_prod_trs_agrege.
3. Quantité physique d'abord, euros ensuite, nature toujours nommée. Jamais de total combinant les trois natures (règle produit non négociable).
4. La capacité se valorise par l'arbre E1→E6 : un poste sous {SEUIL_CONTRAINTE*100:.0f} % de charge n'est pas contraint, sa capacité perdue vaut 0 € et c'est une réponse juste. Le taux d'absorption n'est qu'un REPLI quand charge/capacité manquent — dites-le et marquez le montant ★.
5. Le goulot se lit dans v_prod_charge_poste (taux_charge max), pas au temps de cycle le plus long.
6. Un TRS se commente par sa composante dominante (D, P ou Q) et des pistes d'investigation — jamais une cause présentée comme établie.
7. Reliez vos constats aux actions de prod_actions quand c'est pertinent (potentiel, objectif, statut).
8. Réponses concises (2 à 4 paragraphes) : réponse, contexte, recommandation. Montants formatés (12 400 €). TOUJOURS en français.
9. LIMITE STRICTE : 2 requêtes SQL maximum par réponse. Privilégiez UNE requête avec JOINs.
10. Si la donnée manque (causes non codifiées, cycles unitaires absents), dites précisément quel relevé terrain la fournirait.
"""
else:
    PROD_SYSTEM_PROMPT = f"""You are the AI analyst of SupplyStack's PRODUCTION module for industrial SMEs. You answer questions about OEE, wastes (mudas), the bottleneck, flow and the action plan by querying the client's live database.

{PROD_DB_SCHEMA}

RULES:
1. Use the query_database tool (SELECT only). Never invent figures.
2. Prefer the v_prod_* views: they apply correct weighting. NEVER average OEE ratios across stations — use v_prod_trs_agrege.
3. Physical quantity first, euros second, nature always named. Never a total combining the three natures (non-negotiable product rule).
4. Capacity is valued through the E1→E6 tree: a station below {SEUIL_CONTRAINTE*100:.0f}% load is not a constraint, its lost capacity is worth €0, and that is a correct answer. The absorption rate is only a FALLBACK when load/capacity are missing — say so and mark the figure ★.
5. The bottleneck is read from v_prod_charge_poste (max taux_charge), not the longest cycle time.
6. Comment OEE through its dominant component (D, P or Q) with investigation leads — never a cause stated as established.
7. Tie findings to prod_actions when relevant (potential, target, status).
8. Concise answers (2-4 paragraphs): answer, context, recommendation. Format amounts clearly.
9. STRICT LIMIT: 2 SQL queries max per answer. Prefer ONE query with JOINs.
10. If data is missing (causes not coded, unit cycles absent), say precisely which field survey would provide it.
"""


@st.cache_data(ttl=300, show_spinner=False)
def _prod_backend_ready():
    """R6 probe: True once production_backend_v2.sql is loaded with data."""
    try:
        df = pd.read_sql("SELECT 1 FROM prod_mesures LIMIT 1", get_connection())
        return not df.empty
    except Exception:
        return False


LOG_PAGES = [
    T["tab_exec"], T["tab_stock"], T["tab_supplier"], T["tab_reorder"],
    T["tab_ai"], T["tab_health"], T["tab_diag"], T["tab_whatif"],
]
_MODE_LOG = "📦 " + ("Logistique & stock" if CLIENT_LANG == "fr" else "Logistics & stock")
_MODE_PROD = "🏭 " + ("Production" if CLIENT_LANG == "fr" else "Production")
_ss_mode = st.radio("Volet", [_MODE_LOG, _MODE_PROD], key="ss_mode",
                    horizontal=True, label_visibility="collapsed")
PAGES = LOG_PAGES if _ss_mode == _MODE_LOG else PROD_PAGES
_navkey = "nav_page" if _ss_mode == _MODE_LOG else "nav_page_prod"
if _navkey not in st.session_state or st.session_state[_navkey] not in PAGES:
    st.session_state[_navkey] = PAGES[0]

st.markdown("""
<style>
    /* Radio navigation styled as the Aurora tab bar */
    div[data-testid="stRadio"] > label { display: none; }
    div[data-testid="stRadio"] > div {
        flex-direction: row; gap: 26px; flex-wrap: wrap;
        border-bottom: 1px solid rgba(15,23,42,0.08);
        padding: 0 0 0 2px; margin-bottom: 18px;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"] {
        padding: 11px 0 12px; margin: 0; cursor: pointer;
        border-bottom: 2.5px solid transparent; gap: 0;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child { display: none; }
    div[data-testid="stRadio"] label[data-baseweb="radio"] div[data-testid="stMarkdownContainer"] p {
        font-size: 13.5px !important; font-weight: 600 !important;
        color: #64748b !important; margin: 0 !important;
        transition: color 0.12s ease;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:hover
        div[data-testid="stMarkdownContainer"] p { color: #0f172a !important; }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
        border-bottom-color: #6355ff;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked)
        div[data-testid="stMarkdownContainer"] p { color: #6355ff !important; }
</style>
""", unsafe_allow_html=True)

_page = st.radio("Navigation", PAGES, key=_navkey,
                 horizontal=True, label_visibility="collapsed")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: EXECUTIVE DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[0]:
    st.markdown(f"""
    <div style="display:flex; align-items:flex-end; justify-content:space-between; margin:2px 0 18px;">
      <div>
        <h2 style="margin:0; font-size:22px; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">{T['exec_title']}</h2>
        <p style="margin:5px 0 0; font-size:13px; font-weight:500; color:#64748b;">{T['exec_sub']}</p>
      </div>
      <div style="display:flex; gap:16px; align-items:center;">
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#12b76a;"></span>{T['legend_healthy']}</span>
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#f79009;"></span>{T['legend_watch']}</span>
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#e5484d;"></span>{T['legend_risk']}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    kpi_data = run_query("""
        SELECT * FROM daily_kpis_industrial
        ORDER BY kpi_date DESC LIMIT 1
    """)

    hist = get_kpi_history()
    deltas = kpi_deltas(hist)

    def _series(col):
        try:
            if hist is not None and not hist.empty and col in hist.columns:
                return hist[col].tolist()[-12:]
        except Exception:
            pass
        return []

    def _card(label, col, value, klass, info=""):
        d = deltas.get(col, ("", ""))
        return kpi_card(
            label, value, klass,
            delta=d[0], delta_color=d[1],
            spark=sparkline_svg(_series(col), STATUS[klass]["spark"]),
            info=info,
        )

    if not kpi_data.empty:
        row = kpi_data.iloc[0]
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            st.markdown(_card(T["kpi_dead"], "dead_stock_value",
                              format_currency(row["dead_stock_value"]), "kpi-danger",
                              info=T["help_dead"]), unsafe_allow_html=True)
        with c2:
            st.markdown(_card(T["kpi_excess"], "excess_stock_value",
                              format_currency(row["excess_stock_value"]), "kpi-warning",
                              info=T["help_excess"]), unsafe_allow_html=True)
        with c3:
            st.markdown(_card(T["kpi_total"], "total_stock_value",
                              format_currency(row["total_stock_value"]), "kpi-info",
                              info=T["help_total"]), unsafe_allow_html=True)
        with c4:
            st.markdown(_card(T["kpi_holding"], "annual_holding_cost",
                              format_currency(row["annual_holding_cost"]), "kpi-warning",
                              info=T["help_holding"]), unsafe_allow_html=True)
        with c5:
            turn = row["stock_turnover_ratio"]
            tclass = "kpi-danger" if (turn is not None and float(turn) < 2) else "kpi-success"
            st.markdown(_card(T["kpi_turnover"], "stock_turnover_ratio",
                              format_number(turn, 2) + "x", tclass,
                              info=T["help_turnover"]), unsafe_allow_html=True)
        with c6:
            st.markdown(_card(T["kpi_recover"], "recoverable_cash_est",
                              format_currency(row["recoverable_cash_est"]), "kpi-success",
                              info=T["help_recover"]), unsafe_allow_html=True)

        st.write("")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(_card(T["kpi_bfr"], "working_capital_tied",
                              format_currency(row["working_capital_tied"]), "kpi-warning",
                              info=T["help_bfr"]), unsafe_allow_html=True)
        with c2:
            otd = row["supplier_otd_rate"]
            oclass = "kpi-danger" if (otd is not None and float(otd) < 70) else (
                "kpi-warning" if (otd is not None and float(otd) < 85) else "kpi-success")
            st.markdown(_card(T["kpi_otd"], "supplier_otd_rate", format_pct(otd), oclass,
                              info=T["help_otd"]), unsafe_allow_html=True)
        with c3:
            cov = row["avg_coverage_days"]
            cclass = "kpi-danger" if (cov is not None and float(cov) > 180) else "kpi-info"
            st.markdown(_card(T["kpi_coverage"], "avg_coverage_days",
                              format_number(cov, 0) + " j", cclass,
                              info=T["help_coverage"]), unsafe_allow_html=True)
        with c4:
            st.markdown(kpi_card(T["kpi_stockout"],
                                 format_number(row["stockout_risk_ref_count"]), "kpi-danger",
                                 info=T["help_stockout"]), unsafe_allow_html=True)
    else:
        alert_box("info", T["run_pipeline"])

    st.write("")

    # ── main 2:1 layout ───────────────────────────────────────────────────────
    main_left, main_right = st.columns([2, 1], gap="medium")

    with main_left:
        st.subheader(T["chart_dead_family"])
        dead_by_family = run_query("""
            SELECT article_family, SUM(trapped_value) AS dead_value
            FROM inventory
            WHERE is_dead_stock = true AND trapped_value > 0
            GROUP BY article_family
            ORDER BY dead_value DESC
            LIMIT 8
        """)
        if not dead_by_family.empty:
            fig = px.bar(
                dead_by_family, y="article_family", x="dead_value", orientation="h",
                color="dead_value", color_continuous_scale=["#ffc2b8", "#ff8a8b", "#ff5470"],
                labels={"dead_value": f"{T['kpi_dead']} ({CURRENCY})", "article_family": ""},
            )
            fig = style_fig(fig, height=320)
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=10, r=12, t=10, b=34),
                              yaxis=dict(categoryorder="total ascending", gridcolor="rgba(0,0,0,0)",
                                         showticklabels=True, automargin=True))
            try:
                fig.update_traces(marker_cornerradius=6)
            except Exception:
                pass
            fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x:,.0f} " + CURRENCY + "<extra></extra>")
            st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        else:
            alert_box("success", "✅ " + ("Aucune famille en stock dormant." if CLIENT_LANG == "fr"
                                          else "No family with dead stock."))

        sub_l, sub_r = st.columns(2, gap="medium")

        with sub_l:
            st.subheader(T["chart_type_mix"])
            by_type = run_query("""
                SELECT article_type, SUM(current_stock * unit_cost) AS val
                FROM inventory
                GROUP BY article_type
                ORDER BY val DESC
            """)
            if not by_type.empty:
                by_type["label"] = by_type["article_type"].map(lambda x: TN.get(x, x))
                total_val = by_type["val"].sum()
                fig = px.pie(
                    by_type, values="val", names="label", hole=0.62,
                    color_discrete_sequence=["#6355ff", "#8b7cff", "#a78bfa", "#c4b5fd",
                                             "#ddd6fe", "#ede9fe", "#f5f3ff", "#e0e7ff"],
                )
                fig.update_traces(
                    textinfo="percent", textfont=dict(family="Plus Jakarta Sans", size=11, color="#fff"),
                    marker=dict(line=dict(color="#ffffff", width=2)),
                    hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + CURRENCY + "<extra></extra>",
                    # keep the donut in the top ~66% so the legend has its own band below
                    domain=dict(x=[0.0, 1.0], y=[0.34, 1.0]),
                )
                fig = style_fig(fig, height=350, legend=True)
                fig.update_layout(
                    margin=dict(l=0, r=0, t=6, b=6),
                    legend=dict(orientation="h", yanchor="top", y=0.24,
                                xanchor="center", x=0.5,
                                font=dict(size=11, color="#334155")),
                )
                fig.add_annotation(
                    text=f"<b>{format_currency(total_val)}</b><br><span style='font-size:10px;color:#94a3b8'>{T['kpi_total'].lower()}</span>",
                    x=0.5, y=0.67, showarrow=False,  # centre of the raised donut
                    font=dict(family="Plus Jakarta Sans", size=17, color="#0f172a"),
                )
                st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
            else:
                alert_box("info", T["no_data"])

        with sub_r:
            st.subheader(T["chart_trend"])
            if hist is not None and not hist.empty and "total_stock_value" in hist.columns:
                tv = hist.dropna(subset=["total_stock_value"])
                if len(tv) >= 2:
                    ymax = tv["total_stock_value"].astype(float).max()
                    # Anchor the axis at 0 so a small (~few %) swing on a large stock
                    # value reads as small, not dramatic. Headroom above the peak.
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=tv["kpi_date"], y=tv["total_stock_value"],
                        mode="lines+markers", line=dict(color="#6355ff", width=2.5),
                        marker=dict(size=6, color="#6355ff"),
                        fill="tozeroy", fillcolor="rgba(99,85,255,0.12)",
                        hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
                    ))
                    fig = style_fig(fig, height=280)
                    fig.update_layout(yaxis=dict(range=[0, ymax * 1.08], gridcolor="#eef0f6"))
                    st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
                else:
                    alert_box("info", T["not_enough_hist"])
            else:
                alert_box("info", T["run_pipeline"])

    with main_right:
        # ── AI Insight card (data-driven) ──────────────────────────────────
        insight = ("Le stock dormant concentre votre risque en fonds de roulement."
                   if CLIENT_LANG == "fr" else
                   "Dead stock concentrates your working capital risk.")
        try:
            if not kpi_data.empty:
                r = kpi_data.iloc[0]
                pdr_saved = run_query("""
                    SELECT COUNT(*) AS c FROM inventory
                    WHERE article_type = 'PDR' AND days_since_movement > 365 AND is_dead_stock = false
                """)
                n_saved = int(pdr_saved.iloc[0]["c"]) if not pdr_saved.empty else 0
                if CLIENT_LANG == "fr":
                    insight = (f"<b>{format_currency(r['recoverable_cash_est'])}</b> de trésorerie mobilisable "
                               f"sur <b>{format_currency(r['working_capital_tied'])}</b> immobilisés. "
                               f"Le seuil de dormance différencié par type d'article évite "
                               f"<b>{n_saved} faux positifs</b> sur vos pièces de rechange.")
                else:
                    insight = (f"<b>{format_currency(r['recoverable_cash_est'])}</b> of cash is mobilisable "
                               f"out of <b>{format_currency(r['working_capital_tied'])}</b> tied up. "
                               f"Type-specific dormancy thresholds avoid "
                               f"<b>{n_saved} false positives</b> on your spare parts.")
        except Exception:
            pass

        st.markdown(f"""
        <div style="background:linear-gradient(140deg,#6355ff,#8b5cf6); border-radius:18px; padding:20px; color:#fff;
             box-shadow:0 18px 38px -18px rgba(99,85,255,0.7); margin-bottom:16px;">
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:13px;">
            <span style="width:24px;height:24px;border-radius:8px;background:rgba(255,255,255,0.2);
                  display:flex;align-items:center;justify-content:center;font-size:13px;">✦</span>
            <span style="font-size:10px; font-weight:700; letter-spacing:0.12em;">{T['rail_ai']}</span>
          </div>
          <p style="margin:0; font-size:13.5px; font-weight:500; line-height:1.55; color:rgba(255,255,255,0.94);">{insight}</p>
        </div>
        """, unsafe_allow_html=True)

        hint = ("💬 Ouvrez l'onglet <b style=\"color:#6355ff;\">Assistant IA</b> pour un plan de déstockage complet "
                "ou une analyse de dérive de vos paramètres ERP."
                if CLIENT_LANG == "fr" else
                "💬 Open the <b style=\"color:#6355ff;\">AI Assistant</b> tab for a full destocking plan "
                "or an ERP parameter drift analysis.")
        st.markdown(f'<div style="font-size:12px;color:#94a3b8;margin-top:2px;line-height:1.5;">{hint}</div>',
                    unsafe_allow_html=True)
        st.write("")

        # ── Recent Alerts (live data) ──────────────────────────────────────
        alerts_html = ['<div class="aurora-panel" style="margin-bottom:16px;">',
                       f'<div class="rail-title"><h4>{T["rail_alerts"]}</h4>'
                       f'<span style="color:#94a3b8;font-weight:600;">{T["live"]}</span></div>']
        tint = {"#e5484d": "#fdecec", "#f79009": "#fef3e2", "#3b82f6": "#eaf1fe"}
        rows = []
        try:
            top_dead = run_query("""
                SELECT product_name, article_code, trapped_value
                FROM inventory WHERE is_dead_stock = true
                ORDER BY trapped_value DESC LIMIT 1
            """)
            if not top_dead.empty:
                r0 = top_dead.iloc[0]
                nm = str(r0["product_name"])[:34]
                rows.append((f"{nm} — {format_currency(r0['trapped_value'])} " +
                             ("immobilisés" if CLIENT_LANG == "fr" else "tied up"),
                             T["kpi_dead"], "#e5484d", T["live"]))
        except Exception:
            pass
        try:
            crit_sup = run_query("""
                SELECT supplier_name, otd_when_measurable
                FROM v_supplier_scorecard_robust
                WHERE supplier_category = 'critical'
                ORDER BY risk_score DESC LIMIT 1
            """)
            if not crit_sup.empty:
                s0 = crit_sup.iloc[0]
                lbl = ("OTD à %.0f%%" if CLIENT_LANG == "fr" else "OTD at %.0f%%") % float(s0["otd_when_measurable"] or 0)
                rows.append((f"{s0['supplier_name']} — {lbl}",
                             T["col_supplier"], "#e5484d", T["live"]))
        except Exception:
            pass
        try:
            below = run_query("SELECT COUNT(*) AS c FROM inventory WHERE is_stockout_risk = true")
            if not below.empty and int(below.iloc[0]["c"]) > 0:
                txt = (f"{int(below.iloc[0]['c'])} références sous le seuil d'alerte"
                       if CLIENT_LANG == "fr" else
                       f"{int(below.iloc[0]['c'])} references below alert level")
                rows.append((txt, T["kpi_stockout"], "#f79009", T["live"]))
        except Exception:
            pass
        try:
            drift = run_query("""
                SELECT COUNT(*) AS c FROM inventory
                WHERE actual_lead_time_days IS NOT NULL AND erp_lead_time_days IS NOT NULL
                  AND ABS(actual_lead_time_days - erp_lead_time_days) > 7
            """)
            if not drift.empty and int(drift.iloc[0]["c"]) > 0:
                txt = (f"{int(drift.iloc[0]['c'])} références : délai ERP décalé de plus de 7 jours"
                       if CLIENT_LANG == "fr" else
                       f"{int(drift.iloc[0]['c'])} references: ERP lead time off by more than 7 days")
                rows.append((txt, "ERP", "#3b82f6", T["live"]))
        except Exception:
            pass

        for text, tag, sev, when in rows:
            alerts_html.append(f"""
            <div class="alert-row">
              <span class="alert-bar" style="background:{sev};"></span>
              <div class="alert-body">
                <span class="alert-text">{_esc(text)}</span>
                <div class="alert-meta">
                  <span class="alert-tag" style="color:{sev};background:{tint.get(sev,'#f1f2f8')};">{_esc(tag)}</span>
                  <span class="alert-time">{when}</span>
                </div>
              </div>
            </div>""")
        alerts_html.append("</div>")
        st.markdown("".join(alerts_html), unsafe_allow_html=True)

        # ── Reorder Recommendations (mini) ─────────────────────────────────
        reo_html = ['<div class="aurora-panel">',
                    f'<div class="rail-title"><h4>{T["rail_reorder"]}</h4>'
                    f'<span style="color:#94a3b8;font-weight:600;">top 4</span></div>']
        pbg = {"#e5484d": "#fdecec", "#f79009": "#fef3e2", "#12b76a": "#e7f7ef"}
        try:
            reo = run_query("""
                SELECT product_name, article_code, warehouse,
                    GREATEST(COALESCE(moq, 1),
                        ROUND(GREATEST(0, COALESCE(calculated_reorder_point, 0) - current_stock))
                    ) AS qty,
                    ROUND(COALESCE(coverage_days, 0)) AS cov
                FROM inventory
                WHERE is_stockout_risk = true AND avg_daily_consumption > 0
                ORDER BY coverage_days ASC NULLS LAST
                LIMIT 4
            """)
            if not reo.empty:
                for _, rr in reo.iterrows():
                    cov = float(rr["cov"] or 0)
                    if cov < 14:
                        pri, pc = ("Haute" if CLIENT_LANG == "fr" else "High"), "#e5484d"
                    elif cov < 30:
                        pri, pc = ("Moy" if CLIENT_LANG == "fr" else "Med"), "#f79009"
                    else:
                        pri, pc = ("Basse" if CLIENT_LANG == "fr" else "Low"), "#12b76a"
                    name = str(rr["product_name"])
                    if len(name) > 26:
                        name = name[:26] + "…"
                    unit_lbl = "unités" if CLIENT_LANG == "fr" else "units"
                    day_lbl = "j restants" if CLIENT_LANG == "fr" else "d left"
                    reo_html.append(f"""
                    <div class="reo-row">
                      <div style="flex:1; min-width:0;">
                        <div class="reo-name">{_esc(name)}</div>
                        <div class="reo-sub">{_esc(rr['warehouse'])} · {cov:.0f}{day_lbl}</div>
                      </div>
                      <div style="text-align:right;">
                        <div class="reo-qty">{float(rr['qty'] or 0):,.0f} <span style="font-weight:500;color:#a5aec4;">{unit_lbl}</span></div>
                        <span class="reo-pri" style="color:{pc};background:{pbg[pc]};">{pri}</span>
                      </div>
                    </div>""")
            else:
                msg = ("Rien sous le seuil d'alerte." if CLIENT_LANG == "fr" else "Nothing below alert level.")
                reo_html.append(f'<p style="padding:16px 0 4px; font-size:12.5px; color:#94a3b8;">{msg}</p>')
        except Exception:
            reo_html.append('<p style="padding:16px 0 4px; font-size:12.5px; color:#94a3b8;">—</p>')
        reo_html.append("</div>")
        st.markdown("".join(reo_html), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: INVENTORY DETAIL
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[1]:
    inv_kpis = run_query("""
        SELECT
            COUNT(*) FILTER (WHERE is_dead_stock) AS dead_count,
            COUNT(*) FILTER (WHERE is_excess) AS excess_count,
            COUNT(*) FILTER (WHERE is_stockout_risk) AS stockout_count,
            COUNT(*) AS total_refs
        FROM inventory
    """)
    if not inv_kpis.empty:
        r = inv_kpis.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card(T["dead_refs"], format_number(r["dead_count"]), "kpi-danger", info=("Nombre de références classées dormantes (sans mouvement au-delà du seuil de leur type)." if CLIENT_LANG == "fr" else "Number of references flagged dead (no movement beyond their type's threshold).")), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card(T["excess_refs"], format_number(r["excess_count"]), "kpi-warning", info=("Nombre de références en surstock (couverture au-delà de la cible du type)." if CLIENT_LANG == "fr" else "Number of overstocked references (coverage above their type's target).")), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card(T["kpi_stockout"], format_number(r["stockout_count"]), "kpi-danger", info=("Nombre de références dont la couverture passe sous le seuil d'alerte." if CLIENT_LANG == "fr" else "Number of references whose coverage falls below the alert threshold.")), unsafe_allow_html=True)
        with c4:
            abc_data = run_query("SELECT abc_class, COUNT(*) as cnt FROM inventory WHERE abc_class IS NOT NULL GROUP BY abc_class ORDER BY abc_class")
            abc_str = " | ".join([f"{row['abc_class']}: {row['cnt']}" for _, row in abc_data.iterrows()]) if not abc_data.empty else "N/A"
            st.markdown(kpi_card(T["abc_split"], abc_str, "kpi-info", small=True, info=("Répartition des références par classe ABC, sur la valeur de consommation annuelle (A ≈ 80 %)." if CLIENT_LANG == "fr" else "Reference split by ABC class, on annual consumption value (A ≈ 80%).")), unsafe_allow_html=True)

    st.write("")

    # ── ABC × XYZ matrix ─────────────────────────────────────────────────────
    st.subheader(T["chart_abcxyz"])
    matrix = run_query("""
        SELECT
            COALESCE(abc_class, 'N/A') AS abc,
            COALESCE(xyz_class, 'N/A') AS xyz,
            COUNT(*) AS refs,
            ROUND(SUM(current_stock * unit_cost)::numeric, 0) AS val
        FROM inventory
        GROUP BY abc_class, xyz_class
    """)
    if not matrix.empty:
        mx_l, mx_r = st.columns([3, 2], gap="medium")
        with mx_l:
            pivot = matrix.pivot(index="abc", columns="xyz", values="val").fillna(0)
            fig = px.imshow(
                pivot, text_auto=".2s", aspect="auto",
                labels=dict(x="XYZ", y="ABC", color=T["col_value"]),
                color_continuous_scale=["#f5f3ff", "#c4b5fd", "#8b7cff", "#6355ff"],
            )
            fig = style_fig(fig, height=330)
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=10, r=10, t=10, b=20))
            fig.update_traces(hovertemplate="ABC %{y} · XYZ %{x}<br>%{z:,.0f} " + CURRENCY + "<extra></extra>")
            st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        with mx_r:
            note = ("Les articles <b>AZ</b> — forte valeur, demande erratique — sont les plus difficiles à piloter. "
                    "C'est là que se concentrent à la fois le surstock et les ruptures."
                    if CLIENT_LANG == "fr" else
                    "<b>AZ</b> items — high value, erratic demand — are the hardest to plan. "
                    "That's where both overstock and stockouts concentrate.")
            st.markdown(f'<div class="aurora-panel" style="font-size:12.5px;color:#475569;line-height:1.6;">{note}</div>',
                        unsafe_allow_html=True)
            mtab = matrix.copy()
            mtab.columns = ["ABC", "XYZ", T["refs"], T["col_value"]]
            mtab = mtab.sort_values(T["col_value"], ascending=False).head(9)
            render_table(mtab, height=250, formats={
                T["refs"]: "{:,.0f}",
                T["col_value"]: lambda v: format_currency(v),
            })

    st.write("")

    # ── Type breakdown table ─────────────────────────────────────────────────
    st.subheader(T["chart_type_mix"])
    type_detail = run_query("""
        SELECT
            i.article_type,
            at.dead_stock_days,
            COUNT(*) AS refs,
            COUNT(*) FILTER (WHERE i.is_dead_stock) AS dead,
            COUNT(*) FILTER (WHERE i.is_excess) AS excess,
            COUNT(*) FILTER (WHERE i.is_stockout_risk) AS stockout,
            ROUND(SUM(i.current_stock * i.unit_cost)::numeric, 0) AS val,
            ROUND(SUM(i.trapped_value)::numeric, 0) AS trapped,
            ROUND(SUM(i.excess_value)::numeric, 0) AS excess_val
        FROM inventory i
        LEFT JOIN article_types at ON at.code = i.article_type
        GROUP BY i.article_type, at.dead_stock_days
        ORDER BY val DESC
    """)
    if not type_detail.empty:
        td = type_detail.copy()
        td["article_type"] = td["article_type"].map(lambda x: f"{TN.get(x, x)} ({x})")
        seuil = "Seuil dormance (j)" if CLIENT_LANG == "fr" else "Dormancy threshold (d)"
        td.columns = [T["col_type"], seuil, T["refs"], T["dead_refs"], T["excess_refs"],
                      T["kpi_stockout"], T["col_value"], T["col_trapped"], T["col_excess"]]
        sortable_table(td, index=False, height=380, wrap=[T["col_type"]], formats={
            seuil: "{:,.0f}", T["refs"]: "{:,.0f}", T["dead_refs"]: "{:,.0f}",
            T["excess_refs"]: "{:,.0f}", T["kpi_stockout"]: "{:,.0f}",
            T["col_value"]: lambda v: format_currency(v),
            T["col_trapped"]: lambda v: format_currency(v),
            T["col_excess"]: lambda v: format_currency(v),
        })

    st.write("")

    detail_left, detail_right = st.columns(2, gap="medium")

    with detail_left:
        st.subheader(T["top_dead"])
        top_dead = run_query("""
            SELECT article_code, product_name, article_type,
                   current_stock, unit_cost, trapped_value, days_since_movement
            FROM inventory
            WHERE is_dead_stock = true
            ORDER BY trapped_value DESC
            LIMIT 20
        """)
        if not top_dead.empty:
            td2 = top_dead.copy()
            td2["article_type"] = td2["article_type"].map(lambda x: TN.get(x, x))
            td2.columns = [T["col_code"], T["col_product"], T["col_type"], T["col_stock"],
                           T["col_cost"], T["col_trapped"], T["col_days_nomvt"]]
            sortable_table(td2, index=True, height=520, wrap=[T["col_product"]], formats={
                T["col_stock"]: "{:,.0f}",
                T["col_cost"]: lambda v: f"{float(v):,.2f} {CURRENCY}",
                T["col_trapped"]: lambda v: format_currency(v),
                T["col_days_nomvt"]: "{:,.0f}",
            })
        else:
            alert_box("success", "✅ " + ("Aucune référence dormante." if CLIENT_LANG == "fr"
                                          else "No dead references."))

    with detail_right:
        st.subheader(T["coverage_dist"])
        scatter_data = run_query("""
            SELECT product_name, article_type, coverage_days,
                   current_stock * unit_cost AS val,
                   is_dead_stock, is_excess
            FROM inventory
            WHERE coverage_days IS NOT NULL AND coverage_days < 730
              AND current_stock * unit_cost > 0
        """)
        if not scatter_data.empty:
            def _status(r):
                if r["is_dead_stock"]:
                    return T["kpi_dead"]
                if r["is_excess"]:
                    return T["kpi_excess"]
                return T["legend_healthy"]
            scatter_data["status"] = scatter_data.apply(_status, axis=1)
            fig = px.scatter(
                scatter_data, x="coverage_days", y="val", color="status",
                color_discrete_map={
                    T["kpi_dead"]: "#e5484d",
                    T["kpi_excess"]: "#f79009",
                    T["legend_healthy"]: "#12b76a",
                },
                hover_data=["product_name", "article_type"],
                labels={"coverage_days": T["col_coverage"], "val": f"{T['col_value']} ({CURRENCY})",
                        "status": ""},
                log_y=True,
            )
            fig = style_fig(fig, height=500, legend=True)
            st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        else:
            alert_box("info", T["no_data"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: SUPPLIERS
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[2]:
    # ── Period selector — scoped to this tab, where it actually changes the data ──
    _hdr_l, _hdr_r = st.columns([3, 1])
    with _hdr_l:
        _lbl = ("Période d'analyse" if CLIENT_LANG == "fr" else "Analysis period")
        st.markdown(
            f'<div style="font-size:13px;font-weight:700;color:#0f172a;padding-top:6px;">{_lbl}</div>',
            unsafe_allow_html=True)
    with _hdr_r:
        _choice = st.selectbox("Period", list(PRESETS.keys()),
                               index=list(PRESETS).index(ALL_LABEL),
                               key="sup_period", label_visibility="collapsed")

    if _choice == CUSTOM_LABEL:
        _r = st.date_input("Custom range", value=(DATA_MIN, DATA_MAX),
                           min_value=DATA_MIN, max_value=DATA_MAX,
                           key="sup_custom", label_visibility="collapsed")
        if isinstance(_r, (list, tuple)) and len(_r) == 2:
            START_DATE, END_DATE = _r
        else:
            START_DATE, END_DATE = DATA_MIN, DATA_MAX
    elif _choice == ALL_LABEL:
        START_DATE, END_DATE = DATA_MIN, DATA_MAX
    else:
        END_DATE = DATA_MAX
        START_DATE = max(DATA_MIN, DATA_MAX - timedelta(days=PRESETS[_choice]))

    if _choice == ALL_LABEL:
        PO_AND = ""
    else:
        PO_AND = ("  AND order_date >= '%s' AND order_date < '%s'"
                  % (START_DATE.isoformat(), (END_DATE + timedelta(days=1)).isoformat()))

    st.markdown(
        f'<div style="font-size:12px;color:#94a3b8;margin:2px 0 14px;">'
        f'📅&nbsp; {T["date_note"]} <b style="color:#475569;">{START_DATE:%d/%m/%Y} → {END_DATE:%d/%m/%Y}</b></div>',
        unsafe_allow_html=True)

    sup_kpis = run_query(f"""
        SELECT
            COALESCE(ROUND(100.0 * SUM(CASE WHEN received_date <= promised_date THEN 1 ELSE 0 END)
                     / NULLIF(COUNT(promised_date), 0), 1), 0) AS otd_rate,
            COALESCE(ROUND(AVG(received_date - order_date)::numeric, 1), 0) AS avg_lt,
            COALESCE(ROUND(STDDEV(received_date - order_date)::numeric, 1), 0) AS lt_std,
            COUNT(DISTINCT supplier_name) AS n_suppliers,
            COUNT(*) AS n_lines
        FROM purchase_orders
        WHERE received_date IS NOT NULL AND order_date IS NOT NULL
{PO_AND}
    """)

    # Scorecard recomputed live so it responds to the period selector.
    # Same logic as v_supplier_scorecard_robust, with the date filter applied.
    scorecard = run_query(f"""
        WITH base AS (
            SELECT
                supplier_name,
                COUNT(*) AS commandes_total,
                AVG(received_date - order_date)    AS lt_moyen_raw,
                STDDEV(received_date - order_date) AS lt_stddev_raw,
                COUNT(promised_date)               AS n_promised,
                SUM(CASE WHEN received_date <= promised_date THEN 1 ELSE 0 END) AS n_ontime,
                SUM(CASE WHEN quantity_received < quantity_ordered THEN 1 ELSE 0 END) AS n_partial
            FROM purchase_orders
            WHERE received_date IS NOT NULL AND order_date IS NOT NULL
{PO_AND}
            GROUP BY supplier_name
            HAVING COUNT(*) >= 5
        ),
        calc AS (
            SELECT
                supplier_name,
                commandes_total,
                ROUND(lt_moyen_raw::numeric, 1)    AS lt_moyen,
                ROUND(COALESCE(lt_stddev_raw, 0)::numeric, 1) AS lt_stddev,
                ROUND((COALESCE(lt_stddev_raw, 0) / NULLIF(lt_moyen_raw, 0))::numeric, 2) AS cv_lead_time,
                ROUND((100.0 * n_promised / NULLIF(commandes_total, 0))::numeric, 1) AS pct_avec_promised,
                ROUND((100.0 * n_ontime / NULLIF(n_promised, 0))::numeric, 1) AS otd_when_measurable,
                ROUND((100.0 * n_partial / NULLIF(commandes_total, 0))::numeric, 1) AS pct_livraison_partielle,
                COALESCE(lt_stddev_raw / NULLIF(lt_moyen_raw, 0), 0) AS cv_raw,
                COALESCE(100.0 * n_ontime / NULLIF(n_promised, 0), 50) AS otd_raw,
                n_promised
            FROM base
        )
        SELECT
            supplier_name,
            commandes_total,
            lt_moyen,
            lt_stddev,
            cv_lead_time,
            pct_avec_promised,
            otd_when_measurable,
            pct_livraison_partielle,
            ROUND((
                LEAST(100, GREATEST(0, cv_raw * 100)) * 0.5
              + LEAST(100, GREATEST(0, 100 - otd_raw)) * 0.3
              + LEAST(100, COALESCE(pct_livraison_partielle, 0)) * 0.2
            )::numeric, 1) AS risk_score,
            CASE
                WHEN n_promised = 0 THEN 'no_promised_data'
                WHEN cv_raw > 0.35 OR otd_raw < 40 THEN 'critical'
                WHEN cv_raw > 0.25 THEN 'unstable'
                WHEN otd_raw < 55 THEN 'weak'
                WHEN otd_raw < 75 THEN 'acceptable'
                ELSE 'solid'
            END AS supplier_category
        FROM calc
        ORDER BY risk_score DESC
    """)

    if not sup_kpis.empty:
        r = sup_kpis.iloc[0]
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            otdv = float(r["otd_rate"])
            st.markdown(kpi_card(T["kpi_otd"], format_pct(otdv),
                                 "kpi-danger" if otdv < 70 else ("kpi-warning" if otdv < 85 else "kpi-success"),
                                 info=("Part des commandes fournisseurs livrées à l'heure. ↑ plus fiable (vert) · ↓ dérive (rouge)." if CLIENT_LANG == "fr" else "Share of supplier orders delivered on time. ↑ more reliable (green) · ↓ slipping (red).")),
                        unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card(T["col_lt"], f"{float(r['avg_lt']):.1f} j", "kpi-info", info=("Délai d'approvisionnement moyen mesuré sur les réceptions réelles." if CLIENT_LANG == "fr" else "Average lead time measured on actual receipts.")), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card(T["col_ltstd"], f"± {float(r['lt_std']):.1f} j", "kpi-warning", info=("Variabilité du délai fournisseur (écart-type). ↑ plus erratique (rouge) · ↓ plus stable (vert)." if CLIENT_LANG == "fr" else "Supplier lead-time variability (std dev). ↑ more erratic (red) · ↓ more stable (green).")), unsafe_allow_html=True)
        with c4:
            lbl = "Fournisseurs actifs" if CLIENT_LANG == "fr" else "Active suppliers"
            st.markdown(kpi_card(lbl, format_number(r["n_suppliers"]), "kpi-info", info=("Nombre de fournisseurs analysés sur la période." if CLIENT_LANG == "fr" else "Number of suppliers analysed over the period.")), unsafe_allow_html=True)
        with c5:
            lbl = "Lignes réceptionnées" if CLIENT_LANG == "fr" else "Received lines"
            st.markdown(kpi_card(lbl, format_number(r["n_lines"]), "kpi-info", info=("Nombre de lignes de commande fournisseur sur la période." if CLIENT_LANG == "fr" else "Number of supplier order lines over the period.")), unsafe_allow_html=True)

    scope_note = ("Seuls les fournisseurs avec au moins 5 réceptions sur la période sélectionnée sont notés."
                  if CLIENT_LANG == "fr" else
                  "Only suppliers with at least 5 receipts in the selected period are scored.")
    st.markdown(f'<div style="font-size:12px;color:#94a3b8;margin:10px 0 0;">{scope_note}</div>',
                unsafe_allow_html=True)

    st.write("")

    seg_l, seg_r = st.columns([3, 2], gap="medium")

    with seg_l:
        st.subheader(T["supplier_seg"])
        if not scorecard.empty:
            dist = (scorecard.groupby("supplier_category")
                    .agg(n=("supplier_name", "count"),
                         cmds=("commandes_total", "sum"),
                         otd=("otd_when_measurable", "mean"),
                         cv=("cv_lead_time", "mean"))
                    .reset_index())
        else:
            dist = pd.DataFrame()
        if not dist.empty:
            order = ["critical", "unstable", "weak", "acceptable", "solid", "no_promised_data"]
            dist["ord"] = dist["supplier_category"].map(lambda x: order.index(x) if x in order else 99)
            dist = dist.sort_values("ord")
            dist["label"] = dist["supplier_category"].map(lambda x: CN.get(x, x))
            cmap = {
                CN["critical"]: "#e5484d", CN["unstable"]: "#f97316", CN["weak"]: "#f79009",
                CN["acceptable"]: "#3b82f6", CN["solid"]: "#12b76a", CN["no_promised_data"]: "#94a3b8",
            }
            fig = px.bar(dist, x="label", y="n", color="label", color_discrete_map=cmap, text="n")
            fig = style_fig(fig, height=320)
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="")
            fig.update_traces(textposition="outside",
                              hovertemplate="<b>%{x}</b><br>%{y} " +
                              ("fournisseurs" if CLIENT_LANG == "fr" else "suppliers") + "<extra></extra>")
            try:
                fig.update_traces(marker_cornerradius=6)
            except Exception:
                pass
            st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        else:
            alert_box("info", T["no_data"])

    with seg_r:
        if CLIENT_LANG == "fr":
            actions = """
            <div class="aurora-panel" style="font-size:12.5px;color:#475569;line-height:1.65;">
              <div style="font-weight:700;color:#0f172a;font-size:14px;margin-bottom:10px;">Plan d'action par segment</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#e5484d;">Critique</b> — revue fournisseur immédiate, clause de pénalité, sourcing alternatif.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#f97316;">Instable</b> — double sourcing sous 3 mois, stock de sécurité renforcé.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#f79009;">Faible</b> — renégocier les dates promises. Ils décrochent de peu : ajouter 3 jours de coussin remonte l'OTD sans effort côté fournisseur.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#3b82f6;">Acceptable</b> — surveillance trimestrielle.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#12b76a;">Solide</b> — à utiliser comme référence de négociation.</div>
            </div>"""
        else:
            actions = """
            <div class="aurora-panel" style="font-size:12.5px;color:#475569;line-height:1.65;">
              <div style="font-weight:700;color:#0f172a;font-size:14px;margin-bottom:10px;">Action plan by segment</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#e5484d;">Critical</b> — immediate business review, penalty clause, alternative sourcing.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#f97316;">Unstable</b> — dual-source within 3 months, raise safety stock.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#f79009;">Weak</b> — renegotiate promised dates. They miss by a few days: adding a 3-day buffer lifts OTD with no supplier-side change.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#3b82f6;">Acceptable</b> — quarterly monitoring.</div>
              <div style="padding:7px 0;border-top:1px solid #f1f2f8;"><b style="color:#12b76a;">Solid</b> — use as negotiation benchmark.</div>
            </div>"""
        st.markdown(actions, unsafe_allow_html=True)

    st.write("")
    st.subheader(T["supplier_detail"])

    sup_all = scorecard.copy() if not scorecard.empty else pd.DataFrame()
    if not sup_all.empty:
        f1, f2 = st.columns([1, 3])
        with f1:
            cats = ([T["all_actions"]] +
                    [CN.get(c, c) for c in sup_all["supplier_category"].dropna().unique().tolist()])
            sel_cat = st.selectbox("cat", cats, key="sup_cat", label_visibility="collapsed")
        with f2:
            sup_q = st.text_input("q", key="sup_search",
                                  placeholder="🔍  " + (T["col_supplier"] + "…"),
                                  label_visibility="collapsed")

        view = sup_all.copy()
        view["cat_label"] = view["supplier_category"].map(lambda x: CN.get(x, x))
        if sel_cat != T["all_actions"]:
            view = view[view["cat_label"] == sel_cat]
        if sup_q:
            view = view[view["supplier_name"].astype(str).str.contains(sup_q, case=False, na=False)]

        st.markdown(
            f'<div style="font-size:12px;color:#94a3b8;margin:2px 0 8px;">'
            f'{T["showing"]} {len(view)} {T["of"]} {len(sup_all)} · {T["sort_hint"]}</div>',
            unsafe_allow_html=True)

        partial = "Livr. partielles %" if CLIENT_LANG == "fr" else "Partial deliv. %"
        out = view[["supplier_name", "cat_label", "commandes_total", "lt_moyen", "lt_stddev",
                    "cv_lead_time", "otd_when_measurable", "pct_livraison_partielle", "risk_score"]].copy()
        out.columns = [T["col_supplier"], T["col_category"], T["col_orders"], T["col_lt"],
                       T["col_ltstd"], T["col_cv"], T["col_otd"], partial, T["col_risk"]]
        sortable_table(out, index=True, height=560, wrap=[T["col_supplier"]],
                       cell_style={T["col_category"]: _bg_category}, formats={
            T["col_orders"]: "{:,.0f}", T["col_lt"]: "{:,.1f}", T["col_ltstd"]: "{:,.1f}",
            T["col_cv"]: "{:.2f}", T["col_otd"]: "{:.1f}%", partial: "{:.1f}%",
            T["col_risk"]: "{:.1f}",
        })
    else:
        alert_box("info", T["no_data"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: REORDER RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[3]:
    reo_kpis = run_query("""
        SELECT
            COUNT(*) FILTER (WHERE is_stockout_risk) AS at_risk,
            COALESCE(MIN(coverage_days) FILTER (WHERE is_stockout_risk AND coverage_days IS NOT NULL), 0) AS min_cov,
            (SELECT product_name FROM inventory
             WHERE is_stockout_risk AND coverage_days IS NOT NULL
             ORDER BY coverage_days ASC LIMIT 1) AS most_urgent,
            COUNT(*) FILTER (WHERE calculated_reorder_point IS NOT NULL
                             AND erp_reorder_point IS NOT NULL
                             AND ABS(calculated_reorder_point - erp_reorder_point) / NULLIF(erp_reorder_point,0) > 0.25) AS drifted
        FROM inventory
    """)
    if not reo_kpis.empty:
        r = reo_kpis.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card(T["kpi_stockout"], format_number(r["at_risk"]), "kpi-danger", info=("Références dont la couverture est sous le seuil d'alerte : à réapprovisionner en priorité." if CLIENT_LANG == "fr" else "References below the alert threshold — reorder first.")), unsafe_allow_html=True)
        with c2:
            lbl = "Couverture mini" if CLIENT_LANG == "fr" else "Min coverage"
            st.markdown(kpi_card(lbl, f"{float(r['min_cov'] or 0):.0f} j", "kpi-danger", info=("Couverture la plus faible parmi les références à risque, en jours." if CLIENT_LANG == "fr" else "Lowest coverage among at-risk references, in days.")), unsafe_allow_html=True)
        with c3:
            lbl = "Réf la + urgente" if CLIENT_LANG == "fr" else "Most urgent ref"
            st.markdown(kpi_card(lbl, _esc(str(r["most_urgent"] or "—")), "kpi-warning", small=True,
                                 info=("Référence la plus proche de la rupture." if CLIENT_LANG == "fr" else "Reference closest to stockout.")),
                        unsafe_allow_html=True)
        with c4:
            lbl = "Paramètres ERP dérivés" if CLIENT_LANG == "fr" else "Drifted ERP params"
            st.markdown(kpi_card(lbl, format_number(r["drifted"]), "kpi-warning", info=("Références dont le point de commande calculé s'écarte de plus de 25 % du paramétrage ERP." if CLIENT_LANG == "fr" else "References whose calculated reorder point deviates over 25% from the ERP setting.")), unsafe_allow_html=True)

    st.write("")
    st.subheader(T["reorder_table"])

    _a_reorder = T["act_reorder"]
    _a_liquidate = T["act_liquidate"]
    _a_stop = T["act_stop"]
    _a_hold = T["act_hold"]

    reorder_table = run_query(f"""
        SELECT
            article_code, product_name, article_type, warehouse,
            current_stock,
            ROUND(COALESCE(avg_daily_consumption, 0)::numeric, 2) AS daily,
            COALESCE(actual_lead_time_days, erp_lead_time_days, lead_time_days) AS lt,
            ROUND(COALESCE(erp_safety_stock, 0)::numeric, 0) AS ss_erp,
            ROUND(COALESCE(calculated_safety_stock, 0)::numeric, 0) AS ss_calc,
            ROUND(COALESCE(erp_reorder_point, 0)::numeric, 0) AS rop_erp,
            ROUND(COALESCE(calculated_reorder_point, 0)::numeric, 0) AS rop_calc,
            GREATEST(COALESCE(moq, 1),
                ROUND(GREATEST(0, COALESCE(calculated_reorder_point, 0) - current_stock))) AS qty,
            ROUND(COALESCE(coverage_days, 9999)::numeric, 0) AS days_out,
            CASE
                WHEN is_stockout_risk THEN '{_a_reorder}'
                WHEN is_dead_stock THEN '{_a_liquidate}'
                WHEN is_excess THEN '{_a_stop}'
                ELSE '{_a_hold}'
            END AS action
        FROM inventory
        WHERE avg_daily_consumption > 0
        ORDER BY coverage_days ASC NULLS LAST
        LIMIT 300
    """)

    if not reorder_table.empty:
        rt = reorder_table.copy()
        rt["article_type"] = rt["article_type"].map(lambda x: TN.get(x, x))
        daily_lbl = "Conso/jour" if CLIENT_LANG == "fr" else "Daily use"
        rt.columns = [T["col_code"], T["col_product"], T["col_type"], T["col_warehouse"],
                      T["col_stock"], daily_lbl, T["col_lt"], T["col_ss_erp"], T["col_ss_calc"],
                      T["col_rop_erp"], T["col_rop_calc"], T["col_qty"], T["col_days_out"], T["col_action"]]

        fcol1, fcol2, fcol3 = st.columns([3, 1, 1])
        with fcol1:
            reo_q = st.text_input("Search", key="reo_search",
                                  placeholder=T["search_product"], label_visibility="collapsed")
        with fcol2:
            actions_list = [T["all_actions"]] + sorted(rt[T["col_action"]].dropna().unique().tolist())
            reo_act = st.selectbox("Action", actions_list, key="reo_action", label_visibility="collapsed")
        with fcol3:
            types_list = [T["all_types"]] + sorted(rt[T["col_type"]].dropna().unique().tolist())
            reo_type = st.selectbox("Type", types_list, key="reo_type", label_visibility="collapsed")

        view = rt.copy()
        if reo_q:
            mask = (view[T["col_product"]].astype(str).str.contains(reo_q, case=False, na=False) |
                    view[T["col_code"]].astype(str).str.contains(reo_q, case=False, na=False))
            view = view[mask]
        if reo_act != T["all_actions"]:
            view = view[view[T["col_action"]] == reo_act]
        if reo_type != T["all_types"]:
            view = view[view[T["col_type"]] == reo_type]

        st.markdown(
            f'<div style="font-size:12px;color:#94a3b8;margin:2px 0 8px;">'
            f'{T["showing"]} {len(view)} {T["of"]} {len(rt)} {T["refs"]} · {T["sort_hint"]}</div>',
            unsafe_allow_html=True)

        sortable_table(view, height=620, wrap=[T["col_product"], T["col_action"]], cell_style={
            T["col_days_out"]: _bg_days_out, T["col_action"]: _bg_action,
        }, formats={
            T["col_stock"]: "{:,.0f}", daily_lbl: "{:,.2f}", T["col_lt"]: "{:,.0f}",
            T["col_ss_erp"]: "{:,.0f}", T["col_ss_calc"]: "{:,.0f}",
            T["col_rop_erp"]: "{:,.0f}", T["col_rop_calc"]: "{:,.0f}",
            T["col_qty"]: "{:,.0f}",
            T["col_days_out"]: lambda v: "∞" if float(v) >= 9000 else f"{float(v):,.0f}",
        })

        note = ("Les colonnes <b>SS/PC ERP</b> montrent ce qui est paramétré dans votre système ; "
                "<b>SS/PC calculé</b> montre ce que la demande réelle et la variabilité fournisseur imposent. "
                "L'écart entre les deux est la cause directe de vos ruptures et de votre surstock."
                if CLIENT_LANG == "fr" else
                "The <b>SS/ROP ERP</b> columns show what is configured in your system; "
                "<b>SS/ROP calc</b> shows what real demand and supplier variability actually require. "
                "The gap between the two is the direct cause of your stockouts and overstock.")
        st.markdown(f'<div style="font-size:12px;color:#94a3b8;margin-top:8px;line-height:1.5;">{note}</div>',
                    unsafe_allow_html=True)
    else:
        alert_box("info", T["no_data"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: AI ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[4]:
    st.subheader(T["ai_title"])
    st.caption(T["ai_caption"])

    with st.expander(T["ai_check"]):
        if st.button(T["ai_test"], key="ai_test_btn"):
            if not ANTHROPIC_API_KEY:
                alert_box("error", "❌ No anthropic_api_key found in secrets.")
            else:
                try:
                    import anthropic as _an
                    _c = _an.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0, max_retries=3)
                    _r = _c.messages.create(
                        model="claude-haiku-4-5-20251001", max_tokens=20,
                        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                    )
                    alert_box("success", "✅ API OK — " + _esc(_r.content[0].text))
                except Exception as e:
                    alert_box("error", "❌ " + _esc(str(e)))

    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = []
    if "processed_ids" not in st.session_state:
        st.session_state.processed_ids = set()
    if "next_question" not in st.session_state:
        st.session_state.next_question = None
    if "next_question_id" not in st.session_state:
        st.session_state.next_question_id = None

    st.markdown(f'<div style="font-size:13px;font-weight:700;margin:2px 0 8px;">{T["ai_try"]}</div>',
                unsafe_allow_html=True)
    sug_cols = st.columns(4)
    if CLIENT_LANG == "fr":
        suggestions = [
            "Quelles références dois-je liquider en priorité et pour quel montant ?",
            "Quels fournisseurs causent le plus de ruptures et pourquoi ?",
            "Mes paramètres ERP sont-ils encore à jour ?",
            "Où est bloquée ma trésorerie par famille d'articles ?",
        ]
    else:
        suggestions = [
            "Which references should I liquidate first and for how much?",
            "Which suppliers cause the most stockouts and why?",
            "Are my ERP parameters still up to date?",
            "Where is my cash tied up by article family?",
        ]
    for i, sug in enumerate(suggestions):
        with sug_cols[i]:
            if st.button(sug, key=f"sug_{i}", use_container_width=True):
                st.session_state.next_question = sug
                st.session_state.next_question_id = str(uuid.uuid4())

    for msg in st.session_state.ai_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["display"], unsafe_allow_html=True)
            for _sql, df in msg.get("dataframes", []):
                with st.expander(T["ai_see_data"]):
                    render_table(df, index=True, height=300)

    q = st.session_state.next_question
    qid = st.session_state.next_question_id
    already_done = qid in st.session_state.processed_ids if qid else True

    if q and qid and not already_done:
        st.session_state.processed_ids.add(qid)
        st.session_state.ai_messages.append({"role": "user", "display": q, "dataframes": [], "id": qid})

        with st.chat_message("user"):
            st.markdown(q)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            history = [{"role": m["role"], "content": m["display"]}
                       for m in st.session_state.ai_messages[:-1]]
            try:
                answer, dataframes = ask_claude(q, history, text_placeholder=placeholder)
            except Exception as e:
                answer = f"⚠️ {e}"
                dataframes = []
                placeholder.markdown(answer)
            for _sql, df in dataframes:
                with st.expander(T["ai_see_data"]):
                    render_table(df, index=True, height=300)

        st.session_state.ai_messages.append(
            {"role": "assistant", "display": answer, "dataframes": dataframes, "id": qid})
        st.session_state.next_question = None
        st.session_state.next_question_id = None

    with st.form("ai_form", clear_on_submit=True):
        col_in, col_btn = st.columns([6, 1])
        with col_in:
            user_input = st.text_input(
                T["ai_placeholder"], key="ai_input", label_visibility="collapsed",
                placeholder=T["ai_placeholder"],
            )
        with col_btn:
            submitted = st.form_submit_button(T["ai_send"], use_container_width=True)

    if submitted and user_input:
        st.session_state.next_question = user_input
        st.session_state.next_question_id = str(uuid.uuid4())
        st.rerun()

    if st.session_state.ai_messages:
        if st.button(T["ai_clear"]):
            st.session_state.ai_messages = []
            st.session_state.processed_ids = set()
            st.session_state.next_question = None
            st.session_state.next_question_id = None
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: DATA HEALTH
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[5]:
    st.subheader(T["health_title"])
    st.caption(T["health_caption"])

    st.markdown(f"### {T['health_freshness']}")
    freshness = run_query("""
        SELECT
            (SELECT COUNT(*) FROM inventory) AS n_refs,
            (SELECT COUNT(*) FROM stock_movements) AS n_mvt,
            (SELECT COUNT(*) FROM purchase_orders) AS n_po,
            (SELECT MAX(movement_date)::date FROM stock_movements) AS last_mvt,
            (SELECT MAX(order_date)::date FROM purchase_orders) AS last_po
    """)
    if not freshness.empty:
        f = freshness.iloc[0]
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            st.markdown(kpi_card(T["refs"], format_number(f["n_refs"]), "kpi-info", info=("Nombre de références présentes en base." if CLIENT_LANG == "fr" else "Number of references in the database.")), unsafe_allow_html=True)
        with fc2:
            lbl = "Mouvements" if CLIENT_LANG == "fr" else "Movements"
            st.markdown(kpi_card(lbl, format_number(f["n_mvt"]), "kpi-info", info=("Nombre de mouvements de stock ingérés." if CLIENT_LANG == "fr" else "Number of stock movements ingested.")), unsafe_allow_html=True)
        with fc3:
            lbl = "Lignes de commande" if CLIENT_LANG == "fr" else "PO lines"
            st.markdown(kpi_card(lbl, format_number(f["n_po"]), "kpi-info", info=("Nombre de lignes de commande fournisseur ingérées." if CLIENT_LANG == "fr" else "Number of supplier order lines ingested.")), unsafe_allow_html=True)
        with fc4:
            lbl = "Dernier mouvement" if CLIENT_LANG == "fr" else "Last movement"
            lm = str(f["last_mvt"]) if f["last_mvt"] else "—"
            st.markdown(kpi_card(lbl, lm, "kpi-info", info=("Date du dernier mouvement enregistré : indicateur de fraîcheur des données." if CLIENT_LANG == "fr" else "Date of the last recorded movement: a data-freshness indicator.")), unsafe_allow_html=True)

    st.write("")

    hl, hr = st.columns(2, gap="medium")

    with hl:
        st.markdown(f"### {T['health_audit']}")
        quality = run_query("""
            SELECT table_name, issue_code,
                   issue_label_fr, issue_label_en,
                   affected_rows, severity
            FROM data_quality_log
            WHERE audit_date >= CURRENT_DATE - INTERVAL '2 days'
            ORDER BY
                CASE severity WHEN 'critical' THEN 1 ELSE 2 END,
                affected_rows DESC
        """)
        if not quality.empty:
            label_col = "issue_label_fr" if CLIENT_LANG == "fr" else "issue_label_en"
            qv = quality[["table_name", label_col, "affected_rows", "severity"]].copy()
            issue_lbl = "Contrôle" if CLIENT_LANG == "fr" else "Check"
            rows_lbl = "Lignes" if CLIENT_LANG == "fr" else "Rows"
            sev_lbl = "Sévérité" if CLIENT_LANG == "fr" else "Severity"
            qv.columns = ["Table", issue_lbl, rows_lbl, sev_lbl]
            sortable_table(qv, index=False, height=420, wrap=[issue_lbl], cell_style={
                sev_lbl: lambda v: ("background:#fdecec;color:#b42318;font-weight:700;"
                                    if str(v) == "critical" else
                                    "background:#fef3e2;color:#a15c07;font-weight:600;"),
                rows_lbl: lambda v: ("background:#e7f7ef;color:#0f7a4d;"
                                     if float(v or 0) == 0 else
                                     "background:#fef3e2;color:#a15c07;font-weight:700;"),
            }, formats={rows_lbl: "{:,.0f}"})

            issues = int(quality[quality["affected_rows"] > 0].shape[0])
            crit = int(quality[(quality["severity"] == "critical") & (quality["affected_rows"] > 0)].shape[0])
            if crit > 0:
                alert_box("error", f"<b>{crit}</b> " +
                          ("problème(s) critique(s) — corrigez avant de vous fier aux métriques."
                           if CLIENT_LANG == "fr" else
                           "critical issue(s) — fix before relying on the metrics."))
            elif issues == 0:
                alert_box("success", "<b>EXCELLENT</b> — " +
                          ("aucun problème de qualité détecté." if CLIENT_LANG == "fr"
                           else "no data quality issue detected."))
            else:
                alert_box("warning", f"<b>{issues}</b> " +
                          ("point(s) d'attention mineur(s)." if CLIENT_LANG == "fr"
                           else "minor point(s) of attention."))
        else:
            alert_box("info", T["no_data"])

    with hr:
        st.markdown(f"### {T['health_valuation']}")
        val_gap = run_query("""
            SELECT
                ROUND(SUM(current_stock * unit_cost)::numeric, 0) AS ours,
                ROUND(SUM(erp_stock_value)::numeric, 0) AS erp,
                ROUND((100.0 * (SUM(current_stock * unit_cost) - SUM(erp_stock_value))
                       / NULLIF(SUM(erp_stock_value), 0))::numeric, 3) AS gap_pct,
                COUNT(*) FILTER (
                    WHERE erp_stock_value > 0
                      AND ABS(current_stock * unit_cost - erp_stock_value) / erp_stock_value > 0.05
                ) AS refs_off
            FROM inventory
        """)
        if not val_gap.empty:
            v = val_gap.iloc[0]
            gap = float(v["gap_pct"] or 0)
            vc1, vc2 = st.columns(2)
            with vc1:
                lbl = "Notre valorisation" if CLIENT_LANG == "fr" else "Our valuation"
                st.markdown(kpi_card(lbl, format_currency(v["ours"]), "kpi-info", info=("Valorisation du stock selon notre calcul (stock × coût unitaire)." if CLIENT_LANG == "fr" else "Stock valuation from our calculation (stock × unit cost).")), unsafe_allow_html=True)
            with vc2:
                lbl = "Valorisation ERP" if CLIENT_LANG == "fr" else "ERP valuation"
                st.markdown(kpi_card(lbl, format_currency(v["erp"]), "kpi-info", info=("Valorisation du stock fournie par l'ERP — la source de vérité comptable." if CLIENT_LANG == "fr" else "Stock valuation provided by the ERP — the accounting source of truth.")), unsafe_allow_html=True)
            st.write("")
            if abs(gap) < 1:
                alert_box("success", "✅ " + (f"Écart de valorisation : {gap:.3f}% — vos données de stock sont fiables."
                                              if CLIENT_LANG == "fr" else
                                              f"Valuation gap: {gap:.3f}% — your stock data is reliable."))
            else:
                alert_box("warning", "⚠️ " + (f"Écart de valorisation : {gap:.2f}% sur {int(v['refs_off'])} références."
                                              if CLIENT_LANG == "fr" else
                                              f"Valuation gap: {gap:.2f}% across {int(v['refs_off'])} references."))

        st.markdown(f"### {T['health_params']}")
        drift = run_query("""
            SELECT
                COUNT(*) FILTER (WHERE erp_lead_time_days IS NULL) AS lt_missing,
                COUNT(*) FILTER (WHERE erp_safety_stock IS NULL) AS ss_missing,
                COUNT(*) FILTER (WHERE erp_reorder_point IS NULL) AS rop_missing,
                COUNT(*) FILTER (
                    WHERE actual_lead_time_days IS NOT NULL AND erp_lead_time_days IS NOT NULL
                      AND ABS(actual_lead_time_days - erp_lead_time_days) > 7
                ) AS lt_drift,
                COUNT(*) AS total
            FROM inventory
        """)
        if not drift.empty:
            d = drift.iloc[0]
            missing_lbl = "Paramètre absent de l'ERP" if CLIENT_LANG == "fr" else "Parameter missing in ERP"
            dd = pd.DataFrame([
                [T["col_lt"], int(d["lt_missing"]), int(d["total"])],
                [T["col_ss_erp"], int(d["ss_missing"]), int(d["total"])],
                [T["col_rop_erp"], int(d["rop_missing"]), int(d["total"])],
            ], columns=[missing_lbl, "Manquant" if CLIENT_LANG == "fr" else "Missing",
                        "Total"])
            render_table(dd, height=200, formats={
                ("Manquant" if CLIENT_LANG == "fr" else "Missing"): "{:,.0f}",
                "Total": "{:,.0f}",
            })
            if int(d["lt_drift"]) > 0:
                alert_box("warning", "⚠️ " +
                          (f"{int(d['lt_drift'])} références ont un délai ERP décalé de plus de 7 jours "
                           f"par rapport aux réceptions réelles. Vos commandes sont passées sur des hypothèses obsolètes."
                           if CLIENT_LANG == "fr" else
                           f"{int(d['lt_drift'])} references have an ERP lead time off by more than 7 days "
                           f"versus actual receipts. Orders are placed on stale assumptions."))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7: PARAMETER DIAGNOSIS
# ══════════════════════════════════════════════════════════════════════════════
if _page == LOG_PAGES[6]:
    st.subheader(T["diag_title"])
    st.caption(T["diag_caption"])

    _params = run_query("""
        SELECT COUNT(erp_safety_stock) AS n_ss, COUNT(erp_lead_time_days) AS n_lt
        FROM inventory
    """)
    _has_params = (not _params.empty
                   and (int(_params.iloc[0]["n_ss"]) > 0 or int(_params.iloc[0]["n_lt"]) > 0))

    if not _has_params:
        alert_box("info", T["diag_no_params"])
    else:
        # ═══════════════════════════════════════════════════════════════════
        # 1 — ALERT QUALITY
        # ═══════════════════════════════════════════════════════════════════
        st.markdown(f"### {T['diag_alerts']}")

        _c_confirmed = "Alerte justifiée" if CLIENT_LANG == "fr" else "Justified alert"
        _c_false = "Fausse alerte" if CLIENT_LANG == "fr" else "False alert"
        _c_blind = "Risque non détecté" if CLIENT_LANG == "fr" else "Undetected risk"
        _c_ok = "Sain" if CLIENT_LANG == "fr" else "Healthy"

        alerts = run_query(f"""
            SELECT
              CASE
                WHEN current_stock < erp_safety_stock AND is_stockout_risk     THEN '{_c_confirmed}'
                WHEN current_stock < erp_safety_stock AND NOT is_stockout_risk THEN '{_c_false}'
                WHEN current_stock >= erp_safety_stock AND is_stockout_risk    THEN '{_c_blind}'
                ELSE '{_c_ok}'
              END AS diagnostic,
              COUNT(*) AS refs,
              ROUND(AVG(coverage_days)::numeric, 0) AS couverture
            FROM inventory
            WHERE erp_safety_stock IS NOT NULL AND avg_daily_consumption > 0
            GROUP BY 1
        """)

        if not alerts.empty:
            _m = {r["diagnostic"]: r for _, r in alerts.iterrows()}

            def _get(cat, col, default=0):
                return _m[cat][col] if cat in _m else default

            n_conf = int(_get(_c_confirmed, "refs"))
            n_false = int(_get(_c_false, "refs"))
            n_blind = int(_get(_c_blind, "refs"))
            n_total_alerts = n_conf + n_false

            a1, a2, a3, a4 = st.columns(4)
            with a1:
                lbl = "Alertes déclenchées" if CLIENT_LANG == "fr" else "Alerts triggered"
                st.markdown(kpi_card(lbl, format_number(n_total_alerts), "kpi-info",
                                     info=("Nombre total d'alertes de stock bas produites par le paramétrage ERP actuel." if CLIENT_LANG == "fr" else "Total low-stock alerts produced by the current ERP configuration.")),
                            unsafe_allow_html=True)
            with a2:
                lbl = "Dont justifiées" if CLIENT_LANG == "fr" else "Of which justified"
                st.markdown(kpi_card(lbl, format_number(n_conf), "kpi-success",
                                     info=("Alertes ERP confirmées par notre calcul de risque : justifiées." if CLIENT_LANG == "fr" else "ERP alerts confirmed by our risk calculation: justified.")),
                            unsafe_allow_html=True)
            with a3:
                lbl = "Dont fausses" if CLIENT_LANG == "fr" else "Of which false"
                st.markdown(kpi_card(lbl, format_number(n_false), "kpi-danger",
                                     info=("Alertes ERP jugées injustifiées par notre calcul : faux positifs." if CLIENT_LANG == "fr" else "ERP alerts our calculation deems unjustified: false positives.")),
                            unsafe_allow_html=True)
            with a4:
                lbl = "Risques non vus" if CLIENT_LANG == "fr" else "Undetected risks"
                st.markdown(kpi_card(lbl, format_number(n_blind), "kpi-danger",
                                     info=("Ruptures que notre calcul détecte mais que l'ERP ne signale pas : angles morts." if CLIENT_LANG == "fr" else "Stockouts our calculation catches but the ERP misses: blind spots.")),
                            unsafe_allow_html=True)

            al_l, al_r = st.columns([3, 2], gap="medium")

            with al_l:
                order = [_c_false, _c_ok, _c_confirmed, _c_blind]
                av = alerts.copy()
                av["ord"] = av["diagnostic"].map(lambda x: order.index(x) if x in order else 9)
                av = av.sort_values("ord")
                cmap = {_c_false: "#f79009", _c_ok: "#12b76a",
                        _c_confirmed: "#3b82f6", _c_blind: "#e5484d"}
                fig = px.bar(av, x="diagnostic", y="refs", color="diagnostic",
                             color_discrete_map=cmap, text="refs")
                fig = style_fig(fig, height=320)
                fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="")
                fig.update_traces(textposition="outside",
                                  hovertemplate="<b>%{x}</b><br>%{y} " +
                                  ("références" if CLIENT_LANG == "fr" else "references") +
                                  "<extra></extra>")
                try:
                    fig.update_traces(marker_cornerradius=6)
                except Exception:
                    pass
                st.plotly_chart(fig, use_container_width=True, theme=None,
                                config={"displayModeBar": False})

            with al_r:
                if n_total_alerts > 0:
                    pct_false = 100.0 * n_false / n_total_alerts
                    cov_false = float(_get(_c_false, "couverture") or 0)
                    cov_blind = float(_get(_c_blind, "couverture") or 0)
                    if CLIENT_LANG == "fr":
                        body = (f"Sur <b>{n_total_alerts}</b> alertes de stock bas déclenchées par le "
                                f"paramétrage actuel, <b>{n_false}</b> portent sur des références qui "
                                f"disposent de <b>{cov_false:.0f} jours</b> de couverture — soit "
                                f"<b>{pct_false:.0f} %</b> de bruit.<br><br>"
                                f"Un acheteur qui reçoit quatre fausses alertes sur cinq cesse de les "
                                f"lire. Pendant ce temps, <b>{n_blind} références</b> réellement à "
                                f"risque ({cov_blind:.0f} jours de couverture) ne déclenchent rien.")
                    else:
                        body = (f"Out of <b>{n_total_alerts}</b> low-stock alerts raised by the current "
                                f"configuration, <b>{n_false}</b> concern references holding "
                                f"<b>{cov_false:.0f} days</b> of coverage — <b>{pct_false:.0f}%</b> noise."
                                f"<br><br>Buyers who get four false alerts out of five stop reading them. "
                                f"Meanwhile <b>{n_blind} references</b> genuinely at risk "
                                f"({cov_blind:.0f} days of coverage) trigger nothing at all.")
                    st.markdown(
                        f'<div class="aurora-panel" style="font-size:12.5px;color:#475569;'
                        f'line-height:1.65;">{body}</div>', unsafe_allow_html=True)

        st.write("")

        # ═══════════════════════════════════════════════════════════════════
        # 2 — SAFETY STOCK: CONFIGURED VS CALCULATED
        # ═══════════════════════════════════════════════════════════════════
        st.markdown(f"### {T['diag_ss']}")

        ss = run_query("""
            SELECT
              abc_class,
              COUNT(*) AS refs,
              ROUND(AVG(erp_safety_stock)::numeric, 0)        AS ss_erp,
              ROUND(AVG(calculated_safety_stock)::numeric, 0) AS ss_calc,
              ROUND(AVG(current_stock)::numeric, 0)           AS stock_reel
            FROM inventory
            WHERE erp_safety_stock IS NOT NULL
              AND calculated_safety_stock IS NOT NULL
              AND abc_class IS NOT NULL
            GROUP BY abc_class
            ORDER BY abc_class
        """)

        if not ss.empty:
            ss_l, ss_r = st.columns([3, 2], gap="medium")

            with ss_l:
                lbl_erp = "Paramétré ERP" if CLIENT_LANG == "fr" else "ERP configured"
                lbl_calc = "Calculé" if CLIENT_LANG == "fr" else "Calculated"
                fig = go.Figure()
                fig.add_trace(go.Bar(name=lbl_erp, x=ss["abc_class"], y=ss["ss_erp"],
                                     marker_color="#94a3b8"))
                fig.add_trace(go.Bar(name=lbl_calc, x=ss["abc_class"], y=ss["ss_calc"],
                                     marker_color="#6355ff"))
                fig = style_fig(fig, height=320, legend=True)
                fig.update_layout(barmode="group", xaxis_title="",
                                  yaxis_title=("Unités" if CLIENT_LANG == "fr" else "Units"))
                try:
                    fig.update_traces(marker_cornerradius=6)
                except Exception:
                    pass
                st.plotly_chart(fig, use_container_width=True, theme=None,
                                config={"displayModeBar": False})

            with ss_r:
                try:
                    spread_erp = float(ss["ss_erp"].max()) / max(float(ss["ss_erp"].min()), 1)
                    spread_calc = float(ss["ss_calc"].max()) / max(float(ss["ss_calc"].min()), 1)
                except Exception:
                    spread_erp = spread_calc = 1.0
                if CLIENT_LANG == "fr":
                    body = (f"Le stock de sécurité paramétré varie d'un facteur "
                            f"<b>{spread_erp:.1f}</b> entre les classes A et C. Le calcul, qui intègre "
                            f"la criticité et la variabilité de la demande, demande un facteur "
                            f"<b>{spread_calc:.1f}</b>.<br><br>"
                            f"Autrement dit, le paramétrage actuel protège les références de classe C "
                            f"presque autant que celles qui portent 80 % du flux. Ce n'est pas un "
                            f"réglage à affiner, c'est une logique de classe absente.")
                else:
                    body = (f"Configured safety stock varies by a factor of <b>{spread_erp:.1f}</b> "
                            f"between classes A and C. The calculation, which accounts for criticality "
                            f"and demand variability, calls for a factor of <b>{spread_calc:.1f}</b>."
                            f"<br><br>In other words, the current configuration protects class C "
                            f"references almost as much as those carrying 80% of the flow. This is not "
                            f"a setting to fine-tune — it is a missing class logic.")
                st.markdown(
                    f'<div class="aurora-panel" style="font-size:12.5px;color:#475569;'
                    f'line-height:1.65;">{body}</div>', unsafe_allow_html=True)

            sv = ss.copy()
            stock_lbl = "Stock réel moyen" if CLIENT_LANG == "fr" else "Avg actual stock"
            erp_lbl = "SS paramétré" if CLIENT_LANG == "fr" else "SS configured"
            calc_lbl = "SS calculé" if CLIENT_LANG == "fr" else "SS calculated"
            sv.columns = [T["col_abc"], T["refs"], erp_lbl, calc_lbl, stock_lbl]
            render_table(sv, height=220, formats={
                T["refs"]: "{:,.0f}", erp_lbl: "{:,.0f}",
                calc_lbl: "{:,.0f}", stock_lbl: "{:,.0f}",
            })

        st.write("")

        # ═══════════════════════════════════════════════════════════════════
        # 3 — LEAD TIME RELIABILITY
        # ═══════════════════════════════════════════════════════════════════
        st.markdown(f"### {T['diag_lt']}")

        lt = run_query("""
            SELECT
              COUNT(*) AS refs,
              ROUND(AVG(erp_lead_time_days)::numeric, 1)    AS lt_erp,
              ROUND(AVG(actual_lead_time_days)::numeric, 1) AS lt_reel,
              ROUND(AVG(ABS(actual_lead_time_days - erp_lead_time_days))::numeric, 1) AS ecart_abs,
              ROUND(MAX(ABS(actual_lead_time_days - erp_lead_time_days))::numeric, 1) AS ecart_max,
              COUNT(*) FILTER (WHERE ABS(actual_lead_time_days - erp_lead_time_days) > 7)  AS sup7,
              COUNT(*) FILTER (WHERE ABS(actual_lead_time_days - erp_lead_time_days) > 14) AS sup14
            FROM inventory
            WHERE actual_lead_time_days IS NOT NULL AND erp_lead_time_days IS NOT NULL
        """)

        if not lt.empty and int(lt.iloc[0]["refs"]) > 0:
            l = lt.iloc[0]
            n_refs = int(l["refs"])
            n7 = int(l["sup7"])
            pct7 = 100.0 * n7 / n_refs if n_refs else 0

            t1, t2, t3, t4 = st.columns(4)
            with t1:
                lbl = "Délai moyen ERP" if CLIENT_LANG == "fr" else "Avg ERP lead time"
                st.markdown(kpi_card(lbl, f"{float(l['lt_erp']):.1f} j", "kpi-info",
                                     info=("Délai d'approvisionnement tel que saisi dans l'ERP." if CLIENT_LANG == "fr" else "Lead time as configured in the ERP.")),
                            unsafe_allow_html=True)
            with t2:
                lbl = "Délai moyen réel" if CLIENT_LANG == "fr" else "Avg actual lead time"
                st.markdown(kpi_card(lbl, f"{float(l['lt_reel']):.1f} j", "kpi-info",
                                     info=("Délai réel mesuré sur les réceptions fournisseurs." if CLIENT_LANG == "fr" else "Actual lead time measured on supplier receipts.")),
                            unsafe_allow_html=True)
            with t3:
                lbl = "Écart absolu moyen" if CLIENT_LANG == "fr" else "Mean absolute gap"
                st.markdown(kpi_card(lbl, f"{float(l['ecart_abs']):.1f} j", "kpi-warning",
                                     info=("Écart absolu moyen entre le délai ERP et le délai réel." if CLIENT_LANG == "fr" else "Average absolute gap between ERP and actual lead time.")),
                            unsafe_allow_html=True)
            with t4:
                lbl = "Écart max" if CLIENT_LANG == "fr" else "Max gap"
                st.markdown(kpi_card(lbl, f"{float(l['ecart_max']):.0f} j", "kpi-danger",
                                     info=("Écart maximal observé entre délai ERP et délai réel." if CLIENT_LANG == "fr" else "Largest gap observed between ERP and actual lead time.")),
                            unsafe_allow_html=True)

            if CLIENT_LANG == "fr":
                body = (f"Les moyennes concordent — <b>{float(l['lt_erp']):.1f}</b> jours paramétrés "
                        f"contre <b>{float(l['lt_reel']):.1f}</b> jours constatés. C'est précisément ce "
                        f"qui rend le problème invisible dans un reporting agrégé.<br><br>"
                        f"Référence par référence, <b>{n7}</b> articles sur {n_refs} "
                        f"(<b>{pct7:.0f} %</b>) ont un délai faux de plus d'une semaine, dont "
                        f"<b>{int(l['sup14'])}</b> de plus de deux semaines. Les erreurs se compensent "
                        f"dans la moyenne, pas dans les commandes.")
            else:
                body = (f"The averages agree — <b>{float(l['lt_erp']):.1f}</b> days configured against "
                        f"<b>{float(l['lt_reel']):.1f}</b> days observed. That is precisely what makes "
                        f"the problem invisible in aggregate reporting.<br><br>"
                        f"Reference by reference, <b>{n7}</b> out of {n_refs} items "
                        f"(<b>{pct7:.0f}%</b>) have a lead time wrong by more than a week, including "
                        f"<b>{int(l['sup14'])}</b> wrong by more than two weeks. Errors cancel out in "
                        f"the average, not in the orders.")
            st.markdown(
                f'<div class="aurora-panel" style="font-size:12.5px;color:#475569;'
                f'line-height:1.65;margin-top:6px;">{body}</div>', unsafe_allow_html=True)

            st.write("")

            worst = run_query("""
                SELECT
                  article_code, product_name, article_type, supplier_name,
                  erp_lead_time_days AS lt_erp,
                  ROUND(actual_lead_time_days::numeric, 1) AS lt_reel,
                  ROUND((actual_lead_time_days - erp_lead_time_days)::numeric, 1) AS ecart
                FROM inventory
                WHERE actual_lead_time_days IS NOT NULL AND erp_lead_time_days IS NOT NULL
                ORDER BY ABS(actual_lead_time_days - erp_lead_time_days) DESC
                LIMIT 25
            """)
            if not worst.empty:
                wv = worst.copy()
                wv["article_type"] = wv["article_type"].map(lambda x: TN.get(x, x))
                erp_lbl = "Délai ERP" if CLIENT_LANG == "fr" else "ERP LT"
                real_lbl = "Délai réel" if CLIENT_LANG == "fr" else "Actual LT"
                gap_lbl = "Écart (j)" if CLIENT_LANG == "fr" else "Gap (d)"
                wv.columns = [T["col_code"], T["col_product"], T["col_type"], T["col_supplier"],
                              erp_lbl, real_lbl, gap_lbl]
                sortable_table(wv, index=True, height=420,
                               wrap=[T["col_product"], T["col_supplier"]],
                               cell_style={gap_lbl: _bg_variance}, formats={
                    erp_lbl: "{:,.0f}", real_lbl: "{:,.1f}", gap_lbl: "{:+.1f}",
                })
        else:
            alert_box("info",
                      ("Pas assez de réceptions pour mesurer un délai réel comparable au paramétrage."
                       if CLIENT_LANG == "fr" else
                       "Not enough receipts to measure an actual lead time comparable to the configuration."))

# ══════════════════════════════════════════════════════════════════════════════
# WHAT-IF SIMULATOR  (read-only: replays STEP 4's formula in Python, writes nothing)
# ══════════════════════════════════════════════════════════════════════════════
if _page == T["tab_whatif"]:
    fr = (CLIENT_LANG == "fr")
    st.subheader("🧪 " + ("Simulateur de politique de stock" if fr else "Stock policy simulator"))
    st.markdown(
        '<div style="font-size:13px;color:#64748b;margin:-6px 0 12px;">' + (
            "Faites varier le niveau de service, la tension sur les délais et les coûts : stock de "
            "sécurité, point de commande et cash immobilisé se recalculent en direct. Aucune donnée "
            "n'est modifiée — vos calculs nocturnes restent la référence."
            if fr else
            "Vary service level, lead-time pressure and costs: safety stock, reorder point and tied-up "
            "cash recompute live. Nothing is written — your nightly calculations stay the source of truth."
        ) + '</div>', unsafe_allow_html=True)

    sim = run_query("""
        SELECT i.article_code, i.product_name, i.abc_class,
               COALESCE(i.avg_daily_consumption,0)                          AS d,
               COALESCE(i.consumption_stddev,0)                             AS sd,
               COALESCE(i.actual_lead_time_days, i.erp_lead_time_days, 30)  AS lt,
               COALESCE(i.lead_time_stddev,0)                               AS slt,
               COALESCE(i.unit_cost,0)                                      AS unit_cost,
               COALESCE(i.current_stock,0)                                  AS current_stock,
               i.moq,
               COALESCE(i.calculated_safety_stock,0)                        AS ss_now,
               COALESCE(i.calculated_reorder_point,0)                       AS rop_now,
               at.holding_cost_rate                                         AS h_rate
        FROM inventory i
        JOIN article_types at ON at.code = COALESCE(i.article_type, 'NA')
        WHERE COALESCE(i.avg_daily_consumption,0) > 0
    """)

    if sim is None or sim.empty:
        alert_box("info", ("Lancez le pipeline KPI pour alimenter le simulateur."
                           if fr else "Run the KPI pipeline to feed the simulator."))
    else:
        # Z table (inverse normal) — no scipy dependency. Per-ABC reproduces STEP 4 exactly.
        Z_TABLE = {90: 1.2816, 95: 1.6449, 97: 1.8808, 98: 2.0537, 99: 2.3263, 99.5: 2.5758}
        _by_abc = ("Par classe ABC (actuel)" if fr else "By ABC class (current)")
        _uniform = ("Uniforme" if fr else "Uniform")

        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            mode = st.radio(("Niveau de service" if fr else "Service level"),
                            [_by_abc, _uniform], key="wf_mode")
            uniform_level = st.select_slider(("Cible uniforme" if fr else "Uniform target"),
                            options=[90, 95, 97, 98, 99, 99.5], value=95, key="wf_level",
                            format_func=lambda v: f"{v}%")
        with cc2:
            lt_factor = st.slider(("Tension sur les délais (×)" if fr else "Lead-time pressure (×)"),
                                  0.8, 2.0, 1.0, 0.05, key="wf_ltf")
            review = st.slider(("Période de révision (j)" if fr else "Review period (d)"),
                               0, 30, 0, 1, key="wf_R")
        with cc3:
            order_cost = st.number_input(("Coût de passation (€/commande)" if fr else "Order cost (€/order)"),
                                         min_value=0.0, value=50.0, step=10.0, key="wf_S")
            force_h = st.checkbox(("Forcer un taux de possession unique" if fr else "Force one holding rate"),
                                  value=False, key="wf_fh")
            h_pct = st.slider(("Taux de possession annuel (%)" if fr else "Annual holding rate (%)"),
                              5, 35, 20, 1, key="wf_h", disabled=not force_h)

        # ── vectorised recompute (mirrors industrial_kpi_computation.sql STEP 4) ──
        d   = pd.to_numeric(sim["d"],   errors="coerce").fillna(0.0)
        sd  = pd.to_numeric(sim["sd"],  errors="coerce").fillna(0.0)
        lt  = pd.to_numeric(sim["lt"],  errors="coerce").fillna(30.0)
        slt = pd.to_numeric(sim["slt"], errors="coerce").fillna(0.0)
        uc  = pd.to_numeric(sim["unit_cost"], errors="coerce").fillna(0.0)
        cur = pd.to_numeric(sim["current_stock"], errors="coerce").fillna(0.0)
        moq = pd.to_numeric(sim["moq"], errors="coerce").fillna(1.0).clip(lower=1.0)
        hr  = pd.to_numeric(sim["h_rate"], errors="coerce").fillna(0.20)
        ss_now  = pd.to_numeric(sim["ss_now"],  errors="coerce").fillna(0.0)
        rop_now = pd.to_numeric(sim["rop_now"], errors="coerce").fillna(0.0)

        lt2 = lt * lt_factor
        if mode == _by_abc:
            z = sim["abc_class"].map({"A": 2.05, "B": 1.65, "C": 1.28}).fillna(1.28).astype(float)
        else:
            z = pd.Series(Z_TABLE[uniform_level], index=sim.index, dtype=float)

        sigma_term = ((lt2 * sd**2) + (d**2 * slt**2)).clip(lower=0.0) ** 0.5
        ss_new  = (z * sigma_term).round(2)
        rop_new = (d * (lt2 + review) + ss_new).round(2)

        h = pd.Series(h_pct / 100.0, index=sim.index) if force_h else hr
        denom = uc * h
        eoq = ((2.0 * d * 365.0 * order_cost) / denom.where(denom > 0)) ** 0.5
        eoq_moq = pd.concat([eoq.fillna(0.0), moq], axis=1).max(axis=1).round(0)

        below_new, below_now = (cur < rop_new), (cur < rop_now)
        cash_ss_new, cash_ss_now = float((ss_new * uc).sum()), float((ss_now * uc).sum())
        holding_annual = float((ss_new * uc * h).sum() + (eoq_moq / 2.0 * uc * h).sum())
        orders_yr = (d * 365.0) / eoq_moq.where(eoq_moq > 0)
        ordering_annual = float((orders_yr.fillna(0.0) * order_cost).sum())
        total_cost = holding_annual + ordering_annual

        def _wf_delta(new, old):  # lower = better -> down green, up red
            if not old:
                return "", ""
            p = (new - old) / abs(old) * 100.0
            if abs(p) < 0.05:
                return "→ 0.0%", "#94a3b8"
            up = p > 0
            return (("↑" if up else "↓") + f" {abs(p):.1f}%"), ("#e5484d" if up else "#12b76a")

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            dd = _wf_delta(cash_ss_new, cash_ss_now)
            st.markdown(kpi_card(("Cash en stock de sécurité" if fr else "Cash in safety stock"),
                format_currency(cash_ss_new), "kpi-warning", delta=dd[0], delta_color=dd[1],
                info=("Stock de sécurité valorisé au niveau de service simulé, vs actuel."
                      if fr else "Valued safety stock at the simulated service level, vs current.")),
                unsafe_allow_html=True)
        with k2:
            dd = _wf_delta(int(below_new.sum()), int(below_now.sum()))
            st.markdown(kpi_card(("Réfs sous point de commande" if fr else "Refs below reorder point"),
                format_number(int(below_new.sum())), "kpi-danger", delta=dd[0], delta_color=dd[1],
                info=("Références dont le stock actuel passe sous le point de commande simulé."
                      if fr else "References whose current stock falls below the simulated reorder point.")),
                unsafe_allow_html=True)
        with k3:
            st.markdown(kpi_card(("Coût annuel total estimé" if fr else "Est. total annual cost"),
                format_currency(total_cost), "kpi-info",
                info=("Possession (sécurité + stock de cycle EOQ/2) + coût de passation."
                      if fr else "Holding (safety + EOQ/2 cycle stock) + ordering cost.")),
                unsafe_allow_html=True)
        with k4:
            lvl = (("par classe ABC" if fr else "by ABC class") if mode == _by_abc else f"{uniform_level}%")
            st.markdown(kpi_card(("Niveau de service" if fr else "Service level"),
                str(lvl), "kpi-success",
                info=("Niveau de service simulé : la probabilité de ne pas être en rupture pendant le délai."
                      if fr else "Simulated service level: the probability of not stocking out during lead time.")),
                unsafe_allow_html=True)

        st.write("")
        gL, gR = st.columns([3, 2], gap="medium")
        with gL:
            st.subheader("Cash ↔ " + ("niveau de service" if fr else "service level"))
            base_term = sigma_term * uc  # cash contribution per unit of Z
            lv = [90, 95, 97, 98, 99, 99.5]
            cash_curve = [float((Z_TABLE[l] * base_term).sum()) for l in lv]
            figc = go.Figure()
            figc.add_trace(go.Scatter(x=lv, y=cash_curve, mode="lines+markers",
                line=dict(color="#6355ff", width=2.5), marker=dict(size=7, color="#6355ff"),
                fill="tozeroy", fillcolor="rgba(99,85,255,0.10)",
                hovertemplate="%{x}%<br>%{y:,.0f} " + CURRENCY + "<extra></extra>"))
            if mode != _by_abc:
                figc.add_vline(x=uniform_level, line=dict(color="#e5484d", width=1.5, dash="dot"))
            figc = style_fig(figc, height=300)
            figc.update_layout(xaxis_title=("Niveau de service (%)" if fr else "Service level (%)"),
                               yaxis_title="Cash (" + CURRENCY + ")")
            st.plotly_chart(figc, use_container_width=True, theme=None, config={"displayModeBar": False})
        with gR:
            st.subheader("Impact " + ("par classe ABC" if fr else "by ABC class"))
            imp = pd.DataFrame({"abc": sim["abc_class"].fillna("C"),
                                "now": ss_now * uc, "sim": ss_new * uc})
            agg = imp.groupby("abc").sum(numeric_only=True).reindex(["A", "B", "C"]).fillna(0.0)
            figb = go.Figure()
            figb.add_trace(go.Bar(x=agg.index, y=agg["now"],
                                  name=("Actuel" if fr else "Current"), marker_color="#c4b5fd"))
            figb.add_trace(go.Bar(x=agg.index, y=agg["sim"],
                                  name=("Simulé" if fr else "Simulated"), marker_color="#6355ff"))
            figb = style_fig(figb, height=300, legend=True)
            figb.update_layout(barmode="group", yaxis_title="Cash (" + CURRENCY + ")")
            st.plotly_chart(figb, use_container_width=True, theme=None, config={"displayModeBar": False})

        st.subheader("Références les plus impactées" if fr else "Most-impacted references")
        cN = {"code": "Code", "name": ("Désignation" if fr else "Name"),
              "ss0": ("SS actuel" if fr else "SS now"), "ss1": ("SS simulé" if fr else "SS sim"),
              "rop0": ("ROP actuel" if fr else "ROP now"), "rop1": ("ROP simulé" if fr else "ROP sim"),
              "drop": "Δ ROP"}
        out = pd.DataFrame({
            cN["code"]: sim["article_code"].values,
            cN["name"]: sim["product_name"].values,
            "ABC": sim["abc_class"].fillna("C").values,
            cN["ss0"]: ss_now.round(0).values,  cN["ss1"]: ss_new.round(0).values,
            cN["rop0"]: rop_now.round(0).values, cN["rop1"]: rop_new.round(0).values,
            "EOQ": eoq_moq.values,
            cN["drop"]: (rop_new - rop_now).round(0).values,
        })
        out["_a"] = (rop_new - rop_now).abs().values
        out = out.sort_values("_a", ascending=False).drop(columns="_a").head(40)
        _nf = lambda v: format_number(v)
        render_table(out, formats={cN["ss0"]: _nf, cN["ss1"]: _nf, cN["rop0"]: _nf,
                                   cN["rop1"]: _nf, "EOQ": _nf, cN["drop"]: _nf})



# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTION SCREENS
# ══════════════════════════════════════════════════════════════════════════════
if _page == P_SYNTH:
    st.subheader("📊 " + ("Où le cash se consume sur la ligne" if _PF else "Where cash burns on the line"))
    s, mudas, k = prod_compute()
    # Source des données : visible sans être un bandeau de chantier (R6).
    if k.get("source") == "db":
        _src = ((f"Campagne <b>{_esc(k.get('campagne',''))}</b> · relevés terrain en base" if _PF
                 else f"Campaign <b>{_esc(k.get('campagne',''))}</b> · field data from database"), "#12b76a")
    else:
        _src = (("Jeu de démonstration · aucune campagne en base" if _PF
                 else "Demonstration dataset · no campaign in database"), "#94a3b8")
    st.markdown(f'<div style="font-size:11.5px;color:{_src[1]};margin:-8px 0 12px;">'
                f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
                f'background:{_src[1]};margin-right:6px;"></span>{_src[0]}</div>', unsafe_allow_html=True)
    prod_natures_note()

    # ── Sélecteur de période (spec 3.1) ─────────────────────────────────────
    _periods = ([("Aujourd'hui", 1.0 / JOURS_OUVRES_AN), ("Semaine", 5.0 / JOURS_OUVRES_AN),
                 ("Mois", 18.3 / JOURS_OUVRES_AN), ("YTD", 160.0 / JOURS_OUVRES_AN), ("12 mois", 1.0)]
                if _PF else
                [("Today", 1.0 / JOURS_OUVRES_AN), ("Week", 5.0 / JOURS_OUVRES_AN),
                 ("Month", 18.3 / JOURS_OUVRES_AN), ("YTD", 160.0 / JOURS_OUVRES_AN), ("12 months", 1.0)])
    _pnames = [p[0] for p in _periods]
    _psel = st.radio("Période", _pnames, index=4, horizontal=True,
                     key="prod_period", label_visibility="collapsed")
    _pfac = dict(_periods)[_psel]
    # variations vs période précédente (démo — le back end fournira le réel)
    _pdelta = {_pnames[0]: {"c": -1.8, "k": -0.9, "i": 0.4},
               _pnames[1]: {"c": -2.6, "k": -1.2, "i": 0.7},
               _pnames[2]: {"c": -3.1, "k": -1.8, "i": 1.1},
               _pnames[3]: {"c": -6.4, "k": -3.5, "i": 2.0},
               _pnames[4]: {"c": -8.2, "k": -4.1, "i": 2.6}}[_psel]

    # ── R4 : trois cartes, une par nature — aucun total ─────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        d = _delta_txt(_pdelta["c"])
        st.markdown(kpi_card(N_CONST, format_currency(k["constate"] * _pfac), "kpi-danger",
            delta=d[0], delta_color=d[1],
            info=("Décaissements réels : matière rebutée valorisée au coût cumulé de l'étape + heures de retouche payées. Non contestable." if _PF
                  else "Real cash out: scrapped material at step-accumulated cost + paid rework hours. Non-negotiable.")), unsafe_allow_html=True)
    with c2:
        d = _delta_txt(_pdelta["k"])
        st.markdown(kpi_card(N_CAPA, format_currency(k["capacite"] * _pfac), "kpi-warning",
            delta=d[0], delta_color=d[1],
            info=(f"Chiffrée uniquement sur les postes réellement contraints (charge ≥ {SEUIL_CONTRAINTE*100:.0f} %) et non rattrapables, à la marge sur coût variable. Ailleurs le travail se termine quand même : la perte vaut 0 €." if _PF
                  else f"Valued only on genuinely constrained stations (load ≥ {SEUIL_CONTRAINTE*100:.0f}%) that cannot catch up, at contribution margin. Elsewhere the work still gets done: the loss is €0.")), unsafe_allow_html=True)
    with c3:
        d = _delta_txt(_pdelta["i"])
        st.markdown(kpi_card(N_CAPI, format_currency(k["capital"] * _pfac), "kpi-capital",
            delta=d[0], delta_color=d[1],
            info=(f"Encours + surproduction × taux de possession ({TAUX_POSSESSION_ANNUEL*100:.0f} %/an). Un coût de portage, pas une perte sèche." if _PF
                  else f"WIP + overproduction × carrying rate ({TAUX_POSSESSION_ANNUEL*100:.0f}%/yr). A carrying cost, not a loss.")), unsafe_allow_html=True)

    st.write("")
    # ── TRS pondéré + composantes (spec 2.2) ────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_card("TRS " + ("ligne (pondéré)" if _PF else "line (weighted)"),
            f"{k['trs']*100:.1f}%", _trs_class(k["trs"]),
            info=("D × P × Q, agrégés sur les temps réels de chaque poste — jamais une moyenne de ratios." if _PF
                  else "D × P × Q aggregated on each station's actual times — never an average of ratios.")), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card(("Disponibilité ligne" if _PF else "Line availability"),
            f"{k['d_l']*100:.1f}%", "kpi-info",
            info=("Σ temps de fonctionnement / Σ temps requis." if _PF else "Σ run time / Σ required time.")), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card(("Performance ligne" if _PF else "Line performance"),
            f"{k['p_l']*100:.1f}%", "kpi-info",
            info=("Σ (pièces × cycle nominal) / Σ temps de fonctionnement." if _PF else "Σ (pieces × nominal cycle) / Σ run time.")), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card(("Qualité ligne" if _PF else "Line quality"),
            f"{k['q_l']*100:.1f}%", "kpi-info",
            info=("Σ pièces bonnes / Σ pièces produites." if _PF else "Σ good pieces / Σ produced pieces.")), unsafe_allow_html=True)

    st.write("")
    gL, gR = st.columns([2, 3], gap="medium")
    with gL:
        st.subheader(("TRS par niveau" if _PF else "OEE by level"))
        lvls = ([("Usine"), ("Atelier"), ("Ligne"), ("Poste")] if _PF
                else [("Plant"), ("Workshop"), ("Line"), ("Station")])
        lvl = st.selectbox(("Niveau d'agrégation" if _PF else "Aggregation level"), lvls, index=1, key="prod_lvl")
        agg = prod_aggregate(lvl)
        fpc = lambda v: f"{float(v)*100:.1f} %"
        render_table(agg, formats={"D": fpc, "P": fpc, "Q": fpc, "TRS": fpc})
    with gR:
        st.subheader(("Composition par nature" if _PF else "Composition by nature"))
        dcols = st.columns(3)
        _donuts = [
            (N_CONST, pd.DataFrame({
                "part": [("Rebut matière" if _PF else "Scrapped material"), ("Retouches" if _PF else "Rework")],
                "value": [k["constate"] - k["rework_h"] * COUT_HORAIRE_MO,
                          k["rework_h"] * COUT_HORAIRE_MO]}),
             ["#e5484d", "#f4a8aa"]),
            (N_CAPA, mudas[mudas["nature"] == N_CAPA][["muda", "value"]].rename(columns={"muda": "part"}),
             ["#f79009", "#f7c88a", "#fddcab", "#fef0d9", "#fca55d"]),
            (N_CAPI, mudas[mudas["nature"] == N_CAPI][["muda", "value"]].rename(columns={"muda": "part"}),
             ["#6355ff", "#c4b5fd"]),
        ]
        for _dc, (_nat, _df, _pal) in zip(dcols, _donuts):
            with _dc:
                figd = px.pie(_df, values="value", names="part", hole=0.62, color_discrete_sequence=_pal)
                figd.update_traces(sort=False, textinfo="none",
                                   marker=dict(line=dict(color="#ffffff", width=2)),
                                   hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + CURRENCY + "<extra></extra>")
                figd = style_fig(figd, height=210, legend=True)
                figd.update_layout(margin=dict(l=0, r=0, t=4, b=0),
                                   legend=dict(orientation="h", yanchor="top", y=-0.05, x=0.5,
                                               xanchor="center", font=dict(size=9)))
                figd.add_annotation(text=f"<b>{format_currency(float(_df['value'].sum()))}</b>",
                                    x=0.5, y=0.5, showarrow=False,
                                    font=dict(family="Plus Jakarta Sans", size=13,
                                              color=PROD_NATURE_COLOR[_nat]))
                st.caption(_nat)
                st.plotly_chart(figd, use_container_width=True, theme=None, config={"displayModeBar": False})


if _page == P_FLOW:
    st.subheader("🗺️ " + ("Cartographie de flux" if _PF else "Flow map"))
    s, mudas, k = prod_compute()

    # ── Bandeau takt (spec 3.2) ─────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_card(("Demande client" if _PF else "Customer demand"),
            f"{k['demande']:.0f} " + ("pcs/j" if _PF else "pcs/d"), "kpi-info",
            info=("Demande journalière moyenne — le rythme que la ligne doit tenir." if _PF
                  else "Average daily demand — the pace the line must hold.")), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card("Takt", f"{k['takt_s']:.0f} s", "kpi-info",
            info=(f"Ouverture site ({HEURES_OUVERTURE_JOUR:.0f} h) ÷ demande. Une pièce doit sortir toutes les {k['takt_s']:.0f} s." if _PF
                  else f"Site opening ({HEURES_OUVERTURE_JOUR:.0f}h) ÷ demand. One piece must leave every {k['takt_s']:.0f}s.")), unsafe_allow_html=True)
    with c3:
        _pr_cls = "kpi-danger" if k["prod_reelle"] < k["demande"] else "kpi-success"
        st.markdown(kpi_card(("Production réelle" if _PF else "Actual output"),
            f"{k['prod_reelle']:.0f} " + ("pcs/j" if _PF else "pcs/d"), _pr_cls,
            info=("Production journalière constatée sur la campagne, à comparer à la demande." if _PF
                  else "Measured daily output over the campaign, vs demand.")), unsafe_allow_html=True)
    with c4:
        _ot_cls = "kpi-danger" if k["otif"] < 0.90 else ("kpi-warning" if k["otif"] < 0.95 else "kpi-success")
        st.markdown(kpi_card(("OTIF client" if _PF else "Customer OTIF"),
            f"{k['otif']*100:.1f}%", _ot_cls,
            info=("Un beau TRS peut cacher des clients livrés en retard : l'OTIF tranche." if _PF
                  else "A nice OEE can hide late deliveries: OTIF settles it.")), unsafe_allow_html=True)

    st.write("")
    # ── Efficacité de flux détaillée (spec 3.2) ─────────────────────────────
    c1, c2, c3 = st.columns(3)
    _va_lbl = (f"{k['va_s']/60:.1f} min" if k["va_s"] < 3600 else f"{k['va_s']/3600:.1f} h")
    with c1:
        st.markdown(kpi_card(("Lead time total" if _PF else "Total lead time"),
            f"{k['lead_days']:.1f} j ({k['lead_h']:.1f} h)", "kpi-warning",
            info=("Traversée complète d'une pièce, encours compris." if _PF
                  else "Full traversal of one piece, WIP included.")), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card(("Temps à valeur ajoutée" if _PF else "Value-added time"),
            _va_lbl, "kpi-success",
            info=("Le temps pendant lequel la pièce est réellement transformée." if _PF
                  else "Time during which the piece is actually transformed.")), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card(("Efficacité de flux" if _PF else "Flow efficiency"),
            f"{k['flow_eff']*100:.1f}%", "kpi-danger",
            info=("VA ÷ traversée. Entre 1 et 5 % dans une PME non optimisée." if _PF
                  else "VA ÷ lead time. 1–5% in an unoptimised SME.")), unsafe_allow_html=True)

    st.write("")
    st.subheader(("Temps par étape — valeur ajoutée vs non-valeur" if _PF else "Time per step — value-added vs non-value"))
    fl = s.copy()
    fl["nonva"] = (fl["cycle_time_sec"] - fl["value_added_sec"]).clip(lower=0)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=fl["step_name"], y=fl["value_added_sec"],
                         name=("Valeur ajoutée" if _PF else "Value-added"), marker_color="#12b76a"))
    fig.add_trace(go.Bar(x=fl["step_name"], y=fl["nonva"],
                         name=("Non-valeur" if _PF else "Non-value"), marker_color="#cbd5e1"))
    fig = style_fig(fig, height=300, legend=True)
    fig.update_layout(barmode="stack", xaxis_title="", yaxis_title=("Secondes / pièce" if _PF else "Seconds / piece"))
    st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})

    gL, gR = st.columns(2, gap="medium")
    with gL:
        st.subheader(("Cycle effectif vs takt" if _PF else "Effective cycle vs takt"))
        fig2 = px.bar(s, x="step_name", y="eff_cycle", color_discrete_sequence=["#bcd0f5"])
        fig2.add_hline(y=k["takt_s"], line=dict(color="#e5484d", width=1.5, dash="dot"),
                       annotation_text=f"takt {k['takt_s']:.0f}s", annotation_font_color="#e5484d")
        fig2 = style_fig(fig2, height=300)
        fig2.update_layout(showlegend=False, xaxis_title="", yaxis_title=("Cycle effectif (s)" if _PF else "Effective cycle (s)"))
        st.plotly_chart(fig2, use_container_width=True, theme=None, config={"displayModeBar": False})
        st.caption(("Aucun cycle ne dépasse le takt site — et pourtant la ligne sature. C'est le taux de charge, pas le cycle, qui révèle le goulot →" if _PF
                    else "No cycle exceeds site takt — yet the line saturates. Load rate, not cycle time, reveals the bottleneck →"))
    with gR:
        st.subheader(("Goulot par taux de charge" if _PF else "Bottleneck by load rate"))
        ch = s.sort_values("taux_charge")
        _cols = ["#e5484d" if v > 1.0 else ("#f79009" if v > 0.9 else "#bcd0f5") for v in ch["taux_charge"]]
        fig3 = go.Figure(go.Bar(x=ch["taux_charge"] * 100, y=ch["step_name"], orientation="h",
                                marker_color=_cols,
                                hovertemplate="<b>%{y}</b><br>%{x:.0f} %<extra></extra>"))
        fig3.add_vline(x=100, line=dict(color="#0f172a", width=1.5, dash="dot"))
        fig3 = style_fig(fig3, height=300)
        fig3.update_layout(xaxis_title=("Taux de charge (%)" if _PF else "Load rate (%)"), yaxis_title="")
        st.plotly_chart(fig3, use_container_width=True, theme=None, config={"displayModeBar": False})
        st.caption((f"Goulot : {k['goulot']} — {k['goulot_charge']*100:.0f} % de charge (capacité nette : ouverture × machines × disponibilité ÷ cycle)." if _PF
                    else f"Bottleneck: {k['goulot']} — {k['goulot_charge']*100:.0f}% load (net capacity: opening × machines × availability ÷ cycle)."))

    # ── Encours entre opérations (spec 3.2) ─────────────────────────────────
    st.subheader(("Encours entre opérations" if _PF else "WIP between operations"))
    _enc = []
    for i in range(1, len(s)):
        amont, aval = s.iloc[i - 1], s.iloc[i]
        pcs = float(aval["wip_units"])
        _enc.append({
            ("Liaison" if _PF else "Link"): f"{amont['step_name']} → {aval['step_name']}",
            ("Pièces en attente" if _PF else "Waiting pieces"): pcs,
            ("Valeur" if _PF else "Value"): pcs * float(amont["cost_at_step"]),
            ("Attente moyenne (h)" if _PF else "Avg wait (h)"): pcs / k["demande"] * HEURES_OUVERTURE_JOUR,
            ("Couverture (j)" if _PF else "Coverage (d)"): pcs / k["demande"],
        })
    _encdf = pd.DataFrame(_enc)
    _c = _encdf.columns
    render_table(_encdf, formats={_c[1]: lambda v: format_number(v),
                                  _c[2]: lambda v: format_currency(v),
                                  _c[3]: lambda v: f"{float(v):.1f}",
                                  _c[4]: lambda v: f"{float(v):.2f}"})

    st.subheader(("Variabilité par poste" if _PF else "Per-station variability"))
    prod_unavailable(("Nécessite des relevés cycle par cycle (médiane, P90, P95…). "
                      "Disponible dès que la campagne inclut les cycles unitaires." if _PF
                      else "Requires cycle-by-cycle measurements (median, P90, P95…). "
                      "Available once the campaign includes unit cycles."))


if _page == P_MUDA:
    st.subheader("🗑️ " + ("Les huit mudas, quantifiés puis valorisés" if _PF else "The eight wastes, quantified then valued"))
    s, mudas, k = prod_compute()
    prod_natures_note()

    # ── Tableau : quantité physique obligatoire (R1 / spec 3.3) ─────────────
    cQ = ("Quantité physique" if _PF else "Physical quantity")
    cU = ("Unité" if _PF else "Unit")
    cO = "Occurrences"
    cH = ("Heures" if _PF else "Hours")
    cV = ("Impact économique" if _PF else "Economic impact")
    cM = ("Méthode / confiance" if _PF else "Method / confidence")
    tbl = pd.DataFrame({
        "Muda": mudas["muda"], cQ: mudas["qty_label"], cU: mudas["unite"],
        cO: mudas["occurrences"], cH: mudas["heures"], cV: mudas["value"],
        "Nature": mudas["nature"],
        cM: [methode_badge(m, c) for m, c in zip(mudas["methode"], mudas["confiance"])],
    })
    def _nat_style(v):
        col = PROD_NATURE_COLOR.get(str(v), "#64748b")
        return f"color:{col};font-weight:700;"
    render_table(tbl, formats={cO: lambda v: format_number(v),
                               cH: lambda v: (f"{float(v):,.0f}" if float(v) > 0 else "—"),
                               cV: lambda v: format_currency(v)},
                 cell_style={"Nature": _nat_style}, raw_html=[cM])
    st.caption(("Vert = valorisation fine (arbre E1→E6, doctrine terrain). Orange = repli sur "
                "l'absorption globale, faute de charge/capacité rattachées au poste — un montant "
                "★ ne se présente pas comme un montant ★★★." if _PF else
                "Green = fine valuation (E1→E6 tree). Orange = fallback on global absorption, "
                "for lack of station load/capacity — a ★ figure is not presented like a ★★★ one."))

    # ── Bascule d'axe de lecture (spec 3.3) ─────────────────────────────────
    axes = ([("Impact €", "value"), ("Occurrences", "occurrences"),
             ("Heures perdues", "heures"), ("Quantité", "qty")] if _PF else
            [("Impact €", "value"), ("Occurrences", "occurrences"),
             ("Hours lost", "heures"), ("Quantity", "qty")])
    _axn = [a[0] for a in axes]
    _axsel = st.radio(("Axe de lecture" if _PF else "Reading axis"), _axn, horizontal=True, key="muda_axis")
    _axcol = dict(axes)[_axsel]
    m2 = mudas.sort_values(_axcol)
    figm = px.bar(m2, x=_axcol, y="muda", orientation="h", color="nature",
                  color_discrete_map=PROD_NATURE_COLOR, text=_axcol)
    _fmt = "%{text:,.0f} " + CURRENCY if _axcol == "value" else "%{text:,.0f}"
    figm.update_traces(texttemplate=_fmt, textposition="outside", cliponaxis=False)
    figm = style_fig(figm, height=340, legend=True)
    figm.update_layout(xaxis_title="", yaxis_title="",
                       legend=dict(orientation="h", yanchor="bottom", y=-0.2, x=0, font=dict(size=10)))
    st.plotly_chart(figm, use_container_width=True, theme=None, config={"displayModeBar": False})
    st.caption(("Un incident unique à fort impact et une nuée de petits incidents n'appellent pas la même réponse — le Pareto en euros seul masque l'instabilité structurelle." if _PF
                else "One big incident and a swarm of small ones call for different responses — a euro-only Pareto hides structural instability."))

    gL, gR = st.columns(2, gap="medium")
    with gL:
        st.subheader(("Répartition par atelier" if _PF else "By workshop"))
        ws = s.groupby("workshop", as_index=False).agg(
            constate=("m_defauts", "sum"), capacite=("m_capacite", "sum"), capital=("m_stocks", "sum"))
        figw = go.Figure()
        figw.add_trace(go.Bar(x=ws["workshop"], y=ws["constate"], name=N_CONST, marker_color=PROD_NATURE_COLOR[N_CONST]))
        figw.add_trace(go.Bar(x=ws["workshop"], y=ws["capacite"], name=N_CAPA, marker_color=PROD_NATURE_COLOR[N_CAPA]))
        figw.add_trace(go.Bar(x=ws["workshop"], y=ws["capital"], name=N_CAPI, marker_color=PROD_NATURE_COLOR[N_CAPI]))
        figw = style_fig(figw, height=300, legend=True)
        figw.update_layout(barmode="group", xaxis_title="", yaxis_title=CURRENCY,
                           legend=dict(orientation="h", yanchor="bottom", y=-0.35, x=0, font=dict(size=9.5)))
        st.plotly_chart(figw, use_container_width=True, theme=None, config={"displayModeBar": False})
        st.caption(("Surproduction et compétences sont des grandeurs de ligne, non ventilées par atelier." if _PF
                    else "Overproduction and skills are line-level figures, not split by workshop."))
    with gR:
        st.subheader(("Matrice Impact × Effort" if _PF else "Impact × Effort matrix"))
        figx = px.scatter(mudas, x="effort", y="evitable", color="nature", text="muda",
                          color_discrete_map=PROD_NATURE_COLOR, size="value", size_max=38)
        figx.update_traces(textposition="top center", textfont=dict(size=10))
        figx = style_fig(figx, height=300, legend=False)
        figx.update_layout(xaxis_title=("Effort (1 = facile → 5 = lourd)" if _PF else "Effort (1 = easy → 5 = heavy)"),
                           yaxis_title=("Part évitable (€)" if _PF else "Avoidable share (€)"),
                           xaxis=dict(range=[0.5, 5.5]))
        st.plotly_chart(figx, use_container_width=True, theme=None, config={"displayModeBar": False})

    # ── Chaîne de récupérabilité (spec 3.3) ─────────────────────────────────
    st.subheader(("Récupérabilité" if _PF else "Recoverability"))
    cI = ("Impact identifié" if _PF else "Identified impact")
    cE = ("Part techniquement évitable" if _PF else "Technically avoidable")
    cOb = ("Objectif retenu" if _PF else "Committed target")
    cG = ("Gain constaté" if _PF else "Measured gain")
    rec = pd.DataFrame({"Muda": mudas["muda"], "Nature": mudas["nature"],
                        cI: mudas["value"], cE: mudas["evitable"], cOb: mudas["objectif"],
                        cG: ["—"] * len(mudas)})
    render_table(rec, formats={cI: lambda v: format_currency(v), cE: lambda v: format_currency(v),
                               cOb: lambda v: format_currency(v)},
                 cell_style={"Nature": _nat_style})
    st.caption(("Le gain constaté se mesure à la campagne suivante — il alimente le taux de réalisation du Suivi." if _PF
                else "Measured gain comes from the next campaign — it feeds the realisation rate in Tracking."))

    st.subheader(("Pareto des causes racines" if _PF else "Root-cause Pareto"))
    prod_unavailable(("Nécessite la codification des causes (cause_code) sur les événements terrain. "
                      "L'écran s'activera dès que la codification est en place chez le client." if _PF
                      else "Requires cause coding (cause_code) on field events. "
                      "This screen activates once cause coding is in place."))


if _page == P_POSTE:
    st.subheader("🏭 " + ("Détail par poste" if _PF else "By workstation"))
    s, mudas, k = prod_compute()

    d = s.copy()
    _comps = d.apply(lambda r: composante_dominante(r["availability_rate"], r["performance_rate"], r["quality_rate"]), axis=1)
    d["comp_nom"] = [c[0] for c in _comps]
    d["comp_txt"] = [f"{c[0]} — {c[1]:.1f} pts" for c in _comps]

    cP = ("Poste" if _PF else "Station"); cA = ("Atelier" if _PF else "Workshop")
    cD, cPe, cQ2 = ("Dispo." if _PF else "Avail."), "Perf.", ("Qualité" if _PF else "Quality")
    cCh = ("Charge" if _PF else "Load")
    cC1, cC2, cC3 = ("Constaté €" if _PF else "Booked €"), ("Capacité €" if _PF else "Capacity €"), ("Capital €" if _PF else "Capital €")
    cCo = ("Composante à traiter" if _PF else "Component to address")
    tbl = pd.DataFrame({
        cP: d["step_name"], cA: d["workshop"],
        cD: d["availability_rate"], cPe: d["performance_rate"], cQ2: d["quality_rate"],
        "TRS": d["trs"], cCh: d["taux_charge"],
        cC1: d["m_defauts"], cC2: d["m_capacite"], cC3: d["m_stocks"],
        cCo: d["comp_txt"],
    })
    fpc = lambda v: f"{float(v)*100:.0f}%"
    def _comp_style(v):
        sv = str(v)
        if sv.startswith(("Disponibilité", "Availability")):
            return "background:#fdecec;color:#b42318;font-weight:700;"
        if sv.startswith("Performance"):
            return "background:#fef3e2;color:#a15c07;font-weight:700;"
        return "background:#eaf1fe;color:#1d4ed8;font-weight:700;"
    def _charge_style(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        if f > 1.0:
            return "background:#fdecec;color:#b42318;font-weight:700;"
        if f > 0.9:
            return "background:#fef3e2;color:#a15c07;font-weight:600;"
        return ""
    render_table(tbl, formats={cD: fpc, cPe: fpc, cQ2: fpc, "TRS": fpc, cCh: fpc,
                               cC1: lambda v: format_currency(v),
                               cC2: lambda v: format_currency(v),
                               cC3: lambda v: format_currency(v)},
                 cell_style={cCo: _comp_style, cCh: _charge_style})
    _lg = "".join(f'<div style="margin:3px 0;"><b style="color:#334155;">{c}</b> — {p}</div>' for c, p in PISTES.items())
    st.markdown('<div style="background:#f8f9fc;border:1px solid rgba(15,23,42,0.06);border-radius:10px;'
                'padding:10px 14px;font-size:11.5px;color:#64748b;margin:4px 0 14px;">'
                + ("🧭 <b>Pistes d'investigation</b> (aucune cause n'est établie sans vérification terrain) :"
                   if _PF else "🧭 <b>Investigation leads</b> (no cause is established without floor verification):")
                + _lg + '</div>', unsafe_allow_html=True)

    st.subheader(("TRS décomposé par poste" if _PF else "OEE decomposed by station"))
    figd = go.Figure()
    figd.add_trace(go.Bar(x=d["step_name"], y=d["availability_rate"] * 100, name=cD, marker_color="#bcd0f5"))
    figd.add_trace(go.Bar(x=d["step_name"], y=d["performance_rate"] * 100, name="Perf.", marker_color="#8b7cff"))
    figd.add_trace(go.Bar(x=d["step_name"], y=d["quality_rate"] * 100, name=cQ2, marker_color="#12b76a"))
    figd = style_fig(figd, height=280, legend=True)
    figd.update_layout(barmode="group", xaxis_title="", yaxis_title="%")
    st.plotly_chart(figd, use_container_width=True, theme=None, config={"displayModeBar": False})

    # ── Simulateur de points de TRS récupérables (spec 3.4) ─────────────────
    st.subheader("🎚️ " + ("Simulateur de points de TRS récupérables" if _PF else "Recoverable OEE points simulator"))
    simL, simR = st.columns(2, gap="large")
    with simL:
        psel = st.selectbox(("Poste" if _PF else "Station"), list(d["step_name"]), key="trs_sim_poste")
        r = d[d["step_name"] == psel].iloc[0]
        comp, ecart = composante_dominante(r["availability_rate"], r["performance_rate"], r["quality_rate"])
        _map = {("Disponibilité" if _PF else "Availability"): "availability_rate",
                "Performance": "performance_rate",
                ("Qualité" if _PF else "Quality"): "quality_rate"}
        cur = float(r[_map[comp]])
        st.markdown((f"Composante dominante : **{comp}** ({cur*100:.0f} % — écart {ecart:.1f} pts)" if _PF
                     else f"Dominant component: **{comp}** ({cur*100:.0f}% — gap {ecart:.1f} pts)"))
        target = st.slider((f"{comp} cible" if _PF else f"Target {comp}"),
                           min_value=float(round(cur * 100)), max_value=min(99.0, float(round(cur * 100)) + 20.0),
                           value=min(99.0, float(round(cur * 100)) + 10.0), step=1.0, key="trs_sim_target") / 100.0
        vals = {"availability_rate": float(r["availability_rate"]),
                "performance_rate": float(r["performance_rate"]),
                "quality_rate": float(r["quality_rate"])}
        trs_old = vals["availability_rate"] * vals["performance_rate"] * vals["quality_rate"]
        vals[_map[comp]] = target
        trs_new = vals["availability_rate"] * vals["performance_rate"] * vals["quality_rate"]
        freed_h = float(r["temps_requis_h"]) * (trs_new - trs_old)
        pot = freed_h * float(r["machine_hourly_cost"] if r["machine_hourly_cost"] > 0 else COUT_HORAIRE_MACHINE)
        real = pot * TAUX_ABSORPTION_DEMANDE
    with simR:
        st.markdown(kpi_card(("TRS théorique" if _PF else "Theoretical OEE"),
            f"{trs_new*100:.1f}% (+{(trs_new-trs_old)*100:.1f} pts)", _trs_class(trs_new)), unsafe_allow_html=True)
        st.markdown(kpi_card(("Capacité libérée" if _PF else "Freed capacity"),
            f"{freed_h:,.0f} h/an", "kpi-info",
            info=("Heures utiles supplémentaires = temps requis × Δ TRS." if _PF
                  else "Extra useful hours = required time × Δ OEE.")), unsafe_allow_html=True)
        st.markdown(kpi_card(("Valeur potentielle (capacité)" if _PF else "Potential value (capacity)"),
            format_currency(pot), "",
            info=("Une capacité, pas un gain : elle ne vaut que si la demande l'absorbe." if _PF
                  else "A capacity, not a gain: worth money only if demand absorbs it.")), unsafe_allow_html=True)
        st.markdown(kpi_card((f"Valeur réalisable (hypothèse d'absorption {TAUX_ABSORPTION_DEMANDE*100:.0f} %)" if _PF
                              else f"Realisable value (absorption assumption {TAUX_ABSORPTION_DEMANDE*100:.0f}%)"),
            format_currency(real), "kpi-success"), unsafe_allow_html=True)

    # ── Simulateur SMED (spec 3.4) ──────────────────────────────────────────
    st.subheader("⚙️ " + ("Simulateur SMED" if _PF else "SMED simulator"))
    smL, smR = st.columns(2, gap="large")
    with smL:
        ps2 = st.selectbox(("Poste" if _PF else "Station"), list(d["step_name"]), index=1, key="smed_poste")
        r2 = d[d["step_name"] == ps2].iloc[0]
        chg, nchg = float(r2["changeover_min"]), float(r2["nb_changements_an"])
        st.markdown((f"Changement actuel : **{chg:.0f} min** × **{nchg:,.0f} changements/an**" if _PF
                     else f"Current changeover: **{chg:.0f} min** × **{nchg:,.0f} changeovers/yr**"))
        obj = st.radio(("Objectif" if _PF else "Target"),
                       ["−30 %", "−50 %", ("Personnalisé" if _PF else "Custom")],
                       horizontal=True, key="smed_obj")
        red = {"−30 %": 0.30, "−50 %": 0.50}.get(obj)
        if red is None:
            red = st.slider(("Réduction (%)" if _PF else "Reduction (%)"), 10, 80, 40, 5, key="smed_pct") / 100.0
        freed2 = nchg * (chg * red) / 60.0
        pot2 = freed2 * float(r2["poste_hourly"])
        real2 = pot2 * TAUX_ABSORPTION_DEMANDE
    with smR:
        st.markdown(kpi_card(("Capacité libérée" if _PF else "Freed capacity"),
            f"{freed2:,.0f} h/an", "kpi-info"), unsafe_allow_html=True)
        st.markdown(kpi_card(("Valeur potentielle (capacité)" if _PF else "Potential value (capacity)"),
            format_currency(pot2), "",
            info=("Une capacité, pas un gain." if _PF else "A capacity, not a gain.")), unsafe_allow_html=True)
        st.markdown(kpi_card((f"Valeur réalisable (hypothèse d'absorption {TAUX_ABSORPTION_DEMANDE*100:.0f} %)" if _PF
                              else f"Realisable value (absorption assumption {TAUX_ABSORPTION_DEMANDE*100:.0f}%)"),
            format_currency(real2), "kpi-success"), unsafe_allow_html=True)


if _page == P_ACTIONS:
    st.subheader("📋 " + ("Plan d'actions" if _PF else "Action plan"))
    s, mudas, k = prod_compute()
    st.caption(("L'écran qui fait passer du diagnostic au pilotage : il est saisi et tenu, pas calculé. "
                "Chaque écart du Suivi se rattache à une action décidée ici." if _PF
                else "The screen that turns diagnosis into steering: it is entered and maintained, not computed. "
                "Every Tracking delta ties back to an action decided here."))

    cAc = ("Action" if _PF else "Action"); cPo = ("Poste" if _PF else "Station")
    cMu = "Muda"; cCa = ("Cause" if _PF else "Cause")
    cPot = ("Potentiel accessible" if _PF else "Accessible potential")
    cObj = ("Objectif retenu" if _PF else "Committed target")
    cRe = ("Responsable" if _PF else "Owner"); cEc = ("Échéance" if _PF else "Due")
    cSt = ("Statut" if _PF else "Status"); cGa = ("Gain constaté" if _PF else "Measured gain")
    cDc = ("Date de constat" if _PF else "Measured on")
    _statuts = PROD_STATUTS_UI
    _muda_ui2key = dict(zip(mudas["muda"], mudas["key"]))
    _muda_key2ui = dict(zip(mudas["key"], mudas["muda"]))
    _poste2id, _id2poste = _prod_poste_map()

    _db = prod_actions_load()
    # Un tableau sans la colonne 'libelle' (table absente, lecture dégradée) ne doit
    # pas être traité comme une source valide — sinon KeyError à l'affichage.
    _from_db = _db is not None and "libelle" in getattr(_db, "columns", [])
    _EMPTY = pd.DataFrame(columns=[cAc, cPo, cMu, cCa, cPot, cObj, cRe, cEc, cSt, cGa, cDc])

    if _from_db:
        # Base -> affichage : les clés techniques deviennent des libellés lisibles.
        view_df = pd.DataFrame({
            cAc: _db["libelle"],
            cPo: _db["poste_id"].map(lambda v: _id2poste.get(v, "—") if pd.notna(v) else "—"),
            cMu: _db["type_muda"].map(lambda v: _muda_key2ui.get(v, v if pd.notna(v) else "")),
            cCa: _db["cause_code"].fillna(""),
            cPot: pd.to_numeric(_db["potentiel_accessible"], errors="coerce"),
            cObj: pd.to_numeric(_db["objectif_retenu"], errors="coerce"),
            cRe: _db["responsable"].fillna(""),
            cEc: pd.to_datetime(_db["echeance"], errors="coerce"),
            cSt: _db["statut"].map(lambda v: _ST_DB2UI.get(v, _statuts[0])),
            cGa: pd.to_numeric(_db["gain_constate"], errors="coerce"),
            cDc: pd.to_datetime(_db["date_constat"], errors="coerce"),
        })
        _src_txt, _src_col = ((f"{len(view_df)} action(s) en base" if _PF
                               else f"{len(view_df)} action(s) in database"), "#12b76a")
    else:
        # R6 : pas de table -> plan de travail local, non persistant, dit clairement.
        if "prod_actions_local" not in st.session_state:
            st.session_state["prod_actions_local"] = _EMPTY.copy()
        view_df = st.session_state["prod_actions_local"]
        _src_txt, _src_col = (("Tables prod_* absentes — saisie locale non conservée" if _PF
                               else "prod_* tables absent — local entry, not persisted"), "#94a3b8")

    _wr = prod_actions_writable()
    _readonly = _from_db and not _wr      # base sans secrets d'écriture -> consultation
    _mode = (("écriture activée" if _PF else "write enabled") if (_from_db and _wr)
             else ("lecture seule" if _PF else "read-only"))
    st.markdown(f'<div style="font-size:11.5px;color:{_src_col};margin:-4px 0 10px;">'
                f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
                f'background:{_src_col};margin-right:6px;"></span>{_src_txt} · {_mode}</div>',
                unsafe_allow_html=True)

    edited = st.data_editor(
        view_df, num_rows="dynamic", use_container_width=True, key="prod_actions_editor",
        disabled=_readonly,
        column_config={
            cAc: st.column_config.TextColumn(cAc, width="large", required=True),
            cSt: st.column_config.SelectboxColumn(cSt, options=_statuts),
            cPo: st.column_config.SelectboxColumn(cPo, options=["—"] + list(s["step_name"])),
            cMu: st.column_config.SelectboxColumn(cMu, options=list(mudas["muda"])),
            cPot: st.column_config.NumberColumn(cPot, format="%.0f €"),
            cObj: st.column_config.NumberColumn(cObj, format="%.0f €"),
            cGa: st.column_config.NumberColumn(cGa, format="%.0f €"),
            cEc: st.column_config.DateColumn(cEc, format="DD/MM/YYYY"),
            cDc: st.column_config.DateColumn(cDc, format="DD/MM/YYYY"),
        })
    if not _from_db:
        st.session_state["prod_actions_local"] = edited

    # ── Enregistrement en base ──────────────────────────────────────────────
    bcol1, bcol2, _bsp = st.columns([1.4, 1.4, 3])
    with bcol1:
        _save = st.button(("💾 Enregistrer en base" if _PF else "💾 Save to database"),
                          use_container_width=True, disabled=not (_from_db and _wr))
    with bcol2:
        st.download_button(("⬇️ Exporter (CSV)" if _PF else "⬇️ Export (CSV)"),
                           data=edited.to_csv(index=False).encode("utf-8-sig"),
                           file_name="plan_actions_production.csv", mime="text/csv",
                           use_container_width=True)

    if _save:
        _rows, _bad = [], False
        for _, r in edited.iterrows():
            lib = str(r[cAc] or "").strip()
            if not lib:
                _bad = True
                continue
            _num = lambda v: (None if pd.isna(v) else float(v))
            _dat = lambda v: (None if pd.isna(v) else pd.to_datetime(v).date())
            _rows.append(dict(
                libelle=lib,
                poste_id=_poste2id.get(str(r[cPo]), None),
                type_muda=_muda_ui2key.get(str(r[cMu]), None),
                cause_code=(str(r[cCa]).strip() or None),
                potentiel_accessible=_num(r[cPot]), objectif_retenu=_num(r[cObj]),
                gain_constate=_num(r[cGa]),
                responsable=(str(r[cRe]).strip() or None),
                echeance=_dat(r[cEc]), statut=_ST_UI2DB.get(str(r[cSt]), "a_lancer"),
                date_constat=_dat(r[cDc])))
        okw, err = prod_actions_save(_rows)
        if okw:
            prod_actions_load.clear()
            msg = (f"✅ {len(_rows)} action(s) enregistrée(s)." if _PF
                   else f"✅ {len(_rows)} action(s) saved.")
            if _bad:
                msg += (" Lignes sans libellé ignorées." if _PF else " Rows without a label were skipped.")
            alert_box("success", msg)
            st.rerun()
        else:
            alert_box("error", ("❌ Échec de l'enregistrement : " if _PF else "❌ Save failed: ") + _esc(str(err)))

    if _from_db and not _wr:
        st.caption(("Édition en base désactivée : ajoutez supabase_actions_user et "
                    "supabase_actions_password dans les secrets Streamlit (rôle créé par "
                    "la partie 8 de production_backend_v2.sql)." if _PF else
                    "Database editing disabled: add supabase_actions_user and "
                    "supabase_actions_password to the Streamlit secrets (role created by "
                    "part 8 of production_backend_v2.sql)."))

    # ── Filtres + indicateurs de tenue du plan ──────────────────────────────
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        fst = st.multiselect(cSt, _statuts, default=[], key="fa_st")
    with fc2:
        fre = st.multiselect(cRe, sorted(str(x) for x in edited[cRe].dropna().unique() if str(x).strip()), default=[], key="fa_re")
    with fc3:
        fpo = st.multiselect(cPo, sorted(str(x) for x in edited[cPo].dropna().unique() if str(x).strip()), default=[], key="fa_po")
    view = edited.copy()
    if fst:
        view = view[view[cSt].isin(fst)]
    if fre:
        view = view[view[cRe].astype(str).isin(fre)]
    if fpo:
        view = view[view[cPo].astype(str).isin(fpo)]

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(kpi_card(("Actions au plan" if _PF else "Actions in plan"),
            format_number(len(view)), "kpi-info"), unsafe_allow_html=True)
    with m2:
        st.markdown(kpi_card(("En cours" if _PF else "In progress"),
            format_number(int((view[cSt] == _statuts[1]).sum())), "kpi-warning"), unsafe_allow_html=True)
    with m3:
        _obj_sum = pd.to_numeric(view[cObj], errors="coerce").fillna(0).sum()
        st.markdown(kpi_card(cObj, format_currency(_obj_sum), "kpi-capital",
            info=("Somme des objectifs saisis — l'engagement pris avec le client." if _PF
                  else "Sum of committed targets — the promise made with the client.")), unsafe_allow_html=True)
    with m4:
        _gain_sum = pd.to_numeric(view[cGa], errors="coerce").fillna(0).sum()
        _taux = (_gain_sum / _obj_sum * 100) if _obj_sum else 0
        st.markdown(kpi_card(cGa, format_currency(_gain_sum), "kpi-success",
            delta=(f"{_taux:.0f} % " + ("de l'objectif" if _PF else "of target")) if _obj_sum else "",
            delta_color="#12b76a",
            info=("Se remplit au constat des campagnes suivantes — c'est le taux de réalisation du plan." if _PF
                  else "Filled as the next campaigns are measured — this is the plan's realisation rate.")), unsafe_allow_html=True)


if _page == P_AI:
    st.subheader("🤖 " + ("Analyste production industrielle" if _PF else "Industrial production analyst"))
    st.caption(("Posez vos questions sur le TRS, les gaspillages, le goulot, le flux et le plan d'actions en langage naturel." if _PF
                else "Ask about OEE, wastes, the bottleneck, flow and the action plan in natural language."))

    if not _prod_backend_ready():
        prod_unavailable(("L'assistant interroge les tables de production (prod_*). "
                          "Il s'activera dès que production_backend_v2.sql et une campagne de mesure "
                          "seront chargés dans la base." if _PF else
                          "The assistant queries the production tables (prod_*). It activates once "
                          "production_backend_v2.sql and a measurement campaign are loaded."))
    else:
        for _k, _v in [("prod_ai_messages", []), ("prod_processed_ids", set()),
                       ("prod_next_question", None), ("prod_next_question_id", None)]:
            if _k not in st.session_state:
                st.session_state[_k] = _v

        st.markdown('<div style="font-size:13px;font-weight:700;margin:2px 0 8px;">'
                    + ("Essayez de demander" if _PF else "Try asking") + '</div>', unsafe_allow_html=True)
        sug_cols = st.columns(4)
        suggestions = ([
            "Où part le cash sur ma ligne, et sous quelle nature économique ?",
            "Quel est mon goulot réel et pourquoi ce poste-là ?",
            "Pourquoi mon TRS ligne est-il sous 70 % — quelle composante traiter ?",
            "Quelles actions du plan ont le plus fort potentiel accessible ?",
        ] if _PF else [
            "Where does cash burn on my line, and under which economic nature?",
            "What is my real bottleneck and why that station?",
            "Why is my line OEE below 70% — which component to address?",
            "Which plan actions have the highest accessible potential?",
        ])
        for i, sug in enumerate(suggestions):
            with sug_cols[i]:
                if st.button(sug, key=f"prod_sug_{i}", use_container_width=True):
                    st.session_state.prod_next_question = sug
                    st.session_state.prod_next_question_id = str(uuid.uuid4())

        for msg in st.session_state.prod_ai_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["display"], unsafe_allow_html=True)
                for _sql, df in msg.get("dataframes", []):
                    with st.expander(T["ai_see_data"]):
                        render_table(df, index=True, height=300)

        q = st.session_state.prod_next_question
        qid = st.session_state.prod_next_question_id
        already_done = qid in st.session_state.prod_processed_ids if qid else True

        if q and qid and not already_done:
            st.session_state.prod_processed_ids.add(qid)
            st.session_state.prod_ai_messages.append({"role": "user", "display": q, "dataframes": [], "id": qid})
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                placeholder = st.empty()
                history = [{"role": m["role"], "content": m["display"]}
                           for m in st.session_state.prod_ai_messages[:-1]]
                try:
                    answer, dataframes = ask_claude(q, history, text_placeholder=placeholder,
                                                    system_prompt=PROD_SYSTEM_PROMPT)
                except Exception as e:
                    answer = f"⚠️ {e}"
                    dataframes = []
                    placeholder.markdown(answer)
                for _sql, df in dataframes:
                    with st.expander(T["ai_see_data"]):
                        render_table(df, index=True, height=300)
            st.session_state.prod_ai_messages.append(
                {"role": "assistant", "display": answer, "dataframes": dataframes, "id": qid})
            st.session_state.prod_next_question = None
            st.session_state.prod_next_question_id = None

        with st.form("prod_ai_form", clear_on_submit=True):
            col_in, col_btn = st.columns([6, 1])
            with col_in:
                user_input = st.text_input(
                    T["ai_placeholder"], key="prod_ai_input", label_visibility="collapsed",
                    placeholder=("Posez une question sur votre production…" if _PF
                                 else "Ask a question about your production…"))
            with col_btn:
                submitted = st.form_submit_button(T["ai_send"], use_container_width=True)
        if submitted and user_input:
            st.session_state.prod_next_question = user_input
            st.session_state.prod_next_question_id = str(uuid.uuid4())
            st.rerun()

        if st.session_state.prod_ai_messages:
            if st.button(T["ai_clear"], key="prod_ai_clear"):
                st.session_state.prod_ai_messages = []
                st.session_state.prod_processed_ids = set()
                st.session_state.prod_next_question = None
                st.session_state.prod_next_question_id = None
                st.rerun()


if _page == P_SUIVI:
    st.subheader("📈 " + ("Suivi des campagnes de mesure" if _PF else "Measurement campaigns tracking"))
    s, mudas, k = prod_compute()
    st.caption(("Projection illustrative sur une campagne unique — le suivi réel s'alimente des campagnes chargées et des actions clôturées." if _PF
                else "Illustrative projection from a single campaign — real tracking feeds on loaded campaigns and closed actions."))

    camps = ["T1 2026", "T2 2026", "T3 2026", "T4 2026"]
    fc_ = [1.00, 0.90, 0.80, 0.73]
    fa_ = [1.00, 0.95, 0.86, 0.79]
    fi_ = [1.00, 0.92, 0.85, 0.80]
    dD = [0.0, 0.03, 0.055, 0.08]
    dP = [0.0, 0.01, 0.025, 0.04]
    dQ = [0.0, 0.004, 0.007, 0.01]
    camp = pd.DataFrame({
        "campagne": camps,
        N_CONST: [k["constate"] * f for f in fc_],
        N_CAPA: [k["capacite"] * f for f in fa_],
        N_CAPI: [k["capital"] * f for f in fi_],
        "D": [min(0.99, k["d_l"] + x) for x in dD],
        "P": [min(0.99, k["p_l"] + x) for x in dP],
        "Q": [min(0.999, k["q_l"] + x) for x in dQ],
    })
    camp["TRS"] = camp["D"] * camp["P"] * camp["Q"]

    # R4 : cartes par nature — « Impact économique identifié » & « Impact réduit vs référence »
    c1, c2, c3, c4 = st.columns(4)
    _cards = [(N_CONST, "kpi-danger"), (N_CAPA, "kpi-warning"), (N_CAPI, "kpi-capital")]
    for _cc, (_nat, _cls) in zip([c1, c2, c3], _cards):
        with _cc:
            last, first = float(camp[_nat].iloc[-1]), float(camp[_nat].iloc[0])
            dd = _delta_txt((last - first) / first * 100 if first else None)
            st.markdown(kpi_card(_nat + (" — identifié" if _PF else " — identified"),
                format_currency(last), _cls, delta=dd[0], delta_color=dd[1],
                info=("Impact économique identifié sur la dernière campagne ; la variation est un impact réduit vs référence, pas un gain encaissé." if _PF
                      else "Identified economic impact on the latest campaign; the delta is impact reduced vs baseline, not banked profit.")), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card(("TRS — dernière campagne" if _PF else "OEE — latest campaign"),
            f"{camp['TRS'].iloc[-1]*100:.1f}%", _trs_class(camp["TRS"].iloc[-1])), unsafe_allow_html=True)

    st.write("")
    gL, gR = st.columns(2, gap="medium")
    with gL:
        st.subheader(("Impact par campagne, par nature" if _PF else "Impact per campaign, by nature"))
        figc = go.Figure()
        for nat in [N_CONST, N_CAPA, N_CAPI]:
            figc.add_trace(go.Bar(x=camp["campagne"], y=camp[nat], name=nat,
                                  marker_color=PROD_NATURE_COLOR[nat]))
        figc = style_fig(figc, height=300, legend=True)
        figc.update_layout(barmode="group", xaxis_title="", yaxis_title=CURRENCY,
                           legend=dict(orientation="h", yanchor="bottom", y=-0.35, x=0, font=dict(size=9.5)))
        st.plotly_chart(figc, use_container_width=True, theme=None, config={"displayModeBar": False})
    with gR:
        st.subheader(("Évolution du TRS pondéré" if _PF else "Weighted OEE trend"))
        figt = go.Figure()
        figt.add_trace(go.Scatter(x=camp["campagne"], y=camp["TRS"] * 100, mode="lines+markers",
                                  line=dict(color="#12b76a", width=2.5), marker=dict(size=8, color="#12b76a"),
                                  fill="tozeroy", fillcolor="rgba(18,183,106,0.10)"))
        figt = style_fig(figt, height=300)
        figt.update_layout(yaxis=dict(range=[0, 100]), xaxis_title="", yaxis_title="TRS %")
        st.plotly_chart(figt, use_container_width=True, theme=None, config={"displayModeBar": False})

    # ── Décomposition D/P/Q entre première et dernière campagne (spec 3.6) ──
    st.subheader(("Pourquoi le TRS a bougé — décomposition D / P / Q" if _PF else "Why OEE moved — D / P / Q decomposition"))
    _acts = {("Disponibilité" if _PF else "Availability"):
                 ("SMED Tournage · maintenance préventive Fraisage" if _PF else "Turning SMED · milling preventive maintenance"),
             "Performance": ("standard opératoire Ébavurage" if _PF else "Deburring work standard"),
             ("Qualité" if _PF else "Quality"): ("réduction rebut Tournage" if _PF else "Turning scrap reduction"),
             "TRS": "—"}
    dec = pd.DataFrame({
        ("Composante" if _PF else "Component"): [("Disponibilité" if _PF else "Availability"), "Performance",
                                                 ("Qualité" if _PF else "Quality"), "TRS"],
        camps[0]: [camp["D"].iloc[0], camp["P"].iloc[0], camp["Q"].iloc[0], camp["TRS"].iloc[0]],
        camps[-1]: [camp["D"].iloc[-1], camp["P"].iloc[-1], camp["Q"].iloc[-1], camp["TRS"].iloc[-1]],
        ("Écart" if _PF else "Delta"): [(camp["D"].iloc[-1] - camp["D"].iloc[0]),
                                        (camp["P"].iloc[-1] - camp["P"].iloc[0]),
                                        (camp["Q"].iloc[-1] - camp["Q"].iloc[0]),
                                        (camp["TRS"].iloc[-1] - camp["TRS"].iloc[0])],
        ("Actions du plan rattachées" if _PF else "Linked plan actions"): list(_acts.values()),
    })
    _cd = dec.columns
    render_table(dec, formats={_cd[1]: lambda v: f"{float(v)*100:.1f} %",
                               _cd[2]: lambda v: f"{float(v)*100:.1f} %",
                               _cd[3]: lambda v: f"+{float(v)*100:.1f} pts" if float(v) >= 0 else f"{float(v)*100:.1f} pts"})


# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #94a3b8; font-size: 12px;">'
    f'Industrial Supply Chain Intelligence · {CLIENT_NAME} · Powered by SupplyStack · '
    f'{datetime.now().strftime("%d/%m/%Y %H:%M")}'
    '</p>',
    unsafe_allow_html=True,
)
