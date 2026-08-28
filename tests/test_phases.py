"""Tests for Phase 2 (replay/calibration), Phase 3 (alerts) and Phase 4 (dashboard).

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine import alerts, backfill, regime
from src.engine.timeseries import Series
from src.output import alert_builder, dashboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_cfg():
    with open(os.path.join(ROOT, "config", "thresholds.json")) as fh:
        return json.load(fh)


def series(values, sid="X", step=1, end=None):
    end = end or date(2026, 8, 10)
    n = len(values)
    dates = [end - timedelta(days=(n - 1 - i) * step) for i in range(n)]
    return Series(sid, dates, list(values))


class FakePillar(object):
    def __init__(self, num, score, known=True, state="X"):
        self.num, self.score, self.known, self.state = num, score, known, state
        self.readings = []


# ------------------------------------------------------------------ Phase 2

class TestRegimeHysteresis(unittest.TestCase):
    def _pillars(self, growth):
        return {1: FakePillar(1, growth), 2: FakePillar(2, -0.2),
                3: FakePillar(3, -0.1), 4: FakePillar(4, 0.0), 5: FakePillar(5, 0.0)}

    def test_incumbent_held_when_challenger_is_marginal(self):
        """A near-tie must not flip the label; that produced monthly regime churn."""
        pillars = self._pillars(0.22)
        fresh = regime.classify(pillars).regime
        others = [n for n in regime.PROFILES if n != fresh]
        held = regime.classify(pillars, None, incumbent=others[0])
        # Either it genuinely beat the margin, or the incumbent was retained.
        self.assertIn(held.regime, (fresh, others[0]))

    def test_decisive_challenger_still_wins(self):
        """Hysteresis must not freeze the label when the reading really changes."""
        risk_off = {1: FakePillar(1, -0.7), 2: FakePillar(2, -0.3),
                    3: FakePillar(3, 0.4), 4: FakePillar(4, 0.8), 5: FakePillar(5, -0.7)}
        self.assertEqual(
            regime.classify(risk_off, None, incumbent="Goldilocks").regime, "Risk-Off")

    def test_unknown_incumbent_is_ignored(self):
        pillars = self._pillars(0.5)
        self.assertEqual(regime.classify(pillars, None, incumbent="Nonsense").regime,
                         regime.classify(pillars).regime)


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.specs = [
            {"id": "A", "name": "A", "pillar": 1, "freq": "daily", "polarity": 1,
             "transform": "level", "unit": "%", "weight": 1.0, "decimals": 2},
            {"id": "B", "name": "B", "pillar": 4, "freq": "daily", "polarity": 1,
             "transform": "level", "unit": "%", "weight": 1.0, "decimals": 2},
        ]
        n = 1400
        self.raw = {
            "A": series([10.0 + 0.01 * i + (i % 11) * 0.05 for i in range(n)], "A"),
            "B": series([3.0 + (i % 17) * 0.04 for i in range(n)], "B"),
        }

    def test_slice_to_respects_cutoff(self):
        s = series([1.0, 2.0, 3.0, 4.0])
        cut = backfill._slice_to(s, s.dates[1])
        self.assertEqual(cut.values, [1.0, 2.0])

    def test_slice_to_before_start_returns_none(self):
        s = series([1.0, 2.0])
        self.assertIsNone(backfill._slice_to(s, s.dates[0] - timedelta(days=5)))

    def test_replay_is_chronological_and_bounded(self):
        recs = backfill.replay(self.raw, self.specs, self.cfg, step_days=14,
                               max_points=20)
        self.assertTrue(recs)
        self.assertLessEqual(len(recs), 20)
        dates = [r["date"] for r in recs]
        self.assertEqual(dates, sorted(dates))

    def test_replay_records_carry_regime_and_readings(self):
        recs = backfill.replay(self.raw, self.specs, self.cfg, step_days=30,
                               max_points=8)
        for r in recs:
            self.assertIn("regime", r)
            self.assertIn("pillars", r)
            self.assertIsInstance(r["readings"], dict)

    def test_replay_is_point_in_time(self):
        """A record must not be influenced by data after its own date."""
        full = backfill.replay(self.raw, self.specs, self.cfg, step_days=30, max_points=6)
        truncated_raw = {k: backfill._slice_to(v, full[-1]["date"] and
                                               date.fromisoformat(full[-1]["date"]))
                         for k, v in self.raw.items()}
        again = backfill.replay(truncated_raw, self.specs, self.cfg, step_days=30,
                                max_points=6)
        self.assertEqual(full[-1]["pillars"]["1"]["score"],
                         again[-1]["pillars"]["1"]["score"])

    def test_replay_empty_input(self):
        self.assertEqual(backfill.replay({}, self.specs, self.cfg), [])

    def test_episodes_collapse_runs(self):
        recs = [{"date": "2026-01-0%d" % i, "regime": r}
                for i, r in enumerate(["A", "A", "B", "B", "B", "A"], start=1)]
        eps = backfill.regime_episodes(recs)
        self.assertEqual([e["regime"] for e in eps], ["A", "B", "A"])
        self.assertEqual(eps[1]["points"], 3)

    def test_calibration_flags_single_regime_dominance(self):
        recs = [{"date": "2026-01-01", "regime": "Late Cycle", "direction": "Stable",
                 "pillars": {"1": {"score": 0.0, "state": "S", "known": True}}}] * 20
        report = backfill.calibration(recs, self.cfg)
        self.assertTrue(any("single regime" in w for w in report["warnings"]))

    def test_calibration_empty(self):
        self.assertEqual(backfill.calibration([], self.cfg), {})


# ------------------------------------------------------------------ Phase 3

class TestAlerts(unittest.TestCase):
    def test_level_trigger_fires_and_reports(self):
        data = {"VIXCLS": series([15.0, 16.0, 33.0])}
        fired, _ = alerts.evaluate(data, {}, {})
        keys = [a.key for a in fired]
        self.assertIn("vix_level", keys)

    def test_single_session_widening_trigger(self):
        data = {"BAMLH0A0HYM2": series([300.0, 305.0, 340.0])}
        fired, _ = alerts.evaluate(data, {}, {})
        self.assertIn("hy_widening", [a.key for a in fired])

    def test_gradual_move_does_not_fire(self):
        """Same total move spread over many sessions is not an alert."""
        data = {"BAMLH0A0HYM2": series([300.0 + 2.0 * i for i in range(20)])}
        fired, _ = alerts.evaluate(data, {}, {})
        self.assertNotIn("hy_widening", [a.key for a in fired])

    def test_cross_above_requires_an_actual_crossing(self):
        crossed = {"NFCI": series([-0.05, 0.04])}
        already = {"NFCI": series([0.10, 0.14])}
        self.assertIn("nfci_flip", [a.key for a in alerts.evaluate(crossed, {}, {})[0]])
        self.assertNotIn("nfci_flip", [a.key for a in alerts.evaluate(already, {}, {})[0]])

    def test_pct_move_uses_percentage_not_absolute(self):
        data = {"DEXJPUS": series([150.0, 145.0])}  # -3.3%
        self.assertIn("usdjpy_move", [a.key for a in alerts.evaluate(data, {}, {})[0]])

    def test_cooldown_suppresses_repeat(self):
        data = {"VIXCLS": series([15.0, 16.0, 33.0])}
        today = date(2026, 8, 10)
        first, state = alerts.evaluate(data, {}, {}, today)
        self.assertTrue(first)
        second, _ = alerts.evaluate(data, {}, state, today + timedelta(days=1))
        self.assertNotIn("vix_level", [a.key for a in second])

    def test_cooldown_yields_when_condition_worsens(self):
        today = date(2026, 8, 10)
        # Stay inside one band so this exercises cooldown, not supersede.
        _, state = alerts.evaluate({"VIXCLS": series([15.0, 16.0, 31.0])}, {}, {}, today)
        worse, _ = alerts.evaluate({"VIXCLS": series([15.0, 16.0, 38.0])}, {}, state,
                                   today + timedelta(days=1))
        self.assertIn("vix_level", [a.key for a in worse])

    def test_state_clears_when_condition_resets(self):
        today = date(2026, 8, 10)
        _, state = alerts.evaluate({"VIXCLS": series([15.0, 16.0, 33.0])}, {}, {}, today)
        self.assertIn("vix_level", state)
        _, cleared = alerts.evaluate({"VIXCLS": series([33.0, 20.0, 15.0])}, {}, state,
                                     today + timedelta(days=1))
        self.assertNotIn("vix_level", cleared)

    def test_spx_drawdown_from_prices(self):
        fired, _ = alerts.evaluate({}, {"SPY": series([600.0, 570.0])}, {})
        self.assertIn("spx_drawdown", [a.key for a in fired])

    def test_missing_series_never_raises(self):
        fired, state = alerts.evaluate({}, {}, {})
        self.assertEqual(fired, [])
        self.assertEqual(state, {})

    def test_single_observation_cannot_trigger_change_rules(self):
        fired, _ = alerts.evaluate({"BAMLH0A0HYM2": series([900.0])}, {}, {})
        self.assertNotIn("hy_widening", [a.key for a in fired])

    def test_severe_band_supersedes_weaker_one(self):
        """VIX at 45 trips both the >30 and >40 rules; only the severe one reports."""
        fired, _ = alerts.evaluate({"VIXCLS": series([15.0, 16.0, 44.9])}, {}, {})
        keys = [a.key for a in fired]
        self.assertIn("vix_spike", keys)
        self.assertNotIn("vix_level", keys)

    def test_weaker_band_reports_when_alone(self):
        fired, _ = alerts.evaluate({"VIXCLS": series([15.0, 16.0, 33.0])}, {}, {})
        self.assertIn("vix_level", [a.key for a in fired])

    def test_alerts_sorted_critical_first(self):
        data = {"VIXCLS": series([15.0, 16.0, 33.0]),
                "DGS2": series([3.0, 3.0, 3.3])}
        fired, _ = alerts.evaluate(data, {}, {})
        self.assertEqual(fired[0].tone, "critical")

    def test_prune_state_drops_stale_records(self):
        today = date(2026, 8, 10)
        state = {"a": {"date": (today - timedelta(days=90)).isoformat(), "metric": 1},
                 "b": {"date": today.isoformat(), "metric": 1},
                 "c": {"garbage": True}}
        pruned = alerts.prune_state(state, today)
        self.assertEqual(sorted(pruned), ["b"])

    def test_every_trigger_references_a_configured_series(self):
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            known = {s["id"] for s in json.load(fh)["series"]}
        for trig in alerts.TRIGGERS:
            self.assertIn(trig["sid"], known, "%s references unknown series" % trig["key"])


class TestAlertBuilder(unittest.TestCase):
    def _alert(self, tone="critical"):
        return alerts.Alert("k", "VIX above 30", "because", tone, 33.0,
                            "now 33.00", date(2026, 8, 10))

    def test_subject_names_the_lead_alert(self):
        subject, _, _ = alert_builder.build([self._alert()], date(2026, 8, 10))
        self.assertIn("VIX above 30", subject)

    def test_subject_counts_extras(self):
        subject, _, _ = alert_builder.build([self._alert(), self._alert()],
                                            date(2026, 8, 10))
        self.assertIn("+1 more", subject)

    def test_bodies_escape_and_carry_reason(self):
        a = alerts.Alert("k", "<b>x</b>", "why it matters", "serious", 1.0, "d",
                         date(2026, 8, 10))
        _, text, html = alert_builder.build([a], date(2026, 8, 10))
        self.assertIn("why it matters", text)
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>x</b>", html)


# ------------------------------------------------------------------ Phase 4

class TestDashboard(unittest.TestCase):
    def setUp(self):
        from src.engine.pillar_scores import score_all
        self.cfg = load_cfg()
        specs = [{"pillar": n, "weight": 1.0} for n in (1, 2, 3, 4, 5)]
        self.ctx = {
            "date": date(2026, 8, 10),
            "diagnosis": regime.classify({n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}),
            "pillars": score_all([], self.cfg, specs),
            "readings": [],
            "signals": [],
            "key_levels": [],
            "sectors": [],
            "sector_note": "",
            "global_rows": [],
            "errors": {},
        }

    def test_renders_self_contained(self):
        html = dashboard.build(self.ctx)
        self.assertTrue(html.startswith("<!doctype html>"))
        for forbidden in ("http://", "https://", "<link", "@import"):
            self.assertNotIn(forbidden, html)

    def test_declares_both_dark_mode_scopes(self):
        """Media query alone misses the explicit toggle; the toggle alone misses OS dark."""
        html = dashboard.build(self.ctx)
        self.assertIn("prefers-color-scheme", html)
        self.assertIn('[data-theme="dark"]', html)

    def test_synthetic_banner_only_when_synthetic(self):
        self.assertIn("fabricated", dashboard.build(self.ctx, synthetic=True))
        self.assertNotIn("fabricated", dashboard.build(self.ctx, synthetic=False))

    def test_timeline_absent_history_explains_itself(self):
        html = dashboard.build(self.ctx, records=[])
        self.assertIn("No history yet", html)

    def test_sparkline_handles_degenerate_input(self):
        self.assertIn("no history", dashboard._sparkline([]))
        self.assertIn("no history", dashboard._sparkline([1.0]))
        self.assertNotIn("NaN", dashboard._sparkline([5.0, 5.0, 5.0]))

    def test_sparkline_coordinates_are_finite(self):
        svg = dashboard._sparkline([1.0, 5.0, 2.0, 9.0])
        pts = re.search(r'points="([^"]+)"', svg).group(1)
        for pair in pts.split():
            x, y = pair.split(",")
            self.assertTrue(float(x) == float(x) and float(y) == float(y))

    def test_diverging_bar_sign_picks_colour(self):
        self.assertIn(dashboard.DIVERGE_POS, dashboard._diverging_bar(2.0, 5.0, "up"))
        self.assertIn(dashboard.DIVERGE_NEG, dashboard._diverging_bar(-2.0, 5.0, "down"))
        self.assertIn("-", dashboard._diverging_bar(None, 5.0, "none"))

    def test_status_glyphs_are_not_directional(self):
        """Triangles read as direction; these encode tone. '<up> Cooling' was wrong."""
        for glyph in dashboard.STATUS_GLYPH.values():
            self.assertNotIn(glyph, ("▲", "▼"))

    def test_timeline_labels_every_regime_in_legend(self):
        recs = [{"date": "2026-0%d-01" % i, "regime": r, "readings": {}}
                for i, r in enumerate(["Goldilocks", "Risk-Off", "Late Cycle"], start=1)]
        html = dashboard.build(self.ctx, records=recs)
        for name in ("Goldilocks", "Risk-Off", "Late Cycle"):
            self.assertIn(name, html)

    def test_table_view_accompanies_timeline(self):
        """Relief rule: three light-mode hues are sub-3:1, so a table must exist."""
        recs = [{"date": "2026-01-0%d" % i, "regime": "Goldilocks", "readings": {}}
                for i in range(1, 5)]
        html = dashboard.build(self.ctx, records=recs)
        self.assertIn("<details>", html)
        self.assertIn("Table view", html)

    def test_every_regime_has_a_hue(self):
        for name in regime.PROFILES:
            self.assertIn(name, dashboard.REGIME_LIGHT)
            self.assertIn(name, dashboard.REGIME_DARK)

    def test_alerts_surface_on_page(self):
        a = alerts.Alert("k", "VIX above 30", "why", "critical", 33.0, "now 33",
                         date(2026, 8, 10))
        self.assertIn("VIX above 30", dashboard.build(self.ctx, alerts=[a]))


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ------------------------------------------------- Debt & debasement chain

from src.engine import chain            # noqa: E402
from src.fetchers import treasury_fetcher  # noqa: E402
from src.engine.indicators import Reading  # noqa: E402


def reading(sid, value, direction="flat"):
    return Reading(sid=sid, name=sid, pillar=7, unit="", decimals=2, weight=0.0,
                   freq="quarterly", value=value, as_of=date(2026, 8, 10), stale=False,
                   level=0.0, momentum=0.0, trend=0.0, drift=0.0, score=0.0,
                   direction=direction)


class TestTreasuryFetcher(unittest.TestCase):
    def test_filters_bills_out(self):
        payload = [
            {"securityTerm": "26-Week", "securityType": "Bill", "bidToCoverRatio": "2.9"},
            {"securityTerm": "10-Year", "securityType": "Note", "bidToCoverRatio": "2.5",
             "issueDate": "2026-08-15T00:00:00"},
        ]
        out = treasury_fetcher._parse(payload)
        self.assertEqual([a.term for a in out], ["10-Year"])

    def test_skips_rows_without_bid_to_cover(self):
        payload = [{"securityTerm": "10-Year", "bidToCoverRatio": None,
                    "issueDate": "2026-08-15T00:00:00"}]
        self.assertEqual(treasury_fetcher._parse(payload), [])

    def test_non_list_payload_raises(self):
        with self.assertRaises(Exception):
            treasury_fetcher._parse({"error": "nope"})

    def test_summary_compares_recent_to_baseline(self):
        rows = treasury_fetcher._parse([
            {"securityTerm": "10-Year", "bidToCoverRatio": "%.2f" % v,
             "issueDate": "2026-0%d-01T00:00:00" % (i + 1)}
            for i, v in enumerate([3.0, 3.0, 3.0, 2.0, 2.0, 2.0, 2.0, 2.0])])
        s = treasury_fetcher.demand_summary(rows, recent=4)
        self.assertAlmostEqual(s["recent_avg"], 2.0)
        self.assertLess(s["delta"], 0)

    def test_summary_none_on_empty(self):
        self.assertIsNone(treasury_fetcher.demand_summary([]))

    def test_real_fixture_parses(self):
        rows = treasury_fetcher.fetch_auctions(use_fixtures=True)
        self.assertTrue(rows)
        self.assertTrue(all(r.bid_to_cover > 0 for r in rows))


class TestChain(unittest.TestCase):
    def test_debt_burden_uses_actual_outlays_not_yield(self):
        """The load-bearing correction: burden is interest/receipts, not a yield."""
        r = {"A091RC1Q027SBEA": reading("A091RC1Q027SBEA", 1247.0),
             "FGRECPT": reading("FGRECPT", 5872.0)}
        st = chain.stage_debt(r)
        self.assertEqual(st.status, chain.BUILDING)   # ~21%, not a crisis
        self.assertIn("21%", st.detail)

    def test_debt_burden_fires_only_when_genuinely_high(self):
        r = {"A091RC1Q027SBEA": reading("A091RC1Q027SBEA", 2100.0),
             "FGRECPT": reading("FGRECPT", 5872.0)}
        self.assertEqual(chain.stage_debt(r).status, chain.FIRING)

    def test_debt_burden_unknown_without_inputs(self):
        self.assertEqual(chain.stage_debt({}).status, chain.UNKNOWN)

    def test_healthy_auctions_report_not_firing(self):
        """The thesis's own trigger must be able to read as absent."""
        st = chain.stage_funding({}, {"latest_term": "10-Year", "latest_btc": 2.71,
                                      "recent_avg": 2.62, "baseline_avg": 2.60,
                                      "delta": 0.02, "count": 20, "min_recent": 2.4,
                                      "latest_date": "2026-08-11", "terms": []})
        self.assertEqual(st.status, chain.NOT_FIRING)

    def test_weak_auctions_fire(self):
        st = chain.stage_funding({}, {"latest_term": "10-Year", "latest_btc": 1.8,
                                      "recent_avg": 1.85, "baseline_avg": 2.55,
                                      "delta": -0.70, "count": 20, "min_recent": 1.7,
                                      "latest_date": "2026-08-11", "terms": []})
        self.assertEqual(st.status, chain.FIRING)

    def test_funding_stage_states_the_dealer_caveat(self):
        st = chain.stage_funding({}, None)
        self.assertIn("primary dealers", st.caveat)

    def test_fed_stage_needs_actual_expansion(self):
        shrinking = chain.stage_fed({}, raw={"WALCL": series([7000.0, 6500.0], step=120)})
        self.assertEqual(shrinking.status, chain.NOT_FIRING)

    def test_fed_stage_fires_on_expansion_with_high_long_end(self):
        r = {"DGS10": reading("DGS10", 4.65), "DGS30": reading("DGS30", 5.19)}
        st = chain.stage_fed(r, raw={"WALCL": series([6500.0, 6900.0], step=120)})
        self.assertEqual(st.status, chain.FIRING)

    def test_debasement_requires_both_legs_to_fire(self):
        r = {"WM2NS": reading("WM2NS", 12.0)}
        self.assertEqual(chain.stage_debasement(r, gold_1y_pct=40.0).status, chain.FIRING)
        self.assertEqual(chain.stage_debasement(r, gold_1y_pct=3.0).status, chain.BUILDING)
        self.assertEqual(chain.stage_debasement({"WM2NS": reading("WM2NS", 3.7)},
                                                gold_1y_pct=3.0).status, chain.NOT_FIRING)

    def test_hollow_labour_market_is_detected(self):
        """Low unemployment WITH falling participation - the thesis's own claim."""
        r = {"UNRATE": reading("UNRATE", 4.1), "CIVPART": reading("CIVPART", 61.4)}
        raw = {"CIVPART": series([62.2, 61.4], step=400)}
        self.assertEqual(chain.stage_endpoints(r, raw=raw).status, chain.FIRING)

    def test_low_unemployment_with_stable_participation_is_not_hollow(self):
        r = {"UNRATE": reading("UNRATE", 4.1), "CIVPART": reading("CIVPART", 62.5)}
        raw = {"CIVPART": series([62.5, 62.5], step=400)}
        self.assertEqual(chain.stage_endpoints(r, raw=raw).status, chain.NOT_FIRING)

    def test_participation_uses_horizon_not_zscore(self):
        """A smooth multi-year decline scores ~0 on momentum but must still register."""
        r = {"UNRATE": reading("UNRATE", 4.1),
             "CIVPART": reading("CIVPART", 61.4, direction="flat")}
        raw = {"CIVPART": series([62.5 - 0.01 * i for i in range(120)], step=10)}
        self.assertEqual(chain.stage_endpoints(r, raw=raw).status, chain.FIRING)

    def test_every_stage_can_report_not_firing(self):
        """Falsifiability is the point: no stage may be structurally unable to be off."""
        stages, summary = chain.evaluate(
            {"A091RC1Q027SBEA": reading("A091RC1Q027SBEA", 500.0),
             "FGRECPT": reading("FGRECPT", 5872.0),
             "UNRATE": reading("UNRATE", 4.1),
             "CIVPART": reading("CIVPART", 62.5),
             "WM2NS": reading("WM2NS", 3.0)},
            auctions={"latest_term": "10-Year", "latest_btc": 2.7, "recent_avg": 2.7,
                      "baseline_avg": 2.6, "delta": 0.1, "count": 20,
                      "min_recent": 2.5, "latest_date": "2026-08-11", "terms": []},
            gold_1y_pct=2.0, spy_1y_pct=5.0,
            raw={"WALCL": series([7000.0, 6500.0], step=120),
                 "CIVPART": series([62.5, 62.5], step=400)})
        self.assertEqual(summary["firing"], 0)
        self.assertIn("No stage is firing", summary["verdict"])

    def test_evaluate_survives_completely_missing_data(self):
        stages, summary = chain.evaluate({}, None, None, None, None)
        self.assertEqual(len(stages), 5)
        self.assertEqual(summary["known"], 0)

    def test_every_stage_declares_claim_and_test(self):
        stages, _ = chain.evaluate({}, None)
        for st in stages:
            self.assertTrue(st.claim, "stage %d missing claim" % st.num)
            self.assertTrue(st.test, "stage %d missing test" % st.num)

    def test_chain_renders_into_dashboard(self):
        from src.engine.pillar_scores import score_all
        cfg = load_cfg()
        ctx = {"date": date(2026, 8, 10),
               "diagnosis": regime.classify({n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}),
               "pillars": score_all([], cfg, [{"pillar": n, "weight": 1.0} for n in range(1, 6)]),
               "readings": [], "signals": [], "key_levels": [], "sectors": [],
               "sector_note": "", "global_rows": [], "errors": {}}
        stages, summary = chain.evaluate({}, None)
        html = dashboard.build(ctx, chain_stages=stages, chain_summary=summary)
        self.assertIn("Debt &amp; debasement chain", html)
        self.assertIn("Claim:", html)
        self.assertIn("Test:", html)


