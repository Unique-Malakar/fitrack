"""Static dashboard generator (Phase 4).

Emits one self-contained HTML file - no scripts from any CDN, no external fonts,
no build step - so GitHub Pages can serve it straight from the repo.

Charting decisions, and why:

* PILLAR STATES use the STATUS palette, not a diverging scale. A pillar's score is
  a state (Healthy / Stressed), and its axis direction differs per pillar: +0.4 on
  Growth is good, +0.4 on Credit is bad. Encoding raw sign on a diverging ramp
  would colour those identically. Status colours always ship with the state name
  and a glyph, never colour alone.
* SECTOR RELATIVE STRENGTH uses the DIVERGING pair (blue/red, neutral grey
  midpoint). Out- versus under-performance against SPY is genuine polarity.
  Note this is deliberately NOT the red/green convention of finance UIs: that pair
  is the one red-green colourblind readers cannot separate, and roughly 8% of men
  are. Blue/red carries the same meaning and survives every CVD check.
* THE REGIME TIMELINE uses categorical hues in the fixed palette order, validated
  for six slots in both modes. Three light-mode hues fall below 3:1 against the
  surface, so the relief rule applies: every segment carries a direct label and a
  table view sits below it.
* SPARKLINES are single-series, so they take no legend - the row label names them.

Dark mode is a selected set of steps for the dark surface, not an inversion.
"""
from __future__ import annotations

from .email_builder import _esc

# --- palette (validated: see README) ---------------------------------------
REGIME_HUES = [
    ("Goldilocks",  "#2a78d6", "#3987e5"),
    ("Reflation",   "#eb6834", "#d95926"),
    ("Overheating", "#1baf7a", "#199e70"),
    ("Stagflation", "#eda100", "#c98500"),
    ("Risk-Off",    "#e87ba4", "#d55181"),
    ("Late Cycle",  "#008300", "#008300"),
]
REGIME_LIGHT = {n: l for n, l, _ in REGIME_HUES}
REGIME_DARK = {n: d for n, _, d in REGIME_HUES}

STATUS = {"good": "#0ca30c", "watch": "#fab219", "bad": "#d03b3b", "unknown": "#898781"}
STATUS_GLYPH = {"good": "\u2713", "watch": "\u25c6", "bad": "\u0021", "unknown": "\u2014"}

DIVERGE_POS, DIVERGE_NEG = "#2a78d6", "#e34948"

CSS = """
:root{color-scheme:light;
--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,0.10);--card:#ffffff;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--surface:#1a1a19;--plane:#0d0d0d;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,0.10);--card:#1a1a19;}}
:root[data-theme="dark"]{color-scheme:dark;
--surface:#1a1a19;--plane:#0d0d0d;--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,0.10);--card:#1a1a19;}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 64px;}
.card{background:var(--card);border:1px solid var(--ring);border-radius:12px;
padding:20px 22px;margin:16px 0;}
h1{font-size:13px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);
margin:0 0 4px;font-weight:700;}
h2{font-size:12px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);
margin:0 0 14px;font-weight:700;}
.hero{font-size:clamp(28px,5vw,42px);font-weight:700;margin:8px 0 6px;line-height:1.1;}
.sub{color:var(--ink-2);font-size:14px;}
.chip{display:inline-block;padding:3px 10px;border-radius:11px;font-size:12px;
font-weight:600;border:1px solid var(--ring);margin-right:6px;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{text-align:left;font-size:11px;letter-spacing:.6px;text-transform:uppercase;
color:var(--muted);font-weight:600;padding:0 8px 7px 0;}
td{padding:7px 8px 7px 0;border-top:1px solid var(--grid);vertical-align:middle;}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
.scroll{overflow-x:auto;}
details{margin-top:12px;}
summary{cursor:pointer;font-size:12px;color:var(--ink-2);}
.legend{display:flex;flex-wrap:wrap;gap:10px 16px;margin:10px 0 0;font-size:12px;
color:var(--ink-2);}
.legend span{display:inline-flex;align-items:center;gap:6px;}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block;
box-shadow:0 0 0 1px var(--ring);}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;}
.note{font-size:11px;color:var(--muted);margin-top:10px;line-height:1.6;}
.warn{background:#fdf3dd;color:#6b4d00;border:1px solid #f0d68a;border-radius:8px;
padding:11px 14px;font-size:13px;margin:0 0 16px;}
:root[data-theme="dark"] .warn{background:#3a2f10;color:#f5d98a;border-color:#5c4a1a;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .warn{
background:#3a2f10;color:#f5d98a;border-color:#5c4a1a;}}
svg{display:block;max-width:100%;}
.spark{width:132px;height:30px;}
"""

