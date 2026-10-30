"""Stocks and coins: what you hold, a row each, in its own currency.

Each row: its name and symbol (and, when its market is closed, that the change is the last
session's), the past week as a line, its price and the day's change with an arrow. Everything is
sized from the element's own box, so the same page reads on the 5.79" strip, the 4.2", the 2.9"
and an 800 × 480 screen: rows share the height, a wide box takes two columns before rows get too
small, and holdings that still don't fit are counted ("+2 more") rather than squeezed.

The words under each row are what it is: a market that's closed says "At close Thu", never a
change that looks live. Prices older than three updates say when they're from; coin prices
credit CoinGecko, as its free use asks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import clock, hero
from . import theme as T
from .todo import now_in
from .words import cap, money, percent, say

MIN_LABEL = 13                  # a row's name: smaller disappears on e-ink at arm's length
MIN_SUB = 12
STALE = 15 * 60                 # prices older than this say when they're from
COL_MIN_W = 250                 # a column narrower than this can't hold a name, a price and a change


@dataclass
class Cell:
    box: tuple
    label: str = ""
    sub: str = ""
    price: str = ""
    change: str = ""
    up: int = 0                 # 1 up, -1 down, 0 neither
    trend: list = field(default_factory=list)
    trend_box: tuple | None = None
    label_px: int = MIN_LABEL
    sub_px: int = MIN_SUB
    label_w: int = 0            # the room each text has
    right_w: int = 0


@dataclass
class Plan:
    cells: list
    note: str = ""
    note_px: int = MIN_SUB
    message: str = ""
    rule_px: int = 2


def _since_words(row: dict, now: datetime) -> str:
    if row.get("kind") == "coin":
        return say("markets.day")
    if row.get("open", True):
        return ""
    since = str(row.get("since") or "")
    try:
        day = datetime.fromisoformat(since).date()
    except ValueError:
        return say("markets.closed")
    if day == now.date():
        return say("markets.at_close")
    return say("markets.at_close_on", day=cap(clock.date(datetime(day.year, day.month, day.day), "wd")))


def _sub(row: dict, now: datetime) -> str:
    if row.get("missing"):
        return say("markets.not_found")
    sym = row.get("symbol") or ""
    if row.get("kind") == "coin":
        sym = row.get("currency") or ""
    return " · ".join(x for x in (sym, _since_words(row, now)) if x)


def _texts(row: dict, now: datetime) -> tuple[str, str, int]:
    """(price, change, direction) as the screen's language writes them."""
    price = row.get("price")
    if price is None:
        return ("" if row.get("missing") else "…"), "", 0
    p = money(price, row.get("currency") or "", int(row.get("decimals", 2)))
    pct = row.get("change_pct")
    if pct is None:
        return p, "", 0
    return p, percent(pct), (1 if pct > 0.005 else -1 if pct < -0.005 else 0)


def _note(data: dict, now: datetime) -> str:
    parts = []
    at = data.get("at")
    if isinstance(at, (int, float)) and now.timestamp() - at > STALE:
        when = datetime.fromtimestamp(at, timezone.utc).astimezone(now.tzinfo)
        stamp = clock.hm(when) if when.date() == now.date() else f"{clock.date(when, 'date')} {clock.hm(when)}"
        parts.append(say("markets.prices_from", time=stamp))
    if data.get("coins"):
        parts.append(say("markets.credit"))
    return " · ".join(parts)


