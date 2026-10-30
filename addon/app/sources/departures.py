"""The next departures, from whatever transit integration someone has.

Transit integrations put departures in Home Assistant in a few shapes, and this reads them all
into one: [{"at": ISO time, "line", "destination", "delay", "platform"}], soonest first.

- A list in an attribute (`next_departures`, `departures`, `next`, `upcoming`...), each item a
  set of fields (RMV, Rejseplanen, HVV's "next") or just a time (GTFS's next departures).
- The sensor itself as one departure: its state a time (a timestamp sensor: GTFS, HVV, Swiss
  public transport, NextBus) or the minutes until it (Rejseplanen, RMV), with the line and
  destination in its attributes. Several such sensors (departure 0, 1, 2) are merged.

Each field is found by the names integrations use (`TIME`, `LINE`, `TO`...); when one is unusual,
the page says which attribute holds the list, the time, the line and the destination (`keys`).
A time is an ISO time, seconds since 1970, a time of day ("14:05", today or else tomorrow), or
minutes from when the sensor last updated.

A page with no sensors picked shows every sensor that looks like departures (`FIND`), from any
integration, core or not.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import examples
import runtime
from config import HA_TOKEN
from ha import ha_template
from sources import hass_read

LISTS = ("next_departures", "departures", "next", "upcoming", "upcoming_departures", "next_buses",
         "next_trains", "trips", "journeys", "connections", "data")
TIME = ("departure_time_actual", "real_time", "realtime", "expected", "expected_departure", "estimated",
        "departure", "departure_time", "departure_timestamp", "departure_datetime", "dep_time", "due_at",
        "time", "datetime", "scheduled", "scheduled_departure", "planned", "departure_time_planned", "when")
MINUTES = ("minutes", "due_in", "departure_in", "in_minutes", "countdown", "min", "mins", "eta")
LINE = ("line", "line_name", "route_short_name", "route", "short_name", "name", "train", "train_number",
        "number", "service", "product", "route_name")
TO = ("destination", "direction", "headsign", "trip_headsign", "to", "towards", "final_destination",
      "destination_name", "destination_station_stop_name", "destination_stop_name", "terminus", "route_long_name")
DELAY = ("delay", "delay_minutes", "delayed_by")
PLATFORM = ("platform", "track", "stop_position", "gleis", "bay")
MOST = 20

# Sensors that look like departures, whatever made them: a list of departures, or a time with a line.
FIND = """
{%- set ns = namespace(out=[]) -%}
{%- for s in states.sensor -%}
{%- set a = s.attributes -%}
{%- if (LISTS | select('in', a) | list) or (a.device_class == 'timestamp' and (LINES | select('in', a) | list)) -%}
{%- set ns.out = ns.out + [s.entity_id] -%}
{%- endif -%}
{%- endfor -%}
{{ ns.out[:12] | to_json }}
"""


def keys_of(el: dict) -> dict:
    """The attributes a page names for its departures, when they're unusual: list, time, line, to."""
    return {k: str(el.get(f"{k}_key") or "").strip() for k in ("list", "time", "line", "to")}


def _first(item: dict, names, own: str = ""):
    if own:
        return item.get(own)
    lowered = {str(k).lower().replace(" ", "_"): v for k, v in item.items()}
    for n in names:
        if lowered.get(n) not in (None, ""):
            return lowered[n]
    return None


_HM = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")


def when(raw, now: datetime, base: datetime | None = None, as_minutes: bool = False) -> datetime | None:
    """A departure's time from what an integration gave, in `now`'s zone."""
    if raw is None or isinstance(raw, bool):
        return None
    if as_minutes:
        try:
            return (base or now) + timedelta(minutes=float(str(raw).replace(",", ".").split()[0]))
        except (TypeError, ValueError, IndexError):
            return None
    if isinstance(raw, (int, float)):
        if raw > 1e11:
            raw = raw / 1000
        return datetime.fromtimestamp(raw, now.tzinfo) if raw > 1e9 else None
    text = str(raw).strip()
    m = _HM.match(text)
    if m:
        at = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)), second=int(m.group(3) or 0), microsecond=0)
        return at + timedelta(days=1) if at < now - timedelta(hours=1) else at
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return at.replace(tzinfo=now.tzinfo) if at.tzinfo is None else at.astimezone(now.tzinfo)


def _text(v) -> str:
    if isinstance(v, dict):
        v = v.get("name") or v.get("short_name") or v.get("label") or ""
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:60]


def _number(v) -> int | None:
    try:
        return round(float(str(v).replace(",", ".").split()[0]))
    except (TypeError, ValueError, IndexError):
        return None


