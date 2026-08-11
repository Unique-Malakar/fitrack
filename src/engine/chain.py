"""The debt / debasement chain reaction, as a FALSIFIABLE tracker.

The thesis: unsustainable debt forces the Fed to monetise it, which debases the
currency, which pumps asset prices and flatters the labour market, until inflation
forces rates back up and the cycle restarts harder.

It is a coherent thesis with real transmission mechanisms. It is also the kind of
narrative that confirms itself if you let it: a falling dollar proves debasement, a
rising dollar is "the illusion of strength". A thesis that cannot be wrong cannot
inform a decision.

So each stage here carries an explicit, checkable condition and is allowed to report
NOT FIRING. That is the whole point of the module. The stages are deliberately
independent - stage 5 can be lit while stage 2 is dark, and that combination is
informative precisely because the chain says it should not happen.

Two corrections are baked in, because both are load-bearing and both are commonly
stated wrongly:

1. INTEREST BURDEN. The 10-year yield is not the rate the government pays. The
   average rate across outstanding debt is far lower and moves slowly, because the
   stack rolls over across years. So the burden is computed from ACTUAL interest
   outlays over ACTUAL receipts, not projected from a headline yield.

2. AUCTION FAILURE. A US Treasury auction cannot fail the way the narrative
   describes - primary dealers are obligated to bid, which floors bid-to-cover.
   Weak demand raises the clearing yield instead. Stage 2 therefore tracks demand
   as a trend against its own baseline rather than waiting for a "failure" that
   the plumbing prevents.
"""
from __future__ import annotations

# Status vocabulary, ordered by how much of the thesis is corroborated.
FIRING = "firing"        # the stage's condition is met
BUILDING = "building"    # moving toward the condition
NOT_FIRING = "not_firing"
UNKNOWN = "unknown"

STATUS_TONE = {FIRING: "bad", BUILDING: "watch", NOT_FIRING: "good", UNKNOWN: "unknown"}
STATUS_LABEL = {FIRING: "FIRING", BUILDING: "BUILDING", NOT_FIRING: "NOT FIRING",
                UNKNOWN: "NO DATA"}


class Stage(object):
    __slots__ = ("num", "name", "claim", "test", "status", "detail", "metrics", "caveat")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    @property
    def tone(self):
        return STATUS_TONE.get(self.status, "unknown")

    @property
    def label(self):
        return STATUS_LABEL.get(self.status, "NO DATA")

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        d["tone"] = self.tone
        d["label"] = self.label
        return d


def _v(readings, sid):
    r = readings.get(sid)
    return r.value if r is not None else None


def _chg(raw, sid, days):
    """Change in the RAW series over a calendar horizon.

    The scored `momentum`/`trend`/`direction` fields are deliberately not used here.
    They are z-scores measuring whether a move is UNUSUAL for that series, which is
    the right question for regime scoring and the wrong one for this tracker: labour
    participation declining smoothly for years is entirely usual, scores ~0 on both,
    and reads "flat" - while being precisely the multi-year drift the thesis is about.
    A plain horizon comparison answers the question actually being asked.
    """
    series = raw.get(sid) if raw else None
    if series is None:
        return None
    return series.change_over(days)


def _trend_word(delta, flat_band):
    if delta is None:
        return "unknown"
    if delta > flat_band:
        return "rising"
    if delta < -flat_band:
        return "falling"
    return "flat"


# ---------------------------------------------------------------- stage 1

