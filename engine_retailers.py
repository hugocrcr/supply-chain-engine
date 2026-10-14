"""
Moteur de la démo distributeur : tous les calculs, aucune ligne de Streamlit.

Les deux chiffres de tête — excédent saisonnier et dormant — sortent de
`snapshot.analyse()`, la fonction même du snapshot gratuit. Un prospect qui a
reçu son snapshot retrouve donc dans la démo exactement les mêmes définitions,
au dollar près.

Règles de doctrine tenues ici, pas dans les écrans :
  • excédent saisonnier, dormant et surstock ne s'additionnent jamais ;
  • un écart de point de commande ne se monétise jamais. Un point de commande
    est une consigne, pas une quantité détenue : les montants ne portent que
    sur du stock physiquement présent, ou sur une commande que l'ERP passerait
    réellement ;
  • le stock en consignation (propriété du fournisseur) est exclu de tout montant.

Le point de commande de l'ERP et le point de commande recommandé utilisent la
MÊME formule. Seule la fenêtre de demande change : la moyenne de l'année pour
l'ERP, les trois prochains mois — lus sur l'an dernier — pour la
recommandation. C'est toute la démonstration.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snapshot"))
import snapshot as snap  # noqa: E402

import demo_data  # noqa: E402
import fmt  # noqa: E402

Z = 1.65                # niveau de service visé : ~95 %
CV = 0.5                # variabilité journalière supposée de la demande
HORIZON = 6             # mois — même horizon que le snapshot
REORDER_WINDOW = 3      # mois de demande à venir pris en compte par la recommandation
CARRY_RATE = 0.20       # coût de possession annuel
SEASONAL_RATIO = 2.0    # même seuil de saisonnalité que le snapshot
LOWER_FACTOR = 0.7      # « à baisser » : recommandé ≤ 70 % du point de commande ERP
RAISE_FACTOR = 1.3      # « à relever » : recommandé ≥ 130 % du point de commande ERP
MIN_CHANGE = 2          # écart minimal en unités : en dessous, c'est l'arrondi qui parle, pas la saison
FILL_THRESHOLD = 0.98   # une ligne est « complète » si ≥ 98 % de la quantité est livrée
SHORT_SHIP_FILL = 0.85  # segment « livraisons partielles » : taux de lignes complètes sous ce seuil
ERRATIC_SD = 4          # segment « erratique » : écart-type du délai réel au-delà de 4 jours
LATE_DRIFT = 2          # segment « toujours en retard » : délai moyen réel > délai ERP + 2 jours
RETURN_WINDOW = 24      # mois : au-delà, l'article est supposé sorti du catalogue fournisseur

AGING_BUCKETS = ["12–18 months", "18–24 months", "24+ months"]

STATUS_LABELS = {"seasonal": "Seasonal carryover", "dead": "Dead stock", "overstock": "Overstock", "ok": "—"}

# Définitions affichées à l'écran — un seul texte par notion, partagé par toutes les pages.
DEFINITIONS = {
    "inventory": "Value of stock on your books, from your own valuation report. Consigned stock is excluded.",
    "seasonal_carryover": (
        "On items whose season just ended: stock on hand beyond everything you sold over the same "
        "six months last year. Not lost — parked until next season. Deliberately conservative."),
    "carrying_cost": "What it costs to hold that carryover until next season, at 20% a year.",
    "dead_stock": "Items on hand with no net sales in the last twelve months.",
    "overstock": (
        "On items without a marked season: stock beyond everything you sold over the same six months "
        "last year."),
    "erp_rop": "Your ERP reorder point today: set once, on the average demand of the year.",
    "rec_rop": (
        "Same formula, different window: demand over the next three months, read on what you sold in "
        "those same months last year."),
    "buy_now": "Items at or below their recommended reorder point. Quantities rounded up to the vendor's pack.",
    "hold": (
        "Items your ERP would reorder now, on SKUs whose seasonal reorder point is 70% or less of the "
        "ERP setting and at least 2 units lower (or down to zero) — the coming season no longer needs them."),
    "returns": (
        "Dead stock that could go back to the vendor under your annual stock-rotation allowance. "
        "Demo assumption: items whose last sale was less than 24 months ago are still in the vendor's "
        "catalog and eligible; older ones are not. Real terms vary by vendor."),
    "at_risk": (
        "On hand plus on order won't last through the lead time set in your ERP, at the pace you sold in "
        "these same months last year. Every one of these is on this week's buy list."),
    "lower_rule": "Listed when the seasonal reorder point is 70% or less of the ERP setting and at least 2 units lower.",
    "raise_rule": "Listed when the seasonal reorder point is 130% or more of the ERP setting and at least 2 units higher.",
    "aging": "Months since the last sale. 24+ also covers items with no sale anywhere in the history on file.",
    "vendors_to_call": "Distinct vendors with at least one SKU on this week's order-now list.",
    "lead_time_drift": "Actual average lead time minus the lead time your ERP plans with, in days.",
    "segments": (
        "Checked in this order: short-ships (fill rate under 85%), erratic (lead time varies by more than "
        "4 days), consistently late (actual lead time more than 2 days over the ERP setting), otherwise "
        "reliable."),
    "otd": "Share of PO lines received on or before the promised date.",
    "fill_rate": "Share of PO lines received at 98% or more of the ordered quantity.",
    "lead_time_sd": ("A vendor whose deliveries swing widely needs a bigger safety buffer than one that is slow "
                     "but predictable."),
}

SEGMENT_ACTIONS = {
    "Short-ships": "Chase backorders and track fill rate on every receipt.",
    "Erratic": "Carry more safety stock on this vendor's items — the lead time can't be trusted.",
    "Consistently late": "Update the lead time in your ERP to what this vendor actually delivers.",
    "Reliable": "No action needed.",
}


def reorder_point(daily, lead_time_days) -> np.ndarray:
    """Demande pendant le délai + stock de sécurité. Même formule pour l'ERP et la recommandation."""
    daily = np.asarray(daily, dtype=float)
    lt = np.asarray(lead_time_days, dtype=float)
    return np.ceil(daily * lt + Z * daily * CV * np.sqrt(lt))


