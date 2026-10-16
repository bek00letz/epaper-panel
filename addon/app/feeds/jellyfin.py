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


async def _get(session, base, key, path, **params):
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    async with session.get(url, headers={"X-Emby-Token": key}) as r:
        r.raise_for_status()
        return await r.json()


async def fetch(src, ctx):
    base, key = (src.get("base") or "").rstrip("/"), src.get("key")
    if not base or not key:
        return []
    days = int(src.get("days", 30))

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        user = src.get("user") or ""
        if not user or (len(user) != 32 and "-" not in user):
            users = await _get(s, base, key, "/Users")
            match = next((u for u in users
                          if user and user.lower() in (u.get("Name", "").lower(),)), None)
            user = (match or (users[0] if users else {})).get("Id", "")
        if not user:
            return []

        items = await _get(s, base, key, "/Items/Latest", userId=user, Limit=20,
                           IsPlayed="false", IncludeItemTypes="Movie,Episode",
                           GroupItems="true", Fields="SeriesName,DateCreated,ChildCount")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for it in items:
        raw = it.get("DateCreated")
        if not raw:
            continue
        try:
            added = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if added < cutoff:
            continue
        kind = it.get("Type")
        if kind == "Episode":
            title, detail = (it.get("SeriesName") or it.get("Name")), it.get("Name")
        elif kind == "Series":
            n = it.get("ChildCount") or 0
            title = it.get("Name")
            detail = f"{n} new episodes" if n != 1 else "1 new episode"
        else:
            title, detail = it.get("Name"), "film"
        out.append({"title": title or "?", "detail": f"{detail} · {human_ago(added)}"})

    name = src["name"]
    top = out[0] if out else None
    return [
        (f"sensor.epaper_{name}", top["title"] if top else "nothing new",
         {"detail": top["detail"] if top else "", "count": len(out),
          "titles": [i["title"] for i in out],
          "friendly_name": src.get("friendly_name") or "Next to watch",
          "icon": "mdi:television-play"}),
        (f"sensor.epaper_{name}_count", len(out),
         {"friendly_name": f"{src.get('friendly_name') or 'Next to watch'} count",
          "icon": "mdi:television-play"}),
    ]