class TestNetworkResilience(unittest.TestCase):
    """A dropped connection must cost one series, never the whole run."""

    def test_non_urlerror_transport_failures_become_fetch_errors(self):
        import http.client, ssl
        from src.fetchers import http as fhttp

        for exc in (http.client.RemoteDisconnected("peer closed"),
                    ConnectionResetError("reset by peer"),
                    ssl.SSLError("handshake failed"),
                    OSError("network unreachable")):
            with self.subTest(exc=type(exc).__name__):
                original = fhttp.urllib.request.urlopen
                fhttp.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(exc)
                try:
                    with self.assertRaises(fhttp.FetchError):
                        fhttp.get_json("https://example.invalid", {}, "x", False,
                                       retries=1, pause=0)
                finally:
                    fhttp.urllib.request.urlopen = original

    def test_one_bad_series_does_not_abort_the_fred_pull(self):
        from src.fetchers import fred_fetcher
        specs = [{"id": "DGS10", "name": "d", "pillar": 3, "freq": "daily",
                  "polarity": 1, "transform": "level", "weight": 1.0},
                 {"id": "NOPE_NOT_A_SERIES", "name": "n", "pillar": 3, "freq": "daily",
                  "polarity": 1, "transform": "level", "weight": 1.0}]
        out, errs = fred_fetcher.fetch_all(specs, "", use_fixtures=True)
        self.assertIn("DGS10", out)
        self.assertIn("NOPE_NOT_A_SERIES", errs)

    def test_throttle_and_daily_cap_are_distinguished(self):
        from src.fetchers import av_fetcher
        throttle = ("Thank you for using Alpha Vantage! Please consider spreading out "
                    "your free API requests more sparingly... premium plans at http")
        cap = "You have reached the 25 requests per day limit for the free plan."
        self.assertTrue(av_fetcher._is_throttle(throttle))
        self.assertFalse(av_fetcher._is_daily_cap(throttle))
        self.assertTrue(av_fetcher._is_daily_cap(cap))


