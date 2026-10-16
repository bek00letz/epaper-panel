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
import hashlib
import hmac
import io
import json
import os
import re
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

    if m_attr:
        eid, attr = m_attr.group(1), m_attr.group(2)
        raw = (states.get(eid) or {}).get(attr)
        val = "" if raw is None else str(raw)
        if "[:-3]" in expr and len(val) > 3:
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
    # Ensure every non-alert page is in rotation unless explicitly removed
    return {"rotation": rotation, "pages": pages}


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


async def publish_computed(session):
    """Run every configured source and publish what it returns."""
    srcs = load_sources()
    if not srcs:
        return
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": session}
    for entity_id, state, attrs in await feeds.run_all(srcs, ctx):
        await publish_entity(session, entity_id, state, attrs)


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
    alert = await check_alerts(session, spec)
    if alert and alert in spec.get("pages", {}):
        # Serve a 1-page strip while an alert is active: decodes in ~1s on
        # the ESP32 and prevents its 5-minute interval from rotating away.
        live = [alert]
    else:
        live = await eligible_pages(session, spec)

    if not live:
        empty_page = {"elements": [{"type": "text", "value": "no pages", "x": 40, "y": 60, "w": 712, "h": 120}]}
        img = await asyncio.to_thread(
            layout.render_page, empty_page, {},
            clock=datetime.now().strftime("%H:%M"), label="empty")
        one = T.to_1bit(img)
        png = _png(one)
        return png, png, []

    vals = await gather_values(session, spec, set(live))

    series = {}
    for name in set(live):
        for i, el in enumerate(spec["pages"][name].get("elements", [])):
            if el.get("type") == "curve" and el.get("entity"):
                series.setdefault(name, {})[i] = await curve_series(
                    session, el["entity"], int(el.get("hours", 24)))

    imgs = []
    for i, name in enumerate(live):
        img = await asyncio.to_thread(
            layout.render_page, spec["pages"][name], vals.get(name, {}),
            clock=datetime.now().strftime("%H:%M"),
            label=f"{name.replace('_', ' ')} \u00b7 {i + 1}/{len(live)}",
            battery_pct=None, series=series.get(name))
        imgs.append(T.to_1bit(img))

    strip = Image.new("1", (T.W, T.H * len(imgs)), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * T.H))
    return _png(strip), _png(imgs[0]), live


async def refresh_frames(session):
    """Build a new Frames snapshot and atomically swap FRAMES."""
    strip, single, names = await build_frames(session)
    nxt = Frames()
    nxt.strip, nxt.single, nxt.names = strip, single, names
    nxt.strip_etag = _etag(strip)
    nxt.single_etag = _etag(single)
    nxt.rendered_at = datetime.now().isoformat(timespec="seconds")
    globals()["FRAMES"] = nxt
    print(f"rendered {names} ({len(strip)}B strip)", flush=True)
    return nxt


async def render_loop():
    was_alert = None
    while True:
        try:
            await refresh_frames(SHARED_SESSION)
            cur_alert = ALERT["name"]
            if cur_alert != was_alert:
                # Immediately push when an alert seizes or releases the screen.
                await call_ha_service(SHARED_SESSION, "esphome",
                                      f"{ESPHOME_DEVICE}_refresh_now")
                was_alert = cur_alert
        except Exception as exc:
            print(f"render failed: {exc!r}", flush=True)
            FRAMES.error = repr(exc)
        await asyncio.sleep(REFRESH)


def _check_frame_auth(request):
    if not FRAME_TOKEN:
        return
    provided = request.query.get("token") or request.headers.get("X-Frame-Token") or ""
    if not hmac.compare_digest(provided, FRAME_TOKEN):
        raise web.HTTPUnauthorized(text="invalid or missing token")


async def frame_png(request):
    _check_frame_auth(request)
    f = FRAMES
    if not f.single:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.single_etag and request.headers.get("If-None-Match") == f.single_etag:
        raise web.HTTPNotModified(headers={"ETag": f.single_etag})
    headers = {"ETag": f.single_etag, "Cache-Control": "no-cache"} if f.single_etag else {}
    return web.Response(body=f.single, content_type="image/png", headers=headers)


async def frames_png(request):
    _check_frame_auth(request)
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.strip_etag and request.headers.get("If-None-Match") == f.strip_etag:
        raise web.HTTPNotModified(headers={"ETag": f.strip_etag})
    headers = {"ETag": f.strip_etag, "Cache-Control": "no-cache"} if f.strip_etag else {}
    return web.Response(body=f.strip, content_type="image/png", headers=headers)


async def public_status(request):
    _check_frame_auth(request)
    f = FRAMES
    return web.json_response({
        "ok": f.error is None and bool(f.strip),
        "page_count": len(f.names),
        "rendered_at": f.rendered_at,
    })


async def status(request):
    f = FRAMES
    return web.json_response({
        "pages": f.names,
        "rendered_at": f.rendered_at,
        "strip_bytes": len(f.strip),
        "error": f.error,
        "refresh_seconds": REFRESH,
        "esphome_device": ESPHOME_DEVICE,
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
    return web.json_response({"saved": True, "pages": list(clean["pages"]), "rotation": clean["rotation"]})


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
    tpls = layout.collect_templates(page)
    vals = await resolve_templates(SHARED_SESSION, tpls) if tpls else {}
    series = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") == "curve" and el.get("entity"):
            series[i] = await curve_series(SHARED_SESSION, el["entity"],
                                           int(el.get("hours", 24)))
    metrics = []
    img = await asyncio.to_thread(
        layout.render_page, page, vals,
        clock=datetime.now().strftime("%H:%M"),
        label=str(body.get("label") or "preview")[:40],
        battery_pct=None, series=series, metrics=metrics)
    # Effective font sizes ride back on a header so the editor can report
    # what you actually got, in millimetres, rather than what you asked for.
    return web.Response(body=_png(T.to_1bit(img)), content_type="image/png",
                        headers={"X-Metrics": json.dumps(metrics)})


async def api_push(request):
    """Re-render immediately and make the panel fetch and redraw now."""
    try:
        await refresh_frames(SHARED_SESSION)
    except Exception as exc:
        print(f"pre-push render failed: {exc!r}", flush=True)
    await call_ha_service(SHARED_SESSION, "esphome", f"{ESPHOME_DEVICE}_refresh_now")
    return web.json_response({"pushed": True})


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


async def editor_index(request):
    index = WEB_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Editor not built yet.", content_type="text/plain")
    return web.FileResponse(index)


async def start(app_runners):
    panel = web.Application()
    panel.add_routes([
        web.get("/frame.png", frame_png),
        web.get("/frames.png", frames_png),
        web.get("/status", public_status),
    ])

    editor = web.Application(client_max_size=1024 * 1024)
    editor.add_routes([
        web.get("/", editor_index),
        web.get("/api/status", status),
        web.get("/api/layouts", api_layouts_get),
        web.put("/api/layouts", api_layouts_put),
        web.get("/api/entities", api_entities),
        web.get("/api/attributes", api_attributes),
        web.post("/api/preview", api_preview),
        web.post("/api/push", api_push),
        web.get("/api/sources", api_sources_get),
        web.put("/api/sources", api_sources_put),
        web.post("/api/sources/test", api_sources_test),
        web.get("/api/mdi/font", api_mdi_font),
        web.get("/api/mdi/list", api_mdi_list),
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
    global SHARED_SESSION
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
