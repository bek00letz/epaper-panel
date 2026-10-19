"""Aircraft overhead (Flightradar24, falling back to OpenSky)."""

import math
import time
import aiohttp

import runtime
from sources.geo import _bearing_calc, _haversine_km, get_home_coordinates


_aircraft_cache = {}
_warned_no_location = False


@runtime.live(30)
async def fetch_overhead_aircraft(session, radius_km=35.0, lat=None, lon=None):
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
        f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
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
                    dist = _haversine_km(lat, lon, a_lat, a_lon)
                    if dist > radius_km:
                        continue
                    b_deg, cardinal = _bearing_calc(lat, lon, a_lat, a_lon)
                    cs = str(v[16] or v[13] or v[0]).strip().upper()
                    origin = str(v[11] or "").strip()
                    dest = str(v[12] or "").strip()
                    ac_type = str(v[8] or "").strip()
                    airline = str(v[18] or "").strip()
                    route = f"{origin} → {dest}" if (origin and dest) else (origin or dest or "")
                    desc_parts = [p for p in (route, ac_type, airline) if p]
                    desc = " · ".join(desc_parts) if desc_parts else "Commercial Flight"

                    alt_ft = float(v[4]) if v[4] is not None else 0.0
                    alt_m = alt_ft * 0.3048
                    spd_kts = float(v[5]) if v[5] is not None else 0.0
                    spd_ms = spd_kts * 0.514444
                    v_rate_fpm = float(v[15]) if len(v) > 15 and v[15] is not None else 0.0
                    v_rate_ms = v_rate_fpm * 0.00508

                    aircraft.append({
                        "icao24": str(v[0]).upper(),
                        "callsign": cs,
                        "country": desc,
                        "latitude": a_lat,
                        "longitude": a_lon,
                        "altitude_m": round(alt_m, 1),
                        "velocity_ms": round(spd_ms, 1),
                        "track_deg": float(v[3]) if v[3] is not None else 0.0,
                        "vertical_rate": round(v_rate_ms, 2),
                        "distance_km": round(dist, 1),
                        "bearing_deg": round(b_deg, 1),
                        "bearing_cardinal": cardinal,
                        "origin": origin,
                        "destination": dest,
                        "model": ac_type
                    })
                aircraft.sort(key=lambda a: a["distance_km"])
                _aircraft_cache[cache_key] = {"at": now, "items": aircraft}
                return aircraft
    except Exception as exc:
        print(f"FR24 fetch error: {exc!r}", flush=True)

    # 2. Fallback: OpenSky Network
    opensky_url = (
        f"https://opensky-network.org/api/states/all"
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
                    dist = _haversine_km(lat, lon, a_lat, a_lon)
                    if dist > radius_km:
                        continue
                    b_deg, cardinal = _bearing_calc(lat, lon, a_lat, a_lon)
                    cs = str(s[1]).strip() if s[1] else str(s[0]).upper()
                    aircraft.append({
                        "icao24": str(s[0]).upper(),
                        "callsign": cs,
                        "country": str(s[2] or "Commercial"),
                        "latitude": a_lat,
                        "longitude": a_lon,
                        "altitude_m": float(s[7]) if s[7] is not None else 0.0,
                        "velocity_ms": float(s[9]) if s[9] is not None else 0.0,
                        "track_deg": float(s[10]) if s[10] is not None else 0.0,
                        "vertical_rate": float(s[11]) if s[11] is not None else 0.0,
                        "distance_km": round(dist, 1),
                        "bearing_deg": round(b_deg, 1),
                        "bearing_cardinal": cardinal
                    })
                aircraft.sort(key=lambda a: a["distance_km"])
                _aircraft_cache[cache_key] = {"at": now, "items": aircraft}
                return aircraft
    except Exception as exc:
        print(f"OpenSky fallback error: {exc!r}", flush=True)

    cached = _aircraft_cache.get(cache_key)
    return (cached.get("items") if cached else []) or []
