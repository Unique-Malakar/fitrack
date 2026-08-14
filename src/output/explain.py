"""Plain-language meaning for every tracked indicator.

Content, deliberately separated from rendering. A reader looking at "JTSQUR 2.0"
learns nothing; they need what it is, why anyone watches it, and what today's
reading implies. Each entry is:

    sid: (what it is, why it matters, what a HIGH reading means,
          what a LOW reading means)

"High" and "low" are about the number itself, not about whether it is good news -
the pillar axis already handles good-versus-bad, and conflating the two is how you
end up telling someone that high unemployment is a high score.
"""
from __future__ import annotations

INDICATOR_INFO = {
    # ---------------------------------------------------------------- growth
    "GDPNOW": (
        "The Atlanta Fed's running estimate of how fast the economy is growing this quarter.",
        "Official GDP arrives months after the fact. This is the live read, updated as new data lands.",
        "The economy is expanding quickly right now.",
        "Growth is slower than it has been over recent quarters."),
    "CFNAI": (
        "One score combining 85 separate monthly measures of economic activity.",
        "It is built so that zero equals average historical growth, so the sign alone tells you above or below trend.",
        "Activity is running above its long-run trend.",
        "Activity is below trend. Sustained readings near -0.7 have accompanied recessions."),
    "WEI": (
        "A weekly index of real economic activity, built from retail, labour and production data.",
        "Nearly everything else here is monthly or slower. This is the closest thing to a live pulse.",
        "The economy is active right now.",
        "Activity is weakening, and you are seeing it in near real time."),
    "INDPRO": (
        "Total output of factories, mines and utilities, versus a year ago.",
        "Physical production is highly cyclical and tends to turn before the service economy does.",
        "Factories are busy.",
        "Industrial output is shrinking - often an early warning."),
    "JTSJOL": (
        "The number of unfilled jobs employers are advertising.",
        "Labour demand fades here long before it shows up in the unemployment rate.",
        "Employers are competing for workers.",
        "Hiring demand is drying up, which usually precedes rising unemployment."),
    "JTSQUR": (
        "The share of workers who voluntarily quit their job each month.",
        "People only quit when they are confident of finding something better, so this tracks worker confidence directly.",
        "Workers are confident enough to walk away from a job.",
        "Workers are staying put - a quiet signal that they see few alternatives."),
    "PAYEMS": (
        "How many jobs the economy added or lost last month.",
        "The single labour number markets react to most, released the first Friday of each month.",
        "Strong hiring.",
        "Hiring has stalled, or the economy is shedding jobs."),
    "UNRATE": (
        "The share of people who want work and cannot find it.",
        "The most widely watched economic statistic there is, and half of the Fed's dual mandate.",
        "More people are out of work.",
        "A tight labour market - though check participation, since people leaving the workforce also lowers this."),
    "ICSA": (
        "How many people filed for unemployment benefits for the first time, this week.",
        "The fastest labour signal available. It turns before payrolls and before unemployment.",
        "Layoffs are picking up.",
        "Very few layoffs - employers are holding on to staff."),
    "CCSA": (
        "How many people are still collecting unemployment benefits.",
        "Shows whether people who lost jobs are finding new ones, which first-time claims cannot tell you.",
        "The unemployed are struggling to get rehired.",
        "People who lose jobs are finding new ones quickly."),
    "SAHMREALTIME": (
        "How far unemployment has risen above its own recent low.",
        "Crossing 0.50 has coincided with the start of every modern US recession. It confirms rather than predicts.",
        "Labour deterioration has reached recessionary territory.",
        "No recession signal coming from the labour market."),
    "RECPROUSM156N": (
        "A model's estimate of the probability the economy is currently in recession.",
        "Summarises several recession models into one number, smoothed to cut noise.",
        "Recession risk is elevated.",
        "Recession risk is low on this measure."),
    "RSAFS": (
        "What Americans spent at retailers, versus a year ago.",
        "Consumer spending is roughly two-thirds of the US economy, so this is most of the demand side.",
        "Consumers are spending freely.",
        "Consumers are pulling back - the largest single driver of growth is weakening."),
    "UMCSENT": (
        "A survey of how households feel about the economy and their finances.",
        "Sentiment shapes spending, though the link is loose - people often spend despite saying they feel bad.",
        "Households feel good about their situation.",
        "Households are gloomy, which sometimes precedes reduced spending."),
    "HOUST": (
        "The number of new homes on which construction began.",
        "Housing responds faster to interest rates than almost anything else, so it turns early in the cycle.",
        "Builders are confident and building.",
        "Housing construction is contracting."),
    "PERMIT": (
        "Permits issued for new home construction.",
        "Leads housing starts by a month or two, since permits come before ground breaks.",
        "More building is coming.",
        "The construction pipeline is thinning."),
    "MORTGAGE30US": (
        "The typical rate on a 30-year fixed mortgage.",
        "The main channel through which Fed policy reaches ordinary households.",
        "Housing is expensive to finance, which cools demand.",
        "Cheap mortgages support housing and household budgets."),

    # ------------------------------------------------------------- inflation
    "CPIAUCSL": (
        "Headline consumer price inflation versus a year ago.",
        "The inflation number in the news. Includes food and energy, which are volatile.",
        "Prices are rising fast.",
        "Inflation is contained."),
    "CPILFESL": (
        "Inflation excluding food and energy.",
        "Strips out the noisiest items to reveal the underlying trend the Fed actually responds to.",
        "Underlying inflation is hot.",
        "Underlying inflation is cooling."),
    "PCEPI": (
        "The Fed's preferred measure of overall inflation.",
        "The Fed's 2% target is defined on this, not on CPI. It typically runs a little below CPI.",
        "Inflation is above where the Fed wants it.",
        "Inflation is at or below target."),
    "PCEPILFE": (
        "The Fed's preferred inflation measure, excluding food and energy.",
        "This is the single number the Fed is steering toward 2%. Arguably the most consequential figure here.",
        "Core inflation is above target - the Fed has reason to stay restrictive.",
        "Core inflation is at or below target, giving the Fed room to cut."),
    "T5YIE": (
        "What bond markets expect inflation to average over the next five years.",
        "Investors betting real money, rather than economists forecasting. It moves daily.",
        "Markets expect persistent inflation.",
        "Markets expect inflation to be well behaved."),
    "T10YIE": (
        "Market-implied inflation over the next ten years.",
        "A longer view of the same market expectation, less sensitive to today's news.",
        "Long-run inflation expectations are elevated.",
        "Long-run expectations remain contained."),
    "T5YIFR": (
        "Expected inflation for the five years that begin five years from now.",
        "Deliberately excludes everything happening now, making it the purest test of whether long-run expectations stay anchored. Central banks watch it closely.",
        "Expectations are drifting up - the thing central banks fear most.",
        "Long-run expectations remain firmly anchored."),
    "CORESTICKM159SFRBATL": (
        "Inflation in prices that change only occasionally, such as rent and insurance.",
        "Sticky prices move slowly, so when they rise it signals inflation that will persist rather than pass.",
        "Persistent, hard-to-shift inflation.",
        "Even the slow-moving prices are cooling - a genuine improvement."),
    "MEDCPIM158SFRBCLE": (
        "The middle of the distribution of all price changes.",
        "A few extreme items can drag core CPI around. The median cannot be distorted that way.",
        "The typical price is rising quickly.",
        "The typical price is well behaved."),
    "MICH": (
        "What consumers say they expect inflation to be a year from now.",
        "Expectations can become self-fulfilling: people who expect inflation demand higher wages and accept higher prices.",
        "Consumers expect prices to keep climbing.",
        "Consumers expect price rises to slow."),
    "CES0500000003": (
        "Average hourly wages versus a year ago.",
        "Wages feed services inflation, the stickiest kind. The Fed watches this as a persistence signal.",
        "Wage growth may keep services inflation elevated.",
        "Wage pressure is easing."),
    "DCOILWTICO": (
        "The US benchmark price of crude oil.",
        "Energy is an input to almost everything, so oil passes into other prices within months.",
        "Expensive energy pushes up costs across the economy.",
        "Cheap energy takes pressure off inflation and household budgets."),
    "PCOPPUSDM": (
        "The global price of copper.",
        "Copper goes into construction, wiring and machinery everywhere, so its price tracks global industrial demand.",
        "Global industrial demand is strong.",
        "Industrial demand is soft worldwide."),

    # ------------------------------------------------------- rates & policy
    "DGS2": (
        "What the US government pays to borrow for two years.",
        "The tenor most tied to Fed expectations. When it moves sharply, the market has repriced policy.",
        "Markets expect rates to stay high.",
        "Markets expect cuts."),
    "DGS10": (
        "What the US government pays to borrow for ten years.",
        "The benchmark for mortgages, corporate loans and how much investors will pay for future earnings.",
        "Borrowing is expensive across the economy, and high rates weigh on stock valuations.",
        "Cheaper borrowing, supportive of both housing and asset prices."),
    "DGS30": (
        "What the US government pays to borrow for thirty years.",
        "Reflects long-run growth, inflation and fiscal credibility. Less about the Fed, more about confidence.",
        "Investors demand more to fund the government long term.",
        "Long-run confidence is intact."),
    "T10Y2Y": (
        "The ten-year yield minus the two-year yield.",
        "Normally positive. When negative (inverted) it has preceded most recessions - though with long and inconsistent lags, and the 2022-24 inversion proved a false alarm.",
        "A normal, healthy upward-sloping curve.",
        "Inverted. Historically a warning, but check whether expectations or term premium is driving it."),
    "T10Y3M": (
        "The ten-year yield minus the three-month yield.",
        "The version of the curve with the strongest historical recession record.",
        "Normal curve shape.",
        "Inverted - short-term money costs more than long-term."),
    "THREEFYTP10": (
        "The extra yield investors demand simply for holding long bonds.",
        "Separates a yield rise driven by fiscal or supply worry from one driven by growth optimism. Same yield, very different meaning.",
        "Investors want compensation for long-term risk - often a fiscal concern signal.",
        "Investors are relaxed about holding long-dated debt."),
    "DFF": (
        "The Federal Reserve's policy interest rate.",
        "The anchor from which nearly every other borrowing cost is priced.",
        "Policy is restrictive - deliberately slowing the economy.",
        "Policy is accommodative - deliberately supporting it."),
    "DFII10": (
        "The ten-year yield after stripping out expected inflation.",
        "The true cost of money. It drives the valuation of anything whose payoff is far in the future, which includes growth stocks.",
        "Real borrowing costs are high, which pressures long-duration assets.",
        "Real rates are low or negative, which inflates asset prices."),
    "NFCI": (
        "A composite of over 100 measures of how easy money is to obtain.",
        "Built so zero equals average conditions. Answers 'are conditions actually tightening?' better than any single rate.",
        "Financial conditions are tighter than normal.",
        "Conditions are looser than normal - money is easy to come by."),
    "ANFCI": (
        "The same conditions index, adjusted for where the economy is in the cycle.",
        "Isolates whether conditions are unusual given current growth and inflation, rather than just unusual.",
        "Conditions are tighter than the state of the economy would justify.",
        "Conditions are looser than the economy alone would explain."),
    "STLFSI4": (
        "A composite index of stress in financial markets.",
        "Another zero-centred read on plumbing, useful as a cross-check on NFCI.",
        "Market stress is above normal.",
        "Markets are calm."),

    # ------------------------------------------------------ credit & liquidity
    "BAA10Y": (
        "The extra yield on medium-quality corporate bonds over government bonds.",
        "Widens when lenders start worrying about being repaid. Decades of history, unlike the other spreads here.",
        "Lenders are demanding much more to lend to companies - a genuine stress signal.",
        "Lenders are relaxed about corporate credit risk."),
    "BAMLC0A0CM": (
        "The extra yield on investment-grade corporate bonds over Treasuries.",
        "When stress reaches high-quality borrowers, it is no longer contained to the risky end.",
        "Stress has spread to the safest corporate borrowers.",
        "Blue-chip companies borrow near government rates."),
    "BAMLH0A0HYM2": (
        "The extra yield on junk bonds over Treasuries.",
        "The first place credit stress appears. Credit markets price default risk more directly than stock markets do, which makes this a useful independent warning.",
        "Lenders are pricing real default risk - watch this closely.",
        "Risky borrowers can raise money cheaply."),
    "VIXCLS": (
        "How much movement the options market expects in the S&P over the next month.",
        "Effectively the price of insurance against a fall. It spikes during panic and drifts low during calm.",
        "Fear is elevated. Whether that is a buying opportunity depends on whether credit agrees.",
        "Markets are complacent - which is itself worth noting."),
    "WM2NS": (
        "The total amount of money in the economy, versus a year ago.",
        "Money growing much faster than output is the textbook definition of currency debasement.",
        "Money supply is expanding quickly.",
        "Money supply is flat or shrinking, which drains support from asset prices."),
    "WALCL": (
        "The weekly change in what the Federal Reserve owns.",
        "Growing means the Fed is injecting money; shrinking means withdrawing it. This is quantitative easing or tightening, made visible.",
        "The Fed is adding liquidity.",
        "The Fed is withdrawing liquidity."),
    "RRPONTSYD": (
        "Cash that institutions park at the Fed overnight rather than lending it out.",
        "A large balance means money is sitting idle instead of circulating.",
        "A lot of cash is parked rather than working.",
        "Cash is deployed in markets rather than sitting at the Fed."),
    "DRTSCILM": (
        "The share of banks making it harder for businesses to borrow.",
        "Even when the Fed cuts, easing does not reach the economy if banks refuse to lend. This is the transmission check.",
        "Banks are restricting credit - Fed easing may not be reaching borrowers.",
        "Banks are willing to lend."),
    "DRCCLACBS": (
        "The share of credit card balances where payments are behind.",
        "Direct evidence of household financial stress. Corporate spreads say nothing about whether ordinary people are coping.",
        "Households are falling behind on debts.",
        "Households are managing their debts comfortably."),
    "NFCICREDIT": (
        "The credit-specific slice of the financial conditions index.",
        "Isolates lending conditions from the broader index, which also captures equity and volatility effects.",
        "Credit specifically is tightening.",
        "Credit is readily available."),

    # ------------------------------------------------------------- market
    "SP500": (
        "The level of the S&P 500 index.",
        "The reference point for US equities.",
        "Near the top of its recent range.",
        "Near the bottom of its recent range."),
    "SPY_TREND": (
        "How much the S&P 500 has moved over the past month.",
        "Recent direction, rather than the absolute level.",
        "The market has been rising.",
        "The market has been falling."),
    "RSP_SPY": (
        "How the average S&P company performed versus the index itself.",
        "The index is dominated by its biggest members. If it rises while the average share falls, only a handful of names are carrying it - which is fragile.",
        "The rise is broad, with most companies participating. The healthiest configuration.",
        "Only the largest companies are driving the index. Narrow rallies break more easily."),

    # ------------------------------------------------------------- global
    "DTWEXBGS": (
        "The dollar against a broad basket of trading partners' currencies.",
        "A strong dollar tightens conditions worldwide and squeezes US exporters and emerging markets.",
        "A strong dollar, which pressures commodities and emerging markets.",
        "A weak dollar, which tends to support commodities and foreign earnings."),
    "DEXJPUS": (
        "How many yen one dollar buys.",
        "Japan's cheap money funds investments worldwide. Sharp moves force those trades to unwind, causing selling far from Japan - as in August 2024.",
        "The yen is weak, which sustains the global carry trade.",
        "The yen is strengthening sharply, which can force a global unwind."),

    # --------------------------------------------------------- debt chain
    "GFDEBTN": (
        "The total the US government owes.",
        "The headline debt figure. On its own it says little - what matters is the cost of servicing it.",
        "Debt is at a record.",
        "Debt has fallen, which is historically rare."),
    "GFDEGDQ188S": (
        "Government debt measured against the size of the economy.",
        "More meaningful than the raw total, because a bigger economy can carry more debt.",
        "Debt is large relative to the economy.",
        "Debt is moderate relative to the economy."),
    "A091RC1Q027SBEA": (
        "What the government pays in interest each year.",
        "This is the number that actually constrains a budget - not the debt total.",
        "Interest costs are consuming a growing share of the budget.",
        "Debt service is comfortable."),
    "FGRECPT": (
        "Total federal government revenue.",
        "The denominator for judging whether interest costs are affordable.",
        "Revenue is strong.",
        "Revenue is weak, which makes fixed interest costs bite harder."),
    "FDHBFIN": (
        "How much US government debt foreign investors hold.",
        "A sustained decline would suggest foreign buyers are stepping back - one version of the debt-crisis thesis.",
        "Foreign appetite for US debt is strong.",
        "Foreign holdings are shrinking - worth watching, though it has many benign explanations."),
    "CIVPART": (
        "The share of adults working or actively looking for work.",
        "Unemployment can fall simply because people stop looking. This is how you tell a genuinely strong job market from a hollow one.",
        "People are entering the workforce - a sign of genuine strength.",
        "People are leaving the workforce, which flatters the unemployment rate without any real improvement."),
    "U6RATE": (
        "A broader unemployment measure including part-timers who want full-time work and people who have given up looking.",
        "Captures underemployment the headline rate misses.",
        "Significant hidden slack in the labour market.",
        "Little hidden slack - the job market is genuinely tight."),
    "EMRATIO": (
        "The share of the adult population actually employed.",
        "Immune to the definitional games around who counts as 'looking for work'.",
        "A large share of people are working.",
        "Fewer people are working, regardless of what the unemployment rate says."),
    "PSAVERT": (
        "The share of income households save rather than spend.",
        "Genuinely ambiguous: it rises both when people are prudent and when they are frightened.",
        "Households are saving more, which supports future spending but reduces it today.",
        "Households are saving little, leaving no cushion if incomes fall."),
}