def _round_up(qty, pack) -> np.ndarray:
    qty = np.asarray(qty, dtype=float)
    pack = np.maximum(np.asarray(pack, dtype=float), 1)
    return np.ceil(qty / pack) * pack


def _days(months: list) -> int:
    return int(sum(m.days_in_month for m in months))


def _peak_label(row: np.ndarray, months: list) -> str:
    """Les trois mois consécutifs (en boucle) les plus vendus : « Jun–Aug »."""
    if row.sum() <= 0:
        return "—"
    sums = [row[k] + row[(k + 1) % 12] + row[(k + 2) % 12] for k in range(12)]
    k = int(np.argmax(sums))
    return f"{months[k].strftime('%b')}–{months[(k + 2) % 12].strftime('%b')}"


@dataclass
class Model:
    company: str
    as_of: pd.Period
    branches: list
    headline: snap.Result          # source unique des deux chiffres de tête
    items: pd.DataFrame            # une ligne par article possédé, tous les champs dérivés
    consigned_value: float
    consigned_items: int
    lower: pd.DataFrame            # points de commande à baisser avant la bascule
    raise_now: pd.DataFrame        # points de commande à relever maintenant
    buy_now: pd.DataFrame          # à commander cette semaine
    hold: pd.DataFrame             # ce que l'ERP commanderait et qu'il faut bloquer
    dead: pd.DataFrame             # dormant, avec ancienneté
    returns: pd.DataFrame          # par fournisseur : enveloppe de retour et ce qu'elle couvre
    return_candidates: pd.DataFrame
    suppliers: pd.DataFrame
    monthly_by_profile: pd.DataFrame
    brief: list = field(default_factory=list)
    _grid: pd.DataFrame = None
    _profile_months: list = None

    # ── Fenêtres ────────────────────────────────────────────────────────────
    @property
    def profile_months(self) -> list:
        """Les 12 mois complets avant le mois d'analyse."""
        return self._profile_months

    @property
    def skus_on_hand(self) -> int:
        """Articles possédés avec du stock en main — le même compte partout."""
        return int((self.items["on_hand"] > 0).sum())

    @property
    def status_counts(self) -> dict:
        """Nombre d'articles par nature : dead / seasonal / overstock / ok."""
        return self.items["status"].value_counts().to_dict()

    @property
    def at_risk_count(self) -> int:
        return int(self.items["at_risk"].sum())

    @property
    def vendors_to_update(self) -> pd.DataFrame:
        """Fournisseurs dont le délai ERP est à corriger (hors consignation)."""
        s = self.suppliers
        return s[(s["segment"] == "Consistently late") & ~s["consignment"]]

    @property
    def fleet_otd(self) -> float:
        """Ponctualité pondérée par le nombre de lignes de commande."""
        s = self.suppliers
        return float((s["otd"] * s["lines"]).sum() / s["lines"].sum())

    @property
    def fleet_fill_rate(self) -> float:
        s = self.suppliers
        return float((s["fill_rate"] * s["lines"]).sum() / s["lines"].sum())

    @property
    def top_idle(self) -> pd.DataFrame:
        """Où l'argent dort : excédent saisonnier et dormant, du plus gros au plus petit. Jamais totalisé."""
        it = self.items
        return it[it["status"].isin(["seasonal", "dead"])].sort_values("idle_value", ascending=False)

    @property
    def next_window_label(self) -> str:
        """« Nov–Jan » : les mois couverts par la recommandation."""
        a = self.as_of + 1
        b = self.as_of + REORDER_WINDOW
        return f"{a.strftime('%b')}–{b.strftime('%b')}"

    # ── Graphique d'un article ──────────────────────────────────────────────
    def item_profile(self, item: str) -> pd.DataFrame:
        """Ventes mensuelles sur 24 mois, puis les 6 mois à venir lus sur l'an dernier, avec le point
        de commande ERP (plat) et le point de commande saisonnier (mois par mois)."""
        it = self.items.loc[item]
        hist = [self.as_of - demo_data.HISTORY_MONTHS + k for k in range(demo_data.HISTORY_MONTHS)]
        future = [self.as_of + k for k in range(HORIZON)]
        row = self._grid.loc[item] if item in self._grid.index else pd.Series(dtype=float)

        def sold(mo):
            return float(row.get(mo, 0.0))

        # Point de commande saisonnier par mois calendaire M : les 3 mois qui suivent M, lus sur les
        # 12 derniers — exactement ce que rec_rop fait pour as_of. La colonne « Today » du graphique
        # montre donc la même valeur que la colonne Recommended.
        prof = self._profile_months
        by_moy = {}
        for k in range(12):
            window = [prof[(k + 1 + j) % 12] for j in range(REORDER_WINDOW)]
            daily = max(sum(sold(m) for m in window), 0.0) / _days(window)   # même plancher que next_ly
            by_moy[prof[k].month] = float(reorder_point(daily, it["lead_time_days"]))

        rows = []
        for mo in hist + future:
            is_future = mo >= self.as_of
            rows.append(dict(
                month=mo, label=fmt.month_short(mo), future=is_future,
                sold=None if is_future else sold(mo),
                last_year=sold(mo - 12) if is_future else None,
                erp_rop=float(it["erp_rop"]), seasonal_rop=by_moy[mo.month]))
        return pd.DataFrame(rows)