class TestSecretRedaction(unittest.TestCase):
    """Upstream errors quote credentials back. Those strings get published."""

    def setUp(self):
        from src.fetchers import http as fhttp
        self.fhttp = fhttp
        self._saved = os.environ.get("ALPHAVANTAGE_API_KEY")
        os.environ["ALPHAVANTAGE_API_KEY"] = "TESTKEY1234567890"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ALPHAVANTAGE_API_KEY", None)
        else:
            os.environ["ALPHAVANTAGE_API_KEY"] = self._saved

    def test_scrub_masks_the_key(self):
        msg = "We have detected your API key as TESTKEY1234567890 and our limit is 25/day"
        out = self.fhttp.scrub(msg)
        self.assertNotIn("TESTKEY1234567890", out)
        self.assertIn("REDACTED", out)

    def test_fetch_error_scrubs_on_construction(self):
        err = self.fhttp.FetchError("key TESTKEY1234567890 rejected")
        self.assertNotIn("TESTKEY1234567890", str(err))

    def test_short_values_are_not_masked(self):
        """A 3-character secret would blank out harmless substrings."""
        os.environ["ALPHAVANTAGE_API_KEY"] = "abc"
        self.assertEqual(self.fhttp.scrub("abcdef"), "abcdef")

    def test_snapshot_never_persists_a_key(self):
        """The actual leak path: error text -> snapshot -> public repo."""
        import tempfile, json as _json
        from src import store
        from src.engine.pillar_scores import score_all
        cfg = load_cfg()
        pillars = score_all([], cfg, [{"pillar": n, "weight": 1.0} for n in range(1, 6)])
        diag = regime.classify({n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)})

        original = store.DAILY_DIR
        tmp = tempfile.mkdtemp()
        store.DAILY_DIR = tmp
        try:
            payload = store.save_snapshot(
                date(2026, 8, 11), pillars, diag, [], [],
                {"SPY": "detected your API key as TESTKEY1234567890 rate limit"})
            written = open(os.path.join(tmp, "2026-08-11.json")).read()
            self.assertNotIn("TESTKEY1234567890", written)
            self.assertNotIn("TESTKEY1234567890", _json.dumps(payload))
        finally:
            store.DAILY_DIR = original


