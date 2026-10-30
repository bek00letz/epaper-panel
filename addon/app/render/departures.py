"""The next departures, drawn as a board: the line in a solid badge, where it goes, when it leaves.

What it shows comes from sources/departures.py, every integration's shape already read into one.
Soon is said in minutes ("4 min", "now"); later, and always on a device that sleeps between
updates, as the time it leaves ("14:05"), which doesn't go stale while it sleeps.
"""
from __future__ import annotations

from datetime import datetime

from . import clock, hero, listing
from .todo import now_in
from .words import say

SOON = 60               # minutes: sooner is said as minutes, later as the time


def leaves(at: datetime, now: datetime, asleep: bool = False) -> str:
    mins = (at - now).total_seconds() / 60
    if asleep or mins >= SOON:
        return clock.hm(at)
    if mins < 1:
        return say("departures.now")
    return say("departures.minutes", int(mins))


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    title = str(el.get("title") or "").strip() or data.get("stop") or say("departures.title")
    if data.get("missing"):
        hero.message(d, box, say("departures.none" if data["missing"] == "integration" else "departures.unavailable"))
        return
    now = now_in(data.get("tz"))
    asleep = bool(el.get("asleep"))
    rows = []
    for dep in data.get("departures") or []:
        try:
            at = datetime.fromisoformat(str(dep.get("at")))
        except (TypeError, ValueError):
            continue
        at = at.astimezone(now.tzinfo) if at.tzinfo else at.replace(tzinfo=now.tzinfo)
        delay = int(dep.get("delay") or 0)
        rows.append(listing.Row(str(dep.get("destination") or dep.get("line") or ""), badge=str(dep.get("line") or "") if dep.get("destination") else "",
                                sub=say("departures.platform", platform=dep["platform"]) if dep.get("platform") else "",
                                value=leaves(at, now, asleep), note=say("departures.late", n=delay) if delay > 0 else ""))
    listing.draw(img, d, box, title=title, rows=rows, empty=say("departures.empty"), scale=scale)
