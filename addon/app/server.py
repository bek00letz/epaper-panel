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
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from zoneinfo import ZoneInfo
from pathlib import Path

import aiohttp
from aiohttp import web
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import feeds  # noqa: E402
from render import epf, layout, stripmeta, subitems, theme as T  # noqa: E402

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
    states = dict(load_fixture().get("states", {}))
    for eid, info in _epaper_published_entities.items():
        attrs = dict(info.get("attributes") or {})
        attrs["state"] = info.get("state", "")
        states[eid] = attrs
    s = migrate_legacy_entity_refs(str(tpl or "").strip())

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


LEGACY_ENTITY_MAP = {
    "sensor.overhead_aircraft_count": "sensor.epaper_flights_overhead",
    "sensor.closest_aircraft": "sensor.epaper_closest_aircraft",
    "sensor.f1_status": "sensor.epaper_racing_f1",
    "sensor.formula_e_status": "sensor.epaper_racing_fe",
}

_epaper_published_entities: dict[str, dict] = {}


def migrate_legacy_entity_refs(text: str) -> str:
    """Upgrade legacy non-prefixed add-on sensor names to canonical sensor.epaper_* names."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for old_id, new_id in LEGACY_ENTITY_MAP.items():
        if old_id in out:
            out = out.replace(old_id, new_id)
    # Migrate sensor.sports_<slug> -> sensor.epaper_sports_<slug>
    out = re.sub(r"\bsensor\.sports_([a-z0-9_]+)\b", r"sensor.epaper_sports_\1", out)
    # Also upgrade old racing show_if `states('sensor.epaper_racing_f1') in ['IN', 'PRE']` -> `is_state('sensor.epaper_racing_f1', 'active')`
    out = re.sub(
        r"states\(\s*'(sensor\.epaper_racing_[a-z0-9_]+)'\s*\)\s+in\s+\[\s*'IN'\s*,\s*'PRE'\s*\]",
        r"is_state('\1', 'active')",
        out,
    )
    return out


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
        els = []
        for raw_el in (p.get("elements") or []):
            if not isinstance(raw_el, dict):
                continue
            el = dict(raw_el)
            if isinstance(el.get("entity"), str) and el["entity"]:
                el["entity"] = migrate_legacy_entity_refs(el["entity"].strip())
            if isinstance(el.get("show_if"), str) and el["show_if"]:
                el["show_if"] = migrate_legacy_entity_refs(el["show_if"].strip())
            els.append(el)
        entry = {"tier": tier, "elements": els}
        if p.get("show_if") and isinstance(p.get("show_if"), str):
            entry["show_if"] = migrate_legacy_entity_refs(p["show_if"].strip())
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

    raw_qh = spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}
    qh_start = str(raw_qh.get("start") or "23:00").strip()[:5]
    qh_end = str(raw_qh.get("end") or "07:00").strip()[:5]
    if not re.match(r"^\d{2}:\d{2}$", qh_start):
        qh_start = "23:00"
    if not re.match(r"^\d{2}:\d{2}$", qh_end):
        qh_end = "07:00"
    qh_pres = str(raw_qh.get("presence_entity") or "").strip()
    if qh_pres and not valid_entity_id(qh_pres):
        qh_pres = ""
    quiet_hours = {
        "enabled": bool(raw_qh.get("enabled", False)),
        "start": qh_start,
        "end": qh_end,
        "presence_entity": qh_pres,
        "allow_alerts": bool(raw_qh.get("allow_alerts", True)),
    }

    raw_presets = spec.get("custom_presets")
    custom_presets = []
    if isinstance(raw_presets, list):
        for cp in raw_presets[:50]:
            if isinstance(cp, dict) and cp.get("name") and isinstance(cp.get("elements"), list):
                custom_presets.append({
                    "id": str(cp.get("id") or f"custom_{len(custom_presets)+1}")[:40],
                    "name": str(cp.get("name"))[:60],
                    "desc": str(cp.get("desc") or "Custom saved layout preset")[:140],
                    "tier": cp.get("tier") if cp.get("tier") in ("rotate", "when", "alert") else "rotate",
                    "show_if": migrate_legacy_entity_refs(str(cp.get("show_if") or "").strip()),
                    "elements": [el for el in cp["elements"] if isinstance(el, dict)],
                })

    return {
        "display": disp_id,
        "orientation": orient,
        "rotate_seconds": rot_sec,
        "quiet_hours": quiet_hours,
        "custom_presets": custom_presets,
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


async def publish_entity(session, entity_id, state, attrs=None, register_mqtt=True):
    """Push a computed value into Home Assistant as a real entity and record it for the Studio picker."""
    if not valid_entity_id(entity_id):
        return
    clean_id = entity_id.strip()
    merged_attrs = dict(attrs or {})
    if clean_id.startswith("sensor.epaper_"):
        merged_attrs.setdefault("source", "epaper_studio")
        fn = merged_attrs.get("friendly_name") or clean_id
        if not str(fn).startswith("E-Paper"):
            merged_attrs["friendly_name"] = f"E-Paper · {fn}"
        _epaper_published_entities[clean_id] = {
            "entity_id": clean_id,
            "state": str(state)[:255],
            "attributes": merged_attrs,
            "register_mqtt": register_mqtt,
        }
    if not HA_TOKEN:
        return
    safe_eid = urllib.parse.quote(clean_id, safe=".")
    try:
        await ha_json(session, f"/states/{safe_eid}", method="POST",
                      json={"state": str(state)[:255], "attributes": merged_attrs})
    except Exception as exc:
        print(f"publish {clean_id} failed: {exc!r}", flush=True)


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
        self.epf_strip: bytes = b""
        self.epf_single: bytes = b""
        self.slices: list[bytes] = []
        self.strip_etag = ""
        self.single_etag = ""
        self.epf_strip_etag = ""
        self.epf_single_etag = ""
        self.names: list[str] = []
        self.cat_offsets: list[int] = [0]
        self.cat_sizes: list[int] = [1]
        self.cat_pill_widths: list[int] = [110]
        self.cat_names: list[str] = []
        self.cat_ids: list[int] = []
        self.sub_ids: list[int] = []
        self.cat_count: int = 1
        self.quiet_active: bool = False
        self.quiet_reason: str = "disabled"
        self.rotate_seconds: int = 30
        self.last_modified: str = ""
        self.rendered_at = None
        self.error = None


FRAMES = Frames()

# Which alert page, if any, currently owns the screen.
ALERT = {"name": None, "until": 0.0, "fired": {}}


async def evaluate_quiet_hours(session, spec: dict) -> tuple[bool, str]:
    """Determine if Night / Quiet Hours (Zero-Ghosting Deep Idle) is currently active."""
    qh = spec.get("quiet_hours") if isinstance(spec.get("quiet_hours"), dict) else {}
    enabled = bool(qh.get("enabled", False))
    start_str = str(qh.get("start") or "23:00").strip()[:5]
    end_str = str(qh.get("end") or "07:00").strip()[:5]
    pres_ent = str(qh.get("presence_entity") or "").strip()
    allow_alerts = bool(qh.get("allow_alerts", True))

    active = False
    reason = "disabled"
    if enabled:
        now_t = datetime.now()
        cur_mins = now_t.hour * 60 + now_t.minute
        try:
            sh, sm = [int(x) for x in start_str.split(":")]
            eh, em = [int(x) for x in end_str.split(":")]
            s_mins = sh * 60 + sm
            e_mins = eh * 60 + em
            if s_mins != e_mins:
                in_window = (cur_mins >= s_mins or cur_mins < e_mins) if s_mins > e_mins else (s_mins <= cur_mins < e_mins)
                if in_window:
                    active = True
                    reason = f"schedule ({start_str}–{end_str})"
        except Exception:
            pass

        if not active and pres_ent and valid_entity_id(pres_ent):
            try:
                if HA_TOKEN:
                    safe_eid = urllib.parse.quote(pres_ent, safe=".")
                    st_obj = await ha_json(session, f"/states/{safe_eid}")
                    st_val = str(st_obj.get("state") or "").strip().lower()
                    if st_val in ("not_home", "away", "0", "off"):
                        active = True
                        reason = f"away ({pres_ent}: {st_val})"
            except Exception:
                pass
        if not active:
            reason = "outside quiet window"

    await publish_entity(session, "sensor.epaper_quiet_hours", "active" if active else "inactive", {
        "friendly_name": "E-Paper Quiet Hours",
        "icon": "mdi:weather-night" if active else "mdi:weather-sunny",
        "enabled": enabled,
        "reason": reason,
        "start": start_str,
        "end": end_str,
        "presence_entity": pres_ent,
        "allow_alerts": allow_alerts,
    })
    return active, reason


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



_aircraft_cache = {}
_home_location_cache = {"at": 0.0, "lat": 45.794, "lon": 21.222}
_ha_config_cache = {"at": 0.0, "tz": "Europe/Bucharest"}
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


async def get_home_timezone(session, default="Europe/Bucharest"):
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


async def fetch_overhead_aircraft(session, radius_km=35.0, lat=None, lon=None):
    if lat is not None and lon is not None:
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            lat, lon = await get_home_coordinates(session)
    else:
        lat, lon = await get_home_coordinates(session)

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
        # HA REST API wraps ?return_response=1 in {"service_response": {eid: {"forecast": [...]}}}
        payload = (f_resp.get("service_response") or f_resp.get("response") or f_resp) if isinstance(f_resp, dict) else {}
        forecast_list = None
        if isinstance(payload, dict) and eid in payload and isinstance(payload[eid], dict):
            forecast_list = payload[eid].get("forecast")
        if not isinstance(forecast_list, list) or not forecast_list:
            for f_type in ("twice_daily", "hourly"):
                try:
                    f_resp2 = await ha_json(session, "/services/weather/get_forecasts?return_response=1",
                                            method="POST", json={"entity_id": eid, "type": f_type})
                    p2 = (f_resp2.get("service_response") or f_resp2.get("response") or f_resp2) if isinstance(f_resp2, dict) else {}
                    if isinstance(p2, dict) and eid in p2 and isinstance(p2[eid], dict):
                        cand = p2[eid].get("forecast")
                        if isinstance(cand, list) and cand:
                            forecast_list = cand
                            break
                except Exception:
                    pass
        if (not isinstance(forecast_list, list) or not forecast_list) and isinstance(attrs.get("forecast"), list):
            forecast_list = attrs.get("forecast")
        if isinstance(forecast_list, list) and forecast_list:
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
                payload = (c_resp.get("service_response") or c_resp.get("response") or c_resp) if isinstance(c_resp, dict) else {}
                cal_events = []
                if isinstance(payload, dict) and eid in payload and isinstance(payload[eid], dict):
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


async def fetch_racing_data(session, entity_or_series="f1", fallback=None, tz_name=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    now = time.time()
    raw_key = str(entity_or_series or "f1").strip().lower()
    cache_key = f"{raw_key}:{tz_name}"

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
            ser_name = "FE" if raw_key in ("fe", "formula_e", "formula-e", "formulae") else "F1"
            return {
                "series": ser_name,
                "event_name": ha_event_name or ("Formula E World Championship" if ser_name == "FE" else "Formula 1 Grand Prix"),
                "circuit": ha_circuit or "Grand Prix Circuit",
                "status": ha_status or "IN",
                "lap": attrs.get("lap"),
                "total_laps": attrs.get("total_laps"),
                "clock": attrs.get("clock") or ha_status,
                "standings": attrs.get("standings")
            }

    # 2. Formula E support
    if raw_key in ("fe", "formula_e", "formula-e", "formulae"):
        cached = _racing_cache.get(cache_key)
        if cached and (now - cached["at"] < (60.0 if cached.get("is_live") else 600.0)):
            return cached["data"]

        fe_event = {
            "series": "FE",
            "event_name": ha_event_name or "Formula E World Championship",
            "circuit": ha_circuit or "ePrix Circuit",
            "detail": "Upcoming Formula E Session",
            "status": ha_status or "PRE",
            "clock": "PRE",
            "standings": []
        }
        is_live = False
        now_utc = datetime.now(timezone.utc)
        cur_year = now_utc.year
        headers = {"User-Agent": "Crowpanel-Epaper/0.8.23 (HomeAssistant Addon)"}
        timeout = aiohttp.ClientTimeout(total=6)

        try:
            races = []
            for yr in (cur_year, cur_year + 1):
                fe_url = f"https://raw.githubusercontent.com/sportstimes/f1/main/_db/fe/{yr}.json"
                try:
                    async with session.get(fe_url, headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            fdata = await r.json(content_type=None)
                            yr_races = fdata.get("races") or []
                            if yr_races:
                                races.extend(yr_races)
                except Exception:
                    pass

            if not races:
                try:
                    async with session.get(f"https://formulaecal.com/api/year/{cur_year}", headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            fdata = await r.json(content_type=None)
                            races = fdata.get("races") or []
                except Exception:
                    pass

            if races:
                candidate_race = None
                active_session_name = "Race"
                active_session_dt = None
                session_st = "PRE"

                for r in races:
                    sess_dict = r.get("sessions") or {}
                    s_items = []
                    for s_k, s_v in sess_dict.items():
                        if not s_v:
                            continue
                        try:
                            s_dt = datetime.fromisoformat(str(s_v).replace("Z", "+00:00"))
                            s_items.append((s_k, s_dt))
                        except Exception:
                            pass
                    s_items.sort(key=lambda x: x[1])
                    if not s_items:
                        continue

                    if s_items[-1][1] + timedelta(hours=4) >= now_utc:
                        candidate_race = r
                        for s_k, s_dt in s_items:
                            if s_dt <= now_utc <= s_dt + timedelta(hours=2):
                                active_session_name = s_k
                                active_session_dt = s_dt
                                session_st = "IN"
                                is_live = True
                                break
                            elif s_dt > now_utc:
                                active_session_name = s_k
                                active_session_dt = s_dt
                                session_st = "PRE"
                                break
                        if not active_session_dt:
                            active_session_name = s_items[-1][0]
                            active_session_dt = s_items[-1][1]
                            session_st = "POST"
                        break

                if not candidate_race:
                    candidate_race = races[-1]
                    session_st = "POST"
                    s_items = [(k, datetime.fromisoformat(str(v).replace("Z", "+00:00")))
                               for k, v in candidate_race.get("sessions", {}).items() if v]
                    s_items.sort(key=lambda x: x[1])
                    active_session_name = s_items[-1][0] if s_items else "Race"
                    active_session_dt = s_items[-1][1] if s_items else now_utc

                friendly_session_map = {
                    "practice1": "Practice 1",
                    "practice2": "Practice 2",
                    "qualifying": "Qualifying",
                    "race": "ePrix Race"
                }
                session_title = friendly_session_map.get(active_session_name.lower(), active_session_name.capitalize())
                circ_name = candidate_race.get("location") or "ePrix Circuit"
                if "circuit" not in circ_name.lower():
                    circ_name = f"{circ_name} ePrix Circuit"

                detail_str = ""
                if active_session_dt:
                    try:
                        dt_loc = active_session_dt.astimezone(ZoneInfo(tz_name))
                        tz_abbr = dt_loc.tzname() or ""
                        detail_str = f"{session_title} · {dt_loc.strftime('%a %b %d · %H:%M')} {tz_abbr}".strip()
                    except Exception:
                        detail_str = f"{session_title} · {active_session_dt.strftime('%a %b %d · %H:%M UTC')}"

                fe_event = {
                    "series": "FE",
                    "event_name": candidate_race.get("name") or ha_event_name or "Formula E World Championship",
                    "circuit": circ_name,
                    "detail": detail_str or f"Status: {session_st}",
                    "status": session_st,
                    "clock": f"{session_title} LIVE" if session_st == "IN" else ("SCHEDULED" if session_st == "PRE" else "FINAL"),
                    "standings": []
                }

            _racing_cache[cache_key] = {"at": now, "data": fe_event, "is_live": is_live}
            return fe_event
        except Exception as exc:
            print(f"fetch_formula_e_data error: {exc!r}", flush=True)
            return _racing_cache.get(cache_key, {}).get("data") or fe_event

    # 3. Check in-memory cache for F1 / other series
    cached = _racing_cache.get(cache_key)
    if cached and (now - cached["at"] < (60.0 if cached.get("is_live") else 600.0)):
        return cached["data"]

    # 4. Approach B: Query ESPN F1 scoreboard
    f1_url = "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.23 (HomeAssistant Addon)"}
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
                            if tz_name:
                                dt_loc = dt.astimezone(ZoneInfo(tz_name))
                                tz_abbr = dt_loc.tzname() or ""
                                detail_str = f"{dt_loc.strftime('%a %b %d · %H:%M')} {tz_abbr}".strip()
                            else:
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

        _racing_cache[cache_key] = {"at": now, "data": event_data, "is_live": is_live}
        return event_data
    except Exception as exc:
        print(f"fetch_racing_data error: {exc!r}", flush=True)
        return _racing_cache.get(cache_key, {}).get("data") or event_data


LEAGUE_MAP = {
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

LEAGUE_SLUGS = {
    "soccer/eng.1": "premier_league",
    "premier_league": "premier_league",
    "epl": "premier_league",
    "soccer/uefa.champions": "champions_league",
    "champions_league": "champions_league",
    "ucl": "champions_league",
    "soccer/esp.1": "la_liga",
    "la_liga": "la_liga",
    "soccer/ger.1": "bundesliga",
    "bundesliga": "bundesliga",
    "soccer/ita.1": "serie_a",
    "serie_a": "serie_a",
    "soccer/usa.1": "mls",
    "mls": "mls",
    "basketball/nba": "nba",
    "nba": "nba",
    "basketball/wnba": "wnba",
    "wnba": "wnba",
    "football/nfl": "nfl",
    "nfl": "nfl",
    "football/college-football": "college_football",
    "baseball/mlb": "mlb",
    "mlb": "mlb",
    "hockey/nhl": "nhl",
    "nhl": "nhl"
}


def _parse_espn_event(ev, league_title="MATCH", tz_name=None):
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    st_type = comp.get("status", {}).get("type", {})
    st_state = st_type.get("state") or "pre"
    st_desc = st_type.get("description") or st_type.get("detail") or "Scheduled"
    clock_val = comp.get("status", {}).get("displayClock")
    is_live = (st_state == "in")

    date_str = ev.get("date") or comp.get("date") or ""
    kickoff_time_str = ""
    kickoff_day_str = ""
    if date_str:
        try:
            kickoff_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if tz_name:
                try:
                    local_tz = ZoneInfo(tz_name)
                    kickoff_dt = kickoff_dt.astimezone(local_tz)
                except Exception:
                    pass
            kickoff_time_str = kickoff_dt.strftime("%H:%M")
            now_local = datetime.now(kickoff_dt.tzinfo)
            if kickoff_dt.date() != now_local.date():
                kickoff_day_str = kickoff_dt.strftime("%a ")
        except Exception:
            pass

    if is_live:
        clock_badge = f"{clock_val} · {st_desc}" if (clock_val and clock_val != "0'") else st_desc
    elif st_state == "pre":
        if kickoff_day_str:
            clock_badge = f"{kickoff_day_str}{kickoff_time_str}"
        elif kickoff_time_str:
            clock_badge = f"Kickoff {kickoff_time_str}"
        else:
            clock_badge = st_desc
    else:
        clock_badge = st_desc

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
        "id": str(ev.get("id") or comp.get("id") or f"{home_id}_{str(away.get('team', {}).get('id') or '')}"),
        "league": league_title,
        "venue": venue_title,
        "clock": clock_badge,
        "status": st_state.upper(),
        "is_live": is_live,
        "kickoff_iso": date_str,
        "kickoff_time": kickoff_time_str,
        "home_team": home.get("team", {}).get("displayName") or home.get("team", {}).get("shortDisplayName") or "HOME",
        "home_score": home.get("score") if home.get("score") is not None else "-",
        "home_stats": (home.get("records") or [{}])[0].get("summary", ""),
        "away_team": away.get("team", {}).get("displayName") or away.get("team", {}).get("shortDisplayName") or "AWAY",
        "away_score": away.get("score") if away.get("score") is not None else "-",
        "away_stats": (away.get("records") or [{}])[0].get("summary", ""),
        "events_home": ", ".join(events_home[:3]),
        "events_away": ", ".join(events_away[:3])
    }


_sports_window_cache: dict[str, dict] = {}
_racing_window_cache: dict[str, dict] = {}


async def compute_sports_active_window(session, entity_or_league="soccer/eng.1", pre_buffer_hours=2.0, post_buffer_hours=2.0, tz_name=None, team=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    slug_in = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = LEAGUE_MAP.get(slug_in, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"
    slug = LEAGUE_SLUGS.get(endpoint_path, LEAGUE_SLUGS.get(slug_in, slug_in.replace("/", "_")))
    team_q = str(team or "").strip().lower()

    cache_key = f"{endpoint_path}:{pre_buffer_hours}:{post_buffer_hours}:{tz_name}:{team_q}"
    now_ts = time.time()
    cached = _sports_window_cache.get(cache_key)
    if cached and (now_ts - cached["at"] < 60.0):
        return cached["data"]

    sport_key = endpoint_path.split("/")[0]
    durations = {"soccer": 2.0, "basketball": 2.5, "football": 3.25, "baseball": 2.75, "hockey": 2.5}
    est_duration_hours = durations.get(sport_key, 2.0)

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")
    yesterday_str = (now_utc - timedelta(days=1)).strftime("%Y%m%d")

    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    today_url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={today_str}"
    events = []
    league_title = "MATCH"
    try:
        async with session.get(today_url, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                league_title = (data.get("leagues") or [{}])[0].get("name") or "MATCH"
    except Exception as exc:
        print(f"compute_sports_active_window error: {exc!r}", flush=True)

    yesterday_events = []
    if not events or now_utc.hour < 12:
        yest_url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={yesterday_str}"
        try:
            async with session.get(yest_url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    ydata = await r.json()
                    yesterday_events = ydata.get("events") or []
                    if not events:
                        league_title = (ydata.get("leagues") or [{}])[0].get("name") or league_title
        except Exception:
            pass

    def _matches_team_filter(ev_obj):
        if not team_q:
            return True
        comp = (ev_obj.get("competitions") or [{}])[0]
        for c in (comp.get("competitors") or []):
            t_info = c.get("team") or {}
            names = f"{t_info.get('displayName', '')} {t_info.get('shortDisplayName', '')} {t_info.get('abbreviation', '')}".lower()
            if team_q in names:
                return True
        return False

    filtered_today = [ev for ev in events if _matches_team_filter(ev)]
    filtered_yesterday = [ev for ev in yesterday_events if _matches_team_filter(ev)]
    all_candidate_events = filtered_today + filtered_yesterday

    game_times = []
    is_live = False
    today_parsed = []

    for ev in filtered_today:
        parsed = _parse_espn_event(ev, league_title, tz_name=tz_name)
        today_parsed.append(parsed)

    for ev in all_candidate_events:
        st_state = ev.get("status", {}).get("type", {}).get("state")
        if st_state == "in":
            is_live = True
        d_str = ev.get("date")
        if d_str:
            try:
                dt = datetime.fromisoformat(d_str.replace("Z", "+00:00"))
                if ev in filtered_today or st_state == "in":
                    game_times.append(dt)
            except Exception:
                pass

    first_ko = min(game_times) if game_times else None
    last_ko = max(game_times) if game_times else None

    win_start = (first_ko - timedelta(hours=pre_buffer_hours)) if first_ko else None
    win_end = (last_ko + timedelta(hours=est_duration_hours + post_buffer_hours)) if last_ko else None

    is_active = is_live or (bool(win_start and win_end and (win_start <= now_utc <= win_end)))

    summaries = []
    for m in today_parsed:
        summaries.append(f"{m['away_team']} at {m['home_team']}")

    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    first_ko_local = first_ko.astimezone(local_tz).strftime("%H:%M") if first_ko else None
    last_ko_local = last_ko.astimezone(local_tz).strftime("%H:%M") if last_ko else None
    win_start_local = win_start.astimezone(local_tz).strftime("%H:%M") if win_start else None
    win_end_local = win_end.astimezone(local_tz).strftime("%H:%M") if win_end else None

    result = {
        "slug": slug,
        "sensor_id": f"sensor.epaper_sports_{slug}",
        "league_name": league_title,
        "is_active": is_active,
        "state": "active" if is_active else "idle",
        "is_live": is_live,
        "matches_today": len(filtered_today),
        "first_kickoff": first_ko.isoformat() if first_ko else None,
        "first_kickoff_local": first_ko_local,
        "last_kickoff": last_ko.isoformat() if last_ko else None,
        "last_kickoff_local": last_ko_local,
        "window_start": win_start.isoformat() if win_start else None,
        "window_start_local": win_start_local,
        "window_end": win_end.isoformat() if win_end else None,
        "window_end_local": win_end_local,
        "time_zone": tz_name,
        "pre_buffer_hours": pre_buffer_hours,
        "post_buffer_hours": post_buffer_hours,
        "team_filter": team or "",
        "matches_summary": ", ".join(summaries[:6]),
        "today_matches": today_parsed,
    }
    _sports_window_cache[cache_key] = {"at": now_ts, "data": result}
    return result


async def compute_racing_active_window(session, series="f1", pre_buffer_hours=2.0, post_buffer_hours=2.0, window_mode="session", tz_name=None):
    """Compute whether a Motorsport series (F1, Formula E, NASCAR, IndyCar) is in an active session/race-weekend window."""
    if not tz_name:
        tz_name = await get_home_timezone(session)
    raw_s = str(series or "f1").strip().lower()
    if raw_s in ("fe", "formula_e", "formula-e", "formulae"):
        slug = "fe"
        series_title = "Formula E"
    elif raw_s in ("nascar", "nascar-premier"):
        slug = "nascar"
        series_title = "NASCAR"
    elif raw_s in ("indycar", "irl"):
        slug = "indycar"
        series_title = "IndyCar"
    else:
        slug = "f1"
        series_title = "Formula 1"

    w_mode = "weekend" if str(window_mode).strip().lower() == "weekend" else "session"
    cache_key = f"{slug}:{pre_buffer_hours}:{post_buffer_hours}:{w_mode}:{tz_name}"
    now_ts = time.time()
    cached = _racing_window_cache.get(cache_key)
    if cached and (now_ts - cached["at"] < 60.0):
        return cached["data"]

    now_utc = datetime.now(timezone.utc)
    cur_year = now_utc.year
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    sessions_list: list[tuple[str, datetime, float]] = []  # (session_label, start_utc, duration_hours)
    event_name = f"{series_title} Championship"
    circuit_name = ""
    is_live = False

    # 1. For F1 and Formula E, check sportstimes session database for exact FP1/FP2/FP3/Quali/Sprint/Race UTC timestamps
    if slug in ("f1", "fe"):
        for yr in (cur_year, cur_year + 1):
            db_url = f"https://raw.githubusercontent.com/sportstimes/f1/main/_db/{slug}/{yr}.json"
            try:
                async with session.get(db_url, headers=headers, timeout=timeout) as r:
                    if r.status == 200:
                        fdata = await r.json(content_type=None)
                        races = fdata.get("races") or []
                        for race in races:
                            sess_dict = race.get("sessions") or {}
                            r_sessions = []
                            for sk, sv in sess_dict.items():
                                if not sv:
                                    continue
                                try:
                                    sdt = datetime.fromisoformat(str(sv).replace("Z", "+00:00"))
                                    dur = 2.5 if sk.lower() in ("gp", "race") else 1.5
                                    r_sessions.append((sk, sdt, dur))
                                except Exception:
                                    pass
                            r_sessions.sort(key=lambda x: x[1])
                            if not r_sessions:
                                continue
                            # Pick the race weekend whose final session + post_buffer + 12h hasn't long passed
                            if r_sessions[-1][1] + timedelta(hours=r_sessions[-1][2] + max(post_buffer_hours, 6.0)) >= now_utc:
                                event_name = race.get("name") or event_name
                                circuit_name = race.get("location") or ""
                                sessions_list = r_sessions
                                break
                        if sessions_list:
                            break
            except Exception:
                pass

    # 2. Also check ESPN racing scoreboard (for live status and NASCAR/IndyCar/F1 fallback)
    espn_map = {"f1": "f1", "nascar": "nascar-premier", "indycar": "irl"}
    if slug in espn_map:
        espn_url = f"https://site.api.espn.com/apis/site/v2/sports/racing/{espn_map[slug]}/scoreboard"
        try:
            async with session.get(espn_url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = data.get("events") or []
                    if events:
                        ev = events[0]
                        event_name = ev.get("name") or event_name
                        circuit_name = (ev.get("circuit") or {}).get("fullName") or circuit_name
                        st_state = ev.get("status", {}).get("type", {}).get("state") or "pre"
                        if st_state == "in":
                            is_live = True
                        if not sessions_list:
                            for comp in (ev.get("competitions") or []):
                                c_date = comp.get("date") or ev.get("date")
                                c_type = (comp.get("type") or {}).get("text") or "Session"
                                c_state = (comp.get("status") or {}).get("type", {}).get("state")
                                if c_state == "in":
                                    is_live = True
                                if c_date:
                                    try:
                                        cdt = datetime.fromisoformat(str(c_date).replace("Z", "+00:00"))
                                        dur = 2.5 if "race" in c_type.lower() else 1.5
                                        sessions_list.append((c_type, cdt, dur))
                                    except Exception:
                                        pass
                            if not sessions_list and ev.get("date"):
                                try:
                                    edt = datetime.fromisoformat(str(ev["date"]).replace("Z", "+00:00"))
                                    sessions_list.append(("Race", edt, 2.5))
                                except Exception:
                                    pass
                            sessions_list.sort(key=lambda x: x[1])
        except Exception:
            pass

    active_win_start = None
    active_win_end = None
    active_session_label = ""
    is_active = is_live

    if sessions_list:
        for s_label, s_dt, s_dur in sessions_list:
            if s_dt <= now_utc <= s_dt + timedelta(hours=s_dur):
                is_live = True
                is_active = True

        if w_mode == "weekend":
            first_label, first_dt, _ = sessions_list[0]
            last_label, last_dt, last_dur = sessions_list[-1]
            w_start = first_dt - timedelta(hours=pre_buffer_hours)
            w_end = last_dt + timedelta(hours=last_dur + post_buffer_hours)
            active_win_start = w_start
            active_win_end = w_end
            active_session_label = f"{first_label} – {last_label}"
            if w_start <= now_utc <= w_end:
                is_active = True
        else:
            # Session-by-session mode: find the currently active session window, or the next upcoming one
            chosen = None
            for s_label, s_dt, s_dur in sessions_list:
                w_start = s_dt - timedelta(hours=pre_buffer_hours)
                w_end = s_dt + timedelta(hours=s_dur + post_buffer_hours)
                if w_start <= now_utc <= w_end:
                    is_active = True
                    chosen = (s_label, w_start, w_end)
                    break
                elif w_start > now_utc and chosen is None:
                    chosen = (s_label, w_start, w_end)
            if chosen is None:
                s_label, s_dt, s_dur = sessions_list[-1]
                chosen = (s_label, s_dt - timedelta(hours=pre_buffer_hours), s_dt + timedelta(hours=s_dur + post_buffer_hours))
            active_session_label, active_win_start, active_win_end = chosen

    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    win_start_local = active_win_start.astimezone(local_tz).strftime("%a %H:%M") if active_win_start else None
    win_end_local = active_win_end.astimezone(local_tz).strftime("%a %H:%M") if active_win_end else None

    result = {
        "slug": slug,
        "sensor_id": f"sensor.epaper_racing_{slug}",
        "series_name": series_title,
        "event_name": event_name,
        "circuit": circuit_name,
        "session_name": active_session_label,
        "is_active": is_active,
        "state": "active" if is_active else "idle",
        "is_live": is_live,
        "window_mode": w_mode,
        "window_start": active_win_start.isoformat() if active_win_start else None,
        "window_start_local": win_start_local,
        "window_end": active_win_end.isoformat() if active_win_end else None,
        "window_end_local": win_end_local,
        "time_zone": tz_name,
        "pre_buffer_hours": pre_buffer_hours,
        "post_buffer_hours": post_buffer_hours,
    }
    _racing_window_cache[cache_key] = {"at": now_ts, "data": result}
    return result


async def fetch_sports_match(session, entity_or_league="soccer/eng.1", team=None, fallback=None, tz_name=None):
    if not tz_name:
        tz_name = await get_home_timezone(session)
    now = time.time()
    raw_input = str(entity_or_league or "soccer/eng.1").strip()
    cache_key = f"{raw_input}:{str(team or '').lower()}:{tz_name}"

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
            "id": str(attrs.get("event_id") or attrs.get("id") or f"{home}_{away}"),
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
    slug = raw_input.lower().replace("-", "_").replace(" ", "_")
    endpoint_path = LEAGUE_MAP.get(slug, raw_input)
    if "/" not in endpoint_path:
        endpoint_path = f"soccer/{endpoint_path}"

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y%m%d")

    url_today = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard?dates={today_str}"
    url_default = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint_path}/scoreboard"
    headers = {"User-Agent": "Crowpanel-Epaper/0.8.27 (HomeAssistant Addon)"}
    timeout = aiohttp.ClientTimeout(total=6)

    try:
        events = []
        league_title = "MATCH"
        # First try today's games so today's upcoming/live matches take precedence
        async with session.get(url_today, headers=headers, timeout=timeout) as r:
            if r.status == 200:
                data = await r.json()
                events = data.get("events") or []
                league_title = (data.get("leagues") or [{}])[0].get("name") or "MATCH"

        # If no games today, fall back to default scoreboard (upcoming or current round)
        if not events:
            async with session.get(url_default, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    data = await r.json()
                    events = data.get("events") or []
                    league_title = (data.get("leagues") or [{}])[0].get("name") or league_title

        if not events:
            return cached["data"] if cached else None

        parsed_matches = [_parse_espn_event(ev, league_title, tz_name=tz_name) for ev in events]

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
    home_tz = await get_home_timezone(session)
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
            custom_lat = el.get("lat") or el.get("latitude")
            custom_lon = el.get("lon") or el.get("lng") or el.get("longitude")
            fl_data = await fetch_overhead_aircraft(session, radius_km=radius, lat=custom_lat, lon=custom_lon)
            if fl_data is not None:
                vals[i] = fl_data
        elif t == "sports_racing":
            entity_or_series = el.get("entity") or el.get("series") or "f1"
            el_tz = el.get("timezone") or home_tz
            race_data = await fetch_racing_data(session, entity_or_series, fallback=vals.get(i), tz_name=el_tz)
            if race_data:
                vals[i] = race_data
        elif t == "sports_match":
            entity_or_league = el.get("entity") or el.get("league") or "soccer/eng.1"
            team = el.get("team")
            el_tz = el.get("timezone") or home_tz
            match_data = await fetch_sports_match(session, entity_or_league, team=team, fallback=vals.get(i), tz_name=el_tz)
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


def _is_builtin_widget_gate(page: dict) -> dict | None:
    """Return the composite element that drives this page's active window if applicable."""
    els = page.get("elements") or []
    widget = next((e for e in els if isinstance(e, dict) and e.get("type") in ("sports_match", "sports_racing", "flight_tracker")), None)
    if not widget:
        return None
    show_if = str(page.get("show_if") or "").strip()
    if not show_if or widget.get("auto_window"):
        return widget
    # Also intercept any show_if that points to our built-in sports/racing/flight sensors
    # so switching leagues or series in the widget inspector always evaluates the widget's live config!
    builtin_patterns = (
        "sensor.epaper_sports_",
        "sensor.sports_",
        "sensor.epaper_racing_",
        "sensor.f1_status",
        "sensor.formula_e_status",
        "sensor.epaper_flights_overhead",
        "sensor.overhead_aircraft_count",
    )
    if any(pat in show_if for pat in builtin_patterns):
        return widget
    return None


