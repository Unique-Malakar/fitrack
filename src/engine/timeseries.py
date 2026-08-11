"""The one data structure the whole pipeline passes around.

A Series is a date-ordered pair of parallel lists (ascending, no gaps in the sense
that every entry has a real value - missing observations are dropped at parse time).
Transforms produce new Series so the raw pull stays intact for the history store.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime


def parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


class Series(object):
    __slots__ = ("sid", "dates", "values")

    def __init__(self, sid, dates, values):
        self.sid = sid
        self.dates = list(dates)
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def __bool__(self):
        return bool(self.values)

    @property
    def latest(self):
        return self.values[-1] if self.values else None

    @property
    def latest_date(self):
        return self.dates[-1] if self.dates else None

    def scaled(self, factor):
        if factor in (None, 1):
            return self
        return Series(self.sid, self.dates, [v * factor for v in self.values])

    def tail(self, n):
        if n <= 0 or n >= len(self.values):
            return self
        return Series(self.sid, self.dates[-n:], self.values[-n:])

    def since(self, cutoff):
        keep = [i for i, d in enumerate(self.dates) if d >= cutoff]
        if not keep:
            return Series(self.sid, [], [])
        i = keep[0]
        return Series(self.sid, self.dates[i:], self.values[i:])

    # -- transforms -------------------------------------------------------

    def diff(self, periods=1):
        if len(self.values) <= periods:
            return Series(self.sid, [], [])
        out = [self.values[i] - self.values[i - periods] for i in range(periods, len(self.values))]
        return Series(self.sid, self.dates[periods:], out)

    def pct_change(self, periods=1):
        if len(self.values) <= periods:
            return Series(self.sid, [], [])
        dates, out = [], []
        for i in range(periods, len(self.values)):
            prev = self.values[i - periods]
            if prev == 0:
                continue
            dates.append(self.dates[i])
            out.append((self.values[i] - prev) / abs(prev) * 100.0)
        return Series(self.sid, dates, out)

    def yoy_pct(self, freq):
        """Year-over-year percent change, using the period count implied by frequency."""
        periods = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4}.get(freq, 12)
        return self.pct_change(periods)

    def moving_average(self, window):
        if len(self.values) < window or window < 1:
            return Series(self.sid, [], [])
        out = []
        run = sum(self.values[:window])
        out.append(run / window)
        for i in range(window, len(self.values)):
            run += self.values[i] - self.values[i - window]
            out.append(run / window)
        return Series(self.sid, self.dates[window - 1:], out)

    # -- statistics -------------------------------------------------------

    def percentile_of(self, value):
        """Percentile rank (0-100) of `value` within this series. Midpoint rule for ties."""
        if not self.values:
            return None
        below = sum(1 for v in self.values if v < value)
        equal = sum(1 for v in self.values if v == value)
        return (below + 0.5 * equal) / len(self.values) * 100.0

    def change_sigma(self):
        """Standard deviation of period-over-period changes; the series' own volatility unit."""
        d = self.diff(1)
        if len(d) < 2:
            return None
        try:
            sigma = statistics.pstdev(d.values)
        except statistics.StatisticsError:
            return None
        return sigma if sigma > 0 else None

    def ma_gap(self, short_window, long_window):
        """Series of (short MA - long MA), aligned on the long MA's dates.

        This is the trend measure. It must be normalised against its OWN historical
        spread rather than against single-period change volatility: the gap reflects
        a multi-period trend, so dividing it by a one-period sigma systematically
        understates every move and makes the measure incomparable across series
        with different noise profiles.
        """
        short = self.moving_average(short_window)
        long_ = self.moving_average(long_window)
        if not short or not long_:
            return Series(self.sid, [], [])
        lookup = dict(zip(short.dates, short.values))
        dates, values = [], []
        for d, lv in zip(long_.dates, long_.values):
            sv = lookup.get(d)
            if sv is not None:
                dates.append(d)
                values.append(sv - lv)
        return Series(self.sid, dates, values)

    def ma_gap_z(self, short_window, long_window):
        """How unusual the current short-vs-long trend is, in its own standard deviations."""
        gap = self.ma_gap(short_window, long_window)
        if len(gap) < 8:
            return None
        try:
            sigma = statistics.pstdev(gap.values)
            mean = statistics.fmean(gap.values)
        except statistics.StatisticsError:
            return None
        # A guard of `sigma <= 0` is not enough: a series with a mathematically
        # constant gap (a perfect ramp) leaves floating-point residue on the order
        # of 1e-16, and dividing by that amplifies rounding error into a maximal
        # score. Require the spread to be meaningful relative to the data's scale.
        if not _is_significant(sigma, gap.values, mean):
            return None
        return (gap.latest - mean) / sigma

    def change_z(self, periods):
        """The latest n-period change, z-scored against all historical n-period changes.

        Complements ma_gap_z: that measures short-term ACCELERATION, this measures
        sustained medium-term DIRECTION. A series grinding steadily to a multi-year
        high scores ~0 on the former and high on the latter, and the difference
        matters - a slow grind and a sharp spike are different signals.
        """
        d = self.diff(periods)
        if len(d) < 8:
            return None
        try:
            sigma = statistics.pstdev(d.values)
            mean = statistics.fmean(d.values)
        except statistics.StatisticsError:
            return None
        if not _is_significant(sigma, d.values, mean):
            return None
        return (d.latest - mean) / sigma

    def change_over(self, days):
        """Absolute change vs the last observation at least `days` calendar days back.

        Calendar-based rather than positional so it behaves correctly for series that
        only publish weekly or monthly, and for holidays in daily series.
        """
        if len(self.values) < 2:
            return None
        target = self.dates[-1] - _timedelta(days)
        prior = None
        for d, v in zip(self.dates[:-1], self.values[:-1]):
            if d <= target:
                prior = v
            else:
                break
        if prior is None:
            return None
        return self.values[-1] - prior


def _is_significant(sigma, values, mean):
    """True when `sigma` reflects real variation rather than floating-point residue."""
    if not sigma or sigma <= 0:
        return False
    scale = max([abs(v) for v in values] + [abs(mean), 1.0])
    return sigma > 1e-9 * scale


def _timedelta(days):
    from datetime import timedelta
    return timedelta(days=days)


def apply_transform(series, transform, freq):
    if transform == "diff":
        return series.diff(1)
    if transform == "mom_pct":
        return series.pct_change(1)
    if transform == "yoy_pct":
        return series.yoy_pct(freq)
    return series
