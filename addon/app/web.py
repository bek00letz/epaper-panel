"""The two HTTP faces: frames on the LAN port, the editor and its API behind Ingress."""

import health
import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from pathlib import Path
from aiohttp import web

import feeds
import live_data
from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import airports
import config
import frame_token
import runtime
from config import ADDON_VERSION, FRAME_PORT, HA_BASE, HA_TOKEN, INGRESS_GATEWAY, REFRESH, SLEEP_PAGE, WEB_DIR, valid_entity_id
from fixture import load_fixture
from frames import _etag, _png, as_int, enrich_page_values, refresh_frames, split_page_values
from ha import curve_series, ha_json, resolve_templates
from layouts_store import clear_draft, layouts_etag, load_draft, load_layouts, load_sources, sanitize_layouts, save_draft, save_layouts
from panel_ops import push_panel_update, step_panel_page
from panel_setup import _detect_external_port, _detect_panel_connection, _new_api_key, generate_esphome_yaml, load_panel_setup, save_panel_setup
from sources.flights import fetch_overhead_aircraft


_rejected_peers: set[str] = set()


def editor_peer_allowed(peer: str, under_supervisor: bool | None = None) -> bool:
    peer = (peer or "").removeprefix("::ffff:")
    if config.UNDER_SUPERVISOR if under_supervisor is None else under_supervisor:
        return peer == INGRESS_GATEWAY
    return peer in ("127.0.0.1", "::1")          # running locally for development


@web.middleware
async def ingress_only(request, handler):
    """The editor is behind Home Assistant's login; refuse anyone who isn't."""
    peer = request.remote or ""
    if not editor_peer_allowed(peer):
        if peer not in _rejected_peers:
            _rejected_peers.add(peer)
            print(f"editor: refused a connection from {peer} (not Home Assistant's Ingress)", flush=True)
        raise web.HTTPForbidden(text="Open the editor from the Home Assistant sidebar.")
    return await handler(request)


def _provided_token(request) -> str:
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return request.query.get("token") or request.headers.get("X-Frame-Token") or ""


def _require_frame_token(request):
    """LAN endpoints that make the add-on or the panel do something: always
    need the token, even while plain frame downloads are still switching over."""
    if frame_token.check(_provided_token(request)) != "ok":
        raise web.HTTPUnauthorized(text="This needs the frame token (Panel setup shows it in the panel's YAML).")


def _check_frame_auth(request):
    """Frames and status on the LAN port (see frame_token for the switch-over)."""
    result = frame_token.check(_provided_token(request))
    if result == "wrong" or (result == "missing" and frame_token.required()):
        raise web.HTTPUnauthorized(text="invalid or missing token")


def _frame_headers(f=None, etag=None, page_count=1):
    """Caching headers for frame responses.

    0.8.x also sent page names, category layout and the quiet-hours flag as
    X- headers. Nothing read them, and on an untokened LAN port they said more
    than a frame should (quiet hours can mean nobody is home).
    """
    last_mod = (getattr(f, "last_modified", "") if f is not None else "") or formatdate(timeval=None, localtime=False, usegmt=True)
    h = {"Cache-Control": "no-cache", "Last-Modified": last_mod}
    if etag:
        h["ETag"] = etag
    return h


async def frame_png(request):
    _check_frame_auth(request)
    f = runtime.FRAMES
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
    f = runtime.FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.strip_etag and request.headers.get("If-None-Match") == f.strip_etag:
        raise web.HTTPNotModified(headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))
    return web.Response(body=f.strip, content_type="image/png", headers=_frame_headers(f=f, etag=f.strip_etag, page_count=len(f.names)))


async def frame_epf(request):
    _check_frame_auth(request)
    f = runtime.FRAMES
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
    try:
        if "cap" in request.query and runtime.set_panel_capacity(int(request.query["cap"])):
            runtime.LIVE._event().set()                # render to the new size now
    except ValueError:
        pass
    f = runtime.FRAMES
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
    f = runtime.FRAMES
    if not getattr(f, "epf_strip", None):
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    return web.Response(body=f.epf_strip, headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-cache"})


async def api_manifest(request):
    f = runtime.FRAMES
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
    """Health check on the LAN port. Deliberately says nothing about the pages
    or why quiet hours are on: the reason can reveal whether anyone is home."""
    _check_frame_auth(request)
    f = runtime.FRAMES
    return web.json_response({
        "ok": f.error is None and bool(f.strip),
        "page_count": len(f.names),
        "rendered_at": f.rendered_at,
        "version": ADDON_VERSION,
    })


async def editor_strip_png(request):
    """Serve the rendered strip over Ingress without requiring config.FRAME_TOKEN."""
    f = runtime.FRAMES
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.strip, content_type="image/png",
                        headers={"Cache-Control": "no-cache"})


