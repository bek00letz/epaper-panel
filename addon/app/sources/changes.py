"""When a sensor last really changed: it took a new value, not Home Assistant
restarting or the sensor dropping out and coming back with the one it had.

Home Assistant's own `last_changed` moves for both (on 21 Oct, 329 sensors
"changed" in the same second as it restarted), so a "changed in the last 30
minutes" page would come up after every restart. Its history (the recorder)
has every value a sensor took, so a change here is a real value that differs
from the real value before it; unavailable and unknown are skipped over. A
sensor that comes back from unavailable with another value has changed.

Nothing is kept here: the history is Home Assistant's, read for the minutes
asked about and only when `last_changed` says something happened in them. A
sensor the recorder leaves out has no history; then `last_changed` is all
there is, and the answer says so (`history: False`).
"""
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime

import runtime
from config import HA_TOKEN, valid_entity_id
from fixture import load_fixture
from ha import ha_json, ha_template

NO_VALUE = (None, "", "unavailable", "unknown")
LOOK_BACK = 24 * 3600          # how far back to find the value before a window that starts with none


def _when(text) -> float | None:
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except (TypeError, ValueError):
        return None


def last_real_change(rows: list[dict], since: float) -> tuple[float, str] | None:
    """The last change after `since` in history rows (oldest first): (when, to).
    A row is a change when its value is real and differs from the last real one.
    None when there was none, or when no real value came before to compare with."""
    prev, found = None, None
    for r in rows:
        s = r.get("state")
        if s in NO_VALUE:
            continue
        t = _when(r.get("last_changed") or r.get("last_updated"))
        if prev is not None and s != prev and t is not None and t > since:
            found = (t, s)
        prev = s
    return found


def _state_template(eid: str) -> str:
    q = f"states['{eid}']"
    return ("{{ {'state': states('%s'), 'changed': (as_timestamp(%s.last_changed) "
            "if %s is defined and %s is not none else none)} | to_json }}" % (eid, q, q, q))


async def _history(session, eid: str, start: float) -> list[dict]:
    at = urllib.parse.quote(datetime.fromtimestamp(start).astimezone().isoformat(), safe=":+")
    got = await ha_json(session, f"/history/period/{at}?filter_entity_id={urllib.parse.quote(eid, safe='.')}"
                                 "&minimal_response&no_attributes")
    return list(got[0]) if got and got[0] else []


async def change(session, entity_id: str, minutes: int, now: float | None = None) -> dict:
    """{"state", "at", "to", "history"}: the sensor's value now, and when (epoch seconds) it last
    really changed and to what, if that was in the last `minutes`; "at" is None when it wasn't."""
    eid = str(entity_id or "").strip()
    now = time.time() if now is None else now
    out = {"state": None, "at": None, "to": None, "history": True}
    if not valid_entity_id(eid):
        return out
    since = now - max(1, int(minutes)) * 60
    if not HA_TOKEN:
        st = (load_fixture().get("states") or {}).get(eid) or {}
        out["state"] = st.get("state")
        at = _when(st.get("last_changed"))
        if at is not None and at > since and out["state"] not in NO_VALUE:
            out.update(at=at, to=out["state"])
        return out
    raw = await ha_template(session, _state_template(eid))
    if raw is None:
        raise ConnectionError("Home Assistant didn't answer a template")
    got = json.loads(raw)
    out["state"] = got.get("state")
    stamp = got.get("changed")
    if out["state"] in NO_VALUE or stamp is None or float(stamp) <= since:
        return out                    # no value now, or nothing at all has happened in the window
    rows = await _history(session, eid, since)
    if not rows:
        # The recorder leaves it out: Home Assistant's word is all there is.
        out.update(at=float(stamp), to=out["state"], history=False)
        return out
    if rows[0].get("state") in NO_VALUE:
        rows = await _history(session, eid, since - LOOK_BACK)   # what it was before it dropped out
    found = last_real_change(rows, since)
    if found:
        out["at"], out["to"] = found
    return out


@runtime.live(15)
async def fetch_change(session, entity_id, minutes):
    """`change`, kept fresh in the background so a render never waits on the history."""
    return await change(session, entity_id, minutes)
