"""
SupplyStack — Industrial Supply Chain Intelligence Engine
Streamlit Dashboard for MECAPRO and future industrial clients
"""

import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# ═══════════════════════════════════════════════════════════════════════════
# CLIENT CONFIGURATION — change these two variables per client
# ═══════════════════════════════════════════════════════════════════════════
CLIENT_MODE = "industrial"    # "industrial" or "dtc"
CLIENT_LANG = "fr"             # "fr" or "en"
CLIENT_NAME = "MECAPRO Industries"


# ═══════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title=f"SupplyStack — {CLIENT_NAME}",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ═══════════════════════════════════════════════════════════════════════════
DB_CONFIG = {
    "host": "aws-0-eu-central-1.pooler.supabase.com",
    "port": 6543,
    "database": "postgres",
    "user": "postgres.aporcwacoxablxtuhndz",
    "password": st.secrets["supabase_mecapro_password"],
    "sslmode": "require",
    "connect_timeout": 15,
    "options": "-c statement_timeout=8000",
}


@st.cache_resource
def get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


@st.cache_data(ttl=300)
def run_query(query):
    conn = get_connection()
    try:
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        st.cache_resource.clear()
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# CONNECTION TEST
# ═══════════════════════════════════════════════════════════════════════════
st.title(f"🏭 {CLIENT_NAME}")
st.caption(f"Mode: {CLIENT_MODE} | Lang: {CLIENT_LANG}")

st.header("Connection test")

test = run_query("SELECT COUNT(*) as inv FROM inventory;")
st.write(test)

test2 = run_query("SELECT COUNT(*) as mvt FROM stock_movements;")
st.write(test2)

test3 = run_query("SELECT COUNT(*) as pos FROM purchase_orders;")
st.write(test3)

test4 = run_query("SELECT COUNT(*) as ord FROM orders;")
st.write(test4)

kpi = run_query("SELECT * FROM daily_kpis_industrial WHERE kpi_date = CURRENT_DATE;")
st.write("KPI snapshot du jour:")
st.dataframe(kpi)