async def _evaluate_widget_gate(session, widget: dict, home_tz: str) -> bool:
    """Directly evaluate the active window for a sports_match, sports_racing, or flight_tracker widget."""
    wtype = widget.get("type")
    el_tz = widget.get("timezone") or home_tz
    try:
        pre_b = float(widget.get("pre_buffer_hours")) if widget.get("pre_buffer_hours") is not None else 2.0
    except (ValueError, TypeError):
        pre_b = 2.0
    try:
        post_b = float(widget.get("post_buffer_hours")) if widget.get("post_buffer_hours") is not None else 2.0
    except (ValueError, TypeError):
        post_b = 2.0

    if wtype == "sports_match":
        lg = widget.get("league") or "soccer/eng.1"
        team = widget.get("team")
        win = await compute_sports_active_window(session, lg, pre_buffer_hours=pre_b, post_buffer_hours=post_b, tz_name=el_tz, team=team)
        return bool(win.get("is_active"))
    if wtype == "sports_racing":
        series = widget.get("series") or "f1"
        w_mode = widget.get("window_mode") or "session"
        win = await compute_racing_active_window(session, series, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=el_tz)
        return bool(win.get("is_active"))
    if wtype == "flight_tracker":
        radius = float(widget.get("radius") or 35.0)
        custom_lat = widget.get("lat") or widget.get("latitude")
        custom_lon = widget.get("lon") or widget.get("lng") or widget.get("longitude")
        aircraft = await fetch_overhead_aircraft(session, radius_km=radius, lat=custom_lat, lon=custom_lon)
        return len(aircraft or []) > 0
    return True


