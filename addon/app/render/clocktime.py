"""The date in place of the time, on a device that sleeps between updates.

A device that sleeps shows what it got at its last update, so a clock there
would stop at that time and, changing at every wake, force a full download
and a flashing redraw each time (paging.steady can't keep it). The user's
call (21 Oct): per device and automatic. The design keeps its clock; a
device that sleeps draws the date where any time would be, an always-on one
keeps the clock. Whether a device sleeps comes from its timers
(Kind.sleeps), never its kind, as with the footer's "updated HH:MM".

This is the one place that knows what shows the time: the renderer uses it,
and it marks what it changed in the metrics (`date_for_time`), which is how
the editor knows to say so on the element.

What a time becomes: the weekday ("Tuesday"), and an element beside it that
shows the date stops repeating the weekday ("Tuesday, 21 October" becomes
"21 October"), so the Clock preset reads as the Date preset does. With no
date beside it, the time becomes the whole date ("Tuesday 21 October").
"""
from __future__ import annotations

import re
from datetime import datetime

from . import binding, clock
from . import theme as T

# A template that shows the time of day: now() formatted with an hour, minute or am/pm.
TIME = re.compile(r"now\(\)[^}]*strftime\(\s*['\"]([^'\"]*%-?[HIklMp][^'\"]*)['\"]")
FORMAT = re.compile(r"now\(\)[^}]*strftime\(\s*['\"]([^'\"]*)['\"]")
DAY = re.compile(r"%-?[de]")
# Widgets that say how long ago something happened, and the time it happened on a device that sleeps.
AGES = ("notifications",)
# The other ways people write a clock in Home Assistant.
IDIOMS = (
    TIME,
    # as_timestamp(now()) | timestamp_custom('%H:%M'): a time pattern, on a template that reads now()
    re.compile(r"now\(\).*timestamp_custom\(\s*['\"][^'\"]*%-?[HIklMp]", re.S),
    # now().hour ~ ':' ~ now().minute
    re.compile(r"now\(\)\s*\.\s*(?:hour|minute)\b"),
    # The Time & Date integration's sensors: states('sensor.time'), states.sensor.date_time.state
    re.compile(r"""(?:['"]|states\.)sensor\.(?:time|time_utc|date_time|date_time_utc|date_time_iso|time_date)(?:['"]|\b)"""),
)


def _template(el: dict) -> str:
    """What the element shows, as a template: its own, or the one its binding makes."""
    raw = el.get("value")
    if isinstance(raw, str) and raw.strip():
        return raw
    return binding.template_for(el)


def shows_time(el: dict) -> bool:
    """Whether an element shows the time of day, however it's written: the one place that says.
    A world clock does; a text does when its template or binding reads the time."""
    if isinstance(el, dict) and el.get("type") == "world_clock":
        return True
    if not isinstance(el, dict) or el.get("type") != "text":
        return False
    if el.get("show") == "now" and not (isinstance(el.get("value"), str) and el["value"].strip()):
        return bool(TIME.search("now().strftime('" + binding.pattern(el.get("format") or "time") + "')"))
    text = _template(el)
    return any(p.search(text) for p in IDIOMS)


def times(page: dict) -> list[int]:
    """The elements of a page that show the time (for the editor: /api/shows-time and the render metrics)."""
    return [i for i, el in enumerate(page.get("elements") or []) if shows_time(el)]


def _format(el: dict) -> str:
    if el.get("show") == "now" and not (isinstance(el.get("value"), str) and el["value"].strip()):
        return binding.pattern(el.get("format") or "time")
    m = FORMAT.search(str(el.get("value") or ""))
    return m.group(1) if m else ""


def _strftime(now: datetime, fmt: str) -> str:
    return clock.strftime(now, fmt)


def date_for_time(page: dict, vals: dict, now: datetime) -> tuple[dict, dict, set[int]]:
    """The page and its values with the date where the time was, and which elements showed the
    time (the ones the editor notes). Nothing is changed in place: the design keeps its clock."""
    els = page.get("elements") or []
    times = {i for i, el in enumerate(els) if shows_time(el)}
    # Notifications say when each came, not how long ago: "12 min" would go stale while it sleeps.
    ages = {i for i, el in enumerate(els) if isinstance(el, dict) and el.get("type") in AGES}
    if not times and not ages:
        return page, vals, set()
    # A date beside a clock stops repeating the weekday; a world clock alone changes no date.
    dated = {i for i, el in enumerate(els) if i not in times and el.get("type") == "text" and DAY.search(_format(el))} \
        if any(els[i].get("type") == "text" for i in times) else set()
    out_els, out_vals = [dict(el) for el in els], dict(vals)
    for i in ages:
        out_els[i]["asleep"] = True             # render/needs_you.age_label
    for i in times:
        el = out_els[i]
        if el.get("type") == "world_clock":
            el["asleep"] = True                 # each city: hours ahead or behind (render/worldclock.py)
            continue
        text = _strftime(now, "%A" if dated else "%A %-d %B")
        out_vals[i] = text
        if el.get("size"):
            # The box was sized for "12:34"; the day must fit it too, never larger than the clock was.
            x, y, w, h = int(el.get("x", 0)), int(el.get("y", 0)), int(el.get("w", 200)), int(el.get("h", 60))
            bold = el.get("bold") not in (False, "false", 0, "0")
            el["size"] = max(8, min(int(el["size"]), T.fit_size(text, max(8, w), h, 200, bold=bold, family=str(el.get("font") or "lato").lower())))
    for i in dated:
        fmt = re.sub(r"^\s*%A,?\s*", "", _format(out_els[i]))
        if fmt != _format(out_els[i]):
            out_vals[i] = _strftime(now, fmt)
    return {**page, "elements": out_els}, out_vals, times
