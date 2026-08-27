"""Price cards with a six-month chart, for crypto and metals.

A sparkline is enough to say "up or down" but not enough to say "from where" - and
for assets people hold as a hedge rather than a trade, the shape of the last six
months is the interesting part. So these get a proper area chart with a labelled
range, rather than the bare line used in the indicator drill-down.

Colour follows the heatmap: green up, red down, judged over the window shown rather
than over the last session, so the chart and its colour agree.
"""
from __future__ import annotations

from .email_builder import _esc

UP, DOWN = "#16a34a", "#e5484d"


def _series_chart(values, width=260, height=68, pad=4):
    """Area chart over the window, with the last point marked."""
    if not values or len(values) < 3:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    step = (width - 2 * pad) / (n - 1)
    rising = values[-1] >= values[0]
    color = UP if rising else DOWN

    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = height - pad - (v - lo) / span * (height - 2 * pad)
        pts.append((x, y))

    line = " ".join("%.1f,%.1f" % p for p in pts)
    area = "%s %.1f,%.1f %.1f,%.1f" % (line, pts[-1][0], height, pts[0][0], height)
    gid = "g%d%s" % (n, color.lstrip("#"))

    return (
        '<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;" role="img" '
        'aria-label="six month price history">'
        '<defs><linearGradient id="%s" x1="0" x2="0" y1="0" y2="1">'
        '<stop offset="0%%" stop-color="%s" stop-opacity="0.28"/>'
        '<stop offset="100%%" stop-color="%s" stop-opacity="0.02"/></linearGradient></defs>'
        '<polygon points="%s" fill="url(#%s)"/>'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        '<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/></svg>'
        % (width, height, gid, color, color, area, gid, line, color,
           pts[-1][0], pts[-1][1], color))


def _fmt(value, decimals):
    if value is None:
        return "-"
    return "{:,.{d}f}".format(value, d=decimals)


def cards(section_title, spec, data, note=""):
    """One block of asset cards. `data` maps symbol -> {price, chg_1d, chg_6m, history}."""
    rows = [(s, data.get(s["symbol"])) for s in spec]
    rows = [(s, d) for s, d in rows if d]
    if not rows:
        return ""

    P = ['<div class="card">', '<h2>%s</h2>' % _esc(section_title), '<div class="acards">']
    for spec_row, d in rows:
        chg = d.get("chg_1d")
        color = UP if (chg or 0) > 0 else DOWN if (chg or 0) < 0 else "var(--muted)"
        six = d.get("chg_6m")
        P.append('<div class="acard">')
        P.append('<div class="ac-top">'
                 '<span class="ac-name">%s</span>'
                 '<span class="ac-unit">%s</span></div>'
                 % (_esc(spec_row["label"]), _esc(spec_row.get("unit", ""))))
        P.append('<div class="ac-price">%s</div>'
                 % _fmt(d.get("price"), spec_row.get("decimals", 2)))
        P.append('<div class="ac-chg" style="color:%s;">%s today</div>'
                 % (color, "-" if chg is None else "%+.2f%%" % chg))
        P.append(_series_chart(d.get("history") or []))
        # Colour the window figure to match the chart. Without this a card can show
        # a green "+1.00% today" sitting above a red six-month chart, and the two
        # colours look like a contradiction rather than two different timeframes.
        six_color = UP if (six or 0) >= 0 else DOWN
        P.append('<div class="ac-foot">6 months: <span style="color:%s;'
                 'font-weight:600;">%s</span></div>'
                 % (six_color, "-" if six is None else "%+.1f%%" % six))
        P.append('</div>')
    P.append('</div>')
    if note:
        P.append('<div class="note">%s</div>' % _esc(note))
    P.append('</div>')
    return "".join(P)


CSS = """
.acards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;}
.acard{border:1px solid var(--ring);border-radius:10px;padding:13px 14px 10px;
background:var(--card);}
.ac-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
.ac-name{font-size:14px;font-weight:650;color:var(--ink);}
.ac-unit{font-size:10.5px;color:var(--muted);}
.ac-price{font-size:21px;font-weight:700;margin-top:5px;color:var(--ink);
font-variant-numeric:tabular-nums;}
.ac-chg{font-size:12.5px;font-weight:600;margin-bottom:6px;}
.ac-foot{font-size:11px;color:var(--muted);margin-top:4px;
font-variant-numeric:tabular-nums;}
"""
