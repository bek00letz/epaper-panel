"""The two HTTP faces: frames on the LAN port, the editor and its API behind Ingress."""

import health
import asyncio
import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from aiohttp import web

import feeds
import live_data
from render import binding, epf, layout, sleep, stripmeta, subitems, theme as T
import airports
import companion
import config
import devices
import frame_token
import kinds
import reach
import runtime
import timing
from config import ADDON_VERSION, FRAME_PORT, HA_BASE, HA_TOKEN, INGRESS_GATEWAY, REFRESH, SLEEP_PAGE, WEB_DIR, valid_entity_id
from fixture import load_fixture
from frames import _png, as_int, enrich_page_values, refresh_frames, split_page_values
from ha import curve_series, ha_json, resolve_templates
from layouts_store import clear_draft, layouts_etag, load_draft, load_layouts, load_sources, sanitize_layouts, save_draft, save_layouts
from panel_ops import push_panel_update
from panel_setup import _detect_external_port, _detect_panel_connection, _new_api_key, generate_esphome_yaml, ha_name, hotspot_name, load_panel_setup, more_networks, save_panel_setup, wifi_problems
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


def _device(request) -> dict:
    """The device an editor request is about (?device=), or the first the add-on drives."""
    asked = request.query.get("device")
    try:
        dev = devices.resolve(asked)
    except KeyError:
        raise web.HTTPNotFound(text="There's no such screen.")
    if kinds.shown(dev):
        return dev
    if asked:
        raise web.HTTPNotFound(text="There's no such screen.")         # its kind is switched off
    return next(iter(kinds.shown_devices()), dev)


def _frames(request):
    return runtime.device(_device(request)["id"]).frames


def _link(dev: dict):
    return kinds.of(dev).link(dev)


async def editor_strip_epf(request):
    f = _frames(request)
    if not getattr(f, "epf_strip", None):
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    return web.Response(body=f.epf_strip, headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-cache"})


async def api_manifest(request):
    f = _frames(request)
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
    """Health check on the device port. Deliberately says nothing about the pages
    or why quiet hours are on: the reason can reveal whether anyone is home."""
    f = runtime.device(kinds.device_for(request)["id"]).frames
    return web.json_response({
        "ok": f.error is None and f.rendered_at is not None,
        "page_count": len(f.names),
        "rendered_at": f.rendered_at,
        "version": ADDON_VERSION,
    })


async def editor_strip_png(request):
    """Serve the rendered strip over Ingress without requiring config.FRAME_TOKEN."""
    f = _frames(request)
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    return web.Response(body=f.strip, content_type="image/png",
                        headers={"Cache-Control": "no-cache"})


async def status(request):
    dev = _device(request)
    rt = runtime.device(dev["id"])
    f = rt.frames
    spec = load_layouts(dev["id"])
    link = _link(dev)
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
        "panel_interval": kinds.of(dev).update_minutes(dev),          # Update every (timing.py)
        "device": {"id": dev["id"], "name": dev.get("name"), "kind": dev.get("kind")},
        "esphome_device": link.preferred_node() if link else None,
        "active_alert": runtime.alert(dev["design"]).get("name"),
        "frame_port": FRAME_PORT,
        "display": spec.get("display", T.DEFAULT_DISPLAY),
        "orientation": int(spec.get("orientation") or 0),
        "panel_link": link.status() if link else None,
        "live_data": runtime.LIVE.status(),
        # Every outside service and data source: last success, and the problem
        # if it is failing (also a problem sensor in Home Assistant).
        "services": health.status(),
        # How many pages the panel holds, and what was left out to fit.
        "fit": rt.fit,
        "ha_entities": runtime.PUBLISHER.status() if runtime.PUBLISHER is not None else
                       {"mode": "off", "problem": "not started", "entities": 0},
        "version": ADDON_VERSION,
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
    spec = load_layouts(_device(request)["id"])
    return web.json_response(spec, headers={"ETag": _quoted(layouts_etag(spec))})


async def api_layouts_put(request):
    dev = _device(request)
    dev_id = dev["id"]
    spec = await _json(request)
    if not isinstance(spec, dict) or "pages" not in spec:
        raise web.HTTPBadRequest(text="expected {rotation, pages}")
    # The size is the screen's own: one of its kind's, never another kind's (that one can't be drawn).
    spec.setdefault("display", dev.get("display"))
    kind = kinds.of(dev)
    if T.get_display(spec.get("display")).get("kind") != kind.id:
        raise web.HTTPBadRequest(text=f"Pick one of the {kind.name} sizes.")
    try:
        clean = sanitize_layouts(spec)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    # A client that says which version it edited gets a 409 if someone saved
    # in between, with what's there now so it can merge. Without If-Match the
    # save goes through as it always has.
    expected = _if_match(request)
    if expected is not None and expected != "*":
        current = load_layouts(dev_id)
        current_tag = layouts_etag(current)
        if expected != current_tag:
            return web.json_response({"error": "These pages were changed somewhere else since you opened them.",
                                      "current": current, "etag": current_tag},
                                     status=409, headers={"ETag": _quoted(current_tag)})
    save_layouts(clean, dev_id)
    clear_draft(dev_id)                                   # sent: nothing is waiting any more
    tag = layouts_etag(load_layouts(dev_id))
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"immediate render after save failed: {health.describe(exc)}", flush=True)
    return web.json_response({
        "saved": True,
        "display": clean.get("display", T.DEFAULT_DISPLAY),
        "pages": list(clean["pages"]),
        "rotation": clean["rotation"],
        "orientation": clean["orientation"],
        "etag": tag,
    }, headers={"ETag": _quoted(tag)})


