"""Generate SYNTHETIC fixtures so the pipeline can be exercised without API keys.

    python3 tools/make_fixtures.py

THESE NUMBERS ARE FABRICATED. They are shaped to be structurally plausible - right
units, right frequency, right rough magnitude - so that formatting, scoring and the
divergence detectors can be verified. They are NOT market data and must never be
read as such. Every fixture carries a "_synthetic" marker, and the brief built from
them is a layout preview only.

Replace with real recordings once keys exist:  python3 -m src.main --record

The scripted scenario is deliberately eventful (credit widening, breadth narrowing,
VIX rising into a stable-growth backdrop) so that several detectors fire and the
email's full structure is visible.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")

# id -> (end_value, total_drift_over_window, noise_amplitude[, shape])
# end_value is the value the series lands on today, in RAW FRED units.
# `shape` controls WHEN the drift happens: 1.0 spreads it evenly across the window,
# higher values back-load it so most of the move lands in recent weeks. Without this
# the series have no recent trend to detect, and every momentum read is correctly
# zero - a uniform three-year drift is not an event.
PROFILE = {
    "DGS2":          (3.62, -0.35, 0.06),
    "DGS10":         (4.31, 0.28, 0.06),
    "DGS30":         (4.92, 0.42, 0.06, 2.6),
    "T10Y2Y":        (0.69, 0.63, 0.05),
    "T10Y3M":        (0.34, 0.72, 0.06),
    "THREEFYTP10":   (0.71, 0.55, 0.04, 2.8),
    "DFF":           (3.58, -0.40, 0.01, 3.0),
    "DFII10":        (1.94, 0.18, 0.05),
    "NFCI":          (-0.41, 0.14, 0.015, 3.2),
    "ANFCI":         (-0.22, 0.16, 0.02, 3.0),
    "STLFSI4":       (-0.28, 0.19, 0.03, 3.0),
    "PAYEMS":        (162400.0, 6300.0, 45.0),
    "UNRATE":        (4.4, 0.3, 0.05, 2.6),
    "ICSA":          (238000.0, 22000.0, 9000.0, 3.0),
    "CCSA":          (1962000.0, 130000.0, 22000.0, 2.6),
    "SAHMREALTIME":  (0.41, 0.24, 0.02, 3.0),
    "RECPROUSM156N": (7.4, 3.1, 0.9, 2.2),
    "RSAFS":         (742000.0, 99000.0, 4200.0),
    "UMCSENT":       (61.2, -4.0, 1.9, 2.4),
    "HOUST":         (1318.0, -60.0, 42.0),
    "PERMIT":        (1361.0, -48.0, 38.0),
    "MORTGAGE30US":  (6.54, 0.12, 0.05),
    "CPIAUCSL":      (326.8, 31.0, 0.25),
    "CPILFESL":      (331.4, 36.3, 0.22),
    "PCEPI":         (128.9, 11.3, 0.11),
    "PCEPILFE":      (129.6, 13.3, 0.10),
    "T5YIE":         (2.41, 0.13, 0.03),
    "T10YIE":        (2.35, 0.09, 0.02),
    "CES0500000003": (36.62, 5.50, 0.03),
    "DCOILWTICO":    (71.40, -4.10, 1.30, 2.0),
    "PCOPPUSDM":     (9420.0, 610.0, 190.0),
    "BAMLC0A0CM":    (1.02, 0.19, 0.020, 3.4),
    "BAMLH0A0HYM2":  (3.78, 0.72, 0.055, 3.6),
    "VIXCLS":        (21.40, 6.90, 1.30, 3.6),
    "WM2NS":         (22180.0, 3370.0, 24.0),
    "WALCL":         (6512000.0, -290000.0, 9000.0, 1.6),
    "RRPONTSYD":     (128.4, 44.0, 22.0, 2.8),
    "DRTSCILM":      (8.6, 14.0, 1.4, 2.4),
    "SP500":         (6485.0, 210.0, 48.0),
    "DTWEXBGS":      (121.4, 1.9, 0.35),
    "DEXJPUS":       (152.40, 6.80, 0.55, 2.2),
    # Debt-chain series. End values track the real August 2026 readings scraped
    # from FRED so the tracker's thresholds are exercised at plausible magnitudes.
    "GFDEBTN":       (39065421.0, 4200000.0, 42000.0),
    "GFDEGDQ188S":   (123.4, 8.1, 0.35),
    "A091RC1Q027SBEA": (1247.0, 330.0, 11.0, 1.6),
    "FGRECPT":       (5872.5, 690.0, 42.0),
    "FDHBFIN":       (9270.9, 640.0, 55.0),
    "CIVPART":       (61.4, -1.1, 0.09, 1.8),
    "U6RATE":        (7.9, 0.9, 0.09, 2.0),
    "EMRATIO":       (59.1, -0.9, 0.09, 1.8),
}

PERIODS_PER_YEAR = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4}
STEP_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91}

# Alpha Vantage: symbol -> (last_close, total_pct_move_over_100d, daily_vol_pct, shape)
# shape > 1 back-loads the move into the last few weeks, which is what makes the
# 1m relative-strength readings differ from the 3m ones.
AV_PROFILE = {
    "SPY":  (648.20, 2.6, 0.55, 2.6),
    "RSP":  (188.40, -1.4, 0.48, 2.6),   # lags SPY late -> narrow-rally detector fires
    "XLK":  (272.10, 6.1, 0.80, 2.4),
    "XLE":  (91.60, -3.8, 0.85, 1.8),
    "XLV":  (146.30, -1.9, 0.55, 1.4),
    "XLF":  (53.80, 1.2, 0.60, 2.2),
    "XLI":  (147.90, 0.4, 0.55, 1.6),
    "XLP":  (82.10, 2.2, 0.40, 3.0),     # defensives bid late
    "XLY":  (232.40, -2.1, 0.72, 2.4),
    "XLU":  (89.70, 4.4, 0.52, 3.0),     # defensives bid late
    "XLRE": (43.20, -2.6, 0.65, 2.0),
    "XLC":  (112.80, 3.7, 0.70, 2.4),
    "XLB":  (89.30, -1.7, 0.62, 1.8),
    "GLD":  (318.60, 7.4, 0.65, 2.8),    # rising with real yields -> decoupling detector
}


def business_days_back(n, step_days):
    """Dates ending today, spaced by step_days, skipping weekends for daily series."""
    out, cur = [], date.today()
    while len(out) < n:
        if step_days > 1 or cur.weekday() < 5:
            out.append(cur)
        cur -= timedelta(days=step_days)
    return list(reversed(out))


def make_path(n, end_value, drift, noise, rng, floor=None, shape=1.0):
    """Path landing exactly on end_value, with `drift` applied along a t**shape curve.

    The stochastic part is a BROWNIAN BRIDGE, not white noise around the trend. This
    matters: independent per-observation noise mean-reverts, so an n-period change is
    dominated by two endpoint draws and every trend statistic washes out. Real yields,
    spreads and prices are closer to random walks, where innovations persist and a
    sustained move actually shows up in the change distribution. Using white noise here
    produced fixtures on which no trend detector could ever fire - a property of the
    generator, not of the engine.

    The bridge pins both endpoints exactly while preserving that persistence.
    `noise` is the typical single-period change, damped so the bridge's
    mid-window excursion stays within a plausible range for the series.
    """
    start = end_value - drift
    step = 0.40 * noise

    walk, acc = [], 0.0
    for _ in range(n):
        acc += rng.gauss(0, step)
        walk.append(acc)

    vals = []
    for i in range(n):
        t = i / max(1, n - 1)
        base = start + drift * (t ** shape)
        bridged = walk[i] - walk[-1] * t  # pin walk[0] = walk[-1] = 0
        v = base + bridged
        if floor is not None:
            v = max(floor, v)
        vals.append(v)
    vals[-1] = end_value
    return vals


def build_fred(specs, years=3):
    rng = random.Random(20260810)
    written = []
    for spec in specs:
        sid = spec["id"]
        if sid not in PROFILE:
            continue
        freq = spec.get("freq", "monthly")
        n = int(PERIODS_PER_YEAR[freq] * (years + 1.2))
        n = max(n, 30)
        dates = business_days_back(n, STEP_DAYS[freq])

        profile = PROFILE[sid]
        end_value, drift, noise = profile[0], profile[1], profile[2]
        shape = profile[3] if len(profile) > 3 else 1.0
        floor = 0.0 if sid in ("VIXCLS", "ICSA", "CCSA", "RRPONTSYD", "UNRATE") else None
        values = make_path(n, end_value, drift, noise, rng, floor, shape)

        decimals = 0 if abs(end_value) > 5000 else 4
        payload = {
            "_synthetic": "FABRICATED DATA - generated by tools/make_fixtures.py, not real FRED data",
            "realtime_start": dates[0].isoformat(),
            "realtime_end": dates[-1].isoformat(),
            "observation_start": dates[0].isoformat(),
            "observation_end": dates[-1].isoformat(),
            "units": "lin",
            "count": len(dates),
            "observations": [
                {"realtime_start": d.isoformat(), "realtime_end": d.isoformat(),
                 "date": d.isoformat(), "value": ("%.*f" % (decimals, v))}
                for d, v in zip(dates, values)
            ],
        }
        # A couple of genuine gaps, so the "." handling is actually exercised.
        if freq == "daily" and len(payload["observations"]) > 40:
            payload["observations"][17]["value"] = "."
            payload["observations"][33]["value"] = "."

        _write("fred_" + sid, payload)
        written.append(sid)
    return written


def build_av(specs):
    rng = random.Random(4242)
    written = []
    for spec in specs:
        symbol = spec["symbol"]
        if symbol not in AV_PROFILE:
            continue
        profile = AV_PROFILE[symbol]
        last, total_pct, vol = profile[0], profile[1], profile[2]
        shape = profile[3] if len(profile) > 3 else 1.0
        n = 100
        dates = business_days_back(n, 1)
        start = last / (1.0 + total_pct / 100.0)

        values = make_path(n, last, last - start, last * vol / 100.0, rng,
                           floor=0.01, shape=shape)

        block = {}
        for d, v in zip(dates, values):
            o = v * (1 + rng.gauss(0, 0.0012))
            block[d.isoformat()] = {
                "1. open": "%.4f" % o,
                "2. high": "%.4f" % (max(o, v) * 1.0035),
                "3. low": "%.4f" % (min(o, v) * 0.9965),
                "4. close": "%.4f" % v,
                "5. volume": "%d" % int(rng.uniform(3e6, 9e7)),
            }
        payload = {
            "_synthetic": "FABRICATED DATA - generated by tools/make_fixtures.py, not real market data",
            "Meta Data": {
                "1. Information": "SYNTHETIC Daily Prices",
                "2. Symbol": symbol,
                "3. Last Refreshed": dates[-1].isoformat(),
                "4. Output Size": "Compact",
                "5. Time Zone": "US/Eastern",
            },
            "Time Series (Daily)": block,
        }
        _write("av_" + symbol, payload)
        written.append(symbol)
    return written


def _write(name, payload):
    if not os.path.isdir(FIXTURE_DIR):
        os.makedirs(FIXTURE_DIR)
    with open(os.path.join(FIXTURE_DIR, name + ".json"), "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)


def build_auctions():
    """Coupon auction results shaped like the real TreasuryDirect payload."""
    rng = random.Random(99)
    terms = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]
    rows = []
    d = date.today()
    for i in range(28):
        term = terms[i % len(terms)]
        issue = d - timedelta(days=i * 11)
        rows.append({
            "securityType": "Bond" if term in ("20-Year", "30-Year") else "Note",
            "securityTerm": term,
            "issueDate": issue.isoformat() + "T00:00:00",
            "auctionDate": (issue - timedelta(days=3)).isoformat() + "T00:00:00",
            "bidToCoverRatio": "%.6f" % max(1.9, rng.gauss(2.62, 0.22)),
            "highYield": "%.4f" % max(0.5, rng.gauss(4.4, 0.25)),
            "offeringAmount": "%d" % (rng.choice([25, 30, 42, 44, 58, 70]) * 10 ** 9),
        })
    _write("treasury_auctions", rows)
    return rows


def main():
    with open(os.path.join(ROOT, "config", "fred_series.json")) as fh:
        fred_specs = json.load(fh)["series"]
    with open(os.path.join(ROOT, "config", "av_symbols.json")) as fh:
        av_specs = json.load(fh)["symbols"]

    f = build_fred(fred_specs)
    a = build_av(av_specs)
    t = build_auctions()
    print("Wrote %d FRED + %d Alpha Vantage + %d auction SYNTHETIC fixtures to %s"
          % (len(f), len(a), len(t), FIXTURE_DIR))
    print("These are fabricated. Regenerate real ones with: python3 -m src.main --record")


if __name__ == "__main__":
    main()
