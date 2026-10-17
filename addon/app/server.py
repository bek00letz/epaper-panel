#!/usr/bin/env python3
"""E-paper panel service.

Renders the rotation on a timer and serves it two ways:

  * port 8099  - frames for the panel. Optionally protected by `frame_token`
                 (?token=...). LAN only.
  * ingress    - the editor and its API, behind Home Assistant's own login.

Frames are held in memory and swapped by reference, so a fetch can never see
a half-written file and there is nothing to clean up on disk.
"""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from aiohttp import web
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import feeds  # noqa: E402
from render import layout, theme as T  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"
HA_BASE = (os.environ.get("HA_BASE") or "http://supervisor/core").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
REFRESH = max(10, min(3600, int(os.environ.get("REFRESH_SECONDS", "60") or 60)))
ESPHOME_DEVICE = (
    re.sub(r"[^a-z0-9_]+", "_", (os.environ.get("ESPHOME_DEVICE") or "crowpanel_epaper").strip().lower()).strip("_")
    or "crowpanel_epaper"
)
FRAME_TOKEN = (os.environ.get("FRAME_TOKEN") or "").strip()

FRAME_PORT = int(os.environ.get("FRAME_PORT", "8099") or 8099)
INGRESS_PORT = int(os.environ.get("INGRESS_PORT", "8080") or 8080)

LAYOUTS_PATH = DATA_DIR / "layouts.json"
PANEL_SETUP_PATH = DATA_DIR / "panel_setup.json"
DEFAULTS_PATH = Path(__file__).parent / "default_layouts.json"
FIXTURE_PATH = Path(__file__).parent / "render" / "fixture.json"

ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
PAGE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_entity_cache = {"at": 0.0, "items": []}
_fixture_cache = None
SHARED_SESSION: aiohttp.ClientSession | None = None


def valid_entity_id(eid: str) -> bool:
    return bool(eid and ENTITY_RE.match(str(eid).strip()))


def load_fixture():
    global _fixture_cache
    if _fixture_cache is None:
        try:
            _fixture_cache = json.loads(FIXTURE_PATH.read_text())
        except Exception:
            _fixture_cache = {"states": {}, "pv_curve_w": []}
    return _fixture_cache


def eval_fixture_template(tpl: str) -> str:
    """Evaluate common HA templates against fixture.json when running offline."""
    states = load_fixture().get("states", {})
    s = str(tpl or "").strip()

    # Handle dynamic_grid JSON template: `[{% for e in [...] %}`
    if "[{% for e in [" in s and 'states(e) | to_json' in s:
        m_ents = re.search(r"for e in \[([^\]]+)\]", s)
        res = []
        if m_ents:
            for raw_eid in m_ents.group(1).split(","):
                eid = raw_eid.strip(" '\"")
                if not eid:
                    continue
                st = states.get(eid) or {}
                cur_state = st.get("state", "on")
                fname = st.get("friendly_name") or eid.split(".")[-1].replace("_", " ").title()
                res.append({
                    "entity": eid,
                    "state": str(cur_state),
                    "name": fname,
                    "changed": "25m ago"
                })
        return json.dumps(res)

    # Handle weather_forecast JSON template
    if '"condition": {{ states(' in s and '"temperature": {{ state_attr(' in s:
        return json.dumps({
            "condition": "rainy",
            "temperature": 8.5,
            "unit": "°C",
            "humidity": 95,
            "wind_speed": 6.1,
            "wind_unit": "km/h",
            "forecast": [
                {"datetime": "2026-10-17T09:00:00+00:00", "condition": "rainy", "temperature": 11.2, "templow": 8.5, "precipitation": 1.0},
                {"datetime": "2026-10-18T09:00:00+00:00", "condition": "partlycloudy", "temperature": 15.5, "templow": 4.6, "precipitation": 0.0},
                {"datetime": "2026-10-19T09:00:00+00:00", "condition": "partlycloudy", "temperature": 17.3, "templow": 7.7, "precipitation": 0.0},
                {"datetime": "2026-10-20T09:00:00+00:00", "condition": "cloudy", "temperature": 15.1, "templow": 7.8, "precipitation": 0.1},
                {"datetime": "2026-10-21T09:00:00+00:00", "condition": "rainy", "temperature": 22.7, "templow": 10.6, "precipitation": 0.6}
            ]
        })

    # Handle calendar template
    if '"message": {{ (state_attr(' in s and '"start_time": {{ (state_attr(' in s:
        return json.dumps([
            {"time_label": "TODAY 19:30", "summary": "Dinner with Sarah", "sub": "Trattoria Al Borgo"},
            {"time_label": "TUE 20 OCT", "summary": "Dentist Appointment", "sub": "09:00 AM • Dr. Popa"},
            {"time_label": "THU 22 OCT", "summary": "Trash & Recycling Pickup", "sub": "Bins out by 07:00"},
            {"time_label": "FRI 30 OCT", "summary": "Trip to Munich", "sub": "Flight LH1657"}
        ])

    if s.startswith("{{") and s.endswith("}}"):
        expr = s[2:-2].strip()
    else:
        expr = s

    # Handle `is_state('entity', 'val')`
    m = re.match(r"^is_state\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)$", expr)
    if m:
        eid, target = m.group(1), m.group(2)
        cur = (states.get(eid) or {}).get("state", "")
        return "True" if str(cur) == target else "False"

    # Handle `states('entity') | int(0) > 0`
    m = re.match(r"^states\(\s*'([^']+)'\s*\)\s*\|\s*int\(\d*\)\s*>\s*(\d+)$", expr)
    if m:
        eid, thresh = m.group(1), int(m.group(2))
        try:
            val = int(float((states.get(eid) or {}).get("state", 0)))
        except (TypeError, ValueError):
            val = 0
        return "True" if val > thresh else "False"

    # Handle zone check on `in_zones`
    if "in_zones" in expr:
        return "False"

    # Extract base value from `states('...')`, `state_attr('...', '...')`, or `states['...'].last_changed`
    val = ""
    m_state = re.search(r"states\(\s*'([^']+)'\s*\)", expr)
    m_attr = re.search(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", expr)
    m_prop = re.search(r"states\[\s*'([^']+)'\s*\]\.(last_changed|last_updated)", expr)

    # Check if calculating days until a date/event
    if "/ 86400" in expr and "as_timestamp" in expr:
        m_attr = re.search(r"state_attr\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", expr)
        m_state = re.search(r"states\(\s*'([^']+)'\s*\)", expr)
        raw_date = None
        if m_attr:
            raw_date = (states.get(m_attr.group(1)) or {}).get(m_attr.group(2))
        elif m_state:
            raw_date = (states.get(m_state.group(1)) or {}).get("state")
        if raw_date:
            try:
                from datetime import timezone
                target_dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc if target_dt.tzinfo else None)
                delta = target_dt - now_dt
                val = str(max(0, int(round(delta.total_seconds() / 86400))))
            except Exception:
                val = "4"
        else:
            val = "4"
        return val

    if m_attr:
        eid, attr = m_attr.group(1), m_attr.group(2)
        raw = (states.get(eid) or {}).get(attr)
        val = "" if raw is None else str(raw)
        if "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%-d %b"
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)
        elif "[:-3]" in expr and len(val) > 3:
            val = val[:-3]
    elif m_prop:
        eid, prop = m_prop.group(1), m_prop.group(2)
        raw = (states.get(eid) or {}).get(prop, "")
        if "relative_time" in expr:
            val = "2 hours ago"
        elif "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%H:%M"
            try:
                dt = datetime.fromisoformat(str(raw))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)
        else:
            val = str(raw)
    elif m_state:
        eid = m_state.group(1)
        raw = (states.get(eid) or {}).get("state")
        val = "" if raw is None else str(raw)
        if "timestamp_custom" in expr:
            m_fmt = re.search(r"timestamp_custom\(\s*'([^']+)'\s*\)", expr)
            fmt = m_fmt.group(1) if m_fmt else "%-d %b"
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                val = dt.strftime(fmt)
            except Exception:
                val = str(raw)

    # Apply any chained `| replace('find', 'repl')`
    for m_rep in re.finditer(r"\|\s*replace\(\s*'((?:\\'|[^'])*)'\s*,\s*'((?:\\'|[^'])*)'\s*\)", expr):
        find = m_rep.group(1).replace("\\'", "'").replace("\\\\", "\\")
        repl = m_rep.group(2).replace("\\'", "'").replace("\\\\", "\\")
        val = val.replace(find, repl)

    return val


def load_sources():
    """Configured data sources, migrating the old add-on options once."""
    existing = feeds.load(DATA_DIR)
    if existing:
        return existing
    seeded = []
    if os.environ.get("JELLYFIN_KEY"):
        seeded.append({"type": "jellyfin", "name": "watch",
                       "base": os.environ.get("JELLYFIN_BASE", ""),
                       "user": os.environ.get("JELLYFIN_USER", ""),
                       "key": os.environ["JELLYFIN_KEY"], "days": 30,
                       "friendly_name": "Next to watch"})
    if seeded:
        feeds.save(DATA_DIR, seeded)
        print(f"migrated {len(seeded)} source(s) from add-on options", flush=True)
    return seeded


def load_layouts():
    """User layouts, seeded from the shipped defaults on first run."""
    for src in (LAYOUTS_PATH, DEFAULTS_PATH):
        try:
            return json.loads(src.read_text())
        except Exception:
            continue
    return {"rotation": [], "pages": {}}


def sanitize_layouts(spec: dict) -> dict:
    """Validate and normalize a layout spec before saving."""
    raw_pages = spec.get("pages")
    if not isinstance(raw_pages, dict):
        raise ValueError("pages must be an object")
    pages = {}
    for name, p in raw_pages.items():
        clean_name = str(name).strip()
        if not PAGE_RE.match(clean_name) or not isinstance(p, dict):
            continue
        tier = p.get("tier") if p.get("tier") in ("rotate", "when", "alert") else "rotate"
        els = [el for el in (p.get("elements") or []) if isinstance(el, dict)]
        entry = {"tier": tier, "elements": els}
        if p.get("show_if") and isinstance(p.get("show_if"), str):
            entry["show_if"] = p["show_if"].strip()
        if tier == "alert":
            entry["hold_minutes"] = max(1, min(1440, int(p.get("hold_minutes") or 10)))
        pages[clean_name] = entry

    raw_rot = spec.get("rotation")
    rotation = []
    if isinstance(raw_rot, list):
        for r in raw_rot:
            rn = str(r).strip()
            if rn in pages and pages[rn].get("tier") != "alert":
                rotation.append(rn)
    try:
        orient = int(spec.get("orientation") or 0)
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    try:
        rot_sec = max(5, min(3600, int(spec.get("rotate_seconds") or 30)))
    except (TypeError, ValueError):
        rot_sec = 30
    display = spec.get("display")
    disp_id = T.get_display(display)["id"]
    return {
        "display": disp_id,
        "orientation": orient,
        "rotate_seconds": rot_sec,
        "rotation": rotation,
        "pages": pages,
    }


def save_layouts(spec):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(spec, indent=2))
    tmp.replace(LAYOUTS_PATH)


async def ha_json(session, path, method="GET", **kw):
    url = f"{HA_BASE}/api{path}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with session.request(method, url, headers=headers, timeout=timeout, **kw) as r:
        r.raise_for_status()
        return await r.json()


async def ha_template(session, tpl) -> str | None:
    """Render one template through Home Assistant.

    Returns None on HTTP/network failure so batched callers can distinguish
    a syntax error in one template from a legitimate empty string.
    """
    if not HA_TOKEN:
        return eval_fixture_template(tpl)
    url = f"{HA_BASE}/api/template"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with session.post(url, headers=headers, json={"template": tpl}, timeout=timeout) as r:
            if r.status != 200:
                return None
            return (await r.text()).strip()
    except Exception:
        return None


async def publish_entity(session, entity_id, state, attrs=None):
    """Push a computed value into Home Assistant as a real entity."""
    if not HA_TOKEN or not valid_entity_id(entity_id):
        return
    safe_eid = urllib.parse.quote(entity_id.strip(), safe=".")
    try:
        await ha_json(session, f"/states/{safe_eid}", method="POST",
                      json={"state": str(state)[:255], "attributes": attrs or {}})
    except Exception as exc:
        print(f"publish {entity_id} failed: {exc!r}", flush=True)


SEP = "<<<|epaper|>>>"


async def resolve_templates(session, templates):
    """Render many templates in ONE request, with per-template fallback.

    If one page has a broken Jinja expression, the batch call returns HTTP 400
    (`None`). Falling back to individual evaluation ensures one bad template
    never blanks out the rest of the panel.
    """
    if not templates:
        return {}
    keys = list(templates)
    if not HA_TOKEN:
        return {k: eval_fixture_template(templates[k]) for k in keys}

    joined = f"\n{SEP}\n".join(templates[k] for k in keys)
    out = await ha_template(session, joined)
    if out is not None:
        parts = [p.strip() for p in out.split(SEP)]
        if len(parts) == len(keys):
            return {k: parts[i] for i, k in enumerate(keys)}

    # Fallback: resolve individually so one broken template only affects itself
    results = {}
    for k in keys:
        res = await ha_template(session, templates[k])
        results[k] = res if res is not None else ""
    return results


