"""Jellyfin: what is new and not yet watched.

A preset rather than a generic REST source, because the question needs real
query shaping -- latest, unplayed, grouped so a series arrives as one entry
with a count -- and because Home Assistant's own Jellyfin integration does
not answer it. It reports who is watching; it knows nothing about the
library.
"""
import urllib.parse
from datetime import datetime, timedelta, timezone

import aiohttp


def human_ago(dt, now=None):
    now = now or datetime.now(timezone.utc)
    days = (now.date() - dt.astimezone(now.tzinfo).date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return dt.strftime("%-d %b").lower()


# The parts `detail` is made of, each on its own so a page can show one
# without the rest. Every item carries the same keys, so a page that steps
# through the items finds each part on each item (subitems.item_value).
PARTS = ("kind", "what_is_new", "episode_name", "episode_number", "new_episodes",
         "added", "added_ago", "year", "runtime", "about")
EMPTY = {k: "" for k in PARTS} | {"new_episodes": 0}
UP_NEXT_ROWS = 5
UP_NEXT_TITLE = 30        # characters; a row then fits the panel's width at 26 px


def episode_number(it):
    """S02E04, or E04 without a season, or "" when Jellyfin has no numbers."""
    ep, season, end = it.get("IndexNumber"), it.get("ParentIndexNumber"), it.get("IndexNumberEnd")
    if not isinstance(ep, int):
        return ""
    text = f"S{season:02d}E{ep:02d}" if isinstance(season, int) else f"E{ep:02d}"
    if isinstance(end, int) and end > ep:
        text += f"–E{end:02d}"
    return text


def runtime(it):
    """45 min, or 1 h 52 min; "" when Jellyfin doesn't know."""
    ticks = it.get("RunTimeTicks")
    if not isinstance(ticks, (int, float)) or ticks <= 0:
        return ""
    mins = max(1, round(ticks / 600_000_000))      # 10 million ticks a second
    h, m = divmod(mins, 60)
    if not h:
        return f"{m} min"
    return f"{h} h {m} min" if m else f"{h} h"


def shorten(text, limit):
    """Cut at a word boundary with an ellipsis, so a row stays one line."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" ,·:-–") + "…"


def up_next(items):
    """The first few items, one line each, for a text box that wraps."""
    rows = []
    for d in items[:UP_NEXT_ROWS]:
        short = d["episode_number"] or (f"{d['new_episodes']} new" if d["kind"] == "series" else d["kind"])
        rows.append(f"{shorten(d['title'], UP_NEXT_TITLE)} · {short} · {d['added_ago']}")
    return "\n".join(rows)


def describe(it, now=None):
    """One item from /Items/Latest as what a page shows, or None without a date."""
    raw = it.get("DateCreated")
    if not raw:
        return None
    try:
        added = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if added.tzinfo is None:
        added = added.replace(tzinfo=timezone.utc)
    kind = it.get("Type")
    episode, number, new = "", "", 0
    year = it.get("ProductionYear") if isinstance(it.get("ProductionYear"), int) else ""
    length = runtime(it)
    if kind == "Episode":
        title, detail = (it.get("SeriesName") or it.get("Name")), it.get("Name")
        episode, number, new = it.get("Name") or "", episode_number(it), 1
        kind = "episode"
    elif kind == "Series":
        n = it.get("ChildCount") or 0
        title = it.get("Name")
        detail = f"{n} new episodes" if n != 1 else "1 new episode"
        new, kind = n, "series"
        length = ""                        # the series' typical episode, not what's new
    else:
        title, detail = it.get("Name"), "film"
        kind = "film"
    ago = human_ago(added, now)
    # The line under the name on a card: which episode, how many, or the film's year and length.
    if kind == "episode":
        about = " · ".join(x for x in (number, episode) if x)
    elif kind == "series":
        about = detail
    else:
        about = " · ".join(str(x) for x in (year, length) if x)
    return {"id": str(it.get("Id") or it.get("id") or title or "?"), "title": title or "?",
            "detail": f"{detail} · {ago}",
            "kind": kind, "what_is_new": detail or "", "episode_name": episode,
            "episode_number": number, "new_episodes": new,
            "added": added.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            "added_ago": ago, "year": year, "runtime": length, "about": about,
            "_added": added}


async def _get(session, base, key, path, **params):
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    timeout = aiohttp.ClientTimeout(total=15)
    async with session.get(url, headers={"X-Emby-Token": key}, timeout=timeout) as r:
        r.raise_for_status()
        return await r.json()


async def _fetch_items(s, src, base, key):
    user = (src.get("user") or "").strip()
    if not user or (len(user) != 32 and "-" not in user):
        users = await _get(s, base, key, "/Users")
        match = next((u for u in users
                      if user and user.lower() == (u.get("Name", "") or "").lower()), None)
        user = (match or (users[0] if users else {})).get("Id", "")
    if not user:
        return []
    return await _get(s, base, key, "/Items/Latest", userId=user, Limit=20,
                      IsPlayed="false", IncludeItemTypes="Movie,Episode",
                      GroupItems="true", Fields="SeriesName,DateCreated,ChildCount")


async def fetch(src, ctx):
    base = (src.get("base") or "").strip().rstrip("/")
    key = src.get("key")
    if not base or not key or not base.startswith(("http://", "https://")):
        return []
    days = max(1, min(3650, int(src.get("days") or 30)))

    shared = (ctx or {}).get("session")
    if shared is not None:
        items = await _fetch_items(shared, src, base, key)
    else:
        async with aiohttp.ClientSession() as s:
            items = await _fetch_items(s, src, base, key)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    out = [d for d in (describe(it, now) for it in items) if d and d["_added"] >= cutoff]
    for d in out:
        del d["_added"]

    name = src["name"]
    top = out[0] if out else None
    return [
        (f"sensor.epaper_{name}", top["title"] if top else "nothing new",
         {"detail": top["detail"] if top else "", "count": len(out),
          **{k: (top[k] if top else EMPTY[k]) for k in PARTS},
          "up_next": up_next(out),
          "titles": [i["title"] for i in out],
          "items": out[:10],
          "friendly_name": src.get("friendly_name") or "Next to watch",
          "icon": "mdi:television-play"}),
        (f"sensor.epaper_{name}_count", len(out),
         {"friendly_name": f"{src.get('friendly_name') or 'Next to watch'} count",
          "icon": "mdi:television-play"}),
    ]


def _plain_error(exc) -> str:
    """What went wrong connecting, in words that say what to do next."""
    status = getattr(exc, "status", None)
    if status in (401, 403):
        return "Jellyfin didn't accept that API key. Make one in Jellyfin under Dashboard › API Keys, then paste it here."
    if status is not None:
        return "That address answered, but not like Jellyfin. Check it's the address you open Jellyfin at, without /web at the end."
    return ("Couldn't reach Jellyfin at that address. Check it opens in a browser on the same network as Home Assistant, "
            "including the port (often :8096).")


async def check(base: str, key: str, session=None) -> dict:
    """Try an address and API key before saving them: {"ok", "users": [{"id", "name"}], "titles"}
    or {"ok": false, "error"}. `titles`: films and series in the library."""
    base = (base or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "error": "That isn't a web address. It starts with http:// or https://, like http://192.168.1.20:8096."}
    if not (key or "").strip():
        return {"ok": False, "error": "Paste an API key from Jellyfin's Dashboard › API Keys."}
    try:
        if session is None:
            async with aiohttp.ClientSession() as s:
                return await check(base, key, s)
        users = await _get(session, base, key.strip(), "/Users")
        counts = await _get(session, base, key.strip(), "/Items/Counts")
    except Exception as exc:
        return {"ok": False, "error": _plain_error(exc)}
    if not isinstance(users, list):
        return {"ok": False, "error": "That address answered, but not like Jellyfin. Check it's the address you open Jellyfin at, without /web at the end."}
    titles = sum(int((counts or {}).get(k) or 0) for k in ("MovieCount", "SeriesCount")) if isinstance(counts, dict) else 0
    return {"ok": True, "titles": titles,
            "users": [{"id": str(u.get("Id") or ""), "name": str(u.get("Name") or "")} for u in users if isinstance(u, dict)]}
