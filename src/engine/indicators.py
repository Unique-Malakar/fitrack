"""Turn a raw Series into a scored Reading.

Every indicator produces two independent dimensions, per spec 5.1:
  level    - where it sits in its OWN trailing distribution (percentile-based),
             optionally blended with a structural anchor
  momentum - short MA vs long MA, measured in the series' own change-volatility

Both are signed along the parent pillar's axis, so a pillar score is just a
weighted mean of its readings. No universal level thresholds are used; the only
absolute numbers are structural boundaries declared per-series (`anchor`).
"""
from __future__ import annotations

from .timeseries import apply_transform


class Reading(object):
    __slots__ = (
        "sid", "name", "pillar", "unit", "decimals", "weight", "freq",
        "value", "as_of", "stale", "level", "momentum", "trend", "drift", "score",
        "chg_1d", "chg_1w", "chg_1m", "percentile", "anchor_note", "direction",
    )

    def __init__(self, **kw):
        for slot in self.__slots__:
            setattr(self, slot, kw.get(slot))

    def as_dict(self):
        d = {}
        for slot in self.__slots__:
            v = getattr(self, slot)
            d[slot] = v.isoformat() if hasattr(v, "isoformat") else v
        return d


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _level_score(series, spec, cfg):
    """Percentile of the latest value in its own history, mapped to [-1, 1]."""
    bands = cfg["level_percentile_bands"]
    pct = series.percentile_of(series.latest)
    if pct is None:
        return 0.0, None

    # Piecewise-linear: 0th pct -> -1, 50th -> 0, 100th -> +1, with the
    # configured bands controlling where the flat middle sits.
    if pct <= bands["very_low"]:
        score = -1.0
    elif pct >= bands["very_high"]:
        score = 1.0
    elif pct < bands["low"]:
        span = bands["low"] - bands["very_low"]
        score = -1.0 + 0.5 * (pct - bands["very_low"]) / span
    elif pct > bands["high"]:
        span = bands["very_high"] - bands["high"]
        score = 0.5 + 0.5 * (pct - bands["high"]) / span
    else:
        span = bands["high"] - bands["low"] or 1.0
        score = -0.5 + 1.0 * (pct - bands["low"]) / span

    # Blend in a structural boundary if this series has one.
    anchor = spec.get("anchor")
    if anchor is not None:
        crossed = series.latest >= anchor
        if spec.get("anchor_dir") == "above_is_bad":
            anchor_score = 1.0 if crossed else -0.2
        else:
            anchor_score = 1.0 if crossed else -1.0
        w = cfg["anchor_weight"]
        score = (1 - w) * score + w * anchor_score

    return _clamp(score), pct


def _momentum_score(series, cfg):
    """Short MA vs long MA, z-scored against that gap's own historical spread.

    Normalising against the gap's own distribution (rather than single-period change
    volatility) makes the score self-calibrating: z = 2 means the same thing for VIX
    as for NFCI, despite noise profiles that differ by orders of magnitude.
    """
    m = cfg["momentum"]
    z = series.ma_gap_z(m["short_window"], m["long_window"])
    if z is None or abs(z) < m["mild_sigma"]:
        return 0.0
    return _clamp(z / (m["strong_sigma"] * 2.0))


# How many periods make up a "medium-term" window for each release frequency,
# targeting roughly one quarter in every case.
_TREND_PERIODS = {"daily": 63, "weekly": 13, "monthly": 3, "quarterly": 1}


def _trend_score(series, freq, cfg):
    """Sustained direction over roughly a quarter, in the series' own units."""
    periods = _TREND_PERIODS.get(freq, 3)
    z = series.change_z(periods)
    if z is None:
        return 0.0
    m = cfg["momentum"]
    if abs(z) < m["mild_sigma"]:
        return 0.0
    return _clamp(z / (m["strong_sigma"] * 2.0))


def _is_stale(as_of, freq, today, cfg):
    limit = cfg["staleness_days"].get(freq)
    if limit is None or as_of is None:
        return False
    return (today - as_of).days > limit


def build_reading(spec, raw_series, cfg, today):
    """Score one indicator. Returns None when there is not enough data to judge."""
    freq = spec.get("freq", "monthly")

    series = raw_series
    if spec.get("smooth"):
        smoothed = series.moving_average(spec["smooth"])
        if smoothed:
            series = smoothed

    series = apply_transform(series, spec.get("transform", "level"), freq)
    if len(series) < 4:
        return None

    window = series.since(_cutoff(today, cfg["history_years"]))
    if len(window) < 4:
        window = series

    level, pct = _level_score(window, spec, cfg)
    momentum = _momentum_score(window, cfg)
    trend = _trend_score(window, freq, cfg)
    polarity = spec.get("polarity", 1)

    # `direction` describes the RAW series, because it is displayed beside the raw
    # value and its own change. Polarity-adjusting it would print "falling" next to
    # a rising number - Sahm at 0.41pp, +0.02pp on the week, "falling".
    raw_drift = _clamp(0.5 * momentum + 0.5 * trend)

    level *= polarity
    momentum *= polarity
    trend *= polarity

    # `drift` is the combined direction-of-travel along the PILLAR AXIS: short-term
    # acceleration plus sustained medium-term direction. Detectors key off this
    # rather than momentum alone, so a slow grind to a multi-year extreme still
    # registers as moving against the pillar.
    drift = _clamp(0.5 * momentum + 0.5 * trend)

    # Spec 2.3 favours direction of change over absolute level, hence the tilt
    # toward the two directional dimensions.
    score = _clamp(0.4 * level + 0.6 * drift)

    return Reading(
        sid=spec["id"],
        name=spec["name"],
        pillar=spec["pillar"],
        unit=spec.get("unit", ""),
        decimals=spec.get("decimals", 2),
        weight=spec.get("weight", 1.0),
        freq=freq,
        value=series.latest,
        as_of=series.latest_date,
        stale=_is_stale(series.latest_date, freq, today, cfg),
        level=level,
        momentum=momentum,
        trend=trend,
        drift=drift,
        score=score,
        chg_1d=series.change_over(1) if freq == "daily" else None,
        chg_1w=series.change_over(7),
        chg_1m=series.change_over(30),
        percentile=pct,
        anchor_note=spec.get("anchor_note"),
        direction=_direction(raw_drift),
    )


def _direction(drift):
    if drift > 0.25:
        return "rising"
    if drift < -0.25:
        return "falling"
    return "flat"


def _cutoff(today, years):
    from datetime import timedelta
    return today - timedelta(days=int(365.25 * years))
