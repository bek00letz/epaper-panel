"""Home's location and timezone, from Home Assistant, plus distance and bearing maths."""

import math
import time

import runtime
from config import HA_TOKEN
from ha import ha_json


# No built-in fallback location or timezone: a default would be someone's real
# home, and wrong for everyone else. Home Assistant's own settings are the source.
_home_location_cache = {"at": 0.0, "lat": None, "lon": None}
_ha_config_cache = {"at": 0.0, "tz": None}


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def _bearing_calc(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    cardinals = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    idx = int((deg + 22.5) // 45)
    return deg, cardinals[idx]


def _bearing_cardinal(lat1, lon1, lat2, lon2):
    return _bearing_calc(lat1, lon1, lat2, lon2)[1]


async def get_home_timezone(session, default="UTC"):
    now = time.time()
    if now - _ha_config_cache["at"] < 3600 and _ha_config_cache.get("tz"):
        return _ha_config_cache["tz"]
    if HA_TOKEN:
        try:
            cfg = await ha_json(session, "/config")
            tz = cfg.get("time_zone")
            if tz:
                _ha_config_cache["at"] = now
                _ha_config_cache["tz"] = tz
                if "latitude" in cfg and "longitude" in cfg:
                    _home_location_cache["at"] = now
                    _home_location_cache["lat"] = float(cfg["latitude"])
                    _home_location_cache["lon"] = float(cfg["longitude"])
                return tz
        except Exception:
            pass
    return _ha_config_cache.get("tz") or default


async def get_home_coordinates(session):
    now = time.time()
    if now - _home_location_cache["at"] < 3600 and _home_location_cache["lat"] is not None:
        return _home_location_cache["lat"], _home_location_cache["lon"]
    if HA_TOKEN:
        try:
            cfg = await ha_json(session, "/config")
            if "latitude" in cfg and "longitude" in cfg:
                lat = float(cfg["latitude"])
                lon = float(cfg["longitude"])
                _home_location_cache["at"] = now
                _home_location_cache["lat"] = lat
                _home_location_cache["lon"] = lon
                if "time_zone" in cfg:
                    _ha_config_cache["at"] = now
                    _ha_config_cache["tz"] = cfg["time_zone"]
                return lat, lon
        except Exception:
            pass
        try:
            zone_state = await ha_json(session, "/states/zone.home")
            attrs = zone_state.get("attributes", {})
            lat = float(attrs.get("latitude"))
            lon = float(attrs.get("longitude"))
            _home_location_cache["at"] = now
            _home_location_cache["lat"] = lat
            _home_location_cache["lon"] = lon
            return lat, lon
        except Exception:
            pass
    return _home_location_cache["lat"], _home_location_cache["lon"]
