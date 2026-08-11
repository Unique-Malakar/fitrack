"""Cross-asset relationship checks (spec 6).

These fire only when two or more series DISAGREE in a specific, named way. That is
where the insight lives - any single indicator is noise, but credit widening while
equities rally is a statement. Each detector returns None when its inputs are
missing, so partial data silently reduces coverage instead of inventing signals.

Every detector reports a `tone`: 'alert' (act on it), 'watch', or 'good'.
"""
from __future__ import annotations


def _r(readings, sid):
    return readings.get(sid)


def _val(readings, sid, field="value"):
    r = readings.get(sid)
    return getattr(r, field, None) if r else None


def _rising(readings, sid, threshold=0.25):
    """Direction of travel, using the combined drift (short acceleration + medium
    trend) rather than momentum alone - a series grinding steadily to a multi-year
    extreme is rising even when it is not accelerating."""
    r = readings.get(sid)
    return r is not None and r.drift is not None and r.drift >= threshold


def _falling(readings, sid, threshold=0.25):
    r = readings.get(sid)
    return r is not None and r.drift is not None and r.drift <= -threshold


class Signal(object):
    __slots__ = ("key", "title", "detail", "tone")

    def __init__(self, key, title, detail, tone):
        self.key, self.title, self.detail, self.tone = key, title, detail, tone

    def as_dict(self):
        return {"key": self.key, "title": self.title, "detail": self.detail, "tone": self.tone}


def _narrow_rally(readings, breadth_rs):
    spy_1m = _val(readings, "SPY_TREND", "chg_1m")
    rsp_rel = breadth_rs.get("1m") if breadth_rs else None
    if spy_1m is None or rsp_rel is None:
        return None
    if spy_1m > 1.0 and rsp_rel < -1.0:
        return Signal(
            "narrow_rally", "Rally is narrow",
            "S&P up %.1f%% over the month while equal-weight lags cap-weight by %.1fpp. "
            "The gain is concentrated in the largest names, which is a fragility signal, "
            "not a strength signal." % (spy_1m, abs(rsp_rel)), "watch")
    if spy_1m > 1.0 and rsp_rel > 1.0:
        return Signal(
            "broad_rally", "Rally is broadening",
            "S&P up %.1f%% and equal-weight leading by %.1fpp - participation is widening, "
            "the healthiest configuration for a rally." % (spy_1m, rsp_rel), "good")
    return None


def _vix_credit_cross_check(readings, breadth_rs):
    """Spec 2.3: a VIX spike is only a contrarian buy if credit is NOT confirming."""
    vix = _r(readings, "VIXCLS")
    hy = _r(readings, "BAMLH0A0HYM2")
    if vix is None or hy is None:
        return None
    if not _rising(readings, "VIXCLS", 0.35):
        return None

    credit_stressed = _rising(readings, "BAMLH0A0HYM2", 0.35)
    breadth_washed = (breadth_rs or {}).get("1m")
    breadth_txt = ("breadth washed out" if (breadth_washed is not None and breadth_washed < -1.0)
                   else "breadth intact")

    if credit_stressed:
        return Signal(
            "vix_systemic", "Volatility WITH credit confirming",
            "VIX at %.1f and rising while HY spreads widen to %.0fbps (%s). Credit is "
            "corroborating the equity stress, so this reads closer to systemic than to an "
            "event-driven spike - the configuration where more downside typically follows."
            % (vix.value, hy.value, breadth_txt), "alert")
    return Signal(
        "vix_event", "Volatility WITHOUT credit confirming",
        "VIX at %.1f and rising but HY spreads at %.0fbps are not corroborating (%s). "
        "Historically the event-driven pattern that resolves upward - but it is only a "
        "contrarian signal while credit stays calm."
        % (vix.value, hy.value, breadth_txt), "watch")


def _conditions_lead_growth(readings, pillars):
    """NFCI tightening while growth still reads positive - the early warning."""
    nfci = _r(readings, "NFCI")
    if nfci is None or not _rising(readings, "NFCI", 0.3):
        return None
    growth = pillars.get(1)
    if growth is None or not growth.known or growth.score <= 0:
        return None
    return Signal(
        "conditions_lead", "Conditions tightening ahead of growth",
        "NFCI at %.2f and tightening while Growth still reads %s. Financial conditions "
        "lead activity, so this is the sequence that precedes a growth downgrade rather "
        "than confirming one." % (nfci.value, growth.state), "watch")


