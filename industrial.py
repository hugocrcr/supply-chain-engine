"""
SupplyStack — Industrial Supply Chain Intelligence
Dashboard for MECAPRO Industries and future industrial clients.

CLIENT_MODE / CLIENT_LANG at top let you switch mode and language per client.
"""

import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date

# ═══════════════════════════════════════════════════════════════════════════
# CLIENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
CLIENT_MODE = "industrial"        # "industrial" or "dtc" (only industrial for now)
CLIENT_LANG = "fr"                 # "fr" or "en"
CLIENT_NAME = "MECAPRO Industries"
CLIENT_CURRENCY = "€"

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
    "options": "-c statement_timeout=15000",
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
        return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Database error: {e}")
        st.cache_resource.clear()
        return pd.DataFrame()

# ═══════════════════════════════════════════════════════════════════════════
# LABELS (I18N)
# ═══════════════════════════════════════════════════════════════════════════
LABELS = {
    "fr": {
        "nav_overview": "🎯 Vue d'ensemble",
        "nav_stock": "📦 Analyse Stock",
        "nav_cash": "💰 Trésorerie",
        "nav_suppliers": "🚚 Fournisseurs",
        "nav_quality": "🔍 Qualité data",
        "kpi_total_stock": "Stock total",
        "kpi_working_capital": "BFR immobilisé",
        "kpi_annual_cost": "Coût annuel détention",
        "kpi_recoverable": "Cash récupérable",
        "kpi_dead": "Refs dormantes",
        "kpi_excess": "Refs excess",
        "kpi_stockout": "Refs risque rupture",
        "kpi_otd": "OTD fournisseurs",
        "kpi_coverage": "Couverture moyenne (j)",
        "kpi_turnover": "Rotation stock",
        "abc_class": "Classe ABC",
        "xyz_class": "Classe XYZ",
        "article_type": "Type article",
        "references": "Références",
        "value": "Valeur",
        "supplier": "Fournisseur",
        "orders": "Commandes",
        "lead_time": "Délai moyen (j)",
        "variability": "Variabilité",
        "otd_pct": "OTD %",
        "risk_score": "Score risque",
        "category": "Catégorie",
        "action": "Action recommandée",
        "issue": "Problème",
        "severity": "Sévérité",
        "affected": "Lignes affectées",
        "critical": "Critique",
        "warning": "Attention",
        "no_data": "Aucune donnée disponible",
    },
    "en": {
        "nav_overview": "🎯 Overview",
        "nav_stock": "📦 Stock Analysis",
        "nav_cash": "💰 Cash Recovery",
        "nav_suppliers": "🚚 Suppliers",
        "nav_quality": "🔍 Data Quality",
        "kpi_total_stock": "Total stock",
        "kpi_working_capital": "Working capital tied",
        "kpi_annual_cost": "Annual holding cost",
        "kpi_recoverable": "Recoverable cash",
        "kpi_dead": "Dead stock refs",
        "kpi_excess": "Excess refs",
        "kpi_stockout": "Stockout risk refs",
        "kpi_otd": "Supplier OTD",
        "kpi_coverage": "Avg coverage (days)",
        "kpi_turnover": "Stock turnover",
        "abc_class": "ABC Class",
        "xyz_class": "XYZ Class",
        "article_type": "Article type",
        "references": "References",
        "value": "Value",
        "supplier": "Supplier",
        "orders": "Orders",
        "lead_time": "Avg lead time (d)",
        "variability": "Variability",
        "otd_pct": "OTD %",
        "risk_score": "Risk score",
        "category": "Category",
        "action": "Recommended action",
        "issue": "Issue",
        "severity": "Severity",
        "affected": "Affected rows",
        "critical": "Critical",
        "warning": "Warning",
        "no_data": "No data available",
    },
}
L = LABELS[CLIENT_LANG]

# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════
st.sidebar.title(f"🏭 {CLIENT_NAME}")
st.sidebar.caption(f"Mode: {CLIENT_MODE} | {CLIENT_LANG.upper()}")

