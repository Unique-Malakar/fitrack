"""Roll scored indicators up into per-pillar states.

Each pillar is a weighted mean of its readings along that pillar's axis. Coverage
is enforced: a pillar built from too few live indicators reports Unknown instead of
producing a confident-looking number from a thin sample.
"""
from __future__ import annotations

PILLAR_NAMES = {
    1: "Growth",
    2: "Inflation",
    3: "Policy & Conditions",
    4: "Liquidity & Credit",
    5: "Earnings & Breadth",
    6: "Structural Themes",
}

# Which end of each pillar's axis is bad for risk assets. Used for the badge colour
# and for the regime logic, kept separate from the axis labels themselves.
_AXIS_RISK_SIGN = {1: -1, 2: 1, 3: 1, 4: 1, 5: -1}


class Pillar(object):
    __slots__ = ("num", "name", "score", "state", "readings", "coverage", "known", "axis")

    def __init__(self, num, name, score, state, readings, coverage, known, axis):
        self.num, self.name, self.score, self.state = num, name, score, state
        self.readings, self.coverage, self.known, self.axis = readings, coverage, known, axis

    @property
    def risk_tone(self):
        """'good' | 'watch' | 'bad' - how this pillar's state reads for risk assets."""
        if not self.known:
            return "unknown"
        signed = self.score * _AXIS_RISK_SIGN.get(self.num, 1)
        if signed <= -0.13:
            return "good"
        if signed >= 0.13:
            return "bad"
        return "watch"

    def as_dict(self):
        return {
            "pillar": self.num, "name": self.name, "score": self.score,
            "state": self.state, "coverage": self.coverage, "known": self.known,
            "tone": self.risk_tone,
            "readings": [r.as_dict() for r in self.readings],
        }


def _state_label(num, score, cfg):
    bands = cfg["pillar_state_bands"]
    labels = cfg["pillar_states"].get(str(num), {}).get("labels")
    if not labels:
        return "n/a"
    if score <= bands["strong_negative"]:
        return labels[0]
    if score <= bands["mild_negative"]:
        return labels[1]
    if score < bands["mild_positive"]:
        return labels[2]
    if score < bands["strong_positive"]:
        return labels[3]
    return labels[4]


def score_pillar(num, readings, cfg, expected_weight=None):
    """Weighted mean of readings. `expected_weight` is the total weight configured
    for this pillar, so coverage reflects what is missing, not just what arrived."""
    live = [r for r in readings if r is not None and not r.stale]
    total_w = sum(r.weight for r in live)
    expected = expected_weight if expected_weight else total_w

    coverage = (total_w / expected) if expected else 0.0
    axis = cfg["pillar_states"].get(str(num), {}).get("axis", "")

    if not live or coverage < cfg["min_coverage"]["fraction"]:
        return Pillar(num, PILLAR_NAMES.get(num, str(num)), 0.0, "Unknown",
                      sorted(readings, key=_rank), coverage, False, axis)

    score = sum(r.score * r.weight for r in live) / total_w
    return Pillar(num, PILLAR_NAMES.get(num, str(num)), score,
                  _state_label(num, score, cfg), sorted(live, key=_rank),
                  coverage, True, axis)


def _rank(reading):
    """Most decisive readings first: weight, then absolute score."""
    return (-(reading.weight or 0) * (0.5 + abs(reading.score or 0)),)


def score_all(readings, cfg, specs):
    expected = {}
    for spec in specs:
        p = spec["pillar"]
        expected[p] = expected.get(p, 0.0) + spec.get("weight", 1.0)

    by_pillar = {}
    for r in readings:
        if r is None:
            continue
        by_pillar.setdefault(r.pillar, []).append(r)

    out = {}
    for num in (1, 2, 3, 4, 5):
        out[num] = score_pillar(num, by_pillar.get(num, []), cfg, expected.get(num))
    return out