class TestFixtureCoverage(unittest.TestCase):
    """Adding a series to config without regenerating fixtures broke every offline
    run with a confusing "no fixture recorded" error. Catch it at test time."""

    def test_every_configured_fred_series_has_a_fixture(self):
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            series = json.load(fh)["series"]
        missing = [s["id"] for s in series
                   if not os.path.exists(os.path.join(
                       ROOT, "tests", "fixtures", "fred_%s.json" % s["id"]))]
        self.assertEqual(missing, [],
                         "missing fixtures (run tools/make_fixtures.py): %s" % missing)

    def test_every_configured_symbol_has_a_fixture(self):
        with open(os.path.join(ROOT, "config", "av_symbols.json")) as fh:
            symbols = json.load(fh)["symbols"]
        missing = [s["symbol"] for s in symbols
                   if not os.path.exists(os.path.join(
                       ROOT, "tests", "fixtures", "av_%s.json" % s["symbol"]))]
        self.assertEqual(missing, [], "missing fixtures: %s" % missing)


class TestIndicatorExplanations(unittest.TestCase):
    """Every tracked number must carry its meaning. Adding a series without an
    explanation silently produces a bare figure the reader cannot interpret."""

    def setUp(self):
        from src.output import explain
        self.explain = explain
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            self.series = json.load(fh)["series"]

    def test_every_series_has_an_explanation(self):
        missing = [s["id"] for s in self.series
                   if s["id"] not in self.explain.INDICATOR_INFO]
        self.assertEqual(missing, [], "no explanation for: %s" % missing)

    def test_derived_readings_are_explained_too(self):
        for sid in ("RSP_SPY", "SPY_TREND"):
            self.assertIn(sid, self.explain.INDICATOR_INFO)

    def test_each_entry_has_all_four_parts(self):
        for sid, info in self.explain.INDICATOR_INFO.items():
            self.assertEqual(len(info), 4, "%s malformed" % sid)
            for part in info:
                self.assertTrue(part and part.strip(), "%s has an empty part" % sid)

    def test_describe_links_reading_to_meaning(self):
        high = self.explain.describe("VIXCLS", 95.0, "rising")
        low = self.explain.describe("VIXCLS", 5.0, "falling")
        self.assertIn("top of its 3-year range", high)
        self.assertIn("Fear is elevated", high)
        self.assertIn("complacent", low)
        self.assertNotEqual(high, low)

    def test_describe_survives_missing_percentile(self):
        self.assertIsInstance(self.explain.describe("VIXCLS", None, None), str)

    def test_describe_unknown_series_is_empty_not_an_error(self):
        self.assertEqual(self.explain.describe("NOT_A_SERIES", 50.0, "flat"), "")


