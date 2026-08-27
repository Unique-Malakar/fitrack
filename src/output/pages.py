"""Multi-page shell: shared navigation, and the three tabs beyond the dashboard.

Static pages rather than a single-page app: GitHub Pages serves plain files, every
page is generated fresh each morning anyway, and a tab that fails to build simply
does not appear rather than breaking the ones that do.

The dashboard stays first and stays the default. The other tabs are additions, and
the ordering says so.
"""
from __future__ import annotations

from .assetcards import CSS as ASSET_CSS, cards
from .dashboard import CSS, TIP_JS, _help
from .email_builder import _esc

TABS = [
    ("index.html", "Dashboard", "the regime verdict and what drives it"),
    ("heatmap.html", "Heatmap", "today's moves, sized by company"),
    ("news.html", "News", "headlines, by topic"),
    ("watchlist.html", "Watchlist", "the tickers you track"),
    ("aicredit.html", "AI Credit", "the private-credit thesis, tested"),
]

NAV_CSS = """
.nav{display:flex;gap:2px;overflow-x:auto;margin:0 0 16px;border-bottom:1px solid var(--ring);
-webkit-overflow-scrolling:touch;}
.nav a{flex:0 0 auto;padding:10px 16px;font-size:14px;font-weight:600;
color:var(--muted);text-decoration:none;border-bottom:2px solid transparent;
white-space:nowrap;}
.nav a:hover{color:var(--ink);}
.nav a[aria-current]{color:var(--ink);border-bottom-color:var(--ink);}
.feed{padding:13px 0;border-bottom:1px solid var(--rule-soft,rgba(128,128,128,.12));}
.feed:last-child{border-bottom:none;}
.feed a{color:var(--ink);text-decoration:none;font-size:14.5px;font-weight:600;
line-height:1.4;}
.feed a:hover{text-decoration:underline;}
.feed-meta{font-size:11px;color:var(--muted);margin-top:4px;}
.feed-sum{font-size:13px;color:var(--ink-2);margin-top:5px;line-height:1.5;}
.empty{padding:26px 0;color:var(--muted);font-size:13.5px;line-height:1.6;
max-width:64ch;}
.pf{display:flex;justify-content:space-between;align-items:baseline;gap:14px;
padding:12px 0;border-bottom:1px solid var(--rule-soft,rgba(128,128,128,.12));}
.pf:last-child{border-bottom:none;}
.pf-sym{font-size:15px;font-weight:700;}
.pf-note{font-size:12px;color:var(--muted);margin-top:2px;}
.pf-val{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}
.addrow{display:flex;gap:8px;margin:4px 0 6px;}
.addrow input{flex:1;min-width:0;padding:9px 12px;font-size:14px;border-radius:8px;
border:1px solid var(--ring);background:var(--surface);color:var(--ink);
font-family:inherit;}
.addrow input:focus{outline:2px solid var(--ink);outline-offset:1px;}
.addrow button{padding:9px 18px;font-size:14px;font-weight:600;border-radius:8px;
border:1px solid var(--ring);background:var(--ink);color:var(--surface);cursor:pointer;
font-family:inherit;}
.addnote{font-size:12px;color:var(--muted);min-height:16px;margin-bottom:4px;}
.pf .rm{margin-left:12px;font-size:11px;padding:3px 9px;border-radius:6px;
border:1px solid var(--ring);background:transparent;color:var(--muted);cursor:pointer;
font-family:inherit;align-self:center;}
.pf .rm:hover{color:var(--ink);}
"""


def shell(title, active, body, generated=""):
    """One page, with the shared navigation."""
    nav = ['<nav class="nav">']
    for href, label, _hint in TABS:
        current = ' aria-current="page"' if href == active else ""
        nav.append('<a href="%s"%s>%s</a>' % (href, current, _esc(label)))
    nav.append('</nav>')

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><style>%s%s</style></head><body>'
        '<div class="wrap">%s%s'
        '<div class="note" style="text-align:center;margin-top:22px;">%s</div>'
        '</div><script>%s</script></body></html>'
        % (_esc(title), CSS, NAV_CSS + ASSET_CSS, "".join(nav), body,
           _esc(generated), TIP_JS))


