"""
Charte commune des écrans de la démo distributeur.

Reprend l'identité visuelle du tableau de bord SupplyStack existant — police
Plus Jakarta Sans, violet #6355ff, cartes KPI « Aurora » — pour que la démo
montrée aux distributeurs américains ressemble au produit.

Tout écran passe par ces fonctions : une seule façon d'écrire un montant,
de dessiner une carte, de styler un graphique ou un tableau.
"""

from __future__ import annotations

import html

import streamlit as st

import engine
import fmt

PRIMARY = "#6355ff"
TONES = {
    "danger": "#e5484d",     # perte probable : dormant
    "warning": "#f79009",    # trésorerie garée : excédent saisonnier, surstock
    "success": "#12b76a",
    "info": "#3b82f6",
    "": "#94a3b8",
}
INK, MUTED, LINE = "#0f172a", "#64748b", "#eef0f6"
PROFILE_COLORS = {"Summer peak": "#f79009", "Winter peak": "#3b82f6", "Steady": "#94a3b8"}


@st.cache_resource(show_spinner="Loading demo data…")
def get_model() -> engine.Model:
    return engine.build_model()


def inject_css() -> None:
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea {
    font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif !important;
}
.stApp { background: #f5f6fb; }
.block-container { padding: 1.6rem 3rem 2.4rem 3rem; max-width: 1500px; }
h1, h2, h3 { color: #0f172a !important; letter-spacing: -0.01em; }
.ss-title { font-size: 26px; font-weight: 800; color: #0f172a; letter-spacing: -0.02em; margin: 0; }
.ss-sub { font-size: 14px; color: #64748b; margin: 4px 0 18px 0; max-width: 980px; line-height: 1.5; }
.ss-section { font-size: 11px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase;
    color: #94a3b8; margin: 26px 0 10px 0; }
.ss-note { font-size: 12.5px; color: #64748b; line-height: 1.55; margin: 6px 0 0 0; }
.kpi-card { background: #fff; border: 1px solid rgba(15,23,42,0.06); border-radius: 16px; padding: 16px 17px;
    min-height: 124px; display: flex; flex-direction: column; gap: 9px;
    box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 12px 28px -20px rgba(15,23,42,0.22); }
.kpi-top { display: flex; align-items: center; gap: 7px; }
.kpi-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.kpi-label { font-size: 10px; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase;
    color: #94a3b8; line-height: 1.2; }
.kpi-i { position: relative; margin-left: auto; flex: none; width: 15px; height: 15px; display: inline-flex;
    align-items: center; justify-content: center; border-radius: 50%; background: #eef0f6; color: #94a3b8;
    font-size: 10px; font-weight: 700; font-family: Georgia, serif; cursor: help; outline: none; }
.kpi-i:hover, .kpi-i:focus { background: #6355ff; color: #fff; }
.kpi-tip { position: absolute; top: calc(100% + 9px); right: -7px; width: 240px; background: #fff; color: #475569;
    border: 1px solid rgba(15,23,42,0.08); font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11.5px;
    font-weight: 500; line-height: 1.55; text-transform: none; letter-spacing: normal; text-align: left;
    padding: 11px 13px; border-radius: 12px; box-shadow: 0 12px 28px -14px rgba(15,23,42,0.28);
    opacity: 0; visibility: hidden; transition: opacity .16s ease; z-index: 9999; pointer-events: none; }
.kpi-i:hover .kpi-tip, .kpi-i:focus .kpi-tip { opacity: 1; visibility: visible; }
[data-testid="column"], [data-testid="stHorizontalBlock"] { overflow: visible !important; }
.kpi-value { font-size: 26px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.05; color: #0f172a; }
.kpi-sub { font-size: 12px; color: #64748b; line-height: 1.4; margin-top: auto; }
.stPlotlyChart { background: #fff; border: 1px solid rgba(15,23,42,0.06); border-radius: 18px; padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 16px 36px -26px rgba(15,23,42,0.2); }
[data-testid="stDataFrame"] { background: #fff; border-radius: 14px; }
.ss-brief { background: #fff; border: 1px solid rgba(15,23,42,0.06); border-left: 3px solid #6355ff;
    border-radius: 14px; padding: 14px 18px; }
.ss-brief li { font-size: 14px; color: #0f172a; line-height: 1.55; margin: 4px 0; }
.ss-demo { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: #6355ff; background: #eeecff; border-radius: 6px; padding: 3px 8px; }
.ss-foot { font-size: 11.5px; color: #94a3b8; margin-top: 34px; padding-top: 12px;
    border-top: 1px solid rgba(15,23,42,0.06); }
section[data-testid="stSidebar"] { background: #0f1220; }
section[data-testid="stSidebar"] * { color: #cbd5e1; }
.ss-brand { font-size: 10.5px; font-weight: 700; letter-spacing: 0.18em; color: #a5aec4 !important; }
.ss-client { font-size: 15px; font-weight: 700; color: #fff !important; margin-top: 6px; }
.ss-meta { font-size: 12px; color: #94a3b8 !important; margin-top: 2px; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)


def sidebar(m: engine.Model) -> None:
    with st.sidebar:
        st.markdown(f"""
<div class="ss-brand">SUPPLYSTACK CONSULTING</div>
<div class="ss-client">{html.escape(m.company)}</div>
<div class="ss-meta">{len(m.branches)} branches · {fmt.num(m.skus_on_hand)} SKUs on hand<br>
Data through {fmt.month(m.as_of - 1)} · demo</div>
""", unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<span class="ss-demo">Demo data — fictitious distributor</span>'
                f'<p class="ss-title">{html.escape(title)}</p>'
                + (f'<p class="ss-sub">{html.escape(subtitle)}</p>' if subtitle else ""),
                unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="ss-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<p class="ss-note">{html.escape(text)}</p>', unsafe_allow_html=True)


def kpi_card(label: str, value: str, tone: str = "", sub: str = "", info: str = "") -> str:
    """Carte KPI. `tone` : danger (perte probable), warning (trésorerie garée), success, info, ou vide."""
    color = TONES.get(tone, TONES[""])
    value_color = color if tone in ("danger", "warning", "success") else INK
    info_html = (f'<span class="kpi-i" tabindex="0">i<span class="kpi-tip">{html.escape(info)}</span></span>'
                 if info else "")
    sub_html = f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else ""
    return (f'<div class="kpi-card"><div class="kpi-top"><span class="kpi-dot" style="background:{color}"></span>'
            f'<span class="kpi-label">{html.escape(label)}</span>{info_html}</div>'
            f'<div class="kpi-value" style="color:{value_color}">{html.escape(value)}</div>{sub_html}</div>')


def kpi_row(cards: list, links: list = None) -> None:
    cols = st.columns(len(cards))
    for i, (col, card) in enumerate(zip(cols, cards)):
        col.markdown(card, unsafe_allow_html=True)
        # page_link plutôt qu'un <a href> : navigation côté client, sans recharger l'app.
        if links and links[i]:
            page, label = links[i]
            col.page_link(page, label=label, icon=":material/arrow_forward:")


def brief(lines: list) -> None:
    items = "".join(f"<li>{html.escape(t)}</li>" for t in lines)
    st.markdown(f'<div class="ss-brief"><ul style="margin:0;padding-left:18px;">{items}</ul></div>',
                unsafe_allow_html=True)


def style_fig(fig, height: int = 360, legend: bool = False):
    fig.update_layout(
        height=height, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#334155", size=12.5),
        margin=dict(l=0, r=12, t=10, b=34),
        xaxis=dict(gridcolor=LINE, zeroline=False, linecolor=LINE, automargin=True),
        yaxis=dict(gridcolor=LINE, zeroline=False, linecolor=LINE, automargin=True),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, x=0, font=dict(size=11.5)),
        hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#fff", family="Plus Jakarta Sans")),
    )
    return fig


# Types de colonnes : une seule façon d'afficher chaque nature de donnée.
#
# Les formats intégrés de Streamlit (« dollar », « localized », « percent »)
# suivent la langue du navigateur : sur un Mac en français, « $44,163 » devient
# « 44 163 $ » — en plein partage d'écran avec un prospect américain. On formate
# donc par un Styler pandas, qui fige l'affichage à l'américaine tout en gardant
# la valeur numérique dessous : le tri par colonne reste numérique (vérifié dans
# un navigateur en locale fr).
_FORMATTERS = {
    "money": lambda v: fmt.money(v),
    "money_cents": lambda v: "—" if fmt._bad(v) else f"${float(v):,.2f}",
    "int": lambda v: fmt.num(v),
    "dec1": lambda v: fmt.num(v, 1),
    "pct": lambda v: fmt.pct(v),          # attend une fraction : 0.91 → « 91% »
}


def table(df, spec: dict, height: int = None) -> None:
    """Tableau standard.

    spec = {"colonne": ("Libellé à l'écran", "money" | "money_cents" | "int" | "dec1" | "pct" | "bool" | "text")}
    Seules les colonnes du spec sont affichées, dans cet ordre. L'index n'est jamais affiché.
    Pour l'identifiant article, passer d'abord par df.reset_index().
    """
    cols = [c for c in spec if c in df.columns]
    view = df[cols].reset_index(drop=True)
    cc = st.column_config
    config, formats = {}, {}
    for c in cols:
        label, kind = spec[c]
        if kind == "bool":
            config[c] = cc.CheckboxColumn(label)
        elif kind in _FORMATTERS:
            config[c] = cc.Column(label)
            formats[c] = _FORMATTERS[kind]
        else:
            config[c] = cc.TextColumn(label)
    data = view.style.format(formats) if formats else view
    kwargs = dict(hide_index=True, width="stretch", column_config=config)
    if height:
        kwargs["height"] = height
    st.dataframe(data, **kwargs)


def footer() -> None:
    st.markdown('<div class="ss-foot">Demo data. Acme Industrial Supply and every vendor shown are fictitious; '
                'figures are generated to illustrate the method. SupplyStack Consulting.</div>',
                unsafe_allow_html=True)
