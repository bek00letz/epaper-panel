"""Aircraft overhead (Flightradar24, falling back to OpenSky)."""

import math
import time
import aiohttp

import runtime
import services
from sources.geo import _bearing_calc, _haversine_km, get_home_coordinates


_aircraft_cache = {}
# How old a list may be and still be shown when both services are down. A
# plane crosses a 35 km circle in a few minutes; an older list is fiction.
MAX_AGE = 300.0
_warned_no_location = False


def _first_number(el: dict, *keys):
    for k in keys:
        v = el.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def place_of(el: dict) -> tuple[float | None, float | None, float, str]:
    """A flight widget's place: (lat, lon, radius_km, label). lat/lon None means Home.

    0 is a real coordinate (the equator, Greenwich), so only a missing or
    empty value falls back to Home.
    """
    lat = _first_number(el, "lat", "latitude")
    lon = _first_number(el, "lon", "lng", "longitude")
    if lat is None or lon is None:
        lat = lon = None
    try:
        radius = float(el.get("radius") or 35.0)
    except (TypeError, ValueError):
        radius = 35.0
    return lat, lon, radius, str(el.get("location_name") or "").strip()


def plane_near(lat: float, lon: float, radius_km: float, p: dict) -> dict | None:
    """A plane in the add-on's own fields (shapes.py "flights": callsign, latitude, longitude,
    altitude_m, speed_kmh, track_deg, from, to, aircraft...) as a Flights page draws it, measured from
    `lat, lon`; None when it's further than `radius_km`. The same for every feed and for yours."""
    dist = _haversine_km(lat, lon, p["latitude"], p["longitude"])
    if dist > radius_km:
        return None
    b_deg, cardinal = _bearing_calc(lat, lon, p["latitude"], p["longitude"])
    origin, dest = p.get("from") or "", p.get("to") or ""
    route = f"{origin} → {dest}" if (origin and dest) else (origin or dest or "")
    desc = " · ".join(x for x in (route, p.get("aircraft") or "", p.get("airline") or "") if x) or "Commercial Flight"
    return {
        "icao24": p.get("icao24") or "",
        "callsign": p.get("callsign") or "",
        "country": p.get("country") or desc,
        "latitude": p["latitude"],
        "longitude": p["longitude"],
        "altitude_m": round(float(p.get("altitude_m") or 0.0), 1),
        "velocity_ms": round(float(p.get("speed_kmh") or 0.0) / 3.6, 1),
        "track_deg": float(p.get("track_deg") or 0.0),
        "vertical_rate": round(float(p.get("vertical_rate") or 0.0), 2),
        "distance_km": round(dist, 1),
        "bearing_deg": round(b_deg, 1),
        "bearing_cardinal": cardinal,
        "origin": origin,
        "destination": dest,
        "model": p.get("aircraft") or "",
    }