TIP_JS = """
(function(){
 var tip=document.createElement('div');
 tip.style.cssText='position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;'+
 'background:var(--ink);color:var(--surface);font:12px system-ui,-apple-system,sans-serif;'+
 'padding:5px 9px;border-radius:6px;z-index:99;white-space:nowrap;';
 document.body.appendChild(tip);
 function show(e,t){tip.textContent=t;tip.style.opacity='1';
  var x=e.clientX+12,y=e.clientY-30;
  if(x+tip.offsetWidth>innerWidth-8)x=e.clientX-tip.offsetWidth-12;
  tip.style.left=x+'px';tip.style.top=y+'px';}
 function hide(){tip.style.opacity='0';}
 document.addEventListener('mousemove',function(e){
  var el=e.target.closest('[data-tip]');
  if(el){show(e,el.getAttribute('data-tip'));}else{hide();}
 });
 document.addEventListener('mouseleave',hide);
})();
"""


# --------------------------------------------------------------- primitives

def _sparkline(values, positive_is=None, width=132, height=30, pad=3):
    """Single-series sparkline. No legend: the adjacent row label names it."""
    if not values or len(values) < 2:
        return '<span style="color:var(--muted);font-size:11px;">no history</span>'

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    step = (width - 2 * pad) / (n - 1)

    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = height - pad - (v - lo) / span * (height - 2 * pad)
        pts.append("%.1f,%.1f" % (x, y))

    last_x, last_y = pts[-1].split(",")
    color = DIVERGE_POS if values[-1] >= values[0] else DIVERGE_NEG
    return (
        '<svg class="spark" viewBox="0 0 %d %d" role="img" aria-label="trend">'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="%s" cy="%s" r="2.6" fill="%s"/></svg>'
        % (width, height, " ".join(pts), color, last_x, last_y, color))


def _diverging_bar(value, vmax, label, width=190, height=17):
    """Bar growing left or right from a centred zero, with a 2px surface gap."""
    if value is None:
        return '<span style="color:var(--muted);font-size:11px;">-</span>'
    vmax = vmax or 1.0
    half = width / 2.0
    frac = max(-1.0, min(1.0, value / vmax))
    length = abs(frac) * (half - 4)
    color = DIVERGE_POS if value >= 0 else DIVERGE_NEG
    x = half + 1 if value >= 0 else half - 1 - length

    return (
        '<svg viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="%s" '
        'data-tip="%s">'
        '<line x1="%.1f" y1="0" x2="%.1f" y2="%d" stroke="var(--axis)" stroke-width="1"/>'
        '<rect x="%.1f" y="3" width="%.1f" height="%d" rx="3" fill="%s"/>'
        '</svg>'
        % (width, height, width, height, _esc(label), _esc(label),
           half, half, height, x, max(length, 1.0), height - 6, color))


def _status_bar(score, tone, state, width=170, height=17):
    """Pillar state. Colour is status, and never travels without the state name."""
    color = STATUS.get(tone, STATUS["unknown"])
    half = width / 2.0
    length = abs(max(-1.0, min(1.0, score))) * (half - 4)
    x = half + 1 if score >= 0 else half - 1 - length
    return (
        '<svg viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="%s" '
        'data-tip="%s (score %+.2f)">'
        '<line x1="%.1f" y1="0" x2="%.1f" y2="%d" stroke="var(--axis)" stroke-width="1"/>'
        '<rect x="%.1f" y="3" width="%.1f" height="%d" rx="3" fill="%s"/></svg>'
        % (width, height, width, height, _esc(state), _esc(state), score,
           half, half, height, x, max(length, 1.0), height - 6, color))


