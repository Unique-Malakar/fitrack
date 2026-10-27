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


def fetch_all(specs, api_key, years=3, use_fixtures=False, record=False, workers=8):
    """Fetch every configured series. Returns (series_by_id, errors_by_id).

    A single bad series must never abort the morning brief - the pillar scorer
    handles partial coverage and the email reports what was missed.

    Fetched concurrently. Each series is an independent HTTP round trip of roughly
    half a second, so doing seventy of them in sequence spent over thirty seconds
    doing nothing but waiting. FRED allows 120,000 requests a day, so a modest pool
    is well within its limits; the cap is kept low out of politeness rather than
    necessity. Fixture reads stay sequential - they hit the local disk, where
    threads only add overhead.
    """
    if use_fixtures or record or workers <= 1:
        return _fetch_sequential(specs, api_key, years, use_fixtures, record)

    from concurrent.futures import ThreadPoolExecutor

    def _one(spec):
        sid = spec["id"]
        try:
            series = fetch_series(sid, api_key, years, False, False)
            if not series:
                return sid, None, "no usable observations returned"
            return sid, series.scaled(spec.get("scale")), None
        except FetchError as exc:
            return sid, None, str(exc)
        except Exception as exc:  # noqa: BLE001 - a thread must not kill the run
            return sid, None, "%s: %s" % (type(exc).__name__, exc)

    out, errors = {}, {}
    with ThreadPoolExecutor(max_workers=min(workers, len(specs) or 1)) as pool:
        for sid, series, error in pool.map(_one, specs):
            if error:
                errors[sid] = error
            else:
                out[sid] = series
    return out, errors


def _fetch_sequential(specs, api_key, years, use_fixtures, record):
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