async def status(request):
    f = runtime.FRAMES
    spec = load_layouts()
    panel_cfg = load_panel_setup()
    m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
    panel_int = (await runtime.LINK.refresh_interval()) or (int(m_int.group(0)) if m_int else 5)
    return web.json_response({
        "pages": [n for n in f.names if n != SLEEP_PAGE],
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
        "esphome_device": runtime.ESPHOME_DEVICE,
        "active_alert": runtime.ALERT.get("name"),
        "frame_port": FRAME_PORT,
        "display": spec.get("display", T.DEFAULT_DISPLAY),
        "orientation": int(spec.get("orientation") or 0),
        "panel_link": runtime.LINK.status(),
        "live_data": runtime.LIVE.status(),
        # Every outside service and data source: last success, and the problem
        # if it is failing (also a problem sensor in Home Assistant).
        "services": health.status(),
        # How many pages the panel holds, and what was left out to fit.
        "fit": runtime.FIT,
        "ha_entities": runtime.PUBLISHER.status() if runtime.PUBLISHER is not None else
                       {"mode": "off", "problem": "not started", "entities": 0},
        "version": ADDON_VERSION,
    })


async def api_panel_refresh(request):
    """Update panel refresh rate both in saved panel setup and via HA service if online."""
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

    runtime.LAST_PANEL_PUSH_TIME = time.time()

    # Pre-render latest frames immediately so the panel gets fresh data
    try:
        await refresh_frames(runtime.SESSION)
    except Exception:
        pass

    # The panel's own interval entity is what it actually uses; set it there.
    ha_updated, err = await runtime.LINK.set_refresh_interval(minutes)
    if not ha_updated:
        print(f"panel: couldn't set refresh interval: {err}", flush=True)
    await push_panel_update("refresh interval changed")

    return web.json_response({
        "saved": True,
        "interval": minutes,
        "ha_updated": ha_updated,
        "error": err or None,
    })


def _quoted(tag: str) -> str:
    return f'"{tag}"'


def _if_match(request) -> str | None:
    """The version a client says it edited, or None when it didn't say."""
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    return raw.strip().removeprefix("W/").strip('"')


async def api_layouts_get(request):
    spec = load_layouts()
    return web.json_response(spec, headers={"ETag": _quoted(layouts_etag(spec))})


async def api_layouts_put(request):
    spec = await request.json()
    if not isinstance(spec, dict) or "pages" not in spec:
        raise web.HTTPBadRequest(text="expected {rotation, pages}")
    try:
        clean = sanitize_layouts(spec)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    # A client that says which version it edited gets a 409 if someone saved
    # in between, with what's there now so it can merge. Without If-Match the
    # save goes through as it always has.
    expected = _if_match(request)
    if expected is not None and expected != "*":
        current = load_layouts()
        current_tag = layouts_etag(current)
        if expected != current_tag:
            return web.json_response({"error": "These pages were changed somewhere else since you opened them.",
                                      "current": current, "etag": current_tag},
                                     status=409, headers={"ETag": _quoted(current_tag)})
    save_layouts(clean)
    clear_draft()                                         # sent: nothing is waiting any more
    tag = layouts_etag(load_layouts())
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"immediate render after save failed: {health.describe(exc)}", flush=True)
    return web.json_response({
        "saved": True,
        "display": clean.get("display", T.DEFAULT_DISPLAY),
        "pages": list(clean["pages"]),
        "rotation": clean["rotation"],
        "rotate_seconds": clean["rotate_seconds"],
        "orientation": clean["orientation"],
        "etag": tag,
    }, headers={"ETag": _quoted(tag)})


async def api_draft_get(request):
    """Unsent editor changes, and the version of what's live."""
    return web.json_response({"draft": load_draft(), "etag": layouts_etag()})


