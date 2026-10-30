"""Travel times, drawn: one route large, several as rows, each against its usual.

The routes come from sources/commute.py with their minutes now and their usual. One route is a
fact at a glance (the minutes, where to, and how it compares beside it); several are rows, the
minutes at the right, and a route much slower than usual inverted so it's seen from the sofa.
"""
from __future__ import annotations

from . import hero, listing
from .words import say

ICON = "mdi:car-clock"


def slower(now: float, usual: float | None) -> int | None:
    """Whole minutes slower than usual (negative: faster), 0 within the usual's own wobble
    (two minutes, or a tenth of the usual), None without a usual."""
    if usual is None or now is None:
        return None
    diff = now - usual
    if abs(diff) < max(2.0, usual * 0.1):
        return 0
    return round(diff)


def loud(now: float, usual: float | None) -> bool:
    """Much slower than usual: five minutes and a quarter more, at least."""
    d = slower(now, usual)
    return d is not None and d >= 5 and d >= (usual or 0) * 0.25


def mins(v: float) -> str:
    return say("commute.minutes", int(round(v)))


def compared(now: float, usual: float | None) -> str:
    d = slower(now, usual)
    if d is None:
        return ""
    if d == 0:
        return say("commute.as_usual")
    return say("commute.slower" if d > 0 else "commute.faster", abs(d))


def _title(r: dict) -> str:
    return str(r.get("name") or "").strip()


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    routes = [r for r in data.get("routes") or [] if isinstance(r, dict)]
    if not routes:
        hero.message(d, box, say("commute.none" if data.get("missing") == "integration" else "commute.choose"))
        return
    title = str(el.get("title") or "").strip() or say("commute.title")
    if len(routes) == 1:
        r = routes[0]
        if r.get("minutes") is None:
            hero.message(d, box, say("commute.no_answer_named", name=_title(r)))
            return
        caption = _title(r) + (f" · {say('commute.via', route=r['route'])}" if r.get("route") else "")
        main = hero.Fact(mins(r["minutes"]), caption, ICON)
        diff = slower(r["minutes"], r.get("usual"))
        if diff is None:
            hero.draw(img, d, box, main, scale=scale)
            return
        if diff == 0:
            aside = hero.Fact(mins(r["usual"]), say("commute.as_usual"))
        else:
            aside = hero.Fact(("+" if diff > 0 else "−") + mins(abs(diff)),
                              say("commute.than_usual_slower" if diff > 0 else "commute.than_usual_faster"))
        hero.draw(img, d, box, main, aside=aside, scale=scale, share=0.36)
        return
    rows = []
    for r in routes:
        if r.get("minutes") is None:
            rows.append(listing.Row(_title(r), sub=r.get("route") or "", value="", note=say("commute.no_answer")))
            continue
        rows.append(listing.Row(_title(r), sub=say("commute.via", route=r["route"]) if r.get("route") else "",
                                value=mins(r["minutes"]), note=compared(r["minutes"], r.get("usual")),
                                loud=loud(r["minutes"], r.get("usual"))))
    listing.draw(img, d, box, title=title, rows=rows, scale=scale)

