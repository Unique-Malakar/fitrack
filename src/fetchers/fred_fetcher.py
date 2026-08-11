"""FRED API fetcher.

Talks to the same REST endpoint `fredapi` wraps, without the pandas dependency.
Each series is one request; ~40 series is trivial against the 120K/day limit.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..engine.timeseries import Series, parse_date
from .http import FetchError, get_json, record_fixture

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def _parse(sid, payload):
    obs = payload.get("observations")
    if obs is None:
        raise FetchError("%s: response had no 'observations' key" % sid)
    dates, values = [], []
    for row in obs:
        raw = row.get("value")
        # FRED encodes missing observations as "." - drop rather than zero-fill.
        if raw is None or raw in (".", ""):
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
        dates.append(parse_date(row["date"]))
    return Series(sid, dates, values)


def fetch_series(sid, api_key, years=3, use_fixtures=False, record=False):
    start = (date.today() - timedelta(days=int(365.25 * years) + 400)).isoformat()
    params = {
        "series_id": sid,
        "api_key": api_key or "FIXTURE",
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    payload = get_json(FRED_URL, params, "fred_" + sid, use_fixtures)
    if record:
        record_fixture("fred_" + sid, payload)
    return _parse(sid, payload)


def fetch_all(specs, api_key, years=3, use_fixtures=False, record=False):
    """Fetch every configured series. Returns (series_by_id, errors_by_id).

    A single bad series must never abort the morning brief - the pillar scorer
    handles partial coverage and the email reports what was missed.
    """
    out, errors = {}, {}
    for spec in specs:
        sid = spec["id"]
        try:
            series = fetch_series(sid, api_key, years, use_fixtures, record)
            if not series:
                errors[sid] = "no usable observations returned"
                continue
            out[sid] = series.scaled(spec.get("scale"))
        except FetchError as exc:
            errors[sid] = str(exc)
    return out, errors
