"""Alpha Vantage fetcher.

Uses TIME_SERIES_DAILY (one request per symbol, ~100 trading days back), which is
enough to derive 1w/1m/3m relative strength without spending extra requests.

Note on TIME_SERIES_DAILY vs _ADJUSTED: the adjusted endpoint moved to Alpha
Vantage's premium tier, so this uses unadjusted closes. Dividends therefore show
up as small negative drift in relative strength - material over 3 months for the
high-yield sectors (XLU, XLRE, XLP, XLE). See `DIVIDEND_DRAG_NOTE`.
"""
from __future__ import annotations

import time

from ..engine.timeseries import Series, parse_date
from .http import FetchError, get_json, record_fixture

AV_URL = "https://www.alphavantage.co/query"

# Alpha Vantage throttles the free tier to roughly one request per second, on top of
# the 25/day cap. Firing the symbol list back-to-back gets everything after the first
# request rejected with a "spread out your requests" message returned as HTTP 200.
REQUEST_INTERVAL_SEC = 1.3

DIVIDEND_DRAG_NOTE = (
    "Sector relative strength uses unadjusted closes; high-yield sectors carry roughly "
    "0.5-1.0pp of dividend drag per quarter versus total return."
)

# Alpha Vantage signals problems in the body with a 200 status, under these keys.
_ERROR_KEYS = ("Error Message", "Note", "Information")


def _parse(symbol, payload):
    for key in _ERROR_KEYS:
        if key in payload:
            raise FetchError("%s: %s" % (symbol, str(payload[key])[:180]))

    block = payload.get("Time Series (Daily)")
    if not block:
        raise FetchError("%s: response had no 'Time Series (Daily)' block" % symbol)

    rows = []
    for day, fields in block.items():
        close = fields.get("4. close") or fields.get("5. adjusted close")
        if close in (None, "", "."):
            continue
        try:
            rows.append((parse_date(day), float(close)))
        except (TypeError, ValueError):
            continue
    if not rows:
        raise FetchError("%s: no parseable closes" % symbol)

    rows.sort(key=lambda r: r[0])
    return Series(symbol, [r[0] for r in rows], [r[1] for r in rows])


def fetch_symbol(symbol, api_key, use_fixtures=False, record=False, outputsize="compact"):
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": outputsize,
        "apikey": api_key or "FIXTURE",
    }
    payload = get_json(AV_URL, params, "av_" + symbol, use_fixtures)
    if record:
        record_fixture("av_" + symbol, payload)
    return _parse(symbol, payload)


def _is_daily_cap(message):
    """Distinguish the hard daily cap from the soft per-second throttle.

    Both arrive as HTTP 200 with prose, and both mention premium plans, so matching
    on "premium" treats a one-second throttle as a dead run. Only the daily cap is
    worth aborting on; the throttle just needs another moment.
    """
    text = message.lower()
    return "per day" in text or "daily rate limit" in text or "25 requests" in text


def _is_throttle(message):
    text = message.lower()
    return "spreading out" in text or "per second" in text or "higher api call" in text


def fetch_all(specs, api_key, use_fixtures=False, record=False, budget=25):
    """Fetch every configured symbol, pacing requests to respect the free tier.

    Returns (series_by_symbol, errors_by_symbol). Hitting the DAILY cap aborts the
    remaining symbols, since they would all fail too. Hitting the per-second throttle
    retries once after a pause, because the next second will work.
    """
    out, errors = {}, {}
    spent = 0
    live = not use_fixtures

    for spec in specs:
        symbol = spec["symbol"]
        if spent >= budget:
            errors[symbol] = "skipped: daily request budget (%d) exhausted" % budget
            continue
        # Pace only real requests; fixture reads hit the disk and need no throttle.
        if live and spent:
            time.sleep(REQUEST_INTERVAL_SEC)

        try:
            out[symbol] = fetch_symbol(symbol, api_key, use_fixtures, record)
            spent += 1
            continue
        except FetchError as exc:
            message = str(exc)
        spent += 1

        if live and _is_throttle(message) and not _is_daily_cap(message):
            time.sleep(REQUEST_INTERVAL_SEC * 3)
            try:
                out[symbol] = fetch_symbol(symbol, api_key, use_fixtures, record)
                spent += 1
                continue
            except FetchError as exc:
                message = str(exc)
            spent += 1

        errors[symbol] = message
        if _is_daily_cap(message):
            for rest in specs[specs.index(spec) + 1:]:
                errors[rest["symbol"]] = "skipped: upstream daily cap reached"
            break

    return out, errors