# ------------------------------------------------------------------ heatmap

def heatmap_page(svg, error, as_of, assets=None, asset_cfg=None):
    body = ['<div class="card">', '<h2>Market heatmap</h2>']
    if svg:
        body.append('<p class="section-lead">Every box is a company. Its <strong>size</strong> '
                    'is how large the company is; its <strong>colour</strong> is how far it '
                    'moved today. Grouped by sector, so you can see whether a move is one '
                    'company or a whole industry.</p>')
        body.append(svg)
        body.append('<div class="legend" style="margin-top:12px;">'
                    '<span><i class="sw" style="background:#16a34a;"></i>up today</span>'
                    '<span><i class="sw" style="background:#e5484d;"></i>down today</span>'
                    '<span><i class="sw" style="background:#8b8f94;"></i>unchanged</span>'
                    '</div>')
        body.append('<div class="note">Green for up, red for down. That pair is the one '
                    'colourblind readers find hardest, so the red leans slightly orange to '
                    'separate better, and every box big enough to label carries its own '
                    'percentage &mdash; colour reinforces a number rather than replacing it. '
                    'Roughly seventy large companies, not the whole index.</div>')
    else:
        body.append('<div class="empty">The heatmap could not be built today.%s<br><br>'
                    'It depends on Yahoo Finance, which is an unofficial source and '
                    'occasionally stops responding. Everything else on this site uses '
                    'official feeds and is unaffected.</div>'
                    % (" <br><br>Reported: " + _esc(error) if error else ""))
    body.append('</div>')

    # Crypto and metals sit below the map: the map is US equities, and these are the
    # assets people watch precisely because they sit outside that system.
    assets = assets or {}
    asset_cfg = asset_cfg or {}
    if assets:
        body.append(cards("Crypto", asset_cfg.get("crypto", []), assets,
                          "Trades continuously, so the daily change has no closing "
                          "bell and moves at weekends too."))
        body.append(cards("Metals", asset_cfg.get("metals", []), assets,
                          "Front-month futures. Units differ by metal - gold and "
                          "silver per ounce, copper per pound, aluminium per tonne - "
                          "so compare each against its own history, not against "
                          "each other."))

    return shell("Market Heatmap", "heatmap.html", "".join(body),
                 "Prices as of %s" % as_of)


# --------------------------------------------------------------------- news