def _timeline(records, height=54):
    """Regime episodes as a proportional band, with direct labels on wide segments."""
    if not records:
        return None

    from ..engine.backfill import regime_episodes
    episodes = regime_episodes(records)
    total = sum(e["points"] for e in episodes) or 1
    width = 1000
    bar_h = 26

    # No preserveAspectRatio="none": non-uniform scaling would squash the segment
    # labels horizontally on narrow viewports. Uniform scaling keeps text legible.
    parts = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;" role="img" '
             'aria-label="regime history">' % (width, height)]
    x = 0.0
    for ep in episodes:
        w = ep["points"] / total * width
        light = REGIME_LIGHT.get(ep["regime"], "#898781")
        tip = "%s  %s to %s" % (ep["regime"], ep["start"], ep["end"])
        # 2px surface gap between adjacent fills.
        parts.append(
            '<rect x="%.2f" y="0" width="%.2f" height="%d" fill="%s" data-tip="%s"/>'
            % (x, max(w - 2, 0.6), bar_h, light, _esc(tip)))
        # Direct label: the relief rule for sub-3:1 hues in light mode.
        if w > 74:
            parts.append(
                '<text x="%.2f" y="%d" text-anchor="middle" font-size="11" '
                'fill="#ffffff" font-family="system-ui,sans-serif" font-weight="600" '
                'style="paint-order:stroke;stroke:rgba(0,0,0,.35);stroke-width:2.5px;">'
                '%s</text>' % (x + w / 2, bar_h - 9, _esc(ep["regime"])))
        x += w

    parts.append('<text x="0" y="%d" font-size="11" fill="var(--muted)" '
                 'font-family="system-ui,sans-serif">%s</text>' % (height - 4, records[0]["date"]))
    parts.append('<text x="%d" y="%d" text-anchor="end" font-size="11" fill="var(--muted)" '
                 'font-family="system-ui,sans-serif">%s</text>'
                 % (width, height - 4, records[-1]["date"]))
    parts.append('</svg>')
    return "".join(parts)


# --------------------------------------------------------------- sections

def _hero(ctx):
    d = ctx["diagnosis"]
    P = ['<div class="card">', '<h1>Market Regime</h1>',
         '<div class="sub">%s</div>' % _esc(ctx["date"].strftime("%A, %d %B %Y")),
         '<div class="hero">%s</div>' % _esc(d.regime)]
    tone = {"Improving": "good", "Deteriorating": "bad"}.get(d.direction, "watch")
    P.append('<div style="margin-top:6px;">')
    P.append('<span class="chip" style="color:%s;">%s %s</span>'
             % (STATUS[tone], STATUS_GLYPH[tone], _esc(d.direction)))
    P.append('<span class="chip" style="color:var(--ink-2);">confidence %.0f%%</span>'
             % (d.confidence * 100))
    if d.runner_up and d.confidence < 0.55:
        P.append('<span class="chip" style="color:var(--ink-2);">near %s</span>'
                 % _esc(d.runner_up))
    P.append('</div>')
    P.append('<div class="grid2" style="margin-top:18px;">')
    for label, key, color in (("Favored", "favored", STATUS["good"]),
                              ("Disfavored", "disfavored", STATUS["bad"])):
        P.append('<div><div style="font-size:11px;letter-spacing:.8px;'
                 'text-transform:uppercase;color:%s;font-weight:700;">%s</div>'
                 '<div style="font-size:13px;color:var(--ink-2);margin-top:3px;">%s</div></div>'
                 % (color, label, _esc(d.flows.get(key, "-"))))
    P.append('</div></div>')
    return "".join(P)


def _alerts_section(alerts):
    if not alerts:
        return ""
    P = ['<div class="card">', '<h2>Active alerts</h2>']
    for a in alerts:
        color = STATUS["bad"] if a.tone == "critical" else STATUS["watch"]
        P.append('<div style="border-left:3px solid %s;padding:8px 12px;margin:8px 0;">'
                 '<div style="font-weight:600;font-size:14px;">%s %s</div>'
                 '<div style="font-size:12px;color:var(--ink-2);margin-top:3px;">%s</div>'
                 '</div>' % (color, STATUS_GLYPH["bad"], _esc(a.label), _esc(a.detail or "")))
    P.append('</div>')
    return "".join(P)


