"""
SupplyStack — Supply Chain Intelligence Engine
Streamlit Dashboard + AI Assistant
Connects to Supabase Postgres. All data reads from the same DB that n8n writes to.

── UI: "Aurora" light theme ──────────────────────────────────────────────────
Airy violet-accented light theme. KPI cards carry a status dot + traffic-light
value color + day-over-day delta + sparkline. Charts restyled to the Aurora
palette; warehouse mix shown as a donut; Executive tab uses a 2:1 layout with an
Aurora right rail (AI insight, recent alerts, reorder recommendations).
Only presentation changed — all DB queries and AI logic are unchanged.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import psycopg2
import re
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SupplyStack — Supply Chain Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CREDENTIALS ───────────────────────────────────────────────────────────────
# Replace these two values with your own

DB_CONFIG = {
    "host": "aws-1-eu-central-1.pooler.supabase.com",
    "port": 5432,
    "database": "postgres",
    "user": "postgres.wnwuaeuifcdxncdbhjrj",
    "password": st.secrets["supabase_password"],
    "sslmode": "require", "connect_timeout": 30,
}

ANTHROPIC_API_KEY = st.secrets["anthropic_api_key"]


# ── SUPABASE CONNECTION ───────────────────────────────────────────────────────

@st.cache_resource
def get_connection():
    """Create a persistent database connection."""
    return psycopg2.connect(**DB_CONFIG)


@st.cache_data(ttl=300)
def run_query(query):
    """Execute a SQL query and return results as a DataFrame."""
    conn = get_connection()
    try:
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        st.cache_resource.clear()
        return pd.DataFrame()


def run_query_uncached(query):
    """Execute a SQL query without caching (used by AI assistant)."""
    conn = get_connection()
    try:
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.cache_resource.clear()
        raise e


# ── AURORA THEME / STYLING ────────────────────────────────────────────────────
# Palette
#   canvas   #f5f6fb   card #ffffff   ink #0f172a   muted #64748b / #94a3b8
#   primary  #6355ff (violet)         gridlines #eef0f6
#   status   danger #e5484d  warning #f79009  success #12b76a  info #3b82f6

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

    /* Headings */
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
    .kpi-value { font-size: 27px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.05; }
    .kpi-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
    .kpi-delta { font-size: 12px; font-weight: 700; }

    /* status colors */
    .kpi-danger  .kpi-dot { background: #e5484d; } .kpi-danger  .kpi-value { color: #e5484d; }
    .kpi-warning .kpi-dot { background: #f79009; } .kpi-warning .kpi-value { color: #f79009; }
    .kpi-success .kpi-dot { background: #12b76a; } .kpi-success .kpi-value { color: #12b76a; }
    .kpi-info    .kpi-dot { background: #3b82f6; } .kpi-info    .kpi-value { color: #0f172a; }
    .kpi-card    .kpi-dot { background: #94a3b8; }

    /* ── Aurora panel (charts / rail cards) ──────────────────────────────── */
    .aurora-panel {
        background: #ffffff; border: 1px solid rgba(15,23,42,0.06);
        border-radius: 18px; padding: 18px 20px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 16px 36px -26px rgba(15,23,42,0.2);
    }

    /* Plotly containers -> match panel look */
    .stPlotlyChart {
        background: #ffffff; border: 1px solid rgba(15,23,42,0.06);
        border-radius: 18px; padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 16px 36px -26px rgba(15,23,42,0.2);
    }

    /* Dataframes */
    [data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid rgba(15,23,42,0.06); }

    /* ── Tabs -> Aurora violet underline ─────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 26px; border-bottom: 1px solid rgba(15,23,42,0.08);
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 12px 0; font-size: 13.5px; font-weight: 600; color: #64748b;
    }
    .stTabs [aria-selected="true"] { color: #6355ff !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: #6355ff !important; height: 2.5px; }
    .stTabs [data-baseweb="tab-border"] { background-color: transparent; }

    /* Buttons (suggestions / actions) */
    .stButton > button {
        border-radius: 11px; border: 1px solid rgba(15,23,42,0.08);
        background: #ffffff; color: #475569; font-weight: 600; font-size: 12.5px;
    }
    .stButton > button:hover { border-color: #6355ff; color: #6355ff; }

    /* hide Streamlit chrome */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}

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
</style>
""", unsafe_allow_html=True)

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def format_currency(value):
    if value is None or pd.isna(value):
        return "$0"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    elif abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    else:
        return f"${value:,.0f}"


def format_number(value, decimals=0):
    if value is None or pd.isna(value):
        return "0"
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def format_pct(value):
    if value is None or pd.isna(value):
        return "0%"
    return f"{value:.1f}%"


def sparkline_svg(series, color, w=74, h=24):
    """Tiny inline sparkline from a numeric series (returns '' if not enough data)."""
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


def kpi_card(label, value, card_class="", delta="", delta_color="", spark=""):
    """Aurora KPI card: status dot + label, big traffic-light value, delta + sparkline."""
    foot = ""
    if delta or spark:
        dcol = delta_color or "#64748b"
        delta_html = f'<span class="kpi-delta" style="color:{dcol}">{delta}</span>' if delta else "<span></span>"
        foot = f'<div class="kpi-foot">{delta_html}{spark}</div>'
    return f"""
    <div class="kpi-card {card_class}">
        <div class="kpi-top"><span class="kpi-dot"></span><span class="kpi-label">{label}</span></div>
        <div class="kpi-value">{value}</div>
        {foot}
    </div>
    """


def style_fig(fig, height=360, legend=False):
    """Apply the Aurora chart look to any Plotly figure."""
    fig.update_layout(
        height=height,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#475569", size=12),
        margin=dict(l=0, r=12, t=10, b=34),
        xaxis=dict(gridcolor="#eef0f6", zeroline=False, linecolor="#eef0f6"),
        yaxis=dict(gridcolor="#eef0f6", zeroline=False, linecolor="#eef0f6"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=-0.22, x=0, font=dict(size=11)),
        hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#fff", family="Plus Jakarta Sans")),
    )
    return fig


@st.cache_data(ttl=300)
def get_kpi_history():
    """Recent daily KPI snapshots for sparklines + day-over-day deltas."""
    return run_query("""
        SELECT kpi_date, dead_stock_value, excess_stock_value, total_inventory_value,
               holding_cost_monthly, stockout_cost, inventory_turnover
        FROM daily_kpis
        ORDER BY kpi_date ASC
        LIMIT 60
    """)


