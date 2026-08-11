"""Replay the scoring engine across historical data (Phase 2).

Every run already pulls ~3 years of history per series in order to compute
percentiles. That same history can be scored at every past date, which yields a
regime timeline immediately rather than after months of accumulating snapshots.

Two uses:
  1. CALIBRATION - see how often each regime and pillar state actually occurs. If
     90% of days classify as one regime, the bands in thresholds.json are wrong.
  2. The Phase 4 dashboard's historical views, which would otherwise chart a single
     point until enough live snapshots existed.

The replay calls the SAME build_reading / score_all / classify path as the live
brief. It cannot drift from production scoring, because it is production scoring
with `today` moved backwards.

Point-in-time caveat: FRED revises data, and this replays the CURRENT vintage of
each series rather than what was actually published on the day. Revisions to
payrolls and GDP are routinely large, so treat the timeline as "how today's data
characterises the past", not as what the brief would have said at the time. FRED's
ALFRED archive holds true vintages if that distinction ever matters.
"""
from __future__ import annotations

from datetime import timedelta

from .indicators import build_reading
from .market import breadth_reading, index_trend_reading
from .pillar_scores import score_all
from .regime import classify
from .timeseries import Series


def _slice_to(series, cutoff):
    """The series as it appears at `cutoff`, dropping later observations."""
    keep = 0
    for d in series.dates:
        if d > cutoff:
            break
        keep += 1
    if keep == len(series.values):
        return series
    if keep == 0:
        return None
    return Series(series.sid, series.dates[:keep], series.values[:keep])


def replay(raw_series, specs, cfg, market_series=None, step_days=7, max_points=200):
    """Score every `step_days` back through the available history.

    Returns records ordered oldest-first. Each is a plain dict so it can be written
    straight to JSON for the dashboard.
    """
    market_series = market_series or {}

    spans = [s.dates[-1] for s in raw_series.values() if len(s)]
    starts = [s.dates[0] for s in raw_series.values() if len(s)]
    if not spans:
        return []

    end = max(spans)
    # Need a full trailing window before the first scoreable date, otherwise the
    # earliest points are scored against a handful of observations.
    warmup = timedelta(days=int(365.25 * cfg["history_years"]) + 60)
    start = min(starts) + warmup
    if start >= end:
        start = min(starts) + timedelta(days=180)

    dates = []
    cur = end
    while cur >= start and len(dates) < max_points:
        dates.append(cur)
        cur -= timedelta(days=step_days)
    dates.reverse()

    records, prev_pillars, incumbent = [], None, None
    for asof in dates:
        readings = []
        for spec in specs:
            series = raw_series.get(spec["id"])
            if series is None:
                continue
            sliced = _slice_to(series, asof)
            if sliced is None:
                continue
            reading = build_reading(spec, sliced, cfg, asof)
            if reading is not None:
                readings.append(reading)

        sliced_market = {}
        for sym, series in market_series.items():
            s = _slice_to(series, asof)
            if s is not None and len(s) > 21:
                sliced_market[sym] = s
        if sliced_market:
            breadth, _ = breadth_reading(sliced_market, cfg, asof)
            if breadth:
                readings.append(breadth)
            trend = index_trend_reading(sliced_market, cfg, asof)
            if trend:
                readings.append(trend)

        if not readings:
            continue

        pillars = score_all(readings, cfg, specs)
        diagnosis = classify(pillars, prev_pillars, incumbent)
        incumbent = diagnosis.regime

        records.append({
            "date": asof.isoformat(),
            "regime": diagnosis.regime,
            "direction": diagnosis.direction,
            "confidence": diagnosis.confidence,
            "runner_up": diagnosis.runner_up,
            "pillars": {str(n): {"score": round(p.score, 4), "state": p.state,
                                 "known": p.known, "tone": p.risk_tone}
                        for n, p in pillars.items()},
            "readings": {r.sid: round(r.value, 4) for r in readings
                         if r.value is not None},
        })
        prev_pillars = {n: {"score": p.score, "known": p.known}
                        for n, p in pillars.items()}

    return records


def regime_episodes(records):
    """Collapse consecutive same-regime records into episodes, for the timeline."""
    episodes = []
    for rec in records:
        if episodes and episodes[-1]["regime"] == rec["regime"]:
            episodes[-1]["end"] = rec["date"]
            episodes[-1]["points"] += 1
        else:
            episodes.append({"regime": rec["regime"], "start": rec["date"],
                             "end": rec["date"], "points": 1})
    return episodes


def calibration(records, cfg):
    """Distribution summary used to sanity-check the scoring bands.

    A healthy configuration visits several regimes and spreads pillar states out.
    Near-total concentration in one bucket means the bands need widening or the
    profiles need moving - the whole point of Phase 2.
    """
    if not records:
        return {}

    total = len(records)
    regime_counts, direction_counts = {}, {}
    pillar_states, pillar_scores = {}, {}

    for rec in records:
        regime_counts[rec["regime"]] = regime_counts.get(rec["regime"], 0) + 1
        direction_counts[rec["direction"]] = direction_counts.get(rec["direction"], 0) + 1
        for num, p in rec["pillars"].items():
            pillar_states.setdefault(num, {})
            pillar_states[num][p["state"]] = pillar_states[num].get(p["state"], 0) + 1
            pillar_scores.setdefault(num, []).append(p["score"])

    def _spread(values):
        if not values:
            return {}
        ordered = sorted(values)
        n = len(ordered)
        return {
            "min": round(ordered[0], 3),
            "p25": round(ordered[n // 4], 3),
            "median": round(ordered[n // 2], 3),
            "p75": round(ordered[(3 * n) // 4], 3),
            "max": round(ordered[-1], 3),
        }

    concentration = max(regime_counts.values()) / total
    warnings = []
    if concentration > 0.75:
        warnings.append(
            "%.0f%% of the window classifies as a single regime (%s). Widen the "
            "pillar_state_bands or revisit the regime profiles."
            % (concentration * 100,
               max(regime_counts, key=lambda k: regime_counts[k])))
    if len(regime_counts) < 3:
        warnings.append("Only %d distinct regimes appear across %d points; the "
                        "classifier may be under-discriminating."
                        % (len(regime_counts), total))
    for num, scores in pillar_scores.items():
        spread = _spread(scores)
        if spread and abs(spread["max"] - spread["min"]) < 0.25:
            warnings.append("Pillar %s barely moves (range %.2f); its indicators may "
                            "be cancelling out." % (num, spread["max"] - spread["min"]))

    return {
        "points": total,
        "span": {"from": records[0]["date"], "to": records[-1]["date"]},
        "regimes": {k: round(v / total, 3) for k, v in
                    sorted(regime_counts.items(), key=lambda kv: -kv[1])},
        "directions": {k: round(v / total, 3) for k, v in direction_counts.items()},
        "pillar_states": pillar_states,
        "pillar_score_spread": {n: _spread(v) for n, v in pillar_scores.items()},
        "episodes": len(regime_episodes(records)),
        "warnings": warnings,
    }
