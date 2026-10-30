"""Place of the day: its name, where it is, a few lines about it, a few facts, and its streets.

Text on the left, the map on the right on a wide box (below it on a tall one, left out on a box
too small to read one). The map is drawn from OpenStreetMap's lines (sources/place.py) with hard
edges, as e-paper wants: main roads as hollow bands, other streets solid, rivers thick, lakes and
the sea hatched, and the place marked at the centre. Its credits are drawn on it.

The facts are the ones known: population, elevation, local time. On a device that sleeps between
updates a local time would stop, so there it shows how many hours apart the place is.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from . import clock, hero
from . import theme as T
from .hero import Line, place_line, wrap_into
from .todo import now_in
from .words import language, number, say

MAP_MIN = 120                   # a map smaller than this across is a smudge: left out


def _texts(data: dict, now: datetime, asleep: bool) -> tuple[str, str, str, list[tuple[str, str]]]:
    lang = language()
    name = (data.get("names") or {}).get(lang) or data.get("name") or ""
    region = (data.get("regions") or {}).get(lang) or data.get("region") or ""
    country = say(f"country.{data.get('country')}") if data.get("country") else ""
    where = ", ".join(x for x in (region if region and region != name else "", country) if x)
    summary = data.get("summary") or {}
    text = summary.get(lang) or summary.get("en") or ""
    facts = []
    if data.get("population"):
        facts.append((say("place.population"), number(data["population"], 0, group=True)))
    if data.get("elevation") is not None:
        facts.append((say("place.elevation"), say("place.metres", n=number(data["elevation"], 0, group=True))))
    try:
        tz = ZoneInfo(data.get("tz") or "")
    except Exception:
        tz = None
    if tz is not None:
        here = now.astimezone(tz)
        if asleep:
            from .worldclock import _offset
            facts.append((say("place.time_apart"), _offset(here, now)))
        else:
            facts.append((say("place.local_time"), clock.hm(here)))
    return name, where, text, facts


def _map_box(data: dict, box, show_map: bool):
    """(text box, map box or None)."""
    x, y, w, h = box
    if not show_map or not (data.get("map") or {}).get("lines"):
        return box, None
    gap = max(12, min(w, h) // 16)
    if w >= h * 1.3:
        mw = min(round(w * 0.42), round(h * 1.6))
        if mw >= MAP_MIN and h >= MAP_MIN * 0.8 and w - mw - gap >= 220:
            return (x, y, w - mw - gap, h), (x + w - mw, y, mw, h)
    elif h >= w * 0.9:
        mh = round(h * 0.45)
        if mh >= MAP_MIN and w >= MAP_MIN:
            return (x, y, w, h - mh - gap), (x, y + h - mh, w, mh)
    return box, None


def plan(el: dict, data, box, now: datetime | None = None, scale: float = 1.0):
    """(lines of text, map box or None). None when there's nothing to draw yet."""
    if not isinstance(data, dict) or not data.get("name"):
        return None
    now = now or now_in(data.get("home_tz"))
    name, where, text, facts = _texts(data, now, bool(el.get("asleep")))
    if el.get("show_facts") is False:
        facts = []
    tbox, mbox = _map_box(data, box, el.get("show_map") is not False)
    x, y, w, h = tbox
    name_px = max(hero.MIN_VALUE, min(round(h * 0.2 * scale), 64))
    where_px = max(hero.MIN_CAPTION, round(name_px * 0.46))
    fact_px = max(hero.MIN_CAPTION, round(name_px * 0.36))
    label_px = max(hero.MIN_CAPTION, round(fact_px * 0.8))
    facts_h = (label_px + 4 + fact_px) if facts else 0
    # Shrink together until the name, where it is and the facts fit, leaving the rest to the text.
    while name_px > hero.MIN_VALUE and name_px + 6 + where_px + (12 + facts_h if facts else 0) > h:
        name_px -= 2
        where_px = max(hero.MIN_CAPTION, round(name_px * 0.46))
        fact_px = max(hero.MIN_CAPTION, round(name_px * 0.36))
        label_px = max(hero.MIN_CAPTION, round(fact_px * 0.8))
        facts_h = (label_px + 4 + fact_px) if facts else 0
    if name_px + 6 + where_px + (12 + facts_h if facts else 0) > h:
        facts, facts_h = [], 0
    lines = [place_line(name, x, y, w, name_px, bold=True, floor=hero.MIN_VALUE)]
    cy = y + name_px + 6
    if where:
        lines.append(place_line(where, x, cy, w, where_px))
        cy += where_px
    room = y + h - (facts_h + 12 if facts else 0) - (cy + 12)
    if text and room >= hero.MIN_CAPTION:
        lines += wrap_into(text, x, cy + 12, w, room, max(hero.MIN_CAPTION, round(name_px * 0.36)))
    if facts:
        fy = y + h - facts_h
        cw = w // len(facts)
        for k, (label, value) in enumerate(facts):
            lines.append(place_line(label, x + k * cw, fy, cw - 10, label_px))
            lines.append(place_line(value, x + k * cw, fy + label_px + 4, cw - 10, fact_px, bold=True))
    return lines, mbox