async def eligible_pages(session, spec):
    """Pages whose tier and show_if (or built-in widget active window) say they belong in the rotation now."""
    rotation = spec.get("rotation", [])
    defs = spec.get("pages", {})
    home_tz = await get_home_timezone(session)

    widget_gates: dict[str, dict] = {}
    template_gates: dict[str, str] = {}

    for n in set(rotation):
        p = defs.get(n)
        if not p or p.get("tier") != "when":
            continue
        w_gate = _is_builtin_widget_gate(p)
        if w_gate is not None:
            widget_gates[n] = w_gate
        elif p.get("show_if"):
            template_gates[n] = p["show_if"]

    passed = await resolve_templates(session, template_gates) if template_gates else {}
    widget_results: dict[str, bool] = {}
    for n, w_el in widget_gates.items():
        try:
            widget_results[n] = await _evaluate_widget_gate(session, w_el, home_tz)
        except Exception as exc:
            print(f"widget gate eval error for {n}: {exc!r}", flush=True)
            widget_results[n] = False

    live = []
    for name in rotation:
        page = defs.get(name)
        if page is None or page.get("tier") == "alert":
            continue
        if name in widget_results:
            if not widget_results[name]:
                continue
        elif name in template_gates:
            if str(passed.get(name, "")).strip().lower() not in ("true", "on", "yes", "1"):
                continue
        live.append(name)
    return live or [n for n in rotation if n in defs and defs[n].get("tier") != "alert"][:1]