def stage_debt(readings):
    debt = _v(readings, "GFDEBTN")
    pct_gdp = _v(readings, "GFDEGDQ188S")
    interest = _v(readings, "A091RC1Q027SBEA")
    receipts = _v(readings, "FGRECPT")

    metrics = []
    if debt is not None:
        metrics.append(("Total public debt", "$%.2fT" % debt))
    if pct_gdp is not None:
        metrics.append(("Debt as % of GDP", "%.1f%%" % pct_gdp))

    burden = None
    if interest and receipts:
        burden = interest / receipts * 100.0
        metrics.append(("Interest / federal receipts", "%.1f%%" % burden))
        metrics.append(("Annual interest outlay", "$%.2fT" % (interest / 1000.0)))

    if burden is None:
        return Stage(num=1, name="Debt burden", status=UNKNOWN, metrics=metrics,
                     claim="Debt grows until servicing it crowds out the budget.",
                     test="Interest outlays as a share of federal receipts.",
                     detail="Interest or receipts data unavailable.",
                     caveat="Projecting this from the 10-year yield overstates it badly: "
                            "the average rate paid across outstanding debt is well below "
                            "the 10-year and reprices over years.")

    # Thresholds are on the SERVICING BURDEN, not the debt level. A large debt at a
    # low rate is affordable; a smaller one at a high rate may not be.
    if burden >= 30.0:
        status, detail = FIRING, (
            "Interest consumes %.0f%% of federal receipts. Above roughly 30%% the "
            "budget is genuinely constrained by debt service." % burden)
    elif burden >= 20.0:
        status, detail = BUILDING, (
            "Interest consumes %.0f%% of federal receipts and is climbing. Elevated "
            "versus the post-1990s norm, but well short of the level that forces a "
            "financing crisis." % burden)
    else:
        status, detail = NOT_FIRING, (
            "Interest consumes %.0f%% of federal receipts - within historical range."
            % burden)

    return Stage(
        num=1, name="Debt burden", status=status, metrics=metrics, detail=detail,
        claim="Debt grows until servicing it crowds out the rest of the budget.",
        test="Interest outlays as a share of federal receipts (actual, not projected).",
        caveat="Computed from actual outlays. Projecting this from the 10-year yield "
               "overstates it badly: the average rate paid across outstanding debt is "
               "well below the 10-year, and reprices over years as the stack rolls.")


# ---------------------------------------------------------------- stage 2

def stage_funding(readings, auctions, raw=None):
    metrics = []
    foreign = _v(readings, "FDHBFIN")
    if foreign is not None:
        metrics.append(("Debt held by foreign investors", "$%.2fT" % (foreign / 1000.0)))
        delta = _chg(raw, "FDHBFIN", 365)
        if delta is not None:
            metrics.append(("Foreign holdings, 1 year",
                            "%+.0f $B (%s)" % (delta, _trend_word(delta, 50.0))))

    if not auctions:
        return Stage(num=2, name="Market appetite", status=UNKNOWN, metrics=metrics,
                     claim="Buyers walk away; the Treasury cannot fund itself.",
                     test="Bid-to-cover at coupon auctions versus its own baseline.",
                     detail="No auction data available.",
                     caveat="A US auction cannot 'fail' as commonly described - primary "
                            "dealers are obligated to bid, which floors bid-to-cover. "
                            "Weak demand raises the clearing yield instead.")

    metrics.insert(0, ("Latest coupon auction",
                       "%s, bid-to-cover %.2f" % (auctions["latest_term"],
                                                  auctions["latest_btc"])))
    metrics.insert(1, ("Recent avg bid-to-cover", "%.2f" % auctions["recent_avg"]))
    metrics.insert(2, ("Longer baseline", "%.2f" % auctions["baseline_avg"]))

    recent = auctions["recent_avg"]
    delta = auctions["delta"]

    if recent < 2.0:
        status, detail = FIRING, (
            "Recent coupon auctions averaging %.2f bid-to-cover, below the ~2.0 that "
            "marks comfortable demand." % recent)
    elif recent < 2.25 or delta < -0.35:
        status, detail = BUILDING, (
            "Bid-to-cover averaging %.2f, %+.2f versus baseline - demand softening "
            "but still adequately covered." % (recent, delta))
    else:
        status, detail = NOT_FIRING, (
            "Bid-to-cover averaging %.2f against a %.2f baseline. Demand is healthy; "
            "the market is funding the debt without difficulty."
            % (recent, auctions["baseline_avg"]))

    return Stage(
        num=2, name="Market appetite", status=status, metrics=metrics, detail=detail,
        claim="Investors refuse to fund the debt, forcing the Fed to step in.",
        test="Bid-to-cover at coupon auctions versus its own baseline.",
        caveat="A US auction cannot 'fail' as commonly described - primary dealers are "
               "obligated to bid, which floors bid-to-cover. Weak demand raises the "
               "clearing yield instead, so a rising yield-at-auction is the real tell.")


# ---------------------------------------------------------------- stage 3