async def api_draft_get(request):
    """Unsent editor changes, and the version of what's live."""
    dev_id = _device(request)["id"]
    return web.json_response({"draft": load_draft(dev_id), "etag": layouts_etag(device_id=dev_id)})


async def api_draft_put(request):
    """Save the editor's changes as you go, without sending them to the panel.

    Body: {spec, base, base_etag}: the pages as edited, and the live pages they
    started from. If-Match carries the draft version the client last saw; on a
    mismatch (another window saved, or the draft was sent) the answer is 409
    with the current draft and the live pages, so the client can merge.
    """
    dev_id = _device(request)["id"]
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("spec"), dict):
        raise web.HTTPBadRequest(text="expected {spec, base, base_etag}")
    try:
        spec = sanitize_layouts(body["spec"])
        base = sanitize_layouts(body["base"]) if isinstance(body.get("base"), dict) else None
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    current = load_draft(dev_id)
    version = int(current.get("version") or 0) if current else 0
    expected = _if_match(request)
    if expected is not None and expected != "*" and expected != str(version):
        live = load_layouts(dev_id)
        return web.json_response({"error": "These pages were changed in another window.",
                                  "draft": current, "live": live, "etag": layouts_etag(live)}, status=409)
    draft = {"version": version + 1, "base_etag": str(body.get("base_etag") or ""),
             "base": base, "spec": spec, "saved_at": time.time()}
    save_draft(draft, dev_id)
    return web.json_response({"saved": True, "version": draft["version"]})


async def api_panel_device_get(request):
    """The panel's Sleep and ghost-clearing settings, read through Home Assistant."""
    link = _link(_device(request))
    if link is None:
        return web.json_response({"available": False, "problem": "the add-on can't reach this screen"})
    return web.json_response(await link.device_settings())


async def api_panel_device_post(request):
    """Change one panel setting: {sleep: bool} | {ghost_after: n} | {ghost_mode: s} | {clear_ghosting: true}."""
    body = await _json(request)
    if not isinstance(body, dict) or len(body) != 1:
        raise web.HTTPBadRequest(text="expected one setting")
    key, value = next(iter(body.items()))
    link = _link(_device(request))
    ok, err = await link.set_device_setting(key, value) if link else (False, "the add-on can't reach this screen")
    return web.json_response({"ok": ok, "error": err or None}, status=200 if ok or key in
                             ("sleep", "ghost_after", "ghost_mode", "clear_ghosting") else 400)


