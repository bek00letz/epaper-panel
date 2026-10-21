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

from . import theme as T

# A template that shows the time of day: now() formatted with an hour, minute or am/pm.
TIME = re.compile(r"now\(\)[^}]*strftime\(\s*['\"]([^'\"]*%-?[HIklMp][^'\"]*)['\"]")
FORMAT = re.compile(r"now\(\)[^}]*strftime\(\s*['\"]([^'\"]*)['\"]")
DAY = re.compile(r"%-?[de]")


def shows_time(el: dict) -> bool:
    return isinstance(el, dict) and el.get("type") == "text" and bool(TIME.search(str(el.get("value") or "")))


def _format(el: dict) -> str:
    m = FORMAT.search(str(el.get("value") or ""))
    return m.group(1) if m else ""


def _strftime(now: datetime, fmt: str) -> str:
    """strftime with the no-padding forms (%-d) on every platform."""
    for code, value in (("%-d", str(now.day)), ("%-m", str(now.month)), ("%-H", str(now.hour)), ("%-I", str(int(now.strftime("%I"))))):
        fmt = fmt.replace(code, value)
    return now.strftime(fmt)


def date_for_time(page: dict, vals: dict, now: datetime) -> tuple[dict, dict, set[int]]:
    """The page and its values with the date where the time was, and which elements showed the
    time (the ones the editor notes). Nothing is changed in place: the design keeps its clock."""
    els = page.get("elements") or []
    times = {i for i, el in enumerate(els) if shows_time(el)}
    if not times:
        return page, vals, set()
    dated = {i for i, el in enumerate(els) if i not in times and el.get("type") == "text" and DAY.search(_format(el))}
    out_els, out_vals = [dict(el) for el in els], dict(vals)
    for i in times:
        text = _strftime(now, "%A" if dated else "%A %-d %B")
        el = out_els[i]
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
