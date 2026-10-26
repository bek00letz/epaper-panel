"""What a race page says, in the screen's language: its badge and its line under the race.

sources/racing.py gives the facts (the session, when it starts, its state, the time zone); the
words are said here when the page is drawn, so one race fetched once reads in each screen's own
language. Session names are the add-on's own ("Qualifying"); one it doesn't know (a series'
own name for a session) is shown as its source says it.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import clock
from .words import has, say

LEADER = "LEADER"           # the leader's gap, as a source gives it: said as the screen's word


def session(name: str) -> str:
    """A session's name in the screen's language ("Race" -> "Rennen")."""
    name = str(name or "").strip()
    return say(f"race.session.{name}") if has(f"race.session.{name}") else name


def badge(name: str, status: str, lap=None, total_laps=None) -> list:
    """What a race page's badge says, longest first, so a narrow page drops the state before the
    session's name: ["QUALIFYING · LIVE", "QUALIFYING"], ["RACE · LAP 34/57", "RACE"],
    ["PRACTICE 3 · FINAL", "PRACTICE 3"]. An order whose session its source didn't say is a
    "RESULT" (or "LIVE", when the source says it's live), never a session guessed."""
    status = str(status or "").upper()
    state = (say("race.lap", lap=lap, total=total_laps) if lap and total_laps else say("race.live")) \
        if status == "IN" else say("race.final") if status == "POST" else ""
    name = session(name).upper()
    if not name:
        return [state if status == "IN" else say("race.result")]
    return [f"{name} · {state}", name] if state else [name]


def forms(data: dict) -> list:
    """The badge's words for a race's facts, longest first."""
    status = str(data.get("status") or "").upper()
    if status == "OFF":
        return [say("race.off_season")]
    if status == "PRE" or (not data.get("session") and data.get("race_day")):
        return [say("race.scheduled")]
    return badge(data.get("session") or "", data.get("badge_status", status), data.get("lap"), data.get("total_laps"))


def _local(raw, tz_name):
    """A fact's time in the home's zone (a datetime), or its day (a date)."""
    text = str(raw or "")
    if len(text) == 10:
        return date.fromisoformat(text)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    try:
        return dt.astimezone(ZoneInfo(tz_name)) if tz_name else dt
    except Exception:
        return dt


def day(d) -> str:
    """A day as the panel says it: "Fri 18 Dec"."""
    return clock.date(d if isinstance(d, datetime) else datetime.combine(d, datetime.min.time()), "short_day_date")


def at(dt: datetime) -> str:
    """When a session starts, in the home's time: "Fri 18 Dec · 13:30 GMT"."""
    return f"{day(dt)} · {clock.hm(dt)} {dt.tzname() or ''}".strip()


def detail(data: dict) -> str:
    """The line under the race: when its session is, or when the season starts."""
    tz = data.get("tz")
    try:
        if str(data.get("status") or "").upper() == "OFF":
            return say("race.season_starts", day=day(_local(data["next_start"], tz))) if data.get("next_start") \
                else say("race.no_calendar")
        if data.get("session") and data.get("session_start"):
            return f"{session(data['session'])} · {at(_local(data['session_start'], tz))}"
        if data.get("race_day"):
            return f"{session('Race day')} · {day(_local(data['race_day'], tz))}"
    except (TypeError, ValueError):
        pass
    return ""


def gap(text) -> str:
    """A driver's gap, the leader's said in the screen's language."""
    return say("race.leader") if str(text or "") == LEADER else str(text or "")