def _pillars_section(ctx):
    P = ['<div class="card">', '<h2>Pillar scores</h2>', '<div class="scroll"><table>',
         '<tr><th>Pillar</th><th>State</th><th>Score</th><th></th><th>Coverage</th></tr>']
    for num in (1, 2, 3, 4, 5):
        p = ctx["pillars"].get(num)
        if p is None:
            continue
        tone = p.risk_tone
        P.append('<tr>')
        P.append('<td style="font-weight:600;">%s</td>' % _esc(p.name))
        P.append('<td style="color:%s;white-space:nowrap;">%s %s</td>'
                 % (STATUS.get(tone, STATUS["unknown"]), STATUS_GLYPH.get(tone, "-"),
                    _esc(p.state)))
        P.append('<td class="num">%+.2f</td>' % p.score)
        P.append('<td>%s</td>' % _status_bar(p.score, tone, p.state))
        P.append('<td class="num" style="color:var(--muted);">%.0f%%</td>' % (p.coverage * 100))
        P.append('</tr>')
    P.append('</table></div>')
    P.append('<div class="note">Each pillar has its own axis, so the sign means '
             'different things: Growth up is expansion, Credit up is stress. Colour '
             'encodes the reading for risk assets and always travels with the state name.</div>')
    P.append('</div>')
    return "".join(P)


def _timeline_section(records):
    if not records:
        return ('<div class="card"><h2>Regime history</h2>'
                '<div class="note">No history yet. Once real API keys are configured, '
                'the replay tool backfills roughly three years from the data each run '
                'already pulls.</div></div>')

    from ..engine.backfill import regime_episodes
    episodes = regime_episodes(records)
    seen = []
    for ep in episodes:
        if ep["regime"] not in seen:
            seen.append(ep["regime"])

    P = ['<div class="card">', '<h2>Regime history</h2>', _timeline(records)]
    P.append('<div class="legend">')
    for name in seen:
        P.append('<span><i class="sw" style="background:%s;"></i>%s</span>'
                 % (REGIME_LIGHT.get(name, "#898781"), _esc(name)))
    P.append('</div>')

    # Table view - the relief rule for the sub-3:1 light-mode hues.
    P.append('<details><summary>Table view (%d episodes)</summary>'
             '<div class="scroll"><table><tr><th>Regime</th><th>From</th><th>To</th>'
             '<th>Points</th></tr>' % len(episodes))
    for ep in reversed(episodes):
        P.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%d</td></tr>'
                 % (_esc(ep["regime"]), ep["start"], ep["end"], ep["points"]))
    P.append('</table></div></details>')
    P.append('<div class="note">Replayed from the current data vintage; FRED revises '
             'history, so this shows how today&rsquo;s data characterises the past rather '
             'than what the brief would have said at the time.</div>')
    P.append('</div>')
    return "".join(P)


def _sectors_section(ctx):
    rows = ctx.get("sectors") or []
    if not rows:
        return ""
    vmax = max([abs(r["rs"].get("1m") or 0) for r in rows] + [1.0])
    P = ['<div class="card">', '<h2>Sector relative strength vs SPY</h2>',
         '<div class="scroll"><table>',
         '<tr><th>Sector</th><th>1W</th><th>1M</th><th>3M</th><th>1M chart</th></tr>']
    for r in rows:
        P.append('<tr><td>%s <span style="color:var(--muted);">%s</span></td>'
                 % (_esc(r["name"]), _esc(r["symbol"])))
        for w in ("1w", "1m", "3m"):
            v = r["rs"].get(w)
            P.append('<td class="num">%s</td>' % ("-" if v is None else "%+.1f" % v))
        P.append('<td>%s</td></tr>' % _diverging_bar(
            r["rs"].get("1m"), vmax, "%s 1M %+.1fpp" % (r["symbol"], r["rs"].get("1m") or 0)))
    P.append('</table></div>')
    P.append('<div class="legend">'
             '<span><i class="sw" style="background:%s;"></i>outperforming SPY</span>'
             '<span><i class="sw" style="background:%s;"></i>underperforming SPY</span></div>'
             % (DIVERGE_POS, DIVERGE_NEG))
    P.append('<div class="note">Blue/red rather than the usual green/red: red-green is '
             'precisely the pair colourblind readers cannot separate. Values are '
             'percentage points versus SPY, from unadjusted closes, so high-yield '
             'sectors carry roughly 0.5-1.0pp of dividend drag per quarter.</div>')
    P.append('</div>')
    return "".join(P)