def news_page(by_topic, topic_labels, as_of):
    body = ['<div class="card">', '<h2>Headlines</h2>',
            '<p class="section-lead">Headlines only, carrying each publisher&rsquo;s own '
            'summary. Nothing here is re-worded, and none of it feeds the regime '
            'verdict &mdash; that is built from measured data alone. News is here '
            'because you asked for it, deliberately kept in its own tab.</p>',
            '</div>']

    total = 0
    for topic, label in topic_labels.items():
        items = by_topic.get(topic) or []
        total += len(items)
        if not items:
            continue
        body.append('<div class="card">')
        body.append('<h2>%s</h2>' % _esc(label))
        for it in items:
            when = it.published.strftime("%d %b, %H:%M") if it.published else ""
            body.append('<div class="feed">')
            link = it.link or "#"
            body.append('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                        % (_esc(link), _esc(it.title)))
            body.append('<div class="feed-meta">%s%s</div>'
                        % (_esc(it.source), (" &middot; " + _esc(when)) if when else ""))
            if it.summary:
                body.append('<div class="feed-sum">%s</div>' % _esc(it.summary))
            body.append('</div>')
        body.append('</div>')

    if not total:
        body.append('<div class="card"><div class="empty">No headlines were retrieved. '
                    'Feeds are fetched when the site is built, so this usually means the '
                    'sources were unreachable at that moment.</div></div>')

    return shell("Market News", "news.html", "".join(body),
                 "Headlines fetched %s" % as_of)


# ---------------------------------------------------------------- watchlist

WATCHLIST_JS = """
(function(){
 var KEY='mi.watchlist';
 var data=JSON.parse(document.getElementById('universe').textContent||'{}');
 var pinned=JSON.parse(document.getElementById('pinned').textContent||'[]');
 var list=document.getElementById('rows'), input=document.getElementById('add');
 var status=document.getElementById('status');
 function load(){try{return JSON.parse(localStorage.getItem(KEY)||'[]');}catch(e){return [];}}
 function save(v){try{localStorage.setItem(KEY,JSON.stringify(v));}catch(e){}}
 function fmt(n,d){return n===null||n===undefined?'-':n.toFixed(d===undefined?2:d);}
 function row(sym,q,isPinned){
  var d=document.createElement('div');d.className='pf';
  var chg=q&&q.c!==null&&q.c!==undefined?q.c:null;
  var col=chg===null?'var(--muted)':chg>0?'#2a78d6':chg<0?'#e34948':'var(--muted)';
  d.innerHTML='<div><div class="pf-sym">'+sym+'</div><div class="pf-note">'+
   (isPinned?'from your config file':'added on this device')+
   (q?'':' &middot; no price available')+'</div></div>'+
   '<div class="pf-val"><div style="font-size:15px;font-weight:600;">'+
   (q?fmt(q.p):'-')+'</div><div style="font-size:13px;font-weight:600;color:'+col+';">'+
   (chg===null?'-':(chg>0?'+':'')+chg.toFixed(2)+'%')+'</div></div>';
  if(!isPinned){
   var b=document.createElement('button');b.textContent='remove';b.className='rm';
   b.onclick=function(){save(load().filter(function(x){return x!==sym;}));render();};
   d.appendChild(b);
  }
  return d;
 }
 function render(){
  list.innerHTML='';
  var mine=load();
  var all=pinned.concat(mine.filter(function(s){return pinned.indexOf(s)<0;}));
  if(!all.length){list.innerHTML='<div class="empty">Nothing tracked yet. '+
   'Type a ticker above to add one.</div>';return;}
  all.forEach(function(s){list.appendChild(row(s,data[s],pinned.indexOf(s)>=0));});
 }
 function add(){
  var sym=(input.value||'').trim().toUpperCase();
  input.value='';
  if(!sym)return;
  if(!data[sym]){status.textContent='"'+sym+'" is not in the pre-loaded set. '+
   'Add it to config/portfolio.json to track it anyway.';return;}
  status.textContent='';
  var mine=load();
  if(mine.indexOf(sym)<0&&pinned.indexOf(sym)<0){mine.push(sym);save(mine);}
  render();
 }
 document.getElementById('addbtn').onclick=add;
 input.addEventListener('keydown',function(e){if(e.key==='Enter')add();});
 render();
})();
"""


def watchlist_page(rows, error, regime_name, favoured, disfavoured, as_of,
                   universe=None, pinned=None):
    import json as _json

    universe = universe or {}
    pinned = pinned or []

    body = ['<div class="card">', '<h2>Your watchlist</h2>']
    body.append('<p class="section-lead">Add a ticker and it stays on this device. '
                'Symbols in <code>config/portfolio.json</code> are pinned and appear '
                'on every device you open this from.</p>')
    body.append('<div class="addrow">'
                '<input id="add" type="text" placeholder="Add a ticker, e.g. NVDA" '
                'autocomplete="off" spellcheck="false" aria-label="Add a ticker">'
                '<button id="addbtn" type="button">Add</button></div>')
    body.append('<div id="status" class="addnote"></div>')

    if error:
        body.append('<div class="note">Prices could not be refreshed: %s</div>'
                    % _esc(error))

    body.append('<div id="rows"></div>')
    body.append('<script type="application/json" id="universe">%s</script>'
                % _json.dumps(universe))
    body.append('<script type="application/json" id="pinned">%s</script>'
                % _json.dumps(pinned))
    body.append('<div class="note">Prices are from the most recent build, not live. '
                'Tickers added here are remembered by this browser only &mdash; that is '
                'all a site with no server can do. Put anything you want on every '
                'device into the config file instead.<br><br>'
                'Current regime favours %s. It disfavours %s. Those are tendencies of '
                'the regime, not views on any company.</div>'
                % (_esc(favoured), _esc(disfavoured)))
    body.append('</div>')
    body.append('<script>%s</script>' % WATCHLIST_JS)

    return shell("Watchlist", "watchlist.html", "".join(body),
                 "Prices as of %s" % as_of)


# --------------------------------------------------------------- ai credit

def aicredit_page(stages, summary, not_measurable, as_of):
    """The AI / private-credit thesis, stage by stage.

    Same treatment as the debt chain: claim, test, reading, caveat. What separates
    this from the version circulating online is that a stage is allowed to say the
    condition is absent - and today most of them do.
    """
    from .dashboard import STATUS, STATUS_GLYPH

    body = ['<div class="card">', '<h2>The AI credit thesis, tested</h2>']
    body.append('<p class="section-lead">The argument: the AI buildout is funded by '
                'debt banks would not write, that debt sits in private credit, private '
                'credit sits with insurers, and if the data centres underearn, the '
                'losses land somewhere unprepared.</p>')
    body.append('<p class="section-lead">The mechanisms are real and partly '
                'measurable. The argument as usually told is not testable &mdash; it '
                'names a crisis window, and until that window passes nothing counts '
                'against it. So each stage below can read NOT FIRING.</p>')
    body.append('<div style="font-size:15px;font-weight:600;margin:14px 0 6px;">%s</div>'
                % _esc(summary.get("verdict", "")))
    body.append('</div>')

    for i, st in enumerate(stages):
        color = STATUS.get(st.tone, STATUS["unknown"])
        body.append('<div class="card" style="border-left:4px solid %s;">' % color)
        body.append('<div style="display:flex;flex-wrap:wrap;gap:9px;align-items:baseline;">'
                    '<span style="font-weight:700;font-size:16px;">Stage %d &middot; %s</span>'
                    '<span style="color:%s;font-weight:700;font-size:12px;">%s %s</span></div>'
                    % (st.num, _esc(st.name), color,
                       STATUS_GLYPH.get(st.tone, ""), _esc(st.label)))
        body.append('<div style="font-size:12px;color:var(--muted);margin-top:7px;">'
                    '<strong>Claim:</strong> %s</div>' % _esc(st.claim or ""))
        body.append('<div style="font-size:12px;color:var(--muted);margin-top:2px;">'
                    '<strong>Test:</strong> %s</div>' % _esc(st.test or ""))
        body.append('<div style="font-size:13.5px;color:var(--ink-2);margin-top:9px;'
                    'line-height:1.55;">%s</div>' % _esc(st.detail or ""))
        if st.metrics:
            body.append('<div class="scroll"><table style="margin-top:10px;">')
            for label, value in st.metrics:
                body.append('<tr><td style="font-size:12.5px;color:var(--ink-2);">%s</td>'
                            '<td class="num" style="font-size:12.5px;">%s</td></tr>'
                            % (_esc(label), _esc(value)))
            body.append('</table></div>')
        if st.caveat:
            body.append('<div style="font-size:11.5px;color:var(--muted);margin-top:10px;'
                        'padding-top:9px;border-top:1px dashed var(--grid);line-height:1.6;">'
                        '<strong>Caveat:</strong> %s</div>' % _esc(st.caveat))
        body.append('</div>')

    body.append('<div class="card">')
    body.append('<h2>What this cannot test</h2>')
    body.append('<p class="section-lead">Roughly half the argument is not measurable '
                'with free data. Listing it beats quietly leaving it out.</p>')
    for title, why in not_measurable:
        body.append('<div style="padding:10px 0;border-bottom:1px solid '
                    'var(--rule-soft,rgba(128,128,128,.12));">'
                    '<div style="font-size:14px;font-weight:600;">%s</div>'
                    '<div style="font-size:13px;color:var(--ink-2);margin-top:3px;'
                    'line-height:1.55;">%s</div></div>' % (_esc(title), _esc(why)))
    body.append('<div class="note">No individual company is tracked here. The thesis '
                'names particular asset managers and insurers, but publishing a row '
                'implying a named firm is systemically dangerous is a strong claim, and '
                'the ownership assertions behind it are not verified by this system. '
                'Sector-level gauges show the same stress without naming anyone.'
                '<br><br>This page tracks conditions. It is not advice, and it '
                'deliberately contains no suggested allocation.</div>')
    body.append('</div>')

    return shell("AI Credit Thesis", "aicredit.html", "".join(body),
                 "Data as of %s" % as_of)
