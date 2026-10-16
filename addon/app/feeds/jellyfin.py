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