def build_model(seed: int = 7, as_of: str = "2026-10") -> Model:
    d = demo_data.generate(seed, as_of)
    as_of_p = d.as_of
    master = d.items.set_index("item")
    consigned = set(master.index[master["consigned"]])

    owned_stock = d.stock[~d.stock["item"].isin(consigned)]
    consigned_stock = d.stock[d.stock["item"].isin(consigned)]

    # ── Les deux chiffres de tête : la fonction même du snapshot ────────────
    head = snap.analyse(owned_stock, d.sales, as_of_p, HORIZON, SEASONAL_RATIO, CARRY_RATE, snap.Notes())

    grid = d.sales.groupby(["item", "month"])["qty"].sum().unstack(fill_value=0.0)

    def total(months):
        cols = [m for m in months if m in grid.columns]
        return grid[cols].sum(axis=1) if cols else pd.Series(0.0, index=grid.index)

    profile = [as_of_p - 12 + k for k in range(12)]
    next_ly = [as_of_p + 1 - 12 + k for k in range(REORDER_WINDOW)]

    # ── Fiche par article possédé ───────────────────────────────────────────
    it = master.loc[~master["consigned"]].copy()
    on_hand = owned_stock.groupby("item")["qty"].sum()
    it["on_hand"] = on_hand.reindex(it.index).fillna(0.0)
    it["on_order"] = d.on_order.reindex(it.index).fillna(0).astype(float)
    it["position"] = it["on_hand"] + it["on_order"]
    it["value"] = owned_stock.groupby("item")["value"].sum().reindex(it.index).fillna(0.0)
    it["sales_12m"] = total(profile).reindex(it.index).fillna(0.0).clip(lower=0)
    it["next_ly"] = total(next_ly).reindex(it.index).fillna(0.0).clip(lower=0)
    it["daily_annual"] = it["sales_12m"] / _days(profile)
    it["daily_next"] = it["next_ly"] / _days(next_ly)
    it["erp_rop"] = reorder_point(it["daily_annual"], it["lead_time_days"])
    it["rec_rop"] = reorder_point(it["daily_next"], it["lead_time_days"])
    it["erp_order_qty"] = np.maximum(it["moq"], _round_up(it["daily_annual"] * 30, it["pack"]))
    it["days_cover"] = np.where(it["daily_next"] > 0, it["position"] / it["daily_next"].replace(0, np.nan), np.inf)

    # Profil de saison lu sur les ventes, jamais sur une étiquette : chez un vrai client il n'y en a pas.
    prof_grid = grid.reindex(index=it.index, columns=profile, fill_value=0.0).fillna(0.0)
    arr = prof_grid.to_numpy()
    tot = arr.sum(axis=1)
    jja = prof_grid[[m for m in profile if m.month in (6, 7, 8)]].sum(axis=1).to_numpy()
    djf = prof_grid[[m for m in profile if m.month in (12, 1, 2)]].sum(axis=1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        it["profile"] = np.select(
            [tot <= 0, jja / tot >= 0.40, djf / tot >= 0.40],
            ["No sales", "Summer peak", "Winter peak"], default="Steady")
    it["peak"] = [_peak_label(arr[i], profile) for i in range(len(it))]
    # Un article régulier n'a pas de saison : afficher « Aug–Oct » sur une boîte de vis serait du bruit.
    it.loc[it["profile"].isin(["Steady", "No sales"]), "peak"] = "—"

    hi = head.items
    it["status"] = hi["category"].reindex(it.index).fillna("ok")
    it["idle_value"] = hi["idle_value"].reindex(it.index).fillna(0.0)
    it["excess_units"] = (it["on_hand"] - hi["sales_next_window_ly"].reindex(it.index).fillna(0.0)).clip(lower=0)
    it.loc[it["status"] == "dead", "excess_units"] = it["on_hand"]
    it["last_sale_month"] = hi["last_sale_month"].reindex(it.index)
    it["status_label"] = it["status"].map(STATUS_LABELS)
    it = it.rename_axis("item")

    active = it["status"] != "dead"
    # Une seule définition, partagée par toutes les pages : le stock disponible plus les
    # commandes en cours ne tiennent pas le délai fournisseur au rythme de la saison qui vient.
    it["at_risk"] = active & (it["daily_next"] > 0) & (it["position"] < it["daily_next"] * it["lead_time_days"])

    # ── La bascule : points de commande à baisser / relever ─────────────────
    # Un article régulier dont le point de commande passe de 3 à 2 ne relève pas de la saison mais de
    # l'arrondi : il gonflerait la liste et décrédibiliserait les autres.
    lower = it[active & (it["erp_rop"] >= 2) & (it["rec_rop"] <= LOWER_FACTOR * it["erp_rop"])
               & (it["erp_rop"] - it["rec_rop"] >= MIN_CHANGE)].copy()
    lower["change"] = lower["rec_rop"] - lower["erp_rop"]

    raise_now = it[active & (it["rec_rop"] >= RAISE_FACTOR * it["erp_rop"])
                   & (it["rec_rop"] - it["erp_rop"] >= MIN_CHANGE)].copy()
    raise_now["change"] = raise_now["rec_rop"] - raise_now["erp_rop"]
    raise_now = raise_now.sort_values(["at_risk", "days_cover"], ascending=[False, True])

    # ── Liste d'achats de la semaine ────────────────────────────────────────
    buy = it[active & (it["rec_rop"] > 0) & (it["position"] <= it["rec_rop"])].copy()
    target = buy["rec_rop"] + buy["daily_next"] * 30
    buy["order_qty"] = _round_up(np.maximum(target - buy["position"], buy["moq"]), buy["pack"])
    buy["order_value"] = buy["order_qty"] * buy["unit_cost"]
    buy["erp_would_order"] = buy["position"] <= buy["erp_rop"]
    buy = buy.sort_values(["vendor", "order_value"], ascending=[True, False])

    # Ce que l'ERP commanderait cette semaine et que la saison ne justifie plus :
    # une commande réelle, pas un écart de paramètre. Même seuil de 70 % que « à baisser », sinon
    # un article régulier à peine moins vendu passerait pour « plus nécessaire ». Pas de plancher
    # erp_rop ≥ 2 en revanche : un 1 → 0 hors saison est un vrai blocage.
    material = (it["erp_rop"] - it["rec_rop"] >= MIN_CHANGE) | (it["rec_rop"] == 0)
    hold = it[active & (it["rec_rop"] <= LOWER_FACTOR * it["erp_rop"]) & material
              & (it["position"] <= it["erp_rop"]) & (it["position"] > it["rec_rop"])].copy()
    hold["po_value"] = hold["erp_order_qty"] * hold["unit_cost"]
    hold = hold.sort_values("po_value", ascending=False)

    # Baisser ne change quelque chose que là où l'ERP va déclencher : d'abord les articles à
    # bloquer (définition de hold, pas recalculée), puis les plus proches du seuil ERP. Trier
    # sur les dollars en stock ferait croire que la baisse les récupère.
    lower["erp_reorders_now"] = lower.index.isin(hold.index)
    lower["trigger_ratio"] = lower["position"] / lower["erp_rop"]   # erp_rop ≥ 2 sur cette liste
    lower = lower.sort_values(["erp_reorders_now", "trigger_ratio", "change"], ascending=[False, True, True])

    # ── Dormant ─────────────────────────────────────────────────────────────
    dead = it[it["status"] == "dead"].copy()

    def months_since(p):
        return (as_of_p - p).n if isinstance(p, pd.Period) else np.nan

    dead["months_idle"] = dead["last_sale_month"].map(months_since)
    first_hist = as_of_p - demo_data.HISTORY_MONTHS
    dead["aging"] = np.select(
        [dead["months_idle"].isna() | (dead["months_idle"] >= RETURN_WINDOW), dead["months_idle"] >= 18],
        [AGING_BUCKETS[2], AGING_BUCKETS[1]], default=AGING_BUCKETS[0])
    dead["last_sale"] = [fmt.month(p) if isinstance(p, pd.Period) else f"Before {fmt.month(first_hist)}"
                         for p in dead["last_sale_month"]]
    dead = dead.sort_values("idle_value", ascending=False)

    # ── Retours fournisseurs ────────────────────────────────────────────────
    po = d.po_lines.copy()
    po["spend"] = po["qty_received"] * po["unit_price"]
    spend = po.groupby("vendor")["spend"].sum()
    vend = d.vendors[d.vendors["vendor"] != demo_data.CONSIGNMENT_VENDOR].set_index("vendor").copy()
    vend["purchases_12m"] = spend.reindex(vend.index).fillna(0.0)
    vend["allowance"] = vend["allowance_pct"] * vend["purchases_12m"]
    vend["used"] = vend["allowance"] * vend["allowance_used_share"]
    vend["remaining"] = (vend["allowance"] - vend["used"]).clip(lower=0)
    vend["dead_value"] = dead.groupby("vendor")["idle_value"].sum().reindex(vend.index).fillna(0.0)

    cand_rows = []
    for v, room in vend["remaining"].items():
        cum = 0.0
        for item, r in dead[dead["vendor"] == v].iterrows():
            # Hypothèse de démo : au-delà de 24 mois sans vente, l'article est sorti du catalogue
            # fournisseur et n'est plus repris.
            eligible = r["aging"] != AGING_BUCKETS[2]
            fits = eligible and cum + r["idle_value"] <= room
            if fits:
                cum += r["idle_value"]
            cand_rows.append(dict(item=item, vendor=v, desc=r["desc"], on_hand=r["on_hand"],
                                  value=r["idle_value"], aging=r["aging"], eligible=eligible,
                                  fits_allowance=fits))
    candidates = pd.DataFrame(cand_rows, columns=["item", "vendor", "desc", "on_hand", "value", "aging",
                                                  "eligible", "fits_allowance"])
    candidates["return_status"] = np.select(
        [candidates["fits_allowance"], candidates["eligible"]],
        ["Fits allowance", "Eligible, over allowance"], default="Past return window")
    returnable = candidates[candidates["fits_allowance"]].groupby("vendor")["value"].sum()
    vend["returnable_value"] = returnable.reindex(vend.index).fillna(0.0)
    vend["returnable_items"] = (candidates[candidates["fits_allowance"]].groupby("vendor").size()
                                .reindex(vend.index).fillna(0).astype(int))
    returns = vend.reset_index().sort_values("returnable_value", ascending=False)

    # ── Fournisseurs ────────────────────────────────────────────────────────
    po["lead_time"] = (pd.to_datetime(po["received_date"]) - pd.to_datetime(po["order_date"])).dt.days
    po["days_late"] = (pd.to_datetime(po["received_date"]) - pd.to_datetime(po["promised_date"])).dt.days
    po["on_time"] = po["days_late"] <= 0
    po["complete"] = po["qty_received"] >= FILL_THRESHOLD * po["qty_ordered"]
    nominal = d.vendors.set_index("vendor")["lead_time_days"]
    sup = po.groupby("vendor").agg(
        lines=("po_id", "size"), spend_12m=("spend", "sum"), otd=("on_time", "mean"),
        fill_rate=("complete", "mean"), lead_time_avg=("lead_time", "mean"), lead_time_sd=("lead_time", "std"))
    sup["avg_days_late"] = po[~po["on_time"]].groupby("vendor")["days_late"].mean().reindex(sup.index)
    sup["erp_lead_time"] = nominal.reindex(sup.index)
    sup["drift_days"] = sup["lead_time_avg"] - sup["erp_lead_time"]
    sup["segment"] = np.select(
        [sup["fill_rate"] < SHORT_SHIP_FILL, sup["lead_time_sd"] > ERRATIC_SD, sup["drift_days"] > LATE_DRIFT],
        ["Short-ships", "Erratic", "Consistently late"], default="Reliable")
    sup["action"] = sup["segment"].map(SEGMENT_ACTIONS)
    sup["consignment"] = sup.index == demo_data.CONSIGNMENT_VENDOR
    suppliers = sup.reset_index().sort_values(["segment", "spend_12m"], ascending=[True, False])

    # ── Courbes de demande par profil, pour la vue d'ensemble ───────────────
    hist = [as_of_p - demo_data.HISTORY_MONTHS + k for k in range(demo_data.HISTORY_MONTHS)]
    g = grid.reindex(index=it.index, columns=hist, fill_value=0.0).fillna(0.0)
    monthly = g.groupby(it["profile"]).sum().T
    monthly.index.name = "month"
    monthly = monthly.drop(columns=[c for c in monthly.columns if c == "No sales"]).reset_index()

    model = Model(
        company=d.company, as_of=as_of_p, branches=d.branches, headline=head, items=it,
        consigned_value=float(consigned_stock["value"].sum()),
        consigned_items=int(consigned_stock["item"].nunique()),
        lower=lower, raise_now=raise_now, buy_now=buy, hold=hold, dead=dead, returns=returns,
        return_candidates=candidates, suppliers=suppliers, monthly_by_profile=monthly,
        _grid=grid, _profile_months=profile)
    model.brief = _brief(model)
    return model


def _brief(m: Model) -> list:
    """Le brief de la semaine : ce qu'un acheteur doit faire, en cinq lignes au plus."""
    out = []
    h = m.headline
    summer_lower = m.lower[m.lower["profile"] == "Summer peak"]
    n = len(summer_lower)
    if n:
        # Même cause que DEFINITIONS["erp_rop"] : l'ERP est réglé sur la moyenne de l'année, pas sur le pic.
        verb, obj, them = ("carries", "a reorder point", "it") if n == 1 else ("carry", "reorder points", "them")
        out.append(f"{fmt.plural(n, 'summer-peak SKU')} still {verb} {obj} set on the year's average "
                   f"demand, higher than the {m.next_window_label} season needs. Lower {them} before more "
                   f"stock arrives.")
    at_risk = m.at_risk_count
    if at_risk:
        # Délai ERP, pas le délai réel : c'est celui que at_risk utilise, la ligne fournisseur suit.
        they = "It's" if at_risk == 1 else "They're"
        out.append(f"{fmt.plural(at_risk, 'SKU')} won't last through the lead time your ERP plans with, at "
                   f"the pace of the {m.next_window_label} season. {they} on this week's buy list.")
    if len(m.hold):
        out.append(f"Your ERP would place {fmt.money(m.hold['po_value'].sum())} of orders this week that the "
                   f"coming season no longer needs. Hold them.")
    returnable = m.returns["returnable_value"].sum()
    if returnable > 0:
        out.append(f"{fmt.money(returnable)} of dead stock fits inside your vendors' remaining return "
                   f"allowances this year.")
    late = m.vendors_to_update
    if len(late):
        v = late.sort_values("spend_12m", ascending=False).iloc[0]
        out.append(f"{v['vendor']} delivers in {v['lead_time_avg']:.0f} days on average. Your ERP still "
                   f"plans with {v['erp_lead_time']:.0f}.")
    if h.seasonal_value > 0 and len(out) < 5:
        out.append(f"{fmt.money(h.seasonal_value)} of seasonal stock is parked until next season — about "
                   f"{fmt.money(h.carry_cost)} to carry it.")
    return out[:5]
