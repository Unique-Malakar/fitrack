"""TreasuryDirect auction results - free, no key, no rate limit.

This supplies the one metric the debt-spiral thesis names as its own trigger:
demand at Treasury auctions. Two measures matter, and the second is the one most
commentary gets wrong.

  BID-TO-COVER - total bids divided by the amount sold. Above ~2.0 is normal.

  TAIL - the gap between the yield the auction cleared at and where the market was
  trading just beforehand. A positive tail means buyers demanded a discount, i.e.
  weak demand.

Why the tail is the better signal: a US Treasury auction cannot "fail" the way a
corporate bond sale can. Primary dealers are obligated to bid, which puts a floor
under bid-to-cover - it structurally cannot fall toward 1.0 in a functioning
market. Weak demand shows up as a higher clearing yield, not an unsold auction.
Watching for a "failed auction" is watching for something the plumbing prevents.
"""
from __future__ import annotations

from datetime import date, datetime

from .http import FetchError, get_json, record_fixture

AUCTION_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"

# Bills are money-market instruments and their demand says little about long-term
# confidence in the debt, which is what the thesis is actually about.
COUPON_TERMS = ("2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year")


class Auction(object):
    __slots__ = ("term", "security_type", "issue_date", "auction_date",
                 "bid_to_cover", "high_yield", "offering", "tail")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        for k in ("issue_date", "auction_date"):
            if hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        return d


def _num(value):
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse(payload):
    if not isinstance(payload, list):
        raise FetchError("treasury: expected a JSON list of auctions")

    out = []
    for row in payload:
        term = row.get("securityTerm")
        if term not in COUPON_TERMS:
            continue
        btc = _num(row.get("bidToCoverRatio"))
        if btc is None:
            continue
        out.append(Auction(
            term=term,
            security_type=row.get("securityType"),
            issue_date=_day(row.get("issueDate")),
            auction_date=_day(row.get("auctionDate")) or _day(row.get("issueDate")),
            bid_to_cover=btc,
            high_yield=_num(row.get("highYield")),
            offering=_num(row.get("offeringAmount")),
            tail=None,
        ))

    out.sort(key=lambda a: a.auction_date or date.min)
    return out


def fetch_auctions(pagesize=60, use_fixtures=False, record=False):
    params = {"format": "json", "pagesize": pagesize, "reopening": "No"}
    payload = get_json(AUCTION_URL, params, "treasury_auctions", use_fixtures)
    if record:
        record_fixture("treasury_auctions", payload)
    return _parse(payload)


def demand_summary(auctions, recent=6):
    """Average bid-to-cover recently versus its longer baseline.

    Comparing recent demand to this series' own baseline, rather than to a fixed
    number, keeps it consistent with how everything else here is scored.
    """
    if not auctions:
        return None

    by_term = {}
    for a in auctions:
        by_term.setdefault(a.term, []).append(a)

    latest = auctions[-1]
    recent_set = auctions[-recent:]
    recent_avg = sum(a.bid_to_cover for a in recent_set) / len(recent_set)
    baseline = sum(a.bid_to_cover for a in auctions) / len(auctions)

    return {
        "latest_term": latest.term,
        "latest_btc": latest.bid_to_cover,
        "latest_date": latest.auction_date.isoformat() if latest.auction_date else None,
        "recent_avg": recent_avg,
        "baseline_avg": baseline,
        "delta": recent_avg - baseline,
        "count": len(auctions),
        "min_recent": min(a.bid_to_cover for a in recent_set),
        "terms": sorted(by_term),
    }
