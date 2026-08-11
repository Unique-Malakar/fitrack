"""Render the morning brief as multipart HTML + plain text.

Email-client constraints drive the markup: inline styles only, table-based layout,
no flexbox/grid, no <style> block (Gmail strips much of it), explicit background
colours (several clients auto-invert otherwise). The plain-text part is a genuine
fallback that mirrors the spec's drafted layout, not an afterthought.
"""
from __future__ import annotations

TONE_COLOR = {
    "good":    ("#0b6b3a", "#e6f4ec"),
    "watch":   ("#8a6100", "#fdf3dd"),
    "bad":     ("#a01722", "#fdeaec"),
    "alert":   ("#a01722", "#fdeaec"),
    "unknown": ("#5a5f66", "#eef0f2"),
}
TONE_MARK = {"good": "+", "watch": "~", "bad": "!", "alert": "!", "unknown": "?"}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


# ---------------------------------------------------------------- formatting

def fmt_value(reading):
    if reading is None or reading.value is None:
        return "n/a"
    return _fmt_num(reading.value, reading.decimals, reading.unit)


def _fmt_num(value, decimals, unit=""):
    if value is None:
        return "n/a"
    decimals = 2 if decimals is None else decimals
    if unit == "$":
        return "$%.*f" % (decimals, value)
    text = "%.*f" % (decimals, value)
    if unit == "%":
        return text + "%"
    if unit == "pp":
        return text + "pp"
    if unit in ("bps", "K", "$B", "$/mt", "net %", "idx", ""):
        return text + (" " + unit if unit and unit not in ("idx", "") else "")
    return text + " " + unit


def fmt_change(value, decimals, unit=""):
    if value is None:
        return "-"
    decimals = 2 if decimals is None else decimals
    sign = "+" if value > 0 else ""
    if unit == "bps":
        return "%s%.0f bps" % (sign, value)
    if unit in ("%", "pp"):
        return "%s%.*fpp" % (sign, decimals, value)
    return "%s%.*f" % (sign, decimals, value)


def movers(readings, limit=6):
    """Biggest moves relative to each series' own volatility, weighted by importance.

    Ranking by raw change would just surface whichever series has the largest units;
    ranking by own-sigma momentum is what makes 'what changed' meaningful.
    """
    scored = []
    for r in readings:
        if r is None or r.drift is None or r.stale:
            continue
        significance = abs(r.drift) * (0.5 + (r.weight or 1.0))
        if significance < 0.2:
            continue
        scored.append((significance, r))
    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:limit]]


def _mover_line(r):
    chg = r.chg_1w if r.chg_1w is not None else r.chg_1d
    window = "1w" if r.chg_1w is not None else "1d"
    return "%s: %s (%s %s), %s" % (
        r.name, fmt_value(r), fmt_change(chg, r.decimals, r.unit), window, r.direction)


# ---------------------------------------------------------------- plain text