@runtime.live(30, stale_after=MAX_AGE)
async def fetch_overhead_aircraft(session, radius_km=35.0, lat=None, lon=None, own=""):
    """The planes within `radius_km`, nearest first. `own`: the id of your data source that gives
    planes in the add-on's own fields, in place of Flightradar24 and OpenSky."""
    global _warned_no_location
    if lat is not None and lon is not None:
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            lat, lon = await get_home_coordinates(session)
    else:
        lat, lon = await get_home_coordinates(session)
    if lat is None or lon is None:
        if not _warned_no_location:
            _warned_no_location = True
            print("flights: Home Assistant has no home location. Set it under Settings → System → General, "
                  "or give the flight widget its own coordinates", flush=True)
        return []

    radius_km = max(5.0, min(250.0, float(radius_km or 35.0)))
    if own:
        import shapes
        planes = await shapes.read_own(session, own, "flights")
        if planes is None:
            raise LookupError("your flight source hasn't answered")
        return sorted((a for a in (plane_near(lat, lon, radius_km, p) for p in planes) if a), key=lambda a: a["distance_km"])
    cache_key = (round(lat, 3), round(lon, 3), int(radius_km))
    now = time.time()
    cached = _aircraft_cache.get(cache_key)
    if cached and (now - cached["at"] < 30.0) and cached.get("items") is not None:
        return cached["items"]

    d_lat = radius_km / 111.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    d_lon = radius_km / (111.0 * cos_lat)

    # 1. Primary: Flightradar24 high-speed live feed (rate-limit free, global coverage)
    fr24_url = (
        f"{services.url('flightradar24')}"
        f"?bounds={lat + d_lat:.3f},{lat - d_lat:.3f},{lon - d_lon:.3f},{lon + d_lon:.3f}"
        f"&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1&maxage=14400&gliders=0&stats=0"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    timeout = aiohttp.ClientTimeout(total=6)
    try:
        async with session.get(fr24_url, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                aircraft = []
                for k, v in data.items():
                    if k in ("full_count", "version", "stats") or not isinstance(v, list) or len(v) < 14:
                        continue
                    a_lat, a_lon = v[1], v[2]
                    if a_lat is None or a_lon is None:
                        continue
                    # On ground flag (v[14] == 1)
                    if len(v) > 14 and v[14] == 1:
                        continue
                    near = plane_near(lat, lon, radius_km, {
                        "icao24": str(v[0]).upper(), "callsign": str(v[16] or v[13] or v[0]).strip().upper(),
                        "latitude": a_lat, "longitude": a_lon,
                        "altitude_m": (float(v[4]) if v[4] is not None else 0.0) * 0.3048,
                        "speed_kmh": (float(v[5]) if v[5] is not None else 0.0) * 1.852,
                        "track_deg": float(v[3]) if v[3] is not None else 0.0,
                        "vertical_rate": (float(v[15]) if len(v) > 15 and v[15] is not None else 0.0) * 0.00508,
                        "from": str(v[11] or "").strip(), "to": str(v[12] or "").strip(),
                        "aircraft": str(v[8] or "").strip(), "airline": str(v[18] or "").strip()})
                    if near is not None:
                        aircraft.append(near)
                aircraft.sort(key=lambda a: a["distance_km"])
                _aircraft_cache[cache_key] = {"at": now, "items": aircraft}
                runtime.prune(_aircraft_cache)
                return aircraft
    except Exception as exc:
        pass                                              # health.py has recorded it

    # 2. Fallback: OpenSky Network
    opensky_url = (
        f"{services.url('opensky')}"
        f"?lamin={lat - d_lat:.4f}&lamax={lat + d_lat:.4f}"
        f"&lomin={lon - d_lon:.4f}&lomax={lon + d_lon:.4f}"
    )
    try:
        async with session.get(opensky_url, headers={"User-Agent": "Crowpanel-Epaper/0.8.21"}, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                raw_states = data.get("states") or []
                aircraft = []
                for s in raw_states:
                    if not s or len(s) < 12 or s[8] is True:
                        continue
                    a_lon, a_lat = s[5], s[6]
                    if a_lon is None or a_lat is None:
                        continue
                    near = plane_near(lat, lon, radius_km, {
                        "icao24": str(s[0]).upper(), "callsign": str(s[1]).strip() if s[1] else str(s[0]).upper(),
                        "country": str(s[2] or "Commercial"), "latitude": a_lat, "longitude": a_lon,
                        "altitude_m": float(s[7]) if s[7] is not None else 0.0,
                        "speed_kmh": (float(s[9]) if s[9] is not None else 0.0) * 3.6,
                        "track_deg": float(s[10]) if s[10] is not None else 0.0,
                        "vertical_rate": float(s[11]) if s[11] is not None else 0.0})
                    if near is not None:
                        aircraft.append(near)
                aircraft.sort(key=lambda a: a["distance_km"])
                _aircraft_cache[cache_key] = {"at": now, "items": aircraft}
                runtime.prune(_aircraft_cache)
                return aircraft
    except Exception as exc:
        pass

    # Both are down. live_data keeps the last good list for MAX_AGE, then the
    # widget says it has no data rather than showing planes long gone.
    raise LookupError("no aircraft service answered")


# ---------------------------------------------------------------- following one flight

# Flightradar24's feed finds a flight by its number (W43186) or its callsign (WMT4ZZ) anywhere in
# the world, and says both, with its route: no second service is needed to turn one into the other.
# A flight not in the air is looked for every few minutes, not every minute; after a failure, longer
# and longer waits (pacing.py). Nobody's page follows it any more: live_data stops asking.
import re as _re

import pacing

FOLLOW_EVERY = 60
QUIET = 180                         # a flight that isn't in the air: looked for every 3 minutes
REMEMBER = 6 * 3600                 # how long a flight seen in the air is remembered after it's gone
LANDED_KM = 40                      # gone this near its destination, this low: it has landed
LANDED_M = 1500
PACE_FR24 = pacing.Pace("Flightradar24", first=FOLLOW_EVERY, most=1800)
_IDENT = _re.compile(r"^[A-Z0-9]{3,8}$")
_seen: dict[str, dict] = {}         # flight -> {"plane", "at", "absent_at", "result"}


def ident_of(raw) -> str:
    """A flight as typed ("W4 3186", "baw17r") -> "W43186", "BAW17R"; "" when it can't be one."""
    s = _re.sub(r"[\s\-]", "", str(raw or "")).upper()
    return s if _IDENT.match(s) and any(c.isdigit() for c in s) else ""


def asks_by(ident: str) -> str:
    """Callsigns start with their airline's three letters (BAW17R); flight numbers with two
    characters, a digit among them or not, then digits (BA117, W43186)."""
    return "callsign" if ident[:3].isalpha() else "flight"


def read_follow(body, ident: str) -> dict | None:
    """The plane in Flightradar24's answer whose flight number or callsign is `ident`, in the
    add-on's own fields; None when it isn't there. Raises ValueError for another form of answer."""
    if not isinstance(body, dict) or not ({"full_count", "version"} & set(body)):
        raise ValueError("not a flight feed")
    for k, v in body.items():
        if not isinstance(v, list) or len(v) < 17:
            continue
        flight, callsign = str(v[13] or "").strip().upper(), str(v[16] or "").strip().upper()
        if ident not in (flight, callsign) or v[1] is None or v[2] is None:
            continue
        return {"flight": flight, "callsign": callsign, "from": str(v[11] or "").strip().upper(),
                "to": str(v[12] or "").strip().upper(), "latitude": float(v[1]), "longitude": float(v[2]),
                "altitude_m": round(float(v[4] or 0) * 0.3048), "speed_kmh": round(float(v[5] or 0) * 1.852),
                "track_deg": float(v[3] or 0), "vertical_ms": round(float(v[15] or 0) * 0.00508, 1),
                "on_ground": v[14] == 1, "aircraft": str(v[8] or "").strip(), "at": float(v[10] or 0) or None}
    return None


def _place(code: str) -> dict | None:
    import airports
    return airports.lookup(code) if code else None


def describe(ident: str, plane: dict | None, seen: dict | None, now: float) -> dict:
    """Where the flight is, as a page shows it: status "air" (with its route, height, speed, how far
    to go and when it arrives, when known), "landed", "lost" (gone mid-flight: last seen) or
    "waiting" (not in the air: before it, or long after)."""
    out = {"ident": ident, "status": "waiting", "flight": ident, "callsign": "", "from": "", "to": "",
           "from_city": "", "to_city": "", "seen_at": None}
    last = (seen or {}).get("plane")
    if plane is None and last and now - (seen or {}).get("at", 0) <= REMEMBER:
        dest = _place(last.get("to"))
        near = dest and _haversine_km(last["latitude"], last["longitude"], dest["lat"], dest["lon"]) <= LANDED_KM
        status = "landed" if near and last["altitude_m"] <= LANDED_M else "lost"
        plane, out["status"] = last, status
    elif plane is not None:
        if plane["on_ground"]:
            out["status"] = "landed" if last and not last.get("on_ground") else "waiting"
        else:
            out["status"] = "air"
    if plane is None:
        return out
    a, b = _place(plane["from"]), _place(plane["to"])
    out.update(flight=plane["flight"] or ident, callsign=plane["callsign"], **{"from": plane["from"], "to": plane["to"]},
               from_city=(a or {}).get("city", ""), to_city=(b or {}).get("city", ""), seen_at=plane.get("at") or now,
               latitude=plane["latitude"], longitude=plane["longitude"], altitude_m=plane["altitude_m"],
               speed_kmh=plane["speed_kmh"], vertical_ms=plane["vertical_ms"], aircraft=plane["aircraft"])
    if out["status"] == "air" and b:
        left = _haversine_km(plane["latitude"], plane["longitude"], b["lat"], b["lon"])
        out["left_km"] = round(left)
        if a:
            out["total_km"] = round(_haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]))
        if plane["speed_kmh"] >= 150:
            out["arrives"] = (plane.get("at") or now) + left / plane["speed_kmh"] * 3600
    return out


def forget_follow() -> None:
    """Try again: look at once."""
    PACE_FR24.forget()
    for s in _seen.values():
        s.pop("absent_at", None)


@runtime.live(FOLLOW_EVERY)
async def fetch_followed(session, ident: str):
    """One flight, as describe() says it. Asked every minute while it's in the air, every few
    minutes while it isn't."""
    ident = ident_of(ident)
    if not ident:
        return None
    now = time.time()
    seen = _seen.get(ident)
    if seen and seen.get("absent_at") and now - seen["absent_at"] < QUIET and seen.get("result"):
        return seen["result"]
    url = (f"{services.url('flightradar24')}?{asks_by(ident)}={ident}"
           "&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=1&air=1&vehicles=0&estimated=1&maxage=14400&gliders=0&stats=0")
    body = await pacing.get(session, url, PACE_FR24, timeout=10)
    try:
        plane = read_follow(body, ident)
    except ValueError:
        pacing.unreadable(PACE_FR24, "flight feed")
        raise LookupError("not a flight feed") from None
    pacing.answered(PACE_FR24)
    result = describe(ident, plane, seen, now)
    entry = _seen.setdefault(ident, {})
    if plane is not None and not plane["on_ground"]:
        entry.update(plane=plane, at=now)
    entry["absent_at"] = None if result["status"] == "air" else now
    entry["result"] = result
    for k in [k for k, v in _seen.items() if now - (v.get("at") or v.get("absent_at") or now) > 2 * REMEMBER]:
        del _seen[k]
    return result
