"""Reading what Home Assistant already has, one way for every page built on it.

The year grid, commute times, departures and the mail list are layouts over data Home Assistant
keeps: sensors and their attributes, the integrations that made them, long-term statistics. They
read it here, so each asks the same way, with the same checks:

- `found_by`: the sensors an integration made (`integration_entities`), so a first page needs
  nothing picked: it finds your travel times, your transit sensors, your mail;
- `states_of`: several sensors' state, name, attributes and when they were updated, in one request;
- `statistics_meta` and `statistics`: long-term statistics, which only the websocket reaches.

Every entity ID that goes into a template is checked first (`valid_entity_id`). A request that
fails raises, so live_data keeps the last good value; nothing here is called during a render.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import health
import runtime
from config import valid_entity_id
from ha import ha_template
from sources.geo import get_home_timezone

# A state that isn't a value: the sensor is there, but has nothing to say right now.
NO_VALUE = ("unavailable", "unknown", "none", "")
STATISTICS = "Home Assistant statistics"


def clean_ids(ids) -> list[str]:
    """Entity IDs that can go into a template, in order, each once."""
    out = []
    for raw in ids or ():
        e = str(raw or "").strip()
        if valid_entity_id(e) and e not in out:
            out.append(e)
    return out


def no_value(state) -> bool:
    return str(state if state is not None else "").strip().lower() in NO_VALUE


async def home_now(session) -> datetime:
    """Now in Home Assistant's time zone: its "today" is the one a page means."""
    tz = await get_home_timezone(session)
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.now().astimezone()


async def _json(session, tpl: str):
    raw = await ha_template(session, tpl)
    if raw is None:
        raise ConnectionError("Home Assistant didn't answer a template")
    return json.loads(raw) if raw else None


def _quoted(ids: list[str]) -> str:
    return "[" + ", ".join(f"'{e}'" for e in ids) + "]"


async def found_by(session, integrations, domain: str = "sensor") -> list[str]:
    """The entities the integrations made, in this domain, in the order Home Assistant lists them.
    An integration that isn't set up has none; that's an answer, not a failure."""
    names = [i for i in integrations if i.replace("_", "").isalnum()]
    if not names:
        return []
    tpl = ("{%- set ns = namespace(out=[]) -%}{%- for i in " + _quoted(names) + " -%}"
           "{%- set ns.out = ns.out + (integration_entities(i) | select('match', '" + domain + "[.]') | list) -%}"
           "{%- endfor -%}{{ ns.out | unique | list | to_json }}")
    got = await _json(session, tpl)
    return clean_ids(got if isinstance(got, list) else [])


STATES_TEMPLATE = """
{%- set ns = namespace(out=[]) -%}
{%- for e in IDS -%}
{%- set s = states[e] -%}
{%- if s is defined and s is not none -%}
{%- set ns.out = ns.out + [{'entity': e, 'state': s.state, 'name': s.name, 'attributes': dict(s.attributes),
  'updated': as_timestamp(s.last_updated), 'entry': config_entry_id(e)}] -%}
{%- else -%}
{%- set ns.out = ns.out + [{'entity': e, 'state': none, 'name': none, 'attributes': {}, 'updated': none, 'entry': none}] -%}
{%- endif -%}
{%- endfor -%}
{{ ns.out | to_json }}
"""


async def states_of(session, ids) -> list[dict]:
    """[{"entity", "state", "name", "attributes", "updated", "entry"}] for each ID, in order; one that
    Home Assistant doesn't have comes back with state None. `entry` is its config entry's ID."""
    ids = clean_ids(ids)
    if not ids:
        return []
    got = await _json(session, STATES_TEMPLATE.replace("IDS", _quoted(ids)))
    rows = [r for r in (got if isinstance(got, list) else []) if isinstance(r, dict)]
    return [{"entity": r.get("entity"), "state": r.get("state"), "name": r.get("name") or "",
             "attributes": r.get("attributes") if isinstance(r.get("attributes"), dict) else {},
             "updated": r.get("updated"), "entry": r.get("entry") or ""} for r in rows]


# ------------------------------------------------------------------ long-term statistics

def mean_kind(meta: dict) -> bool:
    """Whether a statistic keeps a mean (Home Assistant wrote `has_mean` before 2025.8, `mean_type` after)."""
    if "mean_type" in meta:
        return bool(meta.get("mean_type"))
    return bool(meta.get("has_mean"))


async def statistics_meta(ids) -> dict[str, dict]:
    """{statistic_id: its metadata} for those Home Assistant keeps statistics of."""
    ids = clean_ids(ids)
    if not ids:
        return {}
    try:
        got = await runtime.HASS.ws({"type": "recorder/get_statistics_metadata", "statistic_ids": ids}, timeout=15)
    except Exception as exc:
        health.fail(STATISTICS, exc)
        raise
    return {m["statistic_id"]: m for m in got or [] if isinstance(m, dict) and m.get("statistic_id")}


async def statistics(ids, start: datetime, period: str, types, units: dict | None = None) -> dict:
    """recorder/statistics_during_period from `start` to now: {statistic_id: [rows]}."""
    ids = clean_ids(ids)
    if not ids:
        return {}
    req = {"type": "recorder/statistics_during_period", "start_time": start.isoformat(),
           "statistic_ids": ids, "period": period, "types": list(types)}
    if units:
        req["units"] = units
    try:
        got = await runtime.HASS.ws(req, timeout=20) or {}
    except Exception as exc:
        health.fail(STATISTICS, exc)
        raise
    health.ok(STATISTICS)
    return got if isinstance(got, dict) else {}


def row_start(row: dict, tz) -> datetime | None:
    """When a statistics row starts, in `tz`: Home Assistant gives epoch milliseconds (an ISO
    string before 2023.3)."""
    raw = row.get("start")
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000 if raw > 1e11 else raw, tz)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(tz)
    except (TypeError, ValueError, OSError):
        return None
