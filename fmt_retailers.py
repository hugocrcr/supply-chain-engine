"""
Mise en forme à l'américaine, partagée par le moteur et les écrans.

Aucune dépendance à Streamlit : le moteur s'en sert pour rédiger ses phrases,
les écrans pour leurs cartes et leurs tableaux. Un seul endroit décide de la
façon dont un montant s'écrit.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def money(x, compact: bool = False) -> str:
    """« $1,234 » ou, en compact, « $1.23M » / « $412k » / « $950 »."""
    if _bad(x):
        return "—"
    x = float(x)
    sign = "-" if x < 0 else ""
    a = abs(x)
    if compact:
        if a >= 1_000_000:
            return f"{sign}${a / 1_000_000:.2f}M"
        if a >= 10_000:
            return f"{sign}${a / 1_000:.0f}k"
        if a >= 1_000:
            return f"{sign}${a / 1_000:.1f}k"
    return f"{sign}${a:,.0f}"


def num(x, decimals: int = 0) -> str:
    if _bad(x):
        return "—"
    return f"{float(x):,.{decimals}f}"


def pct(x, decimals: int = 0) -> str:
    if _bad(x):
        return "—"
    return f"{float(x) * 100:.{decimals}f}%"


def month(p) -> str:
    """« Oct 2026 »."""
    if isinstance(p, pd.Period):
        return p.strftime("%b %Y")
    return "—"


def month_short(p) -> str:
    """« Oct '26 » — pour les axes de graphiques."""
    if isinstance(p, pd.Period):
        return p.strftime("%b '%y")
    return "—"


def day(d) -> str:
    """Date au format américain : « 10/14/2026 »."""
    if isinstance(d, (date, pd.Timestamp)):
        return d.strftime("%m/%d/%Y")
    return "—"


def plural(n: int, word: str, plural_word: str = "") -> str:
    """« 1 item » / « 12 items »."""
    return f"{n:,} {word if n == 1 else (plural_word or word + 's')}"