def _fed_vs_long_end(readings):
    """Fed easing but long yields rising - the market pricing something the Fed isn't."""
    if not _falling(readings, "DFF", 0.2):
        return None
    if not _rising(readings, "DGS30", 0.25):
        return None
    tp = _r(readings, "THREEFYTP10")
    tp_txt = (" Term premium at %.2f%% is doing the work, which points at fiscal/supply "
              "risk rather than growth optimism." % tp.value) if tp and _rising(readings, "THREEFYTP10", 0.2) else ""
    return Signal(
        "fed_vs_long_end", "Fed easing, long end rising",
        "Policy rate falling while the 30Y climbs to %.2f%%. The market is pricing "
        "something the Fed is not - typically fiscal supply or inflation persistence.%s"
        % (_val(readings, "DGS30"), tp_txt), "alert")


def _curve_inversion_quality(readings, pillars):
    """Spec 2.3: an inversion's meaning depends on WHICH component drives it."""
    t10y2y = _r(readings, "T10Y2Y")
    if t10y2y is None or t10y2y.value is None or t10y2y.value >= 0:
        return None

    tp = _r(readings, "THREEFYTP10")
    growth = pillars.get(1)
    labor_weak = growth is not None and growth.known and growth.score < -0.13

    tp_driven = tp is not None and tp.value is not None and tp.value > 0.5
    if tp_driven and not labor_weak:
        return Signal(
            "inversion_term_premium", "Curve inverted - term-premium driven",
            "2s10s at %.2f%% with term premium elevated at %.2f%% and labour data stable. "
            "Per the Cleveland Fed's reassessment of 2022-24, a term-premium-driven "
            "inversion carries far less recession signal than an expectations-driven one. "
            "Treat as technical until labour or credit confirms."
            % (t10y2y.value, tp.value), "watch")
    if labor_weak:
        return Signal(
            "inversion_expectations", "Curve inverted WITH labour deteriorating",
            "2s10s at %.2f%% and Growth reading %s. Inversion plus deteriorating labour is "
            "the combination that has carried genuine predictive weight - take seriously."
            % (t10y2y.value, growth.state), "alert")
    return None


def _gold_vs_real_yields(readings, market_series):
    """Spec 2.3: the gold/real-yield correlation broke down post-2022."""
    gld = market_series.get("GLD")
    real = _r(readings, "DFII10")
    if gld is None or real is None or len(gld) < 25:
        return None

    gold_1m = (gld.values[-1] - gld.values[-21]) / gld.values[-21] * 100.0 if len(gld) > 21 else None
    if gold_1m is None:
        return None
    if gold_1m > 2.0 and _rising(readings, "DFII10", 0.25):
        return Signal(
            "gold_decoupled", "Gold rising WITH real yields",
            "Gold up %.1f%% over the month while the 10Y real yield rises to %.2f%%. The "
            "textbook inverse relationship is not operating - consistent with central bank "
            "buying running near twice its historical pace. Read gold as a reserve-demand "
            "signal here, not a real-rate signal." % (gold_1m, real.value), "watch")
    return None


def _sahm_trigger(readings):
    sahm = _r(readings, "SAHMREALTIME")
    if sahm is None or sahm.value is None:
        return None
    if sahm.value >= 0.50:
        return Signal(
            "sahm_triggered", "Sahm Rule triggered",
            "Real-time Sahm indicator at %.2f, at or above the 0.50 recession threshold. "
            "This is a confirmation trigger, not a forecast - labour deterioration has "
            "already crossed the historical line." % sahm.value, "alert")
    if sahm.value >= 0.35:
        return Signal(
            "sahm_approaching", "Sahm Rule approaching trigger",
            "Real-time Sahm indicator at %.2f, closing on the 0.50 threshold." % sahm.value,
            "watch")
    return None


def _credit_divergence(readings, pillars):
    """Credit deteriorating while equities hold up - the independent confirmation check."""
    hy = _r(readings, "BAMLH0A0HYM2")
    spy_1m = _val(readings, "SPY_TREND", "chg_1m")
    if hy is None or spy_1m is None:
        return None
    if _rising(readings, "BAMLH0A0HYM2", 0.35) and spy_1m > 0:
        return Signal(
            "credit_divergence", "Credit widening while equities hold",
            "HY spreads widening to %.0fbps with the S&P still up %.1f%% on the month. "
            "Credit markets price default and financing risk more directly, which makes "
            "this divergence a useful independent warning rather than confirmation."
            % (hy.value, spy_1m), "alert")
    return None


def evaluate(readings, pillars, breadth_rs, market_series):
    """Run every detector. `readings` is a dict of sid -> Reading."""
    candidates = [
        _sahm_trigger(readings),
        _credit_divergence(readings, pillars),
        _vix_credit_cross_check(readings, breadth_rs),
        _curve_inversion_quality(readings, pillars),
        _fed_vs_long_end(readings),
        _conditions_lead_growth(readings, pillars),
        _narrow_rally(readings, breadth_rs),
        _gold_vs_real_yields(readings, market_series),
    ]
    signals = [s for s in candidates if s is not None]
    order = {"alert": 0, "watch": 1, "good": 2}
    signals.sort(key=lambda s: order.get(s.tone, 3))
    return signals