def stage_fed(readings, raw=None):
    ffr = _v(readings, "DFF")
    ten = _v(readings, "DGS10")
    thirty = _v(readings, "DGS30")

    metrics = []
    if ffr is not None:
        metrics.append(("Fed funds (effective)", "%.2f%%" % ffr))
    if ten is not None:
        metrics.append(("10-year Treasury", "%.2f%%" % ten))
    if thirty is not None:
        metrics.append(("30-year Treasury", "%.2f%%" % thirty))
    bs_90 = _chg(raw, "WALCL", 90)
    bs_365 = _chg(raw, "WALCL", 365)
    bs_series = (raw or {}).get("WALCL")
    if bs_series is not None and bs_series.latest is not None:
        metrics.append(("Fed balance sheet", "$%.2fT" % (bs_series.latest / 1000.0)))
    if bs_90 is not None:
        metrics.append(("Balance sheet, 90 days", "%+.0f $B" % bs_90))
    if bs_365 is not None:
        metrics.append(("Balance sheet, 1 year", "%+.0f $B" % bs_365))

    if bs_90 is None:
        return Stage(num=3, name="Fed monetisation", status=UNKNOWN, metrics=metrics,
                     claim="The Fed monetises the debt and pins yields down.",
                     test="Balance sheet expanding while long yields stay elevated.",
                     detail="Fed balance sheet data unavailable.",
                     caveat="Yield curve control is an announced policy, not something "
                            "inferred from the balance sheet alone.")

    # Expansion means the holdings are actually growing, not merely wobbling.
    expanding = bs_90 > 25.0
    long_high = thirty is not None and ten is not None and thirty > ten

    if expanding and long_high:
        status, detail = FIRING, (
            "Balance sheet expanding while long yields remain elevated - the "
            "signature of monetisation rather than ordinary easing.")
    elif expanding:
        status, detail = BUILDING, (
            "Balance sheet expanding. Watch whether it continues while long yields "
            "stay high, which is what separates monetisation from normal easing.")
    else:
        status, detail = NOT_FIRING, (
            "Balance sheet is not expanding - the Fed is still shrinking or holding "
            "its holdings, the opposite of the monetisation the thesis requires. "
            "Explicit yield curve control would show up here first.")

    return Stage(
        num=3, name="Fed monetisation", status=status, metrics=metrics, detail=detail,
        claim="The Fed becomes buyer of last resort and deploys yield curve control.",
        test="Balance sheet expanding while long-end yields stay elevated.",
        caveat="Yield curve control is an announced policy, not something inferred. "
               "Until the Fed states a yield ceiling, this stage is inference only.")


# ---------------------------------------------------------------- stage 4

def stage_debasement(readings, gold_1y_pct=None):
    m2 = readings.get("WM2NS")
    dollar = readings.get("DTWEXBGS")

    metrics = []
    if m2 is not None and m2.value is not None:
        metrics.append(("M2 money supply, YoY", "%.1f%%" % m2.value))
    if dollar is not None and dollar.value is not None:
        metrics.append(("Broad dollar index", "%.2f" % dollar.value))
        metrics.append(("Dollar trend", dollar.direction or "flat"))
    if gold_1y_pct is not None:
        metrics.append(("Gold, 1 year", "%+.1f%%" % gold_1y_pct))

    m2_yoy = m2.value if m2 is not None else None
    if m2_yoy is None:
        return Stage(num=4, name="Currency debasement", status=UNKNOWN, metrics=metrics,
                     claim="Money supply outruns output; purchasing power falls.",
                     test="M2 growth well above trend, alongside gold strength.",
                     detail="M2 data unavailable.",
                     caveat="The dollar index is relative - it can hold up while every "
                            "currency debases together.")

    gold_hot = gold_1y_pct is not None and gold_1y_pct > 25.0

    # M2 growth is only debasing if it outruns real output plus target inflation,
    # which is roughly 4-5% nominal. Sustained double-digit growth is the signal.
    if m2_yoy >= 10.0 and gold_hot:
        status, detail = FIRING, (
            "M2 growing %.1f%% year over year with gold up %.0f%% - money supply "
            "expanding far faster than output, and hard assets confirming."
            % (m2_yoy, gold_1y_pct))
    elif m2_yoy >= 10.0 or gold_hot:
        status, detail = BUILDING, (
            "Partial confirmation: M2 at %.1f%% YoY%s. One leg of the debasement "
            "signal is present, the other is not."
            % (m2_yoy, (", gold up %.0f%%" % gold_1y_pct) if gold_hot else ""))
    else:
        status, detail = NOT_FIRING, (
            "M2 growing %.1f%% year over year - close to what nominal output growth "
            "absorbs, not the runaway expansion the thesis describes." % m2_yoy)

    return Stage(
        num=4, name="Currency debasement", status=status, metrics=metrics, detail=detail,
        claim="Money printing debases the currency and collapses purchasing power.",
        test="M2 growth well above nominal output growth, confirmed by gold.",
        caveat="The dollar INDEX is a relative measure - it can hold up while every "
               "currency debases together. Gold and M2 test purchasing power directly, "
               "which is why they lead here and the index does not.")


