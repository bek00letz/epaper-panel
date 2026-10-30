"""Travel times from Home Assistant, against the usual.

Home Assistant's travel-time integrations (Waze Travel Time, which needs no key, and Google's and
HERE's) each make a sensor per route: its state is the minutes it takes now, with the route's
name in its attributes where the service gives one. A page with no routes picked shows every
such sensor Home Assistant has (`found_by`), so the first page already shows your commute.

"Usual" is the route's own history: the median of its hourly means at this hour, on this kind of
day (a weekday or the weekend), over the past four weeks of long-term statistics. A route Home
Assistant keeps no statistics of shows only the minutes now.
"""
from __future__ import annotations

import statistics as stats
from datetime import datetime, timedelta

import examples
import runtime
from config import HA_TOKEN
from sources import hass_read

INTEGRATIONS = ("waze_travel_time", "google_travel_time", "here_travel_time")
WEEKS = 4
# A minute is the unit; a sensor shown in another (its display unit changed in Home Assistant) is converted.
TO_MINUTES = {"min": 1.0, "h": 60.0, "s": 1 / 60, "d": 1440.0, "ms": 1 / 60000}
ROUTE_KEYS = ("route", "summary", "via")


def minutes(state, unit) -> float | None:
    try:
        v = float(state)
    except (TypeError, ValueError):
        return None
    return round(v * TO_MINUTES.get(str(unit or "min").strip(), 1.0), 1)


def route_of(attributes: dict) -> str:
    """The way it goes, as the service names it ("A1; DN1"), or ""."""
    for key in ROUTE_KEYS:
        got = str((attributes or {}).get(key) or "").strip()
        if got:
            return got[:80]
    return ""


def routes_from(rows: list[dict]) -> list[dict]:
    """hass_read.states_of's rows as routes: [{"entity", "name", "minutes", "route", "state"}],
    state "ok", "unavailable" (no value now) or "missing" (Home Assistant has no such sensor)."""
    out = []
    for r in rows:
        attrs = r.get("attributes") or {}
        mins = minutes(r.get("state"), attrs.get("unit_of_measurement"))
        state = "missing" if r.get("state") is None else "ok" if mins is not None else "unavailable"
        out.append({"entity": r.get("entity"), "name": r.get("name") or str(r.get("entity") or "").split(".")[-1],
                    "minutes": mins, "route": route_of(attrs), "state": state})
    return out


def slot(when: datetime) -> tuple[bool, int]:
    """The kind of day and the hour a time falls in: what "usual" compares like with like by."""
    return when.weekday() >= 5, when.hour


def usual_table(rows, tz) -> dict:
    """{(weekend, hour): median minutes} from a route's hourly statistics."""
    by_slot: dict[tuple[bool, int], list[float]] = {}
    for row in rows or []:
        start = hass_read.row_start(row, tz)
        if start is None or row.get("mean") is None:
            continue
        try:
            by_slot.setdefault(slot(start), []).append(float(row["mean"]))
        except (TypeError, ValueError):
            continue
    return {k: round(stats.median(v), 1) for k, v in by_slot.items() if len(v) >= 2}


def usual_at(table: dict, when: datetime) -> float | None:
    """The usual at this hour on this kind of day; else this hour on any day; else None."""
    weekend, hour = slot(when)
    if (weekend, hour) in table:
        return table[(weekend, hour)]
    return table.get((not weekend, hour))


@runtime.live(3600)
async def fetch_usual(session, entities: tuple) -> dict:
    """{entity: usual_table} for routes Home Assistant keeps statistics of, in minutes."""
    now = await hass_read.home_now(session)
    meta = await hass_read.statistics_meta(entities)
    kept = [e for e in entities if e in meta and hass_read.mean_kind(meta[e])]
    if not kept:
        return {}
    start = (now - timedelta(weeks=WEEKS)).replace(minute=0, second=0, microsecond=0)
    got = await hass_read.statistics(kept, start, "hour", ("mean",), units={"duration": "min"})
    return {e: {f"{int(k[0])}:{k[1]}": v for k, v in usual_table(got.get(e), now.tzinfo).items()} for e in kept}


def _table(stored: dict) -> dict:
    out = {}
    for key, v in (stored or {}).items():
        weekend, hour = str(key).split(":")
        out[(weekend == "1", int(hour))] = v
    return out


@runtime.live(120)
async def fetch_routes(session, entities: tuple = ()):
    """{"routes": [...], "found": bool} for the routes picked, or every travel time Home Assistant
    has when none are; {"routes": [], "missing": "integration"} when it has none."""
    now = await hass_read.home_now(session)
    if not HA_TOKEN:
        return examples.commute(now)
    ids = hass_read.clean_ids(entities) or await hass_read.found_by(session, INTEGRATIONS)
    if not ids:
        return {"routes": [], "missing": "integration"}
    routes = routes_from(await hass_read.states_of(session, ids))
    try:
        usual = await fetch_usual(session, tuple(ids)) or {}
    except Exception:
        usual = {}                              # statistics failing doesn't hide the minutes now
    for r in routes:
        r["usual"] = usual_at(_table(usual.get(r["entity"])), now)
    return {"routes": routes, "found": not hass_read.clean_ids(entities)}