page = st.sidebar.radio(
    "Navigation",
    [L["nav_overview"], L["nav_stock"], L["nav_cash"], L["nav_suppliers"], L["nav_quality"]],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Data as of: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ═══════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def fmt_currency(val):
    if val is None or pd.isna(val):
        return "—"
    val = float(val)
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:.2f} M{CLIENT_CURRENCY}"
    if abs(val) >= 1_000:
        return f"{val/1_000:.0f} k{CLIENT_CURRENCY}"
    return f"{val:.0f} {CLIENT_CURRENCY}"

def fmt_number(val):
    if val is None or pd.isna(val):
        return "—"
    return f"{int(val):,}".replace(",", " ")

def fmt_pct(val):
    if val is None or pd.isna(val):
        return "—"
    return f"{float(val):.1f}%"

# ═══════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════
def render_overview():
    st.title(L["nav_overview"])
    
    kpi = run_query("SELECT * FROM daily_kpis_industrial WHERE kpi_date = CURRENT_DATE LIMIT 1;")
    
    if kpi.empty:
        st.warning(L["no_data"])
        return
    
    k = kpi.iloc[0]
    
    # 4 KPI cards principales
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(L["kpi_total_stock"], fmt_currency(k["total_stock_value"]))
    col2.metric(L["kpi_working_capital"], fmt_currency(k["working_capital_tied"]))
    col3.metric(L["kpi_annual_cost"], fmt_currency(k["annual_holding_cost"]))
    col4.metric(L["kpi_recoverable"], fmt_currency(k["recoverable_cash_est"]))
    
    st.markdown("---")
    
    # 4 KPI opérationnelles
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(L["kpi_dead"], fmt_number(k["dead_stock_ref_count"]))
    col2.metric(L["kpi_excess"], fmt_number(k["excess_stock_ref_count"]))
    col3.metric(L["kpi_stockout"], fmt_number(k["stockout_risk_ref_count"]))
    col4.metric(L["kpi_otd"], fmt_pct(k["supplier_otd_rate"]))
    
    st.markdown("---")
    
    # Alertes
    st.subheader("⚠️ Alertes")
    
    alerts = []
    if k["dead_stock_ref_count"] > 20:
        alerts.append((
            "🔴" if k["dead_stock_ref_count"] > 50 else "🟠",
            f"{int(k['dead_stock_ref_count'])} références dormantes — {fmt_currency(k['dead_stock_value'])} à libérer"
        ))
    if k["stockout_risk_ref_count"] > 50:
        alerts.append((
            "🔴",
            f"{int(k['stockout_risk_ref_count'])} références en risque de rupture — action requise"
        ))
    if k["supplier_otd_rate"] and k["supplier_otd_rate"] < 70:
        alerts.append((
            "🔴",
            f"OTD fournisseurs à {k['supplier_otd_rate']:.1f}% — vraie cause des ruptures"
        ))
    if k["excess_stock_ref_count"] > 200:
        alerts.append((
            "🟠",
            f"{int(k['excess_stock_ref_count'])} références en sur-stock — {fmt_currency(k['excess_stock_value'])} mobilisable"
        ))
    
    if not alerts:
        st.success("✅ Aucune alerte majeure")
    else:
        for icon, msg in alerts:
            st.warning(f"{icon} {msg}")
    
    st.markdown("---")
    
    # Cascade valeur
    st.subheader("💧 Cascade de la valeur du stock")
    
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "relative", "total"],
        x=["Stock total", "Dormant", "Excess", "Stock sain"],
        y=[
            float(k["total_stock_value"]),
            -float(k["dead_stock_value"]),
            -float(k["excess_stock_value"]),
            0
        ],
        text=[
            fmt_currency(k["total_stock_value"]),
            f"-{fmt_currency(k['dead_stock_value'])}",
            f"-{fmt_currency(k['excess_stock_value'])}",
            fmt_currency(float(k["total_stock_value"]) - float(k["dead_stock_value"]) - float(k["excess_stock_value"]))
        ],
        textposition="outside",
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        increasing={"marker": {"color": "#2ECC71"}},
        decreasing={"marker": {"color": "#E74C3C"}},
        totals={"marker": {"color": "#3498DB"}},
    ))
    fig.update_layout(
        showlegend=False,
        height=400,
        margin=dict(t=30, b=30, l=30, r=30),
    )
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# PAGE 2 — STOCK ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
def render_stock():
    st.title(L["nav_stock"])
    
    # ABC × XYZ Matrix
    st.subheader("Matrice ABC × XYZ")
    
    matrix = run_query("""
        SELECT 
            COALESCE(abc_class, 'N/A') AS abc_class,
            COALESCE(xyz_class, 'N/A') AS xyz_class,
            COUNT(*) AS refs,
            ROUND(SUM(current_stock * unit_cost)::numeric, 0) AS valeur
        FROM inventory
        GROUP BY abc_class, xyz_class
        ORDER BY abc_class, xyz_class;
    """)
    
    if not matrix.empty:
        pivot = matrix.pivot(index="abc_class", columns="xyz_class", values="valeur").fillna(0)
        pivot_refs = matrix.pivot(index="abc_class", columns="xyz_class", values="refs").fillna(0)
        
        fig = px.imshow(
            pivot,
            labels=dict(x=L["xyz_class"], y=L["abc_class"], color=L["value"]),
            text_auto=True,
            aspect="auto",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
        
        col1, col2 = st.columns(2)
        col1.write("**Nombre de références par cellule**")
        col1.dataframe(pivot_refs.astype(int))
        col2.write(f"**{L['value']} par cellule ({CLIENT_CURRENCY})**")
        col2.dataframe(pivot.astype(int))
    
    st.markdown("---")
    
    # Répartition par article_type
    st.subheader("Répartition par type d'article")
    
    by_type = run_query("""
        SELECT 
            article_type,
            COUNT(*) AS refs,
            COUNT(*) FILTER (WHERE is_dead_stock) AS dead,
            COUNT(*) FILTER (WHERE is_excess) AS excess,
            COUNT(*) FILTER (WHERE is_stockout_risk) AS stockout,
            ROUND(SUM(current_stock * unit_cost)::numeric, 0) AS valeur_stock,
            ROUND(SUM(trapped_value)::numeric, 0) AS trapped,
            ROUND(SUM(excess_value)::numeric, 0) AS excess_value
        FROM inventory
        GROUP BY article_type
        ORDER BY valeur_stock DESC;
    """)
    
    if not by_type.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Stock sain",
            x=by_type["article_type"],
            y=by_type["valeur_stock"] - by_type["trapped"].fillna(0) - by_type["excess_value"].fillna(0),
            marker_color="#2ECC71",
        ))
        fig.add_trace(go.Bar(
            name="Excess",
            x=by_type["article_type"],
            y=by_type["excess_value"].fillna(0),
            marker_color="#F39C12",
        ))
        fig.add_trace(go.Bar(
            name="Dormant",
            x=by_type["article_type"],
            y=by_type["trapped"].fillna(0),
            marker_color="#E74C3C",
        ))
        fig.update_layout(
            barmode="stack",
            height=400,
            yaxis_title=f"Valeur ({CLIENT_CURRENCY})",
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(
            by_type,
            column_config={
                "article_type": L["article_type"],
                "refs": L["references"],
                "dead": L["kpi_dead"],
                "excess": L["kpi_excess"],
                "stockout": L["kpi_stockout"],
                "valeur_stock": st.column_config.NumberColumn(L["value"], format=f"%d {CLIENT_CURRENCY}"),
                "trapped": st.column_config.NumberColumn("Trapped", format=f"%d {CLIENT_CURRENCY}"),
                "excess_value": st.column_config.NumberColumn("Excess", format=f"%d {CLIENT_CURRENCY}"),
            },
            use_container_width=True,
            hide_index=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# PAGE 3 — CASH RECOVERY
# ═══════════════════════════════════════════════════════════════════════════
def render_cash():
    st.title(L["nav_cash"])
    
    # Filtres
    col1, col2, col3 = st.columns(3)
    filter_type = col1.multiselect(
        L["article_type"],
        options=["PF", "SF", "COMP", "MP", "CONS", "EMB", "PDR"],
        default=None,
    )
    filter_flag = col2.selectbox(
        "Type",
        options=["Tous", "Dormant", "Excess", "Stockout risk"],
    )
    min_value = col3.number_input(
        f"Valeur min ({CLIENT_CURRENCY})",
        min_value=0,
        value=0,
        step=100,
    )
    
    # Construction de la requête
    where_clauses = []
    if filter_type:
        types_str = ", ".join([f"'{t}'" for t in filter_type])
        where_clauses.append(f"article_type IN ({types_str})")
    if filter_flag == "Dormant":
        where_clauses.append("is_dead_stock = TRUE")
    elif filter_flag == "Excess":
        where_clauses.append("is_excess = TRUE")
    elif filter_flag == "Stockout risk":
        where_clauses.append("is_stockout_risk = TRUE")
    else:
        where_clauses.append("(is_dead_stock OR is_excess OR is_stockout_risk)")
    
    if min_value > 0:
        where_clauses.append(f"(COALESCE(trapped_value, 0) + COALESCE(excess_value, 0)) >= {min_value}")
    
    where = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    df = run_query(f"""
        SELECT 
            article_code,
            product_name,
            article_type,
            article_family,
            warehouse,
            current_stock,
            unit_cost,
            days_since_movement,
            coverage_days,
            trapped_value,
            excess_value,
            CASE 
                WHEN is_dead_stock THEN 'Liquidation ({CLIENT_CURRENCY}55% récupérable)'
                WHEN is_excess THEN 'Stop réappro'
                WHEN is_stockout_risk THEN 'Commande urgente'
                ELSE '—'
            END AS action_recommandee
        FROM inventory
        WHERE {where}
        ORDER BY (COALESCE(trapped_value, 0) + COALESCE(excess_value, 0)) DESC
        LIMIT 500;
    """)
    
    st.caption(f"{len(df)} résultats affichés (max 500)")
    
    if not df.empty:
        # Métriques rapides
        col1, col2, col3 = st.columns(3)
        col1.metric("Trapped total", fmt_currency(df["trapped_value"].sum()))
        col2.metric("Excess total", fmt_currency(df["excess_value"].sum()))
        col3.metric("Impact total", fmt_currency(df["trapped_value"].sum() + df["excess_value"].sum()))
        
        st.dataframe(
            df,
            column_config={
                "article_code": "Code article",
                "product_name": "Désignation",
                "article_type": L["article_type"],
                "article_family": "Famille",
                "warehouse": "Dépôt",
                "current_stock": "Stock",
                "unit_cost": st.column_config.NumberColumn("PMP", format=f"%.2f {CLIENT_CURRENCY}"),
                "days_since_movement": "Jours sans mvt",
                "coverage_days": st.column_config.NumberColumn("Couverture (j)", format="%.0f"),
                "trapped_value": st.column_config.NumberColumn("Dormant", format=f"%.0f {CLIENT_CURRENCY}"),
                "excess_value": st.column_config.NumberColumn("Excess", format=f"%.0f {CLIENT_CURRENCY}"),
                "action_recommandee": L["action"],
            },
            use_container_width=True,
            hide_index=True,
        )
        
        # Export CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Télécharger CSV",
            csv,
            f"mecapro_cash_recovery_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
        )


# ═══════════════════════════════════════════════════════════════════════════
# PAGE 4 — SUPPLIERS
# ═══════════════════════════════════════════════════════════════════════════
def render_suppliers():
    st.title(L["nav_suppliers"])
    
    # Distribution par catégorie
    dist = run_query("""
        SELECT 
            supplier_category,
            COUNT(*) AS nb_fournisseurs,
            SUM(commandes_total) AS commandes,
            ROUND(AVG(lt_moyen)::numeric, 1) AS lt_moyen,
            ROUND(AVG(cv_lead_time)::numeric, 2) AS cv_moyen,
            ROUND(AVG(otd_when_measurable)::numeric, 1) AS otd_moyen,
            ROUND(AVG(risk_score)::numeric, 1) AS risk_moyen
        FROM v_supplier_scorecard_robust
        GROUP BY supplier_category
        ORDER BY 
            CASE supplier_category
                WHEN 'critical' THEN 1
                WHEN 'unstable' THEN 2
                WHEN 'weak' THEN 3
                WHEN 'acceptable' THEN 4
                WHEN 'solid' THEN 5
                ELSE 6
            END;
    """)
    
    if not dist.empty:
        st.subheader("Segmentation automatique")
        
        color_map = {
            "critical": "#E74C3C",
            "unstable": "#E67E22",
            "weak": "#F39C12",
            "acceptable": "#3498DB",
            "solid": "#2ECC71",
        }
        
        fig = px.bar(
            dist,
            x="supplier_category",
            y="nb_fournisseurs",
            color="supplier_category",
            color_discrete_map=color_map,
            text="nb_fournisseurs",
            title="Fournisseurs par catégorie",
        )
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(
            dist,
            column_config={
                "supplier_category": L["category"],
                "nb_fournisseurs": "Nb fournisseurs",
                "commandes": L["orders"],
                "lt_moyen": L["lead_time"],
                "cv_moyen": "CV moyen",
                "otd_moyen": L["otd_pct"],
                "risk_moyen": L["risk_score"],
            },
            use_container_width=True,
            hide_index=True,
        )
    
    st.markdown("---")
    
    # Top 10 pires
    st.subheader("Top 10 fournisseurs à risque")
    
    top = run_query("""
        SELECT 
            supplier_name,
            commandes_total,
            supplier_category,
            lt_moyen,
            lt_stddev,
            cv_lead_time,
            otd_when_measurable,
            risk_score
        FROM v_supplier_scorecard_robust
        ORDER BY risk_score DESC
        LIMIT 10;
    """)
    
    if not top.empty:
        st.dataframe(
            top,
            column_config={
                "supplier_name": L["supplier"],
                "commandes_total": L["orders"],
                "supplier_category": L["category"],
                "lt_moyen": L["lead_time"],
                "lt_stddev": "Écart-type",
                "cv_lead_time": "CV",
                "otd_when_measurable": L["otd_pct"],
                "risk_score": L["risk_score"],
            },
            use_container_width=True,
            hide_index=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# PAGE 5 — DATA QUALITY
# ═══════════════════════════════════════════════════════════════════════════
def render_quality():
    st.title(L["nav_quality"])
    
    quality = run_query("""
        SELECT 
            table_name,
            issue_code,
            issue_label_fr AS issue_label,
            affected_rows,
            severity
        FROM data_quality_log
        WHERE audit_date >= CURRENT_DATE - INTERVAL '1 day'
        ORDER BY 
            CASE severity WHEN 'critical' THEN 1 ELSE 2 END,
            affected_rows DESC;
    """)
    
    if quality.empty:
        st.warning(L["no_data"])
        return
    
    # Score global
    total_issues = quality[quality["affected_rows"] > 0].shape[0]
    critical_issues = quality[(quality["severity"] == "critical") & (quality["affected_rows"] > 0)].shape[0]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Points de contrôle", len(quality))
    col2.metric("Issues détectées", total_issues)
    col3.metric("Critiques", critical_issues, delta_color="inverse")
    
    st.markdown("---")
    
    # Tableau détaillé
    st.dataframe(
        quality,
        column_config={
            "table_name": "Table",
            "issue_code": "Code",
            "issue_label": L["issue"],
            "affected_rows": L["affected"],
            "severity": L["severity"],
        },
        use_container_width=True,
        hide_index=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════
if page == L["nav_overview"]:
    render_overview()
elif page == L["nav_stock"]:
    render_stock()
elif page == L["nav_cash"]:
    render_cash()
elif page == L["nav_suppliers"]:
    render_suppliers()
elif page == L["nav_quality"]:
    render_quality()

# Footer
st.sidebar.markdown("---")
st.sidebar.caption("SupplyStack Consulting © 2026")
