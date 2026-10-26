"""World clock: up to four cities, each its name and its time, filling the box together.

The user's call (21 Oct): all cities alike, fitted. With 2, 3 or 4 cities the
widget tries each way of arranging them (side by side, stacked, 2 x 2) and
keeps the one that gives the largest time for its box, so the same page
reads well on the wide 5.79", the 4.2", a TRMNL and upright.

Times come from the IANA time zone database (zoneinfo), so daylight saving
follows the database, never a table of ours, and are written by clock.py
(12- or 24-hour). A city on another day than Home Assistant's gets "+1" or
"−1" after its time.

On a device that sleeps between updates a time would freeze, so there each
city shows how far it is from Home Assistant's time ("−7 h", "+5:30 h",
"Same time"), with its weekday when that differs (the user's call):
clocktime.py marks the element `asleep`.

    {"type": "world_clock", "zones": [{"tz": "", "label": ""}, {"tz": "America/New_York", "label": "New York"}]}

A zone of "" is Home Assistant's own, named after its city unless given a label.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import clock, hero
from .words import cap, say
from . import theme as T
from .todo import now_in

MOST = 4
MINUS = "−"                         # a real minus, not a hyphen


def city(tz_name: str) -> str:
    """A time zone's city, as people say it: "America/New_York" -> "New York"."""
    return str(tz_name or "").rsplit("/", 1)[-1].replace("_", " ")


REGIONS = ("Africa", "America", "Antarctica", "Asia", "Atlantic", "Australia", "Europe", "Indian", "Pacific")


def catalog(now_utc: datetime | None = None) -> list[dict]:
    """Every city the time zone database knows, for the editor's searchable list:
    [{"tz", "city", "region", "offset"}], by region then city. Old aliases (US/Eastern, Etc/GMT+3) are left out."""
    from zoneinfo import available_timezones
    now_utc = now_utc or datetime.now(timezone.utc)
    out = []
    for name in available_timezones():
        region = name.split("/", 1)[0]
        if region not in REGIONS or "/" not in name:
            continue
        off = now_utc.astimezone(ZoneInfo(name)).utcoffset()
        minutes = round(off.total_seconds() / 60)
        sign = "+" if minutes >= 0 else MINUS
        h, m = divmod(abs(minutes), 60)
        out.append({"tz": name, "city": city(name), "region": region, "offset": f"{sign}{h:02d}:{m:02d}"})
    return sorted(out, key=lambda z: (z["region"], z["city"]))


def zones(el: dict, home_tz: str | None) -> list[tuple[str, ZoneInfo]]:
    """(label, zone) for each city the element names, at most four; "" is Home Assistant's own zone.
    A zone the database doesn't know is left out."""
    out = []
    for z in (el.get("zones") or [])[:MOST]:
        if not isinstance(z, dict):
            continue
        name = str(z.get("tz") or "").strip() or str(home_tz or "")
        try:
            zone = ZoneInfo(name) if name else datetime.now().astimezone().tzinfo
        except Exception:
            continue
        label = str(z.get("label") or "").strip() or (city(name) if name else say("world.here"))
        out.append((label, zone))
    return out


def _offset(local: datetime, home: datetime) -> str:
    minutes = round((local.utcoffset() - home.utcoffset()).total_seconds() / 60)
    if minutes == 0:
        return say("world.same_time")
    sign = "+" if minutes > 0 else MINUS
    h, m = divmod(abs(minutes), 60)
    return f"{sign}{h}:{m:02d} h" if m else f"{sign}{h} h"


def slots(el: dict, home_tz: str | None, now_utc: datetime) -> list[tuple[str, str, str]]:
    """(label, big text, small mark) per city: its time and a day mark, or (asleep) its offset and weekday."""
    home = now_utc.astimezone(now_in(home_tz).tzinfo)
    out = []
    for label, zone in zones(el, home_tz):
        local = now_utc.astimezone(zone)
        days = (local.date() - home.date()).days
        if el.get("asleep"):
            out.append((label, _offset(local, home), cap(clock.date(local, "wd")) if days else ""))
        else:
            mark = "" if not days else (f"+{days}" if days > 0 else f"{MINUS}{-days}")
            out.append((label, clock.hm(local), mark))
    return out


