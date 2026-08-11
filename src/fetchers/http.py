"""Minimal HTTP + fixture layer shared by every fetcher.

Stdlib only, so the project runs with no installs. Two modes:
  live    - real requests, with retry on transient failures
  fixture - reads a recorded JSON response from tests/fixtures/
Fixture mode is what makes the whole pipeline testable before API keys exist.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tests", "fixtures",
)

TRANSIENT_STATUS = {429, 500, 502, 503, 504}


# Upstream error messages can contain the credentials that produced them: Alpha
# Vantage's rate-limit response quotes the API key back verbatim. Those messages are
# stored in daily snapshots, rendered into the email, and shown on the dashboard -
# all of which are published. Every error string must be scrubbed before it travels.
_SECRET_ENV_VARS = ("FRED_API_KEY", "ALPHAVANTAGE_API_KEY", "SMTP_PASSWORD")
_MASK = "***REDACTED***"


def scrub(text):
    """Mask any configured secret appearing in `text`."""
    if text is None:
        return text
    out = str(text)
    for name in _SECRET_ENV_VARS:
        value = os.environ.get(name)
        # Short values would mask harmless substrings; real keys are long.
        if value and len(value) >= 8:
            out = out.replace(value, _MASK)
    return out


class FetchError(Exception):
    """A request failed in a way the caller should record as a missing series."""

    def __init__(self, message):
        super(FetchError, self).__init__(scrub(message))


def fixture_path(name: str) -> str:
    return os.path.join(FIXTURE_DIR, name + ".json")


def _read_fixture(name: str) -> dict:
    path = fixture_path(name)
    if not os.path.exists(path):
        raise FetchError("no fixture recorded for '%s' (expected %s)" % (name, path))
    with open(path, "r") as fh:
        return json.load(fh)


def get_json(url, params, fixture_name, use_fixtures, timeout=30, retries=3, pause=1.5):
    """Fetch JSON, or load the recorded fixture when use_fixtures is set.

    `fixture_name` doubles as the cache key when recording, so it must be unique
    per logical request (typically the series id or symbol).
    """
    if use_fixtures:
        return _read_fixture(fixture_name)

    full = url + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "market-intel/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code not in TRANSIENT_STATUS:
                break
        # Everything else at this boundary is a transport failure. Catching only
        # URLError is not enough: http.client.RemoteDisconnected, ConnectionReset,
        # and ssl.SSLError are not URLError subclasses, so a single dropped
        # connection propagated all the way out and killed the entire run - which
        # at 6am means no brief at all rather than a brief with one gap in it.
        # A named-exception list here is a liability; anything this raises should
        # degrade to one missing series.
        except Exception as exc:  # noqa: BLE001 - deliberate network boundary
            last = "%s: %s" % (type(exc).__name__, exc)
        if attempt < retries - 1:
            time.sleep(pause * (2 ** attempt))
    raise FetchError("%s failed after %d attempts: %s" % (fixture_name, retries, last))


def record_fixture(name: str, payload: dict) -> None:
    """Persist a live response so it can be replayed offline."""
    if not os.path.isdir(FIXTURE_DIR):
        os.makedirs(FIXTURE_DIR)
    with open(fixture_path(name), "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