async def api_draft_delete(request):
    """Throw away unsent changes (the editor offers this as one undoable step)."""
    clear_draft(_device(request)["id"])
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
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("page") or {}, dict):
        raise web.HTTPBadRequest(text="expected {page}")
    page = body.get("page") or {}
    view = load_layouts(_device(request)["id"])
    try:
        orient = int(body.get("orientation") if "orientation" in body else view.get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = body.get("display") or view.get("display", T.DEFAULT_DISPLAY)
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
        series=series, metrics=metrics, orientation=orient,
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
    dev = _device(request)
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"pre-push render failed: {health.describe(exc)}", flush=True)
    delivered = await push_panel_update(dev["id"], "pushed from the editor")
    link = _link(dev)
    return web.json_response({"pushed": delivered, "pending": bool(link and link.pending is not None),
                              "error": None if delivered else (link.last_error if link else
                                                               "the add-on can't reach this screen")})


def _screen(dev: dict, everyone: list[dict]) -> dict:
    """A device as the editor shows it. Never its key."""
    kind = kinds.of(dev)
    disp = T.get_display(dev.get("display"))
    return {
        "id": dev["id"], "name": dev.get("name") or "", "kind": kind.id, "kind_name": kind.name,
        "display": disp["id"], "display_name": disp["name"], "orientation": int(dev.get("orientation") or 0),
        "canvas": devices.canvas_of(dev), "design": dev["design"],
        # On the design's own size, boxes are the design's; elsewhere they're this size's arrangement.
        "made_here": devices.design_canvas(dev["design"]) == devices.canvas_of(dev),
        "shares_with": [{"id": d["id"], "name": d.get("name") or ""} for d in everyone
                        if d["design"] == dev["design"] and d["id"] != dev["id"]],
        "can_wake": kind.link(dev) is not None, "picks_page": kind.picks_page,
        # A screen that sleeps between updates (paging.py) wakes when the add-on says, whatever its kind.
        "owns_interval": "addon" if kind.sleeps(dev) else kind.owns_interval, "sleeps": kind.sleeps(dev),
        "timing": timing.describe(dev, kind.stays_on),
        "setup": kind.setup_flow, "info": kind.describe(dev),
        "entity_suffix": dev.get("entity_suffix") or "",
        # Enough to offer "the same quiet hours as …" when adding a screen.
        "quiet": {k: (dev.get("quiet_hours") or {}).get(k) for k in ("enabled", "start", "end")},
    }


def _screens() -> dict:
    everyone = kinds.shown_devices()                   # a kind that's switched off shows nothing
    on = kinds.enabled_kinds()
    sizes = list(dict.fromkeys(d for k in on for d in k.displays()))
    return {"devices": [_screen(d, everyone) for d in everyone],
            "kinds": [{"id": k.id, "name": k.name, "setup": k.setup_flow,
                       "displays": [{"id": d, "name": T.get_display(d)["name"], "w": T.get_display(d)["w"],
                                     "h": T.get_display(d)["h"]} for d in k.displays()]}
                      for k in on],
            # Every model's canvases, so the editor's guides and new elements
            # use the renderer's own numbers (footer band, margins).
            "displays": {d: {"id": d, "name": v["name"], "w": v["w"], "h": v["h"], "mm_w": v["mm_w"],
                             "landscape": T.canvas_geometry(0, d), "portrait": T.canvas_geometry(90, d)}
                         for d, v in ((d, T.get_display(d)) for d in sizes)}}