class Frames:
    """The current render. Readers take a reference; the writer replaces it."""

    def __init__(self):
        self.strip = b""
        self.single = b""
        self.strip_etag = ""
        self.single_etag = ""
        self.names: list[str] = []
        self.cat_offsets: list[int] = [0]
        self.cat_sizes: list[int] = [1]
        self.cat_pill_widths: list[int] = [110]
        self.cat_names: list[str] = []
        self.cat_count: int = 1
        self.rendered_at = None
        self.error = None


FRAMES = Frames()

# Which alert page, if any, currently owns the screen.
ALERT = {"name": None, "until": 0.0, "fired": {}}


async def call_ha_service(session, domain, service, data=None):
    if not HA_TOKEN:
        return
    safe_domain = re.sub(r"[^a-z0-9_]+", "", str(domain).lower())
    safe_service = re.sub(r"[^a-z0-9_]+", "", str(service).lower())
    try:
        await ha_json(session, f"/services/{safe_domain}/{safe_service}",
                      method="POST", json=data or {})
    except Exception as exc:
        print(f"service {safe_domain}.{safe_service} failed: {exc!r}", flush=True)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _etag(data: bytes) -> str:
    return f'"{hashlib.sha256(data).hexdigest()[:16]}"'


async def curve_series(session, entity, hours=24, buckets=24):
    """Rolling hourly means for a sparkline, from the recorder's history API."""
    eid = str(entity or "").strip()
    if not valid_entity_id(eid):
        return []
    if not HA_TOKEN:
        return list(load_fixture().get("pv_curve_w") or [])

    hours = max(1, min(168, int(hours or 24)))
    buckets = max(2, min(48, int(buckets or min(hours, 24))))
    now = datetime.now().astimezone()
    start = now - timedelta(hours=hours)
    safe_start = urllib.parse.quote(start.isoformat(), safe=":+")
    safe_eid = urllib.parse.quote(eid, safe=".")
    path = (f"/history/period/{safe_start}"
            f"?filter_entity_id={safe_eid}&minimal_response&no_attributes")
    try:
        rows = await ha_json(session, path)
    except Exception:
        return []
    if not rows or not rows[0]:
        return []

    span_sec = max(1.0, (now - start).total_seconds())
    sums, counts = [0.0] * buckets, [0] * buckets
    initial_val = None
    for r in rows[0]:
        try:
            v = float(r["state"])
            t = datetime.fromisoformat(r["last_changed"]).astimezone()
        except (KeyError, TypeError, ValueError):
            continue
        if t <= start:
            initial_val = v
            continue
        idx = int(((t - start).total_seconds() / span_sec) * buckets)
        idx = max(0, min(buckets - 1, idx))
        sums[idx] += v
        counts[idx] += 1

    last = max((i for i, c in enumerate(counts) if c), default=-1)
    if last < 0:
        return [initial_val, initial_val] if initial_val is not None else []

    out = []
    carry = initial_val if initial_val is not None else 0.0
    for i in range(last + 1):
        if counts[i]:
            carry = sums[i] / counts[i]
        out.append(carry)
    return out



_aircraft_cache = {"at": 0.0, "items": []}
_home_location_cache = {"at": 0.0, "lat": 45.794, "lon": 21.222}
_weather_cache = {}
_calendar_cache = {}
_racing_cache = {}
_sports_match_cache = {}
_feed_items_cache = {}


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


async def get_home_coordinates(session):
    now = time.time()
    if now - _home_location_cache["at"] < 3600 and _home_location_cache["lat"] is not None:
        return _home_location_cache["lat"], _home_location_cache["lon"]
    if HA_TOKEN:
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


async def fetch_overhead_aircraft(session, radius_km=35.0):
    now = time.time()
    if now - _aircraft_cache["at"] < 45.0 and _aircraft_cache["items"] is not None:
        return _aircraft_cache["items"]

    lat, lon = await get_home_coordinates(session)
    radius_km = max(5.0, min(150.0, float(radius_km or 35.0)))
    d_lat = radius_km / 111.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    d_lon = radius_km / (111.0 * cos_lat)

    url = (
        f"https://opensky-network.org/api/states/all"
        f"?lamin={lat - d_lat:.4f}&lamax={lat + d_lat:.4f}"
        f"&lomin={lon - d_lon:.4f}&lomax={lon + d_lon:.4f}"
    )
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.9 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with session.get(url, headers=headers, timeout=timeout) as r:
            if r.status != 200:
                return _aircraft_cache["items"]
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
            _aircraft_cache["at"] = now
            _aircraft_cache["items"] = aircraft
            return aircraft
    except Exception as exc:
        print(f"fetch_overhead_aircraft error: {exc!r}", flush=True)
        return _aircraft_cache["items"]


async def fetch_weather_forecast(session, entity_id, fallback=None):
    eid = str(entity_id or "weather.forecast_home").strip()
    now = time.time()
    cached = _weather_cache.get(eid)
    if cached and (now - cached["at"] < 600):
        return cached["data"]

    base_data = {}
    if isinstance(fallback, dict):
        base_data = dict(fallback)
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass

    if not HA_TOKEN:
        return base_data

    try:
        st = await ha_json(session, f"/states/{urllib.parse.quote(eid, safe='.')}")
        attrs = st.get("attributes", {})
        base_data.update({
            "entity": eid,
            "condition": st.get("state", base_data.get("condition", "cloudy")),
            "temperature": attrs.get("temperature", base_data.get("temperature")),
            "unit": attrs.get("temperature_unit", base_data.get("unit", "°C")),
            "humidity": attrs.get("humidity", base_data.get("humidity")),
            "wind_speed": attrs.get("wind_speed", base_data.get("wind_speed")),
            "wind_unit": attrs.get("wind_speed_unit", base_data.get("wind_unit", "km/h")),
            "attribution": attrs.get("attribution", "")
        })

        f_resp = await ha_json(session, "/services/weather/get_forecasts?return_response=1",
                               method="POST", json={"entity_id": eid, "type": "daily"})
        # HA wraps return_response in {"response": {eid: ...}} or sometimes directly
        payload = f_resp.get("response", f_resp) if isinstance(f_resp, dict) else {}
        if isinstance(payload, dict) and eid in payload:
            forecast_list = payload[eid].get("forecast")
            if isinstance(forecast_list, list):
                base_data["forecast"] = forecast_list

        _weather_cache[eid] = {"at": now, "data": base_data}
        return base_data
    except Exception as exc:
        print(f"fetch_weather_forecast error for {eid}: {exc!r}", flush=True)
        return base_data


async def fetch_calendar_events(session, entity_id, days=31, fallback=None):
    raw_eid = str(entity_id or "").strip()
    if not raw_eid:
        return fallback
    now = time.time()
    cached = _calendar_cache.get(raw_eid)
    if cached and (now - cached["at"] < 300):
        return cached["data"]

    if not HA_TOKEN:
        return fallback

    # Support comma-separated list of calendar entities for family/multi-calendar merging
    eids = [e.strip() for e in raw_eid.split(",") if e.strip()]
    if not eids:
        return fallback

    try:
        all_events = []
        for eid in eids:
            try:
                c_resp = await ha_json(session, "/services/calendar/get_events?return_response=1",
                                       method="POST", json={"entity_id": eid, "duration": {"days": days}})
                payload = c_resp.get("response", c_resp) if isinstance(c_resp, dict) else {}
                cal_events = []
                if isinstance(payload, dict) and eid in payload:
                    cal_events = payload[eid].get("events") or []
                
                # Tag each event with source calendar badge
                short_badge = eid.replace("calendar.", "").upper()[:4]
                for ev in cal_events:
                    ev_copy = dict(ev)
                    ev_copy["calendar"] = eid
                    ev_copy["cal_badge"] = short_badge
                    all_events.append(ev_copy)
            except Exception as e_inner:
                print(f"calendar fetch error for {eid}: {e_inner!r}", flush=True)

        # Deduplicate and sort chronologically by start timestamp
        def _event_key(ev):
            raw_st = ev.get("start") or ev.get("start_time") or ""
            return str(raw_st)

        all_events.sort(key=_event_key)
        _calendar_cache[raw_eid] = {"at": now, "data": all_events}
        return all_events
    except Exception as exc:
        print(f"fetch_calendar_events error for {raw_eid}: {exc!r}", flush=True)
        return fallback


