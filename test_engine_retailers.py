"""
Tests du moteur de la démo distributeur.

Ce qu'ils protègent, par ordre d'importance :
  1. les deux chiffres de tête sont ceux du snapshot, au dollar près ;
  2. la doctrine : consignation exclue, natures exclusives, montants adossés
     à du stock physique ou à une commande réelle ;
  3. la mécanique : même formule de point de commande, listes cohérentes ;
  4. l'histoire de la démo : chaque écran a quelque chose à montrer.

Lancer : .venv/bin/python distrib/test_engine.py
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "snapshot")]

import demo_data  # noqa: E402
import engine  # noqa: E402
import snapshot as snap  # noqa: E402

M = engine.build_model()


class HeadlineTest(unittest.TestCase):

    def test_headline_is_the_snapshot_to_the_dollar(self):
        d = demo_data.generate()
        consigned = set(d.items.loc[d.items["consigned"], "item"])
        owned = d.stock[~d.stock["item"].isin(consigned)]
        r = snap.analyse(owned, d.sales, d.as_of, 6, 2.0, 0.20, snap.Notes())
        self.assertAlmostEqual(M.headline.seasonal_value, r.seasonal_value, places=2)
        self.assertAlmostEqual(M.headline.dead_value, r.dead_value, places=2)
        self.assertAlmostEqual(M.headline.total_value, r.total_value, places=2)

    def test_snapshot_is_presentable_on_demo_data(self):
        self.assertEqual(M.headline.notes.blockers, [])

    def test_deterministic(self):
        again = engine.build_model()
        self.assertEqual(M.headline.seasonal_value, again.headline.seasonal_value)
        self.assertEqual(len(M.buy_now), len(again.buy_now))


class DoctrineTest(unittest.TestCase):

    def test_consigned_stock_is_excluded_everywhere(self):
        consigned = set(demo_data.generate().items.query("consigned")["item"])
        self.assertTrue(consigned)
        for name in ("items", "lower", "raise_now", "buy_now", "hold", "dead"):
            self.assertFalse(set(getattr(M, name).index) & consigned, name)
        self.assertNotIn(demo_data.CONSIGNMENT_VENDOR, set(M.returns["vendor"]))
        self.assertGreater(M.consigned_value, 0)

    def test_each_item_has_exactly_one_status(self):
        self.assertTrue(M.items["status"].isin(["dead", "seasonal", "overstock", "ok"]).all())

    def test_idle_amounts_match_the_headline(self):
        it = M.items
        self.assertAlmostEqual(it.loc[it["status"] == "seasonal", "idle_value"].sum(),
                               M.headline.seasonal_value, places=2)
        self.assertAlmostEqual(it.loc[it["status"] == "dead", "idle_value"].sum(),
                               M.headline.dead_value, places=2)

    def test_idle_value_never_exceeds_stock_value(self):
        self.assertTrue((M.items["idle_value"] <= M.items["value"] + 0.01).all())

    def test_hold_value_is_a_real_purchase_order(self):
        # Montant = quantité que l'ERP commanderait × coût — jamais un écart de point de commande.
        h = M.hold
        np.testing.assert_allclose(h["po_value"], h["erp_order_qty"] * h["unit_cost"])


class ReorderPointTest(unittest.TestCase):

    def test_formula(self):
        # 2 u/j sur 9 jours : 18 + 1,65 × 2 × 0,5 × 3 = 22,95 → 23
        self.assertEqual(engine.reorder_point(2.0, 9), 23)
        self.assertEqual(engine.reorder_point(0.0, 14), 0)

    def test_erp_and_recommendation_use_the_same_formula(self):
        it = M.items
        np.testing.assert_array_equal(it["erp_rop"], engine.reorder_point(it["daily_annual"], it["lead_time_days"]))
        np.testing.assert_array_equal(it["rec_rop"], engine.reorder_point(it["daily_next"], it["lead_time_days"]))

    def test_lower_and_raise_rules(self):
        lo, hi = M.lower, M.raise_now
        self.assertTrue((lo["rec_rop"] <= engine.LOWER_FACTOR * lo["erp_rop"]).all())
        self.assertTrue((hi["rec_rop"] >= engine.RAISE_FACTOR * hi["erp_rop"]).all())
        self.assertFalse(set(lo.index) & set(hi.index))
        self.assertFalse((lo["status"] == "dead").any())

    def test_item_profile_matches_the_recommendation(self):
        # La colonne « Today » du graphique doit montrer le point recommandé du tableau, pour chaque article listé.
        for item in list(M.lower.index) + list(M.raise_now.index):
            p = M.item_profile(item)
            self.assertEqual(len(p), demo_data.HISTORY_MONTHS + engine.HORIZON)
            today = p.loc[p["month"] == M.as_of, "seasonal_rop"].iloc[0]
            self.assertEqual(float(today), float(M.items.loc[item, "rec_rop"]), item)
            self.assertTrue(p.loc[p["future"], "sold"].isna().all())
            self.assertTrue(p.loc[~p["future"], "last_year"].isna().all())

    def test_lower_starts_with_what_the_erp_is_about_to_reorder(self):
        lo = M.lower
        self.assertTrue(lo["erp_reorders_now"].iloc[0])
        self.assertEqual(set(lo.index[lo["erp_reorders_now"]]), set(lo.index) & set(M.hold.index))
        flags = lo["erp_reorders_now"].tolist()
        self.assertEqual(flags, sorted(flags, reverse=True))


class BuyListTest(unittest.TestCase):

    def test_buy_now(self):
        b = M.buy_now
        self.assertTrue((b["position"] <= b["rec_rop"]).all())
        self.assertTrue((b["order_qty"] % b["pack"] == 0).all())
        self.assertTrue((b["order_qty"] >= b["moq"]).all())

    def test_hold(self):
        h = M.hold
        self.assertTrue((h["position"] <= h["erp_rop"]).all())
        self.assertTrue((h["position"] > h["rec_rop"]).all())
        self.assertTrue((h["rec_rop"] <= engine.LOWER_FACTOR * h["erp_rop"]).all())
        self.assertFalse(set(h.index) & set(M.buy_now.index))


class ReturnsAndSuppliersTest(unittest.TestCase):

    def test_returns_stay_inside_the_allowance(self):
        r = M.returns.set_index("vendor")
        self.assertTrue((r["returnable_value"] <= r["remaining"] + 0.01).all())
        c = M.return_candidates
        self.assertFalse(c.loc[c["fits_allowance"], "aging"].eq("24+ months").any())

    def test_supplier_rates(self):
        s = M.suppliers
        for col in ("otd", "fill_rate"):
            self.assertTrue(s[col].between(0, 1).all(), col)
        self.assertTrue(set(s["segment"]) <= set(engine.SEGMENT_ACTIONS))


class SharedFieldsTest(unittest.TestCase):
    """Les champs que plusieurs pages affichent doivent venir d'un seul endroit."""

    def test_every_at_risk_item_is_on_the_buy_list(self):
        at_risk = set(M.items.index[M.items["at_risk"]])
        self.assertTrue(at_risk)
        self.assertLessEqual(at_risk, set(M.buy_now.index))
        self.assertEqual(M.at_risk_count, len(at_risk))
        self.assertTrue(M.raise_now["at_risk"].sum() <= M.at_risk_count)

    def test_peak_only_for_seasonal_profiles(self):
        steady = M.items[M.items["profile"].isin(["Steady", "No sales"])]
        self.assertTrue((steady["peak"] == "—").all())

    def test_return_status_and_aging(self):
        c = M.return_candidates
        self.assertTrue(set(c["return_status"]) <= {"Fits allowance", "Eligible, over allowance", "Past return window"})
        self.assertTrue(set(M.dead["aging"]) <= set(engine.AGING_BUCKETS))
        self.assertTrue((c.loc[c["return_status"] == "Past return window", "aging"] == engine.AGING_BUCKETS[2]).all())

    def test_counts_are_consistent(self):
        self.assertEqual(M.status_counts.get("dead", 0), len(M.dead))
        self.assertEqual(M.skus_on_hand, len(M.headline.items))
        self.assertTrue(0 < M.fleet_otd < 1 and 0 < M.fleet_fill_rate < 1)
        self.assertTrue(M.top_idle["status"].isin(["seasonal", "dead"]).all())


class StoryTest(unittest.TestCase):
    """La démo doit avoir quelque chose à montrer sur chaque écran."""

    def test_every_screen_has_content(self):
        T = M.headline.total_value
        self.assertTrue(0.05 <= M.headline.seasonal_value / T <= 0.14)
        self.assertTrue(0.10 <= M.headline.dead_value / T <= 0.20)
        for name in ("lower", "raise_now", "buy_now", "hold", "dead"):
            self.assertGreater(len(getattr(M, name)), 0, name)
        self.assertGreater(int(M.raise_now["at_risk"].sum()), 0)
        self.assertGreater(M.returns["returnable_value"].sum(), 0)
        self.assertGreaterEqual(len(set(M.suppliers["segment"])), 3)
        self.assertGreaterEqual(len(M.brief), 4)

    def test_season_profiles_are_read_from_sales(self):
        counts = M.items["profile"].value_counts()
        for p in ("Summer peak", "Winter peak", "Steady"):
            self.assertGreater(counts.get(p, 0), 0, p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
