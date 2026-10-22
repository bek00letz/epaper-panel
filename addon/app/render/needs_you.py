"""What needs you in Home Assistant, drawn: its notifications, the updates waiting, and a badge.

What they show comes from sources/needs_you.py. Sizes are the 5.79"'s and
scale with the element's text size, like the to-do list: rows fill the box
at a size that reads, then "and 3 more". Hierarchy is size and weight, no grey.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import clock, hero
from . import theme as T
from .todo import now_in

ITEM_PX = 30            # a row's words, as the to-do list's
HEAD_PX = 22            # the heading and its count
MESSAGE_LINES = 2       # a notification's message, at most, when there's room for it


def _s(px: int, scale: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(px * scale)))


def _when(raw, now: datetime) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return when.replace(tzinfo=now.tzinfo)
    return when.astimezone(now.tzinfo) if now.tzinfo else when


def age_label(raw, now: datetime, asleep: bool = False) -> str:
    """How long ago, short: "now", "12 min", "2 h", "Yesterday", "Tue", "3 Oct".
    A device that sleeps between updates shows the time it came instead ("14:05"), which doesn't
    go stale while it sleeps, nor change the picture at every wake."""
    when = _when(raw, now)
    if when is None:
        return ""
    ago = now - when
    days = (now.date() - when.date()).days
    if days <= 0:
        if asleep:
            return clock.hm(when)
        if ago < timedelta(minutes=1):
            return "now"
        if ago < timedelta(hours=1):
            return f"{int(ago.total_seconds() // 60)} min"
        return f"{int(ago.total_seconds() // 3600)} h"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{when:%a}"
    return f"{when.day} {when:%b}"


def _rows(item_px: int) -> tuple[int, int]:
    """(row height, pitch): a row of words with room to breathe, as the to-do list's plain rows."""
    row_h = item_px + max(8, round(item_px * 0.36))
    return row_h, row_h


