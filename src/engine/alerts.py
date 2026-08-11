"""Alert layer (Phase 3).

Triggers on single-session moves large enough to plausibly mark a regime change -
the August 2024 yen unwind or April 2025 tariff shock, not ordinary volatility.

Design constraints that shaped this:

1. COOLDOWN. The spec wants a few firings per quarter. A raw threshold on a
   persistent condition (VIX above 30) re-fires every run for as long as it holds,
   which trains you to ignore it. Each trigger therefore fires once, then stays
   quiet until it either resets below the threshold or materially worsens.

2. CADENCE. Alpha Vantage's free tier allows 25 requests/day and the morning brief
   spends 14, so genuine intraday polling is not affordable. More decisively, the
   highest-value triggers (VIX, HY spreads, NFCI, yields) are FRED series that only
   update once daily - polling them hourly cannot surface anything new. This module
   is therefore source-honest: it evaluates whatever the latest observation is, and
   is designed to run after each daily FRED update.
"""
from __future__ import annotations

from datetime import date, timedelta

# Thresholds are single-session MOVES, not levels, except where the spec named a
# level explicitly (VIX). Moves are inherently scale-free in a way levels are not,
# which is why these survive the spec's removal of hard level thresholds.
TRIGGERS = [
    {"key": "vix_level", "sid": "VIXCLS", "mode": "level_above", "value": 30.0,
     "worsen": 5.0, "tone": "critical",
     "label": "VIX above 30",
     "why": "Options markets are pricing sustained disorder rather than a single event."},
    {"key": "vix_spike", "sid": "VIXCLS", "mode": "level_above", "value": 40.0,
     "worsen": 8.0, "tone": "critical", "supersedes": ["vix_level"],
     "label": "VIX above 40",
     "why": "Historically the zone where forced deleveraging, not opinion, drives prices."},
    {"key": "hy_widening", "sid": "BAMLH0A0HYM2", "mode": "change_up", "value": 25.0,
     "worsen": 15.0, "tone": "critical",
     "label": "HY spreads widened more than 25bps in a session",
     "why": "Credit repricing this fast usually leads equities rather than following."},
    {"key": "ig_widening", "sid": "BAMLC0A0CM", "mode": "change_up", "value": 15.0,
     "worsen": 10.0, "tone": "serious",
     "label": "IG spreads widened more than 15bps in a session",
     "why": "Stress reaching investment grade means it is no longer contained to junk."},
    {"key": "twos_repricing", "sid": "DGS2", "mode": "change_abs", "value": 0.15,
     "worsen": 0.10, "tone": "serious",
     "label": "2-year yield moved more than 15bps in a session",
     "why": "The 2Y is the Fed-expectations tenor; a move this size is a policy repricing."},
    {"key": "usdjpy_move", "sid": "DEXJPUS", "mode": "pct_abs", "value": 2.0,
     "worsen": 1.0, "tone": "critical",
     "label": "USD/JPY moved more than 2% in a session",
     "why": "The yen funds a large share of global carry; sharp moves force unwinds "
            "far from Japan."},
    {"key": "nfci_flip", "sid": "NFCI", "mode": "cross_above", "value": 0.0,
     "worsen": 0.15, "tone": "serious",
     "label": "NFCI crossed into positive territory",
     "why": "Financial conditions have flipped from looser to tighter than average - "
            "the index is centred on zero by construction."},
    {"key": "sahm_trigger", "sid": "SAHMREALTIME", "mode": "level_above", "value": 0.50,
     "worsen": 0.15, "tone": "critical",
     "label": "Sahm Rule triggered",
     "why": "Labour deterioration has crossed the historical recession threshold."},
    {"key": "curve_inversion", "sid": "T10Y2Y", "mode": "cross_below", "value": 0.0,
     "worsen": 0.25, "tone": "serious",
     "label": "2s10s curve inverted",
     "why": "Check whether expectations or term premium is driving it before acting."},
]

# Equity drawdown is derived from prices rather than a FRED series.
SPX_DRAWDOWN_PCT = -3.0


class Alert(object):
    __slots__ = ("key", "label", "why", "tone", "value", "detail", "as_of")

    def __init__(self, key, label, why, tone, value, detail, as_of):
        self.key, self.label, self.why, self.tone = key, label, why, tone
        self.value, self.detail, self.as_of = value, detail, as_of

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        d["as_of"] = self.as_of.isoformat() if hasattr(self.as_of, "isoformat") else self.as_of
        return d


def _session_change(series):
    """Change versus the previous observation, and that previous value."""
    if series is None or len(series) < 2:
        return None, None
    return series.values[-1] - series.values[-2], series.values[-2]


