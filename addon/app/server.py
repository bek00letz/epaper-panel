#!/usr/bin/env python3
"""E-paper panel service.

Renders the rotation on a timer and serves it two ways:

  * port 8099  - frames for the panel. No auth: the panel has no credentials
                 and cannot use ingress. LAN only.
  * ingress    - the editor and its API, behind Home Assistant's own login.

Frames are held in memory and swapped by reference, so a fetch can never see
a half-written file and there is nothing to clean up on disk.
"""
import asyncio
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import web
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from render import layout, pages, sources, theme as T  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"
HA_BASE = os.environ.get("HA_BASE", "http://supervisor/core")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
REFRESH = int(os.environ.get("REFRESH_SECONDS", "60") or 60)

FRAME_PORT = 8099
INGRESS_PORT = 8080

LAYOUTS_PATH = DATA_DIR / "layouts.json"
DEFAULTS_PATH = Path(__file__).parent / "default_layouts.json"

_entity_cache = {"at": 0.0, "items": []}


def load_layouts():
    """User layouts, seeded from the shipped defaults on first run."""
    for src in (LAYOUTS_PATH, DEFAULTS_PATH):
        try:
            return json.loads(src.read_text())
        except Exception:
            continue
    return {"rotation": [], "pages": {}}


def save_layouts(spec):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(spec, indent=2))
    tmp.replace(LAYOUTS_PATH)


async def ha_json(session, path, method="GET", **kw):
    url = f"{HA_BASE}/api{path}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    async with session.request(method, url, headers=headers, **kw) as r:
        r.raise_for_status()
        return await r.json()


async def ha_template(session, tpl):
    """Render one template through Home Assistant.

    Returns "" on any failure: a page with blank values is recoverable, a
    crashed render loop is not.
    """
    url = f"{HA_BASE}/api/template"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        async with session.post(url, headers=headers, json={"template": tpl}) as r:
            if r.status != 200:
                return ""
            return (await r.text()).strip()
    except Exception:
        return ""


async def publish_entity(session, entity_id, state, attrs=None):
    """Push a computed value into Home Assistant as a real entity.

    Things the service works out -- the next unwatched title, this month's
    solar -- are useful beyond the panel, and publishing them means page
    templates are ordinary {{ states(...) }} rather than a private channel.
    """
    try:
        await ha_json(session, f"/states/{entity_id}", method="POST",
                      json={"state": str(state)[:255], "attributes": attrs or {}})
    except Exception as exc:
        print(f"publish {entity_id} failed: {exc!r}", flush=True)


async def ha_ws_statistics(statistic_id, period="month", months_back=1):
    """Long-term statistics over the websocket API.

    Statistics are websocket-only -- there is no REST endpoint -- which is
    why earlier versions read the recorder database directly. The supervisor
    token works here, so that fragility goes away.
    """
    from datetime import timedelta
    start = datetime.now().astimezone().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    url = HA_BASE.replace("http://", "ws://").replace("https://", "wss://") + "/websocket"
    try:
        async with aiohttp.ClientSession() as ses:
            async with ses.ws_connect(url, timeout=10) as ws:
                await ws.receive_json()                      # auth_required
                await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
                if (await ws.receive_json()).get("type") != "auth_ok":
                    return None
                await ws.send_json({
                    "id": 1, "type": "recorder/statistics_during_period",
                    "start_time": start.isoformat(),
                    "statistic_ids": [statistic_id],
                    "period": period, "types": ["change"],
                })
                msg = await ws.receive_json()
                rows = (msg.get("result") or {}).get(statistic_id) or []
                return sum(float(r.get("change") or 0) for r in rows)
    except Exception as exc:
        print(f"statistics for {statistic_id} failed: {exc!r}", flush=True)
        return None


SEP = "<<<|epaper|>>>"


async def resolve_templates(session, templates):
    """Render many templates in ONE request.

    Joined with a separator rather than built into a JSON literal, because
    user templates contain quotes and would break the quoting.
    """
    if not templates:
        return {}
    keys = list(templates)
    joined = f"\n{SEP}\n".join(templates[k] for k in keys)
    out = await ha_template(session, joined)
    parts = [p.strip() for p in out.split(SEP)]
    return {k: (parts[i] if i < len(parts) else "") for i, k in enumerate(keys)}


class Frames:
    """The current render. Readers take a reference; the writer replaces it."""

    def __init__(self):
        self.strip = b""
        self.single = b""
        self.names: list[str] = []
        self.rendered_at = None
        self.error = None


FRAMES = Frames()


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def curve_series(session, entity, hours=24, buckets=24):
    """Hourly means for a sparkline, from the recorder's history API."""
    start = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    start = start.replace(hour=0) if hours >= 24 else start
    path = (f"/history/period/{start.isoformat()}"
            f"?filter_entity_id={entity}&minimal_response&no_attributes")
    try:
        rows = await ha_json(session, path)
    except Exception:
        return []
    if not rows or not rows[0]:
        return []
    sums, counts = [0.0] * buckets, [0] * buckets
    for r in rows[0]:
        try:
            v = float(r["state"])
            t = datetime.fromisoformat(r["last_changed"]).astimezone()
        except (KeyError, TypeError, ValueError):
            continue
        sums[t.hour] += v
        counts[t.hour] += 1
    last = max((i for i, c in enumerate(counts) if c), default=-1)
    return [sums[i] / counts[i] if counts[i] else 0.0 for i in range(last + 1)]


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
             if n in defs and defs[n].get("show_if")}
    passed = await resolve_templates(session, gates) if gates else {}
    live = []
    for name in rotation:
        page = defs.get(name)
        if page is None or page.get("tier") == "alert":
            continue
        if name in gates and str(passed.get(name, "")).strip().lower() not in ("true", "on", "yes"):
            continue
        live.append(name)
    return live or [n for n in rotation if n in defs][:1]


