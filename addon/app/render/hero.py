"""One fact, large: an icon, a value, what it means, and something beside it.

The shared look of the widgets that show one number at a glance (sunrise,
solar this month, grid now, energy cost, now playing). Everything is sized
from the element's own box, so the same widget reads on a 5.79" strip, a
2.9" and a TRMNL without hand-fitting: the value takes the height it can,
the words under it follow at a fixed ratio, and nothing goes below a size
e-ink can still show.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import theme as T

CAPTION = 0.30          # the words under a value, as a share of its size
ASIDE = 0.45            # the value beside the main one, as a share of its size
MIN_CAPTION = 12        # smaller disappears on e-ink at arm's length
MIN_VALUE = 18


@dataclass
class Fact:
    value: str
    caption: str = ""
    icon: str = ""


Box = tuple[int, int, int, int]


def icon(img, d, name: str, box: Box) -> None:
    """An MDI icon fitted into a box, through the icon element's crisp path."""
    if not name:
        return
    from .layout import _draw_icon          # layout imports this module
    x, y, w, h = box
    _draw_icon(img, d, {"icon": name, "x": x, "y": y, "w": w, "h": h}, "")


def shorten(text: str, f, max_w: int) -> str:
    text = str(text or "")
    if T.text_width(text, f) <= max_w:
        return text
    while len(text) > 1 and T.text_width(text + "…", f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _size_for(text: str, max_w: int, max_h: int, start: int, floor: int, bold=True) -> int:
    return T.fit_size(text, max(1, max_w), max(1, max_h), max(floor, start), floor=floor, bold=bold)


def _layout(fact: Fact, w: int, h: int, scale: float) -> tuple[int, int, int]:
    """(icon size, value size, caption size) for a fact in a w x h area."""
    value_px = min(round(h * 0.46 * scale), round(h * 0.62))
    has_icon = bool(fact.icon)
    for _ in range(40):
        icon_px = round(value_px * 0.95) if has_icon else 0
        text_w = w - (icon_px + round(value_px * 0.22) if has_icon else 0)
        fits = _size_for(fact.value, text_w, h, value_px, MIN_VALUE)
        if fits >= value_px or value_px <= MIN_VALUE:
            break
        value_px = max(MIN_VALUE, min(fits, value_px - 1))
    cap_px = max(MIN_CAPTION, round(value_px * CAPTION))
    return (round(value_px * 0.95) if has_icon else 0), value_px, cap_px


def draw_fact(img, d, fact: Fact, box: Box, *, scale: float = 1.0, align: str = "left") -> int:
    """A fact filling its box: icon at the left, the value, its caption under it.
    Returns where the value's ink starts, so what's beside it can line up."""
    x, y, w, h = box
    icon_px, value_px, cap_px = _layout(fact, w, h, scale)
    vf, cf = T.font(value_px, bold=True, text=fact.value), T.font(cap_px, bold=False, text=fact.caption)
    v_asc, _ = vf.getmetrics()
    v_top = vf.getbbox(fact.value or "0")[1]        # the ink starts below the ascent line
    ink_h = v_asc - v_top
    gap = round(cap_px * 0.8) if fact.caption else 0
    block_h = ink_h + (gap + cap_px if fact.caption else 0)
    top = y + max(0, (h - block_h) // 2)
    text_x = x + (icon_px + round(value_px * 0.22) if icon_px else 0)
    text_w = x + w - text_x
    if align == "center":
        widest = max(T.text_width(fact.value, vf), T.text_width(fact.caption, cf) if fact.caption else 0)
        shift = max(0, (text_w - widest) // 2)
        text_x += shift
        x += shift
        text_w -= shift
    if icon_px:
        icon(img, d, fact.icon, (x, top + (ink_h - icon_px) // 2, icon_px, icon_px))
    d.text((text_x, top - v_top), shorten(fact.value, vf, text_w), font=vf, fill=T.BLACK)
    if fact.caption:
        d.text((text_x, top + ink_h + gap), shorten(fact.caption, cf, text_w), font=cf, fill=T.BLACK, anchor="lt")
    return top


def draw_aside(img, d, fact: Fact, box: Box, value_px: int, top: int | None = None) -> None:
    """A smaller fact at the right of its box: icon and value on a line, caption under, right-aligned.
    `top`: where its value starts (level with the main value's), else centred."""
    x, y, w, h = box
    value_px = max(MIN_CAPTION + 2, value_px)
    icon_px = round(value_px * 0.95) if fact.icon else 0
    gap_i = round(value_px * 0.25) if fact.icon else 0
    vf = T.font(_size_for(fact.value, w - icon_px - gap_i, h, value_px, MIN_CAPTION), bold=True, text=fact.value)
    cap_px = max(MIN_CAPTION, round(value_px * 0.55))
    cf = T.font(cap_px, bold=False, text=fact.caption)
    v_asc, _ = vf.getmetrics()
    v_top = vf.getbbox(fact.value or "0")[1]
    ink_h = v_asc - v_top
    gap = round(cap_px * 0.7) if fact.caption else 0
    block_h = ink_h + (gap + cap_px if fact.caption else 0)
    if top is None or w < h * 1.2:                 # stacked under the main fact: centred in its own part
        top = y + max(0, (h - block_h) // 2)
    right = x + w
    vw = T.text_width(fact.value, vf)
    d.text((right - vw, top - v_top), fact.value, font=vf, fill=T.BLACK)
    if icon_px:
        icon(img, d, fact.icon, (right - vw - gap_i - icon_px, top + (ink_h - icon_px) // 2, icon_px, icon_px))
    if fact.caption:
        d.text((right, top + ink_h + gap), shorten(fact.caption, cf, w), font=cf, fill=T.BLACK, anchor="rt")


def message(d, box: Box, text: str) -> None:
    """What a widget says instead of its fact (nothing to show, something to set up), centred."""
    x, y, w, h = box
    for px in range(max(MIN_CAPTION, min(h // 6, 26)), MIN_CAPTION - 1, -1):
        # Smaller until it's three lines at most and fits the box (longer languages need it), then cut
        f = T.font(px, bold=True, text=text)
        lines = T.wrap_lines(text, f, w)
        asc, desc = f.getmetrics()
        lh = asc + desc
        if len(lines) <= 3 and lh * len(lines) <= h:
            break
    if len(lines) > 3:
        lines = lines[:2] + [shorten(lines[2] + " " + " ".join(lines[3:]), f, w)]
    top = y + (h - lh * len(lines)) // 2
    for k, line in enumerate(lines):
        d.text((x + w // 2, top + k * lh), shorten(line, f, w), font=f, fill=T.BLACK, anchor="mt")


def split(box: Box, share: float, gap: int) -> tuple[Box, Box]:
    """A box cut into a main part and what's beside it: side by side when wide, stacked when not."""
    x, y, w, h = box
    if w >= h * 1.6:
        side_w = round(w * share)
        return (x, y, w - side_w - gap, h), (x + w - side_w, y, side_w, h)
    side_h = round(h * share)
    return (x, y, w, h - side_h - gap), (x, y + h - side_h, w, side_h)


def draw(img, d, box: Box, main: Fact, *, aside: Fact | None = None,
         beside: Callable[[Box], None] | None = None, share: float = 0.34, scale: float = 1.0) -> None:
    """The whole widget: the main fact, and either a smaller fact or a drawing (a chart) beside it."""
    if aside is None and beside is None:
        draw_fact(img, d, main, box, scale=scale)
        return
    gap = max(8, box[3] // 12)
    main_box, side_box = split(box, share, gap)
    top = draw_fact(img, d, main, main_box, scale=scale)
    if beside is not None:
        beside(side_box)
    else:
        _, value_px, _ = _layout(main, main_box[2], main_box[3], scale)
        # Level with the main value only beside it; stacked under it, the aside is centred in its own part.
        draw_aside(img, d, aside, side_box, round(value_px * ASIDE), top=top if side_box[1] == main_box[1] else None)


def draw_pair(img, d, box: Box, left: Fact, right: Fact, *, scale: float = 1.0) -> None:
    """Two facts alike, with a hairline between them (wide) or above the second (tall)."""
    x, y, w, h = box
    line = max(2, round(min(w, h) / 120))
    if w >= h * 1.6:
        half = (w - line) // 2
        pad = max(8, half // 14)
        a, b = (x, y, half - pad, h), (x + half + line + pad, y, half - pad, h)
        # One size for both, so they read as a pair.
        size = min(_layout(left, a[2], a[3], scale)[1], _layout(right, b[2], b[3], scale)[1])
        d.rectangle([(x + half, y + h // 8), (x + half + line - 1, y + h - h // 8)], fill=T.BLACK)
    else:
        half = (h - line) // 2
        a, b = (x, y, w, half - 4), (x, y + half + line + 4, w, half - 4)
        size = min(_layout(left, a[2], a[3], scale)[1], _layout(right, b[2], b[3], scale)[1])
        d.rectangle([(x + w // 10, y + half), (x + w - w // 10, y + half + line - 1)], fill=T.BLACK)
    for fact, part in ((left, a), (right, b)):
        s = scale * size / max(1, _layout(fact, part[2], part[3], scale)[1])
        draw_fact(img, d, fact, part, scale=s, align="center")


@dataclass
class Line:
    """A line of text a widget has placed: where, how large, and the room it was given (so a test
    can check it fits). `anchor` as PIL's: "lt" top-left, "rt" top-right, "mt" top-centre."""
    text: str
    x: int
    y: int
    w: int
    px: int
    bold: bool = False
    anchor: str = "lt"

    def font(self):
        return T.font(self.px, bold=self.bold, text=self.text)

    def fits(self) -> bool:
        return T.text_width(self.text, self.font()) <= self.w


def place_line(text: str, x: int, y: int, w: int, px: int, *, bold=False, anchor="lt", floor=MIN_CAPTION) -> Line:
    """A line of text at the largest size up to `px` (not under `floor`) that fits `w`, shortened
    with an ellipsis when even `floor` doesn't."""
    size = px
    while size > floor and T.text_width(text, T.font(size, bold=bold, text=text)) > w:
        size -= 1
    f = T.font(size, bold=bold, text=text)
    return Line(shorten(text, f, w), x, y, w, size, bold, anchor)


def draw_lines(d, lines) -> None:
    for ln in lines:
        d.text((ln.x, ln.y), ln.text, font=ln.font(), fill=T.BLACK, anchor=ln.anchor)


def wrap_into(text: str, x: int, y: int, w: int, h: int, px: int, *, floor=MIN_CAPTION) -> list[Line]:
    """A paragraph in the box: as large as fits up to `px`, the last line ellipsized when even
    `floor` doesn't hold it all."""
    for size in range(max(floor, px), floor - 1, -1):
        f = T.font(size, bold=False, text=text)
        asc, desc = f.getmetrics()
        lh = round((asc + desc) * 1.08)
        lines = T.wrap_lines(text, f, w)
        room = max(0, h // lh)
        if len(lines) <= room or size == floor:
            break
    if not room:
        return []
    if len(lines) > room:
        lines = lines[:room - 1] + [shorten(" ".join(lines[room - 1:]) + "…", f, w)]
    return [Line(shorten(t, f, w), x, y + k * lh, w, size) for k, t in enumerate(lines)]
