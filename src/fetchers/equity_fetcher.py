"""Individual stock prices and market caps, via yfinance.

Kept deliberately off the critical path. FRED and Alpha Vantage feed the regime
engine and must not break; this powers the heatmap and watchlist tabs, which are
useful but optional. yfinance scrapes an unofficial Yahoo endpoint and can stop
working without notice, so every function here fails soft and the pages it feeds
degrade to an empty state rather than taking the build down.

One bulk request covers every ticker, which is why a seventy-name heatmap is
affordable when the Alpha Vantage budget could not stretch to five.
"""
from __future__ import annotations

try:  # pragma: no cover - availability varies by environment
    import yfinance as _yf
except ImportError:  # pragma: no cover
    _yf = None

AVAILABLE = _yf is not None


class Quote(object):
    __slots__ = ("symbol", "price", "prev", "change_pct", "market_cap", "sector")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


def _last_two(frame, symbol):
    """Closing prices for the last two sessions, tolerating yfinance's shapes."""
    try:
        col = frame["Close"][symbol] if hasattr(frame["Close"], "columns") else frame["Close"]
        values = [float(v) for v in col.tolist() if v == v]
    except Exception:  # noqa: BLE001
        return None, None
    if len(values) < 2:
        return (values[-1] if values else None), None
    return values[-1], values[-2]


def fetch_quotes(symbols, with_caps=True, period="5d"):
    """Prices for every symbol in one request; caps individually where asked.

    Returns (quotes_by_symbol, error_or_None). Never raises.
    """
    if not symbols:
        return {}, None
    if _yf is None:
        return {}, "yfinance is not installed"

    try:
        frame = _yf.download(" ".join(symbols), period=period, progress=False,
                             auto_adjust=False, threads=True)
    except Exception as exc:  # noqa: BLE001 - unofficial source
        return {}, "price download failed: %s" % str(exc)[:120]

    if frame is None or len(frame) == 0:
        return {}, "price download returned nothing"

    out = {}
    for symbol in symbols:
        price, prev = _last_two(frame, symbol)
        if price is None:
            continue
        out[symbol] = Quote(
            symbol=symbol, price=price, prev=prev,
            change_pct=((price - prev) / prev * 100.0) if prev else None,
            market_cap=None, sector=None)

    if with_caps:
        for symbol, quote in out.items():
            try:
                cap = getattr(_yf.Ticker(symbol).fast_info, "market_cap", None)
                quote.market_cap = float(cap) if cap else None
            except Exception:  # noqa: BLE001 - a missing cap is survivable
                quote.market_cap = None

    return out, None


def fetch_constituents(sector_map, cached_caps=None):
    """Quotes for every name in the treemap, tagged with its sector."""
    symbols = [s for names in sector_map.values() for s in names]
    # Market caps are the slow part; reuse them when a recent cache exists.
    quotes, error = fetch_quotes(symbols, with_caps=not cached_caps)
    if cached_caps:
        for symbol, quote in quotes.items():
            cap = cached_caps.get(symbol)
            quote.market_cap = float(cap) if cap else None
    for sector, names in sector_map.items():
        for symbol in names:
            if symbol in quotes:
                quotes[symbol].sector = sector
    return quotes, error


def fetch_history(symbols, period="6mo", points=90):
    """Closes plus a downsampled history, for the asset cards.

    Returns {symbol: {price, chg_1d, chg_6m, history}}. Never raises; a symbol that
    fails is simply absent, and the card for it is not drawn.
    """
    out = {}
    if not symbols or _yf is None:
        return out, ("yfinance is not installed" if _yf is None else None)

    try:
        frame = _yf.download(" ".join(symbols), period=period, progress=False,
                            auto_adjust=False, threads=True)
    except Exception as exc:  # noqa: BLE001 - unofficial source
        return out, "history download failed: %s" % str(exc)[:120]
    if frame is None or len(frame) == 0:
        return out, "history download returned nothing"

    for symbol in symbols:
        try:
            col = frame["Close"][symbol] if hasattr(frame["Close"], "columns") else frame["Close"]
            values = [float(v) for v in col.tolist() if v == v]
        except Exception:  # noqa: BLE001
            continue
        if len(values) < 3:
            continue
        # Downsample so a long history does not bloat the page.
        stride = max(1, len(values) // points)
        history = values[::stride]
        if history[-1] != values[-1]:
            history.append(values[-1])
        prev = values[-2] if len(values) > 1 else None
        first = values[0]
        out[symbol] = {
            "price": values[-1],
            "chg_1d": ((values[-1] - prev) / prev * 100.0) if prev else None,
            "chg_6m": ((values[-1] - first) / first * 100.0) if first else None,
            "history": history,
        }
    return out, None
