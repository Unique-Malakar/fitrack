"""Render alerts as a short, scannable email.

Deliberately terse. An alert is read on a phone, probably while doing something
else, so it leads with what happened and why it matters and stops there. The
morning brief is where context belongs.
"""
from __future__ import annotations

from .email_builder import FONT, MONO, _esc

TONE_COLOR = {
    "critical": ("#d03b3b", "#fdeaec"),
    "serious":  ("#b8531f", "#fdf0e8"),
    "warning":  ("#8a6100", "#fdf3dd"),
}
TONE_ICON = {"critical": "!!", "serious": "!", "warning": "~"}


def build(alerts, today):
    """Returns (subject, text_body, html_body)."""
    lead = alerts[0]
    subject = "[ALERT] %s" % lead.label
    if len(alerts) > 1:
        subject += " (+%d more)" % (len(alerts) - 1)
    return subject, _text(alerts, today), _html(alerts, today)


def _text(alerts, today):
    L = ["MARKET ALERT - %s" % today.strftime("%A, %d %B %Y"), ""]
    for a in alerts:
        L.append("[%s] %s" % (a.tone.upper(), a.label))
        L.append("    %s" % (a.detail or ""))
        L.append("    Why: %s" % a.why)
        L.append("    As of: %s" % (a.as_of or "n/a"))
        L.append("")
    L.append("-" * 58)
    L.append("Triggered on a single-session move. Each alert stays quiet after")
    L.append("firing until it resets or materially worsens.")
    return "\n".join(L)


def _html(alerts, today):
    P = ['<div style="background:#f4f5f7;padding:20px 0;font-family:%s;">' % FONT,
         '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
         'width="100%" style="max-width:600px;margin:0 auto;background:#ffffff;'
         'border-radius:10px;border:1px solid #e5e7eb;">',
         '<tr><td style="padding:24px 26px 28px 26px;">',
         '<div style="font-size:11px;letter-spacing:1.6px;text-transform:uppercase;'
         'color:#9ca3af;font-weight:700;">Market Alert</div>',
         '<div style="font-size:13px;color:#6b7280;margin-top:3px;">%s</div>'
         % _esc(today.strftime("%A, %d %B %Y"))]

    for a in alerts:
        fg, bg = TONE_COLOR.get(a.tone, TONE_COLOR["warning"])
        P.append('<div style="border-left:4px solid %s;background:%s;padding:13px 16px;'
                 'margin:16px 0 0 0;border-radius:0 6px 6px 0;">' % (fg, bg))
        # Icon + label pairing: tone is never carried by colour alone.
        P.append('<div style="font-weight:700;font-size:15px;color:%s;">'
                 '<span style="font-family:%s;">%s</span> %s</div>'
                 % (fg, MONO, TONE_ICON.get(a.tone, "*"), _esc(a.label)))
        if a.detail:
            P.append('<div style="font-family:%s;font-size:14px;color:#111827;'
                     'margin-top:6px;">%s</div>' % (MONO, _esc(a.detail)))
        P.append('<div style="font-size:13px;color:#374151;margin-top:7px;'
                 'line-height:1.55;">%s</div>' % _esc(a.why))
        P.append('<div style="font-size:11px;color:#9ca3af;margin-top:7px;">'
                 'as of %s &nbsp;·&nbsp; severity: %s</div>'
                 % (_esc(a.as_of or "n/a"), _esc(a.tone)))
        P.append('</div>')

    P.append('<div style="border-top:1px solid #e5e7eb;margin-top:22px;padding-top:12px;'
             'font-size:11px;color:#9ca3af;line-height:1.6;">Triggered on a single-session '
             'move. Each alert stays quiet after firing until it resets or materially '
             'worsens, so a persistent condition will not repeat daily.</div>')
    P.append('</td></tr></table></div>')
    return "".join(P)