def _clean_name(raw, exclude_id=None) -> str:
    name = re.sub(r"\s+", " ", str(raw or "")).strip()[:60]
    if not name:
        raise web.HTTPBadRequest(text="Give the screen a name.")
    if any(d.get("name", "").casefold() == name.casefold() and d["id"] != exclude_id for d in devices.all_devices()):
        raise web.HTTPBadRequest(text=f"There's already a screen called {name}.")
    return name


async def _json(request):
    """The request's JSON body; a body that isn't JSON is the sender's mistake (400), not ours (500)."""
    try:
        return await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="That isn't JSON.")


async def _body(request) -> dict:
    body = await _json(request)
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    return body


async def _rerender():
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"render after a screen change failed: {health.describe(exc)}", flush=True)


async def api_devices(request):
    return web.json_response(_screens())


async def api_devices_add(request):
    """Add a screen: {kind, name, display, orientation, pages: new|copy|same, from, quiet_hours_from}."""
    body = await _body(request)
    kind = kinds.KINDS.get(str(body.get("kind") or ""))
    if kind is None or not kind.enabled():
        raise web.HTTPBadRequest(text="That isn't a kind of screen this add-on knows.")
    display = str(body.get("display") or "")
    if display not in kind.displays():
        raise web.HTTPBadRequest(text=f"Pick one of the {kind.name} sizes.")
    name = _clean_name(body.get("name"))
    try:
        orientation = int(body.get("orientation") or 0)
    except (TypeError, ValueError):
        orientation = 0
    mode = body.get("pages") or "new"
    try:
        # Its timers (always on or sleeping, from the cards) and its kind's own settings, checked before it exists.
        extra = {**timing.settings({"kind": kind.id}, body, kind.stays_on), **kind.settings({"kind": kind.id}, body)}
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    try:
        if body.get("quiet_hours_from"):
            qh = devices.get(body["quiet_hours_from"]).get("quiet_hours")
            if qh:
                extra["quiet_hours"] = qh
        if mode == "same":
            dev = devices.add(kind.id, name, display, design=devices.get(body.get("from"))["design"],
                              orientation=orientation, **extra)
        elif mode == "copy":
            dev = devices.add(kind.id, name, display, copy_from=devices.get(body.get("from"))["id"],
                              orientation=orientation, **extra)
        elif mode == "new":
            dev = devices.add(kind.id, name, display, orientation=orientation, **extra)
        else:
            raise web.HTTPBadRequest(text="pages must be new, copy or same")
    except KeyError:
        raise web.HTTPBadRequest(text="The screen to copy from isn't there any more.")
    print(f"devices: added {dev['name']} ({kind.name}, {mode})", flush=True)
    await _rerender()
    return web.json_response({"device": _screen(dev, devices.all_devices()), **_screens()})


async def api_devices_update(request):
    """Rename a screen: {name}, or change its timers ({update_minutes, rotate_seconds, rotate_updates},
    at once) or its kind's own settings. Its size and mounting go with its pages (Send)."""
    dev = _device_by_path(request)
    body = await _body(request)
    fields = {}
    if "name" in body:
        fields["name"] = _clean_name(body["name"], exclude_id=dev["id"])
    kind = kinds.of(dev)
    try:
        fields.update(timing.settings(dev, body, kind.stays_on))
        fields.update(kind.settings(dev, body))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    old = dict(dev)
    dev = devices.update(dev["id"], **fields) if fields else dev
    note = None
    if kind.sleeps(old) != kind.sleeps(dev):
        await _rerender()                              # what it fetches next follows the new mode
        note = await kind.switched(old, dev)
    elif "rotate_seconds" in fields and not kind.sleeps(dev):
        await _rerender()                              # the panel turns its pages itself: tell it
        await push_panel_update(dev["id"], "rotation changed")
    return web.json_response({"device": _screen(dev, devices.all_devices()), "note": note, **_screens()})


async def api_devices_unlink(request):
    """Stop sharing pages: the screen gets its own copy, as placed for it."""
    dev = devices.unlink(_device_by_path(request)["id"])
    clear_draft(dev["id"])
    return web.json_response({"device": _screen(dev, devices.all_devices()), **_screens()})