async def publish_category_sensors(session, cur_f):
    if not cur_f or not cur_f.rendered_at:
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
    """Run configured data sources and publish on-demand sensors for active E-Paper Studio widgets."""
    srcs = load_sources()
    if srcs:
        ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": session}
        for entity_id, state, attrs in await feeds.run_all(srcs, ctx):
            if attrs and "items" in attrs:
                _feed_items_cache[entity_id] = attrs["items"]
            await publish_entity(session, entity_id, state, attrs)

    cur_spec = load_layouts()
    spec_text = json.dumps(cur_spec)
    home_tz = await get_home_timezone(session)

    flight_elements = []
    sports_elements = []
    racing_elements = []
    for p in cur_spec.get("pages", {}).values():
        for el in p.get("elements", []):
            t = el.get("type")
            if t == "flight_tracker":
                flight_elements.append(el)
            elif t == "sports_match":
                sports_elements.append(el)
            elif t == "sports_racing":
                racing_elements.append(el)

    # 1. On-demand Overhead Aircraft sensors (only when flight_tracker or flight sensor is used)
    if flight_elements or "epaper_flights_overhead" in spec_text or "epaper_closest_aircraft" in spec_text or "overhead_aircraft_count" in spec_text:
        try:
            flight_radius = 35.0
            custom_lat = None
            custom_lon = None
            custom_loc = None
            if flight_elements:
                el = flight_elements[0]
                flight_radius = float(el.get("radius") or 35.0)
                if el.get("lat") is not None and el.get("lon") is not None:
                    try:
                        custom_lat = float(el.get("lat"))
                        custom_lon = float(el.get("lon"))
                    except (ValueError, TypeError):
                        pass
                if el.get("location_name"):
                    custom_loc = str(el.get("location_name")).strip()

            aircraft = await fetch_overhead_aircraft(session, radius_km=flight_radius, lat=custom_lat, lon=custom_lon)
            closest_cs = aircraft[0]["callsign"] if aircraft else "None"
            friendly_sensor_name = f"E-Paper · Flights Overhead ({custom_loc})" if custom_loc else "E-Paper · Flights Overhead"
            attrs = {
                "unit_of_measurement": "aircraft",
                "friendly_name": friendly_sensor_name,
                "closest_callsign": closest_cs,
                "radius_km": flight_radius,
                "location_name": custom_loc or "Home",
                "icon": "mdi:airplane"
            }
            if custom_lat is not None and custom_lon is not None:
                attrs["latitude"] = custom_lat
                attrs["longitude"] = custom_lon
            if aircraft:
                attrs["closest_distance_km"] = aircraft[0]["distance_km"]
                attrs["closest_bearing"] = aircraft[0]["bearing_cardinal"]
                attrs["closest_route"] = aircraft[0].get("origin", "") + " → " + aircraft[0].get("destination", "") if (aircraft[0].get("origin") and aircraft[0].get("destination")) else ""
                attrs["closest_model"] = aircraft[0].get("model", "")
            await publish_entity(session, "sensor.epaper_flights_overhead", len(aircraft), attrs)
            if aircraft:
                ac0 = aircraft[0]
                alt_m0 = float(ac0.get("altitude_m") or 0.0)
                spd_ms0 = float(ac0.get("velocity_ms") or 0.0)
                await publish_entity(session, "sensor.epaper_closest_aircraft", closest_cs,
                                     {"friendly_name": "E-Paper · Closest Aircraft",
                                      "distance_km": ac0.get("distance_km"),
                                      "bearing": ac0.get("bearing_cardinal"),
                                      "altitude_m": int(alt_m0),
                                      "altitude_ft": int(alt_m0 * 3.28084),
                                      "speed_kts": int(spd_ms0 * 1.94384),
                                      "speed_kmh": int(spd_ms0 * 3.6),
                                      "track_deg": int(ac0.get("track_deg") or 0),
                                      "country": ac0.get("country"),
                                      "model": ac0.get("model", ""),
                                      "location_name": custom_loc or "Home",
                                      "icon": "mdi:airplane"})
        except Exception as exc:
            print(f"publish aircraft sensor failed: {exc!r}", flush=True)

    # 2. On-demand Sports Matchday Window sensors (only for leagues actually present in pages)
    try:
        leagues_to_publish = []
        for el in sports_elements:
            lg = el.get("league") or "soccer/eng.1"
            el_tz = el.get("timezone") or home_tz
            team = el.get("team")
            try:
                pre_b = float(el.get("pre_buffer_hours")) if el.get("pre_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                pre_b = 2.0
            try:
                post_b = float(el.get("post_buffer_hours")) if el.get("post_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                post_b = 2.0
            leagues_to_publish.append((lg, pre_b, post_b, el_tz, team))

        seen_leagues = set()
        for lg, pre_b, post_b, s_tz, team in leagues_to_publish:
            key = f"{lg}:{team or ''}"
            if key in seen_leagues:
                continue
            seen_leagues.add(key)
            win_info = await compute_sports_active_window(session, lg, pre_buffer_hours=pre_b, post_buffer_hours=post_b, tz_name=s_tz, team=team)
            slug = win_info["slug"]
            sensor_id = f"sensor.epaper_sports_{slug}"
            sport_icon = "mdi:soccer"
            if "nba" in slug or "basketball" in lg:
                sport_icon = "mdi:basketball"
            elif "nfl" in slug or "football" in lg:
                sport_icon = "mdi:football"
            elif "mlb" in slug or "baseball" in lg:
                sport_icon = "mdi:baseball"
            elif "nhl" in slug or "hockey" in lg:
                sport_icon = "mdi:hockey-puck"

            await publish_entity(
                session, sensor_id, win_info["state"],
                {
                    "friendly_name": f"E-Paper · {win_info['league_name']} Matchday",
                    "is_active": win_info["is_active"],
                    "is_live": win_info["is_live"],
                    "matches_today": win_info["matches_today"],
                    "first_kickoff": win_info["first_kickoff"],
                    "first_kickoff_local": win_info.get("first_kickoff_local"),
                    "last_kickoff": win_info["last_kickoff"],
                    "last_kickoff_local": win_info.get("last_kickoff_local"),
                    "window_start": win_info["window_start"],
                    "window_start_local": win_info.get("window_start_local"),
                    "window_end": win_info["window_end"],
                    "window_end_local": win_info.get("window_end_local"),
                    "time_zone": win_info.get("time_zone"),
                    "pre_buffer_hours": win_info["pre_buffer_hours"],
                    "post_buffer_hours": win_info["post_buffer_hours"],
                    "team_filter": win_info.get("team_filter", ""),
                    "matches_summary": win_info["matches_summary"],
                    "icon": sport_icon
                }
            )
    except Exception as exc:
        print(f"publish sports matchday sensor failed: {exc!r}", flush=True)

    # 3. On-demand Motorsport Session/Race Window sensors (only for series actually present in pages)
    try:
        series_to_publish = []
        for el in racing_elements:
            ser = el.get("series") or "f1"
            el_tz = el.get("timezone") or home_tz
            w_mode = el.get("window_mode") or "session"
            try:
                pre_b = float(el.get("pre_buffer_hours")) if el.get("pre_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                pre_b = 2.0
            try:
                post_b = float(el.get("post_buffer_hours")) if el.get("post_buffer_hours") is not None else 2.0
            except (ValueError, TypeError):
                post_b = 2.0
            series_to_publish.append((ser, pre_b, post_b, w_mode, el_tz))

        seen_series = set()
        for ser, pre_b, post_b, w_mode, r_tz in series_to_publish:
            if ser in seen_series:
                continue
            seen_series.add(ser)
            win_info = await compute_racing_active_window(session, ser, pre_buffer_hours=pre_b, post_buffer_hours=post_b, window_mode=w_mode, tz_name=r_tz)
            slug = win_info["slug"]
            sensor_id = f"sensor.epaper_racing_{slug}"
            r_data = await fetch_racing_data(session, slug, tz_name=r_tz)
            r_icon = "mdi:car-electric" if slug == "fe" else "mdi:racing-helmet"
            await publish_entity(
                session, sensor_id, win_info["state"],
                {
                    "friendly_name": f"E-Paper · {win_info['series_name']} Window",
                    "is_active": win_info["is_active"],
                    "is_live": win_info["is_live"],
                    "session_status": (r_data or {}).get("status", "PRE"),
                    "event_name": (r_data or {}).get("event_name") or win_info["event_name"],
                    "circuit": (r_data or {}).get("circuit") or win_info["circuit"],
                    "session_name": win_info["session_name"],
                    "detail": (r_data or {}).get("detail", ""),
                    "clock": (r_data or {}).get("clock", ""),
                    "window_mode": win_info["window_mode"],
                    "window_start": win_info["window_start"],
                    "window_start_local": win_info["window_start_local"],
                    "window_end": win_info["window_end"],
                    "window_end_local": win_info["window_end_local"],
                    "pre_buffer_hours": win_info["pre_buffer_hours"],
                    "post_buffer_hours": win_info["post_buffer_hours"],
                    "icon": r_icon,
                }
            )
    except Exception as exc:
        print(f"publish racing window sensor failed: {exc!r}", flush=True)

    # 4. Publish E-Paper panel system status sensors & MQTT discovery
    try:
        cur_f = globals().get("FRAMES")
        if cur_f and cur_f.rendered_at:
            await publish_entity(session, "sensor.epaper_panel_last_render", cur_f.rendered_at,
                                 {"friendly_name": "E-Paper · Last Render", "icon": "mdi:clock-check-outline",
                                  "pages_count": len(cur_f.names), "active_pages": cur_f.names,
                                  "device_class": "timestamp"})
            await publish_category_sensors(session, cur_f)
            await publish_mqtt_discovery(session, cur_f)
    except Exception:
        pass


_mqtt_discovered_ids: set[str] = set()


async def publish_mqtt_discovery(session, frames):
    """Publish Home Assistant MQTT Auto-Discovery with unique_id & device info for all active sensor.epaper_* entities."""
    if not HA_TOKEN:
        return
    try:
        dev_info = {
            "identifiers": ["epaper_panel_hub"],
            "name": "E-Paper Studio",
            "manufacturer": "Elecrow",
            "model": "CrowPanel E-Paper",
            "sw_version": "0.8.27"
        }
        if "epaper_panel_refresh_button" not in _mqtt_discovered_ids:
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
            _mqtt_discovered_ids.add("epaper_panel_refresh_button")

        for eid, info in list(_epaper_published_entities.items()):
            if not eid.startswith("sensor.epaper_") or not info.get("register_mqtt", True):
                continue
            obj_id = eid.split(".", 1)[1]  # e.g. epaper_sports_premier_league
            attrs = dict(info.get("attributes") or {})
            fname = attrs.get("friendly_name") or obj_id.replace("_", " ").title()
            icon = attrs.get("icon") or "mdi:tablet-dashboard"
            dev_class = attrs.get("device_class")
            unit = attrs.get("unit_of_measurement")

            state_topic = f"homeassistant/epaper_panel/{obj_id}/state"
            attr_topic = f"homeassistant/epaper_panel/{obj_id}/attributes"

            if obj_id not in _mqtt_discovered_ids:
                cfg_payload = {
                    "name": fname,
                    "unique_id": f"epaper_studio_{obj_id}",
                    "default_entity_id": f"sensor.{obj_id}",
                    "object_id": obj_id,
                    "state_topic": state_topic,
                    "json_attributes_topic": attr_topic,
                    "icon": icon,
                    "device": dev_info,
                }
                if dev_class:
                    cfg_payload["device_class"] = dev_class
                if unit:
                    cfg_payload["unit_of_measurement"] = unit
                await call_ha_service(session, "mqtt", "publish", {
                    "topic": f"homeassistant/sensor/epaper_panel/{obj_id}/config",
                    "payload": json.dumps(cfg_payload),
                    "retain": True,
                })
                _mqtt_discovered_ids.add(obj_id)

            await call_ha_service(session, "mqtt", "publish", {
                "topic": state_topic,
                "payload": str(info.get("state", "")),
                "retain": True,
            })
            clean_attrs = {k: v for k, v in attrs.items() if k not in ("friendly_name", "icon", "unit_of_measurement", "device_class")}
            await call_ha_service(session, "mqtt", "publish", {
                "topic": attr_topic,
                "payload": json.dumps(clean_attrs),
                "retain": True,
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

    quiet_active, quiet_reason = await evaluate_quiet_hours(session, spec)
    try:
        rot_sec = max(5, min(3600, int(spec.get("rotate_seconds") or 30)))
    except (TypeError, ValueError):
        rot_sec = 30

    if not live:
        cw, _ = T.canvas_dims(orient, display=display)
        empty_page = {"elements": [{"type": "text", "value": "no pages", "x": 24, "y": 60, "w": cw - 48, "h": 120}]}
        img = await asyncio.to_thread(
            layout.render_page, empty_page, {},
            clock=datetime.now().strftime("%H:%M"), label="empty", orientation=orient, display=display)
        one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
        png = _png(one)
        cat_ids = [stripmeta.identity("empty")]
        sub_ids = [stripmeta.identity("empty:0")]
        epf_data = epf.encode_epf(
            pages=[one], cat_ids=cat_ids, cat_offsets=[0], cat_sizes=[1], cat_pill_widths=[110], sub_ids=sub_ids,
            display_model=display, width=dw, height=dh, rotate_sec=rot_sec, quiet_hours=quiet_active, alert_interrupt=False
        )
        return png, png, [png], [], [0], [1], ["empty"], [110], quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_data, epf_data

    vals = await gather_values(session, spec, set(live))

    series = {}
    for name in set(live):
        for i, el in enumerate(spec["pages"][name].get("elements", [])):
            if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
                series.setdefault(name, {})[i] = await curve_series(
                    session, el["entity"], int(el.get("hours", 24)))

    imgs = []
    cat_offsets = []
    cat_sizes = []
    cat_names = []
    cat_pill_widths = []
    cat_sub_keys = []

    for cat_i, cat_name in enumerate(live):
        page_def = spec["pages"][cat_name]
        page_vals = vals.get(cat_name, {})
        elements = page_def.get("elements", [])

        # Fetch any uncached feed items
        for el in elements:
            ent = str(el.get("entity", ""))
            if ent.startswith("sensor.epaper_") and not ent.endswith("_count") and not ent.startswith("sensor.epaper_category_") and not ent.startswith("sensor.epaper_panel_"):
                if ent not in _feed_items_cache:
                    try:
                        st_data = await ha_json(session, f"/states/{ent}")
                        items = (st_data.get("attributes") or {}).get("items")
                        if items:
                            _feed_items_cache[ent] = items
                    except Exception:
                        pass

        sub_count, sub_type, sub_keys, feed_items, feed_entity = subitems.inspect_category_subitems(
            page_def, page_vals, _feed_items_cache
        )
        cat_sub_keys.append(sub_keys)

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

                    # 1. Detail / Episode field
                    is_detail = (
                        (ent and (ent == feed_entity or ent == "sensor.epaper_watch") and el.get("show") == "attribute" and "detail" in str(el.get("attribute", "")).lower())
                        or ("detail" in val_str.lower() and any(k in val_str.lower() for k in ("state_attr", "states", feed_entity, "watch", "jelly", "item")))
                        or (bool(top_detail) and cur_val == top_detail)
                    )

                    # 2. Show title field
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

    slice_pngs = [_png(im) for im in imgs]
    slices_digest = hashlib.md5(b"".join(slice_pngs)).digest()
    etag_b0, etag_b1 = slices_digest[0], slices_digest[1]

    cat_ids, sub_ids = subitems.compute_identities(live, cat_sub_keys)
    meta = stripmeta.StripMeta(
        offsets=cat_offsets,
        sizes=cat_sizes,
        pill_widths=cat_pill_widths,
        cat_ids=cat_ids,
        sub_ids=sub_ids,
        quiet=quiet_active,
        rotate_seconds=rot_sec,
        content_hash=(etag_b0 << 8) | etag_b1,
        interrupt=bool(alert)
    )
    payload = stripmeta.encode(meta)
    meta_rows = stripmeta.rows_needed(len(payload), dw)

    strip = Image.new("1", (dw, dh * len(imgs) + meta_rows), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * dh))
    stripmeta.paint(strip, dh * len(imgs), payload)

    epf_data = epf.encode_epf(
        pages=imgs,
        cat_ids=cat_ids,
        cat_offsets=cat_offsets,
        cat_sizes=cat_sizes,
        cat_pill_widths=cat_pill_widths,
        sub_ids=sub_ids,
        display_model=display,
        width=dw,
        height=dh,
        rotate_sec=rot_sec,
        quiet_hours=quiet_active,
        alert_interrupt=bool(alert),
        orientation_180=(orient == 180),
        content_hash=int.from_bytes(slices_digest[:8], "big"),
    )
    epf_single = epf.extract_page_epf(epf_data, 0)

    return _png(strip), slice_pngs[0], slice_pngs, live, cat_offsets, cat_sizes, cat_names, cat_pill_widths, quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_data, epf_single


async def refresh_frames(session):
    """Build a new Frames snapshot and atomically swap FRAMES."""
    res = await build_frames(session)
    strip, single, slices, names, cat_offsets, cat_sizes, cat_names, cat_pill_widths, quiet_active, quiet_reason, rot_sec, cat_ids, sub_ids, epf_strip, epf_single = res
    old_f = globals().get("FRAMES")
    has_prev = old_f is not None and getattr(old_f, "rendered_at", None)
    struct_changed = (
        has_prev and (
            old_f.cat_offsets != cat_offsets or
            old_f.cat_sizes != cat_sizes or
            old_f.cat_names != cat_names or
            getattr(old_f, "cat_pill_widths", None) != cat_pill_widths or
            getattr(old_f, "cat_ids", None) != cat_ids or
            getattr(old_f, "sub_ids", None) != sub_ids
        )
    )
    quiet_changed = bool(has_prev and getattr(old_f, "quiet_active", False) != quiet_active)
    rot_changed = bool(has_prev and getattr(old_f, "rotate_seconds", 30) != rot_sec)
    nxt = Frames()
    nxt.strip, nxt.single, nxt.slices, nxt.names = strip, single, slices, names
    nxt.strip_etag = _etag(strip)
    nxt.single_etag = _etag(single)
    nxt.epf_strip = epf_strip
    nxt.epf_single = epf_single
    nxt.epf_strip_etag = f'"{hashlib.blake2s(epf_strip, digest_size=8).hexdigest()}"'
    nxt.epf_single_etag = f'"{hashlib.blake2s(epf_single, digest_size=8).hexdigest()}"'
    if has_prev and old_f.strip_etag == nxt.strip_etag and getattr(old_f, "last_modified", ""):
        nxt.last_modified = old_f.last_modified
    else:
        nxt.last_modified = formatdate(timeval=None, localtime=False, usegmt=True)
    nxt.rendered_at = datetime.now().isoformat(timespec="seconds")
    nxt.cat_offsets = cat_offsets
    nxt.cat_sizes = cat_sizes
    nxt.cat_names = cat_names
    nxt.cat_pill_widths = cat_pill_widths
    nxt.cat_ids = cat_ids
    nxt.sub_ids = sub_ids
    nxt.cat_count = len(cat_offsets)
    nxt.quiet_active = quiet_active
    nxt.quiet_reason = quiet_reason
    nxt.rotate_seconds = rot_sec
    globals()["FRAMES"] = nxt
    print(f"rendered {names} ({len(strip)}B strip, {nxt.cat_count} cats, offsets: {cat_offsets}, sizes: {cat_sizes}, rot: {rot_sec}s, quiet: {quiet_active} [{quiet_reason}])", flush=True)
    await publish_category_sensors(session, nxt)
    if quiet_changed:
        print(f"Quiet Hours state transitioned to {quiet_active} ({quiet_reason}) -- syncing panel state", flush=True)
        globals()["LAST_PANEL_PUSH_TIME"] = time.time()
        await push_panel_update(advance_page=False)
    elif struct_changed or rot_changed:
        spec = load_layouts()
        allow_alerts = bool((spec.get("quiet_hours") or {}).get("allow_alerts", True))
        if quiet_active and not (ALERT["name"] and allow_alerts):
            print(f"Layout/rotation changed during Quiet Hours ({quiet_reason}) -- deferring panel push", flush=True)
        else:
            print("Category structure or rotation interval changed -- pushing immediate refresh to panel", flush=True)
            globals()["LAST_PANEL_PUSH_TIME"] = time.time()
            await push_panel_update(advance_page=False)
    return nxt


LAST_PANEL_PUSH_TIME = time.time()


async def push_panel_update(advance_page=False):
    """Trigger the physical panel to fetch latest frames (without clobbering locks or sub_mode)."""
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
            spec = load_layouts()
            allow_alerts = bool((spec.get("quiet_hours") or {}).get("allow_alerts", True))
            if cur_alert != was_alert:
                was_alert = cur_alert
                LAST_PANEL_PUSH_TIME = time.time()
                if not FRAMES.quiet_active or allow_alerts:
                    # Immediately push when an alert seizes or releases the screen.
                    await push_panel_update(advance_page=False)
            else:
                panel_cfg = load_panel_setup()
                m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
                panel_min = int(m_int.group(0)) if m_int else 5
                panel_sec = max(30, panel_min * 60)
                now = time.time()
                if now - LAST_PANEL_PUSH_TIME >= panel_sec:
                    LAST_PANEL_PUSH_TIME = now
                    if FRAMES.quiet_active and not (cur_alert and allow_alerts):
                        print(f"Quiet Hours active ({FRAMES.quiet_reason}) -- suppressing background panel refresh push", flush=True)
                    else:
                        print(f"proactive refresh push to panel ({panel_min} min interval)", flush=True)
                        await push_panel_update(advance_page=False)
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
    quiet_on = bool(f and getattr(f, "quiet_active", False))
    rot_sec = "0" if quiet_on else str(spec.get("rotate_seconds", 30))
    panel_cfg = load_panel_setup()
    m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
    panel_int = int(m_int.group(0)) if m_int else 5
    last_mod = (getattr(f, "last_modified", "") if f is not None else "") or formatdate(timeval=None, localtime=False, usegmt=True)

    h = {
        "Cache-Control": "no-cache",
        "Last-Modified": last_mod,
        "X-Next-Refresh-Seconds": str(panel_int * 60),
        "X-Rotate-Seconds": rot_sec,
        "X-Quiet-Hours": "1" if quiet_on else "0",
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
    page_q = request.query.get("page")
    body = f.single
    if page_q is not None and f.slices:
        try:
            idx = max(0, min(len(f.slices) - 1, int(page_q)))
            body = f.slices[idx]
        except (ValueError, TypeError):
            body = f.single
    etag = _etag(body)
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=etag, page_count=1))
    return web.Response(body=body, content_type="image/png", headers=_frame_headers(f=f, etag=etag, page_count=1))


async def frames_png(request):
    _check_frame_auth(request)
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.strip_etag and request.headers.get("If-None-Match") == f.strip_etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))
    return web.Response(body=f.strip, content_type="image/png", headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))