def _one(item: dict, keys: dict, now: datetime, base: datetime | None, fallback: dict | None = None) -> dict | None:
    fallback = fallback or {}
    at = None
    raw = _first(item, TIME, keys.get("time"))
    if raw is not None:
        at = when(raw, now, base)
        if at is None and keys.get("time"):            # a named field holding minutes
            at = when(raw, now, base, as_minutes=True)
    if at is None and not keys.get("time"):
        mins = _first(item, MINUTES)
        if mins is not None:
            at = when(mins, now, base, as_minutes=True)
    if at is None:
        return None
    line = _text(_first(item, LINE, keys.get("line"))) or fallback.get("line", "")
    to = _text(_first(item, TO, keys.get("to"))) or fallback.get("destination", "")
    return {"at": at.isoformat(), "line": line, "destination": to,
            "delay": _number(_first(item, DELAY)) or 0, "platform": _text(_first(item, PLATFORM))}


def from_sensor(row: dict, keys: dict, now: datetime) -> list[dict]:
    """One sensor's departures (hass_read.states_of's row)."""
    attrs = row.get("attributes") or {}
    base = datetime.fromtimestamp(row["updated"], now.tzinfo) if isinstance(row.get("updated"), (int, float)) else now
    own = {"line": _text(_first(attrs, LINE, keys.get("line"))), "destination": _text(_first(attrs, TO, keys.get("to")))}
    out = []
    lst = attrs.get(keys["list"]) if keys.get("list") else next((attrs[k] for k in LISTS if isinstance(attrs.get(k), list)), None)
    if isinstance(lst, str):
        try:
            lst = json.loads(lst)
        except ValueError:
            lst = None
    for item in lst if isinstance(lst, list) else []:
        got = _one(item, keys, now, base, own) if isinstance(item, dict) else \
            ({"at": t.isoformat(), "line": own["line"], "destination": own["destination"], "delay": 0, "platform": ""}
             if (t := when(item, now, base)) else None)
        if got:
            out.append(got)
    # The sensor itself, a departure: its state a time, or minutes when its unit says so.
    state = row.get("state")
    if not hass_read.no_value(state) and not keys.get("list"):
        unit = str(attrs.get("unit_of_measurement") or "").strip().lower()
        if unit in ("min", "minutes", "mins"):
            at = when(state, now, base, as_minutes=True)
        elif attrs.get("device_class") == "timestamp" or not unit:
            at = when(state, now, base)
        else:
            at = None
        if at is not None:
            mine = _one({**attrs, "__at": at.isoformat()}, {**keys, "time": "__at"}, now, base, own)
            if mine:
                out.insert(0, mine)
    return out


def merged(rows: list[dict], keys: dict, now: datetime, most: int = MOST) -> list[dict]:
    """Every sensor's departures together, each once, soonest first, the ones gone left out."""
    out: list[dict] = []
    for row in rows:
        for dep in from_sensor(row, keys, now):
            at = datetime.fromisoformat(dep["at"])
            if at + timedelta(minutes=max(0, dep["delay"])) < now - timedelta(seconds=30):
                continue
            # The same departure said twice (the sensor's state and its list's first): kept once, with
            # whatever it says most about.
            same = next((k for k, o in enumerate(out) if o["at"][:16] == dep["at"][:16]
                         and (not o["line"] or not dep["line"] or o["line"].lower() == dep["line"].lower())), None)
            if same is None:
                out.append(dep)
            elif sum(map(bool, dep.values())) > sum(map(bool, out[same].values())):
                out[same] = dep
    out.sort(key=lambda d: d["at"])
    return out[:most]


async def found(session) -> list[str]:
    raw = await ha_template(session, FIND.replace("LISTS", json.dumps(list(LISTS)).replace('"', "'"))
                                         .replace("LINES", json.dumps(list(LINE[:4])).replace('"', "'")))
    if raw is None:
        raise ConnectionError("Home Assistant didn't answer a template")
    return hass_read.clean_ids(json.loads(raw) if raw else [])


@runtime.live(60)
async def fetch_departures(session, entities: tuple = (), keys: tuple = ()):
    """{"departures": [...], "stop": name, "found": bool}, or {"missing": "integration"} when Home
    Assistant has nothing that looks like departures, or {"missing": "unavailable"}."""
    now = await hass_read.home_now(session)
    if not HA_TOKEN:
        return examples.departures(now)
    ks = dict(keys) or keys_of({})
    ids = hass_read.clean_ids(entities) or await found(session)
    if not ids:
        return {"departures": [], "missing": "integration"}
    rows = await hass_read.states_of(session, ids)
    live = [r for r in rows if not hass_read.no_value(r.get("state")) or any(isinstance(v, list) for v in (r.get("attributes") or {}).values())]
    if not live:
        return {"departures": [], "missing": "unavailable", "stop": rows[0].get("name") if rows else ""}
    return {"departures": merged(live, ks, now), "stop": rows[0].get("name") if len(rows) == 1 else "",
            "found": not hass_read.clean_ids(entities)}