async def fetch_racing_data(session, entity_or_series="f1", fallback=None):
    now = time.time()
    raw_key = str(entity_or_series or "f1").strip().lower()

    # 1. Approach A: Check if fallback is a resolved template from HA entity (e.g. sensor.f1)
    base_data = None
    if isinstance(fallback, dict):
        base_data = fallback
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass

    ha_event_name = ""
    ha_status = ""
    ha_circuit = ""
    ha_date = ""
    if isinstance(base_data, dict) and "attributes" in base_data:
        attrs = base_data.get("attributes") or {}
        ha_status = str(base_data.get("state") or "").upper()
        ha_event_name = attrs.get("event_name") or attrs.get("event") or ""
        ha_circuit = attrs.get("venue") or attrs.get("circuit") or ""
        ha_date = attrs.get("date") or ""
        if attrs.get("standings"):
            return {
                "series": "F1",
                "event_name": ha_event_name or "Formula 1 Grand Prix",
                "circuit": ha_circuit or "Grand Prix Circuit",
                "status": ha_status or "IN",
                "lap": attrs.get("lap"),
                "total_laps": attrs.get("total_laps"),
                "clock": attrs.get("clock") or ha_status,
                "standings": attrs.get("standings")
            }

    # 2. Check in-memory cache
    cached = _racing_cache.get(raw_key)
    if cached and (now - cached["at"] < (60.0 if cached.get("is_live") else 600.0)):
        return cached["data"]

    # 3. Approach B: Query ESPN F1 scoreboard
    f1_url = "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.11 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    event_data = {
        "series": "F1",
        "event_name": ha_event_name or "Formula 1 Grand Prix",
        "circuit": ha_circuit or "Grand Prix Circuit",
        "detail": "Upcoming Grand Prix Session",
        "status": ha_status or "PRE",
        "standings": []
    }
    is_live = False

    try:
        async with session.get(f1_url, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                if events:
                    ev = events[0]
                    ev_name = ev.get("name") or ha_event_name or "Formula 1 Grand Prix"
                    circuit_info = ev.get("circuit") or {}
                    c_name = circuit_info.get("fullName") or ha_circuit or "Grand Prix Circuit"
                    c_addr = circuit_info.get("address", {})
                    c_city = c_addr.get("city") or ""
                    circuit_str = f"{c_name} · {c_city}" if c_city else c_name
                    st_desc = ev.get("status", {}).get("type", {}).get("description") or "Scheduled"
                    st_state = ev.get("status", {}).get("type", {}).get("state") or "pre"
                    is_live = (st_state == "in" or "progress" in st_desc.lower())

                    date_iso = ev.get("date") or ha_date
                    detail_str = f"Status: {st_desc}"
                    if date_iso:
                        try:
                            dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                            detail_str = dt.strftime("%a %b %d · %H:%M UTC")
                        except Exception:
                            detail_str = f"{st_desc} · {str(date_iso)[:10]}"

                    event_data = {
                        "series": "F1",
                        "event_name": ev_name,
                        "circuit": circuit_str,
                        "detail": detail_str,
                        "status": "IN" if is_live else ("POST" if st_state == "post" else "PRE"),
                        "clock": st_desc,
                        "standings": []
                    }

                    comps = (ev.get("competitions") or [{}])[0].get("competitors") or []
                    if comps:
                        parsed_standings = []
                        for idx, c in enumerate(comps[:10]):
                            ath = c.get("athlete") or {}
                            tm = c.get("team") or {}
                            code = ath.get("abbreviation") or ath.get("shortName") or "DRV"
                            team_name = tm.get("displayName") or tm.get("shortDisplayName") or ""
                            gap_val = c.get("status", {}).get("displayValue") or ("LEADER" if idx == 0 else "")
                            parsed_standings.append({
                                "pos": idx + 1,
                                "driver": str(code)[:3].upper(),
                                "team": team_name,
                                "gap": gap_val,
                                "tyre": "M"
                            })
                        if parsed_standings:
                            event_data["standings"] = parsed_standings

        _racing_cache[raw_key] = {"at": now, "data": event_data, "is_live": is_live}
        return event_data
    except Exception as exc:
        print(f"fetch_racing_data error: {exc!r}", flush=True)
        return _racing_cache.get(raw_key, {}).get("data") or event_data


def _parse_espn_event(ev, league_title="MATCH"):
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    st_type = comp.get("status", {}).get("type", {})
    st_state = st_type.get("state") or "pre"
    st_desc = st_type.get("description") or st_type.get("detail") or "Scheduled"
    clock_val = comp.get("status", {}).get("displayClock")
    is_live = (st_state == "in")

    clock_badge = f"{clock_val} · {st_desc}" if (clock_val and clock_val != "0'" and is_live) else st_desc
    venue_title = comp.get("venue", {}).get("fullName") or ""

    home_id = str(home.get("team", {}).get("id") or "")
    events_home = []
    events_away = []
    for dt in comp.get("details", []):
        t_txt = dt.get("type", {}).get("text") or ""
        clk = dt.get("clock", {}).get("displayValue") or ""
        athletes = dt.get("athletesInvolved") or []
        p_name = athletes[0].get("displayName") if athletes else ""
        if p_name and ("Goal" in t_txt or "Point" in t_txt or "Touchdown" in t_txt or "Home Run" in t_txt):
            entry_str = f"{p_name} ({clk})" if clk else p_name
            if str(dt.get("team", {}).get("id") or "") == home_id:
                events_home.append(entry_str)
            else:
                events_away.append(entry_str)

    return {
        "league": league_title,
        "venue": venue_title,
        "clock": clock_badge,
        "status": st_state.upper(),
        "is_live": is_live,
        "home_team": home.get("team", {}).get("displayName") or home.get("team", {}).get("shortDisplayName") or "HOME",
        "home_score": home.get("score") if home.get("score") is not None else "-",
        "home_stats": (home.get("records") or [{}])[0].get("summary", ""),
        "away_team": away.get("team", {}).get("displayName") or away.get("team", {}).get("shortDisplayName") or "AWAY",
        "away_score": away.get("score") if away.get("score") is not None else "-",
        "away_stats": (away.get("records") or [{}])[0].get("summary", ""),
        "events_home": ", ".join(events_home[:3]),
        "events_away": ", ".join(events_away[:3])
    }


async def fetch_sports_match(session, entity_or_league="soccer/eng.1", team=None, fallback=None):
    now = time.time()
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    cache_key = f"{raw_input}:{str(team or '').lower()}"

    # 1. Approach A: Check if fallback is a resolved HA entity from ha-teamtracker
    base_data = None
    if isinstance(fallback, dict):
        base_data = fallback
    elif isinstance(fallback, str) and fallback.strip():
        try:
            base_data = json.loads(fallback)
        except Exception:
            pass

    if isinstance(base_data, dict) and "attributes" in base_data:
        attrs = base_data.get("attributes") or {}
        home = attrs.get("team_name") or attrs.get("team_abbr") or "HOME"
        away = attrs.get("opponent_name") or attrs.get("opponent_abbr") or "AWAY"
        h_score = attrs.get("team_score")
        a_score = attrs.get("opponent_score")
        st = str(base_data.get("state") or "PRE").upper()
        clock_str = attrs.get("clock") or attrs.get("quarter") or attrs.get("period") or st
        last_play = attrs.get("last_play") or ""
        down_dist = attrs.get("down_distance_text") or ""
        venue = attrs.get("venue") or ""
        league_name = attrs.get("league") or "MATCH"
        return [{
            "league": league_name,
            "venue": venue,
            "clock": clock_str,
            "status": st,
            "home_team": home,
            "home_score": h_score if h_score is not None else "-",
            "home_stats": down_dist,
            "away_team": away,
            "away_score": a_score if a_score is not None else "-",
            "away_stats": "",
            "events_home": last_play,
            "events_away": ""
        }]

    # 2. Check in-memory cache
    cached = _sports_match_cache.get(cache_key)
    if cached and (now - cached["at"] < (30.0 if cached.get("is_live") else 300.0)):
        return cached["data"]

    # 3. Approach B: Map friendly league names to ESPN endpoint
    league_map = {
        "premier_league": "soccer/eng.1",
        "epl": "soccer/eng.1",
        "champions_league": "soccer/uefa.champions",
        "ucl": "soccer/uefa.champions",
        "la_liga": "soccer/esp.1",
        "bundesliga": "soccer/ger.1",
        "serie_a": "soccer/ita.1",
        "mls": "soccer/usa.1",
        "nba": "basketball/nba",
        "wnba": "basketball/wnba",
        "nfl": "football/nfl",
        "college_football": "football/college-football",
        "mlb": "baseball/mlb",
        "nhl": "hockey/nhl"
    }
    slug = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = league_map.get(slug, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"

    url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.11 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    try:
        async with session.get(url, headers=headers, timeout=timeout) as r:
            if r.status != 200:
                return cached["data"] if cached else None
            data = await r.json()
            events = data.get("events") or []
            if not events:
                return cached["data"] if cached else None

            league_title = (data.get("leagues") or [{}])[0].get("name") or "MATCH"
            parsed_matches = [_parse_espn_event(ev, league_title) for ev in events]

            if team:
                query = str(team).lower().strip()
                matched, others = [], []
                for m in parsed_matches:
                    if (query in m["home_team"].lower() or query in m["away_team"].lower()):
                        matched.append(m)
                    else:
                        others.append(m)
                parsed_matches = matched + others
            else:
                def _st_sort(m):
                    st = m.get("status", "")
                    if st == "IN": return 0
                    if st == "PRE": return 1
                    return 2
                parsed_matches.sort(key=_st_sort)

            is_any_live = any(m.get("is_live") for m in parsed_matches)
            _sports_match_cache[cache_key] = {"at": now, "data": parsed_matches, "is_live": is_any_live}
            return parsed_matches
    except Exception as exc:
        print(f"fetch_sports_match error: {exc!r}", flush=True)
        return cached["data"] if cached else None


async def enrich_page_values(session, page, vals):
    for i, el in enumerate(page.get("elements", [])):
        t = el.get("type")
        if t == "weather_forecast":
            wdata = await fetch_weather_forecast(session, el.get("entity", "weather.forecast_home"), fallback=vals.get(i))
            if wdata:
                vals[i] = wdata
        elif t in ("calendar_month", "calendar_agenda"):
            cal_ent = el.get("entity")
            if cal_ent:
                cal_data = await fetch_calendar_events(session, cal_ent, days=31, fallback=vals.get(i))
                if cal_data:
                    vals[i] = cal_data
        elif t == "flight_tracker":
            radius = float(el.get("radius") or 35)
            fl_data = await fetch_overhead_aircraft(session, radius_km=radius)
            if fl_data is not None:
                vals[i] = fl_data
        elif t == "sports_racing":
            entity_or_series = el.get("entity") or el.get("series") or "f1"
            race_data = await fetch_racing_data(session, entity_or_series, fallback=vals.get(i))
            if race_data:
                vals[i] = race_data
        elif t == "sports_match":
            entity_or_league = el.get("entity") or el.get("league") or "soccer/eng.1"
            team = el.get("team")
            match_data = await fetch_sports_match(session, entity_or_league, team=team, fallback=vals.get(i))
            if match_data:
                vals[i] = match_data


async def gather_values(session, spec, names):
    """Resolve every template on every named page in one request."""
    batch, index = {}, []
    for name in names:
        page = spec["pages"][name]
        for i, tpl in layout.collect_templates(page).items():
            key = f"{name}:{i}"
            batch[key] = tpl
            index.append((name, i, key))
    resolved = await resolve_templates(session, batch)
    out = {n: {} for n in names}
    for name, i, key in index:
        out[name][i] = resolved.get(key, "")
    for name in names:
        await enrich_page_values(session, spec["pages"][name], out[name])
    return out


async def eligible_pages(session, spec):
    """Pages whose tier and show_if say they belong in the rotation now."""
    rotation = spec.get("rotation", [])
    defs = spec.get("pages", {})
    gates = {n: defs[n]["show_if"] for n in set(rotation)
             if n in defs and defs[n].get("tier") == "when" and defs[n].get("show_if")}
    passed = await resolve_templates(session, gates) if gates else {}
    live = []
    for name in rotation:
        page = defs.get(name)
        if page is None or page.get("tier") == "alert":
            continue
        if name in gates and str(passed.get(name, "")).strip().lower() not in ("true", "on", "yes", "1"):
            continue
        live.append(name)
    return live or [n for n in rotation if n in defs and defs[n].get("tier") != "alert"][:1]


async def publish_category_sensors(session, cur_f):
    if not HA_TOKEN or not cur_f or not cur_f.rendered_at:
        return
    try:
        await publish_entity(session, "sensor.epaper_category_count", cur_f.cat_count,
                             {"friendly_name": "E-Paper Category Count", "icon": "mdi:view-grid-outline",
                              "offsets": cur_f.cat_offsets, "sizes": cur_f.cat_sizes, "names": cur_f.cat_names})
        await publish_entity(session, "sensor.epaper_category_offsets", ",".join(map(str, cur_f.cat_offsets)),
                             {"friendly_name": "E-Paper Category Offsets", "icon": "mdi:format-list-numbered"})
        await publish_entity(session, "sensor.epaper_category_sizes", ",".join(map(str, cur_f.cat_sizes)),
                             {"friendly_name": "E-Paper Category Sizes", "icon": "mdi:format-list-bulleted"})
        await publish_entity(session, "sensor.epaper_category_pill_widths", ",".join(map(str, cur_f.cat_pill_widths)),
                             {"friendly_name": "E-Paper Category Pill Widths", "icon": "mdi:ruler"})
        await publish_entity(session, "sensor.epaper_category_names", ",".join(cur_f.cat_names),
                             {"friendly_name": "E-Paper Category Names", "icon": "mdi:tag-multiple-outline"})
    except Exception as exc:
        print(f"publish category sensors error: {exc!r}", flush=True)


async def publish_computed(session):
    """Run every configured source and publish what it returns."""
    srcs = load_sources()
    if srcs:
        ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": session}
        for entity_id, state, attrs in await feeds.run_all(srcs, ctx):
            if attrs and "items" in attrs:
                _feed_items_cache[entity_id] = attrs["items"]
            await publish_entity(session, entity_id, state, attrs)

    # Publish overhead aircraft sensor to Home Assistant
    try:
        aircraft = await fetch_overhead_aircraft(session, radius_km=35.0)
        closest_cs = aircraft[0]["callsign"] if aircraft else "None"
        await publish_entity(session, "sensor.overhead_aircraft_count", len(aircraft),
                             {"unit_of_measurement": "aircraft", "friendly_name": "Overhead Aircraft Count",
                              "closest_callsign": closest_cs, "icon": "mdi:airplane"})
        if aircraft:
            await publish_entity(session, "sensor.closest_aircraft", closest_cs,
                                 {"friendly_name": "Closest Aircraft", "distance_km": aircraft[0]["distance_km"],
                                  "bearing": aircraft[0]["bearing_cardinal"], "altitude_m": aircraft[0]["altitude_m"],
                                  "country": aircraft[0]["country"], "icon": "mdi:airplane"})
    except Exception as exc:
        print(f"publish aircraft sensor failed: {exc!r}", flush=True)

    # Publish Formula 1 status sensor
    try:
        f1_data = await fetch_racing_data(session, "f1")
        if f1_data:
            f1_st = f1_data.get("status") or "PRE"
            await publish_entity(session, "sensor.f1_status", f1_st,
                                 {"friendly_name": "Formula 1 Status",
                                  "event_name": f1_data.get("event_name"),
                                  "circuit": f1_data.get("circuit"),
                                  "detail": f1_data.get("detail"),
                                  "clock": f1_data.get("clock"),
                                  "icon": "mdi:racing-helmet"})
    except Exception as exc:
        print(f"publish f1 status failed: {exc!r}", flush=True)

    # Publish E-Paper panel system status sensors & MQTT discovery
    try:
        cur_f = globals().get("FRAMES")
        if cur_f and cur_f.rendered_at:
            await publish_entity(session, "sensor.epaper_panel_last_render", cur_f.rendered_at,
                                 {"friendly_name": "E-Paper Last Render", "icon": "mdi:clock-check-outline",
                                  "pages_count": len(cur_f.names), "active_pages": cur_f.names,
                                  "device_class": "timestamp"})
            await publish_category_sensors(session, cur_f)
            await publish_mqtt_discovery(session, cur_f)
    except Exception as exc:
        pass


_mqtt_discovery_published = False


async def publish_mqtt_discovery(session, frames):
    """Publish Home Assistant MQTT Auto-Discovery entities if MQTT integration is active."""
    global _mqtt_discovery_published
    if not HA_TOKEN:
        return
    try:
        if not _mqtt_discovery_published:
            dev_info = {
                "identifiers": ["epaper_panel_hub"],
                "name": "E-Paper Display Panel",
                "manufacturer": "Elecrow",
                "model": "CrowPanel E-Paper",
                "sw_version": "0.8.17"
            }
            btn_payload = {
                "name": "E-Paper Refresh Now",
                "unique_id": "epaper_panel_refresh_button",
                "command_topic": "homeassistant/epaper_panel/refresh",
                "icon": "mdi:refresh",
                "device": dev_info
            }
            await call_ha_service(session, "mqtt", "publish", {
                "topic": "homeassistant/button/epaper_panel/refresh/config",
                "payload": json.dumps(btn_payload),
                "retain": True
            })
            sens_payload = {
                "name": "E-Paper Last Render",
                "unique_id": "epaper_panel_last_render",
                "state_topic": "homeassistant/epaper_panel/last_render",
                "device_class": "timestamp",
                "icon": "mdi:clock-check-outline",
                "device": dev_info
            }
            await call_ha_service(session, "mqtt", "publish", {
                "topic": "homeassistant/sensor/epaper_panel/last_render/config",
                "payload": json.dumps(sens_payload),
                "retain": True
            })
            _mqtt_discovery_published = True

        if frames and frames.rendered_at:
            await call_ha_service(session, "mqtt", "publish", {
                "topic": "homeassistant/epaper_panel/last_render",
                "payload": str(frames.rendered_at),
                "retain": True
            })
    except Exception:
        pass


async def check_alerts(session, spec):
    """Alert pages never rotate. They seize the screen when their condition
    turns true, hold, then hand it back.

    Edge-triggered, not level: an alert that stays true all evening fires
    once, rather than grabbing the panel every refresh.
    """
    now = time.time()
    defs = spec.get("pages", {})
    alerts = {n: p for n, p in defs.items()
              if p.get("tier") == "alert" and p.get("show_if")}
    if not alerts:
        ALERT["name"], ALERT["until"] = None, 0.0
        return None

    states = await resolve_templates(session, {n: p["show_if"] for n, p in alerts.items()})
    truthy = {n for n, v in states.items()
              if str(v).strip().lower() in ("true", "on", "yes", "1")}

    # release an expired or no-longer-true alert
    if ALERT["name"] and (now > ALERT["until"] or ALERT["name"] not in truthy):
        print(f"alert {ALERT['name']} released", flush=True)
        ALERT["name"], ALERT["until"] = None, 0.0

    for name in truthy:
        if ALERT["fired"].get(name):
            continue                                  # already handled this episode
        hold = max(1, min(1440, int(alerts[name].get("hold_minutes", 10)))) * 60
        ALERT.update(name=name, until=now + hold)
        ALERT["fired"][name] = True
        print(f"alert {name} fired, holding {hold}s", flush=True)
        break

    for name in list(ALERT["fired"]):                  # re-arm when it goes false
        if name not in truthy:
            ALERT["fired"].pop(name, None)

    return ALERT["name"]


async def build_frames(session):
    await publish_computed(session)
    spec = load_layouts()
    orient = int(spec.get("orientation") or 0)
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = spec.get("display", T.DEFAULT_DISPLAY)
    disp = T.get_display(display)
    dw, dh = disp["w"], disp["h"]
    alert = await check_alerts(session, spec)
    if alert and alert in spec.get("pages", {}):
        # Serve a 1-page strip while an alert is active: decodes in ~1s on
        # the ESP32 and prevents its 5-minute interval from rotating away.
        live = [alert]
    else:
        live = await eligible_pages(session, spec)

    if not live:
        cw, _ = T.canvas_dims(orient, display=display)
        empty_page = {"elements": [{"type": "text", "value": "no pages", "x": 24, "y": 60, "w": cw - 48, "h": 120}]}
        img = await asyncio.to_thread(
            layout.render_page, empty_page, {},
            clock=datetime.now().strftime("%H:%M"), label="empty", orientation=orient, display=display)
        one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
        png = _png(one)
        return png, png, [], [0], [1], ["empty"], [110]

    vals = await gather_values(session, spec, set(live))

    series = {}
    for name in set(live):
        for i, el in enumerate(spec["pages"][name].get("elements", [])):
            if el.get("type") == "curve" and el.get("entity"):
                series.setdefault(name, {})[i] = await curve_series(
                    session, el["entity"], int(el.get("hours", 24)))

    imgs = []
    cat_offsets = []
    cat_sizes = []
    cat_names = []
    cat_pill_widths = []

    for cat_i, cat_name in enumerate(live):
        page_def = spec["pages"][cat_name]
        page_vals = vals.get(cat_name, {})
        elements = page_def.get("elements", [])

        # Determine sub_count for this category
        sub_count = 1
        sub_type = None

        # 1. Flight tracker element
        for el_idx, el in enumerate(elements):
            if el.get("type") == "flight_tracker":
                fl_list = page_vals.get(el_idx)
                if isinstance(fl_list, list) and len(fl_list) > 1:
                    sub_count = max(sub_count, min(len(fl_list), 5))
                    sub_type = "flight"
            elif el.get("type") == "sports_match":
                sm_list = page_vals.get(el_idx)
                if isinstance(sm_list, list) and len(sm_list) > 1:
                    sub_count = max(sub_count, min(len(sm_list), 6))
                    sub_type = "sports"

        # 2. Feed items (e.g. Jellyfin, Watch, or any feed sensor with an 'items' attribute)
        feed_entity = None
        feed_items = None
        for el in elements:
            ent = str(el.get("entity", ""))
            if ent.startswith("sensor.epaper_") and not ent.endswith("_count") and not ent.startswith("sensor.epaper_category_") and not ent.startswith("sensor.epaper_panel_"):
                items = _feed_items_cache.get(ent)
                if not items:
                    try:
                        st_data = await ha_json(session, f"/states/{ent}")
                        items = (st_data.get("attributes") or {}).get("items")
                        if items:
                            _feed_items_cache[ent] = items
                    except Exception:
                        pass
                if items and isinstance(items, list) and len(items) > 1:
                    feed_entity = ent
                    feed_items = items
                    sub_count = max(sub_count, min(len(feed_items), 5))
                    sub_type = "feed"
                    break

        cat_display_name = cat_name.replace("_", " ").upper()
        cat_label = f"{cat_i + 1}/{len(live)}  {cat_display_name}"
        cat_f = T.font(13, bold=True)
        cat_w = T.text_width(cat_label, cat_f) + 20
        margin = disp["margin"] if dw >= 400 else min(disp["margin"], 16)
        cat_x0 = 96 if dw >= 400 else (margin + T.text_width("00:00", T.font(18)) + 12)
        sub_w = 48
        sub_x1 = dw - margin
        sub_x0 = sub_x1 - sub_w
        max_cat_w = max(40, (sub_x0 - cat_x0 - 8) if sub_count > 1 else (sub_x1 - cat_x0 - 8))
        cat_w = min(cat_w, max_cat_w)
        cat_offsets.append(len(imgs))
        cat_sizes.append(sub_count)
        cat_names.append(cat_name)
        cat_pill_widths.append(cat_w)

        # Render each sub-item for this category
        for s_idx in range(sub_count):
            cloned_page = {**page_def, "elements": []}
            cloned_vals = dict(page_vals)

            for el_idx, el in enumerate(elements):
                el_c = dict(el)
                if el.get("type") in ("flight_tracker", "sports_match"):
                    el_c["sub_index"] = s_idx
                elif sub_type in ("feed", "watch") and feed_items and s_idx < len(feed_items):
                    item_data = feed_items[s_idx]
                    top_title = str(feed_items[0].get("title", "")).strip()
                    top_detail = str(feed_items[0].get("detail", "")).strip()
                    ent = str(el.get("entity", "")).strip()
                    val_str = str(el.get("value", "")).strip()
                    cur_val = str(cloned_vals.get(el_idx, "")).strip()

                    # 1. Detail / Episode field: matches attribute 'detail', a template referencing detail, or the initial top detail text
                    is_detail = (
                        (ent and (ent == feed_entity or ent == "sensor.epaper_watch") and el.get("show") == "attribute" and "detail" in str(el.get("attribute", "")).lower())
                        or ("detail" in val_str.lower() and any(k in val_str.lower() for k in ("state_attr", "states", feed_entity, "watch", "jelly", "item")))
                        or (bool(top_detail) and cur_val == top_detail)
                    )

                    # 2. Show title field: matches feed entity, or the initial top show title
                    is_title = (
                        (ent and (ent == feed_entity or ent == "sensor.epaper_watch") and el.get("show") != "attribute")
                        or (bool(top_title) and cur_val == top_title)
                    )

                    if is_detail:
                        cloned_vals[el_idx] = item_data.get("detail", "")
                        if "value" in el_c and "{{" in str(el_c["value"]):
                            el_c["value"] = ""
                    elif is_title:
                        cloned_vals[el_idx] = item_data.get("title", "")
                        if "value" in el_c and "{{" in str(el_c["value"]):
                            el_c["value"] = ""
                    elif el.get("type") == "text" and any(k in val_str.lower() for k in ("watch", "deck", "media", "episode", "unwatch")) and sub_count > 1:
                        base_val = val_str.split("  [")[0]
                        el_c["value"] = f"{base_val}  [{s_idx + 1}/{sub_count}]"

                cloned_page["elements"].append(el_c)

            sub_label = f"{s_idx + 1}/{sub_count}" if sub_count > 1 else ""

            img = await asyncio.to_thread(
                layout.render_page, cloned_page, cloned_vals,
                clock=datetime.now().strftime("%H:%M"),
                label=cat_display_name,
                cat_label=cat_label,
                sub_label=sub_label,
                battery_pct=None, series=series.get(cat_name), orientation=orient, display=display)
            imgs.append(T.orient_for_panel(T.to_1bit(img), orient, display=display))

    strip = Image.new("1", (dw, dh * len(imgs) + 1), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * dh))

    # Self-describing image header on row meta_y:
    meta_y = dh * len(imgs)
    # Magic 0xA5, version 0x01, cat_count
    payload = [0xA5, 0x01, len(cat_offsets)]
    for off, sz, pw in zip(cat_offsets, cat_sizes, cat_pill_widths):
        payload.append(min(255, int(off)))
        payload.append(min(255, int(sz)))
        payload.append(min(255, int(pw)))

    px_x = 0
    for byte_val in payload:
        for b in range(8):
            bit = (byte_val >> (7 - b)) & 1
            # In PIL mode "1", 0 = black (decoded as red < 128 in ESPHome), 1 = white
            strip.putpixel((px_x, meta_y), 0 if bit else 1)
            px_x += 1

    return _png(strip), _png(imgs[0]), live, cat_offsets, cat_sizes, cat_names, cat_pill_widths


async def refresh_frames(session):
    """Build a new Frames snapshot and atomically swap FRAMES."""
    strip, single, names, cat_offsets, cat_sizes, cat_names, cat_pill_widths = await build_frames(session)
    old_f = globals().get("FRAMES")
    struct_changed = (
        old_f is not None and getattr(old_f, "rendered_at", None) and (
            old_f.cat_offsets != cat_offsets or
            old_f.cat_sizes != cat_sizes or
            old_f.cat_names != cat_names or
            getattr(old_f, "cat_pill_widths", None) != cat_pill_widths
        )
    )
    nxt = Frames()
    nxt.strip, nxt.single, nxt.names = strip, single, names
    nxt.strip_etag = _etag(strip)
    nxt.single_etag = _etag(single)
    nxt.rendered_at = datetime.now().isoformat(timespec="seconds")
    nxt.cat_offsets = cat_offsets
    nxt.cat_sizes = cat_sizes
    nxt.cat_names = cat_names
    nxt.cat_pill_widths = cat_pill_widths
    nxt.cat_count = len(cat_offsets)
    globals()["FRAMES"] = nxt
    print(f"rendered {names} ({len(strip)}B strip, {nxt.cat_count} cats, offsets: {cat_offsets}, sizes: {cat_sizes}, pill_widths: {cat_pill_widths})", flush=True)
    await publish_category_sensors(session, nxt)
    if struct_changed:
        print("Category structure changed -- pushing immediate refresh to panel", flush=True)
        await push_panel_update(advance_page=False)
    return nxt


LAST_PANEL_PUSH_TIME = time.time()


async def push_panel_update(advance_page=True):
    """Trigger the physical panel to redraw with latest frames."""
    if not HA_TOKEN:
        return False
    candidates = list(dict.fromkeys([
        ESPHOME_DEVICE,
        "crowpanel_epaper",
        "e_paper_panel",
        "epaper_panel"
    ]))
    ok = False
    for dev in candidates:
        try:
            if advance_page:
                try:
                    await call_ha_service(SHARED_SESSION, "esphome", f"{dev}_page_step", {"delta": 1})
                    ok = True
                    break
                except Exception:
                    pass
            await call_ha_service(SHARED_SESSION, "esphome", f"{dev}_refresh_now")
            ok = True
            break
        except Exception:
            continue
    return ok


async def step_panel_page(delta=1):
    """Trigger the physical panel to advance or step backwards."""
    if not HA_TOKEN:
        return False
    candidates = list(dict.fromkeys([
        ESPHOME_DEVICE,
        "crowpanel_epaper",
        "e_paper_panel",
        "epaper_panel"
    ]))
    ok = False
    for dev in candidates:
        try:
            await call_ha_service(SHARED_SESSION, "esphome", f"{dev}_page_step", {"delta": int(delta)})
            ok = True
            break
        except Exception:
            continue
    return ok


async def render_loop():
    global LAST_PANEL_PUSH_TIME
    was_alert = None
    LAST_PANEL_PUSH_TIME = time.time()
    while True:
        try:
            await refresh_frames(SHARED_SESSION)
            cur_alert = ALERT["name"]
            if cur_alert != was_alert:
                # Immediately push when an alert seizes or releases the screen.
                await push_panel_update(advance_page=False)
                was_alert = cur_alert
                LAST_PANEL_PUSH_TIME = time.time()
            else:
                panel_cfg = load_panel_setup()
                m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
                panel_min = int(m_int.group(0)) if m_int else 5
                panel_sec = max(30, panel_min * 60)
                now = time.time()
                if now - LAST_PANEL_PUSH_TIME >= panel_sec:
                    LAST_PANEL_PUSH_TIME = now
                    print(f"proactive refresh push to panel ({panel_min} min interval)", flush=True)
                    await push_panel_update(advance_page=True)
        except Exception as exc:
            print(f"render loop error: {exc!r}", flush=True)
            FRAMES.error = repr(exc)
        await asyncio.sleep(REFRESH)


def _check_frame_auth(request):
    if not FRAME_TOKEN:
        return
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        provided = auth_hdr[7:].strip()
    else:
        provided = request.query.get("token") or request.headers.get("X-Frame-Token") or ""
    if not hmac.compare_digest(provided, FRAME_TOKEN):
        raise web.HTTPUnauthorized(text="invalid or missing token")


def _frame_headers(f=None, etag=None, page_count=1):
    spec = load_layouts()
    rot_sec = str(spec.get("rotate_seconds", 30))
    panel_cfg = load_panel_setup()
    m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
    panel_int = int(m_int.group(0)) if m_int else 5

    h = {
        "Cache-Control": "no-cache",
        "X-Next-Refresh-Seconds": str(panel_int * 60),
        "X-Rotate-Seconds": rot_sec,
        "X-Page-Count": str(page_count),
    }
    if f is not None:
        h["X-Cat-Count"] = str(f.cat_count)
        h["X-Cat-Offsets"] = ",".join(map(str, f.cat_offsets))
        h["X-Cat-Sizes"] = ",".join(map(str, f.cat_sizes))
        h["X-Cat-Names"] = ",".join(f.cat_names)
    if etag:
        h["ETag"] = etag
    return h


async def frame_png(request):
    _check_frame_auth(request)
    f = FRAMES
    if not f.single:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.single_etag and request.headers.get("If-None-Match") == f.single_etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=f.single_etag, page_count=1))
    return web.Response(body=f.single, content_type="image/png", headers=_frame_headers(f=f, etag=f.single_etag, page_count=1))


