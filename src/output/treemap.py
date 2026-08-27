"""Squarified treemap: box area is market capitalisation, colour is the daily move.

Two levels - sectors first, then constituents within each sector rectangle - which
is what makes the familiar finance heatmap readable: you can see at a glance that
technology is large and red before reading a single ticker.

The layout is the standard squarified algorithm. Naive slice-and-dice produces long
thin slivers for small values, which are impossible to label and misleading to
compare; squarifying keeps boxes near square so their areas stay comparable.

Colour is green for up and red for down, the convention every finance heatmap uses.

That pair is the one red-green colourblind readers struggle with, so two things
offset it: the red leans slightly orange, which separates better under protanopia
and deuteranopia than a pure red, and every box large enough to label carries its
own percentage - so colour reinforces a number rather than being the only channel.
"""
from __future__ import annotations

from .email_builder import _esc

POS, NEG, FLAT = "#16a34a", "#e5484d", "#8b8f94"


def _shade(pct, cap=3.0):
    """Colour intensity scaled to the size of the move, capped so one wild day
    does not flatten every other box to the same tone."""
    if pct is None:
        return FLAT
    strength = min(abs(pct) / cap, 1.0)
    base = POS if pct > 0 else NEG if pct < 0 else FLAT
    if base == FLAT:
        return FLAT
    # Blend toward the surface for small moves.
    r, g, b = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)
    mix = 0.30 + 0.70 * strength
    r = int(r * mix + 245 * (1 - mix))
    g = int(g * mix + 245 * (1 - mix))
    b = int(b * mix + 245 * (1 - mix))
    return "#%02x%02x%02x" % (r, g, b)


def _worst(row, side):
    """Worst aspect ratio in a candidate row - the squarify quality measure.

    An earlier version took unused `length`/`total_area` parameters and guarded on
    `length <= 0`. Since the call site passed zero, this returned infinity every
    time, so the row-break comparison was always inf < inf and never fired. Every
    box ended up in one row and the map degenerated into slivers.
    """
    if not row or side <= 0:
        return float("inf")
    s = sum(row)
    if s <= 0:
        return float("inf")
    rmax, rmin = max(row), min(row)
    if rmin <= 0:
        return float("inf")
    return max((side * side * rmax) / (s * s), (s * s) / (side * side * rmin))


def squarify(items, x, y, width, height):
    """Lay out [(value, payload), ...] into rectangles filling the given box."""
    items = [(v, p) for v, p in items if v and v > 0]
    if not items:
        return []
    items.sort(key=lambda t: -t[0])

    total = sum(v for v, _ in items)
    if total <= 0 or width <= 0 or height <= 0:
        return []
    scale = (width * height) / total
    scaled = [(v * scale, p) for v, p in items]

    out = []
    cx, cy, cw, ch = x, y, width, height
    row = []

    def flush():
        nonlocal cx, cy, cw, ch, row
        if not row:
            return
        s = sum(v for v, _ in row)
        vertical = cw >= ch
        if vertical:
            rw = s / ch if ch else 0
            oy = cy
            for v, p in row:
                rh = (v / s) * ch if s else 0
                out.append((cx, oy, rw, rh, p))
                oy += rh
            cx += rw
            cw -= rw
        else:
            rh = s / cw if cw else 0
            ox = cx
            for v, p in row:
                rw = (v / s) * cw if s else 0
                out.append((ox, cy, rw, rh, p))
                ox += rw
            cy += rh
            ch -= rh
        row = []

    for value, payload in scaled:
        side = min(cw, ch)
        current = [v for v, _ in row]
        if row and _worst(current, side) <= _worst(current + [value], side):
            flush()
            side = min(cw, ch)
        row.append((value, payload))
    flush()
    return out


def render(quotes, sector_map, width=980, height=560, gap=2):
    """The full two-level map as inline SVG."""
    sectors = []
    for sector, names in sector_map.items():
        members = [quotes[n] for n in names if n in quotes and quotes[n].market_cap]
        if not members:
            continue
        cap = sum(m.market_cap for m in members)
        weighted = sum((m.change_pct or 0) * m.market_cap for m in members) / cap
        sectors.append((cap, {"sector": sector, "members": members, "change": weighted}))

    if not sectors:
        return ""

    boxes = squarify(sectors, 0, 0, width, height)
    P = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;" role="img" '
         'aria-label="Market heatmap: box size is company size, colour is today\'s move">'
         % (width, height)]

    for sx, sy, sw, sh, payload in boxes:
        if sw <= 2 or sh <= 2:
            continue
        members = payload["members"]
        inner = [(m.market_cap, m) for m in members]
        label_h = 15 if sh > 46 else 0

        P.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" '
                 'stroke="var(--ink-2)" stroke-width="1" opacity="0.35"/>'
                 % (sx, sy, sw, sh))
        if label_h:
            # Drop the percentage, then truncate the name, rather than letting the
            # label run past the box edge and cut a number mid-digit.
            name = payload["sector"].upper()
            budget = int((sw - 8) / 5.6)
            label = "%s %+.2f%%" % (name, payload["change"])
            if len(label) > budget:
                label = name if len(name) <= budget else name[:max(budget - 1, 3)] + "\u2026"
            P.append('<text x="%.1f" y="%.1f" font-size="9.5" font-weight="700" '
                     'letter-spacing="0.6" fill="var(--ink-2)" '
                     'font-family="system-ui,sans-serif">%s</text>'
                     % (sx + 4, sy + 11, _esc(label)))

        for bx, by, bw, bh, q in squarify(inner, sx + 1, sy + label_h + 1,
                                          max(sw - 2, 1), max(sh - label_h - 2, 1)):
            if bw <= gap or bh <= gap:
                continue
            tip = "%s  %.2f  %+.2f%%  $%.0fB" % (
                q.symbol, q.price, q.change_pct or 0, (q.market_cap or 0) / 1e9)
            P.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" '
                     'fill="%s" data-tip="%s"/>'
                     % (bx, by, max(bw - gap, 0.5), max(bh - gap, 0.5),
                        _shade(q.change_pct), _esc(tip)))
            if bw > 40 and bh > 26:
                size = 12 if bw > 78 and bh > 44 else 9
                P.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="%d" '
                         'font-weight="700" fill="#ffffff" pointer-events="none" '
                         'font-family="system-ui,sans-serif" style="paint-order:stroke;'
                         'stroke:rgba(0,0,0,.30);stroke-width:2px;">%s</text>'
                         % (bx + bw / 2, by + bh / 2 - 1, size, _esc(q.symbol)))
                if bh > 40:
                    P.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="%d" '
                             'fill="#ffffff" pointer-events="none" opacity="0.95" '
                             'font-family="system-ui,sans-serif" style="paint-order:stroke;'
                             'stroke:rgba(0,0,0,.30);stroke-width:2px;">%+.2f%%</text>'
                             % (bx + bw / 2, by + bh / 2 + size, max(size - 2, 8),
                                q.change_pct or 0))

    P.append('</svg>')
    return "".join(P)
