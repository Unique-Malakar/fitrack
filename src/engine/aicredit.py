"""The AI / private-credit thesis, as a falsifiable tracker.

The argument: the AI buildout is funded by debt that banks would not write, so it
has moved into private credit; private credit has been absorbed by life insurers;
and if the data centres do not earn what they were financed to earn, the losses
land somewhere unprepared.

The mechanisms are real and the exposures are measurable. The argument as usually
told is not testable - it names a crisis window, and until that window passes,
nothing counts as evidence against it. So each stage below carries a condition that
can read NOT FIRING, and the parts that genuinely cannot be measured are listed as
such rather than quietly omitted.

What cannot be tested here, and why:

  * HYPERSCALER CAPEX AGAINST CASH FLOW. The load-bearing claim. Company filings
    are not free in machine-readable form, so data-centre landlords stand in as a
    weak proxy. Labelled as weak wherever it appears.
  * THE 2027-28 WINDOW. A claim about the future. The maturity wall and the
    depreciation shock are projections; they can be waited for, not observed.
  * THE REGULATORY RECLASSIFICATION. Asserted in the source document and not
    verified here.
  * THE BAILOUT CASCADE. Hypothetical by construction - it describes what would
    happen after a failure that has not happened.

No individual company is tracked. The thesis names specific asset managers and
insurers, but a dashboard row implying a named firm is systemically dangerous is a
strong public claim resting on ownership assertions this system cannot verify.
Sector-level gauges show the same stress without naming anyone.
"""
from __future__ import annotations

FIRING, BUILDING, NOT_FIRING, UNKNOWN = "firing", "building", "not_firing", "unknown"

STATUS_TONE = {FIRING: "bad", BUILDING: "watch", NOT_FIRING: "good", UNKNOWN: "unknown"}
STATUS_LABEL = {FIRING: "FIRING", BUILDING: "BUILDING", NOT_FIRING: "NOT FIRING",
                UNKNOWN: "NO DATA"}

NOT_MEASURABLE = [
    ("Hyperscaler capex versus cash flow",
     "The central claim - that the buildout costs more than the tech giants earn. "
     "Company filings are not available free in machine-readable form. Data-centre "
     "landlords are shown instead, which is a weak substitute."),
    ("The 2027-28 crisis window",
     "A projection about the future. The maturity wall and the accounting shift can "
     "be waited for, but not measured today."),
    ("The regulatory reclassification of data-centre loans",
     "Asserted in the source material. Not independently verified here."),
    ("The bailout cascade through state guarantee funds",
     "Describes what would follow a failure that has not occurred, so there is "
     "nothing to observe."),
]


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


def _v(readings, sid):
    r = readings.get(sid)
    return r.value if r is not None else None


def _rel(gauges, a, b, days=63):
    """Percentage-point performance of a against b over `days` sessions."""
    qa, qb = gauges.get(a), gauges.get(b)
    if not qa or not qb:
        return None
    ra, rb = qa.get("ret_%d" % days), qb.get("ret_%d" % days)
    if ra is None or rb is None:
        return None
    return ra - rb


# ------------------------------------------------------------------ stage 1