# ---------------------------------------------------------------- stage 5

def stage_endpoints(readings, spy_1y_pct=None, raw=None):
    unrate = _v(readings, "UNRATE")
    part = readings.get("CIVPART")
    part_1y = _chg(raw, "CIVPART", 365)
    u6 = _v(readings, "U6RATE")
    emratio = _v(readings, "EMRATIO")

    metrics = []
    if unrate is not None:
        metrics.append(("Unemployment (U-3)", "%.1f%%" % unrate))
    if u6 is not None:
        metrics.append(("Underemployment (U-6)", "%.1f%%" % u6))
    if part is not None and part.value is not None:
        metrics.append(("Labour force participation", "%.1f%%" % part.value))
    if part_1y is not None:
        metrics.append(("Participation, 1 year",
                        "%+.2fpp (%s)" % (part_1y, _trend_word(part_1y, 0.15))))
    if emratio is not None:
        metrics.append(("Employment-population ratio", "%.1f%%" % emratio))
    if spy_1y_pct is not None:
        metrics.append(("S&P 500, 1 year", "%+.1f%%" % spy_1y_pct))

    if unrate is None or part is None or part.value is None:
        return Stage(num=5, name="Asset melt-up & labour", status=UNKNOWN,
                     metrics=metrics,
                     claim="Cheap money pumps assets and flatters unemployment.",
                     test="Low unemployment alongside falling participation.",
                     detail="Labour data unavailable.",
                     caveat="Participation also falls for demographic reasons; read the "
                            "trend, not the level.")

    # The thesis's specific claim is that unemployment looks good for bad reasons.
    # That is directly checkable: a genuinely tight labour market pulls people IN,
    # so participation rises. Low U-3 with falling participation is the hollow kind.
    # Falling participation over a year, not a z-score: a slow structural decline
    # is exactly what this stage is about and is by definition not "unusual".
    hollow = part_1y is not None and part_1y < -0.15
    low_unrate = unrate < 4.5

    if low_unrate and hollow:
        status, detail = FIRING, (
            "Unemployment at %.1f%% while participation falls to %.1f%%. The headline "
            "is flattered by people leaving the labour force rather than finding work "
            "- exactly the hollow strength the thesis predicts."
            % (unrate, part.value))
    elif low_unrate:
        status, detail = NOT_FIRING, (
            "Unemployment at %.1f%% with participation at %.1f%% and not falling. "
            "The labour market looks genuinely rather than artificially tight."
            % (unrate, part.value))
    else:
        status, detail = BUILDING, (
            "Unemployment at %.1f%% - no longer in the low range the thesis's "
            "'artificial boom' stage describes." % unrate)

    return Stage(
        num=5, name="Asset melt-up & labour", status=status, metrics=metrics,
        detail=detail,
        claim="Liquidity inflates assets and temporarily suppresses unemployment.",
        test="Low unemployment alongside FALLING participation (hollow strength).",
        caveat="Participation also falls for demographic reasons - an ageing "
               "population lowers it regardless of policy. Read the trend, not the level.")


# ---------------------------------------------------------------- assembly

def evaluate(readings, auctions=None, gold_1y_pct=None, spy_1y_pct=None, raw=None):
    """Returns (stages, summary). `raw` is the unscored Series dict, used for the
    plain horizon comparisons this tracker needs."""
    stages = [
        stage_debt(readings),
        stage_funding(readings, auctions, raw),
        stage_fed(readings, raw),
        stage_debasement(readings, gold_1y_pct),
        stage_endpoints(readings, spy_1y_pct, raw),
    ]

    firing = [s for s in stages if s.status == FIRING]
    building = [s for s in stages if s.status == BUILDING]
    known = [s for s in stages if s.status != UNKNOWN]

    if not known:
        verdict = "No data - cannot assess."
    elif len(firing) == len(known):
        verdict = ("Every measurable stage is firing. The chain is corroborated "
                   "end to end.")
    elif not firing:
        verdict = ("No stage is firing. The mechanisms exist, but the conditions "
                   "the thesis requires are not currently present.")
    else:
        verdict = (
            "%d of %d measurable stages firing, %d building. The chain is partially "
            "corroborated - and because the stages are supposed to run in sequence, "
            "which ones are dark matters as much as how many are lit."
            % (len(firing), len(known), len(building)))

    return stages, {
        "firing": len(firing),
        "building": len(building),
        "known": len(known),
        "total": len(stages),
        "verdict": verdict,
    }