async def api_devices_remove(request):
    dev = _device_by_path(request)
    if len(kinds.shown_devices()) < 2:
        raise web.HTTPConflict(text="This is the only screen, so it can't be removed.")
    try:
        devices.remove(dev["id"])
    except ValueError as exc:
        raise web.HTTPConflict(text=str(exc))
    print(f"devices: removed {dev['name']}", flush=True)
    await _rerender()
    return web.json_response({"removed": {"id": dev["id"], "name": dev.get("name")}, **_screens()})


async def api_devices_restore(request):
    try:
        dev = devices.restore(request.match_info["id"])
    except (KeyError, ValueError) as exc:
        raise web.HTTPConflict(text=str(exc).strip("'\""))
    await _rerender()
    return web.json_response({"device": _screen(dev, devices.all_devices()), **_screens()})


def _device_by_path(request) -> dict:
    try:
        dev = devices.get(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="There's no such screen.")
    if not kinds.shown(dev):
        raise web.HTTPNotFound(text="There's no such screen.")
    return dev


async def api_arrange(request):
    """{spec, display, orientation}: the pages placed for another size or mounting, before it's sent."""
    dev = _device(request)
    body = await _body(request)
    spec = body.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("pages"), dict):
        raise web.HTTPBadRequest(text="expected {spec, display, orientation}")
    display = str(body.get("display") or "")
    if display not in kinds.of(dev).displays():
        raise web.HTTPBadRequest(text="That size isn't one this screen comes in.")
    try:
        orientation = int(body.get("orientation") or 0)
    except (TypeError, ValueError):
        orientation = 0
    try:
        clean = sanitize_layouts(spec)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response({"pages": devices.place(clean, dev["id"], display, orientation)})


# ---------------------------------------------------------------- reaching home

async def _reach_status() -> dict:
    hostname = await reach.addon_hostname(runtime.SESSION)
    s = reach.settings()
    ha_addr = await reach.ha_address(runtime.HASS) if HA_TOKEN else ""
    installed = companion.installed_version()
    running = await companion.loaded(runtime.HASS) if HA_TOKEN else False
    return {
        **s,
        "ha_address": ha_addr,
        # Where a tunnel app on Home Assistant points (Cloudflare Tunnel's "service").
        "service_address": reach.service_address(hostname),
        "companion": {"installed": installed is not None, "version": installed, "running": running,
                      "restart_needed": installed is not None and (not running or runtime.COMPANION_UPDATED)},
        # A frame token someone chose can be short; away from home that matters.
        "token_short": bool(config.FRAME_TOKEN) and len(config.FRAME_TOKEN) < 16,
    }


async def api_reach_get(request):
    return web.json_response(await _reach_status())


async def api_reach_put(request):
    body = await _body(request)
    try:
        reach.save(str(body.get("mode") or ""), str(body.get("address") or ""))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response(await _reach_status())


async def api_reach_companion(request):
    """Install (or update) the companion integration, and set it up if Home Assistant already runs it."""
    hostname = await reach.addon_hostname(runtime.SESSION)
    try:
        companion.install(reach.service_address(hostname))
    except (OSError, ValueError) as exc:
        raise web.HTTPConflict(text=f"Couldn't install it: {health.describe(exc)}")
    status = await _reach_status()
    if status["companion"]["running"]:
        ok, problem = await companion.set_up(runtime.HASS)
        status["set_up"] = ok
        status["problem"] = problem or None
    return web.json_response(status)


async def api_reach_restart(request):
    """Restart Home Assistant so it loads the companion integration. Set up happens on the next visit."""
    ok, problem = await companion.restart_home_assistant(runtime.HASS)
    return web.json_response({"restarting": ok, "problem": problem or None})


async def api_reach_setup(request):
    ok, problem = await companion.set_up(runtime.HASS)
    return web.json_response({"set_up": ok, "problem": problem or None, **await _reach_status()})


