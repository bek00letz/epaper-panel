"""Countdown: days until a date of yours, or until the bins go out, with no calendar.

The user's call (21 Oct): a countdown or a bin day shouldn't need a calendar
in Home Assistant. The element carries what it counts to, and this works out
how far off it is when it's drawn, with nothing asked of anyone, so the
panel, the editor's canvas and New page's thumbnail all say the same.

    {"type": "countdown", "to": "date", "name": "Holiday", "at": "2026-12-24" | "2026-12-24T18:00", "yearly": false}
    {"type": "countdown", "to": "bins", "today_until": "noon" | "midnight", "numbers": false,
     "bins": [{"name": "Recycling", "from": "2026-11-03", "every": 2}, ...]}

A bin is collected on its `from` date and every `every` weeks after it, so
alternating bins are two bins every 2 weeks, a week apart. The evening
before reads "Tomorrow" and the day "Today", or "1 day" and "0 days" with
`numbers`; bin day ends at noon or midnight (`today_until`), then it counts
to the next one. One setting used to do both: `today_until: "days"`
still means numbers, ending at noon. A date without a time reads "Today"
all its day; with a time, "In 3 hours" on the day; once past, a one-off
date's page hides itself (`passed`) and a yearly one rolls on to next year.
A passed one stays among your pages, marked Passed, to reuse with another
date (the user's call, 21 Oct).

`show_before` (days; none or 0 for always): the page shows only from that
many days before, so a countdown set six months ahead can wait until a
month before (the user's call, 21 Oct). Bins too: the evening before only.

What the editor shows about it (the strip's tile, the page's note) comes
from `status`, in the render's metrics: one place decides.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import hero
from .todo import now_in

ICONS = {"date": "mdi:calendar-clock", "bins": "mdi:trash-can"}
TODAY_UNTIL = ("noon", "midnight", "days")      # "days": numbers, ending at noon (the first shape)


def says_numbers(el: dict) -> bool:
    """Whether a bin day says "1 day" and "0 days" rather than "Tomorrow" and "Today"."""
    return el.get("numbers") is True or el.get("today_until") == "days"


def _day(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _at(raw, tz) -> tuple[datetime | None, bool]:
    """A date or date and time, in Home Assistant's time zone: (when, has a time)."""
    text = str(raw or "").strip()
    d = _day(text)
    if d is None:
        return None, False
    if len(text) > 10:
        try:
            t = datetime.fromisoformat(text[:16])
            return t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz), True
        except ValueError:
            pass
    return datetime(d.year, d.month, d.day, tzinfo=tz), False