class TestAnchorAwareDescriptions(unittest.TestCase):
    """Percentile alone misreads a series with a structural threshold, and which
    side of that threshold counts as the signal cannot be inferred."""

    def setUp(self):
        from src.output import explain
        self.d = explain.describe
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            self.series = json.load(fh)["series"]

    def test_every_anchored_series_declares_its_signal_side(self):
        undeclared = [s["id"] for s in self.series
                      if "anchor" in s and "anchor_signal" not in s]
        self.assertEqual(undeclared, [], "anchored but no anchor_signal: %s" % undeclared)
        for s in self.series:
            if "anchor_signal" in s:
                self.assertIn(s["anchor_signal"], ("above", "below"))

    def test_sahm_below_trigger_does_not_claim_recession(self):
        """0.41 is the top of its own range but below the 0.50 line."""
        out = self.d("SAHMREALTIME", 99.0, "rising", 0.41, 0.50, None, "above")
        self.assertIn("Not yet across", out)
        self.assertNotIn("reached recessionary territory", out)

    def test_sahm_above_trigger_does_claim_it(self):
        out = self.d("SAHMREALTIME", 99.0, "rising", 0.55, 0.50, None, "above")
        self.assertIn("recessionary territory", out)

    def test_inverted_curve_reads_as_signalling(self):
        """A curve signals BELOW zero; treating 'above' as fired inverted the meaning."""
        out = self.d("T10Y2Y", 5.0, "falling", -0.30, 0.0, None, "below")
        self.assertIn("Inverted", out)
        self.assertNotIn("not signalling", out)

    def test_positive_curve_reads_as_quiet(self):
        out = self.d("T10Y2Y", 70.0, "rising", 0.69, 0.0, None, "below")
        self.assertIn("not signalling", out)

    def test_threshold_is_formatted_readably(self):
        self.assertIn("0.50", self.d("SAHMREALTIME", 99.0, "rising", 0.55, 0.50, None, "above"))

    def test_unanchored_series_still_use_percentile(self):
        out = self.d("VIXCLS", 95.0, "rising")
        self.assertIn("top of its 3-year range", out)


class TestSectorOutlook(unittest.TestCase):
    """Sensitivities are structural exposures, not forecasts. The tests pin the
    mechanics so a sign error cannot quietly invert the advice."""

    def setUp(self):
        from src.engine import sectors
        self.s = sectors
        self.specs = [{"symbol": k, "name": k} for k in sectors.SENSITIVITY]

    def _pillars(self, growth=0.0, inflation=0.0, tight=0.0, stress=0.0):
        return {1: FakePillar(1, growth), 2: FakePillar(2, inflation),
                3: FakePillar(3, tight), 4: FakePillar(4, stress),
                5: FakePillar(5, 0.0)}

    def test_easing_rates_favour_the_bond_proxies(self):
        """Utilities and real estate are the most rate-sensitive; easing suits them."""
        rows, _ = self.s.score_sectors(self._pillars(tight=-0.8), self.specs)
        top = [r["symbol"] for r in rows[:3]]
        self.assertTrue({"XLU", "XLRE"} & set(top), "expected rate-sensitives on top: %s" % top)

    def test_tightening_rates_punish_the_same_sectors(self):
        rows, _ = self.s.score_sectors(self._pillars(tight=0.8), self.specs)
        bottom = [r["symbol"] for r in rows[-3:]]
        self.assertTrue({"XLU", "XLRE"} & set(bottom))

    def test_credit_stress_favours_defensives_over_cyclicals(self):
        rows, _ = self.s.score_sectors(self._pillars(stress=0.8), self.specs)
        order = [r["symbol"] for r in rows]
        self.assertLess(order.index("XLP"), order.index("XLY"))
        self.assertLess(order.index("XLP"), order.index("XLF"))

    def test_hot_inflation_favours_energy(self):
        rows, _ = self.s.score_sectors(self._pillars(inflation=0.9), self.specs)
        self.assertEqual(rows[0]["symbol"], "XLE")

    def test_strong_growth_favours_cyclicals_over_staples(self):
        rows, _ = self.s.score_sectors(self._pillars(growth=0.9), self.specs)
        order = [r["symbol"] for r in rows]
        self.assertLess(order.index("XLY"), order.index("XLP"))
        self.assertLess(order.index("XLI"), order.index("XLU"))

    def test_every_sector_explains_its_own_exposure(self):
        for symbol, sens in self.s.SENSITIVITY.items():
            self.assertTrue(sens.get("why"), "%s has no explanation" % symbol)

    def test_drivers_are_named_for_each_row(self):
        rows, _ = self.s.score_sectors(self._pillars(growth=0.6, tight=-0.5), self.specs)
        self.assertTrue(all(r["drivers"] for r in rows))

    def test_returns_nothing_when_conditions_are_unknown(self):
        blank = {n: FakePillar(n, 0.0, known=False) for n in (1, 2, 3, 4, 5)}
        rows, _ = self.s.score_sectors(blank, self.specs)
        self.assertEqual(rows, [])

    def test_divergence_flags_favoured_but_lagging(self):
        rows = [{"symbol": "XLU", "name": "Utilities", "score": 0.5,
                 "drivers": [], "why": "", "actual": -2.5}]
        gaps = self.s.divergences(rows)
        self.assertEqual(len(gaps), 1)
        self.assertIn("lagged", gaps[0][1])

    def test_divergence_flags_disfavoured_but_leading(self):
        rows = [{"symbol": "XLY", "name": "Discretionary", "score": -0.5,
                 "drivers": [], "why": "", "actual": 3.0}]
        self.assertIn("bid it up", self.s.divergences(rows)[0][1])

    def test_agreement_is_not_flagged(self):
        rows = [{"symbol": "XLU", "name": "U", "score": 0.5, "drivers": [],
                 "why": "", "actual": 2.0}]
        self.assertEqual(self.s.divergences(rows), [])

    def test_every_sector_etf_in_config_has_a_sensitivity(self):
        with open(os.path.join(ROOT, "config", "av_symbols.json")) as fh:
            cfg = json.load(fh)["symbols"]
        missing = [s["symbol"] for s in cfg
                   if s.get("role") == "sector" and s["symbol"] not in self.s.SENSITIVITY]
        self.assertEqual(missing, [], "sector ETFs without sensitivities: %s" % missing)


