"""
Jeu de démonstration : un distributeur généraliste américain fictif.

« Acme Industrial Supply », trois agences dans l'Indiana, quelques centaines
de références : visserie, électricité, CVC, plomberie, EPI, outillage,
entretien. Les références saisonnières (été, hiver) sont rangées dans ces
lignes ordinaires, comme dans un vrai ERP : leur saison n'est connue que du
générateur, le moteur doit la retrouver dans les ventes. Tout est fictif —
entreprise, fournisseurs, chiffres — et l'écran le dit.

Volontairement non sectoriel : la démo doit parler à n'importe quel
distributeur. Les mécanismes qu'elle montre — stock dormant, surstock,
points de commande réglés sur la moyenne de l'année, fournisseurs — sont les
mêmes partout ; seuls les libellés d'articles changeraient d'un secteur à
l'autre.

L'histoire que racontent les données, parce qu'une démo doit en raconter une :
  • Les points de commande de l'ERP ont été réglés une fois, sur la demande
    moyenne de l'année : trop bas en pleine saison, trop hauts hors saison.
  • L'été 2026 a été plus frais que l'été 2025 : les acheteurs ont commandé
    pour une saison qui n'est pas venue. En octobre, le stock d'été déborde.
  • La saison d'hiver démarre : plusieurs articles d'hiver sont déjà sous leur
    besoin des trois prochains mois.
  • Une traîne de références mortes — anciens modèles, fins de série — dort
    depuis un à plusieurs années.
  • Une ligne est en consignation (propriété du fournisseur) : elle est exclue
    de tout montant, comme elle doit l'être chez un vrai client.

Déterministe : même graine, mêmes données, mêmes chiffres à chaque démo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

COMPANY = "Acme Industrial Supply"
BRANCHES = ["Indianapolis", "Fort Wayne", "Lafayette"]
BRANCH_WEIGHTS = [0.6, 0.25, 0.15]
HISTORY_MONTHS = 24

# Profils mensuels de janvier à décembre, ramenés à une moyenne de 1.
_RAW_PROFILES = {
    "summer":     [0.15, 0.15, 0.30, 0.70, 1.40, 2.20, 2.60, 2.40, 1.50, 0.60, 0.25, 0.15],
    "winter":     [2.30, 2.00, 1.30, 0.60, 0.25, 0.15, 0.10, 0.15, 0.40, 1.20, 2.00, 2.50],
    "year-round": [0.95, 0.95, 1.00, 1.05, 1.05, 1.05, 1.05, 1.05, 1.00, 1.00, 0.95, 0.90],
}
PROFILES = {k: np.array(v) / np.mean(v) for k, v in _RAW_PROFILES.items()}

# Météo : un été 2025 chaud, un été 2026 frais — d'où le stock d'été d'octobre.
WEATHER = {
    "summer": {2024: 1.00, 2025: 1.12, 2026: 0.86},
    "winter": {2024: 1.00, 2025: 1.00, 2026: 1.05},
    "year-round": {2024: 1.00, 2025: 1.00, 2026: 1.00},
}

# Fournisseurs fictifs. Le profil pilote leur comportement de livraison.
VENDORS = [
    # nom, profil, délai nominal (j), enveloppe de retour annuelle (% des achats)
    ("Great Lakes Fastener Co.", "reliable", 6, 0.06),
    ("Keystone Electric Parts", "reliable", 7, 0.05),
    ("Bluewater Plumbing Supply", "slow", 12, 0.04),
    ("Summit Copper & Fittings", "reliable", 5, 0.06),
    ("Ridgeview Safety Products", "short", 8, 0.05),
    ("Prairie Tool & Abrasives", "erratic", 10, 0.04),
    ("Northline Facility Supply", "reliable", 6, 0.08),
    ("Apex Motor Works", "erratic", 14, 0.03),
    ("Midland Seasonal Goods", "slow", 16, 0.05),
    ("Northline Controls", "slow", 11, 0.04),
    ("Harbor Pump Co.", "reliable", 21, 0.00),
]
CONSIGNMENT_VENDOR = "Harbor Pump Co."

# Modèles de références : préfixe, ligne de produits, saison, fournisseur,
# libellé, variantes (tailles rangées de la plus petite à la plus grande),
# fourchette de coût unitaire ($, de la plus petite taille à la plus grande,
# voir _unit_cost), fourchette de demande (unités/mois), conditionnement,
# sur-représentation dans le dormant (pièces chères d'anciens modèles).
TEMPLATES = [
    # ── Visserie
    ("HXB", "Fasteners", "year-round", "Great Lakes Fastener Co.", "Hex bolt {}, {} x {} in, box of 50",
     [["grade 5", "grade 8", "stainless"], ["1/4", "5/16", "3/8", "1/2", "5/8", "3/4"],
      ["1", "1-1/2", "2", "3", "4", "5", "6"]], (9, 65), (2, 40), 1, 1.0),
    ("SDS", "Fasteners", "year-round", "Great Lakes Fastener Co.", "Self-drilling screw #{} x {} in, {}, box of 100",
     [[8, 10, 12, 14], ["1/2", "3/4", "1", "1-1/2", "2"], ["zinc", "black oxide", "stainless"]], (7, 30), (3, 50), 1, 0.8),
    ("ANC", "Fasteners", "year-round", "Great Lakes Fastener Co.", "Wedge anchor {} x {} in, {}, box of 25",
     [["1/4", "3/8", "1/2", "5/8", "3/4"], ["2-1/4", "3", "3-3/4", "5", "7"], ["zinc", "stainless"]],
     (14, 90), (1, 20), 1, 1.2),
    ("NUT", "Fasteners", "year-round", "Great Lakes Fastener Co.", "Hex nut {}, {} in, box of 100",
     [["grade 5", "grade 8", "stainless", "nylon-insert"], ["1/4", "5/16", "3/8", "7/16", "1/2", "5/8", "3/4", "7/8", "1"]],
     (6, 40), (2, 30), 1, 0.8),
    ("WSH", "Fasteners", "year-round", "Great Lakes Fastener Co.", "{} washer {} in, {}, box of 100",
     [["Flat", "Lock", "Fender"], ["1/4", "5/16", "3/8", "7/16", "1/2", "5/8", "3/4", "7/8", "1"], ["zinc", "stainless"]],
     (4, 28), (2, 30), 1, 0.7),
    ("THR", "Fasteners", "year-round", "Great Lakes Fastener Co.", "Threaded rod {} in x {} ft, {}",
     [["1/4", "5/16", "3/8", "1/2", "5/8", "3/4"], [3, 6, 10], ["zinc", "stainless"]], (3, 45), (2, 35), 1, 0.9),
    # ── Électricité
    ("BKR", "Electrical", "year-round", "Keystone Electric Parts", "Circuit breaker {}-pole {}A, {}",
     [[1, 2, 3], [15, 20, 30, 40, 50, 60, 100], ["plug-on", "bolt-on"]], (8, 140), (1, 25), 1, 1.4),
    ("WNT", "Electrical", "year-round", "Keystone Electric Parts", "Wire connector, {}, {}, box of 100",
     [["twist-on", "push-in", "lever", "waterproof", "butt splice"], ["small", "medium", "large", "assorted"]],
     (6, 32), (5, 60), 1, 0.6),
    ("THN", "Electrical", "year-round", "Keystone Electric Parts", "THHN wire {} AWG, {} ft spool",
     [[14, 12, 10, 8, 6], [500, 2500]], (40, 520), (1, 12), 1, 1.0),
    ("CTR", "Electrical", "year-round", "Keystone Electric Parts", "Contactor {}P {}A, 24V coil",
     [[1, 2, 3], [25, 30, 40, 50, 60]], (9, 28), (2, 30), 1, 1.0),
    ("EMT", "Electrical", "year-round", "Keystone Electric Parts", "EMT {} {} in, {}",
     [["connector", "coupling", "strap"], ["1/2", "3/4", "1", "1-1/4", "1-1/2", "2"], ["set-screw", "compression"]],
     (0.8, 9), (10, 120), 10, 0.5),
    ("TRF", "Electrical", "year-round", "Keystone Electric Parts", "Control transformer {} VA, {}",
     [[40, 50, 75, 100, 150], ["120/240V", "multi-tap"]], (12, 60), (1, 15), 1, 1.0),
    # ── Plomberie
    ("CUF", "Plumbing", "year-round", "Summit Copper & Fittings", "Copper {} {} in, {}",
     [["coupling", "90 elbow", "45 elbow", "tee", "reducer"], ["1/4", "3/8", "1/2", "5/8", "3/4", "7/8", "1-1/8"],
      ["sweat", "press"]], (1.5, 14), (10, 150), 10, 0.4),
    ("HNG", "Plumbing", "year-round", "Summit Copper & Fittings", "Pipe hanger, {}, {} in",
     [["clevis", "J-hook", "split ring"], ["1/2", "3/4", "1", "1-1/4", "1-1/2", "2", "3", "4"]], (1.2, 12), (5, 60), 10, 0.6),
    ("BLV", "Plumbing", "year-round", "Bluewater Plumbing Supply", "Ball valve {} in, {}",
     [["1/2", "3/4", "1", "1-1/4", "1-1/2", "2"], ["threaded", "sweat", "press"]], (9, 85), (2, 30), 1, 1.0),
    ("PVC", "Plumbing", "year-round", "Bluewater Plumbing Supply", "PVC sch {} {} {} in",
     [[40, 80], ["90 elbow", "tee", "coupling", "cap", "adapter"], ["1/2", "3/4", "1", "1-1/2", "2", "3", "4"]],
     (0.6, 18), (5, 90), 10, 0.5),
    # ── EPI
    ("GLV", "Safety", "year-round", "Ridgeview Safety Products", "Work gloves {}, size {}, 12 pairs",
     [["nitrile-coated", "cut-resistant A4", "leather driver", "impact"], ["M", "L", "XL"]], (24, 90), (3, 40), 1, 0.6),
    ("EYE", "Safety", "year-round", "Ridgeview Safety Products", "Safety glasses {}, box of 12",
     [["clear", "smoke", "anti-fog", "over-glasses", "indoor/outdoor", "reader 1.5", "reader 2.0"]],
     (20, 60), (3, 30), 1, 0.5),
    ("VST", "Safety", "year-round", "Ridgeview Safety Products", "Hi-vis vest class {}, {}",
     [[2, 3], ["M/L", "XL/2XL", "3XL/4XL"]], (6, 24), (3, 30), 1, 0.8),
    # ── Outillage
    ("DRB", "Tools", "year-round", "Prairie Tool & Abrasives", "Cobalt drill bit {} in",
     [["1/8", "3/16", "1/4", "5/16", "3/8", "7/16", "1/2", "9/16", "5/8"]], (4, 28), (3, 40), 1, 0.8),
    ("RSB", "Tools", "year-round", "Prairie Tool & Abrasives", "Reciprocating saw blade {} in, {} TPI, 5-pack",
     [[6, 9, 12], [6, 10, 14, 18]], (8, 30), (3, 35), 1, 0.8),
    ("CWH", "Tools", "year-round", "Prairie Tool & Abrasives", "Cut-off wheel {} x {} in, 25-pack",
     [["4-1/2", "5", "6", "7"], ["0.040", "0.045", "1/16"]], (18, 60), (2, 25), 1, 1.0),
    ("SDK", "Tools", "year-round", "Prairie Tool & Abrasives", "Sanding disc {} in, {} grit, 50-pack",
     [["4-1/2", "5", "7"], [36, 60, 80, 120, 180, 220]], (12, 45), (2, 25), 1, 0.8),
    ("HSW", "Tools", "year-round", "Prairie Tool & Abrasives", "Bi-metal hole saw {} in",
     [["3/4", "7/8", "1", "1-1/8", "1-1/4", "1-1/2", "1-3/4", "2", "2-1/4", "2-1/2", "3", "3-1/2", "4", "4-1/2", "5"]],
     (9, 48), (1, 12), 1, 1.0),
    ("PWT", "Tools", "year-round", "Prairie Tool & Abrasives", "Cordless {} kit, 20V",
     [["drill/driver", "impact driver", "hammer drill", "circular saw", "reciprocating saw", "angle grinder",
       "oscillating tool", "rotary hammer"]], (130, 420), (0.5, 6), 1, 2.2),
    # ── Entretien
    ("JAN", "Janitorial", "year-round", "Northline Facility Supply", "{} cleaner, {}",
     [["All-purpose", "Degreaser", "Glass", "Disinfectant", "Floor"], ["1 gal", "5 gal", "20 gal drum"]],
     (8, 95), (3, 40), 1, 0.6),
    ("TWL", "Janitorial", "year-round", "Northline Facility Supply", "Paper towel, {}, case",
     [["roll 8 in", "multifold", "C-fold", "center-pull"]], (22, 65), (4, 40), 1, 0.5),
    ("LNR", "Janitorial", "year-round", "Northline Facility Supply", "Trash liner {} gal, {} mil, case",
     [[16, 33, 45, 55, 60, 95], ["0.9", "1.5", "2.0"]], (18, 70), (3, 40), 1, 0.6),
    # ── Références d'été, rangées dans leurs lignes ordinaires : aucune ligne ne
    #    trahit la saison, que seul le générateur connaît (champ « saison »).
    ("FAN", "HVAC", "summer", "Apex Motor Works", "{} fan {} in",
     [["Drum", "Pedestal", "Wall-mount", "Exhaust"], [18, 24, 30, 36, 42]], (60, 380), (0.5, 10), 1, 1.2),
    ("PAC", "HVAC", "summer", "Apex Motor Works", "Portable spot cooler {} BTU, {}",
     [[8000, 10000, 12000, 14000, 18000, 24000, 36000], ["115V", "230V"]], (380, 1900), (0.4, 5), 1, 1.6),
    ("EVC", "HVAC", "summer", "Midland Seasonal Goods", "Evaporative cooler {} CFM",
     [[1300, 2100, 3100, 5300, 6500, 11000]], (220, 1100), (0.4, 5), 1, 1.4),
    ("CAP", "Electrical", "summer", "Keystone Electric Parts", "Run capacitor {}/{} MFD 440V",
     [[25, 30, 35, 40, 45, 50, 55, 60], [5, 7.5]], (6, 18), (4, 55), 5, 1.0),
    ("CLT", "Safety", "summer", "Ridgeview Safety Products", "Cooling {}",
     [["towels, 10-pack", "neck gaiters, 12-pack", "vest", "hard-hat liners, 10-pack", "electrolyte mix, case"]],
     (18, 75), (2, 30), 1, 0.8),
    ("HOS", "Plumbing", "summer", "Bluewater Plumbing Supply", "Commercial hose {} in x {} ft",
     [["5/8", "3/4"], [25, 50, 75, 100]], (25, 95), (1, 20), 1, 0.8),
    # ── Références d'hiver, même principe : la ligne CVC mêle pics d'été et d'hiver.
    ("ICE", "Janitorial", "winter", "Midland Seasonal Goods", "Ice melt, {}, {} lb bag",
     [["rock salt", "calcium chloride", "magnesium chloride", "pet-safe blend"], [25, 50]], (8, 42), (5, 120), 1, 0.5),
    ("SNW", "Janitorial", "winter", "Midland Seasonal Goods", "Snow {}, {}",
     [["shovel", "pusher", "scraper"], ["18 in", "24 in", "36 in"]], (18, 70), (1, 20), 1, 0.8),
    ("HTR", "HVAC", "winter", "Apex Motor Works", "{} heater, {}",
     [["Portable electric", "Propane forced-air", "Infrared", "Construction"], ["1500W", "30k BTU", "60k BTU", "5kW"]],
     (60, 480), (0.5, 8), 1, 1.6),
    ("WGL", "Safety", "winter", "Ridgeview Safety Products", "Insulated gloves {}, size {}, 12 pairs",
     [["thermal-lined", "waterproof", "heavy-duty"], ["M", "L", "XL"]], (40, 120), (2, 25), 1, 0.8),
    ("IGN", "HVAC", "winter", "Northline Controls", "Hot surface igniter, {} {}",
     [["SiNi 80V", "SiC 120V", "SiNi 120V", "mini 80V"], ["flat", "round", "universal"]], (15, 48), (3, 30), 1, 1.0),
    # ── Consignation — propriété du fournisseur, exclue de tout montant
    ("PMP", "Consigned", "year-round", CONSIGNMENT_VENDOR, "Booster pump {} HP, {}",
     [["1/2", "3/4", "1", "1-1/2", "2"], ["single-phase", "three-phase"]], (450, 1900), (0.3, 4), 1, 0.0),
]

DEAD_SHARE = 0.14          # part des références hors consignation sans vente depuis plus d'un an
PARTIAL_MONTH = 0.45       # le mois en cours n'est entamé qu'à moitié
DEMAND_SCALE = 2.5         # volume d'un distributeur régional à trois agences
STAINLESS_FACTOR = 2.2     # l'inox coûte le double et plus du zingué de même taille


@dataclass
class DemoData:
    company: str
    as_of: pd.Period
    branches: list
    items: pd.DataFrame        # fiche article : item, desc, category, season, vendor, unit_cost, pack, moq,
                               #                 lead_time_days, consigned
    stock: pd.DataFrame        # rapport de valorisation : item, desc, line, branch, qty, cost, value
    sales: pd.DataFrame        # ventes : item, month (Period), qty
    on_order: pd.Series        # item -> quantité en commande
    po_lines: pd.DataFrame     # historique d'achats : vendor, item, dates commande/promise/réception, quantités, prix
    vendors: pd.DataFrame      # vendor, profile, lead_time_days, allowance_pct, allowance_used_share


def _unit_cost(combo, variants, cost_rng, u: float) -> float:
    """Coût unitaire qui monte avec la taille : une cheville de 1/4 ne peut pas
    coûter plus cher qu'une de 1/2. Un seul tirage `u` par article, pour ne pas
    décaler le flux aléatoire (dormant, ventes, commandes)."""
    lo, hi = cost_rng
    # Dimensions de taille : toutes leurs valeurs contiennent un chiffre, et les
    # listes sont déjà rangées de la plus petite à la plus grande.
    sized = [(vals.index(v), len(vals) - 1) for v, vals in zip(combo, variants)
             if len(vals) > 1 and all(re.search(r"\d", str(x)) for x in vals)]
    if not sized:
        cost = lo + (hi - lo) * u   # identique à l'ancien rng.uniform(lo, hi)
    else:
        s = sum(r for r, _ in sized) / sum(n for _, n in sized)   # rang pondéré par le nombre de tailles
        cost = lo * (hi / lo) ** s * (0.90 + 0.20 * u)            # échelle géométrique, ±10 % de bruit
        if "stainless" in combo:
            cost *= STAINLESS_FACTOR
    return round(cost, 2)


def _items(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for prefix, cat, season, vendor, fmt, variants, cost_rng, dem_rng, pack, dead_w in TEMPLATES:
        for n, combo in enumerate(product(*variants), start=1):
            cost = _unit_cost(combo, variants, cost_rng, float(rng.uniform()))
            # Demande de base log-uniforme : beaucoup de petits rouleurs, quelques gros.
            lo, hi = np.log(dem_rng[0]), np.log(dem_rng[1])
            rows.append(dict(
                item=f"{prefix}-{1000 + n * 7:05d}", desc=fmt.format(*combo), category=cat,
                season=season, vendor=vendor, unit_cost=cost,
                base_demand=DEMAND_SCALE * float(np.exp(rng.uniform(lo, hi))),
                pack=pack, moq=pack, dead_weight=dead_w, consigned=(vendor == CONSIGNMENT_VENDOR)))
    items = pd.DataFrame(rows)

    # Le dormant tombe de préférence sur les pièces chères d'anciens modèles.
    eligible = items.index[~items["consigned"]]
    w = items.loc[eligible, "dead_weight"].to_numpy()
    n_dead = int(round(DEAD_SHARE * len(eligible)))
    dead_idx = rng.choice(eligible, size=n_dead, replace=False, p=w / w.sum())
    items["dead"] = False
    items.loc[dead_idx, "dead"] = True
    return items


def _sales(items: pd.DataFrame, as_of: pd.Period, rng: np.random.Generator) -> pd.DataFrame:
    months = [as_of - HISTORY_MONTHS + k for k in range(HISTORY_MONTHS)] + [as_of]
    rows = []
    for it in items.itertuples():
        profile = PROFILES[it.season]
        # Dernière vente d'un article mort : il y a 13 à 36 mois. Au-delà de 24,
        # il n'apparaît plus du tout dans l'historique.
        last = as_of - int(rng.integers(13, 37)) if it.dead else None
        for mo in months:
            if last is not None and mo > last:
                continue
            lam = it.base_demand * profile[mo.month - 1] * WEATHER[it.season].get(mo.year, 1.0)
            if mo == as_of:
                lam *= PARTIAL_MONTH
            q = int(rng.poisson(lam))
            if q:
                rows.append((it.item, mo, q))
    return pd.DataFrame(rows, columns=["item", "month", "qty"])


def _on_hand(items: pd.DataFrame, sales: pd.DataFrame, as_of: pd.Period, rng: np.random.Generator) -> pd.Series:
    grid = sales.groupby(["item", "month"])["qty"].sum().unstack(fill_value=0)

    def ly(months):
        cols = [m for m in months if m in grid.columns]
        return grid[cols].sum(axis=1).reindex(items["item"]).fillna(0).to_numpy()

    next6_ly = ly([as_of - 12 + k for k in range(6)])
    next3_ly = ly([as_of - 11 + k for k in range(3)])
    d = items["base_demand"].to_numpy()
    u = rng.uniform(size=len(items))
    qty = np.zeros(len(items))

    season = items["season"].to_numpy()
    dead = items["dead"].to_numpy()
    consigned = items["consigned"].to_numpy()
    expensive = items["unit_cost"].to_numpy() > 150

    summer = (season == "summer") & ~dead
    # 70 % des articles d'été débordent : commandés pour un été qui n'est pas venu.
    over = summer & (u < 0.70)
    qty[over] = next6_ly[over] + d[over] * rng.uniform(2.0, 7.0, over.sum())
    rest = summer & ~over
    qty[rest] = next6_ly[rest] * rng.uniform(0.15, 0.6, rest.sum())

    winter = (season == "winter") & ~dead
    # La saison démarre : beaucoup d'articles d'hiver sont sous leur besoin des 3 prochains mois.
    qty[winter] = next3_ly[winter] * rng.uniform(0.05, 0.9, winter.sum())

    flat = (season == "year-round") & ~dead & ~consigned
    heavy = flat & (u < 0.12)
    qty[flat & ~heavy] = d[flat & ~heavy] * rng.uniform(0.05, 2.0, (flat & ~heavy).sum())
    qty[heavy] = d[heavy] * rng.uniform(7.0, 11.0, heavy.sum())

    qty[dead] = np.where(expensive[dead], rng.integers(3, 16, dead.sum()), rng.integers(20, 160, dead.sum()))
    qty[consigned] = d[consigned] * rng.uniform(1.0, 3.0, consigned.sum())

    pack = items["pack"].to_numpy()
    qty = np.maximum(0, np.round(qty))
    qty = np.where(pack > 1, np.ceil(qty / pack) * pack, qty)
    return pd.Series(qty.astype(int), index=items["item"])


def _stock_rows(items: pd.DataFrame, on_hand: pd.Series, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for it in items.itertuples():
        q = int(on_hand[it.item])
        if q <= 0:
            continue
        split = rng.multinomial(q, BRANCH_WEIGHTS)
        for branch, bq in zip(BRANCHES, split):
            if bq:
                rows.append(dict(item=it.item, desc=it.desc, line=it.category, branch=branch,
                                 qty=float(bq), cost=it.unit_cost, value=round(bq * it.unit_cost, 2)))
    return pd.DataFrame(rows)


def _on_order(items: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    d = items["base_demand"].to_numpy()
    season = items["season"].to_numpy()
    u = rng.uniform(size=len(items))
    q = np.zeros(len(items))
    winter = (season == "winter") & (u < 0.45)
    q[winter] = d[winter] * rng.uniform(0.3, 1.5, winter.sum())
    # Des commandes d'été passées fin août arrivent encore : c'est ce qu'il faut bloquer.
    summer = (season == "summer") & (u < 0.15)
    q[summer] = d[summer] * rng.uniform(0.5, 2.0, summer.sum())
    flat = (season == "year-round") & (u < 0.25)
    q[flat] = d[flat] * rng.uniform(0.5, 1.5, flat.sum())
    q[items["dead"].to_numpy() | items["consigned"].to_numpy()] = 0
    pack = items["pack"].to_numpy()
    q = np.where(pack > 1, np.ceil(np.round(q) / pack) * pack, np.round(q))
    return pd.Series(q.astype(int), index=items["item"])


def _po_lines(items: pd.DataFrame, as_of: pd.Period, vendors: pd.DataFrame,
              rng: np.random.Generator) -> pd.DataFrame:
    """Douze mois de lignes de commande fournisseur, livrées selon le profil du fournisseur."""
    start = (as_of - 12).to_timestamp()
    end = as_of.to_timestamp() - pd.Timedelta(days=1)
    span = (end - start).days
    vinfo = vendors.set_index("vendor")
    rows = []
    po = 50000
    for it in items[~items["dead"]].itertuples():
        n_lines = max(1, int(rng.poisson(min(it.base_demand, 40) / 3)))
        lt0 = int(vinfo.loc[it.vendor, "lead_time_days"])
        prof = vinfo.loc[it.vendor, "profile"]
        for _ in range(n_lines):
            po += 1
            ordered = start + pd.Timedelta(days=int(rng.integers(0, span)))
            promised = ordered + pd.Timedelta(days=lt0)
            if prof == "reliable":
                actual = lt0 + rng.normal(-1.0, 1.0)
            elif prof == "slow":
                actual = lt0 + rng.normal(3.0, 2.2)
            elif prof == "erratic":
                actual = lt0 + rng.normal(2.0, 7.0)
            else:  # short : à l'heure, mais livre partiellement
                actual = lt0 + rng.normal(-0.8, 1.0)
            received = ordered + pd.Timedelta(days=max(1, int(round(actual))))
            qty = max(it.pack, int(np.ceil(it.base_demand * rng.uniform(0.6, 1.6) / it.pack)) * it.pack)
            rec = qty
            if prof == "short" and rng.uniform() < 0.35:
                rec = int(qty * rng.uniform(0.5, 0.9))
            elif rng.uniform() < 0.04:
                rec = int(qty * rng.uniform(0.7, 0.95))
            rows.append(dict(po_id=f"PO{po}", vendor=it.vendor, item=it.item,
                             order_date=ordered.date(), promised_date=promised.date(),
                             received_date=received.date(), qty_ordered=qty, qty_received=rec,
                             unit_price=it.unit_cost))
    return pd.DataFrame(rows)


def generate(seed: int = 7, as_of: str = "2026-10") -> DemoData:
    rng = np.random.default_rng(seed)
    as_of_p = pd.Period(as_of, freq="M")

    vendors = pd.DataFrame(VENDORS, columns=["vendor", "profile", "lead_time_days", "allowance_pct"])
    # Part de l'enveloppe de retour déjà consommée cette année (valeur de démo).
    vendors["allowance_used_share"] = np.round(rng.uniform(0.2, 0.7, len(vendors)), 2)

    items = _items(rng)
    sales = _sales(items, as_of_p, rng)
    on_hand = _on_hand(items, sales, as_of_p, rng)
    stock = _stock_rows(items, on_hand, rng)
    on_order = _on_order(items, rng)
    po_lines = _po_lines(items, as_of_p, vendors, rng)
    lt = vendors.set_index("vendor")["lead_time_days"]
    items = items.assign(lead_time_days=items["vendor"].map(lt).astype(int))

    return DemoData(
        company=COMPANY, as_of=as_of_p, branches=BRANCHES,
        items=items.drop(columns=["base_demand", "dead_weight", "dead"]),
        stock=stock, sales=sales, on_order=on_order, po_lines=po_lines, vendors=vendors)
