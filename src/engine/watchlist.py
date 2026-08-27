"""What to watch next, and what would change the verdict.

Two related questions the dashboard could not previously answer:

  WHAT SHOULD I WATCH?  Not a fixed list. Which indicator matters most depends on
  what is currently in play: when credit is calm, spreads are background noise;
  when the Sahm Rule is creeping toward its trigger, it is the only thing that
  matters. Priority is scored from the indicator's weight, how close it sits to a
  structural threshold, and how much it is currently moving.

  WHAT WOULD CHANGE YOUR MIND?  The honest version of a forecast. Rather than
  guessing where prices go, state the conditions that would flip the verdict - a
  threshold about to be crossed, a pillar close to changing state. Falsifiable,
  and it tells you what to look for rather than what to believe.
"""
from __future__ import annotations

from datetime import timedelta

# Roughly how often each release cadence repeats, for estimating the next update.
_CADENCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91}


def next_release(reading, raw_series=None):
    """Estimate when this indicator updates next, from its own release history.

    Derived rather than hardcoded: a calendar of publication dates would go stale
    and be wrong in ways nobody notices. The series' own spacing is self-maintaining.
    """
    if reading is None or reading.as_of is None:
        return None
    gap = _CADENCE_DAYS.get(reading.freq, 30)
    if raw_series is not None and len(raw_series) > 6:
        spacings = [(raw_series.dates[i + 1] - raw_series.dates[i]).days
                    for i in range(len(raw_series.dates) - 6, len(raw_series.dates) - 1)]
        spacings = [s for s in spacings if s > 0]
        if spacings:
            gap = sorted(spacings)[len(spacings) // 2]
    return reading.as_of + timedelta(days=gap)


def _threshold_proximity(reading, spec):
    """0..1 - how close this reading sits to its structural threshold."""
    anchor = spec.get("anchor")
    if anchor is None or reading.value is None:
        return 0.0
    signal = spec.get("anchor_signal", "above")
    fired = reading.value >= anchor if signal == "above" else reading.value <= anchor
    if fired:
        return 1.0
    # Scale the gap against the series' own recent range, so "close" means close
    # relative to how much this indicator actually moves.
    span = abs(reading.chg_1m or 0) * 6 or abs(anchor) or 1.0
    gap = abs(reading.value - anchor)
    return max(0.0, min(1.0, 1.0 - gap / span)) if span else 0.0


def top_indicators(readings, specs, raw=None, limit=5):
    """The handful of numbers that matter most right now, most urgent first."""
    spec_by_id = {s["id"]: s for s in specs}
    scored = []

    for r in readings:
        spec = spec_by_id.get(r.sid)
        if spec is None or r.stale:
            continue
        weight = spec.get("weight", 1.0)
        if weight <= 0:
            continue

        proximity = _threshold_proximity(r, spec)
        movement = abs(r.drift or 0.0)
        extremity = 0.0
        if r.percentile is not None:
            extremity = max(0.0, (abs(r.percentile - 50.0) - 25.0) / 25.0)

        # A threshold about to be crossed outranks everything; after that, weight
        # decides, then how much the number is actually moving.
        priority = (proximity * 3.0) + (weight * 0.6) + (movement * 1.2) + (extremity * 0.8)

        # A crossing by a hair is not a crossing worth announcing. CFNAI at -0.02
        # against a zero threshold is sitting on the line, and calling that "crossed"
        # manufactures a signal out of rounding.
        anchor = spec.get("anchor")
        marginal = False
        if anchor is not None and r.value is not None:
            # Scale against how much this series normally moves in one period, taken
            # from the series itself. Using last month's change instead made the
            # window vanishingly small for slow-moving monthly data, so a reading
            # two hundredths past zero was announced as a crossing.
            series = (raw or {}).get(r.sid)
            sigma = series.change_sigma() if series is not None else None
            typical = sigma or abs(r.chg_1m or 0) or abs(anchor) * 0.05 or 0.05
            marginal = abs(r.value - anchor) < typical

        reason = None
        if proximity >= 0.99 and marginal:
            reason = "is sitting right on its threshold"
        elif proximity >= 0.99:
            reason = "has crossed its threshold"
        elif proximity >= 0.5:
            reason = "is closing on the level that would signal"
        elif movement >= 0.5:
            reason = "is moving faster than usual"
        elif extremity >= 0.6:
            reason = "sits at an extreme of its own range"
        else:
            reason = "is one of the heaviest inputs to the verdict"

        scored.append((priority, r, spec, reason))

    scored.sort(key=lambda t: -t[0])

    out = []
    for _, r, spec, reason in scored[:limit]:
        out.append({
            "sid": r.sid,
            "name": r.name,
            "value": r,
            "reason": reason,
            "pillar": r.pillar,
            "next_release": next_release(r, (raw or {}).get(r.sid)),
        })
    return out


def what_would_change(pillars, readings, specs, diagnosis, cfg):
    """Concrete, checkable conditions that would move the verdict.

    Deliberately not a forecast. Each entry names something observable and says
    what it would mean - so you can go and look, rather than take a view on trust.
    """
    spec_by_id = {s["id"]: s for s in specs}
    by_sid = {r.sid: r for r in readings}
    bands = cfg["pillar_state_bands"]
    out = []

    # 1. Thresholds within reach.
    for sid, r in by_sid.items():
        spec = spec_by_id.get(sid)
        if spec is None or spec.get("anchor") is None or r.value is None or r.stale:
            continue
        anchor = spec["anchor"]
        signal = spec.get("anchor_signal", "above")
        fired = r.value >= anchor if signal == "above" else r.value <= anchor
        if fired:
            continue
        if _threshold_proximity(r, spec) >= 0.45:
            out.append({
                "kind": "threshold",
                "what": "%s crossing %s" % (r.name, ("above" if signal == "above" else "below")),
                "detail": "Now %.2f, against a %s threshold of %s. %s"
                          % (r.value, "trigger" if signal == "above" else "signal",
                             anchor, spec.get("anchor_note", "")),
                "weight": spec.get("weight", 1.0),
            })

    # 2. Pillars near a state boundary.
    for num, p in sorted(pillars.items()):
        if not p.known:
            continue
        for label, edge in (("mild_positive", bands["mild_positive"]),
                            ("mild_negative", bands["mild_negative"]),
                            ("strong_positive", bands["strong_positive"]),
                            ("strong_negative", bands["strong_negative"])):
            distance = abs(p.score - edge)
            if distance <= 0.06:
                direction = "improve" if p.score < edge else "weaken"
                out.append({
                    "kind": "pillar",
                    "what": "%s changing state" % p.name,
                    "detail": "Scoring %+.2f, within %.2f of the boundary at %+.2f. "
                              "A small further move would %s the reading."
                              % (p.score, distance, edge, direction),
                    "weight": 2.0,
                })
                break

    # 3. How close the regime itself is to being reclassified.
    if diagnosis.runner_up and diagnosis.distances:
        best = diagnosis.distances.get(diagnosis.regime)
        runner = diagnosis.distances.get(diagnosis.runner_up)
        if best is not None and runner is not None and (runner - best) < 0.20:
            out.append({
                "kind": "regime",
                "what": "The verdict flipping to %s" % diagnosis.runner_up,
                "detail": "Today's reading sits almost as close to %s as to %s. "
                          "It would not take much to tip it."
                          % (diagnosis.runner_up, diagnosis.regime),
                "weight": 3.0,
            })

    out.sort(key=lambda d: -d["weight"])
    return out[:5]
