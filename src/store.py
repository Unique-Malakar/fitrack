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
    out_dir = os.path.dirname(DASHBOARD_PATH)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(DASHBOARD_PATH, "w") as fh:
        fh.write(html)
    return DASHBOARD_PATH
