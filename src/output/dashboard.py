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

import re

from .email_builder import _esc
from .explain import INDICATOR_INFO, describe, ordinal, tooltip

# Plain-language layer. The page was written fluent in its own vocabulary, which is
# useless to a reader who has to decode it first. Every piece of jargon that survives
# on the page now carries a tap-or-hover explanation, and the verdict is restated in
# ordinary words before any number appears.

PLAIN_REGIME = {
    "Goldilocks": "Growth is solid and inflation is behaving. About as good as it gets "
                  "for shares.",
    "Reflation": "The economy is picking up from a soft patch while policy is still "
                 "supportive. Generally good for shares.",
    "Overheating": "Growth is strong but inflation is running hot, so the Fed is likely "
                   "to lean against it. Good for commodities, awkward for bonds.",
    "Stagflation": "Growth is slowing while inflation stays high. The hardest backdrop, "
                   "because shares and bonds can fall at the same time.",
    "Risk-Off": "The economy is contracting and lenders are nervous. Money moves toward "
                "safety - cash, government bonds, gold.",
    "Late Cycle": "Growth is still positive but fading, and fewer shares are driving the "
                  "gains. A time to prefer quality over speculation.",
    "Indeterminate": "Not enough data arrived to reach a verdict today.",
}

# Standalone sentences. Splicing these onto the end of a regime description as a
# clause produced run-ons like "prefer quality over speculation and conditions are
# getting worse".
PLAIN_DIRECTION = {
    "Improving": "Right now conditions are improving.",
    "Deteriorating": "Right now conditions are getting worse.",
    "Stable": "Conditions are holding steady.",
    "Unknown": "The direction of travel is unclear.",
}

HELP = {
    "regime": "The overall type of market we are in, picked from six named states by "
              "comparing today's five pillar scores against what each state normally "
              "looks like.",
    "confidence": "How clearly today's reading matches one regime rather than sitting "
                  "between two. Low confidence is not an error - it means the market is "
                  "genuinely ambiguous right now.",
    "direction": "Whether conditions improved or worsened since the last reading. This "
                 "matters more than the level: things getting worse from a good place is "
                 "usually more informative than a bad level that is stabilising.",
    "favoured": "What this type of market has historically been kind to. Context for "
                "your own thinking, not advice, and never a prediction.",
    "pillar": "One of five forces that together describe the economy. Each is scored "
              "from -1 to +1 by combining its own indicators.",
    "score": "Where this pillar sits on its own scale, from -1 to +1. Note each pillar "
             "points a different way: on Growth, higher means expanding; on Credit, "
             "higher means more stress.",
    "coverage": "How much of the underlying data actually arrived. Below 60% the pillar "
                "reports Unknown instead of guessing from a thin sample.",
    "signals": "These only appear when two indicators disagree in a specific, named way. "
               "A single number moving is usually noise; two of them contradicting each "
               "other is the part worth reading.",
    "percentile": "Where today's value sits within this indicator's own past three "
                  "years. 90 means higher than 90% of that period. Used instead of fixed "
                  "thresholds, which go stale as decades pass.",
    "breadth": "Whether a rise is broad or narrow. Compares the average share (equal "
               "weight) against the index (dominated by the biggest companies). If the "
               "index rises while the average share falls, few names are carrying it - "
               "which is fragile.",
    "sector": "How each slice of the market performed against the S&P 500. Positive "
              "means it beat the index; it does not mean it went up.",
    "chain": "A popular theory that government debt forces money-printing, which "
             "devalues the currency and inflates asset prices. Tracked as five stages "
             "that are each allowed to report NOT happening.",
    "watch": "The indicators most in play right now. This list changes with "
             "conditions - when credit is calm, spreads are background noise; when "
             "the Sahm Rule is creeping toward its trigger, it is the main event.",
    "change": "Specific observable conditions that would shift today's verdict. "
              "Stated so you can check them yourself rather than take a forecast "
              "on trust.",
    "outlook": "Sectors ranked by how well current conditions suit what they are "
               "exposed to - a statement about positioning, not a forecast. The last "
               "column shows what prices have actually done, so you can see where the "
               "market agrees or disagrees.",
    "timeline": "Which regime was in force over the past several years, replayed from "
                "today's data. Useful for seeing whether the current reading is new or "
                "has been running a while.",
    "stale": "The newest published figure is older than expected for this indicator - it "
             "is still shown, but treat it as lagging.",
}