async def api_draft_put(request):
    """Save the editor's changes as you go, without sending them to the panel.

    Body: {spec, base, base_etag}: the pages as edited, and the live pages they
    started from. If-Match carries the draft version the client last saw; on a
    mismatch (another window saved, or the draft was sent) the answer is 409
    with the current draft and the live pages, so the client can merge.
    """
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("spec"), dict):
        raise web.HTTPBadRequest(text="expected {spec, base, base_etag}")
    try:
        spec = sanitize_layouts(body["spec"])
        base = sanitize_layouts(body["base"]) if isinstance(body.get("base"), dict) else None
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    current = load_draft()
    version = int(current.get("version") or 0) if current else 0
    expected = _if_match(request)
    if expected is not None and expected != "*" and expected != str(version):
        live = load_layouts()
        return web.json_response({"error": "These pages were changed in another window.",
                                  "draft": current, "live": live, "etag": layouts_etag(live)}, status=409)
    draft = {"version": version + 1, "base_etag": str(body.get("base_etag") or ""),
             "base": base, "spec": spec, "saved_at": time.time()}
    save_draft(draft)
    return web.json_response({"saved": True, "version": draft["version"]})


async def api_panel_device_get(request):
    """The panel's Sleep and ghost-clearing settings, read through Home Assistant."""
    return web.json_response(await runtime.LINK.device_settings())


async def api_panel_device_post(request):
    """Change one panel setting: {sleep: bool} | {ghost_after: n} | {ghost_mode: s} | {clear_ghosting: true}."""
    body = await request.json()
    if not isinstance(body, dict) or len(body) != 1:
        raise web.HTTPBadRequest(text="expected one setting")
    key, value = next(iter(body.items()))
    ok, err = await runtime.LINK.set_device_setting(key, value)
    return web.json_response({"ok": ok, "error": err or None}, status=200 if ok or key in
                             ("sleep", "ghost_after", "ghost_mode", "clear_ghosting") else 400)


async def api_draft_delete(request):
    """Throw away unsent changes (the editor offers this as one undoable step)."""
    clear_draft()
    return web.json_response({"cleared": True})


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
        if time.time() - runtime.ENTITY_CACHE["at"] >= 30 or not runtime.ENTITY_CACHE["items"]:
            try:
                states = await ha_json(runtime.SESSION, "/states")
            except Exception as exc:
                return web.json_response({"error": health.describe(exc)}, status=502)
            runtime.ENTITY_CACHE.update(at=time.time(), items=states)
        for s in (runtime.ENTITY_CACHE["items"] or []):
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
    for eid, info in runtime.PUBLISHED.items():
        attrs = info.get("attributes") or {}
        by_id[eid] = {
            "entity_id": eid,
            "name": attrs.get("friendly_name") or eid,
            "state": info.get("state"),
            "unit": attrs.get("unit_of_measurement") or "",
            "is_epaper": True,
        }

    # Which source made a sensor, so a preset can offer exactly those.
    for src in load_sources():
        made = by_id.get(f"sensor.epaper_{src.get('name')}")
        if made is not None and src.get("type"):
            made["feed"] = str(src["type"])

    items = sorted(by_id.values(), key=lambda e: (0 if e.get("is_epaper") else 1, e["entity_id"]))
    return web.json_response(items)


