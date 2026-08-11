"""Market-price derived measures: breadth (RSP vs SPY) and sector relative strength.

These are the Pillar 5 inputs that FRED cannot supply. Everything here works off
Alpha Vantage daily closes, so windows are counted in trading days.
"""
from __future__ import annotations

from .indicators import Reading


def _return_over(series, bars):
    """Percent return over the last `bars` trading days."""
    if series is None or len(series) <= bars:
        return None
    prior = series.values[-1 - bars]
    if prior == 0:
        return None
    return (series.values[-1] - prior) / prior * 100.0


def relative_strength(symbol_series, benchmark_series, windows):
    """Percentage-point out/underperformance vs the benchmark, per window."""
    out = {}
    for label, bars in windows.items():
        a = _return_over(symbol_series, bars)
        b = _return_over(benchmark_series, bars)
        out[label] = None if (a is None or b is None) else a - b
    return out


def sector_table(series_by_symbol, specs, benchmark, cfg):
    """Relative strength of every sector ETF vs SPY, sorted strongest-first on 1m."""
    windows = cfg["breadth"]["windows_days"]
    bench = series_by_symbol.get(benchmark)
    rows = []
    for spec in specs:
        if spec.get("role") != "sector":
            continue
        s = series_by_symbol.get(spec["symbol"])
        if s is None or bench is None:
            continue
        rs = relative_strength(s, bench, windows)
        rows.append({
            "symbol": spec["symbol"],
            "name": spec["name"],
            "last": s.latest,
            "rs": rs,
            "abs_1m": _return_over(s, windows["1m"]),
        })
    rows.sort(key=lambda r: (r["rs"].get("1m") is None, -(r["rs"].get("1m") or 0)))
    return rows


def breadth_reading(series_by_symbol, cfg, today):
    """RSP vs SPY as a Pillar 5 Reading.

    Equal-weight underperforming cap-weight means the index is being carried by its
    largest members - the narrowness signal from spec 6.
    """
    spy, rsp = series_by_symbol.get("SPY"), series_by_symbol.get("RSP")
    if spy is None or rsp is None:
        return None, None

    windows = cfg["breadth"]["windows_days"]
    rs = relative_strength(rsp, spy, windows)
    narrow, broad = cfg["breadth"]["narrow_pp"], cfg["breadth"]["broad_pp"]

    ref = rs.get("1m")
    if ref is None:
        return None, rs

    # Map relative performance onto the Pillar 5 axis (up = healthier).
    if ref <= narrow * 2:
        score = -1.0
    elif ref >= broad * 2:
        score = 1.0
    else:
        score = max(-1.0, min(1.0, ref / (broad * 2)))

    short_ref = rs.get("1w")
    momentum = 0.0 if short_ref is None else max(-1.0, min(1.0, short_ref / (broad * 2)))

    reading = Reading(
        sid="RSP_SPY", name="Breadth: RSP vs SPY", pillar=5, unit="pp", decimals=2,
        weight=2.5, freq="daily", value=ref, as_of=rsp.latest_date, stale=False,
        level=score, momentum=momentum, trend=score, drift=momentum,
        score=max(-1.0, min(1.0, 0.6 * score + 0.4 * momentum)),
        chg_1d=None, chg_1w=rs.get("1w"), chg_1m=rs.get("1m"), percentile=None,
        anchor_note="negative = cap-weight leading, rally narrowing",
        direction="rising" if momentum > 0.25 else ("falling" if momentum < -0.25 else "flat"),
    )
    return reading, rs


def index_trend_reading(series_by_symbol, cfg, today):
    """SPY's own trend as a supporting Pillar 5 input."""
    spy = series_by_symbol.get("SPY")
    if spy is None:
        return None
    windows = cfg["breadth"]["windows_days"]
    r1m = _return_over(spy, windows["1m"])
    r3m = _return_over(spy, windows["3m"])
    if r1m is None:
        return None

    score = max(-1.0, min(1.0, r1m / 5.0))
    momentum = 0.0 if r3m is None else max(-1.0, min(1.0, (r1m - r3m / 3.0) / 3.0))
    return Reading(
        sid="SPY_TREND", name="S&P 500 trend (1m)", pillar=5, unit="%", decimals=2,
        weight=1.0, freq="daily", value=r1m, as_of=spy.latest_date, stale=False,
        level=score, momentum=momentum, trend=score, drift=momentum,
        score=max(-1.0, min(1.0, 0.5 * score + 0.5 * momentum)),
        chg_1d=None, chg_1w=_return_over(spy, windows["1w"]), chg_1m=r1m,
        percentile=None, anchor_note=None,
        direction="rising" if momentum > 0.25 else ("falling" if momentum < -0.25 else "flat"),
    )