def arrangements(n: int) -> list[tuple[int, int]]:
    """(rows, columns) that hold n cities with no empty place, except 3 never as 2 x 2."""
    return [(r, c) for r in range(1, n + 1) for c in range(1, n + 1) if r * c == n]


def _sizes(items, cw: int, ch: int, scale: float) -> tuple[int, int]:
    """(time px, label px) for every cell alike: the largest time that fits all of them."""
    label_share = 0.30
    time_h = ch / (1 + label_share * 1.5)
    px = min(round(time_h * 0.92 * scale), round(time_h))
    for _, big, mark in items:
        text = big + (" " + mark if mark else "")
        px = min(px, T.fit_size(text, max(1, cw - max(16, round(cw * 0.14))), max(1, round(time_h)), px, floor=hero.MIN_VALUE - 6))
    return px, max(hero.MIN_CAPTION, round(px * label_share))


def layout(n: int, w: int, h: int, items, scale: float = 1.0) -> tuple[int, int, int, int]:
    """(rows, columns, time px, label px): the arrangement with the largest time."""
    best = None
    for rows, cols in arrangements(n):
        gap = max(8, min(w, h) // 20)
        cw, ch = (w - gap * (cols - 1)) // cols, (h - gap * (rows - 1)) // rows
        px, lpx = _sizes(items, cw, ch, scale)
        if best is None or px > best[2]:
            best = (rows, cols, px, lpx)
    return best


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    data = data if isinstance(data, dict) else {}
    items = slots(el, data.get("tz"), datetime.now(timezone.utc))
    if not items:
        hero.message(d, box, say("world.add_city"))
        return
    x, y, w, h = box
    rows, cols, px, lpx = layout(len(items), w, h, items, scale)
    gap = max(8, min(w, h) // 20)
    cw, ch = (w - gap * (cols - 1)) // cols, (h - gap * (rows - 1)) // rows
    tf, lf, mf = T.font(px, bold=True), T.font(lpx, bold=False), T.font(max(hero.MIN_CAPTION, round(px * 0.42)), bold=True)
    line = max(2, round(min(w, h) / 120))
    asc, _ = tf.getmetrics()
    for k, (label, big, mark) in enumerate(items):
        r, c = divmod(k, cols)
        cx, cy = x + c * (cw + gap), y + r * (ch + gap)
        ink = asc - tf.getbbox(big or "0")[1]
        block = lpx + round(lpx * 0.5) + ink
        top = cy + max(0, (ch - block) // 2)
        d.text((cx + cw // 2, top), hero.shorten(label, lf, cw - 8), font=lf, fill=T.BLACK, anchor="mt")
        bw = T.text_width(big, tf)
        mw = (T.text_width(mark, mf) + round(px * 0.12)) if mark else 0
        bx = cx + (cw - bw - mw) // 2
        ty = top + lpx + round(lpx * 0.5)
        d.text((bx, ty - tf.getbbox(big or "0")[1]), big, font=tf, fill=T.BLACK)
        if mark:                                           # "+1" after the time, level with its top
            d.text((bx + bw + round(px * 0.12), ty), mark, font=mf, fill=T.BLACK, anchor="lt")
    # Hairlines between the cities, whole lengths, as the sunrise pair has.
    for c in range(1, cols):
        lx = x + c * (cw + gap) - gap // 2 - line // 2
        d.rectangle([(lx, y + h // 10), (lx + line - 1, y + h - h // 10)], fill=T.BLACK)
    for r in range(1, rows):
        ly = y + r * (ch + gap) - gap // 2 - line // 2
        d.rectangle([(x + w // 20, ly), (x + w - w // 20, ly + line - 1)], fill=T.BLACK)