async def api_attributes(request):
    """Attribute names and sample values for one entity."""
    eid = (request.query.get("entity") or "").strip()
    if not valid_entity_id(eid):
        return web.json_response([])

    if eid in runtime.PUBLISHED:
        attrs = dict(runtime.PUBLISHED[eid].get("attributes") or {})
    elif not HA_TOKEN:
        attrs = dict((load_fixture().get("states") or {}).get(eid) or {})
        attrs.pop("state", None)
    else:
        safe_eid = urllib.parse.quote(eid, safe=".")
        try:
            st = await ha_json(runtime.SESSION, f"/states/{safe_eid}")
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
    if not isinstance(body, dict) or not isinstance(body.get("page") or {}, dict):
        raise web.HTTPBadRequest(text="expected {page}")
    page = body.get("page") or {}
    try:
        orient = int(body.get("orientation") if "orientation" in body else load_layouts().get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = body.get("display") or load_layouts().get("display", T.DEFAULT_DISPLAY)
    vals, tpls = split_page_values(page)
    if tpls:
        vals.update(await resolve_templates(runtime.SESSION, tpls))
    with live_data.waiting_for_fresh():                   # someone is looking at this preview
        await enrich_page_values(runtime.SESSION, page, vals)
    series = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
            series[i] = await curve_series(runtime.SESSION, el["entity"], as_int(el.get("hours"), 24))
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


async def api_airport(request):
    """A three-letter airport code, as a place for the flight widget."""
    code = (request.query.get("code") or "").strip()
    found = airports.lookup(code)
    if not found:
        return web.json_response({"error": f"No airport with the code “{code.upper()[:8]}”."}, status=404)
    return web.json_response(found)


async def api_aircraft(request):
    try:
        radius = float(request.query.get("radius") or 35.0)
    except (TypeError, ValueError):
        radius = 35.0
    lat = request.query.get("lat")
    lon = request.query.get("lon")
    with live_data.waiting_for_fresh():
        aircraft = await fetch_overhead_aircraft(runtime.SESSION, radius_km=radius, lat=lat, lon=lon) or []
    return web.json_response({"aircraft": aircraft, "count": len(aircraft)})


async def api_push(request):
    """Re-render immediately and make the panel fetch and redraw now."""
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"pre-push render failed: {health.describe(exc)}", flush=True)
    delivered = await push_panel_update("pushed from the editor")
    return web.json_response({"pushed": delivered, "pending": runtime.LINK.pending is not None,
                              "error": None if delivered else runtime.LINK.last_error})


async def api_action_refresh(request):
    """LAN endpoint (scripts, webhooks) to re-render and make the panel redraw. Needs frame_token."""
    _require_frame_token(request)
    try:
        await refresh_frames(runtime.SESSION)
        ha_pushed = await push_panel_update("action endpoint")
        return web.json_response({"success": True, "action": "refresh", "ha_pushed": ha_pushed, "timestamp": datetime.now().isoformat()})
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=500)


async def api_action_page(request):
    """LAN endpoint to step the panel's page. Needs frame_token."""
    _require_frame_token(request)
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    try:
        delta = int(body.get("delta") if "delta" in body else (request.query.get("delta") or 1))
    except (TypeError, ValueError, OverflowError):
        delta = 1
    delta = max(-100, min(100, delta))                # the panel steps one page at a time
    ha_stepped = await step_panel_page(delta=delta)
    return web.json_response({"success": True, "action": "page_step", "delta": delta, "ha_stepped": ha_stepped})


async def api_sources_get(request):
    return web.json_response(feeds.mask_secrets(load_sources()))


async def api_sources_put(request):
    body = await request.json()
    if not isinstance(body, list):
        raise web.HTTPBadRequest(text="expected a list of sources")
    merged = feeds.unmask_secrets(body, load_sources())
    feeds.save(config.DATA_DIR, merged)
    return web.json_response({"saved": True, "count": len(merged),
                              "sources": feeds.mask_secrets(merged)})


async def api_sources_test(request):
    """Run one source now and report what it would publish."""
    src = await request.json()
    if not isinstance(src, dict):
        raise web.HTTPBadRequest(text="expected a source object")
    unmasked = feeds.unmask_secrets([src], load_sources())
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": runtime.SESSION}
    errors: list[str] = []
    rows = await feeds.run_all(unmasked, ctx, errors)
    return web.json_response({"published": [{"entity_id": e, "state": str(v)[:120],
                                             "attributes": a} for e, v, a in rows],
                              "error": errors[0] if errors else None})


async def api_panel_setup_get(request):
    fwd = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or ""
    host_guess = fwd.split(",")[0].strip().split(":")[0]
    if not host_guess or host_guess in ("localhost", "127.0.0.1", "0.0.0.0"):
        host_guess = "homeassistant.local"
    cfg = load_panel_setup(default_host=host_guess)
    detected_port = await _detect_external_port(runtime.SESSION)
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
        "has_frame_token": True,
        "frame_protection": frame_token.status(),
        "panel": conn,
    })


