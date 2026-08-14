"""Sector sensitivity matrix (spec 2.3).

The spec rejected the textbook four-stage rotation clock in favour of scoring each
sector against the factors that actually drive it, then mapping today's readings
onto those sensitivities. This is that.

WHAT THIS IS: a conditional statement. "Utilities behave like bonds, so falling
rates are a tailwind for them." The sensitivities are structural facts about what
each sector owns and owes - a utility carries heavy debt and sells a stable
product; a bank earns a spread between borrowing and lending costs.

WHAT THIS IS NOT: a forecast. Nothing here says a sector will rise. Sensitivities
describe exposure, not outcome, and they are averages that break in any individual
month. Positioning is not prediction.

The genuinely useful output is the GAP: where conditions point one way and prices
have not yet moved, or where the market has already travelled further than
conditions justify. Agreement is unremarkable; disagreement is information.
"""
from __future__ import annotations

# Sensitivity of each sector to each factor, on the factor's OWN axis.
#   growth     pillar 1, up = economy expanding
#   inflation  pillar 2, up = prices rising faster
#   tightness  pillar 3, up = money getting tighter
#   stress     pillar 4, up = credit stress rising
#   dollar     up = stronger dollar
# Positive means the sector benefits when that factor rises.
SENSITIVITY = {
    "XLK": {"growth": 0.55, "inflation": -0.25, "tightness": -0.80, "stress": -0.55, "dollar": -0.35,
            "why": "long-duration earnings and heavy foreign revenue, so it is unusually rate- and dollar-sensitive"},
    "XLC": {"growth": 0.45, "inflation": -0.20, "tightness": -0.55, "stress": -0.45, "dollar": -0.25,
            "why": "advertising-led, so it tracks the economy, with growth-stock rate sensitivity"},
    "XLY": {"growth": 0.80, "inflation": -0.45, "tightness": -0.60, "stress": -0.60, "dollar": -0.10,
            "why": "discretionary spending is the first thing households cut, and much of it is financed"},
    "XLI": {"growth": 0.80, "inflation": 0.10, "tightness": -0.35, "stress": -0.45, "dollar": -0.40,
            "why": "capital goods demand follows the business cycle closely, and exports suffer on a strong dollar"},
    "XLB": {"growth": 0.70, "inflation": 0.55, "tightness": -0.30, "stress": -0.40, "dollar": -0.55,
            "why": "commodities are priced in dollars and demand is industrial, so it is doubly cyclical"},
    "XLE": {"growth": 0.40, "inflation": 0.85, "tightness": -0.10, "stress": -0.25, "dollar": -0.45,
            "why": "revenue is essentially the oil price, which is itself a large part of inflation"},
    "XLF": {"growth": 0.55, "inflation": 0.05, "tightness": 0.30, "stress": -0.85, "dollar": 0.05,
            "why": "banks earn a spread that widens with rates, but credit losses hurt them before anyone else"},
    "XLV": {"growth": -0.25, "inflation": -0.10, "tightness": -0.25, "stress": 0.35, "dollar": 0.10,
            "why": "demand for healthcare barely changes with the economy, which makes it defensive"},
    "XLP": {"growth": -0.50, "inflation": -0.30, "tightness": -0.20, "stress": 0.55, "dollar": 0.10,
            "why": "people buy food and soap in any economy, so it holds up when other things do not"},
    "XLU": {"growth": -0.45, "inflation": -0.20, "tightness": -0.85, "stress": 0.45, "dollar": 0.05,
            "why": "heavily indebted with regulated, stable revenue, so it trades much like a bond"},
    "XLRE": {"growth": 0.30, "inflation": 0.15, "tightness": -0.90, "stress": -0.50, "dollar": 0.00,
             "why": "property is bought with borrowed money, making financing costs the dominant driver"},
}

FACTOR_LABEL = {
    "growth": ("a growing economy", "a slowing economy"),
    "inflation": ("rising inflation", "cooling inflation"),
    "tightness": ("tighter money", "easier money"),
    "stress": ("credit stress", "calm credit"),
    "dollar": ("a stronger dollar", "a weaker dollar"),
}


def _factor_readings(pillars, dollar_drift):
    """Today's conditions, expressed on each factor's own axis."""
    out = {}
    for key, num in (("growth", 1), ("inflation", 2), ("tightness", 3), ("stress", 4)):
        p = pillars.get(num)
        out[key] = p.score if (p is not None and p.known) else None
    out["dollar"] = dollar_drift
    return out


def score_sectors(pillars, specs, dollar_drift=None, market_rs=None):
    """Rank sectors by how well today's conditions suit them.

    Returns rows carrying the tailwind score, the two factors driving it, and -
    where available - what the market has actually done, so the two can be compared.
    """
    factors = _factor_readings(pillars, dollar_drift)
    live = {k: v for k, v in factors.items() if v is not None}
    if len(live) < 2:
        return [], factors

    names = {s["symbol"]: s["name"] for s in specs}
    rows = []
    for symbol, sens in SENSITIVITY.items():
        contributions = []
        total = weight = 0.0
        for key, value in live.items():
            s = sens.get(key, 0.0)
            if not s:
                continue
            total += s * value
            weight += abs(s)
            contributions.append((abs(s * value), key, s * value))

        if not weight:
            continue
        score = total / weight

        # Name the two factors doing the most work, so the number is explainable.
        contributions.sort(reverse=True)
        drivers = []
        for _, key, signed in contributions[:2]:
            if abs(signed) < 0.02:
                continue
            helping = signed > 0
            up, down = FACTOR_LABEL[key]
            condition = up if live[key] > 0 else down
            drivers.append("%s %s" % ("helped by" if helping else "hurt by", condition))

        rows.append({
            "symbol": symbol,
            "name": names.get(symbol, symbol),
            "score": max(-1.0, min(1.0, score)),
            "drivers": drivers,
            "why": sens["why"],
            "actual": (market_rs or {}).get(symbol),
        })

    rows.sort(key=lambda r: -r["score"])
    return rows, factors


def divergences(rows, threshold=0.25, move_threshold=1.0):
    """Where conditions and prices disagree.

    Agreement tells you nothing you did not already know. The interesting cases are
    a sector well suited to current conditions that the market has ignored, and one
    the market has bid up despite conditions working against it.
    """
    out = []
    for r in rows:
        actual = r.get("actual")
        if actual is None:
            continue
        if r["score"] >= threshold and actual <= -move_threshold:
            out.append((r, "conditions favour it, but it has lagged the market"))
        elif r["score"] <= -threshold and actual >= move_threshold:
            out.append((r, "the market has bid it up despite conditions working against it"))
    return out