async def api_sources_get(request):
    return web.json_response(feeds.mask_secrets(load_sources()))


async def api_sources_put(request):
    body = await _json(request)
    if not isinstance(body, list):
        raise web.HTTPBadRequest(text="expected a list of sources")
    merged = feeds.unmask_secrets(body, load_sources())
    feeds.save(config.DATA_DIR, merged)
    return web.json_response({"saved": True, "count": len(merged),
                              "sources": feeds.mask_secrets(merged)})


async def api_sources_test(request):
    """Run one source now and report what it would publish."""
    src = await _json(request)
    if not isinstance(src, dict):
        raise web.HTTPBadRequest(text="expected a source object")
    unmasked = feeds.unmask_secrets([src], load_sources())
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": runtime.SESSION}
    errors: list[str] = []
    rows = await feeds.run_all(unmasked, ctx, errors)
    return web.json_response({"published": [{"entity_id": e, "state": str(v)[:120],
                                             "attributes": a} for e, v, a in rows],
                              "error": errors[0] if errors else None})


def _masked_setup(cfg: dict, dev: dict) -> dict:
    """A panel's setup for the browser: passwords masked."""
    out = dict(cfg)
    if out.get("wifi_password"):
        out["wifi_password"] = feeds.SECRET_MASK
    out["wifi_networks"] = [{"ssid": n["ssid"], "password": feeds.SECRET_MASK if n["password"] else ""}
                            for n in more_networks(cfg)]
    # Shown, not masked: you need it on your phone, standing next to the panel.
    out["hotspot_name"] = hotspot_name(dev)
    return out


async def api_panel_setup_get(request):
    dev = _device(request)
    # A new panel fetches from Home Assistant's own home address, never the browser's (audit #9).
    home = None if (dev.get("setup") or {}).get("ha_host") else await reach.home_address(runtime.HASS, runtime.SESSION)
    cfg = load_panel_setup(dev, default_host=home or reach.HOME_FALLBACK)
    detected_port = await _detect_external_port(runtime.SESSION)
    if "frame_port" not in cfg:
        cfg["frame_port"] = detected_port
    masked_cfg = _masked_setup(cfg, dev)
    public = await reach.public_base(runtime.HASS)
    yaml_text, secrets_text = generate_esphome_yaml(masked_cfg, dev, public)
    conn = await _detect_panel_connection(dev)
    return web.json_response({
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "problems": wifi_problems(cfg),
        "frame_port": cfg.get("frame_port", detected_port),
        "has_frame_token": True,
        "frame_protection": frame_token.status(),
        "panel": conn,
    })