def kpi_deltas(hist):
    """Day-over-day delta per metric -> {key: (text, color)}. Empty if <2 snapshots."""
    out = {}
    if hist is None or hist.empty or len(hist) < 2:
        return out
    last, prev = hist.iloc[-1], hist.iloc[-2]
    # good_down=True => a decrease is good (cost/risk metrics)
    spec = {
        "dead_stock_value": True, "excess_stock_value": True, "holding_cost_monthly": True,
        "stockout_cost": True, "inventory_turnover": False, "total_inventory_value": None,
    }
    for col, good_down in spec.items():
        try:
            a, b = prev.get(col), last.get(col)
            if a in (None, 0) or pd.isna(a) or pd.isna(b):
                continue
            pct = (b - a) / abs(a) * 100
            up = pct >= 0
            arrow = "↑" if up else "↓"
            if good_down is None:
                color = "#64748b"  # neutral (total inventory value)
            else:
                good = (not up) if good_down else up
                color = "#12b76a" if good else "#e5484d"
            out[col] = (f"{arrow} {abs(pct):.1f}%", color)
        except (TypeError, ValueError):
            continue
    return out


# ── AI ASSISTANT: SAFETY + TOOLS ─────────────────────────────────────────────

def is_safe_query(sql):
    """Only allow read-only SELECT queries. Block anything destructive."""
    sql_clean = sql.strip().lower()
    # Remove trailing semicolons and anything after them
    sql_clean = sql_clean.split(";")[0]
    if not sql_clean.startswith("select") and not sql_clean.startswith("with"):
        return False
    forbidden = [
        r"\binsert\b", r"\bupdate\b", r"\bdelete\b", r"\bdrop\b",
        r"\balter\b", r"\bcreate\b", r"\btruncate\b", r"\bgrant\b",
        r"\brevoke\b", r"\bexec\b", r"\bexecute\b",
    ]
    for pattern in forbidden:
        if re.search(pattern, sql_clean):
            return False
    return True


DATABASE_SCHEMA = """
DATABASE SCHEMA (PostgreSQL / Supabase):

TABLE: orders
- id (serial, primary key)
- order_id (text) — order identifier
- order_date (timestamp) — when the order was placed
- product_name (text)
- category (text)
- quantity (integer) — units ordered
- unit_price (numeric) — price per unit
- total_amount (numeric) — total order value
- customer_segment (text) — Consumer / Corporate / Home Office
- market (text) — geographic market
- order_region (text)
- shipping_mode (text) — Standard Class / First Class / Second Class / Same Day
- days_for_shipping_real (integer) — actual delivery days
- days_for_shipping_scheduled (integer) — promised delivery days
- delivery_status (text) — Late delivery / Shipping on time / Advance shipping / Shipping canceled
- late_delivery_risk (integer) — 1 if late, 0 if on time

TABLE: inventory
- id (serial, primary key)
- stock_code (text) — SKU identifier
- product_name (text)
- category (text)
- unit_cost (numeric) — cost per unit
- current_stock (numeric) — units on hand
- inventory_value (numeric) — current_stock * unit_cost
- reorder_point (numeric) — stock level that triggers reorder
- supplier_lead_time_days (numeric) — days from PO to delivery
- warehouse (text) — Warehouse A - East / Warehouse B - Central / Warehouse C - West
- avg_daily_demand (numeric) — average units sold per day
- days_of_supply (numeric) — current_stock / avg_daily_demand
- total_qty_sold (numeric) — lifetime units sold
- optimal_stock (numeric) — avg_daily_demand * lead_time * 1.5
- excess_units (numeric) — units above optimal stock
- excess_value (numeric) — excess_units * unit_cost
- is_dead_stock (boolean) — true if 180+ days of supply or no sales
- is_excess (boolean) — true if stock exceeds optimal level
- abc_class (text) — A (top 80% revenue) / B (next 15%) / C (last 5%)

TABLE: daily_kpis
- id (serial, primary key)
- kpi_date (date)
- dead_stock_value (numeric)
- excess_stock_value (numeric)
- total_inventory_value (numeric)
- holding_cost_monthly (numeric)
- stockout_cost (numeric)
- supplier_otd_rate (numeric) — percentage
- avg_lead_time (numeric)
- lead_time_variance (numeric)
- inventory_turnover (numeric)
- total_orders (integer)
- total_revenue (numeric)

KPI DEFINITIONS:
- Dead Stock: inventory with 180+ days of supply or zero sales — trapped cash
- Excess Stock: inventory above optimal level (avg_daily_demand × lead_time × 1.5 safety factor)
- Holding Cost: 25% of inventory value per year (storage, insurance, capital cost, obsolescence)
- EOQ (Economic Order Quantity): SQRT((2 × annual_demand × 50) / (unit_cost × 0.25)) — assumes $50 order cost
- Stockout Cost: avg_daily_demand × 30 days × unit_cost for SKUs below reorder point
- OTD Rate: % of orders where late_delivery_risk = 0
"""

SYSTEM_PROMPT = f"""You are the AI analyst inside SupplyStack, a supply chain intelligence platform for e-commerce and DTC brands. You answer questions about the client's inventory, orders, suppliers, and operations by querying their live database.

{DATABASE_SCHEMA}

RULES:
1. Use the query_database tool to answer questions with real data. Never make up numbers.
2. Only SELECT queries are allowed. The tool will reject anything else.
3. Give specific, actionable answers with dollar amounts. Don't just report numbers — interpret them and recommend actions.
4. When relevant, connect metrics: high lead time variance causes overstock; dead stock burns holding costs; stockouts on fast movers lose revenue.
5. Format currency clearly ($12,400 not 12400.0).
6. Keep answers concise — 2-4 short paragraphs max. Lead with the answer, then context, then recommendation.
7. If a question is ambiguous, make a reasonable assumption and state it.
8. If asked about something not in the database, say what data would be needed.

Example of a great answer style:
"Your dead stock value is $45.9M across 96 SKUs — 97% of your total inventory value, which is critically high. The biggest offender is the Diamondback Serene Classic ($18.1M trapped, 2,669 days of supply). Recommended: start with the top 5 SKUs which hold $37.6M combined. Options: bundle promotions, liquidation channels, or write-offs for tax benefit. Acting on just the top 5 this quarter could recover $10-15M in cash."
"""