def stage_borrowing(readings, gauges):
    metrics = []
    debt = _v(readings, "NCBDBIQ027S")
    ig = _v(readings, "BAMLC0A0CM")
    if debt is not None:
        metrics.append(("Corporate debt securities", "$%.1fT" % (debt / 1000.0)))
    if ig is not None:
        metrics.append(("Investment-grade spread", "%.0f bps" % ig))
    dc = _rel(gauges, "EQIX", "XLF")
    if dc is not None:
        metrics.append(("Data-centre REITs vs financials, 3m", "%+.1fpp" % dc))

    if debt is None:
        return Stage(num=1, name="Debt funding the buildout", status=UNKNOWN,
                     metrics=metrics, detail="Corporate debt data unavailable.",
                     claim="The buildout is financed with debt rather than earnings.",
                     test="Corporate borrowing and the price of investment-grade credit.",
                     caveat="No free source isolates AI-linked debt, so this is total "
                            "corporate borrowing - it cannot confirm the AI part.")

    # Widening investment-grade spreads mean lenders are charging more to the safest
    # borrowers, which is where strain would first become visible in public markets.
    if ig is not None and ig >= 140:
        status, detail = FIRING, (
            "Investment-grade spreads at %.0fbps - lenders are charging noticeably "
            "more even to strong borrowers." % ig)
    elif ig is not None and ig >= 110:
        status, detail = BUILDING, (
            "Investment-grade spreads at %.0fbps, above the calm range but not "
            "distressed." % ig)
    else:
        status, detail = NOT_FIRING, (
            "Investment-grade credit is priced calmly%s. Companies are borrowing "
            "cheaply, which is the opposite of a funding squeeze."
            % ("" if ig is None else " at %.0fbps" % ig))
        if dc is not None and dc <= -8.0:
            # The nearest available read on the buildout itself. It does not change
            # the credit verdict, but burying it in a table would be misleading.
            status = BUILDING
            detail += (" Data-centre landlords have lagged financials by %.0f "
                       "percentage points over three months, though - the closest "
                       "read available on the buildout, and it is weak." % abs(dc))

    return Stage(
        num=1, name="Debt funding the buildout", status=status, metrics=metrics,
        detail=detail,
        claim="The AI buildout costs more than its sponsors earn, so it is financed "
              "with borrowed money.",
        test="Corporate borrowing levels and what investment-grade credit costs.",
        caveat="This is TOTAL corporate debt. Nothing free separates AI-linked "
               "borrowing from the rest, so this can show the pool growing but never "
               "confirm what it was spent on.")


# ------------------------------------------------------------------ stage 2

def stage_private_credit(gauges):
    metrics = []
    gap = _rel(gauges, "BIZD", "HYG")
    if gauges.get("BIZD"):
        metrics.append(("Listed private-credit funds, 3m",
                        "%+.1f%%" % gauges["BIZD"].get("ret_63", 0)))
    if gauges.get("HYG"):
        metrics.append(("High-yield bonds, 3m",
                        "%+.1f%%" % gauges["HYG"].get("ret_63", 0)))
    if gap is not None:
        metrics.append(("Difference", "%+.1fpp" % gap))

    if gap is None:
        return Stage(num=2, name="Private credit under strain", status=UNKNOWN,
                     metrics=metrics, detail="Price data unavailable.",
                     claim="Private credit has absorbed lending banks would not do.",
                     test="Listed private-credit funds against public junk bonds.",
                     caveat="Only the listed slice of private credit is priced daily. "
                            "Most of it never trades, and unmarked losses are exactly "
                            "what the thesis is about.")

    # Underperforming public junk credit means the market is pricing something wrong
    # with private credit specifically, not with credit generally.
    if gap <= -6.0:
        status, detail = FIRING, (
            "Listed private-credit funds have lagged public junk bonds by %.1f "
            "percentage points over three months. The market is pricing a problem "
            "specific to private credit rather than credit in general." % abs(gap))
    elif gap <= -2.5:
        status, detail = BUILDING, (
            "Private-credit funds trailing public junk bonds by %.1fpp - worth "
            "watching, not yet decisive." % abs(gap))
    elif gap >= 2.5:
        status, detail = NOT_FIRING, (
            "Private-credit funds have OUTPERFORMED public junk bonds by %.1f "
            "percentage points over three months. Whatever the market is worried "
            "about, it is not this." % gap)
    else:
        status, detail = NOT_FIRING, (
            "Private-credit funds are tracking public junk bonds within %.1fpp. "
            "The market is not singling private credit out." % abs(gap))

    return Stage(
        num=2, name="Private credit under strain", status=status, metrics=metrics,
        detail=detail,
        claim="Lending banks would not do has moved into private credit, where it is "
              "less visible and less regulated.",
        test="Listed private-credit funds measured against public high-yield bonds.",
        caveat="Only the LISTED slice trades daily. The bulk of private credit is "
               "valued by its own managers and may not move at all - which is "
               "precisely the concern, and also the reason this test is partial.")