async def api_panel_setup_post(request):
    body = await _json(request)
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    dev = _device(request)
    cur = load_panel_setup(dev)
    if body.get("regenerate_keys"):
        cur["api_encryption_key"] = _new_api_key()
    for k in ("device_name", "ha_host", "wifi_ssid"):
        if k in body and isinstance(body[k], str):
            cur[k] = body[k].strip()
    if not cur.get("ha_host"):
        cur["ha_host"] = await reach.home_address(runtime.HASS, runtime.SESSION)
    if "frame_port" in body:
        try:
            cur["frame_port"] = int(body["frame_port"])
        except (ValueError, TypeError):
            pass
    # The size is the screen's own and goes with its pages (Send); the form only shows it.
    cur.pop("display", None)
    if "use_secrets" in body:
        cur["use_secrets"] = bool(body["use_secrets"])
    if "hotspot" in body:
        cur["hotspot"] = bool(body["hotspot"])
    if "wifi_password" in body and isinstance(body["wifi_password"], str):
        if body["wifi_password"] != feeds.SECRET_MASK:
            cur["wifi_password"] = body["wifi_password"]
    if isinstance(body.get("wifi_networks"), list):
        # A password shown masked and left alone stays what it was for that network.
        before = {n["ssid"]: n["password"] for n in more_networks(cur)}
        cur["wifi_networks"] = [{"ssid": n["ssid"], "password": before.get(n["ssid"], "") if n["password"] == feeds.SECRET_MASK
                                 else n["password"]} for n in more_networks({"wifi_networks": body["wifi_networks"]})]
    for k in ("api_encryption_key",):
        if k in body and isinstance(body[k], str) and body[k].strip():
            if not body.get("regenerate_keys"):
                cur[k] = body[k].strip()
    saved = save_panel_setup(dev["id"], cur)
    saved["display"] = T.get_display(load_layouts(dev["id"]).get("display"))["id"]
    masked_cfg = _masked_setup(saved, dev)
    # The file the panel is built from gets the real values; only the copy
    # shown in the browser is masked. (0.9.2 and earlier wrote the mask into
    # the file when the Wi-Fi password was left untouched.)
    public = await reach.public_base(runtime.HASS)
    disk_yaml, _ = generate_esphome_yaml(saved, dev, public)
    yaml_text, secrets_text = generate_esphome_yaml(masked_cfg, dev, public)
    esphome_dir = config.ESPHOME_DIR
    esphome_synced = False
    # A file ESPHome would refuse isn't written: the one there stays until this one would install.
    problems = wifi_problems(saved)
    if not problems and esphome_dir.exists() and esphome_dir.is_dir():
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
            # The name Home Assistant will know this panel by once it's installed from this file.
            devices.update(dev["id"], setup={**(devices.get(dev["id"]).get("setup") or {}), "installed_name": ha_name(dev)})
            print(f"Synced ESPHome config to {target_yaml}", flush=True)
        except Exception as e:
            print(f"Could not sync to {esphome_dir}: {e}", flush=True)
    conn = await _detect_panel_connection(dev)
    return web.json_response({
        "saved": True,
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "problems": problems,
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
    on = {k.id for k in kinds.enabled_kinds()}
    return web.json_response({
        "displays": [d for d in T.DISPLAYS.values() if d.get("kind") in on],
        "default": T.DEFAULT_DISPLAY,
    })


async def editor_index(request):
    index = WEB_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Editor not built yet.", content_type="text/plain")
    return web.FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


def make_apps():
    """The LAN frame server and the Ingress-only editor."""
    panel = web.Application()
    panel.add_routes([
        web.get("/status", public_status),
        web.get("/fonts/{name}", panel_font),
    ])
    for kind in kinds.enabled_kinds():                 # each kind of device adds its own; one that's off, none
        panel.add_routes(kind.routes())

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
        web.get("/api/devices", api_devices),
        web.post("/api/devices", api_devices_add),
        web.patch("/api/devices/{id}", api_devices_update),
        web.post("/api/devices/{id}/unlink", api_devices_unlink),
        web.delete("/api/devices/{id}", api_devices_remove),
        web.post("/api/devices/{id}/restore", api_devices_restore),
        web.post("/api/arrange", api_arrange),
        web.get("/api/reach", api_reach_get),
        web.put("/api/reach", api_reach_put),
        web.post("/api/reach/companion", api_reach_companion),
        web.post("/api/reach/setup", api_reach_setup),
        web.post("/api/reach/restart", api_reach_restart),
        web.get("/api/panel-setup", api_panel_setup_get),
        web.post("/api/panel-setup", api_panel_setup_post),
        web.get("/api/mdi/font", api_mdi_font),
        web.get("/api/mdi/list", api_mdi_list),
        web.get("/api/mdi/all", api_mdi_all),
    ])
    for kind in kinds.enabled_kinds():
        editor.add_routes(kind.editor_routes())
    if WEB_DIR.exists():
        editor.router.add_static("/static/", WEB_DIR)

    async def no_stale_editor(request, response):
        # The editor's files change with every release; never run yesterday's.
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
    editor.on_response_prepare.append(no_stale_editor)
    return panel, editor