TOOLS = [
    {
        "name": "query_database",
        "description": "Execute a read-only SQL SELECT query against the supply chain PostgreSQL database. Returns results as JSON. Use this to answer any question about inventory, orders, suppliers, or KPIs with real data.",
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
    """Execute the SQL from Claude's tool call. Returns (result_string, dataframe_or_none)."""
    if not is_safe_query(sql):
        return "ERROR: Only SELECT queries are allowed. Query rejected for safety.", None
    try:
        df = run_query_uncached(sql)
        if df.empty:
            return "Query returned no results.", None
        # Limit rows sent back to Claude
        df_limited = df.head(50)
        result = df_limited.to_json(orient="records", date_format="iso")
        return result, df_limited
    except Exception as e:
        return f"ERROR executing query: {str(e)}", None


def ask_claude(user_question, conversation_history):
    """Send question to Claude with tool calling. Returns (answer_text, list_of_dataframes)."""
    try:
        import anthropic
    except ImportError:
        return "The 'anthropic' package is not installed. Run: pip install anthropic", []

    if ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return "⚠️ Anthropic API key not configured. Open app.py and set ANTHROPIC_API_KEY at the top of the file.", []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build messages from history + new question
    messages = []
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_question})

    dataframes = []
    max_iterations = 5

    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Check if Claude wants to use a tool
        if response.stop_reason == "tool_use":
            # Add Claude's response (including tool use) to messages
            messages.append({"role": "assistant", "content": response.content})

            # Process each tool call
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    sql = block.input.get("sql", "")
                    result_str, df = execute_tool_call(sql)
                    if df is not None:
                        dataframes.append((sql, df))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            # Final answer
            answer = ""
            for block in response.content:
                if block.type == "text":
                    answer += block.text
            return answer, dataframes

    return "The assistant took too many steps. Try rephrasing your question.", dataframes