# ------------------------------------------------------------------ stage 3

def stage_insurers(readings, gauges):
    metrics = []
    bonds = _v(readings, "BOGZ1FL543063005Q")
    total = _v(readings, "BOGZ1FL544090005Q")
    share = (bonds / total * 100.0) if (bonds and total) else None

    if share is not None:
        metrics.append(("Life insurers' corporate bonds", "$%.1fT" % (bonds / 1000.0)))
        metrics.append(("As a share of their total assets", "%.1f%%" % share))
    rel = _rel(gauges, "KIE", "XLF")
    if rel is not None:
        metrics.append(("Insurance sector vs financials, 3m", "%+.1fpp" % rel))

    if share is None:
        return Stage(num=3, name="Insurers holding the risk", status=UNKNOWN,
                     metrics=metrics, detail="Federal Reserve holdings data unavailable.",
                     claim="Insurers have taken this credit onto their balance sheets.",
                     test="Corporate bonds as a share of life insurers' total assets.",
                     caveat="Federal Reserve data does not break out private credit "
                            "specifically, and arrives quarterly with a lag.")

    stressed = rel is not None and rel <= -5.0
    if share >= 45.0 and stressed:
        status, detail = FIRING, (
            "Corporate credit is %.0f%% of life insurers' assets and the insurance "
            "sector is underperforming financials by %.1fpp. Concentration plus market "
            "concern together." % (share, abs(rel)))
    elif share >= 40.0 or stressed:
        status, detail = BUILDING, (
            "Corporate credit is %.0f%% of life insurers' assets%s." % (
                share,
                ", and the sector is lagging financials" if stressed else
                " - elevated, though markets are not reacting"))
    else:
        status, detail = NOT_FIRING, (
            "Corporate credit is %.0f%% of life insurers' assets, within the range "
            "the industry has long carried, and equity markets are not signalling "
            "concern." % share)

    return Stage(
        num=3, name="Insurers holding the risk", status=status, metrics=metrics,
        detail=detail,
        claim="Insurers have used policyholders' premiums to buy this credit, putting "
              "ordinary savers behind it.",
        test="Corporate bonds as a share of life insurers' total assets, from Federal "
             "Reserve data, cross-checked against insurance sector share prices.",
        caveat="Insurers have ALWAYS held large amounts of corporate credit - it is "
               "their normal business. The question is whether the mix has shifted "
               "toward illiquid private lending, and Fed data does not break that out.")


# ------------------------------------------------------------------ stage 4

def stage_stress(readings):
    metrics = []
    cre = _v(readings, "DRCRELEXFACBS")
    biz = _v(readings, "DRBLACBS")
    hy = _v(readings, "BAMLH0A0HYM2")
    sloos = _v(readings, "DRTSCILM")
    for label, value, unit in (("Commercial property delinquency", cre, "%"),
                               ("Business loan delinquency", biz, "%"),
                               ("High-yield spread", hy, "bps"),
                               ("Banks tightening lending", sloos, "net %")):
        if value is not None:
            metrics.append((label, ("%.2f%s" % (value, unit)) if unit != "bps"
                            else "%.0f bps" % value))

    if cre is None and biz is None:
        return Stage(num=4, name="Losses actually appearing", status=UNKNOWN,
                     metrics=metrics, detail="Delinquency data unavailable.",
                     claim="The loans stop performing.",
                     test="Commercial property and business loan delinquency rates.",
                     caveat="Delinquencies are quarterly and lag by months. They "
                            "confirm damage rather than warn of it.")

    hot = [v for v in (cre, biz) if v is not None]
    rising_hy = hy is not None and hy >= 450

    if any(v >= 3.0 for v in hot) or rising_hy:
        status, detail = FIRING, (
            "Borrowers are failing to pay: commercial property delinquency %.2f%%, "
            "business loans %.2f%%.%s" % (
                cre or 0, biz or 0,
                " High-yield spreads confirm at %.0fbps." % hy if rising_hy else ""))
    elif any(v >= 2.0 for v in hot):
        status, detail = BUILDING, (
            "Delinquencies are rising but remain historically moderate: commercial "
            "property %.2f%%, business loans %.2f%%." % (cre or 0, biz or 0))
    else:
        status, detail = NOT_FIRING, (
            "Borrowers are paying: commercial property delinquency %.2f%%, business "
            "loans %.2f%%. Whatever the risk, it has not turned into losses."
            % (cre or 0, biz or 0))

    return Stage(
        num=4, name="Losses actually appearing", status=status, metrics=metrics,
        detail=detail,
        claim="Data centre revenues disappoint, the loans default, and losses land on "
              "whoever is holding them.",
        test="Commercial property and business loan delinquency rates, with credit "
             "spreads as a cross-check.",
        caveat="Delinquency data is quarterly and lags by months, so this stage "
               "confirms damage rather than warning of it. Also, 'extend and pretend' "
               "restructuring can keep loans looking current well past the point of "
               "trouble.")