async def api_panel_setup_post(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    cur = load_panel_setup()
    if body.get("regenerate_keys"):
        cur["api_encryption_key"] = _new_api_key()
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
    for k in ("api_encryption_key",):
        if k in body and isinstance(body[k], str) and body[k].strip():
            if not body.get("regenerate_keys"):
                cur[k] = body[k].strip()
    saved = save_panel_setup(cur)
    masked_cfg = dict(saved)
    if masked_cfg.get("wifi_password"):
        masked_cfg["wifi_password"] = feeds.SECRET_MASK
    # The file the panel is built from gets the real values; only the copy
    # shown in the browser is masked. (0.9.2 and earlier wrote the mask into
    # the file when the Wi-Fi password was left untouched.)
    disk_yaml, _ = generate_esphome_yaml(saved)
    yaml_text, secrets_text = generate_esphome_yaml(masked_cfg)
    esphome_dir = config.ESPHOME_DIR
    esphome_synced = False
    if esphome_dir.exists() and esphome_dir.is_dir():
        try:
            device_slug = re.sub(r"[^a-z0-9_]+", "_", saved.get("device_name", "crowpanel-epaper").lower()).strip("_") or "crowpanel_epaper"
            target_yaml = esphome_dir / f"{device_slug}.yaml"
            previous = target_yaml.read_text(encoding="utf-8") if target_yaml.exists() else None
            if previous != disk_yaml:
                if previous is not None:
                    # A way back: ESPHome ignores this name, a rename restores it.
                    target_yaml.with_suffix(".yaml.previous").write_text(previous, encoding="utf-8")
                tmp = target_yaml.with_suffix(".yaml.tmp")
                tmp.write_text(disk_yaml, encoding="utf-8")
                tmp.replace(target_yaml)
            esphome_synced = True
            print(f"Synced ESPHome config to {target_yaml}", flush=True)
        except Exception as e:
            print(f"Could not sync to {esphome_dir}: {e}", flush=True)
    conn = await _detect_panel_connection(saved["device_name"])
    return web.json_response({
        "saved": True,
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "esphome_synced": esphome_synced,
        "frame_port": saved.get("frame_port", FRAME_PORT),
        "has_frame_token": True,
        "frame_protection": frame_token.status(),
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
    # The editor before 0.10, kept reachable until the new one has proven itself.
    name = "classic.html" if request.query.get("classic") in ("1", "true") else "index.html"
    index = WEB_DIR / name
    if not index.exists():
        return web.Response(text="Editor not built yet.", content_type="text/plain")
    return web.FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


def make_apps():
    """The LAN frame server and the Ingress-only editor."""
    panel = web.Application()
    panel.add_routes([
        web.get("/frame.png", frame_png),
        web.get("/frames.png", frames_png),
        web.get("/frame.epf", frame_epf),
        web.get("/frames.epf", frames_epf),
        web.get("/status", public_status),
        web.get("/fonts/{name}", panel_font),
        web.post("/api/action/refresh", api_action_refresh),
        web.post("/api/action/page", api_action_page),
        # Removed from the LAN port in 0.9.2: /api/layouts (exposed every
        # entity, template and custom location, with no token check at all),
        # /manifest.json and /api/manifest (page names, presence-based quiet
        # reason), and GET on the actions (a link preview could trigger them).
        # Nothing on the network used them; the editor keeps its own copies.
    ])

    editor = web.Application(client_max_size=1024 * 1024, middlewares=[ingress_only])
    editor.add_routes([
        web.get("/", editor_index),
        web.get("/api/status", status),
        web.get("/api/manifest", api_manifest),
        web.get("/api/displays", api_displays),
        web.get("/api/strip.png", editor_strip_png),
        web.get("/api/strip.epf", editor_strip_epf),
        web.get("/api/layouts", api_layouts_get),
        web.put("/api/layouts", api_layouts_put),
        web.get("/api/draft", api_draft_get),
        web.put("/api/draft", api_draft_put),
        web.delete("/api/draft", api_draft_delete),
        web.get("/api/panel-device", api_panel_device_get),
        web.post("/api/panel-device", api_panel_device_post),
        web.get("/fonts/{name}", panel_font),
        web.get("/api/entities", api_entities),
        web.get("/api/attributes", api_attributes),
        web.get("/api/aircraft", api_aircraft),
        web.get("/api/airport", api_airport),
        web.post("/api/preview", api_preview),
        web.post("/api/push", api_push),
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

    async def no_stale_editor(request, response):
        # The editor's files change with every release; never run yesterday's.
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
    editor.on_response_prepare.append(no_stale_editor)
    return panel, editor