def _evaluate_trigger(trig, series):
    """Return (fired, current_metric, human detail) for one trigger."""
    if series is None or not len(series):
        return False, None, None

    latest = series.values[-1]
    change, prev = _session_change(series)

    if trig["mode"] == "level_above":
        return latest >= trig["value"], latest, "now %.2f (threshold %.2f)" % (
            latest, trig["value"])

    if change is None:
        return False, None, None

    if trig["mode"] == "change_up":
        return change >= trig["value"], change, "%+.0f in one session, to %.0f" % (
            change, latest)

    if trig["mode"] == "change_abs":
        return abs(change) >= trig["value"], abs(change), "%+.2f in one session, to %.2f" % (
            change, latest)

    if trig["mode"] == "pct_abs":
        if not prev:
            return False, None, None
        pct = (latest - prev) / abs(prev) * 100.0
        return abs(pct) >= trig["value"], abs(pct), "%+.2f%% in one session, to %.2f" % (
            pct, latest)

    if trig["mode"] == "cross_above":
        return (prev < trig["value"] <= latest), latest, "%.2f, up from %.2f" % (latest, prev)

    if trig["mode"] == "cross_below":
        return (prev > trig["value"] >= latest), latest, "%.2f, down from %.2f" % (latest, prev)

    return False, None, None


def _should_suppress(trig, key, metric, state, today):
    """Cooldown: stay quiet unless the condition reset or got materially worse.

    Without this a persistent condition re-fires daily and the alert channel stops
    being read - which defeats the purpose of having one.
    """
    last = state.get(key)
    if not last:
        return False

    try:
        last_fired = date.fromisoformat(last["date"])
    except (KeyError, ValueError):
        return False

    # An alert that has not fired for a fortnight is news again.
    if (today - last_fired).days > 14:
        return False

    last_metric = last.get("metric")
    if last_metric is None or metric is None:
        return True

    # Fire again only if it deteriorated by at least the `worsen` margin.
    return metric < last_metric + trig.get("worsen", 0.0)


def evaluate(series_by_id, market_series, state, today=None, spx_threshold=SPX_DRAWDOWN_PCT):
    """Check every trigger. Returns (alerts, new_state).

    `state` is the persisted cooldown record; pass the previous run's and store the
    returned one.
    """
    today = today or date.today()
    alerts, new_state = [], dict(state or {})

    for trig in TRIGGERS:
        series = series_by_id.get(trig["sid"])
        fired, metric, detail = _evaluate_trigger(trig, series)
        if not fired:
            # Clear the record once the condition resets, so it can fire cleanly next time.
            new_state.pop(trig["key"], None)
            continue
        if _should_suppress(trig, trig["key"], metric, state or {}, today):
            continue

        alerts.append(Alert(trig["key"], trig["label"], trig["why"], trig["tone"],
                            metric, detail, series.latest_date))
        new_state[trig["key"]] = {"date": today.isoformat(), "metric": metric}

    spx = market_series.get("SPY")
    if spx is not None and len(spx) >= 2:
        prev = spx.values[-2]
        if prev:
            pct = (spx.values[-1] - prev) / prev * 100.0
            if pct <= spx_threshold:
                key = "spx_drawdown"
                if not _should_suppress({"worsen": 1.5}, key, abs(pct), state or {}, today):
                    alerts.append(Alert(
                        key, "S&P 500 fell more than %.0f%% in a session" % abs(spx_threshold),
                        "A single-session drop this size is usually a liquidity or "
                        "positioning event, not a fundamental repricing.",
                        "critical", abs(pct), "%+.2f%% to %.2f" % (pct, spx.values[-1]),
                        spx.latest_date))
                    new_state[key] = {"date": today.isoformat(), "metric": abs(pct)}
            else:
                new_state.pop("spx_drawdown", None)

    # A nested threshold fires every band beneath it: VIX at 45 trips both the
    # "above 30" and "above 40" rules. Report only the most severe, or the channel
    # sends two emails describing one condition.
    superseded = set()
    fired_keys = {a.key for a in alerts}
    for trig in TRIGGERS:
        if trig["key"] in fired_keys:
            superseded.update(trig.get("supersedes", []))
    alerts = [a for a in alerts if a.key not in superseded]

    order = {"critical": 0, "serious": 1, "warning": 2}
    alerts.sort(key=lambda a: order.get(a.tone, 3))
    return alerts, new_state


def prune_state(state, today=None, keep_days=60):
    """Drop cooldown records old enough to be irrelevant, so the file stays small."""
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    out = {}
    for key, rec in (state or {}).items():
        try:
            if date.fromisoformat(rec["date"]) >= cutoff:
                out[key] = rec
        except (KeyError, ValueError, TypeError):
            continue
    return out
