"""Upcoming earnings, from Alpha Vantage's calendar endpoint.

One request returns the entire forward calendar as CSV - every listed company,
its report date, fiscal period and consensus EPS estimate. That makes it cheap:
a single call against the daily budget regardless of how many names are tracked.

The full file runs to thousands of rows, almost all of which are companies nobody
watching the S&P cares about. It is filtered to names that actually move the index
plus whatever is on the user's own ticker list.
"""
from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from .http import FetchError, scrub

AV_URL = "https://www.alphavantage.co/query"


class Earning(object):
    __slots__ = ("symbol", "name", "report_date", "fiscal_ending", "estimate", "when")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        if hasattr(d["report_date"], "isoformat"):
            d["report_date"] = d["report_date"].isoformat()
        return d


def _parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_calendar(api_key, horizon="3month", use_fixtures=False, timeout=40):
    """Returns raw CSV rows. This endpoint returns CSV, not JSON, so it does not
    share the JSON fetch path."""
    if use_fixtures:
        import json
        import os
        from .http import fixture_path
        path = fixture_path("av_earnings_calendar")
        if not os.path.exists(path):
            raise FetchError("no fixture recorded for av_earnings_calendar")
        with open(path) as fh:
            return json.load(fh).get("rows", [])

    params = {"function": "EARNINGS_CALENDAR", "horizon": horizon,
              "apikey": api_key or "FIXTURE"}
    url = AV_URL + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "market-intel/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise FetchError(scrub("earnings calendar: %s: %s" % (type(exc).__name__, exc)))

    if not body.lstrip().lower().startswith("symbol"):
        # Rate limits and errors come back as prose or JSON rather than CSV.
        raise FetchError(scrub("earnings calendar returned no CSV: %s" % body[:180]))

    rows = list(csv.DictReader(io.StringIO(body)))

    # Checking the header is not enough. When the daily quota is exhausted this
    # endpoint returns the CSV header followed by the word "Information" spelled one
    # letter per column, which parses cleanly into a row of single characters. The
    # only reliable test is whether the content looks like data.
    usable = [r for r in rows if _parse_date(r.get("reportDate"))
              and 1 <= len((r.get("symbol") or "").strip()) <= 6]
    if rows and not usable:
        raise FetchError(scrub(
            "earnings calendar returned no usable rows (likely a rate limit): %s"
            % body[:160].replace("\n", " ")))
    return usable


def select(rows, watch, days=21, today=None, limit=25):
    """Keep only names worth surfacing, inside the next few weeks.

    `watch` is the set of symbols that matter: index heavyweights plus the user's
    own list. Everything else is noise - the raw calendar contains thousands of
    microcaps reporting on any given day.
    """
    today = today or date.today()
    horizon = today + timedelta(days=days)
    watch = {w.upper() for w in watch}

    out = []
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if symbol not in watch:
            continue
        when = _parse_date(row.get("reportDate"))
        if when is None or when < today or when > horizon:
            continue
        estimate = (row.get("estimate") or "").strip()
        try:
            estimate = float(estimate) if estimate else None
        except ValueError:
            estimate = None
        out.append(Earning(
            symbol=symbol,
            name=(row.get("name") or symbol).title(),
            report_date=when,
            fiscal_ending=(row.get("fiscalDateEnding") or "").strip(),
            estimate=estimate,
            when=(row.get("timeOfTheDay") or "").strip(),
        ))

    out.sort(key=lambda e: (e.report_date, e.symbol))
    return out[:limit]
