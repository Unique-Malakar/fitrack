"""Test suite - stdlib unittest, no pytest dependency.

    python3 -m unittest discover -s tests -v

Covers the maths that is easy to get quietly wrong (transforms, z-scores, percentile
edges), the parsing of both upstream formats including their failure modes, and the
detector logic that turns numbers into claims. Detectors are tested against
hand-built Readings rather than fixtures so each assertion pins one behaviour.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine import market, regime, signals
from src.engine.indicators import Reading, build_reading
from src.engine.pillar_scores import score_all, score_pillar
from src.engine.timeseries import Series, apply_transform
from src.fetchers import av_fetcher, fred_fetcher
from src.fetchers.http import FetchError
from src.output import email_builder

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_cfg():
    with open(os.path.join(ROOT, "config", "thresholds.json")) as fh:
        return json.load(fh)


def mkseries(values, step_days=1, sid="TEST"):
    n = len(values)
    dates = [date(2026, 1, 1) + timedelta(days=i * step_days) for i in range(n)]
    return Series(sid, dates, list(values))


class TestTimeseries(unittest.TestCase):
    def test_diff_and_pct_change(self):
        s = mkseries([10.0, 12.0, 15.0])
        self.assertEqual(s.diff(1).values, [2.0, 3.0])
        self.assertAlmostEqual(s.pct_change(1).values[0], 20.0)
        self.assertAlmostEqual(s.pct_change(2).values[0], 50.0)

    def test_pct_change_skips_zero_base(self):
        """Division by a zero prior must drop the point, not raise or emit inf."""
        s = mkseries([0.0, 5.0, 10.0])
        out = s.pct_change(1)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.values[0], 100.0)

    def test_moving_average_is_correct_and_aligned(self):
        s = mkseries([1.0, 2.0, 3.0, 4.0, 5.0])
        ma = s.moving_average(3)
        self.assertEqual(ma.values, [2.0, 3.0, 4.0])
        self.assertEqual(ma.dates[0], s.dates[2])  # right-aligned

    def test_moving_average_too_short(self):
        self.assertEqual(len(mkseries([1.0, 2.0]).moving_average(5)), 0)

    def test_percentile_of_extremes(self):
        s = mkseries([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(s.percentile_of(4.0), 87.5)  # midpoint rule for ties
        self.assertAlmostEqual(s.percentile_of(0.0), 0.0)
        self.assertAlmostEqual(s.percentile_of(99.0), 100.0)

    def test_change_over_uses_calendar_not_position(self):
        """Weekly series: a 7-day lookback is one observation, not seven."""
        s = mkseries([1.0, 2.0, 3.0, 4.0], step_days=7)
        self.assertAlmostEqual(s.change_over(7), 1.0)
        self.assertAlmostEqual(s.change_over(21), 3.0)

    def test_change_over_insufficient_history(self):
        self.assertIsNone(mkseries([1.0]).change_over(7))
        self.assertIsNone(mkseries([1.0, 2.0]).change_over(9999))

    def test_ma_gap_z_flags_a_recent_break(self):
        """Flat series then a sharp move -> large positive z."""
        flat = [10.0 + (i % 2) * 0.05 for i in range(80)]
        broken = flat + [10.0 + 0.4 * i for i in range(1, 9)]
        z = mkseries(broken).ma_gap_z(4, 13)
        self.assertIsNotNone(z)
        self.assertGreater(z, 1.5)

    def test_ma_gap_z_is_quiet_on_a_steady_trend(self):
        """A steady trend with ordinary jitter is not an event: |z| stays small."""
        vals = [float(i) + (i % 5) * 0.1 for i in range(160)]
        z = mkseries(vals).ma_gap_z(4, 13)
        self.assertIsNotNone(z)
        self.assertLess(abs(z), 1.5)

    def test_ma_gap_z_none_on_degenerate_variance(self):
        """A perfect ramp leaves only FP residue in the gap; dividing by that would
        amplify rounding error to a maximal score, so it must return None."""
        self.assertIsNone(mkseries([float(i) for i in range(120)]).ma_gap_z(4, 13))

    def test_ma_gap_z_none_when_flat(self):
        """Zero variance must return None rather than divide by zero."""
        self.assertIsNone(mkseries([5.0] * 60).ma_gap_z(4, 13))

    def test_change_z_detects_sustained_move(self):
        noise = [10.0 + (i % 3) * 0.1 for i in range(120)]
        ramp = noise + [11.0 + 0.5 * i for i in range(20)]
        z = mkseries(ramp).change_z(10)
        self.assertIsNotNone(z)
        self.assertGreater(z, 1.0)

    def test_yoy_uses_frequency_specific_periods(self):
        monthly = mkseries([100.0 + i for i in range(30)], step_days=30)
        out = monthly.yoy_pct("monthly")
        self.assertAlmostEqual(out.values[0], 12.0)  # 100 -> 112

    def test_apply_transform_dispatch(self):
        s = mkseries([100.0, 110.0])
        self.assertEqual(apply_transform(s, "diff", "daily").values, [10.0])
        self.assertAlmostEqual(apply_transform(s, "mom_pct", "daily").values[0], 10.0)
        self.assertIs(apply_transform(s, "level", "daily"), s)

    def test_scaled_converts_units(self):
        self.assertEqual(mkseries([3.4]).scaled(100).values, [340.0])
        s = mkseries([1.0])
        self.assertIs(s.scaled(None), s)  # no-op must not copy


class TestFredParsing(unittest.TestCase):
    def test_drops_missing_observations(self):
        payload = {"observations": [
            {"date": "2026-01-01", "value": "1.5"},
            {"date": "2026-01-02", "value": "."},
            {"date": "2026-01-03", "value": "2.5"},
        ]}
        s = fred_fetcher._parse("X", payload)
        self.assertEqual(s.values, [1.5, 2.5])
        self.assertEqual(len(s.dates), 2)  # dates stay aligned with values

    def test_raises_without_observations_key(self):
        with self.assertRaises(FetchError):
            fred_fetcher._parse("X", {"error_code": 400})

    def test_real_fixture_parses(self):
        s = fred_fetcher.fetch_series("DGS10", "", 3, use_fixtures=True)
        self.assertGreater(len(s), 500)
        self.assertTrue(all(isinstance(v, float) for v in s.values))
        self.assertEqual(s.dates, sorted(s.dates))


class TestAlphaVantageParsing(unittest.TestCase):
    def test_sorts_ascending(self):
        payload = {"Time Series (Daily)": {
            "2026-01-03": {"4. close": "3.0"},
            "2026-01-01": {"4. close": "1.0"},
            "2026-01-02": {"4. close": "2.0"},
        }}
        s = av_fetcher._parse("X", payload)
        self.assertEqual(s.values, [1.0, 2.0, 3.0])

    def test_rate_limit_body_raises(self):
        """Alpha Vantage returns HTTP 200 with an error key - must not be silent."""
        for key in ("Note", "Information", "Error Message"):
            with self.assertRaises(FetchError):
                av_fetcher._parse("X", {key: "rate limit reached"})

    def test_budget_stops_requests(self):
        specs = [{"symbol": "SPY"}, {"symbol": "RSP"}, {"symbol": "XLK"}]
        out, errs = av_fetcher.fetch_all(specs, "", use_fixtures=True, budget=2)
        self.assertEqual(len(out), 2)
        self.assertIn("XLK", errs)
        self.assertIn("budget", errs["XLK"])


class TestIndicators(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.today = date(2026, 8, 10)

    def _spec(self, **kw):
        base = {"id": "T", "name": "T", "pillar": 1, "freq": "daily",
                "polarity": 1, "transform": "level", "unit": "%", "weight": 1.0,
                "decimals": 2}
        base.update(kw)
        return base

    def _daily(self, values):
        n = len(values)
        dates = [self.today - timedelta(days=n - 1 - i) for i in range(n)]
        return Series("T", dates, values)

    def test_polarity_flips_the_sign(self):
        rising = self._daily([10.0 + 0.4 * i for i in range(120)])
        up = build_reading(self._spec(polarity=1), rising, self.cfg, self.today)
        down = build_reading(self._spec(polarity=-1), rising, self.cfg, self.today)
        self.assertAlmostEqual(up.level, -down.level)
        self.assertAlmostEqual(up.drift, -down.drift)

    def test_insufficient_history_returns_none(self):
        self.assertIsNone(build_reading(self._spec(), self._daily([1.0, 2.0]),
                                        self.cfg, self.today))

    def test_stale_series_is_flagged(self):
        old = Series("T", [date(2025, 1, 1) + timedelta(days=i) for i in range(120)],
                     [float(i) for i in range(120)])
        r = build_reading(self._spec(), old, self.cfg, self.today)
        self.assertTrue(r.stale)

    def test_anchor_above_is_bad_dominates_when_crossed(self):
        """Sahm-style anchor: crossing the definitional line must read as bad."""
        vals = [0.1] * 100 + [0.55]
        spec = self._spec(polarity=-1, anchor=0.50, anchor_dir="above_is_bad")
        r = build_reading(spec, self._daily(vals), self.cfg, self.today)
        self.assertLess(r.level, 0)

    def test_smoothing_applied_before_transform(self):
        spiky = self._daily([100.0, 200.0] * 60)
        r = build_reading(self._spec(smooth=4), spiky, self.cfg, self.today)
        self.assertAlmostEqual(r.value, 150.0, places=6)

    def test_constant_ramp_scores_on_level_only(self):
        """A perfectly steady climb has the same change in every window, so both
        directional measures are correctly ~0 and `level` carries the whole signal.
        This is the real VIX-at-a-multi-year-high case: elevated, not accelerating."""
        ramp = self._daily([10.0 + 0.05 * i for i in range(300)])
        r = build_reading(self._spec(), ramp, self.cfg, self.today)
        self.assertGreater(r.level, 0.9)
        self.assertAlmostEqual(r.momentum, 0.0, places=6)
        self.assertAlmostEqual(r.trend, 0.0, places=6)

    def test_sustained_quarter_long_move_registers_as_drift(self):
        """Quiet, then a sustained rise over roughly a quarter: the configuration the
        `trend` dimension exists to catch, and it must reach `drift`."""
        import random
        rng = random.Random(7)
        vals = [10.0 + rng.gauss(0, 0.15) for _ in range(250)]
        vals += [10.0 + 0.06 * i + rng.gauss(0, 0.15) for i in range(1, 64)]
        r = build_reading(self._spec(), self._daily(vals), self.cfg, self.today)
        self.assertGreater(r.trend, 0.5)
        self.assertGreater(r.drift, 0.5)
        self.assertEqual(r.direction, "rising")


class TestPillarScoring(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def _reading(self, sid, score, weight=1.0, pillar=1, stale=False):
        return Reading(sid=sid, name=sid, pillar=pillar, unit="", decimals=2,
                       weight=weight, freq="daily", value=1.0, as_of=date(2026, 8, 10),
                       stale=stale, level=score, momentum=score, trend=score,
                       drift=score, score=score, percentile=50.0)

    def test_weighting_favours_heavier_indicators(self):
        readings = [self._reading("a", 1.0, weight=3.0), self._reading("b", -1.0, weight=1.0)]
        p = score_pillar(1, readings, self.cfg, expected_weight=4.0)
        self.assertGreater(p.score, 0.4)

    def test_low_coverage_reports_unknown(self):
        """Two of ten weighted units present must not yield a confident verdict."""
        p = score_pillar(1, [self._reading("a", 1.0, weight=2.0)], self.cfg,
                         expected_weight=10.0)
        self.assertFalse(p.known)
        self.assertEqual(p.state, "Unknown")

    def test_stale_readings_excluded_from_score(self):
        readings = [self._reading("a", 1.0, weight=1.0),
                    self._reading("b", 1.0, weight=1.0),
                    self._reading("c", -1.0, weight=1.0, stale=True)]
        p = score_pillar(1, readings, self.cfg, expected_weight=3.0)
        self.assertTrue(p.known)
        self.assertAlmostEqual(p.score, 1.0)   # stale -1.0 excluded
        self.assertLess(p.coverage, 1.0)

    def test_risk_tone_respects_axis_direction(self):
        """Pillar 1 up = expanding = good; pillar 4 up = stress = bad."""
        growth = score_pillar(1, [self._reading("a", 0.8)], self.cfg, 1.0)
        credit = score_pillar(4, [self._reading("a", 0.8, pillar=4)], self.cfg, 1.0)
        self.assertEqual(growth.risk_tone, "good")
        self.assertEqual(credit.risk_tone, "bad")

    def test_score_all_covers_five_pillars(self):
        specs = [{"pillar": n, "weight": 1.0} for n in (1, 2, 3, 4, 5)]
        readings = [self._reading("s%d" % n, 0.5, pillar=n) for n in (1, 2, 3, 4, 5)]
        out = score_all(readings, self.cfg, specs)
        self.assertEqual(sorted(out), [1, 2, 3, 4, 5])


class FakePillar(object):
    def __init__(self, num, score, known=True, state="X", readings=None):
        self.num, self.score, self.known, self.state = num, score, known, state
        self.readings = readings or []


class TestRegime(unittest.TestCase):
    def test_goldilocks_profile_matches(self):
        pillars = {1: FakePillar(1, 0.5), 2: FakePillar(2, -0.4), 3: FakePillar(3, -0.4),
                   4: FakePillar(4, -0.5), 5: FakePillar(5, 0.5)}
        self.assertEqual(regime.classify(pillars).regime, "Goldilocks")

    def test_stagflation_profile_matches(self):
        pillars = {1: FakePillar(1, -0.4), 2: FakePillar(2, 0.6), 3: FakePillar(3, 0.5),
                   4: FakePillar(4, 0.4), 5: FakePillar(5, -0.4)}
        self.assertEqual(regime.classify(pillars).regime, "Stagflation")

    def test_risk_off_profile_matches(self):
        pillars = {1: FakePillar(1, -0.7), 2: FakePillar(2, -0.3), 3: FakePillar(3, 0.4),
                   4: FakePillar(4, 0.8), 5: FakePillar(5, -0.7)}
        self.assertEqual(regime.classify(pillars).regime, "Risk-Off")

    def test_withholds_verdict_below_three_pillars(self):
        pillars = {1: FakePillar(1, 0.5), 2: FakePillar(2, 0.0, known=False),
                   3: FakePillar(3, 0.0, known=False), 4: FakePillar(4, 0.0, known=False),
                   5: FakePillar(5, 0.0, known=False)}
        d = regime.classify(pillars)
        self.assertEqual(d.regime, "Indeterminate")
        self.assertEqual(d.confidence, 0.0)

    def test_unknown_pillars_excluded_not_zeroed(self):
        """A missing pillar must not be scored as 0.0, which would bias the match."""
        full = {n: FakePillar(n, s) for n, s in
                ((1, 0.5), (2, -0.4), (3, -0.4), (4, -0.5), (5, 0.5))}
        partial = dict(full)
        partial[2] = FakePillar(2, 0.0, known=False)
        self.assertEqual(regime.classify(partial).regime, "Goldilocks")
        self.assertIn("2", " ".join(regime.classify(partial).notes))

    def test_ambiguous_reading_lowers_confidence(self):
        clear = {n: FakePillar(n, s) for n, s in
                 ((1, 0.5), (2, -0.4), (3, -0.4), (4, -0.5), (5, 0.5))}
        muddy = {n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}
        self.assertGreater(regime.classify(clear).confidence,
                           regime.classify(muddy).confidence)

    def test_direction_from_previous_snapshot(self):
        now = {n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}
        now[4] = FakePillar(4, 0.6)  # credit stress up = deterioration
        prev = {n: {"score": 0.0, "known": True} for n in (1, 2, 3, 4, 5)}
        self.assertEqual(regime.classify(now, prev).direction, "Deteriorating")

    def test_every_regime_has_capital_flows(self):
        for name in regime.PROFILES:
            self.assertIn(name, regime.CAPITAL_FLOWS)
            self.assertTrue(regime.CAPITAL_FLOWS[name]["favored"])


class TestSignals(unittest.TestCase):
    def _r(self, sid, value, drift=0.0):
        return Reading(sid=sid, name=sid, pillar=1, unit="", decimals=2, weight=1.0,
                       freq="daily", value=value, as_of=date(2026, 8, 10), stale=False,
                       level=0.0, momentum=drift, trend=drift, drift=drift, score=0.0,
                       chg_1m=value)

    def test_sahm_trigger_fires_at_threshold(self):
        s = signals._sahm_trigger({"SAHMREALTIME": self._r("SAHMREALTIME", 0.50)})
        self.assertEqual(s.tone, "alert")

    def test_sahm_quiet_below_watch_level(self):
        self.assertIsNone(signals._sahm_trigger({"SAHMREALTIME": self._r("SAHMREALTIME", 0.20)}))

    def test_vix_with_credit_is_alert_without_is_watch(self):
        vix = self._r("VIXCLS", 32.0, drift=0.6)
        systemic = signals._vix_credit_cross_check(
            {"VIXCLS": vix, "BAMLH0A0HYM2": self._r("BAMLH0A0HYM2", 520.0, drift=0.6)}, {})
        event = signals._vix_credit_cross_check(
            {"VIXCLS": vix, "BAMLH0A0HYM2": self._r("BAMLH0A0HYM2", 300.0, drift=0.0)}, {})
        self.assertEqual(systemic.tone, "alert")
        self.assertEqual(event.tone, "watch")

    def test_inversion_reading_depends_on_driver(self):
        """Spec 2.3: term-premium-driven inversion is not the same signal."""
        readings = {"T10Y2Y": self._r("T10Y2Y", -0.3),
                    "THREEFYTP10": self._r("THREEFYTP10", 0.9)}
        technical = signals._curve_inversion_quality(readings, {1: FakePillar(1, 0.4)})
        genuine = signals._curve_inversion_quality(readings, {1: FakePillar(1, -0.5)})
        self.assertEqual(technical.key, "inversion_term_premium")
        self.assertEqual(technical.tone, "watch")
        self.assertEqual(genuine.key, "inversion_expectations")
        self.assertEqual(genuine.tone, "alert")

    def test_no_inversion_no_signal(self):
        readings = {"T10Y2Y": self._r("T10Y2Y", 0.5), "THREEFYTP10": self._r("THREEFYTP10", 0.9)}
        self.assertIsNone(signals._curve_inversion_quality(readings, {1: FakePillar(1, -0.5)}))

    def test_narrow_and_broad_rally_are_distinguished(self):
        readings = {"SPY_TREND": self._r("SPY_TREND", 3.0)}
        self.assertEqual(signals._narrow_rally(readings, {"1m": -2.5}).key, "narrow_rally")
        self.assertEqual(signals._narrow_rally(readings, {"1m": 2.5}).key, "broad_rally")
        self.assertIsNone(signals._narrow_rally(readings, {"1m": 0.1}))

    def test_detectors_tolerate_missing_inputs(self):
        """Every detector must return None rather than raise when data is absent."""
        empty_pillars = {n: FakePillar(n, 0.0, known=False) for n in (1, 2, 3, 4, 5)}
        self.assertEqual(signals.evaluate({}, empty_pillars, None, {}), [])

    def test_evaluate_sorts_alerts_first(self):
        readings = {"SAHMREALTIME": self._r("SAHMREALTIME", 0.55),
                    "SPY_TREND": self._r("SPY_TREND", 3.0)}
        out = signals.evaluate(readings, {1: FakePillar(1, 0.0)}, {"1m": -2.5}, {})
        self.assertEqual(out[0].tone, "alert")


class TestMarket(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def _prices(self, start, end, n=80):
        step = (end - start) / (n - 1)
        return mkseries([start + step * i for i in range(n)])

    def test_relative_strength_sign(self):
        strong, weak = self._prices(100, 110), self._prices(100, 105)
        rs = market.relative_strength(strong, weak, {"1m": 21})
        self.assertGreater(rs["1m"], 0)

    def test_breadth_negative_when_equal_weight_lags(self):
        series = {"SPY": self._prices(100, 112), "RSP": self._prices(100, 103)}
        reading, rs = market.breadth_reading(series, self.cfg, date(2026, 8, 10))
        self.assertLess(rs["1m"], 0)
        self.assertLess(reading.score, 0)

    def test_breadth_none_when_rsp_missing(self):
        reading, rs = market.breadth_reading({"SPY": self._prices(100, 110)},
                                             self.cfg, date(2026, 8, 10))
        self.assertIsNone(reading)

    def test_sector_table_sorted_by_one_month(self):
        specs = [{"symbol": "XLK", "name": "Tech", "role": "sector"},
                 {"symbol": "XLE", "name": "Energy", "role": "sector"}]
        series = {"SPY": self._prices(100, 105), "XLK": self._prices(100, 115),
                  "XLE": self._prices(100, 98)}
        rows = market.sector_table(series, specs, "SPY", self.cfg)
        self.assertEqual([r["symbol"] for r in rows], ["XLK", "XLE"])


class TestEmailBuilder(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def _reading(self, sid, value, drift=0.5, weight=1.0, unit="%"):
        return Reading(sid=sid, name=sid, pillar=1, unit=unit, decimals=2, weight=weight,
                       freq="daily", value=value, as_of=date(2026, 8, 10), stale=False,
                       level=0.5, momentum=drift, trend=drift, drift=drift, score=0.5,
                       chg_1d=0.1, chg_1w=0.3, chg_1m=0.9, percentile=80.0,
                       direction="rising")

    def _ctx(self, **over):
        pillars = score_all([], self.cfg, [{"pillar": n, "weight": 1.0} for n in range(1, 6)])
        ctx = {
            "date": date(2026, 8, 10),
            "diagnosis": regime.classify({n: FakePillar(n, 0.0) for n in (1, 2, 3, 4, 5)}),
            "pillars": pillars,
            "readings": [self._reading("A", 4.3)],
            "signals": [],
            "key_levels": [self._reading("A", 4.3)],
            "sectors": [],
            "sector_note": "",
            "global_rows": [],
            "errors": {},
        }
        ctx.update(over)
        return ctx

    def test_pp_and_percent_render_differently(self):
        self.assertEqual(email_builder._fmt_num(0.41, 2, "pp"), "0.41pp")
        self.assertEqual(email_builder._fmt_num(4.31, 2, "%"), "4.31%")
        self.assertEqual(email_builder._fmt_num(340.0, 0, "bps"), "340 bps")

    def test_fmt_change_signs_and_none(self):
        self.assertEqual(email_builder.fmt_change(None, 2, "%"), "-")
        self.assertTrue(email_builder.fmt_change(0.5, 2, "%").startswith("+"))
        self.assertTrue(email_builder.fmt_change(-0.5, 2, "%").startswith("-"))

    def test_movers_rank_by_drift_and_weight(self):
        big = self._reading("BIG", 1.0, drift=0.9, weight=2.5)
        small = self._reading("SMALL", 1.0, drift=0.25, weight=0.5)
        self.assertEqual(email_builder.movers([small, big])[0].sid, "BIG")

    def test_movers_skips_stale_and_quiet(self):
        quiet = self._reading("QUIET", 1.0, drift=0.01, weight=0.5)
        self.assertEqual(email_builder.movers([quiet]), [])

    def test_html_escapes_and_has_no_external_refs(self):
        r = self._reading("<script>x</script>", 1.0)
        html = email_builder.build_html(self._ctx(readings=[r], key_levels=[r]))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("http://", html)

    def test_subject_flags_alert_count(self):
        sig = signals.Signal("k", "t", "d", "alert")
        subject, _, _ = email_builder.build(self._ctx(signals=[sig]))
        self.assertIn("1 ALERT", subject)
        subject_quiet, _, _ = email_builder.build(self._ctx())
        self.assertNotIn("ALERT", subject_quiet)

    def test_both_bodies_render_without_optional_sections(self):
        subject, text, html = email_builder.build(self._ctx())
        self.assertTrue(subject and text and html)
        self.assertIn("MARKET BRIEF", text)
        self.assertIn("Pillar scores", html)

    def test_errors_surface_in_both_bodies(self):
        ctx = self._ctx(errors={"DGS10": "boom"})
        _, text, html = email_builder.build(ctx)
        self.assertIn("DGS10", text)
        self.assertIn("DGS10", html)


class TestEmailSender(unittest.TestCase):
    def test_multipart_has_text_and_html(self):
        from src.output.email_sender import EmailConfig, build_message
        cfg = EmailConfig("h", 587, "u@x.com", "p", "u@x.com", ["a@b.com"])
        msg = build_message(cfg, "Subj", "plain", "<b>html</b>")
        types = [p.get_content_type() for p in msg.walk()]
        self.assertIn("text/plain", types)
        self.assertIn("text/html", types)

    def test_unconfigured_is_detected(self):
        from src.output.email_sender import EmailConfig
        self.assertFalse(EmailConfig("h", 587, "", "", "", []).configured)


class TestConfigIntegrity(unittest.TestCase):
    """Guards against config drift - a typo here fails silently at 6am."""

    def setUp(self):
        with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
            self.fred = json.load(fh)
        with open(os.path.join(ROOT, "config", "av_symbols.json")) as fh:
            self.av = json.load(fh)
        self.cfg = load_cfg()

    def test_no_duplicate_series_ids(self):
        ids = [s["id"] for s in self.fred["series"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_removed_series_are_not_still_referenced(self):
        active = {s["id"] for s in self.fred["series"]}
        for dead in self.fred["removed"]:
            self.assertNotIn(dead["id"], active, "%s is discontinued" % dead["id"])

    def test_every_series_has_required_fields(self):
        for s in self.fred["series"]:
            for field in ("id", "name", "pillar", "freq", "polarity", "transform", "weight"):
                self.assertIn(field, s, "%s missing %s" % (s["id"], field))
            self.assertIn(s["freq"], self.cfg["staleness_days"])
            self.assertIn(s["polarity"], (-1, 0, 1))
            self.assertIn(s["transform"], ("level", "diff", "mom_pct", "yoy_pct"))

    def test_scored_pillars_have_state_labels(self):
        for n in (1, 2, 3, 4, 5):
            labels = self.cfg["pillar_states"][str(n)]["labels"]
            self.assertEqual(len(labels), 5)

    def test_alpha_vantage_stays_within_free_tier(self):
        used = len(self.av["symbols"])
        self.assertLessEqual(used, self.av["budget"]["free_tier_daily_limit"])
        self.assertEqual(used, self.av["budget"]["requests_per_run"])

    def test_key_levels_reference_real_ids(self):
        from src.main import KEY_LEVEL_IDS
        known = {s["id"] for s in self.fred["series"]} | {"RSP_SPY", "SPY_TREND"}
        for sid in KEY_LEVEL_IDS:
            self.assertIn(sid, known)


if __name__ == "__main__":
    unittest.main(verbosity=2)