def build_text(ctx):
    d, pillars, sig = ctx["diagnosis"], ctx["pillars"], ctx["signals"]
    L = []
    L.append("MARKET BRIEF - %s" % ctx["date"].strftime("%A, %d %B %Y"))
    L.append("")
    L.append("REGIME:    %s (confidence %.0f%%)" % (d.regime, d.confidence * 100))
    L.append("DIRECTION: %s" % d.direction)
    if d.runner_up and d.confidence < 0.55:
        L.append("           nearest alternative: %s" % d.runner_up)
    for note in d.notes or []:
        L.append("           note: %s" % note)

    L.append("")
    L.append("=== WHAT CHANGED ===")
    mv = movers(ctx["readings"])
    if mv:
        for r in mv:
            L.append("  * " + _mover_line(r))
    else:
        L.append("  Nothing moved meaningfully versus its own trend.")

    L.append("")
    L.append("=== INTERPRETATION ===")
    if sig:
        for s in sig:
            L.append("  [%s] %s" % (s.tone.upper(), s.title))
            L.append("      " + _wrap(s.detail, 72, "      "))
    else:
        L.append("  No cross-asset divergences detected. Pillars are internally consistent.")

    L.append("")
    L.append("=== PILLAR SCORES ===")
    for num in (1, 2, 3, 4, 5):
        p = pillars.get(num)
        if p is None:
            continue
        mark = TONE_MARK.get(p.risk_tone, "?")
        top = ", ".join("%s %s" % (r.name, fmt_value(r)) for r in p.readings[:2])
        L.append("  [%s] %-20s %-14s  %s" % (mark, p.name, p.state, top))
        if not p.known:
            L.append("      (insufficient data: %.0f%% coverage)" % (p.coverage * 100))

    L.append("")
    L.append("=== CAPITAL FLOW IMPLICATIONS ===")
    L.append("  Favored:    %s" % d.flows.get("favored", "-"))
    L.append("  Disfavored: %s" % d.flows.get("disfavored", "-"))

    L.append("")
    L.append("=== KEY LEVELS ===")
    L.append("  %-32s %12s  %10s %10s" % ("", "LEVEL", "1D", "CHG"))
    for r in ctx["key_levels"]:
        L.append("  %-32s %12s  %10s %10s" % (
            r.name[:32], fmt_value(r),
            fmt_change(r.chg_1d, r.decimals, r.unit),
            fmt_change(r.chg_1w, r.decimals, r.unit)))

    if ctx["sectors"]:
        L.append("")
        L.append("=== SECTOR SIGNALS (relative to SPY, percentage points) ===")
        L.append("  %-26s %8s %8s %8s" % ("", "1w", "1m", "3m"))
        for row in ctx["sectors"]:
            L.append("  %-26s %8s %8s %8s" % (
                "%s (%s)" % (row["name"][:19], row["symbol"]),
                _pp(row["rs"].get("1w")), _pp(row["rs"].get("1m")), _pp(row["rs"].get("3m"))))

    if ctx["global_rows"]:
        L.append("")
        L.append("=== GLOBAL WATCHLIST ===")
        for name, value, chg in ctx["global_rows"]:
            L.append("  %-28s %14s  %10s" % (name, value, chg))

    if ctx["errors"]:
        L.append("")
        L.append("=== DATA ISSUES (%d) ===" % len(ctx["errors"]))
        for sid, msg in sorted(ctx["errors"].items())[:12]:
            L.append("  %s: %s" % (sid, msg[:90]))

    L.append("")
    L.append("-" * 60)
    L.append("Levels are scored against each series' own trailing distribution, not")
    L.append("fixed thresholds. Direction of change is weighted above absolute level.")
    return "\n".join(L)


def _pp(v):
    return "-" if v is None else "%+.1f" % v


def _wrap(text, width, indent):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return ("\n" + indent).join(lines)


# ---------------------------------------------------------------- html

def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _badge(tone, label):
    fg, bg = TONE_COLOR.get(tone, TONE_COLOR["unknown"])
    return ('<span style="display:inline-block;padding:3px 9px;border-radius:11px;'
            'background:%s;color:%s;font-size:12px;font-weight:600;white-space:nowrap;">%s</span>'
            % (bg, fg, _esc(label)))


def _section(title):
    return ('<tr><td style="padding:26px 0 8px 0;">'
            '<div style="font-size:11px;letter-spacing:1.4px;text-transform:uppercase;'
            'color:#6b7280;font-weight:700;border-bottom:1px solid #e5e7eb;padding-bottom:6px;">'
            '%s</div></td></tr>' % _esc(title))


def _chg_cell(value, decimals, unit):
    if value is None:
        return '<td style="text-align:right;color:#9ca3af;font-family:%s;font-size:13px;padding:6px 0 6px 12px;">-</td>' % MONO
    color = "#0b6b3a" if value > 0 else ("#a01722" if value < 0 else "#6b7280")
    return ('<td style="text-align:right;color:%s;font-family:%s;font-size:13px;'
            'padding:6px 0 6px 12px;white-space:nowrap;">%s</td>'
            % (color, MONO, _esc(fmt_change(value, decimals, unit))))


