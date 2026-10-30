"""Follow one flight: where it is while it's in the air, and plainly what it's doing when it isn't.

In the air: its flight number large, from and to (the cities, from the add-on's own list of
airports), how far along it is as a bar with the plane on it, and its height, speed and when it
arrives. On a device that sleeps between updates "time left" would stop, so there it says only
when it arrives, a time of day that stays true.

Not in the air it says which: "Not in the air" (before it, with its route when known), "Landed in
Bucharest", or "Out of view" (gone mid-flight, over an ocean say), each with when it was last seen.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import clock, hero
from . import theme as T
from .hero import Line, place_line
from .todo import now_in
from .words import number, say

STALE = 300                     # a position older than this says when it's from


def _hm(ts, tz) -> str:
    return clock.hm(datetime.fromtimestamp(ts, timezone.utc).astimezone(tz))


def spaced(flight: str) -> str:
    """A flight number as airlines print it: its airline's two characters, then the number ("W4 3186",
    "BA 117"); a callsign (three letters first) as it is."""
    f = str(flight or "")
    if len(f) > 2 and not f[:3].isalpha() and f[2:].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ").isdigit():
        return f"{f[:2]} {f[2:]}"
    return f


def _route(data: dict) -> str:
    a = data.get("from_city") or data.get("from") or ""
    b = data.get("to_city") or data.get("to") or ""
    return f"{a} → {b}" if a and b else (a or b)


def _left(seconds: float) -> str:
    m = max(1, round(seconds / 60))
    h, m = divmod(m, 60)
    return say("follow.hours_minutes", h=h, m=f"{m:02d}") if h else say("follow.minutes", m=m)


def facts(data: dict, now: datetime, asleep: bool) -> list[tuple[str, str]]:
    """(label, value) for a flight in the air, as the screen's language writes them."""
    out = [(say("follow.altitude"), f"{number(data.get('altitude_m') or 0, 0, group=True)} m"),
           (say("follow.speed"), f"{number(data.get('speed_kmh') or 0, 0, group=True)} km/h")]
    arrives = data.get("arrives")
    if isinstance(arrives, (int, float)):
        if (data.get("left_km") or 0) <= 30 and (data.get("altitude_m") or 0) < 3000:
            out.append((say("follow.arrives"), say("follow.landing")))
        elif asleep:
            out.append((say("follow.arrives"), say("follow.about", time=_hm(arrives, now.tzinfo))))
        else:
            out.append((say("follow.time_left"), _left(arrives - now.timestamp())))
    return out


