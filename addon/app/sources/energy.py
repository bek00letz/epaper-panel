"""The Energy dashboard's numbers: what it's set up with, long-term statistics, grid power and costs.

Everything comes from Home Assistant's own Energy dashboard settings
(`energy/get_prefs`), so a widget needs nothing picked: solar is every
solar source there, the grid is every grid source, costs are the cost
statistics Home Assistant keeps from its prices (`energy/info`). Totals
come from long-term statistics, which only the websocket reaches.

All of it is fetched in the background (live_data); a failure keeps the
last numbers and is reported as the "Energy dashboard" service.
"""
from __future__ import annotations

import calendar
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import health
import live_data
import runtime
from config import HA_TOKEN, valid_entity_id
from ha import ha_json
from sources.geo import get_home_timezone

SERVICE = "Energy dashboard"
PERIODS = ("day", "month", "year")
SOURCES = ("solar", "grid_import", "grid_export", "entity")
# A period's bars: one per hour of the day, day of the month, month of the year.
BUCKET = {"day": "hour", "month": "day", "year": "month"}


# ------------------------------------------------------------------ what the dashboard is set up with

def _grid_parts(src: dict) -> list[dict]:
    """A grid source as flows: [{"import", "export", "cost", "compensation"}].

    Home Assistant has written grid sources two ways: one flow each
    (`stat_energy_from`/`stat_energy_to` on the source, from 2025) and lists
    of flows (`flow_from`/`flow_to`, before). Both mean the same.
    """
    out = []
    if src.get("stat_energy_from") or src.get("stat_energy_to"):
        out.append({"import": src.get("stat_energy_from") or "", "export": src.get("stat_energy_to") or "",
                    "cost": src.get("stat_cost") or "", "compensation": src.get("stat_compensation") or ""})
    for f in src.get("flow_from") or []:
        out.append({"import": f.get("stat_energy_from") or "", "export": "", "cost": f.get("stat_cost") or "", "compensation": ""})
    for f in src.get("flow_to") or []:
        out.append({"import": "", "export": f.get("stat_energy_to") or "", "cost": "", "compensation": f.get("stat_compensation") or ""})
    return out


def _grid_power(src: dict) -> dict | None:
    """How a grid source's power reads, as {"plus": sensor, "minus": sensor}: buying is plus minus minus.

    Home Assistant takes one sensor positive when buying (`stat_rate`), one
    the other way round (`stat_rate_inverted`), or one for each direction
    (`stat_rate_from`, `stat_rate_to`)."""
    cfg = src.get("power_config") or {}
    if cfg.get("stat_rate"):
        return {"plus": cfg["stat_rate"], "minus": ""}
    if cfg.get("stat_rate_inverted"):
        return {"plus": "", "minus": cfg["stat_rate_inverted"]}
    if cfg.get("stat_rate_from") or cfg.get("stat_rate_to"):
        return {"plus": cfg.get("stat_rate_from") or "", "minus": cfg.get("stat_rate_to") or ""}
    if src.get("stat_rate"):
        return {"plus": src["stat_rate"], "minus": ""}
    return None


def summarise(prefs: dict | None, info: dict | None = None) -> dict:
    """The dashboard's sensors, by what they're for. What the editor's presets and the widgets read."""
    prefs, info = prefs or {}, info or {}
    cost_sensors = info.get("cost_sensors") or {}
    solar, grid = [], []
    for src in prefs.get("energy_sources") or []:
        if not isinstance(src, dict):
            continue
        if src.get("type") == "solar" and src.get("stat_energy_from"):
            solar.append({"energy": src["stat_energy_from"], "power": src.get("stat_rate") or ""})
        elif src.get("type") == "grid":
            flows = _grid_parts(src)
            for f in flows:                   # a price set without a cost statistic: the one Home Assistant keeps
                if f["import"] and not f["cost"]:
                    f["cost"] = cost_sensors.get(f["import"], "")
                if f["export"] and not f["compensation"]:
                    f["compensation"] = cost_sensors.get(f["export"], "")
            grid.append({"flows": flows, "power": _grid_power(src)})
    has_cost = any(f["cost"] or f["compensation"] for g in grid for f in g["flows"])
    return {"solar": solar, "grid": grid, "has_cost": has_cost}


def stats_for(summary: dict, source: str) -> list[str]:
    """The statistics a source adds up."""
    if source == "solar":
        return [s["energy"] for s in summary.get("solar") or []]
    key = {"grid_import": "import", "grid_export": "export"}.get(source)
    if key:
        return [f[key] for g in summary.get("grid") or [] for f in g["flows"] if f[key]]
    return []