def _drilldown_section(ctx, history):
    from ..engine.pillar_scores import PILLAR_NAMES
    from .email_builder import fmt_value

    P = ['<div class="card">', '<h2>Pillar drill-down</h2>']
    for num in (1, 2, 3, 4, 5):
        p = ctx["pillars"].get(num)
        if p is None or not p.readings:
            continue
        P.append('<div style="margin:18px 0 6px;font-weight:600;font-size:14px;">%s '
                 '<span style="color:var(--muted);font-weight:400;font-size:12px;">%s</span></div>'
                 % (_esc(PILLAR_NAMES.get(num, "")), _esc(p.axis)))
        P.append('<div class="scroll"><table>'
                 '<tr><th>Indicator</th><th>Value</th><th>1W</th><th>Percentile</th>'
                 '<th>Direction</th><th>History</th></tr>')
        for r in p.readings:
            series = history.get(r.sid) or []
            pct = "-" if r.percentile is None else "%.0f" % r.percentile
            P.append('<tr>')
            P.append('<td>%s%s</td>' % (
                _esc(r.name),
                ' <span style="color:var(--muted);font-size:11px;">stale</span>' if r.stale else ""))
            P.append('<td class="num">%s</td>' % _esc(fmt_value(r)))
            from .email_builder import fmt_change
            P.append('<td class="num">%s</td>' % _esc(fmt_change(r.chg_1w, r.decimals, r.unit)))
            P.append('<td class="num" style="color:var(--muted);">%s</td>' % pct)
            P.append('<td style="color:var(--ink-2);">%s</td>' % _esc(r.direction or "-"))
            P.append('<td>%s</td>' % _sparkline(series))
            P.append('</tr>')
        P.append('</table></div>')
    P.append('<div class="note">Percentile is the value&rsquo;s rank within its own '
             'trailing window, not a fixed threshold. Sparklines show the replayed '
             'history at weekly resolution.</div>')
    P.append('</div>')
    return "".join(P)


def _signals_section(ctx):
    sigs = ctx.get("signals") or []
    if not sigs:
        return ""
    P = ['<div class="card">', '<h2>Cross-asset signals</h2>']
    for s in sigs:
        color = {"alert": STATUS["bad"], "watch": STATUS["watch"]}.get(s.tone, STATUS["good"])
        P.append('<div style="border-left:3px solid %s;padding:9px 13px;margin:9px 0;">'
                 '<div style="font-weight:600;font-size:14px;">%s %s</div>'
                 '<div style="font-size:13px;color:var(--ink-2);margin-top:4px;">%s</div>'
                 '</div>' % (color, STATUS_GLYPH.get(
                     "bad" if s.tone == "alert" else "watch", ""), _esc(s.title), _esc(s.detail)))
    P.append('</div>')
    return "".join(P)


