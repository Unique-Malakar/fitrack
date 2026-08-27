"""Orchestrator: fetch -> score -> classify -> render -> send.

  python3 -m src.main --fixtures --dry-run              # offline brief preview
  python3 -m src.main                                   # live brief, needs .env
  python3 -m src.main --record                          # live, saves fixtures
  python3 -m src.main --fixtures --dashboard --dry-run  # + build/dashboard.html
  python3 -m src.main --fixtures --alerts --dry-run     # Phase 3 alert check
  python3 -m src.main --fixtures --calibrate            # Phase 2 tuning report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from .engine import alerts as alert_engine
from .engine import backfill, chain, market, regime, sectors as sector_engine
from .engine import signals as signal_engine
from .engine import aicredit as aicredit_engine
from .engine import transitions as transition_engine
from .engine import watchlist as watch_engine
from .engine.indicators import build_reading
from .engine.pillar_scores import score_all
from .fetchers import av_fetcher, earnings_fetcher, equity_fetcher
from .fetchers import fred_fetcher, rss_fetcher, treasury_fetcher, yf_fallback
from .output import alert_builder, dashboard, email_builder, email_sender
from .output import pages, treemap
from . import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
BUILD_DIR = os.path.join(ROOT, "build")

# Shown in the KEY LEVELS block, in this order.
KEY_LEVEL_IDS = [
    "DGS2", "DGS10", "DGS30", "T10Y2Y", "T10Y3M", "THREEFYTP10", "DFII10",
    "NFCI", "BAMLC0A0CM", "BAMLH0A0HYM2", "VIXCLS", "SAHMREALTIME", "ICSA",
    "CPILFESL", "PCEPILFE", "T5YIE", "RSP_SPY", "SPY_TREND", "RRPONTSYD", "WM2NS",
]


def load_json(name):
    with open(os.path.join(CONFIG_DIR, name), "r") as fh:
        return json.load(fh)


def load_dotenv(path):
    """Minimal .env reader so local runs need no extra dependency."""
    if not os.path.exists(path):
        return
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def run(args):
    load_dotenv(os.path.join(ROOT, ".env"))
    today = date.today()

    fred_cfg = load_json("fred_series.json")
    av_cfg = load_json("av_symbols.json")
    cfg = load_json("thresholds.json")

    specs = fred_cfg["series"]
    av_specs = av_cfg["symbols"]

    fred_key = os.environ.get("FRED_API_KEY", "")
    av_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if not args.fixtures and not fred_key:
        print("ERROR: FRED_API_KEY is not set. Use --fixtures for an offline run.",
              file=sys.stderr)
        return 2

    # ---- fetch
    print("Fetching %d FRED series..." % len(specs))
    raw, errors = fred_fetcher.fetch_all(
        specs, fred_key, cfg.get("fetch_years", cfg["history_years"]),
        args.fixtures, args.record)
    print("  %d ok, %d failed" % (len(raw), len(errors)))

    # The alert check only inspects SPY (for the single-session drawdown trigger),
    # so pulling the full symbol list on every alert run burned 13 requests a time
    # against a 25/day cap shared with the morning brief.
    fetch_specs = ([s for s in av_specs if s["symbol"] == "SPY"]
                   if args.alerts else av_specs)
    cached_av = None if (args.fixtures or args.record) else store.load_av_cache()
    if cached_av and not args.alerts:
        market_series = store.rehydrate_av(cached_av)
        av_errors = {}
        print("Alpha Vantage: reusing cached pull (%d symbols, no requests spent)"
              % len(market_series))
    else:
        print("Fetching %d Alpha Vantage symbol(s)..." % len(fetch_specs))
        market_series, av_errors = av_fetcher.fetch_all(
            fetch_specs, av_key, args.fixtures, args.record,
            av_cfg["budget"]["free_tier_daily_limit"])
        if market_series and not args.fixtures and not args.alerts:
            store.save_av_cache(market_series)
    print("  %d ok, %d failed" % (len(market_series), len(av_errors)))

    auctions = None
    try:
        auction_rows = treasury_fetcher.fetch_auctions(
            use_fixtures=args.fixtures, record=args.record)
        auctions = treasury_fetcher.demand_summary(auction_rows)
        print("Treasury auctions: %d coupon results" % len(auction_rows))
    except Exception as exc:  # noqa: BLE001 - never let this block the brief
        errors["treasury_auctions"] = str(exc)[:150]

    if av_errors and not args.fixtures and args.fallback:
        recovered, still_bad = yf_fallback.rescue(list(av_errors))
        if recovered:
            print("  yfinance recovered %d symbol(s)" % len(recovered))
        market_series.update(recovered)
        av_errors = still_bad
    errors.update(av_errors)

    # ---- score
    readings = []
    for spec in specs:
        series = raw.get(spec["id"])
        if series is None:
            continue
        reading = build_reading(spec, series, cfg, today)
        if reading is None:
            errors[spec["id"]] = "insufficient history to score"
            continue
        readings.append(reading)

    breadth, breadth_rs = market.breadth_reading(market_series, cfg, today)
    if breadth:
        readings.append(breadth)
    trend = market.index_trend_reading(market_series, cfg, today)
    if trend:
        readings.append(trend)

    pillars = score_all(readings, cfg, specs + [
        {"pillar": 5, "weight": 2.5}, {"pillar": 5, "weight": 1.0}])

    by_sid = {r.sid: r for r in readings}
    sigs = signal_engine.evaluate(by_sid, pillars, breadth_rs, market_series)

    prev_pillars, prev_snapshot = store.previous_pillars(today)
    incumbent = (prev_snapshot or {}).get("regime", {}).get("regime")
    diagnosis = regime.classify(pillars, prev_pillars, incumbent)

    print("\nREGIME: %s (%s), confidence %.0f%%"
          % (diagnosis.regime, diagnosis.direction, diagnosis.confidence * 100))
    for p in sorted(pillars.values(), key=lambda x: x.num):
        print("  %-22s %-14s score %+.2f  coverage %3.0f%%"
              % (p.name, p.state, p.score, p.coverage * 100))
    for s in sigs:
        print("  [%s] %s" % (s.tone, s.title))

    # ---- Phase 3: alerts
    fired = []
    if args.alerts or args.dashboard:
        alert_state = store.load_alert_state()
        fired, new_state = alert_engine.evaluate(raw, market_series, alert_state, today)
        if args.alerts and not args.dry_run:
            store.save_alert_state(alert_engine.prune_state(new_state, today))
        if fired:
            print("\nALERTS (%d):" % len(fired))
            for a in fired:
                print("  [%s] %s - %s" % (a.tone, a.label, a.detail))
        elif args.alerts:
            print("\nNo alerts triggered.")

    if args.alerts:
        return _deliver_alerts(fired, today, args)

    # ---- Phase 2: historical replay (also feeds the Phase 4 charts)
    records = []
    if args.dashboard or args.calibrate:
        print("\nReplaying history (step %dd)..." % args.replay_step)
        records = backfill.replay(raw, specs, cfg, market_series,
                                  step_days=args.replay_step)
        print("  %d historical points scored" % len(records))
        store.save_history(records)

    if args.calibrate:
        return _print_calibration(records, cfg)

    # ---- render
    sectors = market.sector_table(market_series, av_specs, "SPY", cfg)

    # Top-of-page prices. Order is deliberate: US indices, then bonds, then the
    # international and hard-asset reads that put the US move in context.
    ticker = _build_ticker(by_sid, args)

    # Upcoming earnings: one request returns the whole forward calendar, so this is
    # cheap regardless of how many names are watched.
    upcoming_earnings = []
    try:
        watch = {s["symbol"] for s in av_specs} | set(_portfolio_tickers())
        for names in load_json("constituents.json")["sectors"].values():
            watch.update(names)
        rows = earnings_fetcher.fetch_calendar(av_key, use_fixtures=args.fixtures)
        upcoming_earnings = earnings_fetcher.select(rows, watch, today=today)
        print("Earnings calendar: %d upcoming in the next 3 weeks" % len(upcoming_earnings))
    except Exception as exc:  # noqa: BLE001 - never block the brief
        errors["earnings_calendar"] = str(exc)[:140]

    # Map current conditions onto each sector's structural exposures (spec 2.3).
    dollar = by_sid.get("DTWEXBGS")
    outlook_rows, _ = sector_engine.score_sectors(
        pillars, av_specs,
        dollar_drift=(dollar.drift if dollar is not None else None),
        market_rs={r["symbol"]: r["rs"].get("1m") for r in sectors})
    ctx = {
        "date": today,
        "diagnosis": diagnosis,
        "pillars": pillars,
        "readings": readings,
        "signals": sigs,
        "key_levels": [by_sid[k] for k in KEY_LEVEL_IDS if k in by_sid],
        "sectors": sectors,
        "sector_note": av_fetcher.DIVIDEND_DRAG_NOTE,
        "global_rows": _global_rows(by_sid, market_series),
        "errors": errors,
        # Anchors travel with the reading so the dashboard can say "below the 0.50
        # threshold" instead of inferring meaning from percentile alone.
        "spec_by_id": {sp["id"]: sp for sp in specs},
        "sector_outlook": outlook_rows,
        "spec_readings": by_sid,
        "raw_series": raw,
        "ticker": ticker,
        "watchlist": watch_engine.top_indicators(readings, specs, raw),
        "would_change": watch_engine.what_would_change(
            pillars, readings, specs, diagnosis, cfg),
        "transitions": transition_engine.outlook(
            store.load_history() or records, diagnosis.regime, args.replay_step),
        "earnings": upcoming_earnings,
    }
    subject, text_body, html_body = email_builder.build(ctx)

    if args.fixtures:
        print("Fixture mode: snapshot not saved (fabricated data stays out of history).")
    else:
        store.save_snapshot(today, pillars, diagnosis, readings, sigs, errors)

    # ---- Debt & debasement chain
    chain_stages, chain_summary = chain.evaluate(
        by_sid, auctions,
        gold_1y_pct=_pct_over(market_series.get("GLD"), 252),
        spy_1y_pct=_pct_over(market_series.get("SPY"), 252),
        raw=raw)
    print("\nDebt chain: %s" % chain_summary["verdict"])
    for st in chain_stages:
        print("  Stage %d %-24s %s" % (st.num, st.name, st.label))

    if args.dashboard:
        _build_extra_pages(ctx, diagnosis, today, args)

    # ---- Phase 4: dashboard
    if args.dashboard:
        page = dashboard.build(ctx, records, fired, synthetic=args.fixtures,
                               chain_stages=chain_stages, chain_summary=chain_summary)
        path = store.write_dashboard(page)
        print("Dashboard: %s" % path)

    # ---- deliver
    if args.dry_run:
        html_path, text_path = email_sender.write_preview(
            BUILD_DIR, subject, text_body, html_body)
        print("\nDry run. Wrote:\n  %s\n  %s" % (html_path, text_path))
        return 0

    email_cfg = email_sender.EmailConfig.from_env()
    if not email_cfg.configured:
        html_path, _ = email_sender.write_preview(BUILD_DIR, subject, text_body, html_body)
        print("\nEmail not configured; wrote preview to %s" % html_path, file=sys.stderr)
        return 1

    to = email_sender.send(email_cfg, subject, text_body, html_body)
    print("\nSent to %s" % to)
    return 0


def _gauge_returns(symbols, days=63):
    """Trailing returns for the aggregate gauges, in one bulk request."""
    from .fetchers import equity_fetcher as _eq
    out = {}
    if not _eq.AVAILABLE:
        return out
    try:
        import yfinance as yf
        frame = yf.download(" ".join(symbols), period="6mo", progress=False,
                            auto_adjust=False, threads=True)
    except Exception:  # noqa: BLE001
        return out
    for sym in symbols:
        try:
            col = frame["Close"][sym].dropna()
            values = [float(v) for v in col.tolist()]
        except Exception:  # noqa: BLE001
            continue
        if len(values) < 2:
            continue
        rec = {}
        for window in (21, 63):
            if len(values) > window and values[-1 - window]:
                rec["ret_%d" % window] = (values[-1] / values[-1 - window] - 1) * 100.0
        out[sym] = rec
    return out


def _build_ticker(by_sid, args):
    """Top-of-page prices, from Yahoo rather than Alpha Vantage.

    Yahoo is unmetered, which is what makes crypto, futures and several
    international markets affordable here - the Alpha Vantage free tier is fully
    committed to the regime engine's own symbols.
    """
    tiles = load_json("ticker_strip.json")["tiles"]
    out = []

    live = {}
    symbols = [t["symbol"] for t in tiles if t.get("source") != "fred"]
    if symbols and not args.fixtures:
        quotes, err = equity_fetcher.fetch_quotes(symbols, with_caps=False)
        live = quotes or {}
        if err:
            print("Ticker strip: %s" % err, file=sys.stderr)

    for tile in tiles:
        if tile.get("source") == "fred":
            r = by_sid.get(tile["sid"])
            if r is None or r.value is None:
                continue
            out.append({"label": tile["label"], "name": r.name,
                        "value": "%.2f%s" % (r.value, tile.get("suffix", "")),
                        "chg_1d": None})
            continue
        q = live.get(tile["symbol"])
        if q is None:
            continue
        digits = 0 if q.price >= 1000 else 2
        out.append({"label": tile["label"],
                    "name": "%s (%s)" % (tile["label"], tile["symbol"]),
                    "value": "{:,.{d}f}".format(q.price, d=digits),
                    "chg_1d": q.change_pct})
    return out


def _portfolio_tickers():
    try:
        return [t.strip().upper() for t in load_json("portfolio.json")["tickers"] if t.strip()]
    except Exception:  # noqa: BLE001
        return []


def _build_extra_pages(ctx, diagnosis, today, args):
    """Heatmap, news and watchlist tabs.

    Each is wrapped independently: these depend on an unofficial price source and
    on third-party feeds, and neither should be able to take down the dashboard.
    """
    stamp = today.strftime("%d %B %Y")

    # --- heatmap
    svg, cap_error = "", None
    try:
        sector_map = load_json("constituents.json")["sectors"]
        cached = store.load_market_caps()
        quotes, cap_error = equity_fetcher.fetch_constituents(sector_map, cached)
        if quotes and not cached:
            store.save_market_caps({s: q.market_cap for s, q in quotes.items()
                                    if q.market_cap})
        if quotes:
            svg = treemap.render(quotes, sector_map)
            print("Heatmap: %d constituents" % len(quotes))
    except Exception as exc:  # noqa: BLE001
        cap_error = str(exc)[:140]
    # Crypto and metals for the cards below the map.
    assets, asset_cfg = {}, {}
    try:
        asset_cfg = load_json("assets.json")
        wanted = [a["symbol"] for a in asset_cfg["crypto"] + asset_cfg["metals"]]
        if not args.fixtures:
            assets, aerr = equity_fetcher.fetch_history(wanted)
            if aerr:
                print("Asset cards: %s" % aerr, file=sys.stderr)
            else:
                print("Asset cards: %d crypto/metals" % len(assets))
    except Exception as exc:  # noqa: BLE001
        print("Asset cards failed: %s" % str(exc)[:120], file=sys.stderr)

    store.write_page("heatmap.html", pages.heatmap_page(
        svg, cap_error, stamp, assets=assets, asset_cfg=asset_cfg))

    # --- AI credit thesis
    try:
        gcfg = load_json("aicredit_gauges.json")["gauges"]
        gauges = {}
        if not args.fixtures:
            syms = [g["symbol"] for g in gcfg]
            quotes, _ = equity_fetcher.fetch_quotes(syms, with_caps=False, period="6mo")
            import yfinance as _yf  # noqa: F401  (already imported by the fetcher)
            gauges = _gauge_returns(syms)
        stages, summary = aicredit_engine.evaluate(ctx["spec_readings"], gauges,
                                                   ctx.get("raw_series"))
        store.write_page("aicredit.html", pages.aicredit_page(
            stages, summary, aicredit_engine.NOT_MEASURABLE, stamp))
        print("AI credit: %s" % summary["verdict"])
    except Exception as exc:  # noqa: BLE001
        print("AI credit tab failed: %s" % str(exc)[:140], file=sys.stderr)

    # --- news
    try:
        feeds_cfg = load_json("news_feeds.json")
        by_topic = ({} if args.fixtures
                    else rss_fetcher.fetch_all(feeds_cfg["feeds"]))
        print("News: %d headlines" % sum(len(v) for v in by_topic.values()))
        store.write_page("news.html", pages.news_page(
            by_topic, feeds_cfg["topics"], stamp))
    except Exception as exc:  # noqa: BLE001
        print("News tab failed: %s" % str(exc)[:120], file=sys.stderr)

    # --- watchlist
    pinned = _portfolio_tickers()
    universe, err = {}, None
    try:
        wanted = sorted(set(load_json("universe.json")["tickers"]) | set(pinned))
        if not args.fixtures:
            quotes, err = equity_fetcher.fetch_quotes(wanted, with_caps=False)
            universe = {s: {"p": round(q.price, 4),
                            "c": round(q.change_pct, 2) if q.change_pct is not None else None}
                        for s, q in (quotes or {}).items()}
            print("Watchlist: %d tickers priced" % len(universe))
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:140]
    store.write_page("watchlist.html", pages.watchlist_page(
        [], err, diagnosis.regime, diagnosis.flows.get("favored", "-"),
        diagnosis.flows.get("disfavored", "-"), stamp,
        universe=universe, pinned=pinned))


def _pct_over(series, bars):
    """Percent change over `bars` observations, or the full span if shorter."""
    if series is None or len(series) < 2:
        return None
    idx = max(0, len(series) - 1 - bars)
    prior = series.values[idx]
    if not prior:
        return None
    return (series.values[-1] - prior) / abs(prior) * 100.0


def _global_rows(by_sid, market_series):
    rows = []
    dxy = by_sid.get("DTWEXBGS")
    if dxy:
        rows.append(("Broad Trade-Weighted Dollar", email_builder.fmt_value(dxy),
                     email_builder.fmt_change(dxy.chg_1w, dxy.decimals, dxy.unit)))
    gld = market_series.get("GLD")
    if gld and len(gld) > 6:
        chg = (gld.values[-1] - gld.values[-6]) / gld.values[-6] * 100.0
        rows.append(("Gold (GLD)", "%.2f" % gld.latest, "%+.2f%% 1w" % chg))
    oil = by_sid.get("DCOILWTICO")
    if oil:
        rows.append(("WTI Crude", email_builder.fmt_value(oil),
                     email_builder.fmt_change(oil.chg_1w, oil.decimals, oil.unit)))
    return rows


def _deliver_alerts(fired, today, args):
    """Phase 3 delivery. Silence is the expected outcome on most days."""
    if not fired:
        return 0

    subject, text_body, html_body = alert_builder.build(fired, today)
    if args.dry_run:
        html_path, text_path = email_sender.write_preview(
            BUILD_DIR, subject, text_body, html_body, stem="alert")
        print("\nDry run. Wrote:\n  %s\n  %s" % (html_path, text_path))
        return 0

    email_cfg = email_sender.EmailConfig.from_env()
    if not email_cfg.configured:
        print("\nEmail not configured; alert not sent.", file=sys.stderr)
        return 1
    print("\nAlert sent to %s" % email_sender.send(email_cfg, subject, text_body, html_body))
    return 0


def _print_calibration(records, cfg):
    """Phase 2 tuning aid: are the bands producing a usable spread of outcomes?"""
    report = backfill.calibration(records, cfg)
    if not report:
        print("No historical points to calibrate against.", file=sys.stderr)
        return 1

    print("\n=== CALIBRATION: %d points, %s to %s ==="
          % (report["points"], report["span"]["from"], report["span"]["to"]))
    print("\nRegime frequency:")
    for name, share in report["regimes"].items():
        print("  %-14s %5.1f%%  %s" % (name, share * 100, "#" * int(share * 40)))
    print("\nDirection:")
    for name, share in report["directions"].items():
        print("  %-14s %5.1f%%" % (name, share * 100))
    print("\nPillar score spread (min / p25 / median / p75 / max):")
    for num, sp in sorted(report["pillar_score_spread"].items()):
        print("  Pillar %s   %+.2f  %+.2f  %+.2f  %+.2f  %+.2f"
              % (num, sp["min"], sp["p25"], sp["median"], sp["p75"], sp["max"]))
    print("\nDistinct episodes: %d" % report["episodes"])
    if report["warnings"]:
        print("\nWARNINGS:")
        for w in report["warnings"]:
            print("  ! %s" % w)
    else:
        print("\nNo calibration warnings: the bands produce a usable spread.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Generate and send the daily market brief.")
    ap.add_argument("--fixtures", action="store_true",
                    help="read recorded responses instead of calling the APIs")
    ap.add_argument("--record", action="store_true",
                    help="save live responses as fixtures")
    ap.add_argument("--dry-run", action="store_true",
                    help="write to build/ instead of sending email")
    ap.add_argument("--fallback", action="store_true",
                    help="try yfinance for symbols Alpha Vantage could not supply")
    ap.add_argument("--dashboard", action="store_true",
                    help="Phase 4: also build build/dashboard.html")
    ap.add_argument("--alerts", action="store_true",
                    help="Phase 3: run alert checks only, email only if any fire")
    ap.add_argument("--calibrate", action="store_true",
                    help="Phase 2: print the scoring calibration report and exit")
    ap.add_argument("--replay-step", type=int, default=7,
                    help="days between replayed history points (default 7)")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