OFFLINE_PREFS = {"energy_sources": [
    {"type": "solar", "stat_energy_from": "sensor.solar_energy", "stat_rate": "sensor.solar_power"},
    {"type": "grid", "stat_energy_from": "sensor.grid_import_energy", "stat_energy_to": "sensor.grid_export_energy",
     "entity_energy_price": "input_number.price", "power_config": {"stat_rate": "sensor.grid_power"}},
]}
OFFLINE_INFO = {"cost_sensors": {"sensor.grid_import_energy": "sensor.grid_import_energy_cost",
                                 "sensor.grid_export_energy": "sensor.grid_export_energy_compensation"}}


@runtime.live(600)
async def fetch_dashboard(session):
    """summarise() of Home Assistant's Energy dashboard, plus its currency."""
    if not HA_TOKEN:
        return {**summarise(OFFLINE_PREFS, OFFLINE_INFO), "currency": "EUR"}
    try:
        prefs = await runtime.HASS.ws({"type": "energy/get_prefs"})
    except Exception as exc:
        if getattr(exc, "code", "") != "not_found":     # not set up yet: an empty dashboard, not a failure
            health.fail(SERVICE, exc)
            raise
        prefs = {}
    info = await runtime.HASS.ws({"type": "energy/info"}) if prefs else {}
    cfg = await ha_json(session, "/config")
    health.ok(SERVICE)
    return {**summarise(prefs, info), "currency": str((cfg or {}).get("currency") or "")}


async def dashboard(session) -> dict:
    """The dashboard, for a background fetch: the last one read, or read now if there's none yet."""
    with live_data.waiting_for_fresh():
        return await fetch_dashboard(session) or {}


# ------------------------------------------------------------------ long-term statistics

def period_start(period: str, now: datetime) -> datetime:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return midnight.replace(month=1, day=1)
    if period == "month":
        return midnight.replace(day=1)
    return midnight


def slots(period: str, now: datetime) -> int:
    """How many bars the whole period has."""
    if period == "year":
        return 12
    if period == "month":
        return calendar.monthrange(now.year, now.month)[1]
    return 24


def _slot(period: str, start: datetime) -> int:
    return {"year": start.month - 1, "month": start.day - 1}.get(period, start.hour)


def _row_start(row: dict, tz) -> datetime | None:
    raw = row.get("start")
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000 if raw > 1e11 else raw, tz)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(tz)
    except (TypeError, ValueError, OSError):
        return None


def buckets(rows_by_stat: dict, period: str, now: datetime, field: str = "change") -> list[float | None]:
    """Each statistic's rows added up into the period's bars; None for a bar still to come."""
    n = slots(period, now)
    out: list[float | None] = [0.0] * n
    for rows in (rows_by_stat or {}).values():
        for row in rows or []:
            start = _row_start(row, now.tzinfo)
            if start is None or row.get(field) is None:
                continue
            k = _slot(period, start)
            if 0 <= k < n:
                out[k] += float(row[field])
    current = _slot(period, now)
    return [v if k <= current else None for k, v in enumerate(out)]


async def statistics(stat_ids: list[str], period: str, now: datetime, types=("change",), units=None) -> dict:
    """recorder/statistics_during_period for the period so far, one row per bar."""
    if not stat_ids:
        return {}
    req = {"type": "recorder/statistics_during_period", "start_time": period_start(period, now).isoformat(),
           "statistic_ids": list(stat_ids), "period": BUCKET[period], "types": list(types)}
    if units:
        req["units"] = units
    try:
        return await runtime.HASS.ws(req, timeout=15) or {}
    except Exception as exc:
        health.fail(SERVICE, exc)
        raise


async def _now(session) -> datetime:
    tz = await get_home_timezone(session)
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.now().astimezone()


def _offline_bars(period: str, now: datetime, scale: float, signed: bool = False) -> list[float | None]:
    import math
    n, cur = slots(period, now), _slot(period, now)
    out = []
    for k in range(n):
        if k > cur:
            out.append(None)
        elif period == "day":
            sun = max(0.0, math.sin(math.pi * (k - 6) / 13)) if 6 <= k <= 19 else 0.0
            out.append(round((0.4 - sun * 1.6 if signed else sun) * scale, 2))
        else:
            out.append(round(scale * (0.55 + 0.45 * abs(math.sin(k * 1.7))), 2))
    return out


@runtime.live(300)
async def fetch_total(session, source="solar", entity="", period="month"):
    """{"total", "bars", "unit"}: a source's energy over the period so far (kWh), with a bar per hour, day or month."""
    period = period if period in PERIODS else "month"
    now = await _now(session)
    if not HA_TOKEN:
        bars = _offline_bars(period, now, {"day": 1.2, "month": 9.0, "year": 260.0}[period])
        return {"total": round(sum(b for b in bars if b), 1), "bars": bars, "unit": "kWh"}
    if source == "entity":
        ids = [entity] if valid_entity_id(str(entity or "")) else []
    else:
        ids = stats_for(await dashboard(session), source)
    if not ids:
        return {"total": None, "bars": [], "unit": "kWh", "missing": source}
    rows = await statistics(ids, period, now, units={"energy": "kWh"})
    health.ok(SERVICE)
    bars = buckets(rows, period, now)
    return {"total": round(sum(b for b in bars if b), 2), "bars": bars, "unit": "kWh"}


