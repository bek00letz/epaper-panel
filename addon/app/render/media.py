"""Watch and listen: Now playing (any media player) and On TV this week (any calendar of shows).

Now playing gets a list of the players that are playing, latest started
first; each is its own item of the page (1 of 2, like planes overhead), so
`sub_index` says which one this is. On TV this week gets a calendar's
events and lists the next episodes, a row each, as many as read well.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import clock, hero
from . import theme as T
from .words import cap, say
from .todo import now_in

TITLE_LINES = 2
ICONS = {"music": "mdi:music", "tvshow": "mdi:television-classic", "episode": "mdi:television-classic",
         "movie": "mdi:movie-open", "video": "mdi:play-box", "podcast": "mdi:podcast"}


def _episode(season, episode) -> str:
    try:
        return say("media.episode", season=int(season), episode=int(episode))
    except (TypeError, ValueError):
        return ""


def describe(item: dict) -> tuple[str, str, str]:
    """(title, the line under it, icon) for a playing item. The line says who or what show,
    and on what: "Debussy · Living room", "Severance · S2 E5 · Living room TV"."""
    title = str(item.get("title") or "").strip()
    series = str(item.get("series") or "").strip()
    by = series or str(item.get("artist") or "").strip()
    ep = _episode(item.get("season"), item.get("episode")) if series else ""
    where = str(item.get("player") or "").strip()
    app = str(item.get("app") or "").strip()
    if not title:                       # some apps say only which app is playing
        title, app = app or say("media.playing"), ""
    parts = [p for p in (by, ep, where if not app else say("media.app_on", app=app, where=where) if where else app) if p]
    kind = str(item.get("kind") or "").lower()
    icon = ICONS.get(kind) or ("mdi:television-classic" if series else "mdi:music" if item.get("artist") else "mdi:play-circle")
    return title, " · ".join(parts), icon


def draw_now_playing(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, list):
        return
    if not data:
        hero.message(d, box, say("media.nothing"))
        return
    try:
        item = data[max(0, int(el.get("sub_index", 0))) % len(data)]
    except (TypeError, ValueError):
        item = data[0]
    title, line, icon = describe(item if isinstance(item, dict) else {})
    x, y, w, h = box
    # Like hero's layout, but the title may take two lines before it gets smaller.
    title_px = min(round(h * 0.36 * scale), round(h * 0.5))
    icon_px = round(title_px * 1.1)
    text_x = x + icon_px + round(title_px * 0.4)
    text_w = x + w - text_x
    cap_px = max(hero.MIN_CAPTION, round(title_px * 0.42))
    room = h - (cap_px * 2 if line else 0)
    size = T.fit_wrapped(title, text_w, room, title_px, floor=hero.MIN_VALUE, bold=True)
    tf = T.font(size, bold=True, text=title)
    lines = T.wrap_lines(title, tf, text_w)
    if len(lines) > TITLE_LINES:
        lines = lines[:TITLE_LINES - 1] + [hero.shorten(" ".join(lines[TITLE_LINES - 1:]), tf, text_w)]
    lines = [hero.shorten(ln, tf, text_w) for ln in lines]
    cap_px = max(hero.MIN_CAPTION, min(cap_px, round(size * 0.5)))
    cf = T.font(cap_px, bold=False, text=line)
    asc, desc = tf.getmetrics()
    lh = round((asc + desc) * 0.98)
    gap = round(cap_px * 0.7) if line else 0
    block = lh * len(lines) + (gap + cap_px if line else 0)
    top = y + max(0, (h - block) // 2)
    hero.icon(img, d, icon, (x, top + (min(block, lh * len(lines)) - icon_px) // 2, icon_px, icon_px))
    for k, ln in enumerate(lines):
        d.text((text_x, top + k * lh), ln, font=tf, fill=T.BLACK)
    if line:
        d.text((text_x, top + lh * len(lines) + gap), hero.shorten(line, cf, text_w), font=cf, fill=T.BLACK)


# ---------------------------------------------------------------- On TV this week

# "Slow Horses - S06E06 - Judgement Day" (Sonarr), "Show - 6x06 - Title", "Show S01E02".
_SXE = re.compile(r"^(?P<show>.+?)\s*[-–:·]?\s*(?:S(?P<s>\d{1,3})\s*E(?P<e>\d{1,4})|(?P<s2>\d{1,3})x(?P<e2>\d{1,4}))"
                  r"(?:\s*[-–:·]\s*(?P<title>.*))?$", re.I)
_YEAR = re.compile(r"\s*\((?:19|20)\d\d\)$")


def episode_of(summary: str) -> tuple[str, str, str]:
    """(show, "S6 E6", episode title) from a calendar event's summary; a summary that isn't
    an episode (a film, from Radarr) is the show, with no episode."""
    text = str(summary or "").strip()
    m = _SXE.match(text)
    if not m:
        return text, "", ""
    show = _YEAR.sub("", m.group("show").strip(" -–:·")) or m.group("show")
    return show, _episode(m.group("s") or m.group("s2"), m.group("e") or m.group("e2")), (m.group("title") or "").strip()


def _start(ev: dict, tz) -> datetime | None:
    raw = ev.get("start") or ev.get("start_time") or ""
    if isinstance(raw, dict):
        raw = raw.get("dateTime") or raw.get("date") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)


def day_label(when: datetime, now: datetime) -> str:
    days = (when.date() - now.date()).days
    if days <= 0:
        return say("day.tonight") if when.hour >= 17 else say("day.today")
    if days == 1:
        return say("day.tomorrow")
    return cap(clock.date(when, "weekday")) if days < 7 else clock.date(when, "date")


def upcoming(events, now: datetime, days: int = 7) -> list[dict]:
    """Episodes from today on, in order: [{"day", "show", "ep", "title", "when"}]."""
    out = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        when = _start(ev, now.tzinfo)
        if when is None or when.date() < now.date() or (when.date() - now.date()).days >= days:
            continue
        show, ep, title = episode_of(ev.get("summary") or ev.get("message") or "")
        out.append({"when": when, "day": day_label(when, now), "show": show, "ep": ep, "title": title})
    out.sort(key=lambda r: r["when"])
    return out


def draw_tv_week(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    x, y, w, h = box
    if not str(el.get("entity") or "").strip():
        hero.message(d, box, say("media.choose_calendar"))
        return
    if not isinstance(data, dict):
        return
    now = now_in(data.get("tz"))
    try:
        days = max(1, min(31, int(el.get("days") or 7)))
    except (TypeError, ValueError):
        days = 7
    rows = upcoming(data.get("events"), now, days)
    title = str(el.get("title") or (say("media.on_tv_week") if days == 7 else say("media.on_tv_days", days))).strip()
    row_px = max(hero.MIN_CAPTION + 2, min(round(h * 0.135 * scale), round(h * 0.25)))
    head_px = max(hero.MIN_CAPTION, round(row_px * 0.85))
    hf = T.font(head_px, bold=False)
    count = str(len(rows)) if rows else ""
    cw = T.text_width(count, T.font(head_px, bold=True)) if count else 0
    d.text((x, y), hero.shorten(title, hf, w - cw - 12), font=hf, fill=T.BLACK)
    if count:
        d.text((x + w, y), count, font=T.font(head_px, bold=True), fill=T.BLACK, anchor="ra")
    top = y + round(head_px * 1.9)
    if not rows:
        hero.message(d, (x, top, w, y + h - top), say("media.none_week") if days == 7 else say("media.none_soon"))
        return
    bold, reg = T.font(row_px, bold=True), T.font(row_px, bold=False)
    asc, desc = bold.getmetrics()
    pitch = round((asc + desc) * 1.2)
    fit = max(1, (y + h - top + pitch - asc - desc) // pitch)    # the last row needs no space under it
    shown = rows if len(rows) <= fit else rows[:fit - 1]
    day_w = max(T.text_width(r["day"], bold) for r in shown) + round(row_px * 0.6)
    for k, r in enumerate(shown):
        ry = top + k * pitch
        f = bold if k == 0 else reg                    # the next one stands out
        if k == 0 or r["day"] != shown[k - 1]["day"]:   # a day said once, for its first show
            d.text((x, ry), r["day"], font=f, fill=T.BLACK)
        ep_w = T.text_width(r["ep"], f) if r["ep"] else 0
        d.text((x + w, ry), r["ep"], font=f, fill=T.BLACK, anchor="ra")
        d.text((x + day_w, ry), hero.shorten(r["show"], f, w - day_w - ep_w - round(row_px * 0.6)), font=f, fill=T.BLACK)
    if len(shown) < len(rows):
        d.text((x + day_w, top + len(shown) * pitch), say("and_more", len(rows) - len(shown)), font=reg, fill=T.BLACK)