def plan(el: dict, data, box, now: datetime | None = None, scale: float = 1.0) -> tuple[list[Line], dict] | None:
    """The lines of text, and the progress bar (as {"bar": (x, y, w, h), "done": share} or {}).
    None when there's nothing to draw yet."""
    x, y, w, h = box
    if not str(el.get("flight") or "").strip():
        return [Line(say("follow.add"), x, y, w, 0)], {"message": True}
    if not isinstance(data, dict):
        return None
    if data.get("failing") and not data.get("seen_at"):
        return [Line(say("follow.not_answering"), x, y, w, 0)], {"message": True}
    now = now or now_in(data.get("tz"))
    asleep = bool(el.get("asleep"))
    status = data.get("status") or "waiting"
    title = spaced(data.get("flight") or data.get("ident") or "")
    route = _route(data)
    if status == "air":
        state = route
        sub = ""
        if isinstance(data.get("seen_at"), (int, float)) and now.timestamp() - data["seen_at"] > STALE:
            sub = say("follow.position_from", time=_hm(data["seen_at"], now.tzinfo))
    elif status == "landed":
        state = say("follow.landed_in", place=data["to_city"]) if data.get("to_city") else say("follow.landed")
        sub = say("follow.last_seen", time=_hm(data["seen_at"], now.tzinfo)) if data.get("seen_at") else ""
    elif status == "lost":
        state = say("follow.out_of_view")
        sub = " · ".join(x for x in (say("follow.last_seen", time=_hm(data["seen_at"], now.tzinfo)) if data.get("seen_at") else "",
                                      route) if x)
    else:
        state = say("follow.not_in_air")
        sub = route or say("follow.shows_on_takeoff")
    rows = facts(data, now, asleep) if status == "air" else []
    # Beside the flight, a fact a row while each still reads: speed goes first, then height.
    while len(rows) > 1 and h // len(rows) < hero.MIN_CAPTION + 4 + hero.MIN_CAPTION + 2:
        rows.pop(1 if len(rows) > 2 else 0)
    wide = w >= h * 1.6 and rows
    side_w = round(w * 0.36) if wide else 0
    gap = max(12, w // 30) if wide else 0
    main_w = w - side_w - gap
    # The flight number takes what height is left after its lines; nothing smaller than e-ink allows.
    title_px = max(hero.MIN_VALUE, min(round(h * 0.34 * scale), round(h * 0.5)))
    state_px = max(hero.MIN_CAPTION, round(title_px * 0.42))
    sub_px = max(hero.MIN_CAPTION, round(title_px * 0.32))
    bar_h = max(6, round(h * 0.05)) if status == "air" and data.get("total_km") else 0
    facts_h = 0 if wide or not rows else 2 * sub_px + 10
    while title_px > hero.MIN_VALUE:
        need = title_px + 8 + state_px + (6 + sub_px if sub else 0) + (14 + bar_h if bar_h else 0) + (10 + facts_h if facts_h else 0)
        if need <= h:
            break
        title_px -= 2
        state_px = max(hero.MIN_CAPTION, round(title_px * 0.42))
        sub_px = max(hero.MIN_CAPTION, round(title_px * 0.32))
        facts_h = 0 if wide or not rows else 2 * sub_px + 10
    need = title_px + 8 + state_px + (6 + sub_px if sub else 0) + (14 + bar_h if bar_h else 0) + (10 + facts_h if facts_h else 0)
    if need > h:                                           # a small box: the facts go first, then the bar
        rows, facts_h, bar_h = [], 0, 0
    top = y + max(0, (h - min(h, need)) // 2)
    lines = [place_line(title, x, top, main_w, title_px, bold=True, floor=hero.MIN_VALUE)]
    cy = top + title_px + 8
    lines.append(place_line(state, x, cy, main_w, state_px, bold=status != "air"))
    cy += state_px
    if sub:
        cy += 6
        lines.append(place_line(sub, x, cy, main_w, sub_px))
        cy += sub_px
    extra = {}
    if bar_h:
        cy += 14
        done = 1 - (data.get("left_km") or 0) / max(1, data["total_km"])
        extra = {"bar": (x, cy, main_w, bar_h), "done": max(0.0, min(1.0, done))}
        cy += bar_h
    if rows and wide:
        sx = x + w - side_w
        ch = h // len(rows)
        for k, (label, value) in enumerate(rows):
            px = max(hero.MIN_CAPTION + 2, min(round(ch * 0.42), round(title_px * 0.62)))
            lpx = max(hero.MIN_CAPTION, round(px * 0.55))
            ry = y + k * ch + max(0, (ch - px - lpx - 4) // 2)
            lines.append(place_line(label, sx, ry, side_w, lpx))
            lines.append(place_line(value, sx, ry + lpx + 4, side_w, px, bold=True))
    elif rows:
        cy += 10
        cw = main_w // len(rows)
        for k, (label, value) in enumerate(rows):
            lines.append(place_line(label, x + k * cw, cy, cw - 8, sub_px))
            lines.append(place_line(value, x + k * cw, cy + sub_px + 2, cw - 8, sub_px, bold=True))
    return lines, extra


def _plane(d, cx, cy, size) -> None:
    """A plane seen from above, nose to the right, as solid shapes (thin lines vanish on e-ink)."""
    s = size / 2
    d.polygon([(cx + s, cy), (cx - s * 0.7, cy - s * 0.18), (cx - s * 0.7, cy + s * 0.18)], fill=T.BLACK)   # body
    d.polygon([(cx + s * 0.1, cy), (cx - s * 0.35, cy - s), (cx - s * 0.5, cy - s), (cx - s * 0.2, cy)], fill=T.BLACK)
    d.polygon([(cx + s * 0.1, cy), (cx - s * 0.35, cy + s), (cx - s * 0.5, cy + s), (cx - s * 0.2, cy)], fill=T.BLACK)
    d.polygon([(cx - s * 0.6, cy), (cx - s * 0.85, cy - s * 0.42), (cx - s * 0.95, cy - s * 0.42), (cx - s * 0.8, cy)], fill=T.BLACK)
    d.polygon([(cx - s * 0.6, cy), (cx - s * 0.85, cy + s * 0.42), (cx - s * 0.95, cy + s * 0.42), (cx - s * 0.8, cy)], fill=T.BLACK)


def draw(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    got = plan(el, data, box, scale=scale)
    if got is None:
        return                                      # nothing fetched yet stays blank, so nothing flashes
    lines, extra = got
    if extra.get("message"):
        hero.message(d, box, lines[0].text)
        return
    hero.draw_lines(d, lines)
    if extra.get("bar"):
        bx, by, bw, bh = extra["bar"]
        r = bh // 2
        d.rounded_rectangle([bx, by, bx + bw - 1, by + bh - 1], radius=r, outline=T.BLACK, width=2)
        done = round(bw * extra["done"])
        if done > bh:
            d.rounded_rectangle([bx, by, bx + done - 1, by + bh - 1], radius=r, fill=T.BLACK)
        size = max(18, bh * 4)
        px = min(bx + bw - size // 2, max(bx + size // 2, bx + done))
        halo = size // 2 + 3                        # a clear ring, so the plane reads over the bar
        d.ellipse([px - halo, by + bh // 2 - halo, px + halo, by + bh // 2 + halo], fill=T.WHITE)
        _plane(d, px, by + bh // 2, size)