async def frames_png(request):
    _check_frame_auth(request)
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.strip_etag and request.headers.get("If-None-Match") == f.strip_etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))
    return web.Response(body=f.strip, content_type="image/png", headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))


async def api_manifest(request):
    _check_frame_auth(request)
    f = FRAMES
    return web.json_response({
        "page_count": len(f.names),
        "cat_count": f.cat_count,
        "cat_offsets": f.cat_offsets,
        "cat_sizes": f.cat_sizes,
        "cat_names": f.cat_names,
        "rendered_at": f.rendered_at,
    })


async def public_status(request):
    _check_frame_auth(request)
    f = FRAMES
    return web.json_response({
        "ok": f.error is None and bool(f.strip),
        "page_count": len(f.names),
        "cat_count": f.cat_count,
        "cat_offsets": f.cat_offsets,
        "cat_sizes": f.cat_sizes,
        "cat_names": f.cat_names,
        "rendered_at": f.rendered_at,
    })


async def editor_strip_png(request):
    """Serve the rendered strip over Ingress without requiring FRAME_TOKEN."""
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.strip, content_type="image/png",
                        headers={"Cache-Control": "no-cache"})


async def status(request):
    f = FRAMES
    spec = load_layouts()
    panel_cfg = load_panel_setup()
    m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
    panel_int = int(m_int.group(0)) if m_int else 5
    return web.json_response({
        "pages": f.names,
        "rendered_at": f.rendered_at,
        "strip_bytes": len(f.strip),
        "cat_count": f.cat_count,
        "cat_offsets": f.cat_offsets,
        "cat_sizes": f.cat_sizes,
        "cat_names": f.cat_names,
        "error": f.error,
        "refresh_seconds": REFRESH,
        "panel_interval": panel_int,
        "esphome_device": ESPHOME_DEVICE,
        "active_alert": ALERT.get("name"),
        "frame_port": FRAME_PORT,
        "display": spec.get("display", T.DEFAULT_DISPLAY),
        "orientation": int(spec.get("orientation") or 0),
    })