async def frame_epf(request):
    _check_frame_auth(request)
    f = FRAMES
    if not getattr(f, "epf_strip", None):
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    page_q = request.query.get("page")
    body = getattr(f, "epf_single", None)
    if page_q is not None and getattr(f, "epf_strip", None):
        try:
            page_idx = max(0, min(len(f.names) - 1, int(page_q)))
            body = epf.extract_page_epf(f.epf_strip, page_idx)
        except (ValueError, TypeError, IndexError):
            body = getattr(f, "epf_single", None)
    if not body:
        body = epf.extract_page_epf(f.epf_strip, 0)
    etag = f'"{hashlib.blake2s(body, digest_size=8).hexdigest()}"'
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=etag, page_count=1))
    h = _frame_headers(f=f, etag=etag, page_count=1)
    h["Content-Type"] = "application/octet-stream"
    h["X-EPF-Version"] = "3.0"
    return web.Response(body=body, headers=h)


async def frames_epf(request):
    _check_frame_auth(request)
    f = FRAMES
    if not getattr(f, "epf_strip", None):
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    etag = getattr(f, "epf_strip_etag", "")
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=etag, page_count=len(f.names)))
    h = _frame_headers(f=f, etag=etag, page_count=len(f.names))
    h["Content-Type"] = "application/octet-stream"
    h["X-EPF-Version"] = "3.0"
    return web.Response(body=f.epf_strip, headers=h)


