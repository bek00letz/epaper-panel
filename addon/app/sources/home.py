"""What Home Assistant itself knows that a widget shows whole: the sun, media players.

Read through templates, one request each, in the background (live_data), so
a render never waits on Home Assistant. Without a token (running offline),
example values from render/fixture.json stand in.
"""
import json
from datetime import datetime

import examples
import runtime
from config import HA_TOKEN, valid_entity_id
from ha import ha_template

SUN_TEMPLATE = (
    "{% set r = state_attr('sun.sun', 'next_rising') %}"
    "{% set s = state_attr('sun.sun', 'next_setting') %}"
    "{{ {'rising': (as_local(as_datetime(r)).isoformat() if r else ''),"
    " 'setting': (as_local(as_datetime(s)).isoformat() if s else '')} | to_json }}"
)


async def _json_template(session, tpl):
    out = await ha_template(session, tpl)
    if out is None:
        raise ConnectionError("Home Assistant didn't answer a template")
    return json.loads(out)


@runtime.live(300)
async def fetch_sun(session):
    """{"rising", "setting"}: Home Assistant's next sunrise and sunset, in its time zone ("" if it has no sun)."""
    if not HA_TOKEN:
        return examples.sun(datetime.now().astimezone())
    got = await _json_template(session, SUN_TEMPLATE)
    return {"rising": str(got.get("rising") or ""), "setting": str(got.get("setting") or "")}


def _now_playing_template(entities: list[str]) -> str:
    """Every listed player that's playing (all media players when none is listed), as JSON."""
    if entities:
        quoted = ", ".join("'" + e.replace("\\", "\\\\").replace("'", "\\'") + "'" for e in entities)
        pick = f"expand([{quoted}])"
    else:
        pick = "states.media_player"
    return (
        "{% set ns = namespace(out=[]) %}"
        f"{{% for s in {pick} | selectattr('state', 'eq', 'playing') %}}"
        "{% set a = s.attributes %}"
        # .get(): a missing attribute read as a.name puts a warning in Home Assistant's log every time.
        "{% set ns.out = ns.out + [{'entity': s.entity_id, 'player': s.name,"
        " 'title': a.get('media_title') or a.get('title') or '',"
        " 'artist': a.get('media_artist') or a.get('media_album_artist') or '',"
        " 'series': a.get('media_series_title') or '', 'season': a.get('media_season') or '',"
        " 'episode': a.get('media_episode') or '', 'kind': a.get('media_content_type') or '',"
        " 'app': a.get('app_name') or '', 'since': s.last_changed.isoformat()}] %}"
        "{% endfor %}{{ ns.out | to_json }}"
    )


def players(raw) -> list[str]:
    """The media players a widget follows: "a, b" or a list; [] means all of them."""
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    return [e.strip() for e in items if valid_entity_id(str(e).strip()) and str(e).strip().startswith("media_player.")]


@runtime.live(10)
async def fetch_now_playing(session, entities=()):
    """What's playing, latest started first: [{"entity", "player", "title", "artist", "series",
    "season", "episode", "kind", "app", "since"}]. [] when nothing plays."""
    if not HA_TOKEN:
        return list(examples.PLAYING)
    got = await _json_template(session, _now_playing_template(list(entities)))
    rows = [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []
    rows.sort(key=lambda r: str(r.get("since") or ""), reverse=True)
    for r in rows:
        r["key"] = r.get("entity")              # one slice per player, kept as others start and stop
    return rows


async def episodes(session, entity, days=7):
    """A calendar of shows' events for the next days (sources.ha_services, in the background).
    Offline, example episodes."""
    if not HA_TOKEN:
        return examples.episodes(datetime.now().astimezone())
    from sources.ha_services import fetch_calendar_events
    return await fetch_calendar_events(session, entity, days=days)
