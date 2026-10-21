"""The states an entity has, with the icon Home Assistant gives each, for an icon that
follows it (the editor's "Changes with a sensor").

Three places say what states there are: Home Assistant's own words for its kind
(render/states.py), the choices it lists (a select's or an enum sensor's
`options`), and what it really was over the recorder's last days, with the
icon it had then (a template sensor's icon can change with its state: a cat's
location reads "Outdoor Cat" with mdi:cat). render/states.offered puts them
together, offering only icons the panel can draw; this only reads them. A measurement (a unit, a state class) has
numbers, not states, so its history isn't read.
"""
from __future__ import annotations

import time
import urllib.parse
from datetime import datetime

from config import HA_TOKEN, valid_entity_id
from fixture import load_fixture
from ha import ha_json
from render import layout, states

DAYS = 10                      # the recorder's own default keep


def _measures(attrs: dict) -> bool:
    return bool(attrs.get("unit_of_measurement") or attrs.get("unit") or attrs.get("state_class"))


async def _history(session, eid: str, since: float) -> list[tuple[str, str]]:
    """(state, icon) for each row of the recorder since `since`, newest first."""
    at = urllib.parse.quote(datetime.fromtimestamp(since).astimezone().isoformat(), safe=":+")
    got = await ha_json(session, f"/history/period/{at}?filter_entity_id={urllib.parse.quote(eid, safe='.')}")
    rows = list(got[0]) if got and got[0] else []
    return [(r.get("state"), str((r.get("attributes") or {}).get("icon") or "")) for r in reversed(rows) if isinstance(r, dict)]


async def fetch(session, entity_id: str, now: float | None = None) -> list[dict]:
    """[{"state", "word", "icon"}] for an entity (render/states.offered), [] for no entity."""
    eid = str(entity_id or "").strip()
    if not valid_entity_id(eid):
        return []
    if not HA_TOKEN:
        st = (load_fixture().get("states") or {}).get(eid) or {}
        seen = [] if _measures(st) else [(st.get("state"), str(st.get("icon") or ""))]
        return states.offered(eid, st.get("device_class") or "", st.get("options") or (), seen, layout.can_draw_icon)
    st = await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
    attrs = st.get("attributes") or {}
    seen = []
    if not _measures(attrs):
        seen = [(st.get("state"), str(attrs.get("icon") or ""))]
        now = time.time() if now is None else now
        try:
            seen += await _history(session, eid, now - DAYS * 86400)
        except Exception as exc:          # the recorder is optional: the rest still stands
            print(f"states of {eid}: no history ({exc.__class__.__name__})", flush=True)
    return states.offered(eid, attrs.get("device_class") or "", attrs.get("options") or (), seen, layout.can_draw_icon)
