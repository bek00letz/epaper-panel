"""What Home Assistant itself knows that a widget shows whole: the sun, media players.

Read through templates, one request each, in the background (live_data), so
a render never waits on Home Assistant. Without a token (running offline),
example values from render/fixture.json stand in.
"""
import json
from datetime import datetime, timedelta

import runtime
from config import HA_TOKEN
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


def _offline_sun() -> dict:
    now = datetime.now().astimezone()
    rise = now.replace(hour=7, minute=41, second=0, microsecond=0)
    set_ = now.replace(hour=18, minute=22, second=0, microsecond=0)
    if rise <= now:
        rise += timedelta(days=1)
    if set_ <= now:
        set_ += timedelta(days=1)
    return {"rising": rise.isoformat(), "setting": set_.isoformat()}


@runtime.live(300)
async def fetch_sun(session):
    """{"rising", "setting"}: Home Assistant's next sunrise and sunset, in its time zone ("" if it has no sun)."""
    if not HA_TOKEN:
        return _offline_sun()
    got = await _json_template(session, SUN_TEMPLATE)
    return {"rising": str(got.get("rising") or ""), "setting": str(got.get("setting") or "")}
