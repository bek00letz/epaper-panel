"""Times of day on the panel, 12- or 24-hour: the one place that formats them.

Every renderer that shows a time (sunrise, a to-do's due time, a kick-off,
the footer's clock and "updated", a binding's time) asks here, so the whole
panel follows one setting (timeformat.py: Home Assistant's country by
default, or the person's choice). The setting is applied for the process by
`use()`, as the render cycle starts; drawing stays a pure function of it.
"""
from __future__ import annotations

from datetime import datetime

_twelve = False


def use(twelve_hour: bool) -> None:
    global _twelve
    _twelve = bool(twelve_hour)


def twelve_hour() -> bool:
    return _twelve


def pattern(fmt: str = "time") -> str:
    """The strftime pattern for a kind of time ("time", "datetime"), in the panel's format.
    `%-I` and `%-d` are written out by strftime() below, on every platform."""
    if fmt == "datetime":
        return "%-d %b %-I:%M %p" if _twelve else "%-d %b %H:%M"
    return "%-I:%M %p" if _twelve else "%H:%M"


def strftime(dt: datetime, fmt: str) -> str:
    """strftime with the no-padding forms (%-d, %-I, %-m, %-H) on every platform."""
    for code, value in (("%-d", str(dt.day)), ("%-m", str(dt.month)), ("%-H", str(dt.hour)),
                        ("%-I", str(int(dt.strftime("%I"))))):
        fmt = fmt.replace(code, value)
    return dt.strftime(fmt)


def hm(dt: datetime) -> str:
    """A time of day: "14:05", or "2:05 PM"."""
    return strftime(dt, pattern("time"))
