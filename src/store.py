"""Snapshot persistence.

Two jobs (spec, Phase 1 "Data persistence"):
  1. keep the previous run so the brief can report what changed since
  2. accumulate the history the Phase 4 dashboard will chart

Deltas themselves are computed from each series' own history, not from these
snapshots, so a missed run never corrupts the numbers - it only costs one
regime-direction comparison. JSON now; the layout maps cleanly onto SQLite rows
when Phase 4 needs querying.
"""
from __future__ import annotations

import json
import os
from datetime import date

from .fetchers.http import scrub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(ROOT, "data", "daily")
HISTORY_PATH = os.path.join(ROOT, "data", "history.json")
ALERT_STATE_PATH = os.path.join(ROOT, "data", "alert_state.json")
DASHBOARD_PATH = os.path.join(ROOT, "build", "dashboard.html")
BUILD_DIR = os.path.join(ROOT, "build")
CAPS_PATH = os.path.join(ROOT, "data", "market_caps.json")
AV_CACHE_PATH = os.path.join(ROOT, "data", "av_cache.json")


def _ensure_dir():
    if not os.path.isdir(DAILY_DIR):
        os.makedirs(DAILY_DIR)


def snapshot_path(day):
    return os.path.join(DAILY_DIR, "%s.json" % day.isoformat())


def save_snapshot(day, pillars, diagnosis, readings, signals, errors):
    _ensure_dir()
    payload = {
        "date": day.isoformat(),
        "regime": diagnosis.as_dict(),
        "pillars": {str(k): v.as_dict() for k, v in pillars.items()},
        "readings": {r.sid: r.as_dict() for r in readings if r is not None},
        "signals": [s.as_dict() for s in signals],
        "errors": {k: scrub(v) for k, v in (errors or {}).items()},
    }
    with open(snapshot_path(day), "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, default=str)
    return payload


def load_previous(before_day):
    """Most recent snapshot strictly before `before_day`, or None."""
    if not os.path.isdir(DAILY_DIR):
        return None
    days = []
    for fname in os.listdir(DAILY_DIR):
        if not fname.endswith(".json"):
            continue
        stem = fname[:-5]
        try:
            d = date.fromisoformat(stem)
        except ValueError:
            continue
        if d < before_day:
            days.append(d)
    if not days:
        return None
    with open(snapshot_path(max(days)), "r") as fh:
        return json.load(fh)


def previous_pillars(before_day):
    prev = load_previous(before_day)
    if not prev:
        return None, None
    return {int(k): v for k, v in prev.get("pillars", {}).items()}, prev


def save_history(records):
    """Replayed regime history - the dataset the dashboard charts."""
    _ensure_dir()
    with open(HISTORY_PATH, "w") as fh:
        json.dump({"generated": date.today().isoformat(), "records": records},
                  fh, separators=(",", ":"), default=str)
    return HISTORY_PATH


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r") as fh:
            return json.load(fh).get("records", [])
    except (ValueError, OSError):
        return []


def load_alert_state():
    """Cooldown records keeping a persistent condition from re-firing daily."""
    if not os.path.exists(ALERT_STATE_PATH):
        return {}
    try:
        with open(ALERT_STATE_PATH, "r") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return {}


def save_alert_state(state):
    _ensure_dir()
    with open(ALERT_STATE_PATH, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    return ALERT_STATE_PATH


def write_dashboard(html):
    """Write the dashboard as both dashboard.html and index.html.

    The navigation links to index.html because that is what GitHub Pages serves.
    Locally the file was only ever called dashboard.html, so every tab link broke
    on a local preview - the one situation where you most want the links to work.
    Writing both makes local preview identical to the deployed site.
    """
    out_dir = os.path.dirname(DASHBOARD_PATH)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for name in ("dashboard.html", "index.html"):
        with open(os.path.join(out_dir, name), "w") as fh:
            fh.write(html)
    return DASHBOARD_PATH


def load_market_caps(max_age_days=7, today=None):
    """Cached market capitalisations.

    Fetching these per ticker dominates the heatmap's runtime (~28s for seventy
    names) while the values themselves barely move day to day. Refreshed weekly.
    """
    from datetime import date as _date, timedelta as _td
    today = today or _date.today()
    if not os.path.exists(CAPS_PATH):
        return None
    try:
        with open(CAPS_PATH) as fh:
            blob = json.load(fh)
        stamped = _date.fromisoformat(blob.get("generated", "1970-01-01"))
    except (ValueError, OSError, TypeError):
        return None
    if today - stamped > _td(days=max_age_days):
        return None
    return blob.get("caps") or None


def save_market_caps(caps):
    _ensure_dir()
    with open(CAPS_PATH, "w") as fh:
        json.dump({"generated": date.today().isoformat(), "caps": caps}, fh)
    return CAPS_PATH


def write_page(filename, html):
    if not os.path.isdir(BUILD_DIR):
        os.makedirs(BUILD_DIR)
    path = os.path.join(BUILD_DIR, filename)
    with open(path, "w") as fh:
        fh.write(html)
    return path


def load_av_cache(max_age_hours=20):
    """Cached Alpha Vantage series.

    The free tier allows 25 requests a day, which the morning brief nearly fills.
    Refreshing the site hourly would need roughly a hundred, so the intraday runs
    reuse the morning's pull instead. FRED and Yahoo are unmetered and stay live,
    and the regime verdict is built from daily macro data that does not change
    between hourly refreshes anyway - only prices do.
    """
    from datetime import datetime, timedelta
    if not os.path.exists(AV_CACHE_PATH):
        return None
    try:
        with open(AV_CACHE_PATH) as fh:
            blob = json.load(fh)
        stamped = datetime.fromisoformat(blob["generated"])
    except (ValueError, OSError, KeyError, TypeError):
        return None
    if datetime.utcnow() - stamped > timedelta(hours=max_age_hours):
        return None
    return blob.get("series") or None


def save_av_cache(series_by_symbol):
    """Persist the raw closes so an intraday run can rebuild without new requests."""
    from datetime import datetime
    _ensure_dir()
    payload = {s: {"dates": [d.isoformat() for d in ser.dates], "values": ser.values}
               for s, ser in series_by_symbol.items()}
    with open(AV_CACHE_PATH, "w") as fh:
        json.dump({"generated": datetime.utcnow().isoformat(), "series": payload}, fh)
    return AV_CACHE_PATH


def rehydrate_av(blob):
    from .engine.timeseries import Series, parse_date
    out = {}
    for symbol, rec in (blob or {}).items():
        try:
            out[symbol] = Series(symbol, [parse_date(d) for d in rec["dates"]],
                                 [float(v) for v in rec["values"]])
        except (KeyError, ValueError, TypeError):
            continue
    return out
