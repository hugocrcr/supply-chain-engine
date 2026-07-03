"""
Supply Chain Intelligence Engine — Streamlit Dashboard
Connects to Supabase Postgres. All data reads from the same DB that n8n writes to.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Supply Chain Intelligence Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── SUPABASE CONNECTION ───────────────────────────────────────────────────────
# Replace YOUR_PASSWORD_HERE with your actual Supabase password

DB_CONFIG = {
    "host": "aws-1-eu-central-1.pooler.supabase.com",
    "port": 5432,
    "database": "postgres",
    "user": "postgres.wnwuaeuifcdxncdbhjrj",
    "password": "Onizuka97229?",
    "sslmode": "require",
}


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
        # Reconnect on failure
        st.cache_resource.clear()
        return pd.DataFrame()


# ── THEME / STYLING ───────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Clean dark professional look */
    .block-container { padding-top: 2rem; padding-bottom: 1rem; }
    
    /* KPI card styling */
    .kpi-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        min-height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .kpi-value {
        font-size: 28px;
        font-weight: 700;
        color: #e0e0e0;
        margin-bottom: 4px;
    }
    .kpi-label {
        font-size: 13px;
        color: #8888aa;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .kpi-danger .kpi-value { color: #ff6b6b; }
    .kpi-warning .kpi-value { color: #ffa94d; }
    .kpi-success .kpi-value { color: #51cf66; }
    .kpi-info .kpi-value { color: #74c0fc; }
    
    /* Header */
    .main-header {
        font-size: 14px;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 0;
        padding-bottom: 0;
    }
    .main-title {
        font-size: 28px;
        font-weight: 700;
        margin-top: 0;
        padding-top: 0;
        margin-bottom: 24px;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        font-size: 14px;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def format_currency(value):
    """Format a number as currency (e.g., $45.94M, $969K, $1,234)."""
    if value is None or pd.isna(value):
        return "$0"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    elif abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    else:
        return f"${value:,.0f}"


def format_number(value, decimals=0):
    """Format a plain number."""
    if value is None or pd.isna(value):
        return "0"
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def format_pct(value):
    """Format as percentage."""
    if value is None or pd.isna(value):
        return "0%"
    return f"{value:.1f}%"


def kpi_card(label, value, card_class=""):
    """Render a styled KPI card."""
    return f"""
    <div class="kpi-card {card_class}">
        <div class="kpi-value">{value}</div>
        <div class="kpi-label">{label}</div>
    </div>
    """


# ── HEADER ────────────────────────────────────────────────────────────────────

st.markdown('<p class="main-header">Supply Chain Intelligence Engine</p>', unsafe_allow_html=True)
st.markdown('<h1 class="main-title">📊 Inventory Operations Dashboard</h1>', unsafe_allow_html=True)

# Last refresh indicator
col_refresh, col_spacer = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── TABS ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Executive Dashboard",
    "📦 Inventory Detail",
    "🚚 Operations",
    "🔄 Reorder Recommendations",
    "🤖 AI Assistant",
    "🔔 Alert History",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: EXECUTIVE DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab1:

    # ── Fetch KPI data ────────────────────────────────────────────────────
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

    if not kpi_data.empty:
        row = kpi_data.iloc[0]

        # ── 6 KPI Cards ──────────────────────────────────────────────────
        c1, c2, c3, c4, c5, c6 = st.columns(6)

        with c1:
            st.markdown(kpi_card(
                "Dead Stock Value",
                format_currency(row["dead_stock_value"]),
                "kpi-danger"
            ), unsafe_allow_html=True)

        with c2:
            st.markdown(kpi_card(
                "Excess Stock Value",
                format_currency(row["excess_stock_value"]),
                "kpi-warning"
            ), unsafe_allow_html=True)

        with c3:
            st.markdown(kpi_card(
                "Total Inventory Value",
                format_currency(row["total_inventory_value"]),
                "kpi-info"
            ), unsafe_allow_html=True)

        with c4:
            st.markdown(kpi_card(
                "Holding Cost / Month",
                format_currency(row["holding_cost_monthly"]),
                "kpi-warning"
            ), unsafe_allow_html=True)

        with c5:
            st.markdown(kpi_card(
                "Inventory Turnover",
                format_number(row["inventory_turnover"], 2) + "x",
                "kpi-danger" if row["inventory_turnover"] < 2 else "kpi-success"
            ), unsafe_allow_html=True)

        with c6:
            st.markdown(kpi_card(
                "Stockout Cost / Month",
                format_currency(row["stockout_cost"]),
                "kpi-danger"
            ), unsafe_allow_html=True)

    st.markdown("---")

    # ── Charts row ────────────────────────────────────────────────────────
    chart_left, chart_right = st.columns(2)

    with chart_left:
        st.subheader("Dead Stock Value by Category")
        dead_by_cat = run_query("""
            SELECT category, SUM(inventory_value) AS dead_value
            FROM inventory
            WHERE is_dead_stock = true
            GROUP BY category
            ORDER BY dead_value DESC
            LIMIT 15
        """)

        if not dead_by_cat.empty:
            fig = px.bar(
                dead_by_cat,
                y="category",
                x="dead_value",
                orientation="h",
                color_discrete_sequence=["#ff6b6b"],
                labels={"dead_value": "Dead Stock Value ($)", "category": ""},
            )
            fig.update_layout(
                height=400,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
                yaxis=dict(autorange="reversed"),
                margin=dict(l=0, r=20, t=10, b=40),
                showlegend=False,
            )
            fig.update_traces(
                hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No dead stock data available.")

    with chart_right:
        st.subheader("Excess Stock Value by Warehouse")
        excess_by_wh = run_query("""
            SELECT warehouse, SUM(excess_value) AS excess_val
            FROM inventory
            WHERE is_excess = true
            GROUP BY warehouse
            ORDER BY excess_val DESC
        """)

        if not excess_by_wh.empty:
            fig = px.bar(
                excess_by_wh,
                y="warehouse",
                x="excess_val",
                orientation="h",
                color_discrete_sequence=["#ffa94d"],
                labels={"excess_val": "Excess Stock Value ($)", "warehouse": ""},
            )
            fig.update_layout(
                height=400,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
                yaxis=dict(autorange="reversed"),
                margin=dict(l=0, r=20, t=10, b=40),
                showlegend=False,
            )
            fig.update_traces(
                hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No excess stock data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: INVENTORY DETAIL
# ══════════════════════════════════════════════════════════════════════════════

with tab2:

    # ── KPI cards ─────────────────────────────────────────────────────────
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

    st.markdown("---")

    detail_left, detail_right = st.columns(2)

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
                use_container_width=True,
                height=500,
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
            scatter_data["status"] = scatter_data["is_dead_stock"].map(
                {True: "Dead Stock", False: "Healthy"}
            )
            fig = px.scatter(
                scatter_data,
                x="days_of_supply",
                y="inventory_value",
                color="status",
                color_discrete_map={"Dead Stock": "#ff6b6b", "Healthy": "#51cf66"},
                hover_data=["product_name", "category"],
                labels={
                    "days_of_supply": "Days of Supply",
                    "inventory_value": "Inventory Value ($)",
                    "status": "Status",
                },
                log_y=True,
            )
            fig.update_layout(
                height=500,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
                margin=dict(l=0, r=20, t=10, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)
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
            COALESCE(
                SUM(total_amount) / NULLIF(COUNT(DISTINCT order_id)::numeric, 0), 0
            ) AS cost_per_order,
            COALESCE(AVG(days_for_shipping_real), 0) AS avg_fulfillment_time,
            COUNT(*) AS total_orders,
            COALESCE(SUM(total_amount), 0) AS total_revenue
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

    st.markdown("---")

    ops_left, ops_right = st.columns(2)

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
                delivery_status,
                values="order_count",
                names="delivery_status",
                hole=0.4,
                color_discrete_sequence=["#ff6b6b", "#74c0fc", "#ffa94d", "#51cf66"],
            )
            fig.update_layout(
                height=350,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                margin=dict(l=0, r=0, t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No delivery data.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: REORDER RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab4:

    # KPI cards
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

    st.markdown("---")

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
                    return "background-color: rgba(255,107,107,0.3)"
                elif v < 30:
                    return "background-color: rgba(255,169,77,0.3)"
                else:
                    return "background-color: rgba(81,207,102,0.2)"
            except (ValueError, TypeError):
                return ""

        def color_action(val):
            if "Reorder" in str(val):
                return "background-color: rgba(255,107,107,0.3)"
            elif "Discount" in str(val):
                return "background-color: rgba(255,169,77,0.3)"
            return "background-color: rgba(81,207,102,0.2)"

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
# TAB 5: AI ASSISTANT (Phase B — scaffold)
# ══════════════════════════════════════════════════════════════════════════════

with tab5:
    st.subheader("🤖 AI Supply Chain Assistant")
    st.markdown("""
    *Ask questions about your inventory, suppliers, and operations in plain English.*
    
    **Coming in Phase B** — This tab will connect to the Anthropic Claude API with tool calling 
    to answer questions like:
    
    - "What's our dead stock value by category?"
    - "Which SKUs are at risk of stockout this week?"
    - "How has our inventory turnover trended this quarter?"
    - "What should I reorder first and how much?"
    
    The AI will generate SQL queries against your live Supabase data and return 
    contextual answers with specific recommendations.
    """)

    # Placeholder chat interface
    user_input = st.chat_input("Ask a question about your supply chain data...")
    if user_input:
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            st.write("🔧 AI Assistant is being built in Phase B. Check back soon!")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: ALERT HISTORY (scaffold)
# ══════════════════════════════════════════════════════════════════════════════

with tab6:
    st.subheader("🔔 Alert History & Configuration")

    alert_col1, alert_col2 = st.columns(2)

    with alert_col1:
        st.markdown("### Recent Alerts")
        st.markdown("""
        Alert history will be populated from the `daily_kpis` table, 
        showing when thresholds were crossed and what actions were taken.
        """)

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
        | Weekly Brief | Every Monday 8am | 🔧 Phase B |
        | AI Narrative Alerts | Per-SKU recommendations | 🔧 Phase B |
        """)


# ── FOOTER ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #666; font-size: 12px;">'
    'Supply Chain Intelligence Engine • Powered by SCIE • '
    f'Last refresh: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    '</p>',
    unsafe_allow_html=True,
)