def build_html(ctx):
    d, pillars, sig = ctx["diagnosis"], ctx["pillars"], ctx["signals"]
    dir_tone = {"Improving": "good", "Deteriorating": "bad"}.get(d.direction, "watch")
    P = []

    P.append('<div style="background:#f4f5f7;padding:20px 0;font-family:%s;">' % FONT)
    P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
             'width="100%" style="max-width:660px;margin:0 auto;background:#ffffff;'
             'border-radius:10px;border:1px solid #e5e7eb;">')
    P.append('<tr><td style="padding:26px 28px 30px 28px;">')
    P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')

    # header
    P.append('<tr><td>')
    P.append('<div style="font-size:11px;letter-spacing:1.6px;text-transform:uppercase;'
             'color:#9ca3af;font-weight:700;">Market Brief</div>')
    P.append('<div style="font-size:13px;color:#6b7280;margin-top:3px;">%s</div>'
             % _esc(ctx["date"].strftime("%A, %d %B %Y")))
    P.append('<div style="font-size:30px;font-weight:700;color:#111827;margin-top:14px;'
             'line-height:1.15;">%s</div>' % _esc(d.regime))
    P.append('<div style="margin-top:9px;">%s &nbsp; %s</div>'
             % (_badge(dir_tone, d.direction),
                _badge("unknown", "confidence %.0f%%" % (d.confidence * 100))))
    if d.runner_up and d.confidence < 0.55:
        P.append('<div style="font-size:13px;color:#6b7280;margin-top:9px;">'
                 'Sitting close to <strong>%s</strong> - treat the label as provisional.</div>'
                 % _esc(d.runner_up))
    for note in d.notes or []:
        P.append('<div style="font-size:12px;color:#8a6100;margin-top:6px;">%s</div>' % _esc(note))
    P.append('</td></tr>')

    # what changed
    P.append(_section("What changed"))
    P.append('<tr><td>')
    mv = movers(ctx["readings"])
    if mv:
        P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')
        for r in mv:
            chg = r.chg_1w if r.chg_1w is not None else r.chg_1d
            P.append('<tr>')
            P.append('<td style="padding:6px 0;font-size:14px;color:#111827;">%s</td>' % _esc(r.name))
            P.append('<td style="text-align:right;font-family:%s;font-size:13px;color:#111827;'
                     'padding:6px 0;white-space:nowrap;">%s</td>' % (MONO, _esc(fmt_value(r))))
            P.append(_chg_cell(chg, r.decimals, r.unit))
            P.append('</tr>')
        P.append('</table>')
    else:
        P.append('<div style="font-size:14px;color:#6b7280;padding:4px 0;">'
                 'Nothing moved meaningfully versus its own trend.</div>')
    P.append('</td></tr>')

    # interpretation
    P.append(_section("Interpretation"))
    P.append('<tr><td>')
    if sig:
        for s in sig:
            fg, bg = TONE_COLOR.get(s.tone, TONE_COLOR["unknown"])
            P.append('<div style="border-left:3px solid %s;background:%s;padding:11px 14px;'
                     'margin:9px 0;border-radius:0 6px 6px 0;">' % (fg, bg))
            P.append('<div style="font-weight:700;font-size:14px;color:%s;">%s</div>' % (fg, _esc(s.title)))
            P.append('<div style="font-size:13px;color:#374151;margin-top:5px;line-height:1.55;">%s</div>'
                     % _esc(s.detail))
            P.append('</div>')
    else:
        P.append('<div style="font-size:14px;color:#6b7280;padding:4px 0;">'
                 'No cross-asset divergences detected. Pillars are internally consistent.</div>')
    P.append('</td></tr>')

    # pillars
    P.append(_section("Pillar scores"))
    P.append('<tr><td>')
    P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')
    for num in (1, 2, 3, 4, 5):
        p = pillars.get(num)
        if p is None:
            continue
        detail = (", ".join("%s %s" % (r.name, fmt_value(r)) for r in p.readings[:2])
                  if p.known else "insufficient data (%.0f%% coverage)" % (p.coverage * 100))
        P.append('<tr>')
        P.append('<td style="padding:8px 0;font-size:14px;color:#111827;font-weight:600;'
                 'width:38%%;vertical-align:top;">%s</td>' % _esc(p.name))
        P.append('<td style="padding:8px 0;vertical-align:top;">%s</td>' % _badge(p.risk_tone, p.state))
        P.append('<td style="padding:8px 0 8px 12px;font-size:12px;color:#6b7280;'
                 'vertical-align:top;">%s</td>' % _esc(detail))
        P.append('</tr>')
    P.append('</table>')
    P.append('</td></tr>')

    # capital flows
    P.append(_section("Capital flow implications"))
    P.append('<tr><td>')
    for label, key, color in (("Favored", "favored", "#0b6b3a"), ("Disfavored", "disfavored", "#a01722")):
        P.append('<div style="font-size:13px;margin:5px 0;">'
                 '<span style="color:%s;font-weight:700;">%s:</span> '
                 '<span style="color:#374151;">%s</span></div>'
                 % (color, label, _esc(d.flows.get(key, "-"))))
    P.append('</td></tr>')

    # key levels
    P.append(_section("Key levels"))
    P.append('<tr><td>')
    P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')
    P.append('<tr><td></td>'
             '<td style="text-align:right;font-size:11px;color:#9ca3af;padding-bottom:4px;">LEVEL</td>'
             '<td style="text-align:right;font-size:11px;color:#9ca3af;padding:0 0 4px 12px;">1D</td>'
             '<td style="text-align:right;font-size:11px;color:#9ca3af;padding:0 0 4px 12px;">CHG</td></tr>')
    for r in ctx["key_levels"]:
        stale = ' <span style="color:#9ca3af;font-size:11px;">(stale)</span>' if r.stale else ""
        P.append('<tr style="border-top:1px solid #f3f4f6;">')
        P.append('<td style="padding:6px 0;font-size:13px;color:#374151;">%s%s</td>'
                 % (_esc(r.name), stale))
        P.append('<td style="text-align:right;font-family:%s;font-size:13px;color:#111827;'
                 'padding:6px 0;white-space:nowrap;">%s</td>' % (MONO, _esc(fmt_value(r))))
        P.append(_chg_cell(r.chg_1d, r.decimals, r.unit))
        P.append(_chg_cell(r.chg_1w, r.decimals, r.unit))
        P.append('</tr>')
    P.append('</table>')
    P.append('<div style="font-size:11px;color:#9ca3af;margin-top:8px;line-height:1.5;">'
             'CHG is the week-over-week move for daily series, and the move since the '
             'last release for weekly, monthly and quarterly ones. Monthly data has no '
             'daily change, so 1D is blank for it.</div>')
    P.append('</td></tr>')

    # sectors
    if ctx["sectors"]:
        P.append(_section("Sector signals - relative to SPY (pp)"))
        P.append('<tr><td>')
        P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')
        P.append('<tr><td></td>' + "".join(
            '<td style="text-align:right;font-size:11px;color:#9ca3af;padding:0 0 4px 12px;">%s</td>' % w
            for w in ("1W", "1M", "3M")) + '</tr>')
        for row in ctx["sectors"]:
            P.append('<tr style="border-top:1px solid #f3f4f6;">')
            P.append('<td style="padding:6px 0;font-size:13px;color:#374151;">%s '
                     '<span style="color:#9ca3af;">%s</span></td>'
                     % (_esc(row["name"]), _esc(row["symbol"])))
            for w in ("1w", "1m", "3m"):
                P.append(_chg_cell(row["rs"].get(w), 1, "pp"))
            P.append('</tr>')
        P.append('</table>')
        P.append('<div style="font-size:11px;color:#9ca3af;margin-top:8px;line-height:1.5;">%s</div>'
                 % _esc(ctx.get("sector_note", "")))
        P.append('</td></tr>')

    # global
    if ctx["global_rows"]:
        P.append(_section("Global watchlist"))
        P.append('<tr><td>')
        P.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">')
        for name, value, chg in ctx["global_rows"]:
            P.append('<tr style="border-top:1px solid #f3f4f6;">'
                     '<td style="padding:6px 0;font-size:13px;color:#374151;">%s</td>'
                     '<td style="text-align:right;font-family:%s;font-size:13px;color:#111827;'
                     'padding:6px 0;">%s</td>'
                     '<td style="text-align:right;font-family:%s;font-size:13px;color:#6b7280;'
                     'padding:6px 0 6px 12px;">%s</td></tr>'
                     % (_esc(name), MONO, _esc(value), MONO, _esc(chg)))
        P.append('</table></td></tr>')

    # data issues
    if ctx["errors"]:
        P.append(_section("Data issues (%d)" % len(ctx["errors"])))
        P.append('<tr><td>')
        for sid, msg in sorted(ctx["errors"].items())[:12]:
            P.append('<div style="font-size:12px;color:#6b7280;padding:2px 0;">'
                     '<span style="font-family:%s;color:#a01722;">%s</span> - %s</div>'
                     % (MONO, _esc(sid), _esc(msg[:110])))
        P.append('</td></tr>')

    P.append('<tr><td style="padding-top:24px;">'
             '<div style="border-top:1px solid #e5e7eb;padding-top:12px;font-size:11px;'
             'color:#9ca3af;line-height:1.6;">Levels are scored against each series\' own '
             'trailing distribution rather than fixed thresholds; direction of change is '
             'weighted above absolute level. Generated by market-intel.</div></td></tr>')

    P.append('</table></td></tr></table></div>')
    return "".join(P)


def build(ctx):
    """Returns (subject, text_body, html_body)."""
    d = ctx["diagnosis"]
    alerts = sum(1 for s in ctx["signals"] if s.tone == "alert")
    prefix = "[%d ALERT] " % alerts if alerts else ""
    subject = "%sMarket Brief %s - %s / %s" % (
        prefix, ctx["date"].strftime("%d %b"), d.regime, d.direction)
    return subject, build_text(ctx), build_html(ctx)
