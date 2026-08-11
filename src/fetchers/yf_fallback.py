"""yfinance fallback - used only when a symbol fails at Alpha Vantage.

yfinance is an unofficial scraper of Yahoo endpoints and can break without notice,
which is exactly why it sits behind the other two sources. It is also the only
optional dependency: if it is not installed, this degrades to a no-op and the
caller records the symbol as missing.
"""
from __future__ import annotations

from ..engine.timeseries import Series

try:  # pragma: no cover - availability depends on the environment
    import yfinance as _yf
except ImportError:  # pragma: no cover
    _yf = None

AVAILABLE = _yf is not None


def fetch_symbol(symbol, period="6mo"):
    if _yf is None:
        raise RuntimeError("yfinance is not installed; fallback unavailable")

    hist = _yf.Ticker(symbol).history(period=period, auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError("%s: yfinance returned no rows" % symbol)

    dates = [d.date() for d in hist.index.to_pydatetime()]
    values = [float(v) for v in hist["Close"].tolist()]
    pairs = [(d, v) for d, v in zip(dates, values) if v == v]  # drop NaN
    if not pairs:
        raise RuntimeError("%s: yfinance returned no usable closes" % symbol)
    return Series(symbol, [p[0] for p in pairs], [p[1] for p in pairs])


def rescue(symbols, period="6mo"):
    """Try to recover failed symbols. Returns (recovered, still_failing_reasons)."""
    recovered, failed = {}, {}
    if not AVAILABLE:
        return recovered, {s: "yfinance not installed" for s in symbols}
    for symbol in symbols:
        try:
            recovered[symbol] = fetch_symbol(symbol, period)
        except Exception as exc:  # noqa: BLE001 - unofficial source, fail soft
            failed[symbol] = str(exc)
    return recovered, failed