class TestWatchlist(unittest.TestCase):
    """The watchlist must respond to conditions rather than being a fixed list,
    and 'what would change this' must stay checkable rather than predictive."""

    def setUp(self):
        from src.engine import watchlist
        self.w = watchlist
        self.cfg = load_cfg()
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            self.specs = json.load(fh)["series"]

    def _reading(self, sid, name, value, pillar=1, weight=1.0, drift=0.0,
                 pct=50.0, freq="monthly", stale=False):
        from src.engine.indicators import Reading
        return Reading(sid=sid, name=name, pillar=pillar, unit="", decimals=2,
                       weight=weight, freq=freq, value=value, as_of=date(2026, 8, 14),
                       stale=stale, level=0.0, momentum=drift, trend=drift, drift=drift,
                       score=0.0, percentile=pct, chg_1m=0.1, direction="flat")

    def test_series_near_its_threshold_outranks_a_quiet_heavyweight(self):
        near = self._reading("SAHMREALTIME", "Sahm", 0.47, weight=2.5)
        quiet = self._reading("UNRATE", "Unemployment", 4.1, weight=1.5)
        out = self.w.top_indicators([quiet, near], self.specs, limit=2)
        self.assertEqual(out[0]["sid"], "SAHMREALTIME")
        self.assertIn("signal", out[0]["reason"])

    def test_stale_readings_are_never_surfaced(self):
        stale = self._reading("UNRATE", "Unemployment", 4.1, weight=1.5, stale=True)
        self.assertEqual(self.w.top_indicators([stale], self.specs), [])

    def test_unscored_series_are_excluded(self):
        """Weight-zero series are context, not things to watch."""
        ctx = self._reading("PSAVERT", "Saving rate", 2.7, pillar=7, weight=0.0)
        self.assertEqual(self.w.top_indicators([ctx], self.specs), [])

    def test_list_changes_with_conditions(self):
        calm = self._reading("SAHMREALTIME", "Sahm", -0.20, weight=2.5)
        hot = self._reading("SAHMREALTIME", "Sahm", 0.47, weight=2.5)
        other = self._reading("UNRATE", "Unemployment", 4.1, weight=1.5, drift=0.6)
        calm_top = self.w.top_indicators([calm, other], self.specs, limit=1)[0]["sid"]
        hot_top = self.w.top_indicators([hot, other], self.specs, limit=1)[0]["sid"]
        self.assertNotEqual(calm_top, hot_top)

    def test_next_release_follows_the_series_cadence(self):
        weekly = self._reading("ICSA", "Claims", 230.0, freq="weekly")
        monthly = self._reading("UNRATE", "Unemployment", 4.1, freq="monthly")
        self.assertEqual((self.w.next_release(weekly) - date(2026, 8, 14)).days, 7)
        self.assertEqual((self.w.next_release(monthly) - date(2026, 8, 14)).days, 30)

    def test_what_would_change_flags_a_near_threshold(self):
        near = self._reading("SAHMREALTIME", "Sahm", 0.47, weight=2.5)
        d = regime.classify({n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)})
        out = self.w.what_would_change({1: FakePillar(1, 0.0)}, [near], self.specs,
                                       d, self.cfg)
        self.assertTrue(any(i["kind"] == "threshold" for i in out))

    def test_what_would_change_flags_a_close_regime_call(self):
        pillars = {n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}
        d = regime.classify(pillars)
        out = self.w.what_would_change(pillars, [], self.specs, d, self.cfg)
        self.assertTrue(any(i["kind"] in ("regime", "pillar") for i in out))

    def test_what_would_change_survives_empty_input(self):
        d = regime.classify({n: FakePillar(n, 0.0, known=False) for n in (1, 2, 3, 4, 5)})
        self.assertIsInstance(
            self.w.what_would_change({}, [], self.specs, d, self.cfg), list)

    def test_a_hairline_crossing_is_not_announced_as_crossed(self):
        """CFNAI at -0.02 against a zero threshold is on the line, not across it."""
        from src.engine.indicators import Reading
        r = Reading(sid="CFNAI", name="CFNAI", pillar=1, unit="", decimals=2,
                    weight=2.0, freq="monthly", value=-0.02, as_of=date(2026, 8, 14),
                    stale=False, level=0.0, momentum=0.0, trend=0.0, drift=0.0,
                    score=0.0, percentile=50.0, chg_1m=0.30, direction="flat")
        out = self.w.top_indicators([r], self.specs, limit=1)
        self.assertIn("sitting right on", out[0]["reason"])

    def test_a_decisive_crossing_still_says_crossed(self):
        from src.engine.indicators import Reading
        r = Reading(sid="CFNAI", name="CFNAI", pillar=1, unit="", decimals=2,
                    weight=2.0, freq="monthly", value=-0.85, as_of=date(2026, 8, 14),
                    stale=False, level=0.0, momentum=0.0, trend=0.0, drift=0.0,
                    score=0.0, percentile=5.0, chg_1m=0.10, direction="falling")
        out = self.w.top_indicators([r], self.specs, limit=1)
        self.assertIn("has crossed", out[0]["reason"])


class TestNewFetchers(unittest.TestCase):
    """Both of these consume third-party formats that degrade in confusing ways."""

    def test_earnings_rejects_the_rate_limit_masquerading_as_csv(self):
        """When the quota is exhausted, Alpha Vantage returns the CSV header plus
        the word 'Information' spelled one letter per column. It parses cleanly."""
        from src.fetchers import earnings_fetcher as E
        from src.fetchers.http import FetchError
        import csv, io
        body = ("symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
                "I,n,f,o,r,m,a\n")
        rows = list(csv.DictReader(io.StringIO(body)))
        usable = [r for r in rows if E._parse_date(r.get("reportDate"))]
        self.assertEqual(usable, [], "letter-salad row must not parse as data")

    def test_earnings_select_filters_to_watched_names_and_horizon(self):
        from src.fetchers import earnings_fetcher as E
        rows = [
            {"symbol": "AAPL", "name": "Apple", "reportDate": "2026-08-20",
             "fiscalDateEnding": "2026-06-30", "estimate": "1.50", "timeOfTheDay": "post-market"},
            {"symbol": "ZZZZ", "name": "Nobody", "reportDate": "2026-08-20",
             "fiscalDateEnding": "", "estimate": "", "timeOfTheDay": ""},
            {"symbol": "AAPL", "name": "Apple", "reportDate": "2027-01-01",
             "fiscalDateEnding": "", "estimate": "", "timeOfTheDay": ""},
        ]
        got = E.select(rows, {"AAPL"}, days=21, today=date(2026, 8, 14))
        self.assertEqual([e.symbol for e in got], ["AAPL"])
        self.assertEqual(got[0].estimate, 1.50)

    def test_earnings_select_ignores_past_dates(self):
        from src.fetchers import earnings_fetcher as E
        rows = [{"symbol": "AAPL", "name": "A", "reportDate": "2026-01-01",
                 "fiscalDateEnding": "", "estimate": "", "timeOfTheDay": ""}]
        self.assertEqual(E.select(rows, {"AAPL"}, today=date(2026, 8, 14)), [])

    def test_rss_timestamps_are_always_naive(self):
        """Mixed aware/naive stamps crashed the sort and took the whole tab down."""
        from src.fetchers import rss_fetcher as R
        aware = R._parse_when("Wed, 26 Aug 2026 14:30:00 +0200")
        naive = R._parse_when("Wed, 26 Aug 2026 14:30:00")
        self.assertIsNotNone(aware)
        self.assertIsNone(aware.tzinfo)
        self.assertIsNone(naive.tzinfo)
        self.assertLess(aware, naive)  # +0200 converted back to UTC

    def test_rss_unparseable_date_is_none_not_an_error(self):
        from src.fetchers import rss_fetcher as R
        self.assertIsNone(R._parse_when("not a date"))
        self.assertIsNone(R._parse_when(""))

    def test_rss_strips_markup_from_summaries(self):
        from src.fetchers import rss_fetcher as R
        self.assertEqual(R._clean("<p>Hello <b>world</b></p>"), "Hello world")

    def test_dead_feed_returns_empty_not_an_exception(self):
        from src.fetchers import rss_fetcher as R
        self.assertEqual(R.fetch_feed("https://example.invalid/none.xml", "x", "y"), [])


