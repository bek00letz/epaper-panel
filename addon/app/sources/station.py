"""Weather from your own station: "now" from where you choose, the forecast from a forecast service.

The Weather widget's forecast (highs, lows, the days' icons) always comes
from a weather entity that forecasts (met.no comes with Home Assistant).
What it says about *now* can come from somewhere closer:

- `now_entity`: another weather entity, such as a station's own (a Weather
  Underground station has one), for temperature, humidity, wind and its
  condition;
- single sensors, each optional: temperature, humidity, wind, rain (a rate
  or a rain sensor that's on while it rains), pressure, solar radiation.

The big icon follows what can be known at the house: rain falling now beats
everything; then, only if you chose a solar radiation sensor (a station
under trees reads low in full sun, so it's never assumed), sunny or cloudy
from how much sun reaches it compared with a clear sky at this sun height;
then the station's own condition; then the forecast's. A barometer can't
see the sky, so pressure gives only where it's heading: rising, falling or
steady over three hours.
"""
from __future__ import annotations

import math
import urllib.parse
from datetime import datetime, timedelta, timezone

import runtime
from config import HA_TOKEN, valid_entity_id
from ha import ha_json

SENSORS = ("temperature_sensor", "humidity_sensor", "wind_sensor", "rain_sensor", "pressure_sensor", "solar_sensor")
TREND_HOURS = 3
TREND_HPA = 1.0              # less than this over three hours is steady
POURING_MM_H = 7.6           # heavy rain, by the usual definition
# A barometer's units, as hectopascals.
TO_HPA = {"hpa": 1.0, "mbar": 1.0, "mb": 1.0, "kpa": 10.0, "pa": 0.01, "inhg": 33.8639, "mmhg": 1.33322, "psi": 68.9476}
RAIN_TOTAL = ("This sensor counts rain over a day or longer, so it can't say whether it's raining now. "
              "Choose one that measures rain per hour (mm/h or in/h), or a sensor that's on while it rains.")
SKY_MIN_ELEVATION = 10.0     # below this the clear-sky estimate is too rough to judge by


def wanted(el: dict) -> dict:
    """What a weather element takes from a station: {"now_entity", "<kind>_sensor"...}, only those set."""
    out = {}
    for key in ("now_entity",) + SENSORS:
        eid = str(el.get(key) or "").strip()
        if valid_entity_id(eid):
            out[key] = eid
    return out


def _number(state: dict | None) -> float | None:
    try:
        return float((state or {}).get("state"))
    except (TypeError, ValueError):
        return None


def _unit(state: dict | None) -> str:
    return str(((state or {}).get("attributes") or {}).get("unit_of_measurement") or "")


def clear_sky(elevation_deg: float) -> float:
    """Sunlight on flat ground under a clear sky (W/m²) at this sun height (Haurwitz's model)."""
    if elevation_deg <= 0:
        return 0.0
    cos_z = math.sin(math.radians(elevation_deg))
    return 1098.0 * cos_z * math.exp(-0.057 / cos_z)


def sky(radiation: float | None, elevation: float | None) -> str | None:
    """"sunny", "partlycloudy" or "cloudy" from measured sunlight, or None when it can't tell."""
    if radiation is None or elevation is None or elevation < SKY_MIN_ELEVATION:
        return None
    share = radiation / max(1.0, clear_sky(elevation))
    if share >= 0.7:
        return "sunny"
    return "partlycloudy" if share >= 0.35 else "cloudy"


def is_rate(unit: str) -> bool:
    """A rain unit per hour ("mm/h", "in/h", "mm/hr")."""
    return str(unit or "").strip().lower().replace(" ", "").endswith(("/h", "/hr"))


def rain_problem(entity_id: str, unit: str) -> str:
    """Why a sensor can't say whether it's raining now ("" when it can): a rate per hour, or on/off, can."""
    if str(entity_id or "").startswith("binary_sensor.") or is_rate(unit):
        return ""
    return RAIN_TOTAL