def _fit(count: int, avail_h: int, row_h: int, pitch: int) -> tuple[int, int]:
    """(rows shown, how many more): when they don't all fit, "and 4 more" takes the last row."""
    n = max(1, (avail_h - row_h) // pitch + 1)
    if count <= n:
        return count, 0
    if n == 1:
        return 1, 0                                  # the count in the heading says the rest
    return n - 1, count - (n - 1)


def _heading(d, x, y, w, title: str, count: str, head_px: int) -> None:
    f = T.font(head_px, bold=True)
    mid = y + head_px // 2 + 2
    cw = T.text_width(count, f) if count else 0
    if count:
        d.text((x + w, mid), count, font=f, fill=T.BLACK, anchor="rm")
    d.text((x, mid), hero.shorten(title, f, max(1, w - cw - 16)), font=f, fill=T.BLACK, anchor="lm")


def _empty(d, x, top, w, bottom, text: str, item_px: int) -> None:
    """What a list says when there's nothing in it: at its rows' size, in the middle, as the to-do list does."""
    f = T.font(item_px, bold=True)
    d.text((x + w // 2, (top + bottom) // 2), hero.shorten(text, f, w), font=f, fill=T.BLACK, anchor="mm")


# ------------------------------------------------------------------ notifications

def _messages(items, msg_f, text_w: int, row_h: int, avail_h: int) -> list[list[str]] | None:
    """Each notification's message as the lines it gets, if every one shown can have them:
    two lines each, then one, else none (None). Only for one or two notifications."""
    if not 0 < len(items) <= 2 or not any(i.get("message") for i in items):
        return None
    asc, desc = msg_f.getmetrics()
    lh = asc + desc
    for most in range(MESSAGE_LINES, 0, -1):
        lines = []
        for item in items:
            got = [hero.shorten(ln, msg_f, text_w) for ln in T.wrap_lines(item.get("message") or "", msg_f, text_w)]
            if len(got) > most:
                got = got[:most]
                got[-1] = hero.shorten(got[-1] + "…", msg_f, text_w)
            lines.append(got)
        used = sum(row_h + len(ls) * lh for ls in lines) + (len(items) - 1) * max(6, row_h // 4)
        if used <= avail_h:
            return lines
    return None


def draw_notifications(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    x, y, w, h = box
    item_px, head_px = _s(ITEM_PX, scale, 12, 96), _s(HEAD_PX, scale, 11, 64)
    title = str(el.get("title") or "").strip() or "Notifications"
    if not isinstance(data, dict):                   # not read yet: the heading, nothing else
        _heading(d, x, y, w, title, "", head_px)
        return
    now = now_in(data.get("tz"))
    items = [i for i in data.get("items") or [] if isinstance(i, dict) and i.get("title")]
    _heading(d, x, y, w, title, f"{len(items)} new" if items else "", head_px)
    top = y + head_px + max(8, item_px // 3)
    if not items:
        _empty(d, x, top, w, y + h, "No notifications", item_px)
        return

    row_h, pitch = _rows(item_px)
    item_f = T.font(item_px, bold=False)
    label_px = max(10, round(item_px * 0.8))
    label_f = T.font(label_px, bold=True)
    msg_f = T.font(max(hero.MIN_CAPTION, round(item_px * 0.8)), bold=False)
    dot = max(8, round(item_px * 0.42))              # a solid dot before each: one waiting for you
    text_x = x + dot + max(10, item_px // 2)
    asleep = bool(el.get("asleep"))

    lines = _messages(items, msg_f, x + w - text_x, row_h, y + h - top)
    if lines is not None:
        shown, more = len(items), 0
    else:
        shown, more = _fit(len(items), y + h - top, row_h, pitch)
    asc, desc = msg_f.getmetrics()
    r0 = top
    for k, item in enumerate(items[:shown]):
        mid = r0 + row_h // 2
        d.ellipse([(x, mid - dot // 2), (x + dot, mid - dot // 2 + dot)], fill=T.BLACK)
        right = x + w
        label = age_label(item.get("created"), now, asleep)
        if label:
            d.text((right, mid), label, font=label_f, fill=T.BLACK, anchor="rm")
            right -= T.text_width(label, label_f) + max(12, item_px // 2)
        d.text((text_x, mid), hero.shorten(item["title"], item_f, max(1, right - text_x)),
               font=item_f, fill=T.BLACK, anchor="lm")
        r0 += pitch
        if lines is not None:
            r0 -= pitch - row_h
            for line in lines[k]:
                d.text((text_x, r0), line, font=msg_f, fill=T.BLACK)
                r0 += asc + desc
            r0 += max(6, row_h // 4)
    if more:
        d.text((text_x, r0 + row_h // 2), f"and {more} more", font=item_f, fill=T.BLACK, anchor="lm")


# ------------------------------------------------------------------ updates

def count_words(n: int) -> str:
    return f"{n} waiting"


def draw_updates(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    """Each update waiting, by group (Home Assistant, add-ons, integrations, devices): the group
    once in a column of its own where there's room for it, then the name, then the new version."""
    from sources.needs_you import GROUP_NAMES, short_name
    x, y, w, h = box
    item_px, head_px = _s(ITEM_PX, scale, 12, 96), _s(HEAD_PX, scale, 11, 64)
    title = str(el.get("title") or "").strip() or "Updates"
    if not isinstance(data, dict):
        _heading(d, x, y, w, title, "", head_px)
        return
    items = [u for u in data.get("items") or [] if isinstance(u, dict) and u.get("name")]
    _heading(d, x, y, w, title, count_words(len(items)) if items else "", head_px)
    top = y + head_px + max(8, item_px // 3)
    if not items:
        _empty(d, x, top, w, y + h, "Everything's up to date", item_px)
        return

    row_h, pitch = _rows(item_px)
    item_f = T.font(item_px, bold=False)
    label_f = T.font(max(10, round(item_px * 0.8)), bold=True)
    gap = max(16, round(item_px * 0.6))
    groups = [g for g in GROUP_NAMES if any(u.get("group") == g for u in items)]
    col = max(T.text_width(GROUP_NAMES[g], label_f) for g in groups) + gap
    # The group's column only where the names keep most of the row; otherwise each says its full name.
    by_column = col <= w * 0.34
    shown, more = _fit(len(items), y + h - top, row_h, pitch)
    text_x = x + (col if by_column else 0)
    for k, u in enumerate(items[:shown]):
        mid = top + k * pitch + row_h // 2
        if by_column and (k == 0 or items[k - 1].get("group") != u.get("group")):
            d.text((x, mid), GROUP_NAMES.get(u.get("group"), ""), font=label_f, fill=T.BLACK, anchor="lm")
        right = x + w
        version = "Installing" if u.get("installing") else str(u.get("version") or "")
        # A version is shown whole or not at all ("2026.…" says nothing); the name needs the room more.
        if version and T.text_width(version, label_f) <= (w - (text_x - x)) * 0.4:
            d.text((right, mid), version, font=label_f, fill=T.BLACK, anchor="rm")
            right -= T.text_width(version, label_f) + gap
        name = short_name(u) if by_column else u["name"]
        d.text((text_x, mid), hero.shorten(name, item_f, max(1, right - text_x)), font=item_f, fill=T.BLACK, anchor="lm")
    if more:
        d.text((text_x, top + shown * pitch + row_h // 2), f"and {more} more", font=item_f, fill=T.BLACK, anchor="lm")


# ------------------------------------------------------------------ the badge

# What a badge's icon is, by what it counts (sources/needs_you.COUNTS).
BADGE_ICONS = {"updates": "mdi:arrow-up-circle-outline", "notifications": "mdi:bell-outline",
               "repairs": "mdi:wrench-outline", "all": "mdi:home-outline"}
MOST = 99               # more reads "99+", as an app badge does


def badge_text(n: int) -> str:
    return f"{MOST}+" if n > MOST else str(n)


def draw_badge(img, d, box, el: dict, data, *, scale: float = 1.0) -> int:
    """An icon with a solid dot at its top right holding the number, as on an app's icon. Nothing at all
    at zero or before it's read: a badge is there only when something needs you. Returns its number's
    size in px, drawn or not, for the editor's legibility note: its size is its box (the user's call)."""
    from sources.needs_you import badge_counts
    x, y, w, h = box
    side = min(w, h)
    dot = round(side * 0.42)                                         # centred on the icon's corner, as on a phone
    # One size for every number, from a digit: the pill grows for more digits, the digits never shrink.
    num_px = T.fit_size("8", dot, round(dot * 0.95), dot, floor=10, bold=True)
    try:
        n = int(data)
    except (TypeError, ValueError):
        return num_px
    if n <= 0:
        return num_px
    x0, y0 = x + (w - side) // 2, y + (h - side) // 2
    icon = round(side * 0.8)
    hero.icon(img, d, BADGE_ICONS[badge_counts(el)], (x0, y0 + side - icon, icon, icon))

    text = badge_text(n)
    f = T.font(num_px, bold=True)
    pill_w = max(dot, T.text_width(text, f) + round(dot * 0.5))     # two digits and more: a pill, growing left
    right, top = x0 + side, y0
    ring = max(3, round(dot / 9))                                    # paper round it, so it never runs into the icon
    d.rounded_rectangle([(right - pill_w - ring, top - ring), (right + ring, top + dot + ring)],
                        radius=dot // 2 + ring, fill=T.WHITE)
    d.rounded_rectangle([(right - pill_w, top), (right, top + dot)], radius=dot // 2, fill=T.BLACK)
    # Centred by the digits' own ink, not the font's line, so they sit optically in the middle.
    l, t, r, b = d.textbbox((0, 0), text, font=f, anchor="lt")
    d.text((right - pill_w / 2 - (l + r) / 2, top + dot / 2 - (t + b) / 2), text, font=f, fill=T.WHITE, anchor="lt")
    return num_px