async def editor_strip_epf(request):
    f = FRAMES
    if not getattr(f, "epf_strip", None):
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    return web.Response(body=f.epf_strip, headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-cache"})


async def api_manifest(request):
    _check_frame_auth(request)
    f = FRAMES
    return web.json_response({
        "page_count": len(f.names),
        "cat_count": f.cat_count,
        "cat_offsets": f.cat_offsets,
        "cat_sizes": f.cat_sizes,
        "cat_names": f.cat_names,
        "cat_ids": getattr(f, "cat_ids", []),
        "sub_ids": getattr(f, "sub_ids", []),
        "quiet_active": f.quiet_active,
        "quiet_reason": f.quiet_reason,
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
        "cat_ids": getattr(f, "cat_ids", []),
        "sub_ids": getattr(f, "sub_ids", []),
        "quiet_active": f.quiet_active,
        "quiet_reason": f.quiet_reason,
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
        "cat_ids": getattr(f, "cat_ids", []),
        "sub_ids": getattr(f, "sub_ids", []),
        "quiet_active": f.quiet_active,
        "quiet_reason": f.quiet_reason,
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
    by_id = {}
    if not HA_TOKEN:
        states = load_fixture().get("states", {})
        for eid, info in states.items():
            by_id[eid] = {
                "entity_id": eid,
                "name": info.get("friendly_name") or eid,
                "state": info.get("state"),
                "unit": info.get("unit") or "",
                "is_epaper": eid.startswith("sensor.epaper_"),
            }
    else:
        if time.time() - _entity_cache["at"] >= 30 or not _entity_cache["items"]:
            try:
                states = await ha_json(SHARED_SESSION, "/states")
            except Exception as exc:
                return web.json_response({"error": repr(exc)}, status=502)
            _entity_cache.update(at=time.time(), items=states)
        for s in (_entity_cache["items"] or []):
            if isinstance(s, dict) and "entity_id" in s:
                eid = s["entity_id"]
                attrs = s.get("attributes") or {}
                by_id[eid] = {
                    "entity_id": eid,
                    "name": attrs.get("friendly_name") or eid,
                    "state": s.get("state"),
                    "unit": attrs.get("unit_of_measurement") or "",
                    "is_epaper": eid.startswith("sensor.epaper_") or attrs.get("source") == "epaper_studio",
                }

    # Always merge live E-Paper Studio published entities so newly added widgets appear immediately
    for eid, info in _epaper_published_entities.items():
        attrs = info.get("attributes") or {}
        by_id[eid] = {
            "entity_id": eid,
            "name": attrs.get("friendly_name") or eid,
            "state": info.get("state"),
            "unit": attrs.get("unit_of_measurement") or "",
            "is_epaper": True,
        }

    items = sorted(by_id.values(), key=lambda e: (0 if e.get("is_epaper") else 1, e["entity_id"]))
    return web.json_response(items)


async def api_attributes(request):
    """Attribute names and sample values for one entity."""
    eid = (request.query.get("entity") or "").strip()
    if not valid_entity_id(eid):
        return web.json_response([])

    if eid in _epaper_published_entities:
        attrs = dict(_epaper_published_entities[eid].get("attributes") or {})
    elif not HA_TOKEN:
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
        if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
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
    lat = request.query.get("lat")
    lon = request.query.get("lon")
    aircraft = await fetch_overhead_aircraft(SHARED_SESSION, radius_km=radius, lat=lat, lon=lon)
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


def _inspect_existing_secrets() -> set[str]:
    """Scan /config/esphome/secrets.yaml for declared secret keys."""
    for p in (Path("/config/esphome/secrets.yaml"), Path(__file__).parent / "secrets.yaml"):
        if p.exists() and p.is_file():
            found = set()
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k = line.split(":", 1)[0].strip()
                        if k:
                            found.add(k)
                if found:
                    return found
            except Exception:
                pass
    return set()


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
    frames_epf_url = f"{base_url}/frames.epf{token_q}"
    frame_epf_url = f"{base_url}/frame.epf{token_q}"

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

    known_secrets = _inspect_existing_secrets()
    if use_secrets and "api_encryption_key" in known_secrets:
        api_key_line = "!secret api_encryption_key"
    else:
        api_key_line = _yaml_str(api_key)

    if use_secrets and "ota_password" in known_secrets:
        ota_pw_line = "!secret ota_password"
    else:
        ota_pw_line = _yaml_str(ota_pw)

    if (use_secrets or not ssid) and "wifi_ssid" in known_secrets:
        wifi_ssid_line = "!secret wifi_ssid"
    else:
        wifi_ssid_line = _yaml_str(ssid)

    if (use_secrets or not pw) and "wifi_password" in known_secrets:
        wifi_pw_line = "!secret wifi_password"
    else:
        wifi_pw_line = _yaml_str(pw)

    extra_ext = f"\n  - source: {disp['esphome_component']}" if disp["esphome_component"].startswith("github://") else ""
    ext_comp_block = f"""external_components:
  - source: github://bek00letz/epaper-panel@main
    components: [epf]{extra_ext}

epf:
"""
    if disp["esphome_component"].startswith("github://"):
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
  frames_epf_url: {_yaml_str(frames_epf_url)}
  frame_epf_url:  {_yaml_str(frame_epf_url)}
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
  - id: cat_sub_pos
    type: std::vector<int>
    restore_value: false
  - id: cat_ids
    type: std::vector<uint32_t>
    restore_value: false
  - id: sub_ids
    type: std::vector<uint32_t>
    restore_value: false
  - id: pinned_cat_id
    type: uint32_t
    restore_value: false
    initial_value: '0'
  - id: pinned_sub_id
    type: uint32_t
    restore_value: false
    initial_value: '0'
  - id: cur_cat_id
    type: uint32_t
    restore_value: false
    initial_value: '0'
  - id: cur_sub_id
    type: uint32_t
    restore_value: false
    initial_value: '0'
  - id: sub_mode
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: idle_sec
    type: int
    restore_value: false
    initial_value: '0'
  - id: rotate_sec
    type: int
    restore_value: false
    initial_value: '30'
  - id: fetch_idle_sec
    type: int
    restore_value: false
    initial_value: '0'
  - id: user_cool_sec
    type: int
    restore_value: false
    initial_value: '999'
  - id: pending_refetch
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: pending_redraw
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: last_strip_hash
    type: int
    restore_value: false
    initial_value: '-1'
  - id: last_drawn_page
    type: int
    restore_value: false
    initial_value: '-1'
  - id: last_ok_press_ms
    type: uint32_t
    restore_value: false
    initial_value: '0'
  - id: downloading_frames
    type: bool
    restore_value: false
    initial_value: 'false'
  - id: quiet_hours_active
    type: bool
    restore_value: false
    initial_value: 'false'

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
        - script.execute: request_refetch
    - action: show_page
      variables:
        index: int
      then:
        - lambda: |-
            epf::PanelController::instance().show_page(index);
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: show_category
      variables:
        category: int
        sub: int
      then:
        - lambda: |-
            epf::PanelController::instance().show_category(category, sub);
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: page_step
      variables:
        delta: int
      then:
        - lambda: |-
            epf::PanelController::instance().page_step(delta);
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: mode_toggle
      then:
        - lambda: |-
            epf::PanelController::instance().mode_toggle();
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: category_step
      variables:
        delta: int
      then:
        - lambda: |-
            epf::PanelController::instance().category_step(delta);
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: sub_step
      variables:
        delta: int
      then:
        - lambda: |-
            epf::PanelController::instance().sub_step(delta);
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: hold_toggle
      then:
        - lambda: |-
            epf::PanelController::instance().hold_toggle();
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: category_pin_toggle
      then:
        - lambda: |-
            epf::PanelController::instance().category_pin_toggle();
            SYNC_PANEL_GLOBALS();
        - script.execute: redraw
    - action: lock_toggle
      then:
        - lambda: |-
            epf::PanelController::instance().lock_toggle();
            SYNC_PANEL_GLOBALS();
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
      if (id(downloading_frames)) {{
        return;
      }}
      if (epf::EpfClient::instance().has_stream()) {{
        int cur_page = epf::PanelController::instance().page();
        // 1. Direct scanline blit into display buffer: ~80 microseconds!
        epf::EpfClient::instance().blit_to_display(id(epd), cur_page);

        // 2. Fast direct overlays (active pill inversion & solid padlock badge): <50 microseconds!
        epf::PanelController::instance().draw_overlays(id(epd), {dw}, {dh});
      }} else if (id(have_frames)) {{
        // Fallback for legacy PNG strip
        const int off = ${{page_h}} * id(page);
        for (int y = 0; y < ${{page_h}}; y++) {{
          for (int x = 0; x < {dw}; x++) {{
            it.draw_pixel_at(x, y, id(frames).get_pixel(x, y + off));
          }}
        }}
        epf::PanelController::instance().draw_overlays(id(epd), {dw}, {dh});
      }} else if (id(have_single)) {{
        it.image(0, 0, id(frame));
      }} else {{
        it.print(40, 40, id(diag_big), "panel alive");
        it.printf(40, 130, id(diag_small), "ip: %s", id(wifi_ip).state.c_str());
        it.printf(40, 170, id(diag_small), "waiting for %s", "frames.epf");
      }}

http_request:
  verify_ssl: false
  timeout: 15s
  buffer_size_rx: 4096

online_image:
  - id: frames
    url: ${{frames_url}}
    format: png
    type: BINARY
    buffer_size: 4096
    on_download_finished:
      - lambda: |-
          id(downloading_frames) = false;
          int h = id(frames).get_height();
          id(page_count) = (h >= ${{page_h}}) ? h / ${{page_h}} : 1;
          id(have_frames) = true;
          int new_strip_hash = -1;

          epf::EpfHeader fake_hdr = {{}};
          fake_hdr.page_count = id(page_count);
          fake_hdr.cat_count = id(cat_count);
          fake_hdr.rotate_sec = id(rotate_sec);
          fake_hdr.flags = (id(quiet_hours_active) ? 0x0002 : 0);
          std::vector<epf::EpfCategoryRecord> fake_cats;
          for (size_t c = 0; c < id(cat_offsets).size(); c++) {{
            epf::EpfCategoryRecord cr = {{}};
            cr.cat_id = (c < id(cat_ids).size()) ? id(cat_ids)[c] : 0;
            cr.offset_page = id(cat_offsets)[c];
            cr.page_count = (c < id(cat_sizes).size()) ? id(cat_sizes)[c] : 1;
            cr.pill_width = (c < id(cat_pill_widths).size()) ? id(cat_pill_widths)[c] : 110;
            fake_cats.push_back(cr);
          }}
          std::vector<epf::EpfPageRecord> fake_pages;
          for (size_t p = 0; p < id(sub_ids).size(); p++) {{
            epf::EpfPageRecord pr = {{}};
            pr.sub_id = id(sub_ids)[p];
            fake_pages.push_back(pr);
          }}
          epf::PanelController::instance().on_stream_loaded(fake_hdr, fake_cats, fake_pages);
          SYNC_PANEL_GLOBALS();

          if (new_strip_hash != -1 && new_strip_hash == id(last_strip_hash) && !id(pending_redraw) && id(page) == id(last_drawn_page)) {{
            ESP_LOGI("panel", "Strip unchanged (HTTP 304) -- skipping physical e-paper refresh");
          }} else {{
            id(last_strip_hash) = new_strip_hash;
            id(pending_redraw) = true;
          }}
      - if:
          condition:
            lambda: 'return id(pending_redraw);'
          then:
            - script.execute: redraw
    on_error:
      - lambda: 'id(downloading_frames) = false;'
      - if:
          condition:
            lambda: 'return id(have_frames);'
          then:
            - logger.log: "frames.png fetch failed - keeping cached strip in PSRAM"
            - if:
                condition:
                  lambda: 'return id(pending_redraw);'
                then:
                  - script.execute: redraw
          else:
            - logger.log: "frames.png missing - falling back to single frame"
            - component.update: frame

  - id: frame
    url: ${{frame_url}}
    format: png
    type: BINARY
    buffer_size: 4096
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
          epf::PanelController::instance().page_step(1);
          SYNC_PANEL_GLOBALS();
      - script.execute: redraw

  - platform: gpio
    id: key_prev
    internal: true
    pin: {{number: {prev_pin}, mode: {{input: true, pullup: true}}, inverted: true}}
    filters: [delayed_on: 25ms, delayed_off: 25ms]
    on_press:
      - logger.log: "KEY prev (dial backward)"
      - lambda: |-
          epf::PanelController::instance().page_step(-1);
          SYNC_PANEL_GLOBALS();
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
              epf::PanelController::instance().mode_toggle();
              SYNC_PANEL_GLOBALS();
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
              epf::PanelController::instance().category_pin_toggle();
              SYNC_PANEL_GLOBALS();
          - script.execute: redraw
      - min_length: 750ms
        max_length: 6000ms
        then:
          - logger.log: "KEY top: long hold (toggle panel lock)"
          - lambda: |-
              epf::PanelController::instance().hold_toggle();
              SYNC_PANEL_GLOBALS();
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
              epf::PanelController::instance().reset_home();
              SYNC_PANEL_GLOBALS();
          - script.execute: redraw
      - min_length: 750ms
        max_length: 6000ms
        then:
          - logger.log: "KEY bottom: long hold (force refetch)"
          - lambda: |-
              id(idle_sec) = 0;
              id(fetch_idle_sec) = 0;
              id(pending_refetch) = false;
              id(pending_redraw) = true;
          - script.execute: refetch

sensor:
  - platform: wifi_signal
    id: wifi_rssi
    name: Panel Wi-Fi
    update_interval: 60s

text_sensor:
  - platform: wifi_info
    ip_address:
      id: wifi_ip
      name: Panel IP

script:
  - id: redraw
    mode: restart
    then:
      - delay: 80ms
      - if:
          condition:
            lambda: 'return !id(downloading_frames);'
          then:
            - lambda: |-
                id(pending_redraw) = false;
                epf::PanelController::instance().clear_pending_redraw();
                id(last_drawn_page) = id(page);
                if (epf::PanelController::instance().check_settle_clear()) {{
                  id(epd).force_full_update();
                  epf::PanelController::instance().record_full_update();
                }} else {{
                  epf::PanelController::instance().record_partial_update();
                }}
            - component.update: epd

  - id: request_refetch
    mode: restart
    then:
      - if:
          condition:
            lambda: |-
              if (id(downloading_frames)) {{
                id(pending_refetch) = true;
                return false;
              }}
              if (epf::PanelController::instance().should_defer_refetch()) {{
                id(pending_refetch) = true;
                ESP_LOGI("panel", "Manual scroll active (cooldown %ds/15s) -- deferring background refetch",
                         epf::PanelController::instance().user_cool_sec());
                return false;
              }}
              return true;
          then:
            - script.execute: refetch

  - id: refetch
    mode: single
    then:
      - wait_until:
          condition:
            wifi.connected:
          timeout: 30s
      - lambda: |-
          id(downloading_frames) = true;
          id(pending_refetch) = false;
          id(fetch_idle_sec) = 0;
          epf::PanelController::instance().reset_fetch_idle();
          epf::PanelController::instance().set_pending_refetch(false);

          std::string target_url = "${{frames_epf_url}}";

          epf::FetchResult res = epf::EpfClient::instance().fetch(target_url);
          id(downloading_frames) = false;

          if (res == epf::FetchResult::NOT_MODIFIED) {{
            ESP_LOGI("panel", "HTTP 304 Not Modified -- 0 bytes downloaded, skipping refresh");
          }} else if (res == epf::FetchResult::OK) {{
            id(have_frames) = true;
            epf::PanelController::instance().on_stream_loaded(
              epf::EpfClient::instance().header(),
              epf::EpfClient::instance().categories(),
              epf::EpfClient::instance().pages()
            );
            SYNC_PANEL_GLOBALS();
            if (epf::EpfClient::instance().is_alert_interrupt() || epf::EpfClient::instance().is_force_full_waveform()) {{
              id(epd).force_full_update();
              epf::PanelController::instance().record_full_update();
            }}
            id(pending_redraw) = true;
            epf::PanelController::instance().set_pending_redraw();
          }} else {{
            ESP_LOGW("panel", "EPF fetch failed (code %d) -- falling back to legacy frames.png", (int)res);
            id(downloading_frames) = true;
          }}
      - if:
          condition:
            lambda: 'return id(downloading_frames);'
          then:
            - component.update: frames
          else:
            - if:
                condition:
                  lambda: 'return id(pending_redraw);'
                then:
                  - script.execute: redraw

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
  - interval: 5s
    then:
      - lambda: |-
          epf::PanelController::instance().tick_seconds(5);
          id(idle_sec) = epf::PanelController::instance().idle_sec();
          id(fetch_idle_sec) = epf::PanelController::instance().fetch_idle_sec();
          id(user_cool_sec) = epf::PanelController::instance().user_cool_sec();
      # 1. If a background refetch was deferred while user was scrolling, run once cooldown elapses
      - if:
          condition:
            lambda: |-
              return id(pending_refetch) && !epf::PanelController::instance().should_defer_refetch() && !id(downloading_frames);
          then:
            - logger.log: "Manual scroll cooldown complete (15s) -- running deferred background refetch"
            - script.execute: refetch
      # 2. Local PSRAM Page Rotation
      - if:
          condition:
            lambda: |-
              if (id(downloading_frames)) return false;
              bool rotated = epf::PanelController::instance().check_auto_rotate();
              if (rotated) {{
                SYNC_PANEL_GLOBALS();
                return true;
              }}
              return false;
          then:
            - script.execute: redraw
      # 3. Periodic Background Network Data Fetch
      - if:
          condition:
            lambda: |-
              if (epf::PanelController::instance().quiet_hours_active() || id(downloading_frames)) return false;
              int fetch_target = (int)(id(panel_refresh_interval).state * 60.0);
              if (fetch_target < 30) fetch_target = 30;
              return (epf::PanelController::instance().fetch_idle_sec() >= fetch_target);
          then:
            - lambda: 'id(fetch_idle_sec) = 0;'
            - script.execute: request_refetch
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
    esphome_dir = Path("/config/esphome")
    esphome_synced = False
    if esphome_dir.exists() and esphome_dir.is_dir():
        try:
            device_slug = re.sub(r"[^a-z0-9_]+", "_", saved.get("device_name", "crowpanel-epaper").lower()).strip("_") or "crowpanel_epaper"
            target_yaml = esphome_dir / f"{device_slug}.yaml"
            target_yaml.write_text(yaml_text, encoding="utf-8")
            esphome_synced = True
            print(f"Auto-synced ESPHome config to {target_yaml}", flush=True)
        except Exception as e:
            print(f"Could not auto-sync to /config/esphome: {e}", flush=True)
    conn = await _detect_panel_connection(saved["device_name"])
    return web.json_response({
        "saved": True,
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "esphome_synced": esphome_synced,
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


async def api_epf_client_h(request):
    """Serve epf_client.h companion header for ESPHome compilation."""
    f = Path(__file__).parent / "epf_client.h"
    if not f.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={
        "Content-Type": "text/x-c",
        "Content-Disposition": 'attachment; filename="epf_client.h"',
        "Cache-Control": "no-cache",
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
        web.get("/frame.epf", frame_epf),
        web.get("/frames.epf", frames_epf),
        web.get("/epf_client.h", api_epf_client_h),
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
        web.get("/api/strip.epf", editor_strip_epf),
        web.get("/api/epf_client.h", api_epf_client_h),
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
