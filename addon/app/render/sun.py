"""Sunrise and sunset, from Home Assistant's sun.

Two styles: "next" puts whichever comes next large and the other beside it,
so it turns round at sunrise and at sunset; "both" shows them alike, sunrise
first. Times are the next ones Home Assistant has (`next_rising`,
`next_setting`), in its time zone; one more than a day away (the far north
in summer or winter) says which day.
"""
from __future__ import annotations

from datetime import datetime

from . import clock
from .words import say
from . import hero
from . import theme as T
from .todo import now_in

STYLES = ("next", "both")
RISE_ICON, SET_ICON = "mdi:weather-sunset-up", "mdi:weather-sunset-down"


def _when(raw, tz) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(tz)


def facts(data: dict | None, now: datetime) -> tuple[hero.Fact, hero.Fact] | None:
    """(sunrise, sunset) as facts, or None when Home Assistant gave neither."""
    data = data if isinstance(data, dict) else {}
    out = []
    for key, word, icon in (("rising", "sun.rise", RISE_ICON), ("setting", "sun.set", SET_ICON)):
        dt = _when(data.get(key), now.tzinfo)
        if dt is None:
            out.append(None)
            continue
        days = (dt.date() - now.date()).days
        caption = say(word) if days <= 1 else say(f"{word}_on", date=clock.date(dt, "date"))
        out.append(hero.Fact(clock.hm(dt), caption, icon))
    if out[0] is None and out[1] is None:
        return None
    return out[0] or hero.Fact("--:--", say("sun.rise"), RISE_ICON), out[1] or hero.Fact("--:--", say("sun.set"), SET_ICON)


def next_first(data: dict | None, now: datetime) -> bool:
    """Whether the sunrise comes before the sunset from now on."""
    data = data if isinstance(data, dict) else {}
    rise, set_ = _when(data.get("rising"), now.tzinfo), _when(data.get("setting"), now.tzinfo)
    if rise is None or set_ is None:
        return rise is not None
    # The value can be a little behind: a time already past is no longer next.
    if (rise <= now) != (set_ <= now):
        return set_ <= now
    return rise <= set_


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    data = data if isinstance(data, dict) else None
    now = now_in((data or {}).get("tz"))
    pair = facts(data, now)
    if pair is None:
        if data is not None:                  # not fetched yet stays blank, so nothing flashes
            hero.message(d, box, say("sun.missing"))
        return
    rise, set_ = pair
    if el.get("style") == "both":
        hero.draw_pair(img, d, box, rise, set_, scale=scale)
        return
    main, other = (rise, set_) if next_first(data, now) else (set_, rise)
    hero.draw(img, d, box, main, aside=other, scale=scale)