async def api_panel_refresh(request):
    """Update panel refresh rate both in saved panel setup and via HA service if online."""
    global LAST_PANEL_PUSH_TIME
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="expected json body")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a json object")
    raw_val = body.get("interval")
    try:
        minutes = max(1, min(60, int(float(raw_val))))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="invalid interval")

    cfg = load_panel_setup()
    cfg["refresh_interval"] = f"{minutes}min"
    save_panel_setup(cfg)

    LAST_PANEL_PUSH_TIME = time.time()

    # Pre-render latest frames immediately so the panel gets fresh data
    try:
        await refresh_frames(SHARED_SESSION)
    except Exception:
        pass

    # Immediately push to the physical panel so the user sees live feedback right away
    ha_updated = await push_panel_update(advance_page=False)

    # Also attempt setting number entity in HA if device has been flashed with dynamic number entity
    candidates = list(dict.fromkeys([
        re.sub(r"[^a-z0-9_]+", "_", cfg.get("device_name", ESPHOME_DEVICE).lower()).strip("_"),
        "crowpanel_epaper",
        "e_paper_panel",
        "epaper_panel"
    ]))
    for slug in candidates:
        entity_id = f"number.{slug}_refresh_interval"
        try:
            await call_ha_service(SHARED_SESSION, "number", "set_value", {
                "entity_id": entity_id,
                "value": minutes
            })
            ha_updated = True
            break
        except Exception:
            pass

    return web.json_response({
        "saved": True,
        "interval": minutes,
        "ha_updated": ha_updated
    })


async def api_layouts_get(request):
    return web.json_response(load_layouts())


async def api_layouts_put(request):
    spec = await request.json()
    if not isinstance(spec, dict) or "pages" not in spec:
        raise web.HTTPBadRequest(text="expected {rotation, pages}")
    try:
        clean = sanitize_layouts(spec)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    save_layouts(clean)
    try:
        await refresh_frames(SHARED_SESSION)
    except Exception as exc:
        print(f"immediate render after save failed: {exc!r}", flush=True)
    return web.json_response({
        "saved": True,
        "display": clean.get("display", T.DEFAULT_DISPLAY),
        "pages": list(clean["pages"]),
        "rotation": clean["rotation"],
        "rotate_seconds": clean["rotate_seconds"],
        "orientation": clean["orientation"],
    })


async def api_entities(request):
    """Entity list for the picker. Cached briefly -- it is a big response."""
    if not HA_TOKEN:
        states = load_fixture().get("states", {})
        items = sorted(
            ({"entity_id": eid,
              "name": info.get("friendly_name") or eid,
              "state": info.get("state"),
              "unit": info.get("unit") or ""}
             for eid, info in states.items()),
            key=lambda e: e["entity_id"])
        return web.json_response(items)

    if time.time() - _entity_cache["at"] < 60 and _entity_cache["items"]:
        return web.json_response(_entity_cache["items"])
    try:
        states = await ha_json(SHARED_SESSION, "/states")
    except Exception as exc:
        return web.json_response({"error": repr(exc)}, status=502)
    items = sorted(
        ({"entity_id": s["entity_id"],
          "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"],
          "state": s.get("state"),
          "unit": (s.get("attributes") or {}).get("unit_of_measurement") or ""}
         for s in states if isinstance(s, dict) and "entity_id" in s),
        key=lambda e: e["entity_id"])
    _entity_cache.update(at=time.time(), items=items)
    return web.json_response(items)


async def api_attributes(request):
    """Attribute names and sample values for one entity."""
    eid = (request.query.get("entity") or "").strip()
    if not valid_entity_id(eid):
        return web.json_response([])

    if not HA_TOKEN:
        attrs = dict((load_fixture().get("states") or {}).get(eid) or {})
        attrs.pop("state", None)
    else:
        safe_eid = urllib.parse.quote(eid, safe=".")
        try:
            st = await ha_json(SHARED_SESSION, f"/states/{safe_eid}")
        except Exception:
            return web.json_response([])
        attrs = st.get("attributes") or {}

    out = []
    for k, v in attrs.items():
        if v is None:
            continue
        kind = "list" if isinstance(v, (list, tuple)) else \
               "object" if isinstance(v, dict) else "value"
        out.append({"name": str(k), "sample": str(v)[:60], "kind": kind})
    return web.json_response(sorted(out, key=lambda a: a["name"]))


async def api_preview(request):
    """Render one page spec through the real engine, so WYSIWYG cannot lie."""
    body = await request.json()
    page = body.get("page") or {}
    try:
        orient = int(body.get("orientation") if "orientation" in body else load_layouts().get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = body.get("display") or load_layouts().get("display", T.DEFAULT_DISPLAY)
    tpls = layout.collect_templates(page)
    vals = await resolve_templates(SHARED_SESSION, tpls) if tpls else {}
    await enrich_page_values(SHARED_SESSION, page, vals)
    series = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") == "curve" and el.get("entity"):
            series[i] = await curve_series(SHARED_SESSION, el["entity"],
                                           int(el.get("hours", 24)))
    metrics = []
    try:
        dist = float(body.get("distance") or 3.0)
    except (TypeError, ValueError):
        dist = 3.0
    img = await asyncio.to_thread(
        layout.render_page, page, vals,
        clock=datetime.now().strftime("%H:%M"),
        label=str(body.get("label") or "preview")[:40],
        battery_pct=None, series=series, metrics=metrics, orientation=orient,
        distance_m=dist, display=display)
    # Effective font sizes ride back on a header so the editor can report
    # what you actually got, in millimetres, rather than what you asked for.
    return web.Response(body=_png(T.to_1bit(img)), content_type="image/png",
                        headers={"X-Metrics": json.dumps(metrics)})


async def api_aircraft(request):
    try:
        radius = float(request.query.get("radius") or 35.0)
    except (TypeError, ValueError):
        radius = 35.0
    aircraft = await fetch_overhead_aircraft(SHARED_SESSION, radius_km=radius)
    return web.json_response({"aircraft": aircraft, "count": len(aircraft)})


async def api_push(request):
    """Re-render immediately and make the panel fetch and redraw now."""
    try:
        await refresh_frames(SHARED_SESSION)
    except Exception as exc:
        print(f"pre-push render failed: {exc!r}", flush=True)
    await call_ha_service(SHARED_SESSION, "esphome", f"{ESPHOME_DEVICE}_refresh_now")
    return web.json_response({"pushed": True})


async def api_action_refresh(request):
    """External action endpoint (for HA automations, webhooks, or scripts) to trigger re-render & panel redraw."""
    _check_frame_auth(request)
    try:
        await refresh_frames(SHARED_SESSION)
        ha_pushed = await push_panel_update(advance_page=False)
        return web.json_response({"success": True, "action": "refresh", "ha_pushed": ha_pushed, "timestamp": datetime.now().isoformat()})
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=500)


async def api_action_page(request):
    """External action endpoint to advance or set the display page."""
    _check_frame_auth(request)
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    try:
        delta = int(body.get("delta") if "delta" in body else (request.query.get("delta") or 1))
    except (TypeError, ValueError):
        delta = 1
    ha_stepped = await step_panel_page(delta=delta)
    return web.json_response({"success": True, "action": "page_step", "delta": delta, "ha_stepped": ha_stepped})


async def api_sources_get(request):
    return web.json_response(feeds.mask_secrets(load_sources()))


async def api_sources_put(request):
    body = await request.json()
    if not isinstance(body, list):
        raise web.HTTPBadRequest(text="expected a list of sources")
    merged = feeds.unmask_secrets(body, load_sources())
    feeds.save(DATA_DIR, merged)
    return web.json_response({"saved": True, "count": len(merged),
                              "sources": feeds.mask_secrets(merged)})


async def api_sources_test(request):
    """Run one source now and report what it would publish."""
    src = await request.json()
    if not isinstance(src, dict):
        raise web.HTTPBadRequest(text="expected a source object")
    unmasked = feeds.unmask_secrets([src], load_sources())
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": SHARED_SESSION}
    rows = await feeds.run_all(unmasked, ctx)
    return web.json_response({"published": [{"entity_id": e, "state": str(v)[:120],
                                             "attributes": a} for e, v, a in rows]})


def _new_api_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _new_ota_password() -> str:
    return secrets.token_urlsafe(12)


def load_panel_setup(default_host: str = "homeassistant.local") -> dict:
    """Load or initialize the ESPHome panel setup wizard state."""
    cfg = {}
    if PANEL_SETUP_PATH.exists():
        try:
            cfg = json.loads(PANEL_SETUP_PATH.read_text())
        except Exception:
            cfg = {}
    changed = False
    defaults = {
        "device_name": ESPHOME_DEVICE.replace("_", "-"),
        "display": load_layouts().get("display", T.DEFAULT_DISPLAY),
        "ha_host": default_host,
        "wifi_ssid": "",
        "wifi_password": "",
        "api_encryption_key": _new_api_key(),
        "ota_password": _new_ota_password(),
        "refresh_interval": "5min",
        "use_secrets": False,
    }
    for k, v in defaults.items():
        if not cfg.get(k) and k not in ("wifi_ssid", "wifi_password", "use_secrets"):
            cfg[k] = v
            changed = True
        elif k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        save_panel_setup(cfg)
    return cfg