# ── AURORA HEADER ─────────────────────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex; align-items:center; gap:16px; padding:4px 2px 20px; margin-bottom:6px;">
    <div style="width:40px; height:40px; border-radius:12px;
         background:linear-gradient(135deg,#6355ff,#9d8bff);
         display:flex; align-items:center; justify-content:center; font-size:19px; font-weight:800; color:#fff;
         box-shadow:0 8px 18px -8px rgba(99,85,255,0.7);">S</div>
    <div style="display:flex; flex-direction:column; gap:2px;">
        <span style="font-size:9.5px; font-weight:600; letter-spacing:0.18em; color:#a5aec4;">SUPPLYSTACK</span>
        <span style="font-size:22px; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">Inventory Operations Dashboard</span>
    </div>
    <div style="flex:1;"></div>
    <div style="display:flex; align-items:center; gap:8px; background:#fff; border:1px solid rgba(15,23,42,0.08);
         border-radius:11px; padding:9px 14px; font-size:12.5px; font-weight:600; color:#475569;">
        Last 30 days <span style="color:#a5aec4; font-size:10px;">▾</span></div>
    <div style="width:38px; height:38px; border-radius:50%;
         background:linear-gradient(135deg,#6355ff,#c084fc);
         display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#fff;">JD</div>
</div>
""", unsafe_allow_html=True)


# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Executive Dashboard",
    "📦 Inventory Detail",
    "🚚 Operations",
    "🔄 Reorder Recommendations",
    "🤖 AI Assistant",
    "🔔 Alert History",
    "🏥 Data Health",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: EXECUTIVE DASHBOARD  (Aurora layout)
# ══════════════════════════════════════════════════════════════════════════════

with tab1:

    # header row: title + traffic-light legend
    st.markdown("""
    <div style="display:flex; align-items:flex-end; justify-content:space-between; margin:2px 0 18px;">
      <div>
        <h2 style="margin:0; font-size:22px; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">Executive Overview</h2>
        <p style="margin:5px 0 0; font-size:13px; font-weight:500; color:#64748b;">Working-capital health across your warehouses and categories</p>
      </div>
      <div style="display:flex; gap:16px; align-items:center;">
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#12b76a;"></span>Healthy</span>
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#f79009;"></span>Watch</span>
        <span style="display:flex; align-items:center; gap:7px; font-size:11.5px; font-weight:600; color:#475569;"><span style="width:9px;height:9px;border-radius:50%;background:#e5484d;"></span>At risk</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    kpi_data = run_query("""
        SELECT
            COALESCE(SUM(CASE WHEN is_dead_stock THEN inventory_value ELSE 0 END), 0) AS dead_stock_value,
            COALESCE(SUM(CASE WHEN is_excess THEN excess_value ELSE 0 END), 0) AS excess_stock_value,
            COALESCE(SUM(inventory_value), 0) AS total_inventory_value,
            COALESCE(SUM(inventory_value) * 0.25 / 12, 0) AS holding_cost_monthly,
            COALESCE(
                (SELECT SUM(o.total_amount) FROM orders o) / NULLIF(SUM(inventory_value), 0),
                0
            ) AS inventory_turnover,
            COALESCE(
                SUM(CASE WHEN current_stock < reorder_point
                    THEN avg_daily_demand * 30 * unit_cost ELSE 0 END),
                0
            ) AS stockout_cost
        FROM inventory
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

    def _card(label, col, value, klass):
        d = deltas.get(col, ("", ""))
        return kpi_card(
            label, value, klass,
            delta=d[0], delta_color=d[1],
            spark=sparkline_svg(_series(col), STATUS[klass]["spark"]),
        )

    if not kpi_data.empty:
        row = kpi_data.iloc[0]

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            st.markdown(_card("Dead Stock Value", "dead_stock_value", format_currency(row["dead_stock_value"]), "kpi-danger"), unsafe_allow_html=True)
        with c2:
            st.markdown(_card("Excess Stock Value", "excess_stock_value", format_currency(row["excess_stock_value"]), "kpi-warning"), unsafe_allow_html=True)
        with c3:
            st.markdown(_card("Total Inventory", "total_inventory_value", format_currency(row["total_inventory_value"]), "kpi-info"), unsafe_allow_html=True)
        with c4:
            st.markdown(_card("Holding Cost / Mo", "holding_cost_monthly", format_currency(row["holding_cost_monthly"]), "kpi-warning"), unsafe_allow_html=True)
        with c5:
            turnover_class = "kpi-danger" if row["inventory_turnover"] < 2 else "kpi-success"
            st.markdown(_card("Inventory Turnover", "inventory_turnover", format_number(row["inventory_turnover"], 2) + "x", turnover_class), unsafe_allow_html=True)
        with c6:
            st.markdown(_card("Stockout Cost / Mo", "stockout_cost", format_currency(row["stockout_cost"]), "kpi-danger"), unsafe_allow_html=True)

    st.write("")

    # ── main 2:1 layout ───────────────────────────────────────────────────────
    main_left, main_right = st.columns([2, 1], gap="medium")

    with main_left:
        # Dead Stock Value by Category — coral gradient bars
        st.subheader("Dead Stock Value by Category")
        dead_by_cat = run_query("""
            SELECT category, SUM(inventory_value) AS dead_value
            FROM inventory
            WHERE is_dead_stock = true
            GROUP BY category
            ORDER BY dead_value DESC
            LIMIT 8
        """)

        if not dead_by_cat.empty:
            fig = px.bar(
                dead_by_cat, y="category", x="dead_value", orientation="h",
                color="dead_value", color_continuous_scale=["#ffc2b8", "#ff8a8b", "#ff5470"],
                labels={"dead_value": "Dead Stock Value ($)", "category": ""},
            )
            fig = style_fig(fig, height=320)
            fig.update_layout(coloraxis_showscale=False, yaxis=dict(categoryorder="total ascending", gridcolor="rgba(0,0,0,0)"))
            try:
                fig.update_traces(marker_cornerradius=6)
            except Exception:
                pass
            fig.update_traces(hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No dead stock data available.")

        sub_l, sub_r = st.columns(2, gap="medium")

        with sub_l:
            # Excess by Warehouse — DONUT (Aurora)
            st.subheader("Excess by Warehouse")
            excess_by_wh = run_query("""
                SELECT warehouse, SUM(excess_value) AS excess_val
                FROM inventory
                WHERE is_excess = true
                GROUP BY warehouse
                ORDER BY excess_val DESC
            """)

            if not excess_by_wh.empty:
                total_excess = excess_by_wh["excess_val"].sum()
                fig = px.pie(
                    excess_by_wh, values="excess_val", names="warehouse", hole=0.62,
                    color_discrete_sequence=["#6355ff", "#a78bfa", "#ddd6fe", "#ede9fe"],
                )
                fig.update_traces(
                    textinfo="percent", textfont=dict(family="Plus Jakarta Sans", size=12, color="#fff"),
                    marker=dict(line=dict(color="#ffffff", width=2)),
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<extra></extra>",
                )
                fig = style_fig(fig, height=300, legend=True)
                fig.add_annotation(
                    text=f"<b>{format_currency(total_excess)}</b><br><span style='font-size:10px;color:#94a3b8'>excess</span>",
                    x=0.5, y=0.5, showarrow=False,
                    font=dict(family="Plus Jakarta Sans", size=18, color="#0f172a"),
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No excess stock data available.")

        with sub_r:
            # Total Inventory trend — area
            st.subheader("Total Inventory Trend")
            if hist is not None and not hist.empty and "total_inventory_value" in hist.columns:
                tv = hist.dropna(subset=["total_inventory_value"])
                if len(tv) >= 2:
                    ymin = tv["total_inventory_value"].min()
                    ymax = tv["total_inventory_value"].max()
                    pad = (ymax - ymin) * 0.15 or ymax * 0.02
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=tv["kpi_date"], y=tv["total_inventory_value"],
                        mode="lines", line=dict(color="#6355ff", width=2.5, shape="spline"),
                        fill="tozeroy", fillcolor="rgba(99,85,255,0.14)",
                        hovertemplate="%{x|%b %d}<br>$%{y:,.0f}<extra></extra>",
                    ))
                    fig = style_fig(fig, height=300)
                    fig.update_layout(yaxis=dict(range=[ymin - pad, ymax + pad], gridcolor="#eef0f6"))
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("Not enough history yet for a trend.")
            else:
                st.info("Run the daily KPI pipeline to populate the trend.")

    with main_right:
        # ── AI Insight card (data-driven) ──────────────────────────────────
        insight = "Dead stock is concentrating your working-capital risk. Prioritise the top categories for clearance to free cash."
        try:
            if not dead_by_cat.empty:
                tot = dead_by_cat["dead_value"].sum()
                top3 = dead_by_cat.head(3)["dead_value"].sum()
                share = (top3 / tot * 100) if tot else 0
                names = dead_by_cat.head(2)["category"].tolist()
                who = " and ".join(names) if names else "your top categories"
                recover = tot * 0.18
                insight = (f"3 categories drive <b>{share:.0f}%</b> of dead stock. A markdown clearance on "
                           f"{who} could recover <b>~{format_currency(recover)}</b> in working capital this quarter.")
        except Exception:
            pass

        st.markdown(f"""
        <div style="background:linear-gradient(140deg,#6355ff,#8b5cf6); border-radius:18px; padding:20px; color:#fff;
             box-shadow:0 18px 38px -18px rgba(99,85,255,0.7); margin-bottom:16px;">
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:13px;">
            <span style="width:24px;height:24px;border-radius:8px;background:rgba(255,255,255,0.2);
                  display:flex;align-items:center;justify-content:center;font-size:13px;">✦</span>
            <span style="font-size:10px; font-weight:700; letter-spacing:0.12em;">AI ASSISTANT</span>
          </div>
          <p style="margin:0 0 15px; font-size:13.5px; font-weight:500; line-height:1.55; color:rgba(255,255,255,0.94);">{insight}</p>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <span style="font-size:11.5px; font-weight:600; background:rgba(255,255,255,0.16); padding:7px 12px; border-radius:9px;">Draft clearance plan</span>
            <span style="font-size:11.5px; font-weight:600; background:rgba(255,255,255,0.16); padding:7px 12px; border-radius:9px;">Ask about turnover</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Recent Alerts (built from live data) ───────────────────────────
        alerts_html = ['<div class="aurora-panel" style="margin-bottom:16px;">',
                       '<div class="rail-title"><h4>Recent Alerts</h4><span>View all</span></div>']
        tint = {"#e5484d": "#fdecec", "#f79009": "#fef3e2", "#3b82f6": "#eaf1fe"}
        rows = []
        try:
            top_dead = run_query("SELECT product_name, inventory_value FROM inventory WHERE is_dead_stock = true ORDER BY inventory_value DESC LIMIT 1")
            if not top_dead.empty:
                r0 = top_dead.iloc[0]
                rows.append((f"{r0['product_name']} flagged — {format_currency(r0['inventory_value'])} trapped", "Dead stock", "#e5484d", "live"))
        except Exception:
            pass
        try:
            top_wh = run_query("SELECT warehouse, SUM(excess_value) AS v FROM inventory WHERE is_excess = true GROUP BY warehouse ORDER BY v DESC LIMIT 1")
            if not top_wh.empty:
                w0 = top_wh.iloc[0]
                rows.append((f"{w0['warehouse']} holds the most excess — {format_currency(w0['v'])}", "Capacity", "#f79009", "live"))
        except Exception:
            pass
        try:
            below = run_query("SELECT COUNT(*) AS c FROM inventory WHERE current_stock < reorder_point AND avg_daily_demand > 0")
            if not below.empty and int(below.iloc[0]["c"]) > 0:
                rows.append((f"{int(below.iloc[0]['c'])} SKUs are below reorder point", "Stockout", "#e5484d", "live"))
        except Exception:
            pass
        rows.append(("Daily KPI snapshot refreshed", "Forecast", "#3b82f6", "today"))

        for text, tag, sev, when in rows:
            alerts_html.append(f"""
            <div class="alert-row">
              <span class="alert-bar" style="background:{sev};"></span>
              <div class="alert-body">
                <span class="alert-text">{text}</span>
                <div class="alert-meta">
                  <span class="alert-tag" style="color:{sev};background:{tint.get(sev,'#f1f2f8')};">{tag}</span>
                  <span class="alert-time">{when}</span>
                </div>
              </div>
            </div>""")
        alerts_html.append("</div>")
        st.markdown("".join(alerts_html), unsafe_allow_html=True)

        # ── Reorder Recommendations (mini) ─────────────────────────────────
        reo_html = ['<div class="aurora-panel">',
                    '<div class="rail-title"><h4>Reorder Recommendations</h4><span>All</span></div>']
        pbg = {"#e5484d": "#fdecec", "#f79009": "#fef3e2", "#12b76a": "#e7f7ef"}
        try:
            reo = run_query("""
                SELECT product_name, warehouse,
                    GREATEST(100, ROUND(avg_daily_demand * supplier_lead_time_days * 1.5)) AS qty,
                    CASE WHEN avg_daily_demand > 0 THEN ROUND(current_stock / avg_daily_demand) ELSE 9999 END AS dus
                FROM inventory
                WHERE avg_daily_demand > 0 AND current_stock < ROUND(avg_daily_demand * supplier_lead_time_days * 1.5)
                ORDER BY current_stock / NULLIF(avg_daily_demand, 0) ASC
                LIMIT 4
            """)
            if not reo.empty:
                for _, rr in reo.iterrows():
                    dus = rr["dus"]
                    if dus < 14:
                        pri, pc = "High", "#e5484d"
                    elif dus < 30:
                        pri, pc = "Med", "#f79009"
                    else:
                        pri, pc = "Low", "#12b76a"
                    name = str(rr["product_name"])
                    if len(name) > 26:
                        name = name[:26] + "…"
                    reo_html.append(f"""
                    <div class="reo-row">
                      <div style="flex:1; min-width:0;">
                        <div class="reo-name">{name}</div>
                        <div class="reo-sub">{rr['warehouse']} · {dus:.0f}d left</div>
                      </div>
                      <div style="text-align:right;">
                        <div class="reo-qty">{rr['qty']:,.0f} <span style="font-weight:500;color:#a5aec4;">units</span></div>
                        <span class="reo-pri" style="color:{pc};background:{pbg[pc]};">{pri}</span>
                      </div>
                    </div>""")
            else:
                reo_html.append('<p style="padding:16px 0 4px; font-size:12.5px; color:#94a3b8;">Nothing below reorder point right now.</p>')
        except Exception:
            reo_html.append('<p style="padding:16px 0 4px; font-size:12.5px; color:#94a3b8;">Reorder data unavailable.</p>')
        reo_html.append("</div>")
        st.markdown("".join(reo_html), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: INVENTORY DETAIL
# ══════════════════════════════════════════════════════════════════════════════

with tab2:

    inv_kpis = run_query("""
        SELECT
            COUNT(*) FILTER (WHERE is_dead_stock) AS dead_sku_count,
            COUNT(*) FILTER (WHERE is_excess) AS excess_sku_count,
            COUNT(*) FILTER (WHERE current_stock < reorder_point AND avg_daily_demand > 0) AS below_reorder
        FROM inventory
    """)

    if not inv_kpis.empty:
        r = inv_kpis.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card("Dead Stock SKUs", format_number(r["dead_sku_count"]), "kpi-danger"), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card("Excess Stock SKUs", format_number(r["excess_sku_count"]), "kpi-warning"), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card("Below Reorder Point", format_number(r["below_reorder"]), "kpi-danger"), unsafe_allow_html=True)
        with c4:
            abc_data = run_query("SELECT abc_class, COUNT(*) as cnt FROM inventory GROUP BY abc_class ORDER BY abc_class")
            abc_str = " | ".join([f"{row['abc_class']}: {row['cnt']}" for _, row in abc_data.iterrows()]) if not abc_data.empty else "N/A"
            st.markdown(kpi_card("ABC Classification", abc_str, "kpi-info"), unsafe_allow_html=True)

    st.write("")

    detail_left, detail_right = st.columns(2, gap="medium")

    with detail_left:
        st.subheader("Top 20 Dead Stock SKUs")
        top_dead = run_query("""
            SELECT product_name, current_stock, unit_cost, inventory_value, days_of_supply
            FROM inventory
            WHERE is_dead_stock = true
            ORDER BY inventory_value DESC
            LIMIT 20
        """)
        if not top_dead.empty:
            top_dead.columns = ["Product", "Stock", "Unit Cost", "Inventory Value", "Days of Supply"]
            st.dataframe(
                top_dead.style.format({
                    "Unit Cost": "${:,.2f}",
                    "Inventory Value": "${:,.0f}",
                    "Stock": "{:,.0f}",
                    "Days of Supply": "{:,.0f}",
                }),
                use_container_width=True, height=500,
            )
        else:
            st.info("No dead stock data.")

    with detail_right:
        st.subheader("Days of Supply Distribution")
        scatter_data = run_query("""
            SELECT product_name, days_of_supply, inventory_value, is_dead_stock, category
            FROM inventory
            WHERE days_of_supply < 365 AND inventory_value > 0
        """)

        if not scatter_data.empty:
            scatter_data["status"] = scatter_data["is_dead_stock"].map({True: "Dead Stock", False: "Healthy"})
            fig = px.scatter(
                scatter_data, x="days_of_supply", y="inventory_value", color="status",
                color_discrete_map={"Dead Stock": "#e5484d", "Healthy": "#12b76a"},
                hover_data=["product_name", "category"],
                labels={"days_of_supply": "Days of Supply", "inventory_value": "Inventory Value ($)", "status": "Status"},
                log_y=True,
            )
            fig = style_fig(fig, height=500, legend=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No inventory data for scatter chart.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab3:

    ops_kpis = run_query("""
        SELECT
            COALESCE(
                COUNT(*) FILTER (WHERE late_delivery_risk = 0)::numeric
                / NULLIF(COUNT(*)::numeric, 0) * 100, 0
            ) AS otd_rate,
            COALESCE(AVG(days_for_shipping_real), 0) AS avg_lead_time,
            COALESCE(STDDEV(days_for_shipping_real), 0) AS lead_time_variance,
            COALESCE(SUM(total_amount) / NULLIF(COUNT(DISTINCT order_id)::numeric, 0), 0) AS cost_per_order,
            COALESCE(AVG(days_for_shipping_real), 0) AS avg_fulfillment_time
        FROM orders
    """)

    if not ops_kpis.empty:
        r = ops_kpis.iloc[0]
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.markdown(kpi_card("Supplier OTD Rate", format_pct(r["otd_rate"]),
                "kpi-danger" if r["otd_rate"] < 80 else "kpi-success"), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card("Avg Lead Time", f"{r['avg_lead_time']:.1f} days", "kpi-info"), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi_card("Lead Time Variance", f"{r['lead_time_variance']:.2f}", "kpi-warning"), unsafe_allow_html=True)
        with c4:
            st.markdown(kpi_card("Cost Per Order", format_currency(r["cost_per_order"]), "kpi-info"), unsafe_allow_html=True)
        with c5:
            st.markdown(kpi_card("Avg Fulfillment", f"{r['avg_fulfillment_time']:.1f} days", "kpi-info"), unsafe_allow_html=True)

    st.write("")

    ops_left, ops_right = st.columns(2, gap="medium")

    with ops_left:
        st.subheader("OTD Rate by Region")
        otd_region = run_query("""
            SELECT
                order_region,
                COUNT(*) AS total_orders,
                ROUND(COUNT(*) FILTER (WHERE late_delivery_risk = 0)::numeric
                    / NULLIF(COUNT(*)::numeric, 0) * 100, 1) AS otd_rate,
                ROUND(AVG(days_for_shipping_real)::numeric, 2) AS avg_lead_time
            FROM orders
            GROUP BY order_region
            ORDER BY total_orders DESC
        """)
        if not otd_region.empty:
            otd_region.columns = ["Region", "Total Orders", "OTD Rate %", "Avg Lead Time"]
            st.dataframe(otd_region, use_container_width=True, height=350)
        else:
            st.info("No orders data.")

    with ops_right:
        st.subheader("Delivery Status Breakdown")
        delivery_status = run_query("""
            SELECT delivery_status, COUNT(*) AS order_count
            FROM orders
            GROUP BY delivery_status
            ORDER BY order_count DESC
        """)
        if not delivery_status.empty:
            fig = px.pie(
                delivery_status, values="order_count", names="delivery_status", hole=0.55,
                color_discrete_sequence=["#e5484d", "#6355ff", "#f79009", "#12b76a"],
            )
            fig.update_traces(marker=dict(line=dict(color="#ffffff", width=2)))
            fig = style_fig(fig, height=350, legend=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No delivery data.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: REORDER RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab4:

    reorder_kpis = run_query("""
        SELECT
            COUNT(*) FILTER (WHERE current_stock < reorder_point AND avg_daily_demand > 0) AS below_reorder,
            COALESCE(MIN(
                CASE WHEN avg_daily_demand > 0
                    THEN ROUND(current_stock / avg_daily_demand)
                    ELSE NULL END
            ), 0) AS most_urgent_days,
            (SELECT product_name FROM inventory
             WHERE avg_daily_demand > 0
             ORDER BY current_stock / avg_daily_demand ASC
             LIMIT 1) AS most_urgent_sku,
            COALESCE(SUM(
                CASE WHEN current_stock < reorder_point AND avg_daily_demand > 0
                    THEN avg_daily_demand * 30 * unit_cost ELSE 0 END
            ), 0) AS stockout_cost
        FROM inventory
    """)

    if not reorder_kpis.empty:
        r = reorder_kpis.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(kpi_card("SKUs Below Reorder", format_number(r["below_reorder"]), "kpi-danger"), unsafe_allow_html=True)
        with c2:
            st.markdown(kpi_card("Most Urgent Stockout", f"{r['most_urgent_days']:.0f} days", "kpi-danger"), unsafe_allow_html=True)
        with c3:
            sku_name = r["most_urgent_sku"] or "N/A"
            if len(str(sku_name)) > 25:
                sku_name = str(sku_name)[:25] + "..."
            st.markdown(kpi_card("Most Urgent SKU", sku_name, "kpi-warning"), unsafe_allow_html=True)
        with c4:
            st.markdown(kpi_card("Stockout Cost / Month", format_currency(r["stockout_cost"]), "kpi-danger"), unsafe_allow_html=True)

    st.write("")

    st.subheader("Reorder Recommendations Table")
    reorder_table = run_query("""
        SELECT
            product_name,
            current_stock,
            avg_daily_demand,
            supplier_lead_time_days,
            CASE WHEN avg_daily_demand > 0 AND unit_cost > 0
                THEN ROUND(SQRT((2 * avg_daily_demand * 365 * 50) / (unit_cost * 0.25)))
                ELSE 0 END AS eoq,
            CASE WHEN avg_daily_demand > 0 AND unit_cost > 0
                THEN GREATEST(100, ROUND(SQRT((2 * avg_daily_demand * 365 * 50) / (unit_cost * 0.25)) / 100) * 100)
                ELSE 100 END AS moq,
            ROUND(avg_daily_demand * supplier_lead_time_days * 1.5) AS suggested_reorder_point,
            CASE WHEN avg_daily_demand > 0
                THEN ROUND(current_stock / avg_daily_demand)
                ELSE 9999 END AS days_until_stockout,
            CASE
                WHEN current_stock < ROUND(avg_daily_demand * supplier_lead_time_days * 1.5)
                    THEN 'Reorder'
                WHEN is_dead_stock THEN 'Discount or liquidate'
                ELSE 'Hold'
            END AS recommended_action
        FROM inventory
        WHERE avg_daily_demand > 0
        ORDER BY
            CASE WHEN avg_daily_demand > 0 THEN current_stock / avg_daily_demand ELSE 9999 END ASC
        LIMIT 50
    """)

    if not reorder_table.empty:
        reorder_table.columns = [
            "Product", "Current Stock", "Avg Daily Demand", "Lead Time (days)",
            "EOQ", "MOQ", "Reorder Point", "Days Until Stockout", "Action"
        ]

        def color_stockout(val):
            try:
                v = float(val)
                if v < 14:
                    return "background-color: rgba(229,72,77,0.16)"
                elif v < 30:
                    return "background-color: rgba(247,144,9,0.16)"
                else:
                    return "background-color: rgba(18,183,106,0.14)"
            except (ValueError, TypeError):
                return ""

        def color_action(val):
            if "Reorder" in str(val):
                return "background-color: rgba(229,72,77,0.16)"
            elif "Discount" in str(val):
                return "background-color: rgba(247,144,9,0.16)"
            return "background-color: rgba(18,183,106,0.14)"

        styled = reorder_table.style.applymap(
            color_stockout, subset=["Days Until Stockout"]
        ).applymap(
            color_action, subset=["Action"]
        ).format({
            "Current Stock": "{:,.0f}",
            "Avg Daily Demand": "{:,.1f}",
            "Lead Time (days)": "{:,.0f}",
            "EOQ": "{:,.0f}",
            "MOQ": "{:,.0f}",
            "Reorder Point": "{:,.0f}",
            "Days Until Stockout": "{:,.0f}",
        })

        st.dataframe(styled, use_container_width=True, height=600)
    else:
        st.info("No reorder data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: AI ASSISTANT (Claude API with tool calling)
# ══════════════════════════════════════════════════════════════════════════════

with tab5:
    st.subheader("🤖 AI Supply Chain Analyst")
    st.caption("Ask questions about your inventory, orders, and operations in plain English. The AI queries your live data and gives specific recommendations.")

    # Suggested questions
    st.markdown("**Try asking:**")
    suggestion_cols = st.columns(4)
    suggestions = [
        "What's our dead stock value by category?",
        "Which SKUs stock out this week?",
        "What should I reorder first?",
        "Where is cash trapped in my warehouses?",
    ]

    # Initialize chat history
    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    for i, sug in enumerate(suggestions):
        with suggestion_cols[i]:
            if st.button(sug, key=f"sug_{i}", use_container_width=True):
                st.session_state.pending_question = sug

    st.markdown("---")

    # Display chat history
    for msg in st.session_state.ai_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["display"])
            # Show any dataframes attached to this message
            for sql, df in msg.get("dataframes", []):
                with st.expander("📊 View data"):
                    st.code(sql, language="sql")
                    st.dataframe(df, use_container_width=True)

    # Chat input
    user_input = st.text_input("Ask a question about your supply chain data...", key="ai_input")

    # Handle either typed input or suggestion button
    question = None
    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None
    elif user_input and user_input != st.session_state.get("last_question", ""):
        question = user_input
        st.session_state.last_question = user_input

    if question:
        # Display user message
        with st.chat_message("user"):
            st.markdown(question)

        # Build conversation history for Claude (text only)
        history = [
            {"role": m["role"], "content": m["display"]}
            for m in st.session_state.ai_messages
        ]

        # Get Claude's answer
        with st.chat_message("assistant"):
            with st.spinner("Analyzing your data..."):
                answer, dataframes = ask_claude(question, history)
            st.markdown(answer)
            for sql, df in dataframes:
                with st.expander("📊 View data"):
                    st.code(sql, language="sql")
                    st.dataframe(df, use_container_width=True)

        # Save to history
        st.session_state.ai_messages.append({"role": "user", "display": question, "dataframes": []})
        st.session_state.ai_messages.append({"role": "assistant", "display": answer, "dataframes": dataframes})

    # Clear chat button
    if st.session_state.ai_messages:
        if st.button("🗑️ Clear conversation"):
            st.session_state.ai_messages = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: ALERT HISTORY
# ══════════════════════════════════════════════════════════════════════════════

with tab6:
    st.subheader("🔔 Alert History & Configuration")

    alert_col1, alert_col2 = st.columns(2, gap="medium")

    with alert_col1:
        st.markdown("### KPI History")

        daily_kpis = run_query("""
            SELECT kpi_date, dead_stock_value, excess_stock_value,
                   total_inventory_value, stockout_cost, supplier_otd_rate
            FROM daily_kpis
            ORDER BY kpi_date DESC
            LIMIT 30
        """)

        if not daily_kpis.empty:
            daily_kpis.columns = ["Date", "Dead Stock", "Excess Stock",
                                   "Total Inventory", "Stockout Cost", "OTD Rate"]
            st.dataframe(
                daily_kpis.style.format({
                    "Dead Stock": "${:,.0f}",
                    "Excess Stock": "${:,.0f}",
                    "Total Inventory": "${:,.0f}",
                    "Stockout Cost": "${:,.0f}",
                    "OTD Rate": "{:.1f}%",
                }),
                use_container_width=True,
            )
        else:
            st.info("No KPI history yet. Run the n8n pipeline to start populating daily KPIs.")

    with alert_col2:
        st.markdown("### Alert Thresholds")
        st.markdown("Current alert configuration (editable in n8n workflow):")

        st.markdown("""
        | Alert Type | Threshold | Status |
        |---|---|---|
        | Dead Stock | inventory_value > $5,000 | ✅ Active |
        | Excess Stock | excess_value > $5,000 | ✅ Active |
        | Stockout Risk | days_until_stockout < 14 | ✅ Active |
        | Weekly Brief | Every Monday 8am | 🔧 In progress |
        | AI Narrative Alerts | Per-SKU recommendations | 🔧 In progress |
        """)
# ══════════════════════════════════════════════════════════════════════════════
# TAB 7: DATA HEALTH
# ══════════════════════════════════════════════════════════════════════════════

with tab7:
    st.subheader("🏥 Data Health Monitor")
    st.caption("Real-time data quality checks across your orders and inventory tables.")

    st.markdown("### Data Freshness")
    freshness = run_query("""
        SELECT
            (SELECT COUNT(*) FROM orders) AS total_orders,
            (SELECT COUNT(*) FROM inventory) AS total_skus,
            (SELECT MAX(order_date) FROM orders) AS latest_order,
            (SELECT MAX(updated_at) FROM inventory) AS last_inventory_update
    """)

    if not freshness.empty:
        f = freshness.iloc[0]
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            st.markdown(kpi_card("Total Orders", format_number(f["total_orders"]), "kpi-info"), unsafe_allow_html=True)
        with fc2:
            st.markdown(kpi_card("Total SKUs", format_number(f["total_skus"]), "kpi-info"), unsafe_allow_html=True)
        with fc3:
            latest = str(f["latest_order"])[:10] if f["latest_order"] else "N/A"
            st.markdown(kpi_card("Latest Order", latest, "kpi-info"), unsafe_allow_html=True)
        with fc4:
            inv_update = str(f["last_inventory_update"])[:10] if f["last_inventory_update"] else "N/A"
            st.markdown(kpi_card("Last Inventory Sync", inv_update, "kpi-info"), unsafe_allow_html=True)

    st.write("")

    health_left, health_right = st.columns(2, gap="medium")

    with health_left:
        st.markdown("### Missing Values Check")
        missing = run_query("""
            SELECT 'Orders — Product Name' AS field,
                COUNT(*) FILTER (WHERE product_name IS NULL OR product_name = '') AS missing,
                COUNT(*) AS total
            FROM orders
            UNION ALL
            SELECT 'Orders — Quantity',
                COUNT(*) FILTER (WHERE quantity IS NULL OR quantity = 0), COUNT(*) FROM orders
            UNION ALL
            SELECT 'Orders — Amount',
                COUNT(*) FILTER (WHERE total_amount IS NULL OR total_amount = 0), COUNT(*) FROM orders
            UNION ALL
            SELECT 'Orders — Date',
                COUNT(*) FILTER (WHERE order_date IS NULL), COUNT(*) FROM orders
            UNION ALL
            SELECT 'Inventory — Unit Cost',
                COUNT(*) FILTER (WHERE unit_cost IS NULL OR unit_cost <= 0), COUNT(*) FROM inventory
            UNION ALL
            SELECT 'Inventory — Stock',
                COUNT(*) FILTER (WHERE current_stock IS NULL OR current_stock < 0), COUNT(*) FROM inventory
        """)

        if not missing.empty:
            missing.columns = ["Field", "Missing", "Total"]
            st.dataframe(missing, use_container_width=True)

    with health_right:
        st.markdown("### Duplicates & Outliers")

        dupes = run_query("""
            SELECT product_name, COUNT(*) AS count
            FROM inventory GROUP BY product_name HAVING COUNT(*) > 1
            ORDER BY count DESC LIMIT 10
        """)

        if not dupes.empty:
            st.markdown("**Duplicate SKUs:**")
            dupes.columns = ["Product Name", "Count"]
            st.dataframe(dupes, use_container_width=True)
        else:
            st.success("✅ No duplicate SKUs found")

        outliers = run_query("""
            SELECT product_name, unit_cost
            FROM inventory
            WHERE unit_cost > (SELECT AVG(unit_cost) * 5 FROM inventory WHERE unit_cost > 0)
            AND unit_cost > 0
            ORDER BY unit_cost DESC LIMIT 10
        """)

        if not outliers.empty:
            st.markdown("**Price Outliers (5x+ above average):**")
            outliers.columns = ["Product", "Unit Cost"]
            st.dataframe(
                outliers.style.format({"Unit Cost": "${:,.2f}"}),
                use_container_width=True,
            )
        else:
            st.success("✅ No price outliers detected")

    st.write("")

    st.markdown("### Orders vs Inventory Consistency")
    cons_left, cons_right = st.columns(2, gap="medium")

    with cons_left:
        st.markdown("**Inventory SKUs with no orders:**")
        no_orders = run_query("""
            SELECT i.product_name, i.current_stock, i.inventory_value
            FROM inventory i
            LEFT JOIN orders o ON i.product_name = o.product_name
            WHERE o.product_name IS NULL
            ORDER BY i.inventory_value DESC LIMIT 10
        """)

        if not no_orders.empty:
            no_orders.columns = ["Product", "Stock", "Value"]
            st.dataframe(
                no_orders.style.format({"Value": "${:,.0f}", "Stock": "{:,.0f}"}),
                use_container_width=True,
            )
            st.warning(f"⚠️ {len(no_orders)} SKUs have inventory but zero order history")
        else:
            st.success("✅ All inventory SKUs have matching orders")

    with cons_right:
        st.markdown("**Orders for products not in inventory:**")
        no_inv = run_query("""
            SELECT o.product_name, COUNT(*) AS orders, SUM(o.total_amount) AS revenue
            FROM orders o
            LEFT JOIN inventory i ON o.product_name = i.product_name
            WHERE i.product_name IS NULL
            GROUP BY o.product_name
            ORDER BY revenue DESC LIMIT 10
        """)

        if not no_inv.empty:
            no_inv.columns = ["Product", "Orders", "Revenue"]
            st.dataframe(
                no_inv.style.format({"Revenue": "${:,.0f}"}),
                use_container_width=True,
            )
            st.warning(f"⚠️ {len(no_inv)} products have orders but no inventory record")
        else:
            st.success("✅ All ordered products exist in inventory")

    st.write("")

    total_issues = run_query("""
        SELECT
            (SELECT COUNT(*) FILTER (WHERE product_name IS NULL OR product_name = '') FROM orders) +
            (SELECT COUNT(*) FILTER (WHERE quantity IS NULL OR quantity = 0) FROM orders) +
            (SELECT COUNT(*) FROM (SELECT product_name FROM inventory GROUP BY product_name HAVING COUNT(*) > 1) d) +
            (SELECT COUNT(*) FROM inventory WHERE unit_cost <= 0 OR unit_cost IS NULL)
        AS total_issues
    """)

    if not total_issues.empty:
        issues = int(total_issues.iloc[0]["total_issues"])
        if issues == 0:
            st.success("✅ **EXCELLENT** — No data quality issues detected.")
        elif issues <= 5:
            st.warning(f"⚠️ **GOOD** — {issues} minor issues detected. Review above.")
        else:
            st.error(f"🔴 **NEEDS ATTENTION** — {issues} issues found. Clean before trusting metrics.")

# ── FOOTER ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #94a3b8; font-size: 12px;">'
    'Supply Chain Intelligence Engine • Powered by SupplyStack • '
    f'Last refresh: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    '</p>',
    unsafe_allow_html=True,
)