# ---------------------------------------------------------------- the map

def draw_map(img, mbox, data: dict) -> None:
    mx, my, mw, mh = mbox
    m = data.get("map") or {}
    km = float(data.get("km") or 1.6)
    k = max(mw, mh) / (km * 1000.0)                 # pixels per metre: the box's longer side spans the map
    cx, cy = mw / 2, mh / 2

    def at(p):
        return (cx + p[0] * k, cy - p[1] * k)

    pic = Image.new("L", (mw, mh), T.WHITE)
    d = ImageDraw.Draw(pic)
    unit = max(1.0, min(mw, mh) / 110)
    hatch = Image.new("L", (mw, mh), T.WHITE)
    hd = ImageDraw.Draw(hatch)
    for yy in range(0, mh, 6):                      # water: hatched, a hard-edged pattern, never grey
        hd.rectangle([0, yy, mw, yy + 1], fill=T.BLACK)
    for kind, pts in m.get("areas") or []:
        poly = [at(p) for p in pts]
        mask = Image.new("L", (mw, mh), 0)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        pic.paste(hatch, (0, 0), mask)
        d.line(poly + [poly[0]], fill=T.BLACK, width=2)
    widths = {"stream": max(3, round(unit * 1.5)), "river": max(5, round(unit * 3.5)), "path": 2,
              "minor": max(3, round(unit * 1.3)), "major": max(8, round(unit * 3.6))}
    for kind, pts in m.get("lines") or []:
        xy = [at(p) for p in pts]
        width = widths.get(kind, 2)
        d.line(xy, fill=T.BLACK, width=width, joint="curve")
    for kind, pts in m.get("lines") or []:          # main roads hollow: their insides cleared after all are drawn
        if kind == "major":
            d.line([at(p) for p in pts], fill=T.WHITE, width=max(3, widths["major"] - 5), joint="curve")
    r = max(7, round(unit * 6))                     # the place itself
    d.ellipse([cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4], fill=T.WHITE)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=T.BLACK, width=max(3, r // 3))
    d.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], fill=T.BLACK)
    # Credits, as OpenStreetMap's licence and Wikipedia's ask: the fullest that fits, bottom right.
    px = max(hero.MIN_CAPTION, min(16, mh // 14))
    f = T.font(px, bold=False)
    credit = next((t for t in (say("place.credit"), say("place.credit_mid"), say("place.credit_short"))
                   if T.text_width(t, f) <= mw - 24 - max(8, min(mw, mh) // 14)), say("place.credit_short"))
    radius = max(8, min(mw, mh) // 14)              # rounded corners, and a frame round them
    inset = 6 + radius // 3                         # clear of the rounded corner
    tw = T.text_width(credit, f)
    asc, desc = f.getmetrics()
    d.rectangle([mw - tw - inset - 6, mh - asc - desc - 8, mw, mh], fill=T.WHITE)
    d.text((mw - inset, mh - 4), credit, font=f, fill=T.BLACK, anchor="rd")
    corners = Image.new("L", (mw, mh), 0)
    ImageDraw.Draw(corners).rounded_rectangle([0, 0, mw - 1, mh - 1], radius=radius, fill=255)
    img.paste(pic, (mx, my), corners)
    ImageDraw.Draw(img).rounded_rectangle([mx, my, mx + mw - 1, my + mh - 1], radius=radius, outline=T.BLACK, width=2)


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    got = plan(el, data, box, scale=scale)
    if got is None:
        return
    lines, mbox = got
    hero.draw_lines(d, lines)
    if mbox:
        draw_map(img, mbox, data)
