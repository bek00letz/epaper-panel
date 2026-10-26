"""Times of day and dates on the panel, 12- or 24-hour, in the screen's language: the one place
that formats them.

Every renderer that shows a time (sunrise, a to-do's due time, a kick-off,
the footer's clock and "updated", a binding's time) asks here, so the whole
panel follows one setting (timeformat.py: Home Assistant's country by
default, or the person's choice). The setting is applied for the process by
`use()`, as the render cycle starts; drawing stays a pure function of it.

Dates are written in the language being spoken (render/words.py): its own
patterns ("21. Okt." in German) and month and day names, never the system's
locale, which in the add-on's container is English whatever Home Assistant says.
"""
from __future__ import annotations

from datetime import datetime

from . import words

_twelve = False


def use(twelve_hour: bool) -> None:
    global _twelve
    _twelve = bool(twelve_hour)


def twelve_hour() -> bool:
    return _twelve


def pattern(fmt: str = "time") -> str:
    """The strftime pattern for a kind of time ("time", "datetime"), in the panel's format and the
    language's date order. `%-I` and `%-d` are written out by strftime() below, on every platform."""
    hm_ = "%-I:%M %p" if _twelve else "%H:%M"
    if fmt == "datetime":
        return f"{words.date_pattern('date')} {hm_}"
    return hm_


def strftime(dt: datetime, fmt: str) -> str:
    """strftime with the no-padding forms (%-d, %-I, %-m, %-H) on every platform, and the names
    (%a %A %b %B %p) in the screen's language."""
    names = (("%A", words.name("weekday", dt.weekday())), ("%a", words.name("wd", dt.weekday())),
             ("%B", words.name("month", dt.month)), ("%b", words.name("mon", dt.month)),
             ("%p", words.name("pm" if dt.hour >= 12 else "am", 0)))
    for code, value in (("%-d", str(dt.day)), ("%-m", str(dt.month)), ("%-H", str(dt.hour)),
                        ("%-I", str(int(dt.strftime("%I"))))) + names:
        fmt = fmt.replace(code, value.replace("%", "%%"))
    return dt.strftime(fmt)


def hm(dt: datetime) -> str:
    """A time of day: "14:05", or "2:05 PM"."""
    return strftime(dt, pattern("time"))


def date(dt: datetime, kind: str = "date") -> str:
    """A date in the language: kind is one of words.date_pattern's ("date": "21 Oct", "weekday_date":
    "Tuesday 21 October", ...), or "weekday" ("Tuesday") and "wd" ("Tue")."""
    if kind == "weekday":
        return words.name("weekday", dt.weekday())
    if kind == "wd":
        return words.name("wd", dt.weekday())
    return strftime(dt, words.date_pattern(kind))


def day_and_time(dt: datetime) -> str:
    """A short weekday and a time: "Tue 14:05"."""
    return f"{date(dt, 'wd')} {hm(dt)}"


# How long, in its largest whole unit, as Home Assistant's relative time says it ("2 hours").
_SPANS = (("years", 365 * 86400), ("months", 30 * 86400), ("days", 86400), ("hours", 3600), ("minutes", 60))


def span(seconds: float) -> str:
    """How long, in words: "2 hours", "1 minute", "30 seconds" (never negative)."""
    seconds = max(0, int(seconds))
    for unit, size in _SPANS:
        if seconds >= size:
            return words.say(f"span.{unit}", seconds // size)
    return words.say("span.seconds", seconds)


def span_short(seconds: float) -> str:
    """How long, short, for a small card: "25m", "3h", "2d" (in English)."""
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return words.say("for.days", seconds // 86400)
    if seconds >= 3600:
        return words.say("for.hours", seconds // 3600)
    return words.say("for.minutes", seconds // 60)