def _grid(n: int, w: int, h: int, min_row: int) -> tuple[int, int]:
    """(columns, rows per column): one column while rows stay readable, then two or more side by
    side while each is wide enough. What still doesn't fit is counted in the note."""
    cols = 1
    while math.ceil(n / cols) * min_row > h and w // (cols + 1) >= COL_MIN_W:
        cols += 1
    return cols, max(1, min(math.ceil(n / cols), h // min_row))


def plan(data: dict | None, box, now: datetime | None = None, scale: float = 1.0) -> Plan | None:
    """Where everything goes, and in what words: drawn by draw(), and what the tests check fits."""
    if not isinstance(data, dict):
        return None
    now = now or now_in(data.get("tz"))
    x, y, w, h = box
    rows = [r for r in data.get("rows") or [] if isinstance(r, dict)]
    if not rows:
        return Plan([], message=say("markets.add"))
    if data.get("failing") and all(r.get("price") is None for r in rows):
        return Plan([], message=say("markets.no_answer"))
    note_px = max(MIN_SUB, min(18, h // 14))
    min_row = MIN_LABEL + MIN_SUB + 12
    cols, per = _grid(len(rows), w, h - (note_px + note_px // 2), min_row)
    shown = rows[:cols * per]
    rest = len(rows) - len(shown)
    note = " · ".join(x for x in (say("markets.more", rest) if rest else "", _note(data, now)) if x)
    avail = h - ((note_px + note_px // 2) if note else 0)
    gap = max(12, w // 40) if cols > 1 else 0
    cw = (w - gap * (cols - 1)) // cols
    rh = avail // per
    # One size for every row, so they read as a list; the price a little larger than the name.
    label_px = max(MIN_LABEL, min(round(rh * 0.4 * scale), 52))
    texts = [(r, _texts(r, now), _sub(r, now)) for r in shown]
    trend_w = min(round(cw * 0.24), 200) if cw >= 440 else 0
    for _ in range(80):
        sub_px = max(MIN_SUB, round(label_px * 0.62))
        price_px = round(label_px * 1.12)
        pf, sf = T.font(price_px, bold=True), T.font(sub_px, bold=False)
        right_w = max([T.text_width(p, pf) for _, (p, _, _), _ in texts] +
                      [T.text_width(c, sf) + round(sub_px * 1.1) for _, (_, c, _), _ in texts] + [1])
        label_w = cw - right_w - trend_w - (2 if trend_w else 1) * max(12, label_px // 2)
        if (label_w >= cw * 0.3 and price_px + sub_px + max(4, label_px // 4) <= rh - 6) or label_px <= MIN_LABEL:
            break
        label_px -= 1
    sub_px = max(MIN_SUB, round(label_px * 0.62))
    lf, sf = T.font(label_px, bold=True), T.font(sub_px, bold=False)
    cells = []
    for k, (r, (p, c, up), sub) in enumerate(texts):
        col, line = divmod(k, per)
        cx, cy = x + col * (cw + gap), y + line * rh
        tb = None
        if trend_w and len(r.get("trend") or []) >= 2:
            tb = (cx + cw - right_w - trend_w - max(12, label_px // 2), cy + round(rh * 0.22), trend_w, max(8, round(rh * 0.56)))
        label = hero.shorten(r.get("label") or r.get("symbol") or "", lf, max(1, label_w))
        cells.append(Cell((cx, cy, cw, rh), label, hero.shorten(sub, sf, max(1, label_w)), p, c, up,
                          list(r.get("trend") or []), tb, label_px, sub_px, label_w, right_w))
    return Plan(cells, note=hero.shorten(note, T.font(note_px, bold=False), w) if note else "", note_px=note_px,
                rule_px=max(2, round(min(w, h) / 160)))


def _triangle(d, cx, cy, size, up: int) -> None:
    half = size / 2
    if up > 0:
        pts = [(cx - half, cy + half * 0.8), (cx + half, cy + half * 0.8), (cx, cy - half * 0.9)]
    else:
        pts = [(cx - half, cy - half * 0.8), (cx + half, cy - half * 0.8), (cx, cy + half * 0.9)]
    d.polygon(pts, fill=T.BLACK)


def _trend(d, box, points, width) -> None:
    tx, ty, tw, th = box
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    n = len(points)
    xy = [(tx + round(i * (tw - 1) / (n - 1)), ty + th - 1 - round((v - lo) / span * (th - 1))) for i, v in enumerate(points)]
    d.line(xy, fill=T.BLACK, width=width, joint="curve")
    r = width + 1                                   # where it is now: a dot at the end
    ex, ey = xy[-1]
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=T.BLACK)


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    pl = plan(data, box, scale=scale)
    if pl is None:
        return                                      # nothing fetched yet stays blank, so nothing flashes
    if pl.message:
        hero.message(d, box, pl.message)
        return
    x, y, w, h = box
    line = pl.rule_px
    for k, c in enumerate(pl.cells):
        cx, cy, cw, rh = c.box
        lf, sf = T.font(c.label_px, bold=True), T.font(c.sub_px, bold=False)
        pf = T.font(round(c.label_px * 1.12), bold=True)
        cap_top = pf.getbbox("A")[1]                 # the capitals' top, so name and price line up
        p_h = pf.getbbox("A")[3] - cap_top
        gap = max(4, c.label_px // 4)
        block = p_h + gap + c.sub_px
        top = cy + max(0, (rh - block) // 2)
        if cy > y:                                   # a hairline between rows, not above the first
            d.rectangle([(cx, cy - line // 2), (cx + cw - 1, cy - line // 2 + line - 1)], fill=T.BLACK)
        base = top + p_h                             # name and price share a baseline
        d.text((cx, base), c.label, font=lf, fill=T.BLACK, anchor="ls")
        sub_y = base + gap
        d.text((cx, sub_y), c.sub, font=sf, fill=T.BLACK, anchor="lt")
        right = cx + cw
        if c.price:
            d.text((right, base), c.price, font=pf, fill=T.BLACK, anchor="rs")
        if c.change:
            cw_ = T.text_width(c.change, sf)
            d.text((right - cw_, sub_y), c.change, font=sf, fill=T.BLACK, anchor="lt")
            if c.up:
                tri = max(7, round(c.sub_px * 0.62))
                _triangle(d, right - cw_ - round(c.sub_px * 0.3) - tri / 2, sub_y + c.sub_px * 0.55, tri, c.up)
        if c.trend_box:
            _trend(d, c.trend_box, c.trend, max(3, round(rh / 24)))
    if pl.note:
        nf = T.font(pl.note_px, bold=False)
        d.text((x + w, y + h), pl.note, font=nf, fill=T.BLACK, anchor="rd")
