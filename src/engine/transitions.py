"""Empirical regime transition rates, computed from this system's own history.

The honest version of "what happens next". Rather than guessing, this counts what
actually followed each regime across the replayed history and reports the base
rates. It is descriptive statistics on a small sample, not a forecast, and the
sample size is reported alongside every number so it can be discounted properly.

Two things keep it from becoming astrology:

  * Only transitions ACTUALLY OBSERVED are counted. No smoothing, no priors, no
    filling in regimes that never occurred.
  * The sample is tiny - roughly twenty transitions across seven years. That is
    reported prominently, because a 40% base rate drawn from five observations
    deserves very little weight.
"""
from __future__ import annotations


def _episodes(records):
    """Collapse consecutive same-regime readings into episodes with durations."""
    out = []
    for rec in records:
        regime = rec.get("regime")
        if not regime or regime == "Indeterminate":
            continue
        if out and out[-1]["regime"] == regime:
            out[-1]["points"] += 1
            out[-1]["end"] = rec["date"]
        else:
            out.append({"regime": regime, "start": rec["date"],
                        "end": rec["date"], "points": 1})
    return out


def transition_table(records):
    """From each regime, what followed it and how often."""
    eps = _episodes(records)
    counts, durations = {}, {}
    for i, ep in enumerate(eps):
        durations.setdefault(ep["regime"], []).append(ep["points"])
        if i + 1 < len(eps):
            nxt = eps[i + 1]["regime"]
            counts.setdefault(ep["regime"], {})
            counts[ep["regime"]][nxt] = counts[ep["regime"]].get(nxt, 0) + 1
    return counts, durations, eps


def outlook(records, current_regime, step_days=7):
    """Base rates for what has historically followed the current regime.

    Returns None when the sample is too thin to say anything, rather than
    reporting a percentage derived from one or two observations.
    """
    counts, durations, eps = transition_table(records)
    if not eps:
        return None

    following = counts.get(current_regime, {})
    total = sum(following.values())

    spells = durations.get(current_regime, [])
    typical_weeks = None
    if spells:
        ordered = sorted(spells)
        typical_weeks = ordered[len(ordered) // 2] * step_days / 7.0

    current_run = 0
    for ep in reversed(eps):
        if ep["regime"] == current_regime:
            current_run = ep["points"]
        break

    rows = []
    for regime, n in sorted(following.items(), key=lambda kv: -kv[1]):
        rows.append({"regime": regime, "count": n, "share": n / total if total else 0.0})

    return {
        "current": current_regime,
        "transitions_observed": total,
        "episodes_of_current": len(spells),
        "typical_weeks": typical_weeks,
        "current_run_weeks": current_run * step_days / 7.0,
        "rows": rows,
        "total_episodes": len(eps),
        # Anything under five observed transitions is an anecdote, not a rate.
        "reliable": total >= 5,
        # A single destination taking nearly every transition usually means the two
        # regimes sit adjacent in pillar space and the classifier is crossing a
        # boundary back and forth - proximity in the model, not an economic law.
        "dominated": bool(rows) and rows[0]["share"] >= 0.8 and total >= 3,
    }