def _help(key):
    """Small tap-or-hover explainer beside a term."""
    text = HELP.get(key)
    if not text:
        return ""
    return ('<span class="help" tabindex="0" role="button" aria-label="%s" '
            'data-tip="%s">?</span>' % (_esc(text[:100]), _esc(text)))


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
.help{display:inline-flex;align-items:center;justify-content:center;width:15px;
height:15px;border-radius:50%;background:var(--grid);color:var(--ink-2);
font-size:10px;font-weight:700;margin-left:5px;cursor:help;vertical-align:middle;
font-family:system-ui,sans-serif;user-select:none;flex:none;}
.help:hover,.help:focus{background:var(--accent-soft,#d9e6e8);color:var(--ink);
outline:2px solid transparent;box-shadow:0 0 0 2px var(--ring);}
.plain{font-size:16px;line-height:1.6;color:var(--ink);margin:14px 0 0;
max-width:62ch;}
.readme{background:var(--card);border:1px solid var(--ring);border-radius:10px;
padding:0;margin:16px 0;}
.readme summary{padding:14px 20px;font-size:14px;font-weight:600;color:var(--ink);
list-style:none;cursor:pointer;}
.readme summary::-webkit-details-marker{display:none;}
.readme summary::before{content:"▸ ";color:var(--muted);}
.readme[open] summary::before{content:"▾ ";}
.readme .body{padding:0 20px 18px;font-size:13.5px;line-height:1.65;
color:var(--ink-2);max-width:70ch;}
.readme ol{padding-left:1.2em;margin:8px 0 0;}
.readme li{margin-bottom:9px;}
@media (prefers-reduced-motion:reduce){*{transition:none!important;}}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));
gap:12px;margin:4px 0 0;}
.pcard{background:var(--card);border:1px solid var(--ring);border-radius:10px;
padding:14px 16px 12px;display:flex;flex-direction:column;gap:7px;}
.pc-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;}
.pc-name{font-size:14.5px;font-weight:650;color:var(--ink);}
.pc-state{font-size:12.5px;font-weight:650;white-space:nowrap;}
.pc-plain{font-size:13px;color:var(--ink-2);line-height:1.5;}
.pc-sub{font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums;}
.split{display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);
gap:22px;align-items:start;}
@media (max-width:700px){.split{grid-template-columns:1fr;}}
.maplead{font-size:13px;color:var(--ink-2);line-height:1.6;}
.more{border:1px solid var(--ring);border-radius:10px;background:var(--card);
margin:12px 0;overflow:hidden;}
.more>summary{padding:14px 18px;cursor:pointer;font-size:14px;font-weight:600;
color:var(--ink);list-style:none;display:flex;justify-content:space-between;
align-items:center;gap:12px;}
.more>summary::-webkit-details-marker{display:none;}
.more>summary::after{content:"+";color:var(--muted);font-size:17px;font-weight:400;
line-height:1;}
.more[open]>summary::after{content:"−";}
.more>summary:hover{background:var(--rule-soft,rgba(128,128,128,.06));}
.more .inner{padding:0 18px 18px;}
.more .hint{font-size:12px;color:var(--muted);font-weight:400;}
.section-lead{font-size:13.5px;color:var(--ink-2);line-height:1.6;margin:0 0 12px;
max-width:66ch;}
.dd-group{font-size:12px;letter-spacing:.9px;text-transform:uppercase;
color:var(--muted);font-weight:700;margin:22px 0 8px;padding-bottom:6px;
border-bottom:1px solid var(--grid);}
.dd-axis{font-weight:400;letter-spacing:0;text-transform:none;font-size:11.5px;}
.dd-row{padding:11px 0;border-bottom:1px solid var(--rule-soft,rgba(128,128,128,.12));
display:grid;gap:4px;}
.dd-row:last-child{border-bottom:none;}
.dd-head{display:flex;justify-content:space-between;align-items:baseline;gap:14px;}
.dd-name{font-size:14px;font-weight:600;color:var(--ink);}
.dd-term{border-bottom:1px dotted var(--muted);cursor:help;}
.dd-term:hover,.dd-term:focus{border-bottom-color:var(--ink);outline:none;}
.dd-val{font-size:14px;font-weight:600;color:var(--ink);white-space:nowrap;
font-variant-numeric:tabular-nums;}
.dd-mean{font-size:13px;color:var(--ink-2);line-height:1.5;max-width:70ch;}
.dd-foot{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:11px;color:var(--muted);
font-variant-numeric:tabular-nums;}
.dd-stale{font-size:10px;color:var(--muted);border:1px solid var(--grid);
border-radius:3px;padding:0 4px;cursor:help;}
.dd-spark{margin-top:2px;}
.strip{display:flex;gap:0;overflow-x:auto;background:var(--card);
border:1px solid var(--ring);border-radius:10px;margin:0 0 16px;
-webkit-overflow-scrolling:touch;}
.tk{flex:0 0 auto;padding:11px 16px;border-right:1px solid var(--rule-soft,rgba(128,128,128,.12));
min-width:104px;cursor:help;}
.tk:last-child{border-right:none;}
.tk-name{font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;
color:var(--muted);font-weight:700;}
.tk-val{font-size:15px;font-weight:650;color:var(--ink);margin-top:3px;
font-variant-numeric:tabular-nums;}
.tk-chg{font-size:12px;font-weight:600;margin-top:1px;font-variant-numeric:tabular-nums;}
.watch{display:flex;gap:13px;padding:14px 0;
border-bottom:1px solid var(--rule-soft,rgba(128,128,128,.12));}
.watch:last-of-type{border-bottom:none;}
.watch-n{flex:none;width:24px;height:24px;border-radius:50%;background:var(--accent-soft,var(--grid));
color:var(--ink);font-size:12px;font-weight:700;display:flex;align-items:center;
justify-content:center;}
.watch-body{flex:1;min-width:0;}
.watch-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;}
.watch-name{font-size:14.5px;font-weight:650;}
.watch-val{font-size:14.5px;font-weight:650;white-space:nowrap;
font-variant-numeric:tabular-nums;}
.watch-why{font-size:12.5px;color:var(--watch-ink,#8a6100);margin-top:3px;font-weight:600;}
.watch-what{font-size:12.5px;color:var(--ink-2);margin-top:5px;line-height:1.5;}
.watch-next{font-size:11px;color:var(--muted);margin-top:6px;}
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
 // Touch devices have no hover, so the explainers must respond to a tap too.
 document.addEventListener('click',function(e){
  var el=e.target.closest('[data-tip]');
  if(el){e.preventDefault();show({clientX:innerWidth/2,clientY:60},
    el.getAttribute('data-tip'));setTimeout(hide,6000);}
 });
 document.addEventListener('keydown',function(e){
  if(e.key!=='Enter'&&e.key!==' ')return;
  var el=document.activeElement&&document.activeElement.closest('[data-tip]');
  if(el){e.preventDefault();var r=el.getBoundingClientRect();
   show({clientX:r.left,clientY:r.top},el.getAttribute('data-tip'));
   setTimeout(hide,6000);}
 });
 tip.style.maxWidth='min(340px,88vw)';tip.style.whiteSpace='normal';
 tip.style.lineHeight='1.45';
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
# Plain-language state descriptions, keyed by (pillar, state label). A beginner
# cannot act on "Contracting, -0.46"; they can act on a sentence.
PLAIN_STATE = {
    (1, "Contracting"): "The economy is shrinking.",
    (1, "Slowing"): "Still growing, but losing steam.",
    (1, "Steady"): "Growing at a normal, unremarkable pace.",
    (1, "Expanding"): "Growing at a healthy clip.",
    (1, "Booming"): "Growing unusually fast.",
    (2, "Deflationary"): "Prices are falling - rarer, and its own kind of problem.",
    (2, "Cooling"): "Price rises are slowing down.",
    (2, "Sticky"): "Inflation is not falling as fast as hoped.",
    (2, "Hot"): "Prices are rising faster than the Fed wants.",
    (2, "Very Hot"): "Inflation is running well above target.",
    (3, "Easing"): "Borrowing is getting cheaper and easier.",
    (3, "Loosening"): "Financial conditions are gently improving.",
    (3, "Neutral"): "Policy is neither helping nor hurting much.",
    (3, "Tightening"): "Borrowing is getting more expensive.",
    (3, "Very Tight"): "Money is hard to come by; this pressures everything.",
    (4, "Ample"): "Lenders are relaxed and money is flowing freely.",
    (4, "Adequate"): "Credit markets are calm.",
    (4, "Draining"): "Lenders are getting more cautious.",
    (4, "Stressed"): "Credit markets are under real strain - watch this closely.",
    (5, "Deteriorating"): "Share prices are weakening.",
    (5, "Narrowing"): "The market is rising, but on fewer and fewer names.",
    (5, "Mixed"): "No clear direction in the stock market.",
    (5, "Healthy"): "Share prices are rising with decent participation.",
    (5, "Broadening"): "The rise is spreading across many companies - the healthiest kind.",
}

# Both ends of each pillar's scale, in ordinary words. The score is meaningless
# without knowing which direction is which, and each pillar points differently.
AXIS_ENDS = {
    1: ("Shrinking", "Growing"),
    2: ("Prices falling", "Prices surging"),
    3: ("Easy money", "Tight money"),
    4: ("Money flowing", "Credit stress"),
    5: ("Weak market", "Strong market"),
}

PILLAR_PLAIN_NAME = {
    1: "The economy",
    2: "Inflation",
    3: "Interest rates",
    4: "Lending & credit",
    5: "The stock market",
}


def _gauge(score, tone, pillar, width=250, height=44):
    """A position on a labelled track. Reading a number requires knowing the scale;
    reading a dot between two words does not."""
    lo, hi = AXIS_ENDS.get(pillar, ("Low", "High"))
    color = STATUS.get(tone, STATUS["unknown"])
    pad, track_y = 4, 15
    usable = width - 2 * pad
    x = pad + (max(-1.0, min(1.0, score)) + 1) / 2 * usable
    mid = pad + usable / 2

    return (
        '<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;max-width:%dpx;" '
        'role="img" aria-label="%s on a scale from %s to %s">'
        '<rect x="%d" y="%d" width="%.1f" height="7" rx="3.5" fill="var(--grid)"/>'
        '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="var(--axis)" stroke-width="1"/>'
        '<circle cx="%.1f" cy="%.1f" r="7" fill="%s" stroke="var(--card)" stroke-width="2.5"/>'
        '<text x="%d" y="%d" font-size="10.5" fill="var(--muted)" '
        'font-family="system-ui,sans-serif">%s</text>'
        '<text x="%d" y="%d" font-size="10.5" fill="var(--muted)" text-anchor="end" '
        'font-family="system-ui,sans-serif">%s</text>'
        '</svg>'
        % (width, height, width, _esc(lo + " to " + hi), _esc(lo), _esc(hi),
           pad, track_y, usable,
           mid, track_y - 3, mid, track_y + 10,
           x, track_y + 3.5, color,
           pad, height - 6, _esc(lo),
           width - pad, height - 6, _esc(hi)))


def _pillar_cards(ctx):
    """Five cards instead of a table. A table invites reading every cell; cards
    invite scanning, which is what this section is for."""
    P = ['<div class="cards">']
    for num in (1, 2, 3, 4, 5):
        p = ctx["pillars"].get(num)
        if p is None:
            continue
        tone = p.risk_tone
        color = STATUS.get(tone, STATUS["unknown"])
        plain = PLAIN_STATE.get((num, p.state), "")
        if not p.known:
            plain = "Not enough data arrived today to judge this."

        P.append('<div class="pcard">')
        P.append('<div class="pc-top">'
                 '<span class="pc-name">%s</span>'
                 '<span class="pc-state" style="color:%s;">%s %s</span></div>'
                 % (_esc(PILLAR_PLAIN_NAME.get(num, p.name)), color,
                    STATUS_GLYPH.get(tone, ""), _esc(p.state)))
        P.append(_gauge(p.score if p.known else 0.0, tone, num))
        P.append('<div class="pc-plain">%s</div>' % _esc(plain))
        P.append('<div class="pc-sub">%s &middot; score %+.2f</div>'
                 % (_esc(p.name), p.score))
        P.append('</div>')
    P.append('</div>')
    return "".join(P)


def _regime_map(ctx):
    """Where today sits on the growth/inflation plane, with all six regimes shown.

    Growth against inflation is the classic macro frame and the one a beginner picks
    up fastest: two axes, six named neighbourhoods, one dot. Regime positions come
    from the SAME profile coordinates the classifier uses, so the picture cannot
    drift from the verdict.

    Honest limitation: the verdict uses five dimensions and this shows two, so a
    couple of regimes sit close together here that the classifier separates using
    credit, policy and breadth. It is an orientation aid, not the decision itself.
    """
    from ..engine.regime import PROFILES

    g = ctx["pillars"].get(1)
    i = ctx["pillars"].get(2)
    if g is None or i is None or not (g.known and i.known):
        return ""

    W = H = 300
    pad = 34
    span = W - 2 * pad

    def px(v):
        return pad + (max(-1.0, min(1.0, v)) + 1) / 2 * span

    def py(v):
        return pad + (1 - (max(-1.0, min(1.0, v)) + 1) / 2) * span

    P = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;max-width:340px;" '
         'role="img" aria-label="Map of growth against inflation showing the current '
         'position among six market regimes">' % (W, H)]

    # quadrant grid
    P.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" '
             'stroke="var(--grid)" stroke-width="1" rx="6"/>' % (pad, pad, span, span))
    P.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--grid)" '
             'stroke-dasharray="3 3"/>' % (pad, py(0), pad + span, py(0)))
    P.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="var(--grid)" '
             'stroke-dasharray="3 3"/>' % (px(0), pad, px(0), pad + span))

    # you are here
    cx, cy = px(g.score), py(i.score)
    P.append('<circle cx="%.1f" cy="%.1f" r="13" fill="%s" opacity="0.16"/>'
             % (cx, cy, STATUS["bad"]))
    P.append('<circle cx="%.1f" cy="%.1f" r="6.5" fill="%s" stroke="var(--card)" '
             'stroke-width="2.5"><title>Today</title></circle>'
             % (cx, cy, STATUS["bad"]))

    # Regime names at their own profile coordinates. Label placement is explicit
    # per regime rather than computed: on this 2D plane Reflation and Late Cycle sit
    # about twelve pixels apart and Goldilocks is close behind, so an automatic rule
    # stacks all three on the same spot. Offsets fan them apart legibly.
    label_offset = {
        "Overheating": (0, -9, "middle"),
        "Stagflation": (0, -9, "middle"),
        "Risk-Off": (-7, 3, "end"),
        "Late Cycle": (-6, -9, "end"),
        "Reflation": (7, -9, "start"),
        "Goldilocks": (4, 15, "start"),
    }
    for name, prof in PROFILES.items():
        x, y = px(prof[1]), py(prof[2])
        dx, dy, anchor = label_offset.get(name, (0, -9, "middle"))
        P.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s" opacity="0.6"/>'
                 % (x, y, REGIME_LIGHT.get(name, "#898781")))
        P.append('<text x="%.1f" y="%.1f" font-size="9.5" text-anchor="%s" '
                 'fill="var(--muted)" font-family="system-ui,sans-serif">%s</text>'
                 % (x + dx, y + dy, anchor, _esc(name)))

    # axis labels
    P.append('<text x="%d" y="%d" font-size="10.5" fill="var(--ink-2)" '
             'text-anchor="middle" font-family="system-ui,sans-serif" '
             'font-weight="600">Economy growing &#8594;</text>'
             % (W // 2, H - 8))
    P.append('<text transform="rotate(-90 12 %d)" x="12" y="%d" font-size="10.5" '
             'fill="var(--ink-2)" text-anchor="middle" '
             'font-family="system-ui,sans-serif" font-weight="600">'
             'Inflation rising &#8594;</text>' % (H // 2, H // 2))
    P.append('</svg>')
    return "".join(P)


def _hero(ctx):
    d = ctx["diagnosis"]
    P = ['<div class="card">', '<h1>Market Regime</h1>',
         '<div class="sub">%s</div>' % _esc(ctx["date"].strftime("%A, %d %B %Y")),
         '<div class="hero">%s%s</div>' % (_esc(d.regime), _help("regime"))]
    tone = {"Improving": "good", "Deteriorating": "bad"}.get(d.direction, "watch")
    P.append('<div style="margin-top:6px;">')
    P.append('<span class="chip" style="color:%s;">%s %s%s</span>'
             % (STATUS[tone], STATUS_GLYPH[tone], _esc(d.direction), _help("direction")))
    P.append('<span class="chip" style="color:var(--ink-2);">confidence %.0f%%%s</span>'
             % (d.confidence * 100, _help("confidence")))
    if d.runner_up and d.confidence < 0.55:
        P.append('<span class="chip" style="color:var(--ink-2);">near %s</span>'
                 % _esc(d.runner_up))
    P.append('</div>')

    # The verdict restated in ordinary words, before any number appears. A reader who
    # does not already know what "Late Cycle" means gets nothing from the label alone.
    plain = PLAIN_REGIME.get(d.regime)
    if plain:
        tail = PLAIN_DIRECTION.get(d.direction, "")
        P.append('<div class="plain"><strong>In plain terms:</strong> %s</div>'
                 % _esc((plain + " " + tail).strip()))
    if d.runner_up and d.confidence < 0.55:
        P.append('<div style="font-size:13px;color:var(--ink-2);margin-top:8px;">'
                 'This reading sits close to <strong>%s</strong>, so treat the label as '
                 'provisional rather than settled.</div>' % _esc(d.runner_up))
    P.append('<div class="grid2" style="margin-top:18px;">')
    for label, key, color in (("Favored", "favored", STATUS["good"]),
                              ("Disfavored", "disfavored", STATUS["bad"])):
        P.append('<div><div style="font-size:11px;letter-spacing:.8px;'
                 'text-transform:uppercase;color:%s;font-weight:700;">%s%s</div>'
                 '<div style="font-size:13px;color:var(--ink-2);margin-top:3px;">%s</div></div>'
                 % (color, label, _help("favoured") if key == "favored" else "",
                    _esc(d.flows.get(key, "-"))))
    P.append('</div></div>')
    return "".join(P)


def _howto_section():
    """Reading order, stated on the page. The section sequence encodes priority -
    verdict, then warnings, then reasoning, then evidence - and that is invisible
    unless it is said out loud."""
    return (
        '<details class="readme"><summary>How to read this page</summary>'
        '<div class="body">'
        '<p>Sections run in order of importance. On a normal day you can stop after '
        'the second one.</p>'
        '<ol>'
        '<li><strong>The verdict at the top</strong> &mdash; what kind of market this '
        'is, in one word plus a plain-English sentence. If nothing else, read this.</li>'
        '<li><strong>Cross-asset signals</strong> &mdash; the only section that is '
        'sometimes empty, and the most valuable when it is not. It appears when two '
        'indicators contradict each other, which is where the useful information '
        'tends to be.</li>'
        '<li><strong>Pillar scores</strong> &mdash; the five forces behind the '
        'verdict. Read this when you want to know <em>why</em>.</li>'
        '<li><strong>Debt &amp; debasement chain</strong> &mdash; a specific theory, '
        'tracked stage by stage. Each stage may read NOT FIRING, and often does.</li>'
        '<li><strong>Regime history</strong> &mdash; whether today is a change or '
        'more of the same.</li>'
        '<li><strong>Sector strength</strong> &mdash; where money actually moved, '
        'measured against the S&amp;P rather than in absolute terms.</li>'
        '<li><strong>Pillar drill-down</strong> &mdash; every underlying number. '
        'Reference material, not daily reading.</li>'
        '</ol>'
        '<p>Tap or hover any <span class="help" data-tip="Like this one. Every '
        'circled question mark explains the term next to it.">?</span> for an '
        'explanation of the term beside it.</p>'
        '<p><strong>Two things this page is not.</strong> It carries no news '
        'headlines &mdash; only measured data, because conditions are more useful '
        'than commentary. And nothing here is advice or a forecast: it describes '
        'what is happening now, not what happens next.</p>'
        '</div></details>')


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
    P = ['<div class="card">', '<h2>Pillar scores%s</h2>' % _help("pillar"), '<div class="scroll"><table>',
         '<tr><th>Pillar</th><th>State</th><th>Score%s</th><th></th>'
         '<th>Coverage%s</th></tr>' % (_help("score"), _help("coverage"))]
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
        return ('<div class="card"><h2>Regime history%s</h2>'
                '<div class="note">No history yet. Once real API keys are configured, '
                'the replay tool backfills several years from the data each run '
                'already pulls.</div></div>' % _help("timeline"))

    from ..engine.backfill import regime_episodes
    episodes = regime_episodes(records)
    seen = []
    for ep in episodes:
        if ep["regime"] not in seen:
            seen.append(ep["regime"])

    P = ['<div class="card">', '<h2>Regime history%s</h2>' % _help("timeline"), _timeline(records)]
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
    P = ['<div class="card">', '<h2>Sector relative strength vs SPY%s</h2>' % _help("sector"),
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
    """Every underlying number, with its meaning attached.

    A bare "JTSQUR 2.0" teaches nothing. Each row now carries what the indicator is
    and why it is watched (behind the name), plus a sentence linking today's reading
    to what it implies. The raw percentile and direction columns are folded into that
    sentence rather than shown as numbers that need their own decoding.
    """
    from ..engine.pillar_scores import PILLAR_NAMES
    from .email_builder import fmt_change, fmt_value

    P = ['<div class="card">', '<h2>Every number behind the verdict%s</h2>' % _help("percentile"),
         '<p class="section-lead">Grouped by which of the five forces they feed. '
         'Tap any indicator name to see what it measures and why it is watched.</p>']

    for num in (1, 2, 3, 4, 5):
        p = ctx["pillars"].get(num)
        if p is None or not p.readings:
            continue
        P.append('<div class="dd-group">%s <span class="dd-axis">%s</span></div>'
                 % (_esc(PILLAR_PLAIN_NAME.get(num, PILLAR_NAMES.get(num, ""))),
                    _esc(p.axis)))

        for r in p.readings:
            series = history.get(r.sid) or []
            spec = ctx.get('spec_by_id', {}).get(r.sid, {})
            meaning = describe(r.sid, r.percentile, r.direction, r.value,
                               spec.get('anchor'), spec.get('anchor_note'),
                               spec.get('anchor_signal', 'above'))
            tip = tooltip(r.sid)
            name_html = _esc(r.name)
            if tip:
                name_html = ('<span class="dd-term" tabindex="0" role="button" '
                             'data-tip="%s">%s</span>' % (_esc(tip), _esc(r.name)))

            P.append('<div class="dd-row">')
            P.append('<div class="dd-head">'
                     '<span class="dd-name">%s%s</span>'
                     '<span class="dd-val">%s</span></div>'
                     % (name_html,
                        ' <span class="dd-stale" data-tip="%s">stale</span>'
                        % _esc(HELP["stale"]) if r.stale else "",
                        _esc(fmt_value(r))))
            if meaning:
                P.append('<div class="dd-mean">%s</div>' % _esc(meaning))
            P.append('<div class="dd-foot">')
            P.append('<span>%s since last release</span>'
                     % _esc(fmt_change(r.chg_1w, r.decimals, r.unit)))
            if r.percentile is not None:
                P.append('<span>%s percentile</span>' % ordinal(r.percentile))
            P.append('<span>%s</span>' % _esc(r.direction or "flat"))
            P.append('</div>')
            if series:
                P.append('<div class="dd-spark">%s</div>' % _sparkline(series))
            P.append('</div>')

    P.append('<div class="note">Percentile is where today sits within this '
             'indicator&rsquo;s own past three years &mdash; not a fixed threshold, '
             'because what counted as a high reading in 2015 was normal in 1995.</div>')
    P.append('</div>')
    return "".join(P)


def _signals_section(ctx):
    sigs = ctx.get("signals") or []
    if not sigs:
        return ""
    P = ['<div class="card">', '<h2>Cross-asset signals%s</h2>' % _help("signals")]
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

    P = ['<div class="card">', '<h2>Debt &amp; debasement chain%s</h2>' % _help("chain")]
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

# The section builders emit a full card. Inside a collapsible the card chrome and
# the duplicated heading are noise, so strip them rather than maintaining two
# renderers that could drift apart.
_CARD_RE = re.compile(r'^<div class="card">\s*(?:<h2>.*?</h2>)?(.*)</div>$', re.S)


def _bare(html):
    if not html:
        return ""
    m = _CARD_RE.match(html.strip())
    return m.group(1) if m else html


def _sectors_inner(ctx):
    return _bare(_sectors_section(ctx))


def _timeline_inner(records):
    return _bare(_timeline_section(records))


def _chain_inner(stages, summary):
    return _bare(_chain_section(stages, summary))


def _drilldown_inner(ctx, history):
    return _bare(_drilldown_section(ctx, history))


def _gaps_inner():
    return _bare(_not_built_section())


def _outlook_section(ctx):
    """Which sectors today's conditions suit, and where prices disagree.

    Framed as positioning rather than prediction throughout: sensitivities describe
    what a sector is exposed to, not what its price will do. The comparison against
    actual performance is the part with real information in it - agreement is
    unremarkable, disagreement is worth a look.
    """
    from ..engine.sectors import divergences, score_sectors

    rows = ctx.get("sector_outlook") or []
    if not rows:
        return ""

    P = ['<div class="card">', '<h2>What conditions favour%s</h2>' % _help("outlook")]
    P.append('<p class="section-lead">Each sector is exposed to different forces. '
             'Utilities carry heavy debt and behave like bonds; banks earn a spread '
             'that widens with rates; energy revenue is largely the oil price. This '
             'ranks them by how well <em>today\u2019s</em> readings suit what each one '
             'is exposed to.</p>')

    vmax = max([abs(r["score"]) for r in rows] + [0.35])
    P.append('<div class="scroll"><table>')
    P.append('<tr><th>Sector</th><th>Fit with conditions</th><th></th>'
             '<th>Actual 1M vs S&amp;P</th></tr>')
    for r in rows:
        tone = DIVERGE_POS if r["score"] >= 0 else DIVERGE_NEG
        driver = "; ".join(r["drivers"]) if r["drivers"] else "no dominant driver"
        actual = r.get("actual")
        P.append('<tr>')
        P.append('<td><span class="dd-term" tabindex="0" data-tip="%s">%s</span> '
                 '<span style="color:var(--muted);">%s</span>'
                 '<div style="font-size:11.5px;color:var(--muted);margin-top:2px;">%s</div></td>'
                 % (_esc(r["why"]), _esc(r["name"]), _esc(r["symbol"]), _esc(driver)))
        P.append('<td class="num" style="color:%s;font-weight:600;">%+.2f</td>' % (tone, r["score"]))
        P.append('<td>%s</td>' % _diverging_bar(r["score"], vmax,
                                                "%s fit %+.2f" % (r["symbol"], r["score"])))
        P.append('<td class="num">%s</td>'
                 % ("-" if actual is None else "%+.1fpp" % actual))
        P.append('</tr>')
    P.append('</table></div>')

    gaps = divergences(rows)
    if gaps:
        P.append('<div style="margin-top:16px;">')
        P.append('<div style="font-size:12px;letter-spacing:.9px;text-transform:uppercase;'
                 'color:var(--muted);font-weight:700;margin-bottom:8px;">'
                 'Where conditions and prices disagree</div>')
        for r, note in gaps:
            P.append('<div style="border-left:3px solid %s;padding:8px 13px;margin:8px 0;">'
                     '<div style="font-size:13.5px;font-weight:600;">%s '
                     '<span style="color:var(--muted);font-weight:400;">%s</span></div>'
                     '<div style="font-size:12.5px;color:var(--ink-2);margin-top:3px;">%s.</div>'
                     '</div>' % (STATUS["watch"], _esc(r["name"]), _esc(r["symbol"]), _esc(note)))
        P.append('</div>')

    P.append('<div class="note"><strong>This is positioning, not prediction.</strong> '
             'It says which sectors are exposed to the forces currently in play, based '
             'on what each one owns and owes. It does not say what any price will do, '
             'and these relationships are averages that break in any individual month. '
             'Where the market already disagrees, the market may simply be right.</div>')
    P.append('</div>')
    return "".join(P)


def _ticker_strip(ctx):
    """Prices across the top, most-watched first.

    Deliberately plain percentages rather than a colour-blocked heatmap: a grid of
    coloured tiles encodes one number twice (position and hue) and reads as urgency
    even on a quiet day. The numbers are the point.
    """
    rows = ctx.get("ticker") or []
    if not rows:
        return ""
    P = ['<div class="strip">']
    for r in rows:
        chg = r.get("chg_1d")
        color = ("var(--muted)" if chg is None
                 else DIVERGE_POS if chg > 0 else DIVERGE_NEG if chg < 0 else "var(--muted)")
        P.append('<div class="tk" data-tip="%s">'
                 '<div class="tk-name">%s</div>'
                 '<div class="tk-val">%s</div>'
                 '<div class="tk-chg" style="color:%s;">%s</div></div>'
                 % (_esc(r["name"]), _esc(r["label"]), _esc(r["value"]),
                    color, "-" if chg is None else "%+.2f%%" % chg))
    P.append('</div>')
    return "".join(P)


def _watchlist_section(ctx):
    """The few numbers that matter most right now, and when each updates next."""
    from .explain import tooltip
    items = ctx.get("watchlist") or []
    if not items:
        return ""

    from .email_builder import fmt_value
    P = ['<div class="card">', '<h2>What to watch next%s</h2>' % _help("watch")]
    P.append('<p class="section-lead">Not a fixed list. These are the indicators most '
             'in play today, ranked by how close they sit to a level that would '
             'signal, how heavily they weigh on the verdict, and how much they are '
             'currently moving.</p>')

    for i, it in enumerate(items, start=1):
        r = it["value"]
        tip = tooltip(it["sid"])
        nxt = it.get("next_release")
        P.append('<div class="watch">')
        P.append('<div class="watch-n">%d</div>' % i)
        P.append('<div class="watch-body">')
        P.append('<div class="watch-head"><span class="watch-name">%s</span>'
                 '<span class="watch-val">%s</span></div>'
                 % ('<span class="dd-term" tabindex="0" data-tip="%s">%s</span>'
                    % (_esc(tip), _esc(r.name)) if tip else _esc(r.name),
                    _esc(fmt_value(r))))
        P.append('<div class="watch-why">Watching because it %s.</div>' % _esc(it["reason"]))
        if tip:
            what = tip.split("  \u2014  ")[0]
            why = tip.split("  \u2014  ")[-1]
            P.append('<div class="watch-what"><strong>What it is:</strong> %s</div>' % _esc(what))
            P.append('<div class="watch-what"><strong>Why it matters:</strong> %s</div>' % _esc(why))
        if nxt:
            P.append('<div class="watch-next">Next update expected around %s</div>'
                     % _esc(nxt.strftime("%d %b")))
        P.append('</div></div>')

    P.append('<div class="note">Next-update dates are estimated from each series\u2019 own '
             'release history rather than a fixed calendar, so they drift by a day or two '
             'but never go stale.</div>')
    P.append('</div>')
    return "".join(P)


def _change_section(ctx):
    """What would move the verdict - the honest form of a forecast."""
    items = ctx.get("would_change") or []
    if not items:
        return ""
    P = ['<div class="card">', '<h2>What would change this view%s</h2>' % _help("change")]
    P.append('<p class="section-lead">Rather than guessing where prices go, these are '
             'the specific, observable things that would shift the reading. Each one '
             'is checkable, so you can look rather than take it on trust.</p>')
    for it in items:
        P.append('<div style="border-left:3px solid %s;padding:9px 14px;margin:10px 0;">'
                 '<div style="font-size:14px;font-weight:600;">%s</div>'
                 '<div style="font-size:13px;color:var(--ink-2);margin-top:4px;'
                 'line-height:1.55;">%s</div></div>'
                 % (STATUS["watch"], _esc(it["what"]), _esc(it["detail"].strip())))
    P.append('<div class="note"><strong>These are conditions, not predictions.</strong> '
             'Nothing here says any of them will happen - only that if one does, the '
             'reading changes, and here is the number to look at.</div>')
    P.append('</div>')
    return "".join(P)


def _more(title, hint, inner, open_by_default=False):
    """A collapsed layer. The page should answer the question at a glance and let
    curiosity, not obligation, pull the reader deeper."""
    if not inner:
        return ""
    return ('<details class="more"%s><summary><span>%s <span class="hint">%s</span>'
            '</span></summary><div class="inner">%s</div></details>'
            % (" open" if open_by_default else "", _esc(title), _esc(hint), inner))


def build(ctx, records=None, alerts=None, synthetic=False,
          chain_stages=None, chain_summary=None):
    """Render the full dashboard to a self-contained HTML string.

    Layered on purpose: the verdict, the map and the five cards answer "what is going
    on" without a single expandable opened. Everything below is one tap away for a
    reader who wants the evidence.
    """
    records = records or []

    history = {}
    for rec in records:
        for sid, value in rec.get("readings", {}).items():
            history.setdefault(sid, []).append(value)

    map_svg = _regime_map(ctx)
    map_block = ""
    if map_svg:
        map_block = (
            '<div class="card"><h2>Where we are%s</h2>'
            '<div class="split"><div>%s</div>'
            '<div class="maplead"><p>The two forces that shape most market conditions '
            'are how fast the economy is growing and how fast prices are rising. '
            'Together they carve out six familiar situations.</p>'
            '<p><strong>The red dot is today.</strong> The grey labels show where each '
            'named situation normally sits, so you can see not just where we are but '
            'what we are drifting toward.</p>'
            '<p style="font-size:11.5px;color:var(--muted);">The full verdict weighs '
            'five forces; this picture shows the two biggest. Treat it as orientation, '
            'not the whole answer.</p></div></div></div>'
            % (_help("regime"), map_svg))

    signals_inner = _signals_section(ctx)
    body = [
        '<div class="wrap">',
        _ticker_strip(ctx),
        '<div class="warn">These figures come from <strong>fabricated fixture data</strong> '
        'and are not real market observations. Run with live API keys to replace them.'
        '</div>' if synthetic else "",

        # --- layer 1: the answer ---
        _hero(ctx),
        _alerts_section(alerts or []),
        map_block,
        '<div class="card"><h2>The five forces%s</h2>'
        '<p class="section-lead">Each one is measured against its own history. The dot '
        'shows where today sits between the two extremes.</p>%s</div>'
        % (_help("pillar"), _pillar_cards(ctx)),
        signals_inner,
        _watchlist_section(ctx),
        _change_section(ctx),
        _outlook_section(ctx),

        # --- layer 2: the evidence, one tap away ---
        _more("Where money is moving", "sector performance vs the S&P 500",
              _sectors_inner(ctx)),
        _more("How we got here", "regime history over recent years",
              _timeline_inner(records)),
        _more("The debt & debasement theory", "five stages, each testable",
              _chain_inner(chain_stages or [], chain_summary or {})),
        _more("Every number behind the verdict", "reference detail",
              _drilldown_inner(ctx, history)),
        _more("What this cannot tell you", "known gaps", _gaps_inner()),
        _howto_section(),

        '<div class="note" style="text-align:center;margin-top:22px;">'
        'Generated by market-intel &middot; %s</div>' % _esc(ctx["date"].isoformat()),
        '</div>',
    ]

    from .pages import NAV_CSS, TABS
    nav = ['<nav class="nav">']
    for href, label, _hint in TABS:
        cur = ' aria-current="page"' if href == "index.html" else ""
        nav.append('<a href="%s"%s>%s</a>' % (href, cur, _esc(label)))
    nav.append('</nav>')

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Market Regime Dashboard</title>"
        "<style>%s%s</style></head><body>%s<script>%s</script></body></html>"
        % (CSS, NAV_CSS, "".join(body).replace('<div class="wrap">', '<div class="wrap">' + "".join(nav), 1), TIP_JS))