def raining(state: dict | None, entity_id: str = "") -> str | None:
    """"pouring" or "rainy" while a rain sensor says it rains now: a rate above 0, or on. A total
    ("rain today") never counts: after one shower it would say rain all day."""
    if not state:
        return None
    if entity_id.startswith("binary_sensor.") or str(state.get("state")).lower() in ("on", "off"):
        return "rainy" if str(state.get("state")).lower() == "on" else None
    if not is_rate(_unit(state)):
        return None
    rate = _number(state)
    if rate is None or rate <= 0:
        return None
    per_hour = rate * 25.4 if _unit(state).strip().lower().startswith("in") else rate
    return "pouring" if per_hour >= POURING_MM_H else "rainy"


def hpa(value: float, unit: str) -> float | None:
    """A pressure in hectopascals, by its unit; None for a unit that isn't a pressure."""
    factor = TO_HPA.get(str(unit or "").strip().lower().replace(" ", ""))
    return None if factor is None else value * factor


def trend(rows: list[dict], now: datetime, unit: str = "hPa") -> str | None:
    """"rising", "falling" or "steady" from a pressure sensor's last three hours, in its own unit."""
    pts = []
    for r in rows or []:
        try:
            pts.append((datetime.fromisoformat(str(r["last_changed"]).replace("Z", "+00:00")), float(r["state"])))
        except (KeyError, TypeError, ValueError):
            continue
    if len(pts) < 2 or (now - pts[0][0]) < timedelta(hours=TREND_HOURS * 0.6):
        return None                      # not enough history to say
    delta = hpa(pts[-1][1] - pts[0][1], unit)
    if delta is None:
        return None
    if abs(delta) < TREND_HPA:
        return "steady"
    return "rising" if delta > 0 else "falling"


async def _state(session, eid: str) -> dict | None:
    try:
        return await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
    except Exception:
        return None


@runtime.live(60)
async def fetch_station(session, **sources):
    """What the station says now: {"temperature", "unit", "humidity", "wind_speed", "wind_unit",
    "condition", "pressure_trend"}, each only when it has a value. `sources`: wanted()."""
    if not HA_TOKEN:
        return {}
    out: dict = {}
    now_ent = sources.get("now_entity")
    if now_ent:
        st = await _state(session, now_ent)
        a = (st or {}).get("attributes") or {}
        for key, attr in (("temperature", "temperature"), ("unit", "temperature_unit"), ("humidity", "humidity"),
                          ("wind_speed", "wind_speed"), ("wind_unit", "wind_speed_unit")):
            if a.get(attr) is not None:
                out[key] = a[attr]
        if st and st.get("state") not in (None, "unknown", "unavailable"):
            out["condition"] = st["state"]
    for key, sensor, unit_key in (("temperature", "temperature_sensor", "unit"), ("humidity", "humidity_sensor", None),
                                  ("wind_speed", "wind_sensor", "wind_unit")):
        if sources.get(sensor):
            st = await _state(session, sources[sensor])
            v = _number(st)
            if v is not None:
                out[key] = round(v, 1) if key != "humidity" else round(v)
                if unit_key and _unit(st):
                    out[unit_key] = _unit(st)
    if sources.get("solar_sensor"):
        sun = await _state(session, "sun.sun")
        elevation = ((sun or {}).get("attributes") or {}).get("elevation")
        seen = sky(_number(await _state(session, sources["solar_sensor"])), elevation if isinstance(elevation, (int, float)) else None)
        if seen:
            out["condition"] = seen
    if sources.get("rain_sensor"):
        wet = raining(await _state(session, sources["rain_sensor"]), sources["rain_sensor"])
        if wet:
            out["condition"] = wet
    if sources.get("pressure_sensor"):
        now = datetime.now(timezone.utc)
        start = urllib.parse.quote((now - timedelta(hours=TREND_HOURS)).isoformat(), safe=":+")
        eid = urllib.parse.quote(sources["pressure_sensor"], safe=".")
        try:
            unit = _unit(await _state(session, sources["pressure_sensor"]))      # history comes without it
            rows = await ha_json(session, f"/history/period/{start}?filter_entity_id={eid}&minimal_response&no_attributes")
            got = trend(rows[0] if rows else [], now, unit or "hPa")
            if got:
                out["pressure_trend"] = got
        except Exception:
            pass
    return out


def merge(forecast: dict | None, station: dict | None) -> dict | None:
    """The forecast's data with the station's "now" over it. The forecast's days are never touched."""
    if not station:
        return forecast
    return {**(forecast or {}), **station}
