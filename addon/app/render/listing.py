"""A heading and rows that fill their box: the one way the list pages fit what they show.

Commute times, departures and the mail list each turn what they read into rows (a title, a second
line, a value at the right, a small note before it, a badge at the left) and leave the fitting
here: rows take a size that reads, a second line only when every row shown can have one, then
"and 3 more" in the last row. Sizes are the 5.79"'s and scale with the element's text size, and a
short box (the 2.9") shrinks them so the heading and one row still fit. Hierarchy is size and
weight; a row that needs you is inverted, never grey.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import hero
from . import theme as T
from .words import say

ITEM_PX = 30            # a row's words, as the to-do list's
HEAD_PX = 22            # the heading and its count
MIN_ITEM = 12
MIN_HEAD = 11


@dataclass
class Row:
    title: str
    sub: str = ""           # a second line, smaller, when every row shown has room for one
    value: str = ""         # at the right, bold
    note: str = ""          # before the value, smaller
    badge: str = ""         # at the left, inverted: a line's number
    loud: bool = False      # the value inverted: this one needs you (much slower than usual)


def _s(px: float, scale: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(px * scale)))


def sizes(h: int, scale: float, has_head: bool = True) -> tuple[int, int]:
    """(row words, heading) for a box `h` tall: the usual sizes, smaller when the box is too short
    for the heading and one row."""
    item, head = _s(ITEM_PX, scale, MIN_ITEM, 96), _s(HEAD_PX, scale, MIN_HEAD, 64)
    while item > MIN_ITEM and (head + item // 3 if has_head else 0) + row_height(item) > h:
        item -= 1
        head = max(MIN_HEAD, min(head, round(item * 0.75)))
    return item, head


def row_height(item_px: int) -> int:
    return item_px + max(8, round(item_px * 0.36))


def fit(count: int, avail_h: int, pitch: int, more: int = 0) -> tuple[int, int]:
    """(rows shown, how many more): when they don't all fit, "and 4 more" takes the last row; with
    room for one row only, that row and no line saying more (there's no room to say it)."""
    n = max(1, avail_h // pitch)
    if count + (1 if more else 0) <= n:
        return count, more
    if n == 1:
        return 1, 0
    return n - 1, count - (n - 1) + more


GROW = 1.8              # few rows grow to fill their box, up to this much larger


@dataclass
class Layout:
    item_px: int
    head_px: int
    show_head: bool
    two_lines: bool
    shown: int
    more: int

    def row_h(self) -> int:
        return row_height(self.item_px)

    def sub_px(self) -> int:
        return max(MIN_ITEM, round(self.item_px * 0.72))

    def pitch(self) -> int:
        """A row's height: its words, and its second line's whole height (descenders too) under them."""
        if not self.two_lines:
            return self.row_h()
        return self.row_h() + sum(T.font(self.sub_px(), bold=False).getmetrics()) + max(2, self.sub_px() // 6)

    def top(self) -> int:
        return self.head_px + max(6, self.item_px // 3) if self.show_head else 0


def _whole(rows: list[Row], w: int, px: int, two_lines: bool = False) -> bool:
    """Whether every row's title, badge and value fit side by side at this size (its note can give
    way), and its second line under them."""
    if w <= 0:
        return True
    title_f, item_f = T.font(px, bold=True), T.font(px, bold=False)
    badge_f = T.font(max(MIN_ITEM, round(px * 0.8)), bold=True)
    gap, pad = max(10, px // 2), max(6, px // 4)
    badge = max((T.text_width(r.badge, badge_f) for r in rows if r.badge), default=0)
    lead = badge + 2 * pad + gap if badge else 0
    for r in rows:
        need = lead + T.text_width(r.title, item_f if r.badge else title_f)
        if r.value:
            need += gap + T.text_width(r.value, title_f) + (2 * pad if r.loud else 0)
        if need > w:
            return False
        if two_lines and r.sub and lead + T.text_width(r.sub, T.font(max(MIN_ITEM, round(px * 0.72)), bold=False)) > w:
            return False
    return True


def arrange(h: int, rows: list[Row], scale: float, more: int = 0, show_head: bool = True, w: int = 0) -> Layout:
    """How rows fill a box w x h: their size, the heading, a second line or not, how many."""
    item, head = sizes(h, scale, show_head)
    has_sub = any(r.sub for r in rows)

    def at(item_px: int, head_px: int, with_head: bool) -> Layout:
        lay = Layout(item_px, head_px, with_head, False, 0, 0)
        avail = h - lay.top()
        if has_sub:
            lay.two_lines = True
            lay.shown, lay.more = fit(len(rows), avail, lay.pitch(), more)
            if lay.pitch() > avail:
                lay.two_lines = False                   # not even one row with its second line
            elif lay.shown < len(rows):
                # A second line only when it keeps every row: rows read before their details.
                one = fit(len(rows), avail, row_height(item_px), more)
                if one[0] > lay.shown:
                    lay.two_lines, (lay.shown, lay.more) = False, one
        if not lay.two_lines:
            lay.shown, lay.more = fit(len(rows), avail, lay.pitch(), more)
        return lay

    lay = at(item, head, show_head)
    if has_sub and not lay.two_lines:
        # A little smaller, if that keeps every row's second line (a message's subject, a route's way).
        for px in range(item - 1, max(MIN_ITEM, round(item * 0.8)) - 1, -1):
            smaller = at(px, max(MIN_HEAD, min(head, round(px * 0.75))), show_head)
            if smaller.two_lines and smaller.shown >= lay.shown:
                lay = smaller
                break
    if show_head and lay.shown < len(rows) and h < 4 * row_height(item):
        # A short box: the rows matter more than the heading.
        bare = at(*sizes(h, scale, False), False)
        if bare.shown > lay.shown:
            lay = bare
    if rows and lay.shown == len(rows) and not lay.more and _whole(rows, w, lay.item_px, lay.two_lines):
        # Few rows grow to fill the box, the heading with them, while they all still fit, in full.
        base, whole = lay, True
        for px in range(base.item_px + 1, round(base.item_px * GROW) + 1):
            bigger = at(px, round(base.head_px * px / base.item_px), base.show_head)
            if bigger.shown < len(rows) or bigger.two_lines != lay.two_lines or \
                    bigger.top() + bigger.shown * bigger.pitch() > h or (whole and not _whole(rows, w, px, base.two_lines)):
                break
            lay = bigger
    return lay


def heading(d, x: int, y: int, w: int, title: str, count: str, head_px: int) -> None:
    f = T.font(head_px, bold=True)
    mid = y + head_px // 2 + 2
    cw = T.text_width(count, f) if count else 0
    if count:
        d.text((x + w, mid), count, font=f, fill=T.BLACK, anchor="rm")
    d.text((x, mid), hero.shorten(title, f, max(1, w - cw - 16)), font=f, fill=T.BLACK, anchor="lm")


def message(d, box, text: str, item_px: int) -> None:
    """What a list says instead of rows (nothing to show, something to set up), at the rows' size,
    wrapped to two lines when it must."""
    x, y, w, h = box
    for px in range(item_px, MIN_ITEM - 1, -1):
        f = T.font(px, bold=True, text=text)
        lines = T.wrap_lines(text, f, w)
        lh = sum(f.getmetrics())
        if len(lines) <= 2 and lh * len(lines) <= h:
            break
    lines = lines[:2]
    if len(lines) == 2:
        lines[1] = hero.shorten(lines[1], f, w)
    top = y + (h - lh * len(lines)) // 2
    for k, line in enumerate(lines):
        d.text((x + w // 2, top + k * lh), hero.shorten(line, f, w), font=f, fill=T.BLACK, anchor="mt")


def _pill(d, box, text: str, f, *, fill=T.BLACK, ink=T.WHITE) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle([(x0, y0), (x1, y1)], radius=max(3, (y1 - y0) // 4), fill=fill)
    l, t, r, b = d.textbbox((0, 0), text, font=f, anchor="lt")
    d.text(((x0 + x1) / 2 - (l + r) / 2, (y0 + y1) / 2 - (t + b) / 2), text, font=f, fill=ink, anchor="lt")


def draw(img, d, box, *, title: str, rows: list[Row], count: str = "", empty: str = "", more: int = 0,
         scale: float = 1.0, show_head: bool = True) -> dict:
    """The heading and as many rows as fit. Returns what was shown: {"shown", "more"}."""
    x, y, w, h = box
    lay = arrange(h, rows, scale, more, show_head, w)
    item_px = lay.item_px
    if lay.show_head:
        heading(d, x, y, w, title, count, lay.head_px)
    top = y + lay.top()
    if not rows:
        if empty:
            message(d, (x, top, w, y + h - top), empty, item_px)
        return {"shown": 0, "more": more}

    item_f, title_f = T.font(item_px, bold=False), T.font(item_px, bold=True)
    note_f = T.font(max(MIN_ITEM, round(item_px * 0.72)), bold=True)
    sub_f = T.font(lay.sub_px(), bold=False)
    row_h, pitch, shown = lay.row_h(), lay.pitch(), lay.shown
    gap = max(10, item_px // 2)

    # Badges share one width, the widest's, so the titles after them start in one column.
    badge_f = T.font(max(MIN_ITEM, round(item_px * 0.8)), bold=True)
    badge_pad = max(6, item_px // 4)
    badge_w = max((T.text_width(r.badge, badge_f) for r in rows[:shown] if r.badge), default=0)
    badge_w = min(badge_w + 2 * badge_pad, w // 3) if badge_w else 0
    text_x = x + (badge_w + gap if badge_w else 0)

    for k, r in enumerate(rows[:shown]):
        r0 = top + k * pitch
        mid = r0 + row_h // 2
        right = x + w
        if r.value:
            vw = T.text_width(r.value, title_f)
            if r.loud:
                pad = max(6, item_px // 4)
                _pill(d, (right - vw - 2 * pad, mid - row_h // 2 + 2, right, mid + row_h // 2 - 2), r.value, title_f)
                vw += 2 * pad
            else:
                d.text((right, mid), r.value, font=title_f, fill=T.BLACK, anchor="rm")
            right -= vw + gap
        tf = item_f if r.badge else title_f
        if r.note:
            # The note gives way to the title: it shows only where the title keeps its words.
            nw = T.text_width(r.note, note_f)
            left_for_title = right - nw - gap - text_x
            if left_for_title >= min(T.text_width(r.title, tf), (right - text_x) * 0.55):
                d.text((right, mid), r.note, font=note_f, fill=T.BLACK, anchor="rm")
                right -= nw + gap
        if r.badge and badge_w:
            bh = min(row_h - 4, round(item_px * 1.2))
            _pill(d, (x, mid - bh // 2, x + badge_w, mid - bh // 2 + bh), hero.shorten(r.badge, badge_f, badge_w - 2 * badge_pad), badge_f)
        d.text((text_x, mid), hero.shorten(r.title, tf, max(1, right - text_x)), font=tf, fill=T.BLACK, anchor="lm")
        if lay.two_lines and r.sub:
            d.text((text_x, r0 + row_h - 2), hero.shorten(r.sub, sub_f, max(1, x + w - text_x)), font=sub_f, fill=T.BLACK, anchor="lt")
    if lay.more:
        d.text((text_x, top + shown * pitch + row_h // 2), say("and_more", lay.more), font=item_f, fill=T.BLACK, anchor="lm")
    return {"shown": shown, "more": lay.more}