# ------------------------------------------------------------------ stage 5

def stage_japan(readings, raw=None):
    metrics = []
    jgb = _v(readings, "IRLTLT01JPM156N")
    jpy = _v(readings, "DEXJPUS")
    if jgb is not None:
        metrics.append(("Japan 10-year yield", "%.2f%%" % jgb))
    if jpy is not None:
        metrics.append(("Yen per dollar", "%.2f" % jpy))
    change = None
    if raw is not None and raw.get("IRLTLT01JPM156N") is not None:
        change = raw["IRLTLT01JPM156N"].change_over(365)
        if change is not None:
            metrics.append(("Japan yield, 1 year", "%+.2fpp" % change))

    if jgb is None:
        return Stage(num=5, name="The Japan channel", status=UNKNOWN, metrics=metrics,
                     detail="Japanese yield data unavailable.",
                     claim="Rising Japanese yields pull capital home, lifting US rates.",
                     test="Japan's 10-year government bond yield and the yen.",
                     caveat="A channel, not a trigger. It affects the speed of a "
                            "dislocation rather than causing one.")

    if change is not None and change >= 0.75:
        status, detail = FIRING, (
            "Japanese 10-year yields at %.2f%%, up %.2f points over the year. The "
            "incentive for Japanese capital to stay in foreign bonds is weakening."
            % (jgb, change))
    elif jgb >= 2.0:
        status, detail = BUILDING, (
            "Japanese yields at %.2f%% - high by the standards of the last two "
            "decades, though not moving sharply." % jgb)
    else:
        status, detail = NOT_FIRING, (
            "Japanese yields at %.2f%% remain low, so the incentive for that capital "
            "to come home is limited." % jgb)

    return Stage(
        num=5, name="The Japan channel", status=status, metrics=metrics, detail=detail,
        claim="Japanese investors repatriating capital would push US borrowing costs "
              "up at the worst moment.",
        test="Japan's 10-year government bond yield and the yen exchange rate.",
        caveat="This is an amplifier, not a cause. It would make a dislocation faster "
               "and sharper; it does not create one.")


def evaluate(readings, gauges=None, raw=None):
    gauges = gauges or {}
    stages = [
        stage_borrowing(readings, gauges),
        stage_private_credit(gauges),
        stage_insurers(readings, gauges),
        stage_stress(readings),
        stage_japan(readings, raw),
    ]

    firing = [s for s in stages if s.status == FIRING]
    building = [s for s in stages if s.status == BUILDING]
    known = [s for s in stages if s.status != UNKNOWN]

    if not known:
        verdict = "No data - cannot assess."
    elif not firing and not building:
        verdict = ("Nothing is firing. The exposures described are real and "
                   "measurable, but none of the conditions the argument requires is "
                   "present right now.")
    elif not firing:
        verdict = ("%d of %d measurable stages are building, none firing. Pressure "
                   "without damage." % (len(building), len(known)))
    else:
        verdict = ("%d of %d measurable stages firing, %d building."
                   % (len(firing), len(known), len(building)))

    return stages, {"firing": len(firing), "building": len(building),
                    "known": len(known), "total": len(stages), "verdict": verdict}