# ------------------------------------------------------------------ grid now

def _watts(state: dict | None) -> float | None:
    try:
        v = float((state or {}).get("state"))
    except (TypeError, ValueError):
        return None
    unit = str(((state or {}).get("attributes") or {}).get("unit_of_measurement") or "W")
    return v * {"kW": 1000.0, "MW": 1e6, "mW": 0.001}.get(unit, 1.0)


async def _state(session, eid: str) -> dict | None:
    if not valid_entity_id(eid):
        return None
    try:
        return await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
    except Exception:
        return None


async def net_power(session, powers: list[dict]) -> float | None:
    """Watts bought from the grid right now (negative: sold), over every source that says; None if none does."""
    total, said = 0.0, False
    for p in powers:
        for key, sign in (("plus", 1), ("minus", -1)):
            if p.get(key):
                w = _watts(await _state(session, p[key]))
                if w is not None:
                    total += sign * w
                    said = True
    return total if said else None


@runtime.live(15)
async def fetch_grid_power(session, entity="", invert=False):
    """{"watts"}: what the grid gives right now (negative: you're selling), from the Energy
    dashboard's grid power, or one power sensor. None when there's no power sensor."""
    if not HA_TOKEN:
        return {"watts": -1830.0}
    if entity:
        w = _watts(await _state(session, entity))
        return {"watts": None if w is None else (-w if invert else w)}
    dash = await dashboard(session)
    return {"watts": await net_power(session, [g["power"] for g in dash.get("grid") or [] if g.get("power")])}


@runtime.live(300)
async def fetch_grid_hours(session, entity="", invert=False):
    """{"bars", "today", "unit"}: each hour today, bought minus sold. From the Energy dashboard's
    grid energy (kWh, and today's net), or one power sensor's hourly average (kW)."""
    now = await _now(session)
    if not HA_TOKEN:
        bars = _offline_bars("day", now, 1.0, signed=True)
        return {"bars": bars, "today": round(sum(b for b in bars if b), 2), "unit": "kWh"}
    if entity:
        rows = await statistics([entity], "day", now, types=("mean",), units={"power": "kW"})
        bars = [None if b is None else (-b if invert else b) for b in buckets(rows, "day", now, field="mean")]
        return {"bars": bars, "today": None, "unit": "kW"}
    dash = await dashboard(session)
    imports, exports = stats_for(dash, "grid_import"), stats_for(dash, "grid_export")
    if not imports and not exports:
        return {"bars": [], "today": None, "unit": "kWh", "missing": "grid"}
    got = await statistics(imports + exports, "day", now, units={"energy": "kWh"})
    bought = buckets({k: v for k, v in got.items() if k in imports}, "day", now)
    sold = buckets({k: v for k, v in got.items() if k in exports}, "day", now)
    bars = [None if b is None else round(b - (s or 0.0), 3) for b, s in zip(bought, sold)]
    health.ok(SERVICE)
    return {"bars": bars, "today": round(sum(b for b in bars if b), 2), "unit": "kWh"}


# ------------------------------------------------------------------ costs

@runtime.live(300)
async def fetch_cost(session):
    """{"today", "month", "currency", "sells"}: earned minus spent on electricity, from the
    Energy dashboard's cost statistics, in Home Assistant's currency."""
    now = await _now(session)
    if not HA_TOKEN:
        return {"today": 4.2, "month": 38.9, "currency": "EUR", "sells": True}
    dash = await dashboard(session)
    flows = [f for g in dash.get("grid") or [] for f in g["flows"]]
    costs = [f["cost"] for f in flows if f["cost"]]
    comps = [f["compensation"] for f in flows if f["compensation"]]
    if not costs and not comps:
        return {"today": None, "month": None, "currency": dash.get("currency") or "", "missing": "prices"}
    got = await statistics(costs + comps, "month", now)
    spent = buckets({k: v for k, v in got.items() if k in costs}, "month", now)
    earned = buckets({k: v for k, v in got.items() if k in comps}, "month", now)
    net = [None if s is None else (e or 0.0) - s for s, e in zip(spent, earned)]
    health.ok(SERVICE)
    return {"today": round(net[now.day - 1] or 0.0, 2), "month": round(sum(v for v in net if v), 2),
            "currency": dash.get("currency") or "", "sells": bool(comps)}