async def publish_computed(session):
    """Values only this service can work out, pushed to HA before rendering."""
    key = os.environ.get("JELLYFIN_KEY") or ""
    if key:
        items = await asyncio.to_thread(
            sources.jellyfin_new, key,
            base=os.environ.get("JELLYFIN_BASE") or sources.JELLYFIN_BASE,
            user=os.environ.get("JELLYFIN_USER") or sources.JELLYFIN_USER)
        top = items[0] if items else None
        await publish_entity(session, "sensor.epaper_watch",
                             top["title"] if top else "nothing new",
                             {"detail": top["detail"] if top else "",
                              "count": len(items),
                              "titles": [i["title"] for i in items],
                              "friendly_name": "E-paper next to watch",
                              "icon": "mdi:television-play"})
        await publish_entity(session, "sensor.epaper_watch_count", len(items),
                             {"friendly_name": "E-paper new to watch",
                              "icon": "mdi:television-play"})

    month = await ha_ws_statistics("sensor.solar_total_production")
    if month is not None:
        await publish_entity(session, "sensor.epaper_solar_month", round(month, 1),
                             {"unit_of_measurement": "kWh",
                              "device_class": "energy",
                              "friendly_name": "E-paper solar this month",
                              "icon": "mdi:white-balance-sunny"})


async def build_frames(session):
    await publish_computed(session)
    spec = load_layouts()
    live = await eligible_pages(session, spec)
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
            battery_pct=0, series=series.get(name))
        imgs.append(T.to_1bit(img))

    strip = Image.new("1", (T.W, T.H * len(imgs)), 1)
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * T.H))
    return _png(strip), _png(imgs[0]), live


async def render_loop(app):
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                strip, single, names = await build_frames(session)
                nxt = Frames()
                nxt.strip, nxt.single, nxt.names = strip, single, names
                nxt.rendered_at = datetime.now().isoformat(timespec="seconds")
                globals()["FRAMES"] = nxt
                print(f"rendered {names} ({len(strip)}B strip)", flush=True)
            except Exception as exc:
                print(f"render failed: {exc!r}", flush=True)
                FRAMES.error = repr(exc)
            await asyncio.sleep(REFRESH)


async def frame_png(request):
    f = FRAMES
    if not f.single:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.single, content_type="image/png")


async def frames_png(request):
    f = FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.strip, content_type="image/png")


async def status(request):
    f = FRAMES
    return web.json_response({
        "pages": f.names,
        "rendered_at": f.rendered_at,
        "strip_bytes": len(f.strip),
        "error": f.error,
        "refresh_seconds": REFRESH,
    })


async def api_layouts_get(request):
    return web.json_response(load_layouts())


async def api_layouts_put(request):
    spec = await request.json()
    if not isinstance(spec, dict) or "pages" not in spec:
        raise web.HTTPBadRequest(text="expected {rotation, pages}")
    save_layouts(spec)
    return web.json_response({"saved": True, "pages": list(spec["pages"])})


async def api_entities(request):
    """Entity list for the picker. Cached briefly -- it is a big response."""
    import time
    if time.time() - _entity_cache["at"] < 60 and _entity_cache["items"]:
        return web.json_response(_entity_cache["items"])
    async with aiohttp.ClientSession() as session:
        try:
            states = await ha_json(session, "/states")
        except Exception as exc:
            return web.json_response({"error": repr(exc)}, status=502)
    items = sorted(
        ({"entity_id": s["entity_id"],
          "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"],
          "state": s.get("state"),
          "unit": (s.get("attributes") or {}).get("unit_of_measurement") or ""}
         for s in states),
        key=lambda e: e["entity_id"])
    _entity_cache.update(at=time.time(), items=items)
    return web.json_response(items)


async def api_preview(request):
    """Render one page spec through the real engine, so WYSIWYG cannot lie."""
    body = await request.json()
    page = body.get("page") or {}
    async with aiohttp.ClientSession() as session:
        tpls = layout.collect_templates(page)
        vals = await resolve_templates(session, tpls) if tpls else {}
        series = {}
        for i, el in enumerate(page.get("elements", [])):
            if el.get("type") == "curve" and el.get("entity"):
                series[i] = await curve_series(session, el["entity"],
                                               int(el.get("hours", 24)))
    metrics = []
    img = await asyncio.to_thread(
        layout.render_page, page, vals,
        clock=datetime.now().strftime("%H:%M"),
        label=body.get("label", "preview"),
        battery_pct=86, series=series, metrics=metrics)
    # Effective font sizes ride back on a header so the editor can report
    # what you actually got, in millimetres, rather than what you asked for.
    return web.Response(body=_png(T.to_1bit(img)), content_type="image/png",
                        headers={"X-Metrics": json.dumps(metrics)})


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
        web.get("/status", status),
    ])

    editor = web.Application()
    editor.add_routes([
        web.get("/", editor_index),
        web.get("/api/status", status),
        web.get("/api/layouts", api_layouts_get),
        web.put("/api/layouts", api_layouts_put),
        web.get("/api/entities", api_entities),
        web.post("/api/preview", api_preview),
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    runners = []
    await start(runners)
    await render_loop(None)


if __name__ == "__main__":
    asyncio.run(main())