def save_panel_setup(cfg: dict) -> dict:
    global ESPHOME_DEVICE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dev = re.sub(r"[^a-z0-9-]+", "-", str(cfg.get("device_name") or "crowpanel-epaper").strip().lower()).strip("-")
    cfg["device_name"] = dev or "crowpanel-epaper"
    ESPHOME_DEVICE = cfg["device_name"].replace("-", "_")
    tmp = PANEL_SETUP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(PANEL_SETUP_PATH)
    return cfg


def _yaml_str(s: str) -> str:
    escaped = str(s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def generate_esphome_yaml(cfg: dict) -> tuple[str, str]:
    """Build ready-to-flash crowpanel-epaper.yaml and companion secrets.yaml."""
    display_id = cfg.get("display") or load_layouts().get("display", T.DEFAULT_DISPLAY)
    disp = T.get_display(display_id)
    dw, dh = disp["w"], disp["h"]
    dev_name = cfg.get("device_name") or "crowpanel-epaper"
    raw_host = (cfg.get("ha_host") or "homeassistant.local").strip()
    port = cfg.get("frame_port") or FRAME_PORT
    if raw_host.startswith(("http://", "https://")):
        parsed = urllib.parse.urlsplit(raw_host)
        host_only = parsed.hostname or "homeassistant.local"
        if parsed.port:
            port = parsed.port
        scheme = parsed.scheme
    else:
        if ":" in raw_host:
            parts = raw_host.split(":")
            host_only = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                pass
        else:
            host_only = raw_host.split("/")[0] or "homeassistant.local"
        scheme = "http"

    base_url = f"{scheme}://{host_only}:{port}"
    token_q = f"?token={urllib.parse.quote(FRAME_TOKEN)}" if FRAME_TOKEN else ""
    frames_url = f"{base_url}/frames.png{token_q}"
    frame_url = f"{base_url}/frame.png{token_q}"

    use_secrets = bool(cfg.get("use_secrets"))
    ssid = (cfg.get("wifi_ssid") or "").strip()
    pw = cfg.get("wifi_password") or ""
    api_key = (cfg.get("api_encryption_key") or "").strip() or _new_api_key()
    ota_pw = (cfg.get("ota_password") or "").strip() or _new_ota_password()
    raw_interval = cfg.get("refresh_interval") or "5min"
    m_int = re.search(r"\d+", str(raw_interval))
    initial_min = max(1, min(60, int(m_int.group(0)))) if m_int else 5
    interval = f"{initial_min}min"
    try:
        orient = int(cfg.get("orientation") if "orientation" in cfg else load_layouts().get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0

    if orient in (180, 270):
        next_pin, prev_pin = 6, 4
        top_btn_pin = 1
        bot_btn_pin = 2
    else:
        next_pin, prev_pin = 4, 6
        top_btn_pin = 2
        bot_btn_pin = 1

    disp_margin = disp["margin"] if dw >= 400 else min(disp["margin"], 16)
    cat_vx0 = 96 if dw >= 400 else (disp_margin + 55)
    sub_w = 48
    sub_vx1 = dw - disp_margin
    sub_vx0 = sub_vx1 - sub_w
    pill_vy0 = dh - 28
    pill_vy1 = dh - 4

    api_key_line = "!secret api_encryption_key" if use_secrets else _yaml_str(api_key)
    ota_pw_line = "!secret ota_password" if use_secrets else _yaml_str(ota_pw)
    if use_secrets or not ssid:
        wifi_ssid_line = "!secret wifi_ssid"
        wifi_pw_line = "!secret wifi_password"
    else:
        wifi_ssid_line = _yaml_str(ssid)
        wifi_pw_line = _yaml_str(pw)

    pin_drawing_code = f"""        const int off = ${{page_h}} * id(page);
        bool is_sub_mode = id(sub_mode);
        const int py0 = {pill_vy0}, py1 = {pill_vy1};
        const int sub_x0 = {sub_vx0}, sub_x1 = {sub_vx1};

        int c_idx = id(cat_idx);
        int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
        if (sz <= 1) {{
          is_sub_mode = false;
        }}

        int cat_w = (c_idx < id(cat_pill_widths).size()) ? id(cat_pill_widths)[c_idx] : 110;
        int cat_x0 = {cat_vx0};
        int cat_x1 = cat_x0 + cat_w;

        // 1. Fast direct blit of page pixels from frames buffer: ~8 ms
        for (int y = 0; y < ${{page_h}}; y++) {{
          for (int x = 0; x < {dw}; x++) {{
            it.draw_pixel_at(x, y, id(frames).get_pixel(x, y + off));
          }}
        }}

        auto in_rounded_box = [](int px, int py, int x0, int y0, int x1, int y1, int r) -> bool {{
          if (px < x0 || px > x1 || py < y0 || py > y1) return false;
          if (px < x0 + r && py < y0 + r) {{
            int dx = (x0 + r) - px, dy = (y0 + r) - py;
            return (dx * dx + dy * dy <= r * r);
          }}
          if (px > x1 - r && py < y0 + r) {{
            int dx = px - (x1 - r), dy = (y0 + r) - py;
            return (dx * dx + dy * dy <= r * r);
          }}
          if (px < x0 + r && py > y1 - r) {{
            int dx = (x0 + r) - px, dy = py - (y1 - r);
            return (dx * dx + dy * dy <= r * r);
          }}
          if (px > x1 - r && py > y1 - r) {{
            int dx = px - (x1 - r), dy = py - (y1 - r);
            return (dx * dx + dy * dy <= r * r);
          }}
          return true;
        }};

        // 2. Invert ONLY the active pill (Category in Category mode; Sub in Sub mode): <1 ms
        if (!is_sub_mode) {{
          for (int py = py0; py <= py1; py++) {{
            for (int px = cat_x0; px <= cat_x1; px++) {{
              if (in_rounded_box(px, py, cat_x0, py0, cat_x1, py1, 4)) {{
                int rx = ({orient} == 180) ? ({dw - 1} - px) : px;
                int ry = ({orient} == 180) ? ({dh - 1} - py) : py;
                if (rx >= 0 && rx < {dw} && ry >= 0 && ry < {dh}) {{
                  Color c = id(frames).get_pixel(rx, ry + off);
                  it.draw_pixel_at(rx, ry, (c == COLOR_ON) ? COLOR_OFF : COLOR_ON);
                }}
              }}
            }}
          }}
        }} else if (sz > 1) {{
          for (int py = py0; py <= py1; py++) {{
            for (int px = sub_x0; px <= sub_x1; px++) {{
              if (in_rounded_box(px, py, sub_x0, py0, sub_x1, py1, 4)) {{
                int rx = ({orient} == 180) ? ({dw - 1} - px) : px;
                int ry = ({orient} == 180) ? ({dh - 1} - py) : py;
                if (rx >= 0 && rx < {dw} && ry >= 0 && ry < {dh}) {{
                  Color c = id(frames).get_pixel(rx, ry + off);
                  it.draw_pixel_at(rx, ry, (c == COLOR_ON) ? COLOR_OFF : COLOR_ON);
                }}
              }}
            }}
          }}
        }}

        // 3. Apple-grade high-contrast solid padlock badge (22x20px)
        auto draw_lock_badge = [&](int bx, int by, int bw, int bh) {{
          int cx = bx + bw / 2;
          int cy = by + bh / 2;
          for (int py = by; py < by + bh; py++) {{
            for (int px = bx; px < bx + bw; px++) {{
              if (in_rounded_box(px, py, bx, by, bx + bw - 1, by + bh - 1, 4)) {{
                int dx = px - cx;
                int dy = py - cy;
                bool is_shackle = false;
                if (dy >= -6 && dy <= -2) {{
                  if (dy <= -4) {{
                    is_shackle = (dx >= -4 && dx <= 3);
                  }} else {{
                    is_shackle = (dx >= -5 && dx <= -3) || (dx >= 2 && dx <= 4);
                  }}
                }}
                bool is_body = (dy >= -1 && dy <= 6 && dx >= -6 && dx <= 5);
                bool is_keyhole = false;
                if ((dy >= 1 && dy <= 2 && dx >= -1 && dx <= 0) || (dy >= 3 && dy <= 4 && dx == 0)) {{
                  is_keyhole = true;
                }}

                Color col = COLOR_ON;
                if ((is_shackle || is_body) && !is_keyhole) {{
                  col = COLOR_OFF;
                }}

                int rx = ({orient} == 180) ? ({dw - 1} - px) : px;
                int ry = ({orient} == 180) ? ({dh - 1} - py) : py;
                if (rx >= 0 && rx < {dw} && ry >= 0 && ry < {dh}) {{
                  it.draw_pixel_at(rx, ry, col);
                }}
              }}
            }}
          }}
        }};

        if (id(cat_pinned)) {{
          draw_lock_badge(cat_x1 + 8, py0 + 2, 22, 20);
        }}

        if (id(pinned)) {{
          int lx = (sz > 1) ? (sub_x0 - 8 - 22) : ({sub_vx1} - 22);
          draw_lock_badge(lx, py0 + 2, 22, 20);
        }}"""

    if disp["esphome_component"].startswith("github://"):
        ext_comp_block = f"""external_components:
  - source: {disp["esphome_component"]}
"""
        display_platform_block = f"""display:
  - platform: crowpanel_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    clk_pin: 12
    mosi_pin: 11
    cs_pin: 45
    dc_pin: 46
    reset_pin: 47
    busy_pin: 48
    invert_colors: true
    full_update_every: 10
    update_interval: never
    auto_clear_enabled: false"""
    else:
        ext_comp_block = ""
        display_platform_block = f"""display:
  - platform: waveshare_epaper
    id: epd
    model: "{disp["esphome_model"]}"
    cs_pin: 45
    dc_pin: 46
    busy_pin: 48
    reset_pin: 47
    reset_duration: 2ms
    update_interval: never
    auto_clear_enabled: false"""

    yaml_text = f"""# {disp["name"]} ({disp["sku"]}, {dw}x{dh}) e-paper panel — generated by the E-paper add-on wizard.
# Paste into ESPHome Dashboard (New Device -> Edit -> Install).

substitutions:
  name: {dev_name}
  frames_url: {_yaml_str(frames_url)}
  frame_url:  {_yaml_str(frame_url)}
  page_h: "{dh}"

esphome:
  name: ${{name}}
  friendly_name: E-paper panel
  on_boot:
    priority: -100
    then:
      - script.execute: refetch

esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: esp-idf

psram:
  mode: octal
  speed: 80MHz

{ext_comp_block}globals:
  - id: have_frames
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: have_single
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: page
    type: int
    restore_value: false
    initial_value: '0'
  - id: page_count
    type: int
    restore_value: false
    initial_value: '1'
  - id: pinned
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: cat_idx
    type: int
    restore_value: false
    initial_value: '0'
  - id: sub_idx
    type: int
    restore_value: false
    initial_value: '0'
  - id: cat_pinned
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: cat_count
    type: int
    restore_value: false
    initial_value: '1'
  - id: cat_offsets
    type: std::vector<int>
    restore_value: false
  - id: cat_sizes
    type: std::vector<int>
    restore_value: false
  - id: cat_pill_widths
    type: std::vector<int>
    restore_value: false
  - id: sub_mode
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: idle_sec
    type: int
    restore_value: false
    initial_value: '0'
  - id: last_ok_press_ms
    type: uint32_t
    restore_value: false
    initial_value: '0'

font:
  - file: "gfonts://Lato@700"
    id: diag_big
    size: 56
  - file: "gfonts://Lato@400"
    id: diag_small
    size: 26

logger:

api:
  encryption:
    key: {api_key_line}
  actions:
    - action: refresh_now
      then:
        - script.execute: refetch
    - action: show_page
      variables:
        index: int
      then:
        - lambda: |-
            if (index >= 0 && index < id(page_count)) {{
              id(page) = index;
              for (int c = (int)id(cat_offsets).size() - 1; c >= 0; c--) {{
                if (index >= id(cat_offsets)[c]) {{
                  id(cat_idx) = c;
                  id(sub_idx) = index - id(cat_offsets)[c];
                  break;
                }}
              }}
            }}
        - script.execute: redraw
    - action: show_category
      variables:
        category: int
        sub: int
      then:
        - lambda: |-
            int cats = id(cat_count) > 0 ? id(cat_count) : 1;
            if (category >= 0 && category < cats) {{
              id(cat_idx) = category;
              int sz = (category < id(cat_sizes).size()) ? id(cat_sizes)[category] : 1;
              id(sub_idx) = (sub >= 0 && sub < sz) ? sub : 0;
              int off = (category < id(cat_offsets).size()) ? id(cat_offsets)[category] : category;
              int p = off + id(sub_idx);
              if (p < id(page_count)) id(page) = p;
            }}
        - script.execute: redraw
    - action: page_step
      variables:
        delta: int
      then:
        - lambda: |-
            id(idle_sec) = 0;
            int cats = id(cat_count) > 0 ? id(cat_count) : 1;
            if (id(cat_idx) >= cats) id(cat_idx) = 0;

            if (id(sub_mode)) {{
              int c_idx = id(cat_idx);
              int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
              if (sz > 1) {{
                id(sub_idx) = ((id(sub_idx) + delta) % sz + sz) % sz;
                int off = (c_idx < id(cat_offsets).size()) ? id(cat_offsets)[c_idx] : c_idx;
                int p = off + id(sub_idx);
                if (p < id(page_count)) id(page) = p;
              }}
            }} else {{
              id(cat_idx) = ((id(cat_idx) + delta) % cats + cats) % cats;
              id(sub_idx) = 0;
              id(sub_mode) = false;
              int off = (id(cat_idx) < id(cat_offsets).size()) ? id(cat_offsets)[id(cat_idx)] : id(cat_idx);
              if (off < id(page_count)) id(page) = off;
            }}
        - script.execute: redraw
    - action: mode_toggle
      then:
        - lambda: |-
            id(idle_sec) = 0;
            int c_idx = id(cat_idx);
            int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
            if (sz > 1) {{
              id(sub_mode) = !id(sub_mode);
              ESP_LOGI("panel", "Navigation mode toggled: sub_mode=%d (sz=%d)", id(sub_mode), sz);
            }} else {{
              id(sub_mode) = false;
              ESP_LOGI("panel", "Single-page category (sz=%d), staying in category mode", sz);
            }}
        - script.execute: redraw
    - action: category_step
      variables:
        delta: int
      then:
        - lambda: |-
            id(idle_sec) = 0;
            int cats = id(cat_count) > 0 ? id(cat_count) : 1;
            id(cat_idx) = ((id(cat_idx) + delta) % cats + cats) % cats;
            id(sub_idx) = 0;
            id(sub_mode) = false;
            int off = (id(cat_idx) < id(cat_offsets).size()) ? id(cat_offsets)[id(cat_idx)] : id(cat_idx);
            if (off < id(page_count)) id(page) = off;
        - script.execute: redraw
    - action: sub_step
      variables:
        delta: int
      then:
        - lambda: |-
            id(idle_sec) = 0;
            int c_idx = id(cat_idx);
            int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
            if (sz > 1) {{
              id(sub_idx) = ((id(sub_idx) + delta) % sz + sz) % sz;
              int off = (c_idx < id(cat_offsets).size()) ? id(cat_offsets)[c_idx] : c_idx;
              int p = off + id(sub_idx);
              if (p < id(page_count)) id(page) = p;
            }}
        - script.execute: redraw
    - action: hold_toggle
      then:
        - lambda: |-
            id(idle_sec) = 0;
            id(pinned) = !id(pinned);
            if (id(pinned)) id(cat_pinned) = false;
            ESP_LOGI("panel", "Panel lock: %d", id(pinned));
        - script.execute: redraw
    - action: category_pin_toggle
      then:
        - lambda: |-
            id(idle_sec) = 0;
            id(cat_pinned) = !id(cat_pinned);
            if (id(cat_pinned)) id(pinned) = false;
            ESP_LOGI("panel", "Category lock: %d", id(cat_pinned));
        - script.execute: redraw
    - action: lock_toggle
      then:
        - lambda: |-
            id(idle_sec) = 0;
            if (id(sub_mode)) {{
              id(pinned) = !id(pinned);
              if (id(pinned)) id(cat_pinned) = false;
              ESP_LOGI("panel", "Contextual lock (sub_mode): panel lock=%d", id(pinned));
            }} else {{
              id(cat_pinned) = !id(cat_pinned);
              if (id(cat_pinned)) id(pinned) = false;
              ESP_LOGI("panel", "Contextual lock (cat_mode): cat lock=%d", id(cat_pinned));
            }}
        - script.execute: redraw

ota:
  - platform: esphome
    password: {ota_pw_line}

wifi:
  ssid: {wifi_ssid_line}
  password: {wifi_pw_line}
  fast_connect: true

switch:
  - platform: gpio
    pin: 7
    id: epd_power
    restore_mode: ALWAYS_ON
    internal: true

{display_platform_block}
    lambda: |-
      if (id(have_frames)) {{
{pin_drawing_code}
      }} else if (id(have_single)) {{
        it.image(0, 0, id(frame));
      }} else {{
        it.print(40, 40, id(diag_big), "panel alive");
        it.printf(40, 130, id(diag_small), "ip: %s", id(wifi_ip).state.c_str());
        it.printf(40, 170, id(diag_small), "waiting for %s", "frames.png");
      }}

http_request:
  verify_ssl: false
  timeout: 15s
  buffer_size_rx: 8192

online_image:
  - id: frames
    url: ${{frames_url}}
    format: png
    type: BINARY
    buffer_size: 32768
    on_download_finished:
      - lambda: |-
          int h = id(frames).get_height();
          id(page_count) = (h >= ${{page_h}}) ? h / ${{page_h}} : 1;
          if (id(page) >= id(page_count)) id(page) = 0;
          id(have_frames) = true;

          // Check if self-describing metadata row is present (height == page_count * page_h + 1)
          if (h >= id(page_count) * ${{page_h}} + 1) {{
            int meta_y = id(page_count) * ${{page_h}};
            auto read_byte = [&](int byte_idx) -> int {{
              int val = 0;
              int start_px = byte_idx * 8;
              for (int b = 0; b < 8; b++) {{
                if (start_px + b < {dw}) {{
                  // Bit 1 was written as 0 (black in PNG, red < 128 in get_pixel)
                  if (id(frames).get_pixel(start_px + b, meta_y).red < 128) {{
                    val |= (1 << (7 - b));
                  }}
                }}
              }}
              return val;
            }};

            int magic = read_byte(0);
            if (magic == 0xA5) {{
              int num_cats = read_byte(2);
              if (num_cats > 0 && num_cats <= 30) {{
                id(cat_offsets).clear();
                id(cat_sizes).clear();
                id(cat_pill_widths).clear();
                id(cat_count) = num_cats;
                for (int i = 0; i < num_cats; i++) {{
                  int off = read_byte(3 + i * 3);
                  int sz = read_byte(3 + i * 3 + 1);
                  int pw = read_byte(3 + i * 3 + 2);
                  id(cat_offsets).push_back(off);
                  id(cat_sizes).push_back(sz);
                  id(cat_pill_widths).push_back(pw > 0 ? pw : 110);
                }}
                ESP_LOGI("panel", "Loaded metadata directly from frames.png: %d categories", num_cats);
              }}
            }}
          }}

          if (id(cat_offsets).empty() || id(cat_count) <= 0) {{
            id(cat_offsets).clear();
            id(cat_sizes).clear();
            id(cat_pill_widths).clear();
            id(cat_count) = id(page_count);
            for (int i = 0; i < id(page_count); i++) {{
              id(cat_offsets).push_back(i);
              id(cat_sizes).push_back(1);
              id(cat_pill_widths).push_back(110);
            }}
          }}
          if (id(cat_idx) >= id(cat_count)) id(cat_idx) = 0;
          ESP_LOGI("panel", "%d pages (%d categories) held locally", id(page_count), id(cat_count));
      - if:
          condition:
            lambda: 'return (id(idle_sec) > 30);'
          then:
            - component.update: epd
    on_error:
      - logger.log: "frames.png missing - falling back to single frame"
      - component.update: frame

  - id: frame
    url: ${{frame_url}}
    format: png
    type: BINARY
    buffer_size: 32768
    on_download_finished:
      - lambda: 'id(have_single) = true;'
      - component.update: epd
    on_error:
      - logger.log: "frame.png failed too - retrying in 20s"
      - component.update: epd
      - delay: 20s
      - script.execute: refetch

binary_sensor:
  - platform: gpio
    id: key_next
    internal: true
    pin: {{number: {next_pin}, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 25ms, delayed_off: 25ms]
    on_press:
      - logger.log: "KEY next (dial forward)"
      - lambda: |-
          id(idle_sec) = 0;
          int cats = id(cat_count) > 0 ? id(cat_count) : 1;
          if (id(cat_idx) >= cats) id(cat_idx) = 0;

          if (id(sub_mode)) {{
            int c_idx = id(cat_idx);
            int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
            if (sz > 1) {{
              id(sub_idx) = (id(sub_idx) + 1) % sz;
              int off = (c_idx < id(cat_offsets).size()) ? id(cat_offsets)[c_idx] : c_idx;
              int p = off + id(sub_idx);
              if (p < id(page_count)) id(page) = p;
            }}
          }} else {{
            id(cat_idx) = (id(cat_idx) + 1) % cats;
            id(sub_idx) = 0;
            id(sub_mode) = false;
            int off = (id(cat_idx) < id(cat_offsets).size()) ? id(cat_offsets)[id(cat_idx)] : id(cat_idx);
            if (off < id(page_count)) id(page) = off;
          }}
      - script.execute: redraw

  - platform: gpio
    id: key_prev
    internal: true
    pin: {{number: {prev_pin}, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 25ms, delayed_off: 25ms]
    on_press:
      - logger.log: "KEY prev (dial backward)"
      - lambda: |-
          id(idle_sec) = 0;
          int cats = id(cat_count) > 0 ? id(cat_count) : 1;
          if (id(cat_idx) >= cats) id(cat_idx) = 0;

          if (id(sub_mode)) {{
            int c_idx = id(cat_idx);
            int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
            if (sz > 1) {{
              id(sub_idx) = (id(sub_idx) - 1 + sz) % sz;
              int off = (c_idx < id(cat_offsets).size()) ? id(cat_offsets)[c_idx] : c_idx;
              int p = off + id(sub_idx);
              if (p < id(page_count)) id(page) = p;
            }}
          }} else {{
            id(cat_idx) = (id(cat_idx) - 1 + cats) % cats;
            id(sub_idx) = 0;
            id(sub_mode) = false;
            int off = (id(cat_idx) < id(cat_offsets).size()) ? id(cat_offsets)[id(cat_idx)] : id(cat_idx);
            if (off < id(page_count)) id(page) = off;
          }}
      - script.execute: redraw

  - platform: gpio
    id: key_ok
    internal: true
    pin: {{number: 5, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 30ms, delayed_off: 30ms]
    on_click:
      - min_length: 1000ms
        max_length: 5000ms
        then:
          - logger.log: "KEY ok: long hold (toggle category vs sub-item mode)"
          - lambda: |-
              id(idle_sec) = 0;
              int c_idx = id(cat_idx);
              int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
              if (sz > 1) {{
                id(sub_mode) = !id(sub_mode);
                ESP_LOGI("panel", "Navigation mode toggled: sub_mode=%d (sz=%d)", id(sub_mode), sz);
              }} else {{
                id(sub_mode) = false;
                ESP_LOGI("panel", "Category has single page (sz=%d), staying in category mode", sz);
              }}
          - script.execute: redraw

  - platform: gpio
    id: key_top
    internal: true
    pin: {{number: {top_btn_pin}, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 25ms, delayed_off: 25ms]
    on_click:
      - min_length: 30ms
        max_length: 750ms
        then:
          - logger.log: "KEY top: short click (toggle category lock)"
          - lambda: |-
              id(idle_sec) = 0;
              id(cat_pinned) = !id(cat_pinned);
              if (id(cat_pinned)) id(pinned) = false;
              ESP_LOGI("panel", "Category lock: %d", id(cat_pinned));
          - script.execute: redraw
      - min_length: 750ms
        max_length: 6000ms
        then:
          - logger.log: "KEY top: long hold (toggle panel lock)"
          - lambda: |-
              id(idle_sec) = 0;
              id(pinned) = !id(pinned);
              if (id(pinned)) id(cat_pinned) = false;
              ESP_LOGI("panel", "Panel lock: %d", id(pinned));
          - script.execute: redraw

  - platform: gpio
    id: key_bottom
    internal: true
    pin: {{number: {bot_btn_pin}, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 25ms, delayed_off: 25ms]
    on_click:
      - min_length: 30ms
        max_length: 750ms
        then:
          - logger.log: "KEY bottom: short click (reset to first page)"
          - lambda: |-
              id(idle_sec) = 0;
              id(cat_idx) = 0;
              id(sub_idx) = 0;
              id(page) = 0;
              id(sub_mode) = false;
              ESP_LOGI("panel", "Reset to page 0");
          - script.execute: redraw
      - min_length: 750ms
        max_length: 6000ms
        then:
          - logger.log: "KEY bottom: long hold (force refetch)"
          - lambda: 'id(idle_sec) = 0;'
          - script.execute: refetch

sensor:
  - platform: wifi_signal
    id: wifi_rssi
    name: Panel Wi-Fi
    update_interval: 60s

  - platform: homeassistant
    id: ha_cat_count
    entity_id: sensor.epaper_category_count
    on_value:
      then:
        - lambda: |-
            if (!std::isnan(x) && x > 0) {{
              int n = (int)x;
              id(cat_count) = n;
              if (id(cat_idx) >= n) id(cat_idx) = 0;
            }}

text_sensor:
  - platform: wifi_info
    ip_address:
      id: wifi_ip
      name: Panel IP

  - platform: homeassistant
    id: ha_cat_offsets
    entity_id: sensor.epaper_category_offsets
    on_value:
      then:
        - lambda: |-
            std::vector<int> new_offsets;
            const char *p = x.c_str();
            while (*p) {{
              while (*p == ' ' || *p == ',') p++;
              if (!*p) break;
              char *end;
              long val = strtol(p, &end, 10);
              if (p == end) break;
              new_offsets.push_back((int)val);
              p = end;
            }}
            if (!new_offsets.empty()) {{
              id(cat_offsets) = new_offsets;
            }}

  - platform: homeassistant
    id: ha_cat_sizes
    entity_id: sensor.epaper_category_sizes
    on_value:
      then:
        - lambda: |-
            std::vector<int> new_sizes;
            const char *p = x.c_str();
            while (*p) {{
              while (*p == ' ' || *p == ',') p++;
              if (!*p) break;
              char *end;
              long val = strtol(p, &end, 10);
              if (p == end) break;
              new_sizes.push_back((int)val);
              p = end;
            }}
            if (!new_sizes.empty()) {{
              id(cat_sizes) = new_sizes;
            }}

  - platform: homeassistant
    id: ha_cat_pill_widths
    entity_id: sensor.epaper_category_pill_widths
    on_value:
      then:
        - lambda: |-
            std::vector<int> new_pws;
            const char *p = x.c_str();
            while (*p) {{
              while (*p == ' ' || *p == ',') p++;
              if (!*p) break;
              char *end;
              long val = strtol(p, &end, 10);
              if (p == end) break;
              new_pws.push_back((int)val);
              p = end;
            }}
            if (!new_pws.empty()) {{
              id(cat_pill_widths) = new_pws;
            }}

script:
  - id: redraw
    mode: restart
    then:
      - delay: 80ms
      - component.update: epd

  - id: refetch
    mode: single
    then:
      - wait_until:
          condition:
            wifi.connected:
          timeout: 30s
      - component.update: frames

number:
  - platform: template
    name: "Refresh interval"
    id: panel_refresh_interval
    icon: "mdi:timer-outline"
    optimistic: true
    min_value: 1
    max_value: 60
    step: 1
    initial_value: {initial_min}
    restore_value: true
    unit_of_measurement: "min"
    mode: box

interval:
  - interval: 10s
    then:
      - lambda: |-
          id(idle_sec) += 10;
      - if:
          condition:
            lambda: |-
              int target_sec = (int)(id(panel_refresh_interval).state * 60.0);
              if (target_sec < 10) target_sec = 10;
              return (id(idle_sec) >= target_sec);
          then:
            - lambda: |-
                id(idle_sec) = 0;
            - if:
                condition:
                  lambda: 'return !id(pinned);'
                then:
                  - if:
                      condition:
                        lambda: 'return id(cat_pinned);'
                      then:
                        - lambda: |-
                            int c_idx = id(cat_idx);
                            int sz = (c_idx < id(cat_sizes).size()) ? id(cat_sizes)[c_idx] : 1;
                            if (sz > 1) {{
                              id(sub_idx) = (id(sub_idx) + 1) % sz;
                              int off = (c_idx < id(cat_offsets).size()) ? id(cat_offsets)[c_idx] : c_idx;
                              int p = off + id(sub_idx);
                              if (p < id(page_count)) id(page) = p;
                            }}
                        - script.execute: redraw
                      else:
                        - lambda: |-
                            int cats = id(cat_count) > 0 ? id(cat_count) : 1;
                            id(cat_idx) = (id(cat_idx) + 1) % cats;
                            id(sub_idx) = 0;
                            id(sub_mode) = false;
                            int off = (id(cat_idx) < id(cat_offsets).size()) ? id(cat_offsets)[id(cat_idx)] : id(cat_idx);
                            if (off < id(page_count)) id(page) = off;
                        - script.execute: redraw
            - script.execute: refetch
"""

    secrets_text = f"""# Put these in your ESPHome secrets.yaml if using !secret references:
wifi_ssid: {_yaml_str(ssid or "your-wifi-ssid")}
wifi_password: {_yaml_str(pw or "your-wifi-password")}
api_encryption_key: {_yaml_str(api_key)}
ota_password: {_yaml_str(ota_pw)}
"""
    return yaml_text, secrets_text


async def _detect_panel_connection(device_slug: str) -> dict:
    """Check whether Home Assistant sees the ESPHome panel entities."""
    slug = re.sub(r"[^a-z0-9_]+", "_", device_slug.lower()).strip("_")
    ip_val, rssi_val = None, None
    if not HA_TOKEN:
        panel_fix = load_fixture().get("panel") or {}
        return {"connected": False, "ip": None, "rssi": panel_fix.get("rssi")}
    try:
        states = await ha_json(SHARED_SESSION, "/states")
        for s in states:
            if not isinstance(s, dict):
                continue
            eid = s.get("entity_id", "")
            st = s.get("state")
            if st in (None, "unknown", "unavailable", ""):
                continue
            if eid in (f"sensor.{slug}_panel_ip", "sensor.panel_ip", f"text_sensor.{slug}_panel_ip"):
                ip_val = st
            elif eid in (f"sensor.{slug}_panel_wi_fi", "sensor.panel_wi_fi"):
                rssi_val = st
    except Exception:
        pass
    return {"connected": bool(ip_val or rssi_val), "ip": ip_val, "rssi": rssi_val}


async def _detect_external_port(session: aiohttp.ClientSession | None = None) -> int:
    if not HA_TOKEN:
        return FRAME_PORT
    try:
        sess = session or SHARED_SESSION
        if sess:
            async with sess.get(
                "http://supervisor/addons/self/info",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=2.0)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    net = (data.get("data") or {}).get("network") or {}
                    p = net.get(f"{FRAME_PORT}/tcp") or net.get("8099/tcp")
                    if p:
                        return int(p)
    except Exception as exc:
        print(f"could not query supervisor for external port: {exc!r}", flush=True)
    return FRAME_PORT


async def api_panel_setup_get(request):
    fwd = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or ""
    host_guess = fwd.split(",")[0].strip().split(":")[0]
    if not host_guess or host_guess in ("localhost", "127.0.0.1", "0.0.0.0"):
        host_guess = "homeassistant.local"
    cfg = load_panel_setup(default_host=host_guess)
    detected_port = await _detect_external_port(SHARED_SESSION)
    if "frame_port" not in cfg:
        cfg["frame_port"] = detected_port
    masked_cfg = dict(cfg)
    if masked_cfg.get("wifi_password"):
        masked_cfg["wifi_password"] = feeds.SECRET_MASK
    yaml_text, secrets_text = generate_esphome_yaml(masked_cfg)
    conn = await _detect_panel_connection(cfg["device_name"])
    return web.json_response({
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "frame_port": cfg.get("frame_port", detected_port),
        "has_frame_token": bool(FRAME_TOKEN),
        "panel": conn,
    })


async def api_panel_setup_post(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    cur = load_panel_setup()
    if body.get("regenerate_keys"):
        cur["api_encryption_key"] = _new_api_key()
        cur["ota_password"] = _new_ota_password()
    for k in ("device_name", "ha_host", "wifi_ssid", "refresh_interval", "display"):
        if k in body and isinstance(body[k], str):
            cur[k] = body[k].strip()
    if "frame_port" in body:
        try:
            cur["frame_port"] = int(body["frame_port"])
        except (ValueError, TypeError):
            pass
    if cur.get("display"):
        cur["display"] = T.get_display(cur["display"])["id"]
        try:
            lay = load_layouts()
            if lay.get("display") != cur["display"]:
                lay["display"] = cur["display"]
                save_layouts(lay)
        except Exception:
            pass
    if "use_secrets" in body:
        cur["use_secrets"] = bool(body["use_secrets"])
    if "wifi_password" in body and isinstance(body["wifi_password"], str):
        if body["wifi_password"] != feeds.SECRET_MASK:
            cur["wifi_password"] = body["wifi_password"]
    for k in ("api_encryption_key", "ota_password"):
        if k in body and isinstance(body[k], str) and body[k].strip():
            if not body.get("regenerate_keys"):
                cur[k] = body[k].strip()
    saved = save_panel_setup(cur)
    masked_cfg = dict(saved)
    if masked_cfg.get("wifi_password"):
        masked_cfg["wifi_password"] = feeds.SECRET_MASK
    yaml_cfg = masked_cfg if body.get("wifi_password") == feeds.SECRET_MASK else saved
    yaml_text, secrets_text = generate_esphome_yaml(yaml_cfg)
    conn = await _detect_panel_connection(saved["device_name"])
    return web.json_response({
        "saved": True,
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "frame_port": saved.get("frame_port", FRAME_PORT),
        "has_frame_token": bool(FRAME_TOKEN),
        "panel": conn,
    })


async def panel_font(request):
    """Serve bundled font TTF files on port 8099 so ESPHome and editor can fetch them over LAN."""
    name = request.match_info.get("name", "")
    allowed = (
        "Lato-Bold.ttf", "Lato-Regular.ttf",
        "DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
        "RobotoMono-Variable.ttf",
    )
    if name not in allowed:
        raise web.HTTPNotFound()
    f = Path(__file__).parent / "fonts" / name
    if not f.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "max-age=86400"})


async def api_mdi_font(request):
    f = Path(__file__).parent / "fonts" / "mdi.ttf"
    if not f.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "max-age=86400"})


