"""Classify the five pillar scores into one of the six named regimes (spec 5.2)
and map that regime to capital-flow implications (spec 5.3).

Method: each regime is a point in 5-dimensional pillar space. We score the current
reading against every profile by weighted distance and take the nearest. Distance to
the runner-up becomes the confidence signal - a reading sitting between Late Cycle
and Stagflation should say so rather than assert one of them.

Pillars that reported Unknown are excluded from the distance rather than treated as
zero, so a failed data pull degrades confidence instead of biasing the verdict.
"""
from __future__ import annotations

# Coordinates are on each pillar's own axis:
#   1 growth: up=expanding | 2 inflation: up=hotter | 3 conditions: up=tighter
#   4 credit: up=more stress | 5 breadth: up=healthier
PROFILES = {
    "Goldilocks":  {1:  0.50, 2: -0.40, 3: -0.40, 4: -0.50, 5:  0.50},
    "Reflation":   {1:  0.30, 2: -0.20, 3: -0.55, 4: -0.30, 5:  0.30},
    "Overheating": {1:  0.70, 2:  0.70, 3:  0.50, 4:  0.00, 5:  0.20},
    "Stagflation": {1: -0.40, 2:  0.60, 3:  0.50, 4:  0.40, 5: -0.40},
    "Risk-Off":    {1: -0.70, 2: -0.30, 3:  0.40, 4:  0.80, 5: -0.70},
    "Late Cycle":  {1:  0.20, 2: -0.20, 3:  0.10, 4:  0.10, 5: -0.35},
}

# Some pillars are more diagnostic than others when separating regimes.
PILLAR_WEIGHT = {1: 1.2, 2: 1.2, 3: 1.0, 4: 1.3, 5: 1.0}

CAPITAL_FLOWS = {
    "Goldilocks": {
        "favored": "Growth/tech, EM, high-yield credit, small-caps",
        "disfavored": "Cash, gold, utilities, long-duration Treasuries",
    },
    "Reflation": {
        "favored": "Cyclicals, small-caps, EM, industrials, commodities",
        "disfavored": "Treasuries, defensives, cash",
    },
    "Overheating": {
        "favored": "Energy, materials, value, commodities, TIPS",
        "disfavored": "Long-duration bonds, long-duration growth equities",
    },
    "Stagflation": {
        "favored": "Cash, gold, commodities, real assets, energy",
        "disfavored": "Both stocks and bonds - the regime where diversification fails",
    },
    "Risk-Off": {
        "favored": "Treasuries, gold, defensives (staples, utilities), cash",
        "disfavored": "Equities broadly, high-yield credit, EM, crypto",
    },
    "Late Cycle": {
        "favored": "Quality, dividend growth, healthcare, selective mega-cap tech",
        "disfavored": "Speculative small-caps, leverage, low-quality credit",
    },
}


class Diagnosis(object):
    __slots__ = ("regime", "runner_up", "confidence", "direction", "distances",
                 "known_pillars", "flows", "notes")

    def __init__(self, **kw):
        for slot in self.__slots__:
            setattr(self, slot, kw.get(slot))

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


def _distance(pillars, profile, known):
    total, wsum = 0.0, 0.0
    for num in known:
        w = PILLAR_WEIGHT.get(num, 1.0)
        total += w * (pillars[num].score - profile[num]) ** 2
        wsum += w
    if not wsum:
        return None
    return (total / wsum) ** 0.5


# A new regime must beat the incumbent by this margin in distance before the label
# switches. Without it the verdict flips whenever two profiles are near-equidistant,
# which produced a regime change roughly monthly in replay - noise, not signal.
# Regimes are supposed to persist; the cost of the lag is a late label, and the cost
# of no hysteresis is a label nobody can trust.
SWITCH_MARGIN = 0.06


def classify(pillars, prev_pillars=None, incumbent=None):
    """`pillars` maps pillar number -> Pillar. `prev_pillars` is the same shape from
    a previous run, used to derive whether the regime is improving or deteriorating.
    `incumbent` is the previously reported regime name, held unless clearly beaten."""
    known = [n for n in PROFILES["Goldilocks"] if n in pillars and pillars[n].known]

    if len(known) < 3:
        return Diagnosis(
            regime="Indeterminate", runner_up=None, confidence=0.0,
            direction="Unknown", distances={}, known_pillars=known,
            flows={"favored": "-", "disfavored": "-"},
            notes=["Only %d of 5 pillars had sufficient data; withholding a verdict." % len(known)],
        )

    distances = {}
    for name, profile in PROFILES.items():
        d = _distance(pillars, profile, known)
        if d is not None:
            distances[name] = round(d, 4)

    ranked = sorted(distances.items(), key=lambda kv: kv[1])
    best, best_d = ranked[0]
    runner, runner_d = ranked[1]

    # Hysteresis: keep the incumbent unless the challenger is decisively closer.
    if incumbent and incumbent in distances and incumbent != best:
        if distances[incumbent] - best_d < SWITCH_MARGIN:
            runner, runner_d = best, best_d
            best, best_d = incumbent, distances[incumbent]

    # Confidence blends absolute fit with separation from the runner-up.
    fit = max(0.0, 1.0 - best_d / 1.2)
    separation = min(1.0, (runner_d - best_d) / 0.35) if runner_d > best_d else 0.0
    confidence = round(max(0.0, min(1.0, 0.5 * fit + 0.5 * separation)), 2)

    notes = []
    if len(known) < 5:
        missing = [n for n in (1, 2, 3, 4, 5) if n not in known]
        notes.append("Pillars %s lacked data and were excluded from the match."
                     % ", ".join(str(m) for m in missing))
    if confidence < 0.4:
        notes.append("Low confidence: the reading sits between %s and %s." % (best, runner))

    return Diagnosis(
        regime=best, runner_up=runner, confidence=confidence,
        direction=_direction(pillars, prev_pillars, known),
        distances=distances, known_pillars=known,
        flows=CAPITAL_FLOWS.get(best, {"favored": "-", "disfavored": "-"}),
        notes=notes,
    )


def _direction(pillars, prev_pillars, known):
    """Direction of change matters more than level (spec 1). Uses each pillar's own
    momentum when there is no prior run to compare against."""
    from .pillar_scores import _AXIS_RISK_SIGN

    delta = 0.0
    for num in known:
        sign = _AXIS_RISK_SIGN.get(num, 1)
        if prev_pillars and num in prev_pillars and prev_pillars[num].get("known"):
            change = pillars[num].score - prev_pillars[num]["score"]
        else:
            live = [r for r in pillars[num].readings if r.momentum is not None]
            change = (sum(r.momentum * r.weight for r in live) /
                      sum(r.weight for r in live)) if live else 0.0
        # A rise on a risk-negative axis is deterioration.
        delta += -sign * change

    delta /= max(1, len(known))
    if delta > 0.06:
        return "Improving"
    if delta < -0.06:
        return "Deteriorating"
    return "Stable"