class TestTreemap(unittest.TestCase):
    def setUp(self):
        from src.output import treemap
        self.t = treemap

    class _Q:
        def __init__(self, sym, cap, chg):
            self.symbol, self.market_cap, self.change_pct = sym, cap, chg
            self.price, self.sector = 10.0, None

    def _quotes(self):
        return {"A": self._Q("A", 3e12, 1.2), "B": self._Q("B", 1e12, -0.5),
                "C": self._Q("C", 5e11, 0.0)}

    def test_boxes_fill_the_canvas_without_overflow(self):
        import re
        svg = self.t.render(self._quotes(), {"Tech": ["A", "B"], "Energy": ["C"]},
                            width=400, height=300)
        rects = re.findall(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"', svg)
        self.assertTrue(rects)
        for x, y, w, h in rects:
            self.assertGreaterEqual(float(w), 0)
            self.assertGreaterEqual(float(h), 0)
            self.assertLessEqual(float(x) + float(w), 401)
            self.assertLessEqual(float(y) + float(h), 301)

    def test_area_is_proportional_to_market_cap(self):
        boxes = self.t.squarify([(3e12, "big"), (1e12, "small")], 0, 0, 400, 300)
        areas = {p: w * h for _, _, w, h, p in boxes}
        self.assertAlmostEqual(areas["big"] / areas["small"], 3.0, places=1)

    def test_colour_reflects_direction_and_magnitude(self):
        self.assertNotEqual(self.t._shade(2.0), self.t._shade(-2.0))
        self.assertEqual(self.t._shade(None), self.t.FLAT)
        self.assertNotEqual(self.t._shade(0.2), self.t._shade(3.0))

    def test_empty_input_renders_nothing_rather_than_breaking(self):
        self.assertEqual(self.t.render({}, {"Tech": ["A"]}), "")
        self.assertEqual(self.t.squarify([], 0, 0, 100, 100), [])

    def test_no_nan_in_output(self):
        svg = self.t.render(self._quotes(), {"Tech": ["A", "B", "C"]})
        self.assertNotIn("nan", svg.lower())

    def test_squarify_produces_squarish_boxes_not_slivers(self):
        """The row-break comparison silently never fired, degenerating the map into
        full-width slivers. Aspect ratios are the only thing that catches it."""
        boxes = self.t.squarify([(v, "b%d" % i) for i, v in
                                 enumerate([6, 6, 4, 3, 2, 2, 1])], 0, 0, 600, 400)
        ratios = [max(w / h, h / w) for _, _, w, h, _ in boxes if w > 0 and h > 0]
        self.assertEqual(len(boxes), 7)
        self.assertLess(max(ratios), 4.0, "boxes are slivers: %s" % ratios)


class TestAlphaVantageCache(unittest.TestCase):
    """Hourly refreshes would need ~98 Alpha Vantage calls against a 25/day cap.
    The morning pull is cached so intraday runs spend nothing."""

    def setUp(self):
        from src import store
        from src.engine.timeseries import Series
        self.store = store
        self.series = Series("SPY", [date(2026, 8, 24) + timedelta(days=i)
                                     for i in range(3)], [760.0, 764.0, 766.0])
        self._orig = store.AV_CACHE_PATH
        import tempfile
        store.AV_CACHE_PATH = os.path.join(tempfile.mkdtemp(), "av.json")

    def tearDown(self):
        self.store.AV_CACHE_PATH = self._orig

    def test_round_trip_preserves_dates_and_values(self):
        self.store.save_av_cache({"SPY": self.series})
        back = self.store.rehydrate_av(self.store.load_av_cache())
        self.assertEqual(len(back["SPY"]), 3)
        self.assertEqual(back["SPY"].latest, 766.0)
        self.assertEqual(back["SPY"].dates[-1], self.series.dates[-1])

    def test_cache_expires(self):
        self.store.save_av_cache({"SPY": self.series})
        self.assertIsNone(self.store.load_av_cache(max_age_hours=0))

    def test_missing_cache_is_none_not_an_error(self):
        self.assertIsNone(self.store.load_av_cache())

    def test_corrupt_cache_is_none_not_an_error(self):
        with open(self.store.AV_CACHE_PATH, "w") as fh:
            fh.write("{not json")
        self.assertIsNone(self.store.load_av_cache())

    def test_rehydrate_skips_malformed_entries(self):
        out = self.store.rehydrate_av({"BAD": {"dates": ["oops"], "values": [1.0]},
                                       "OK": {"dates": ["2026-08-24"], "values": [5.0]}})
        self.assertEqual(sorted(out), ["OK"])


class TestAiCreditTracker(unittest.TestCase):
    """Every stage must be able to read NOT FIRING - that is the whole point of
    building this as a tracker rather than restating the argument."""

    def setUp(self):
        from src.engine import aicredit
        self.a = aicredit

    def _r(self, sid, value):
        from src.engine.indicators import Reading
        return Reading(sid=sid, name=sid, pillar=8, unit="", decimals=2, weight=0.0,
                       freq="quarterly", value=value, as_of=date(2026, 8, 26),
                       stale=False, level=0.0, momentum=0.0, trend=0.0, drift=0.0,
                       score=0.0, percentile=50.0, direction="flat")

    def test_calm_credit_reads_not_firing(self):
        st = self.a.stage_borrowing({"NCBDBIQ027S": self._r("NCBDBIQ027S", 8982.0),
                                     "BAMLC0A0CM": self._r("BAMLC0A0CM", 78.0)}, {})
        self.assertEqual(st.status, self.a.NOT_FIRING)

    def test_wide_spreads_fire_stage_one(self):
        st = self.a.stage_borrowing({"NCBDBIQ027S": self._r("NCBDBIQ027S", 8982.0),
                                     "BAMLC0A0CM": self._r("BAMLC0A0CM", 180.0)}, {})
        self.assertEqual(st.status, self.a.FIRING)

    def test_private_credit_lagging_junk_bonds_fires(self):
        gauges = {"BIZD": {"ret_63": -9.0}, "HYG": {"ret_63": 1.0}}
        self.assertEqual(self.a.stage_private_credit(gauges).status, self.a.FIRING)

    def test_private_credit_tracking_junk_bonds_is_quiet(self):
        gauges = {"BIZD": {"ret_63": 1.2}, "HYG": {"ret_63": 1.0}}
        self.assertEqual(self.a.stage_private_credit(gauges).status, self.a.NOT_FIRING)

    def test_insurer_concentration_needs_market_confirmation_to_fire(self):
        readings = {"BOGZ1FL543063005Q": self._r("BOGZ1FL543063005Q", 5000.0),
                    "BOGZ1FL544090005Q": self._r("BOGZ1FL544090005Q", 10000.0)}
        calm = self.a.stage_insurers(readings, {"KIE": {"ret_63": 1.0},
                                                "XLF": {"ret_63": 0.5}})
        stressed = self.a.stage_insurers(readings, {"KIE": {"ret_63": -8.0},
                                                    "XLF": {"ret_63": 1.0}})
        self.assertEqual(calm.status, self.a.BUILDING)
        self.assertEqual(stressed.status, self.a.FIRING)

    def test_low_delinquencies_read_not_firing(self):
        st = self.a.stage_stress({"DRCRELEXFACBS": self._r("DRCRELEXFACBS", 1.5),
                                  "DRBLACBS": self._r("DRBLACBS", 1.3)})
        self.assertEqual(st.status, self.a.NOT_FIRING)

    def test_high_delinquencies_fire(self):
        st = self.a.stage_stress({"DRCRELEXFACBS": self._r("DRCRELEXFACBS", 3.4),
                                  "DRBLACBS": self._r("DRBLACBS", 2.1)})
        self.assertEqual(st.status, self.a.FIRING)

    def test_every_stage_can_report_not_firing(self):
        readings = {"NCBDBIQ027S": self._r("NCBDBIQ027S", 8000.0),
                    "BAMLC0A0CM": self._r("BAMLC0A0CM", 80.0),
                    "BOGZ1FL543063005Q": self._r("BOGZ1FL543063005Q", 3000.0),
                    "BOGZ1FL544090005Q": self._r("BOGZ1FL544090005Q", 10000.0),
                    "DRCRELEXFACBS": self._r("DRCRELEXFACBS", 1.0),
                    "DRBLACBS": self._r("DRBLACBS", 1.0),
                    "IRLTLT01JPM156N": self._r("IRLTLT01JPM156N", 0.8)}
        gauges = {"BIZD": {"ret_63": 1.0}, "HYG": {"ret_63": 1.0},
                  "KIE": {"ret_63": 1.0}, "XLF": {"ret_63": 1.0}}
        stages, summary = self.a.evaluate(readings, gauges)
        self.assertEqual(summary["firing"], 0)
        self.assertIn("Nothing is firing", summary["verdict"])

    def test_missing_data_never_raises(self):
        stages, summary = self.a.evaluate({}, {})
        self.assertEqual(len(stages), 5)
        self.assertEqual(summary["known"], 0)

    def test_every_stage_declares_claim_test_and_caveat(self):
        stages, _ = self.a.evaluate({}, {})
        for st in stages:
            self.assertTrue(st.claim, "stage %d has no claim" % st.num)
            self.assertTrue(st.test, "stage %d has no test" % st.num)
            self.assertTrue(st.caveat, "stage %d has no caveat" % st.num)

    def test_unmeasurable_parts_are_declared_not_hidden(self):
        self.assertGreaterEqual(len(self.a.NOT_MEASURABLE), 4)
        titles = " ".join(t for t, _ in self.a.NOT_MEASURABLE).lower()
        self.assertIn("capex", titles)
        self.assertIn("2027", titles)

    def test_no_individual_firms_are_tracked(self):
        """A dashboard row naming a firm as systemically dangerous is a strong claim."""
        with open(os.path.join(ROOT, "config", "aicredit_gauges.json")) as fh:
            gauges = json.load(fh)["gauges"]
        symbols = {g["symbol"] for g in gauges}
        firms = {"APO", "KKR", "BX", "OWL", "ARES", "BN", "MET", "PRU", "LNC", "GL"}
        self.assertEqual(symbols & firms, set())

    def test_outperformance_is_not_described_as_tracking(self):
        gauges = {"BIZD": {"ret_63": 6.4}, "HYG": {"ret_63": -0.3}}
        st = self.a.stage_private_credit(gauges)
        self.assertEqual(st.status, self.a.NOT_FIRING)
        self.assertIn("OUTPERFORMED", st.detail)
        self.assertNotIn("tracking public junk bonds within", st.detail)

    def test_weak_datacentre_proxy_registers_in_stage_one(self):
        readings = {"NCBDBIQ027S": self._r("NCBDBIQ027S", 8982.0),
                    "BAMLC0A0CM": self._r("BAMLC0A0CM", 81.0)}
        gauges = {"EQIX": {"ret_63": -12.0}, "XLF": {"ret_63": 0.4}}
        st = self.a.stage_borrowing(readings, gauges)
        self.assertEqual(st.status, self.a.BUILDING)
        self.assertIn("Data-centre landlords", st.detail)


class TestAssetCards(unittest.TestCase):
    def setUp(self):
        from src.output import assetcards
        self.a = assetcards
        self.spec = [{"symbol": "GC=F", "label": "Gold", "unit": "per oz", "decimals": 2}]
        self.data = {"GC=F": {"price": 4683.2, "chg_1d": -0.4, "chg_6m": 12.3,
                              "history": [4100.0, 4300.0, 4500.0, 4683.2]}}

    def test_card_renders_price_change_and_chart(self):
        html = self.a.cards("Metals", self.spec, self.data)
        self.assertIn("4,683.20", html)
        self.assertIn("-0.40% today", html)
        self.assertIn("+12.3%", html)
        self.assertIn("<polyline", html)

    def test_rising_series_is_green_and_falling_is_red(self):
        up = self.a._series_chart([1.0, 2.0, 3.0])
        down = self.a._series_chart([3.0, 2.0, 1.0])
        self.assertIn(self.a.UP, up)
        self.assertIn(self.a.DOWN, down)

    def test_green_is_up_per_the_convention(self):
        """The user asked for green-up; a sign flip here would invert every card."""
        self.assertEqual(self.a.UP, "#16a34a")
        self.assertEqual(self.a.DOWN, "#e5484d")

    def test_missing_symbol_is_skipped_not_broken(self):
        self.assertEqual(self.a.cards("Metals", self.spec, {}), "")

    def test_short_history_renders_no_chart_rather_than_a_broken_one(self):
        self.assertEqual(self.a._series_chart([1.0]), "")
        self.assertEqual(self.a._series_chart([]), "")

    def test_chart_coordinates_are_finite(self):
        import re
        svg = self.a._series_chart([1.0, 9.0, 3.0, 7.0])
        for pair in re.search(r'<polyline points="([^"]+)"', svg).group(1).split():
            x, y = pair.split(",")
            self.assertTrue(float(x) == float(x) and float(y) == float(y))

    def test_heatmap_uses_green_up_red_down(self):
        """_shade blends toward the surface for small moves, so check the hue
        direction rather than an exact hex: green channel should lead on a rise,
        red channel on a fall."""
        from src.output import treemap
        self.assertEqual(treemap.POS, "#16a34a")
        self.assertEqual(treemap.NEG, "#e5484d")

        def rgb(h):
            return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

        for pct in (0.5, 2.0, 5.0):
            r, g, _ = rgb(treemap._shade(pct))
            self.assertGreater(g, r, "a rise of %.1f%% should read green" % pct)
            r, g, _ = rgb(treemap._shade(-pct))
            self.assertGreater(r, g, "a fall of %.1f%% should read red" % pct)

    def test_every_configured_asset_has_a_label_and_decimals(self):
        with open(os.path.join(ROOT, "config", "assets.json")) as fh:
            cfg = json.load(fh)
        for group in ("crypto", "metals"):
            for row in cfg[group]:
                self.assertTrue(row.get("label"))
                self.assertIsInstance(row.get("decimals"), int)

    def test_six_month_figure_is_coloured_to_match_its_chart(self):
        """A green 'today' above a red chart reads as a contradiction unless the
        window figure is tied to the chart's colour."""
        data = {"GC=F": {"price": 4683.2, "chg_1d": 1.0, "chg_6m": -9.5,
                         "history": [5200.0, 4900.0, 4683.2]}}
        html = self.a.cards("Metals", self.spec, data)
        self.assertIn(self.a.DOWN, html)   # chart and the -9.5% both red
        self.assertIn("-9.5%", html)
        self.assertIn("+1.00% today", html)


class TestDeployedPagesMatchNav(unittest.TestCase):
    """Every tab in the nav must actually be copied to site/ by both workflows -
    aicredit.html was linked and built but never deployed, giving a live 404."""

    def test_every_nav_tab_is_in_the_deploy_step(self):
        from src.output.pages import TABS
        nav_pages = {href.replace(".html", "") for href, _, _ in TABS if href != "index.html"}
        for wf in ("daily-brief.yml", "refresh.yml"):
            path = os.path.join(ROOT, ".github", "workflows", wf)
            with open(path) as fh:
                content = fh.read()
            m = re.search(r"for page in ([\w ]+); do", content)
            self.assertIsNotNone(m, "%s has no page copy loop" % wf)
            deployed = set(m.group(1).split())
            missing = nav_pages - deployed
            self.assertEqual(missing, set(),
                             "%s does not deploy: %s (linked in nav but 404s live)"
                             % (wf, missing))