async def api_mdi_list(request):
    """Icon names and codepoints for the picker, so it can show real glyphs."""
    try:
        cps = json.loads((Path(__file__).parent / "fonts" / "mdi-codepoints.json").read_text())
    except Exception:
        return web.json_response([])
    q = (request.query.get("q") or "").strip().lower()
    names = [n for n in cps if q in n] if q else list(cps)
    names.sort(key=lambda n: (len(n), n))
    return web.json_response([{"n": n, "c": cps[n]} for n in names[:400]])


async def api_mdi_all(request):
    """Serve full icon map for client-side instant search and glyph preview."""
    f = Path(__file__).parent / "fonts" / "mdi-codepoints.json"
    if not f.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "public, max-age=86400"})


async def api_displays(request):
    """Catalog of supported CrowPanel e-paper hardware models."""
    return web.json_response({
        "displays": list(T.DISPLAYS.values()),
        "default": T.DEFAULT_DISPLAY,
    })


async def editor_index(request):
    index = WEB_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Editor not built yet.", content_type="text/plain")
    return web.FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


async def start(app_runners):
    panel = web.Application()
    panel.add_routes([
        web.get("/frame.png", frame_png),
        web.get("/frames.png", frames_png),
        web.get("/status", public_status),
        web.get("/manifest.json", api_manifest),
        web.get("/api/manifest", api_manifest),
        web.get("/fonts/{name}", panel_font),
        web.get("/api/action/refresh", api_action_refresh),
        web.post("/api/action/refresh", api_action_refresh),
        web.get("/api/action/page", api_action_page),
        web.post("/api/action/page", api_action_page),
        web.get("/api/layouts", api_layouts_get),
    ])

    editor = web.Application(client_max_size=1024 * 1024)
    editor.add_routes([
        web.get("/", editor_index),
        web.get("/api/status", status),
        web.get("/api/manifest", api_manifest),
        web.get("/api/displays", api_displays),
        web.get("/api/strip.png", editor_strip_png),
        web.get("/api/layouts", api_layouts_get),
        web.put("/api/layouts", api_layouts_put),
        web.get("/api/entities", api_entities),
        web.get("/api/attributes", api_attributes),
        web.get("/api/aircraft", api_aircraft),
        web.post("/api/preview", api_preview),
        web.post("/api/push", api_push),
        web.get("/api/action/refresh", api_action_refresh),
        web.post("/api/action/refresh", api_action_refresh),
        web.get("/api/action/page", api_action_page),
        web.post("/api/action/page", api_action_page),
        web.get("/api/sources", api_sources_get),
        web.put("/api/sources", api_sources_put),
        web.post("/api/sources/test", api_sources_test),
        web.get("/api/panel-setup", api_panel_setup_get),
        web.post("/api/panel-setup", api_panel_setup_post),
        web.post("/api/panel-refresh", api_panel_refresh),
        web.get("/api/mdi/font", api_mdi_font),
        web.get("/api/mdi/list", api_mdi_list),
        web.get("/api/mdi/all", api_mdi_all),
    ])
    if WEB_DIR.exists():
        editor.router.add_static("/static/", WEB_DIR)

    for app, port in ((panel, FRAME_PORT), (editor, INGRESS_PORT)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        app_runners.append(runner)
        print(f"listening on :{port}", flush=True)


async def main():
    global SHARED_SESSION, ESPHOME_DEVICE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PANEL_SETUP_PATH.exists():
        try:
            saved_dev = json.loads(PANEL_SETUP_PATH.read_text()).get("device_name")
            if saved_dev:
                ESPHOME_DEVICE = re.sub(r"[^a-z0-9_]+", "_", saved_dev.lower()).strip("_") or ESPHOME_DEVICE
        except Exception:
            pass
    runners = []
    async with aiohttp.ClientSession() as session:
        SHARED_SESSION = session
        await start(runners)
        try:
            await render_loop()
        finally:
            for r in runners:
                await r.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