def _yearly(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:                      # 29 February, in a year without one
        return d.replace(year=year, day=28)


def next_bins(el: dict, now: datetime) -> tuple[date, list[str]] | None:
    """The next collection on or after today (today only until its cutoff), and which bins go out."""
    until = el.get("today_until") if el.get("today_until") in TODAY_UNTIL else "noon"
    today = now.date()
    start = today + timedelta(days=1) if until != "midnight" and now.hour >= 12 else today
    best, names = None, []
    for b in el.get("bins") or []:
        first, every = _day(b.get("from")), max(1, min(8, int(b.get("every") or 1)))
        if first is None:
            continue
        if first >= start:
            when = first
        else:
            period = 7 * every
            when = first + timedelta(days=-(-(start - first).days // period) * period)
        name = str(b.get("name") or "").strip() or "Bins"
        if best is None or when < best:
            best, names = when, [name]
        elif when == best and name not in names:
            names.append(name)
    return (best, names) if best else None


def target(el: dict, now: datetime) -> tuple[datetime | None, bool]:
    """When a date countdown is for, rolled on a year if it's yearly and past: (when, has a time)."""
    when, timed = _at(el.get("at"), now.tzinfo)
    if when is None:
        return None, False
    if el.get("yearly") and _passed_at(when, timed, now):
        nxt = _yearly(when.date(), now.year)
        when = when.replace(year=nxt.year, month=nxt.month, day=nxt.day)
        if _passed_at(when, timed, now):
            nxt = _yearly(when.date(), now.year + 1)
            when = when.replace(year=nxt.year, month=nxt.month, day=nxt.day)
    return when, timed


def _passed_at(when: datetime, timed: bool, now: datetime) -> bool:
    return now >= when if timed else now.date() > when.date()


def passed(el: dict, now: datetime) -> bool:
    """A one-off date that has gone: its page hides itself (frames.eligible_pages)."""
    if el.get("type") != "countdown" or el.get("to") != "date" or el.get("yearly"):
        return False
    when, timed = _at(el.get("at"), now.tzinfo)
    return when is not None and _passed_at(when, timed, now)


def _show_before(el: dict) -> int:
    try:
        return max(0, int(el.get("show_before") or 0))
    except (TypeError, ValueError):
        return 0


def _next_day(el: dict, now: datetime) -> date | None:
    if el.get("to") == "bins":
        got = next_bins(el, now)
        return got[0] if got else None
    when, _ = target(el, now)
    return when.date() if when else None


def status(el: dict, now: datetime) -> dict:
    """{"state": "passed", "on"} | {"state": "waiting", "from"} | {"state": "showing"}: what the
    page does now, said in the editor (the strip's tile, the page's note)."""
    if passed(el, now):
        when, _ = _at(el.get("at"), now.tzinfo)
        return {"state": "passed", "on": _date_words(when.date(), now.date())}
    day, before = _next_day(el, now), _show_before(el)
    if day is not None and before and (day - now.date()).days > before:
        start = day - timedelta(days=before)
        return {"state": "waiting", "from": _date_words(start, now.date())}
    return {"state": "showing"}


def page_hidden(page: dict, now: datetime) -> bool:
    """A countdown page shows only while one of its countdowns does: not once a one-off date has
    passed, nor before its `show_before`."""
    els = [e for e in page.get("elements") or [] if isinstance(e, dict) and e.get("type") == "countdown"]
    return bool(els) and all(status(e, now)["state"] != "showing" for e in els)


def page_passed(page: dict, now: datetime) -> bool:
    els = [e for e in page.get("elements") or [] if isinstance(e, dict) and e.get("type") == "countdown"]
    return bool(els) and all(passed(e, now) for e in els)


def _days_words(days: int, numbers: bool) -> str:
    if numbers:
        return f"{days} day" if days == 1 else f"{days} days"
    return "Today" if days == 0 else "Tomorrow" if days == 1 else f"In {days} days"


def _date_words(d: date, today: date) -> str:
    return f"{d:%A} {d.day} {d:%B}" + ("" if d.year == today.year else f" {d.year}")


def describe(el: dict, now: datetime) -> hero.Fact | tuple[hero.Fact, hero.Fact] | None:
    """(what's large, what's beside it), or None when there's nothing to count to yet."""
    to = el.get("to") if el.get("to") in ICONS else "date"
    icon = str(el.get("icon") or ICONS[to])
    today = now.date()
    if to == "bins":
        got = next_bins(el, now)
        if got is None:
            return None
        when, names = got
        days = (when - today).days
        return (hero.Fact(_days_words(days, says_numbers(el)), " and ".join(names), icon),
                hero.Fact(_date_words(when, today)))
    when, timed = target(el, now)
    if when is None:
        return None
    name = str(el.get("name") or "").strip()
    if _passed_at(when, timed, now):
        return hero.Fact("Passed", name, icon), hero.Fact(_date_words(when.date(), today))
    days = (when.date() - today).days
    if timed and days == 0:
        mins = max(0, round((when - now).total_seconds() / 60))
        big = "Now" if mins < 1 else f"In {mins} min" if mins < 60 else f"In {round(mins / 60)} hours" if mins >= 90 else "In 1 hour"
    else:
        big = _days_words(days, False)
    aside = _date_words(when.date(), today) + (f", {when:%H:%M}" if timed else "")
    return hero.Fact(big, name, icon), hero.Fact(aside)


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    now = now_in((data or {}).get("tz") if isinstance(data, dict) else None)
    got = describe(el, now)
    if got is None:
        hero.message(d, box, "Choose a date" if el.get("to") != "bins" else "Add a bin and its day")
        return
    main, aside = got
    hero.draw(img, d, box, main, aside=aside, scale=scale)
