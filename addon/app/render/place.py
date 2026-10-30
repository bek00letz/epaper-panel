"""Place of the day: its name, where it is, a few lines about it, and a few facts.

On a wide box the place is on the left (its name large, where it is, its facts under them) and
what Wikipedia says about it on the right, in text you can read across a room; on a narrow or
tall box it's one column, the description between the place and its facts. A box too small for
the description keeps the place and its facts. Wikipedia is credited under its words, as its
licence asks.

The facts are the ones known: population, elevation, local time. On a device that sleeps between
updates a local time would stop, so there it shows how many hours apart the place is.

There's no map: the user's call (30 Oct), small screens don't show one well.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import clock, hero
from .hero import Line, place_line, wrap_into
from .todo import now_in
from .words import language, number, say

DESC_MOST = 30                  # the description's largest size: a paragraph, not a headline
WIDE = 480                      # narrower than this, one column


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


def _sizes(start: int, name_fit: int, has_where: bool, has_facts: bool, room: int):
    """(name, where, fact value, fact label, height they take, the size they follow): sized from the box (`start`), the
    name no larger than fits its width (`name_fit`), all shrunk together until they take no more
    than `room`. A long name doesn't make the rest small."""
    base = max(hero.MIN_VALUE, start)
    while True:
        name_px = max(hero.MIN_VALUE, min(name_fit, base))
        where_px = max(hero.MIN_CAPTION, round(base * 0.42))
        value_px = max(hero.MIN_CAPTION, min(30, round(base * 0.4)))
        label_px = max(hero.MIN_CAPTION, round(value_px * 0.72))
        need = name_px + (_gap(base) + where_px if has_where else 0) + (2 * _gap(base) + label_px + 4 + value_px if has_facts else 0)
        if need <= room or base <= hero.MIN_VALUE:
            return name_px, where_px, value_px, label_px, need, base
        base -= 2
        name_fit = min(name_fit, base)


def _gap(name_px: int) -> int:
    """The space under the name, in step with it: roomy on a large screen, tight on the 2.9"."""
    return max(4, round(name_px / 7))


def _facts(facts, x, y, w, label_px, value_px) -> list[Line]:
    """The facts side by side, every value at one size and every label at one, so they read as a row."""
    cw = w // len(facts)
    values = [place_line(v, 0, 0, cw - 10, value_px, bold=True) for _, v in facts]
    labels = [place_line(lb, 0, 0, cw - 10, label_px) for lb, _ in facts]
    vpx, lpx = min(v.px for v in values), min(lb.px for lb in labels)
    out = []
    for k, (label, value) in enumerate(facts):
        out.append(place_line(label, x + k * cw, y, cw - 10, lpx))
        out.append(place_line(value, x + k * cw, y + label_px + 4, cw - 10, vpx, bold=True))
    return out


def _description(text: str, x, y, w, h, start: int) -> list[Line]:
    """What Wikipedia says, as large as it reads up to `start`, credited under it."""
    if not text or h < 2 * hero.MIN_CAPTION + 6:
        return []
    credit_px = hero.MIN_CAPTION
    lines = wrap_into(text, x, y, w, h - credit_px - 6, start)
    if not lines:
        return []
    bottom = lines[-1].y + round(lines[-1].px * 1.25) + 4
    return lines + [place_line(say("place.credit"), x, min(bottom, y + h - credit_px), w, credit_px)]


def plan(el: dict, data, box, now: datetime | None = None, scale: float = 1.0):
    """The lines of text, where each goes and how large. None when there's nothing to draw yet."""
    if not isinstance(data, dict) or not data.get("name"):
        return None
    now = now or now_in(data.get("home_tz"))
    name, where, text, facts = _texts(data, now, bool(el.get("asleep")))
    if el.get("show_facts") is False:
        facts = []
    x, y, w, h = box
    if w >= h * 1.6 and w >= WIDE and text:
        # The place on the left, its story on the right.
        gap = max(16, w // 30)
        left = round(w * 0.4)
        start = min(round(h * 0.34 * scale), 72)
        fit = place_line(name, 0, 0, left, start, bold=True, floor=hero.MIN_VALUE).px          # as wide as it fits
        name_px, where_px, value_px, label_px, need, base = _sizes(start, fit, bool(where), bool(facts), h)
        if need > h:
            facts = []
            name_px, where_px, value_px, label_px, need, base = _sizes(start, fit, bool(where), False, h)
        top = y + max(0, (h - need) // 2)
        lines = [place_line(name, x, top, left, name_px, bold=True, floor=hero.MIN_VALUE)]
        cy = top + name_px
        if where:
            lines.append(place_line(where, x, cy + _gap(base), left, where_px))
            cy += _gap(base) + where_px
        if facts:
            lines += _facts(facts, x, cy + 2 * _gap(base), left, label_px, value_px)
        desc = _description(text, x + left + gap, y, w - left - gap, h, min(DESC_MOST, round(h * 0.13 * scale)))
        if desc:                                    # the paragraph sits level with the place, centred
            used = desc[-1].y + desc[-1].px - y
            shift = max(0, (h - used) // 2)
            for ln in desc:
                ln.y += shift
        return lines + desc
    # One column: the place, what it is, its facts at the foot.
    start = min(round(h * 0.22 * scale), 64)
    fit = place_line(name, 0, 0, w, start, bold=True, floor=hero.MIN_VALUE).px
    name_px, where_px, value_px, label_px, need, base = _sizes(start, fit, bool(where), bool(facts), h)
    if need > h:
        facts = []
        name_px, where_px, value_px, label_px, need, base = _sizes(start, fit, bool(where), False, h)
    lines = [place_line(name, x, y, w, name_px, bold=True, floor=hero.MIN_VALUE)]
    cy = y + name_px
    if where:
        lines.append(place_line(where, x, cy + _gap(base), w, where_px))
        cy += _gap(base) + where_px
    facts_h = (label_px + 4 + value_px) if facts else 0
    room = y + h - (facts_h + 2 * _gap(base) if facts else 0) - (cy + 2 * _gap(base))
    lines += _description(text, x, cy + 2 * _gap(base), w, room, min(DESC_MOST, max(hero.MIN_CAPTION, round(start * 0.42))))
    if facts:
        lines += _facts(facts, x, y + h - facts_h, w, label_px, value_px)
    return lines


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    lines = plan(el, data, box, scale=scale)
    if lines is not None:
        hero.draw_lines(d, lines)