def _fmt(v):
    """Thresholds read better as 0.50 than 0.5."""
    return ("%g" % v) if float(v) == int(v) else ("%.2f" % v)


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def describe(sid, percentile, direction, value=None, anchor=None, anchor_note=None,
             anchor_signal="above"):
    """One sentence linking today's reading to what it implies.

    Combines where the value sits in its own history with which way it is moving,
    then hands off to the indicator's own high/low meaning.

    Percentile alone is not enough for a series with a STRUCTURAL threshold. The
    Sahm Rule at 0.41 is at the top of its own three-year range but still below the
    0.50 line that defines the signal, and reporting "reached recessionary
    territory" there is simply false. Where an anchor exists, whether it has been
    crossed overrides the percentile language.
    """
    info = INDICATOR_INFO.get(sid)
    if info is None:
        return ""
    _, _, high, low = info

    if anchor is not None and value is not None:
        # Which side counts as "signalling" differs per series and cannot be derived
        # from polarity: the Sahm Rule fires ABOVE 0.50, a yield curve fires BELOW 0,
        # and both are polarity -1.
        fired = value >= anchor if anchor_signal == "above" else value <= anchor
        meaning = high if anchor_signal == "above" else low
        note = (" (%s)" % anchor_note) if anchor_note else ""
        side = "Above" if anchor_signal == "above" else "Below"
        near = "approaching" if anchor_signal == "above" else "approaching from above"

        if fired:
            return ("%s its %s threshold%s. %s" % (side, _fmt(anchor), note, meaning)).strip()
        toward = (percentile is not None
                  and ((anchor_signal == "above" and percentile >= 65)
                       or (anchor_signal == "below" and percentile <= 35)))
        if toward:
            return ("Not yet across its %s threshold%s, but %s it."
                    % (_fmt(anchor), note, near)).strip()
        return ("Comfortably clear of its %s threshold%s - not signalling."
                % (_fmt(anchor), note)).strip()

    if percentile is None:
        band, meaning = "", ""
    elif percentile >= 85:
        band, meaning = "Near the top of its 3-year range.", high
    elif percentile >= 65:
        band, meaning = "On the high side of its 3-year range.", high
    elif percentile <= 15:
        band, meaning = "Near the bottom of its 3-year range.", low
    elif percentile <= 35:
        band, meaning = "On the low side of its 3-year range.", low
    else:
        band, meaning = "Around the middle of its 3-year range.", ""

    move = {"rising": " Still climbing.", "falling": " Still falling."}.get(direction, "")
    return (band + " " + meaning + move).strip()


def tooltip(sid):
    """What it is, and why anyone watches it."""
    info = INDICATOR_INFO.get(sid)
    if info is None:
        return ""
    what, why, _, _ = info
    return "%s  —  %s" % (what, why)