def _chain_section(stages, summary):
    """The debt/debasement chain, shown as a testable sequence rather than a story.

    Stages are laid out in order with their status prominent, because the sequence
    is the claim: a lit stage 5 above a dark stage 3 is evidence against the chain,
    not for it, and the layout should make that visible at a glance.
    """
    if not stages:
        return ""

    from ..engine.chain import FIRING, BUILDING, NOT_FIRING

    P = ['<div class="card">', '<h2>Debt &amp; debasement chain</h2>']
    P.append('<div style="font-size:14px;color:var(--ink);margin:-4px 0 4px;">%s</div>'
             % _esc(summary.get("verdict", "")))
    P.append('<div class="legend" style="margin-bottom:6px;">')
    for status, text in ((FIRING, "condition met"), (BUILDING, "moving toward it"),
                         (NOT_FIRING, "condition absent")):
        tone = {FIRING: "bad", BUILDING: "watch", NOT_FIRING: "good"}[status]
        P.append('<span><i class="sw" style="background:%s;"></i>%s</span>'
                 % (STATUS[tone], text))
    P.append('</div>')

    for i, st in enumerate(stages):
        color = STATUS.get(st.tone, STATUS["unknown"])
        P.append('<div style="border:1px solid var(--ring);border-left:4px solid %s;'
                 'border-radius:0 8px 8px 0;padding:13px 16px;margin:12px 0;">' % color)
        P.append('<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;">'
                 '<span style="font-weight:700;font-size:15px;">Stage %d &middot; %s</span>'
                 '<span style="color:%s;font-weight:700;font-size:12px;">%s %s</span></div>'
                 % (st.num, _esc(st.name), color,
                    STATUS_GLYPH.get(st.tone, ""), _esc(st.label)))
        P.append('<div style="font-size:12px;color:var(--muted);margin-top:5px;">'
                 '<strong>Claim:</strong> %s</div>' % _esc(st.claim or ""))
        P.append('<div style="font-size:12px;color:var(--muted);margin-top:2px;">'
                 '<strong>Test:</strong> %s</div>' % _esc(st.test or ""))
        P.append('<div style="font-size:13px;color:var(--ink-2);margin-top:8px;'
                 'line-height:1.55;">%s</div>' % _esc(st.detail or ""))

        if st.metrics:
            P.append('<div class="scroll"><table style="margin-top:9px;">')
            for label, value in st.metrics:
                P.append('<tr><td style="font-size:12px;color:var(--ink-2);">%s</td>'
                         '<td class="num" style="font-size:12px;">%s</td></tr>'
                         % (_esc(label), _esc(value)))
            P.append('</table></div>')

        if st.caveat:
            P.append('<div style="font-size:11px;color:var(--muted);margin-top:9px;'
                     'padding-top:8px;border-top:1px dashed var(--grid);line-height:1.6;">'
                     '<strong>Caveat:</strong> %s</div>' % _esc(st.caveat))
        P.append('</div>')

        if i < len(stages) - 1:
            P.append('<div style="text-align:center;color:var(--muted);font-size:15px;'
                     'line-height:1;margin:-6px 0;">&#8595;</div>')

    P.append('<div class="note">Each stage reports independently and is allowed to read '
             'NOT FIRING. The chain claims these run in sequence, so a lit late stage '
             'above a dark early one is evidence against the mechanism, not for it.</div>')
    P.append('</div>')
    return "".join(P)


def _not_built_section():
    return ('<div class="card"><h2>Not yet available</h2>'
            '<div class="note">The plan&rsquo;s <strong>AI Infrastructure Tracker</strong> '
            '(hyperscaler capex, semiconductor shipments, datacentre power demand) has no '
            'free API behind it, and neither do earnings revisions, percentage of the '
            'S&amp;P above its 200-day average, the advance/decline line, or ISM PMI '
            '(licensing keeps ISM off FRED). These need a paid feed or manual entry, so '
            'no view is shown rather than an empty one.</div></div>')


# --------------------------------------------------------------- entrypoint

def build(ctx, records=None, alerts=None, synthetic=False,
          chain_stages=None, chain_summary=None):
    """Render the full dashboard to a self-contained HTML string."""
    records = records or []

    history = {}
    for rec in records:
        for sid, value in rec.get("readings", {}).items():
            history.setdefault(sid, []).append(value)

    body = [
        '<div class="wrap">',
        '<div class="warn">These figures come from <strong>fabricated fixture data</strong> '
        'and are not real market observations. Run with live API keys to replace them.'
        '</div>' if synthetic else "",
        _hero(ctx),
        _alerts_section(alerts or []),
        _signals_section(ctx),
        _pillars_section(ctx),
        _chain_section(chain_stages or [], chain_summary or {}),
        _timeline_section(records),
        _sectors_section(ctx),
        _drilldown_section(ctx, history),
        _not_built_section(),
        '<div class="note" style="text-align:center;margin-top:22px;">'
        'Generated by market-intel &middot; %s</div>' % _esc(ctx["date"].isoformat()),
        '</div>',
    ]

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Market Regime Dashboard</title>"
        "<style>%s</style></head><body>%s<script>%s</script></body></html>"
        % (CSS, "".join(body), TIP_JS))
