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

import examples
from sources.geo import get_home_timezone, home_language
import feeds
import widgets
import live_data
from render import binding, clock, epf, icons, layout, sleep, stripmeta, subitems, theme as T, words
import airports
import companion
import config
import devices
import frame_token
import iconsets
import kinds
import notify
import reach
import runtime
import services
import share
import timing
from config import ADDON_VERSION, FRAME_PORT, HA_BASE, HA_TOKEN, INGRESS_GATEWAY, REFRESH, SLEEP_PAGE, WEB_DIR, valid_entity_id
from fixture import _dated, load_fixture
from frames import _png, as_int, busy_day, date_for_time, device_words, enrich_page_values, refresh_frames, split_page_values
from ha import curve_series, ha_json, resolve_templates
from layouts_store import clear_draft, layouts_etag, load_draft, load_layouts, load_sources, sanitize_layouts, save_draft, save_layouts
from panel_ops import push_panel_update
import panel_setup
from panel_setup import _detect_external_port, _detect_panel_connection, _new_api_key, generate_esphome_yaml, hotspot_name, load_panel_setup, more_networks, save_panel_setup, wifi_problems
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
        raise web.HTTPNotFound(text="There's no such device.")
    if kinds.shown(dev):
        return dev
    if asked:
        raise web.HTTPNotFound(text="There's no such device.")         # its kind is switched off
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
        # Each page's widget part as last answered ("something on it to show"), for the page panel.
        "parts": runtime.parts(dev["design"]),
        "frame_port": FRAME_PORT,
        "display": spec.get("display", T.DEFAULT_DISPLAY),
        "orientation": int(spec.get("orientation") or 0),
        "panel_link": link.status() if link else None,
        "live_data": runtime.LIVE.status(),
        # Every outside service and data source: last success, and the problem
        # if it is failing (also a problem sensor in Home Assistant).
        "services": health.status(),
        # The ones whose problem sensor is on, in plain words, for the status card (services.py).
        "service_problems": services.problems(),
        # How many pages the panel holds, and what was left out to fit: only for a device that keeps its
        # whole rotation in memory (Kind.room), which can run out. One that sleeps gets a page a wake.
        "fit": rt.fit if kinds.of(dev).room(dev) else None,
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
        return web.json_response({"available": False, "problem": "the add-on can't reach this device"})
    return web.json_response(await link.device_settings())


async def api_panel_device_post(request):
    """Change one panel setting: {sleep: bool} | {ghost_after: n} | {ghost_mode: s} | {clear_ghosting: true}."""
    body = await _json(request)
    if not isinstance(body, dict) or len(body) != 1:
        raise web.HTTPBadRequest(text="expected one setting")
    key, value = next(iter(body.items()))
    link = _link(_device(request))
    ok, err = await link.set_device_setting(key, value) if link else (False, "the add-on can't reach this device")
    return web.json_response({"ok": ok, "error": err or None}, status=200 if ok or key in
                             ("sleep", "ghost_after", "ghost_mode", "clear_ghosting") else 400)


def _notify_id(value) -> str:
    nid = notify.clean_id(value)
    if not nid:
        raise web.HTTPBadRequest(text="That page has no notification to change.")
    return nid


async def api_notify_get(request):
    """A page's phone notifications: its sensor and the automations that use it (notify.py).
    ?id= the page's notify id; without one, only whether they can be set up here."""
    nid = notify.clean_id(request.query.get("id"))
    return web.json_response(await notify.status(runtime.HASS, nid))


async def api_notify_targets(request):
    """What can be notified (Home Assistant's notify entities), phones first."""
    return web.json_response({"targets": await notify.targets(runtime.HASS)})


async def api_notify_post(request):
    """"Also notify my phone…": {page, id, tier, targets}. Makes the page's sensor, installs the
    blueprint and makes an automation from it in Home Assistant."""
    dev = _device(request)
    body = await _json(request)
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected {page, id, tier, targets}")
    nid = _notify_id(body.get("id"))
    page = str(body.get("page") or "").strip()
    if not page:
        raise web.HTTPBadRequest(text="Which page?")
    targets = [t for t in body.get("targets") or [] if isinstance(t, str) and t.startswith("notify.") and valid_entity_id(t)]
    tier = body.get("tier") if body.get("tier") in ("when", "alert") else "alert"
    try:
        made = await notify.set_up(runtime.HASS, nid=nid, design=dev["design"], page=page,
                                   page_def={"tier": tier}, targets=targets)
    except notify.SetupError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response(made)


async def api_notify_stop(request):
    """Stop notifying: {id, delete: [automation ids]}. Deletes the automations named (only
    ones made from our blueprint), then withdraws the sensor unless something still uses it."""
    body = await _json(request)
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected {id, delete}")
    nid = _notify_id(body.get("id"))
    delete = [str(d) for d in body.get("delete") or [] if isinstance(d, (str, int))]
    try:
        return web.json_response(await notify.stop(runtime.HASS, nid, delete))
    except notify.SetupError as exc:
        return web.json_response({"error": str(exc)}, status=409)


async def api_draft_delete(request):
    """Throw away unsent changes (the editor offers this as one undoable step)."""
    clear_draft(_device(request)["id"])
    return web.json_response({"cleared": True})


async def api_entities(request):
    """Entity list for the picker. Cached briefly -- it is a big response."""
    try:
        return web.json_response(await entity_list())
    except HomeAssistantUnreachable as exc:
        return web.json_response({"error": str(exc)}, status=502)


class HomeAssistantUnreachable(Exception):
    """Home Assistant didn't give its entity list (the reason, already safe to show: health.describe)."""


async def entity_list() -> list[dict]:
    """Home Assistant's entities as the editor lists them, the add-on's own first: the picker's list, and
    what a shared page's slots are told about each sensor (share.export)."""
    by_id = {}
    if not HA_TOKEN:
        states = load_fixture().get("states", {})
        for eid, info in states.items():
            by_id[eid] = {
                "entity_id": eid,
                "name": info.get("friendly_name") or eid,
                "state": info.get("state"),
                "unit": info.get("unit") or "",
                "device_class": info.get("device_class") or "",
                "state_class": info.get("state_class") or "",
                "changes_every": widgets.sensor_changes_every(info),
                "is_epaper": eid.startswith("sensor.epaper_"),
            }
            if info.get("state") in ("unavailable", "unknown"):
                by_id[eid]["changed"] = _dated(info).get("last_changed") or ""
    else:
        if time.time() - runtime.ENTITY_CACHE["at"] >= 30 or not runtime.ENTITY_CACHE["items"]:
            try:
                states = await ha_json(runtime.SESSION, "/states")
            except Exception as exc:
                raise HomeAssistantUnreachable(health.describe(exc))
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
                    # So a preset can list, say, temperature sensors first.
                    "device_class": attrs.get("device_class") or "",
                    # A running total (total, total_increasing) can show its change today (binding "change_today").
                    "state_class": attrs.get("state_class") or "",
                    "changes_every": widgets.sensor_changes_every(attrs),
                    "is_epaper": eid.startswith("sensor.epaper_") or attrs.get("source") == "epaper_studio",
                }
                if s.get("state") in ("unavailable", "unknown"):
                    by_id[eid]["changed"] = s.get("last_changed") or ""      # how long it's been quiet
                if attrs.get("restored"):
                    by_id[eid]["restored"] = True        # its integration no longer provides it: a leftover

    # Always merge live E-Paper Studio published entities so newly added widgets appear immediately
    for eid, info in runtime.PUBLISHED.items():
        attrs = info.get("attributes") or {}
        by_id[eid] = {
            "entity_id": eid,
            "name": attrs.get("friendly_name") or eid,
            "state": info.get("state"),
            "unit": attrs.get("unit_of_measurement") or "",
            "device_class": attrs.get("device_class") or "",
            "state_class": attrs.get("state_class") or "",
            "is_epaper": True,
        }

    # Which source made a sensor, so a preset can offer exactly those.
    for src in load_sources():
        made = by_id.get(f"sensor.epaper_{src.get('name')}")
        if made is not None and src.get("type"):
            made["feed"] = str(src["type"])

    return sorted(by_id.values(), key=lambda e: (0 if e.get("is_epaper") else 1, e["entity_id"]))


async def api_share_export(request):
    """POST {pages: {name: page}, rotation, canvas, title} -> {file, name, words}: the pages as a file to
    share (share.export), its file name, and the words that go in it as written, for the editor to list."""
    body = await _body(request)
    if not isinstance(body.get("pages"), dict) or not body["pages"]:
        raise web.HTTPBadRequest(text="There's no page to share.")
    try:
        ents = await entity_list()
    except HomeAssistantUnreachable as exc:
        return web.json_response({"error": f"Couldn't read your sensors from Home Assistant, so nothing could be "
                                           f"left out safely. Try again in a moment. ({exc})"}, status=502)
    rotation = body.get("rotation") if isinstance(body.get("rotation"), list) else []
    file = share.export(body["pages"], rotation, str(body.get("canvas") or ""), ents, load_sources())
    return web.json_response({"file": file, "name": share.file_name(str(body.get("title") or "")),
                              "words": share.words(file)})


async def api_share_open(request):
    """POST {text} -> a shared file's pages and slots (share.open_file), or 422 {error} saying why not."""
    body = await _body(request)
    try:
        return web.json_response(share.open_file(str(body.get("text") or "")))
    except share.Refused as exc:
        return web.json_response({"error": str(exc)}, status=422)


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
    """Render one page spec through the real engine, so WYSIWYG cannot lie: in the device's language too."""
    with await device_words(runtime.SESSION, _device(request)):
        return await _preview(request)


async def _preview(request):
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("page") or {}, dict):
        raise web.HTTPBadRequest(text="expected {page}")
    page = body.get("page") or {}
    vals, tpls = split_page_values(page)
    if tpls:
        vals.update(await resolve_templates(runtime.SESSION, tpls))
    with live_data.waiting_for_fresh():                   # someone is looking at this preview
        await enrich_page_values(runtime.SESSION, page, vals)
    series = {}
    for i, el in enumerate(page.get("elements", [])):
        if el.get("type") in ("curve", "bar_chart") and el.get("entity"):
            series[i] = await curve_series(runtime.SESSION, el["entity"], as_int(el.get("hours"), 24))
    # The canvas is this device's own render: one that sleeps between updates shows the date for a time.
    dev = _device(request)
    return await _drawn(request, body, page, vals, series, today=await date_for_time(kinds.of(dev).sleeps(dev)))


def _fit(elements: list, from_canvas: str, display: str, orientation: int) -> list:
    """Elements made on `from_canvas` ("792x272"), placed for a device's size as an arrangement would
    place them automatically (render/arrange.auto_box): the one way a page moves between sizes."""
    from render import arrange
    try:
        arrange.parse_canvas(from_canvas)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="from_canvas is a size like 792x272")
    target = arrange.canvas_key(*T.canvas_dims(orientation, display))
    if target == from_canvas:
        return elements
    return [{**el, **arrange.auto_box(el, from_canvas, target)} if isinstance(el, dict) else el for el in elements]


async def api_widget_data(request):
    """A widget's Data section in the inspector: where it reads from (the add-on's services, by name, or
    one of your data sources) and its fields in the add-on's own form, with what they hold now (shapes.py)."""
    import shapes
    body = await _json(request)
    el = body.get("element") if isinstance(body, dict) else None
    if not isinstance(el, dict):
        raise web.HTTPBadRequest(text="expected {element}")
    w = widgets.get(el.get("type"))
    shape = shapes.get(w.shape) if w else None
    if shape is None:
        raise web.HTTPBadRequest(text="It doesn't read anything from outside.")
    own = shapes.own_source(el)
    entity = own[len(shapes.ENTITY):] if own.startswith(shapes.ENTITY) else ""
    src = next((x for x in load_sources() if isinstance(x, dict) and x.get("id") == own), None) if own and not entity else None
    with live_data.waiting_for_fresh():                   # someone is looking at it
        try:
            value = await widgets.fetch(runtime.SESSION, el, widgets.Ctx(home_tz=await get_home_timezone(runtime.SESSION)))
        except Exception as exc:                          # noqa: BLE001 -- a field list that can't fill is still shown
            print(f"widget data: {health.describe(exc)}", flush=True)
            value = None
    return web.json_response({
        "shape": shape.kind,
        "source": ({"id": own, "name": services.source_name(src), "missing": False} if src
                   else {"id": own, "name": "", "missing": True}) if own and not entity else None,
        "entity": {"id": entity, "problem": shapes.problem(own)} if entity else None,
        "services": [s.name for s in services.SERVICES if s.uses and s.uses(el)],
        "fields": [{"label": label, "value": str(v)} for label, v in shape.shown(value)] if value else [],
    })


async def api_as_template(request):
    """{"template"}: what an element shows, as a template (binding.as_template), for the editor's
    From › Template; the editor keeps no copy of how a binding becomes Jinja."""
    body = await _json(request)
    el = body.get("element") if isinstance(body, dict) else None
    if not isinstance(el, dict):
        raise web.HTTPBadRequest(text="expected {element}")
    return web.json_response({"template": binding.as_template(el)})


async def api_fit(request):
    """POST {elements, from_canvas, display?, orientation?} -> {elements}: a page made on one size, placed
    for a device's (the editor's own device by default), for adding a preset's page."""
    body = await _body(request)
    view = load_layouts(_device(request)["id"])
    display = body.get("display") or view.get("display", T.DEFAULT_DISPLAY)
    try:
        orient = int(body.get("orientation") if "orientation" in body else view.get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    els = body.get("elements")
    if not isinstance(els, list):
        raise web.HTTPBadRequest(text="expected {elements, from_canvas}")
    return web.json_response({"elements": _fit(els, str(body.get("from_canvas") or ""), display, orient)})


async def api_busy_day(request):
    """POST {rotation, pages} -> {"scores": {busiest, room, teams, leagues} | None}: on a busy day, how many
    games a draft's Scores pages can have and how many the device has room for, with the rest of its
    rotation (frames.busy_day). Only a device that keeps its whole rotation in memory can run out
    (Kind.room: an always-on CrowPanel); for any other, scores is None."""
    body = await _body(request)
    dev = _device(request)
    room = kinds.of(dev).room(dev)
    if not room or not isinstance(body.get("pages"), dict) or not isinstance(body.get("rotation"), list):
        return web.json_response({"scores": None})
    return web.json_response(busy_day(body, page_bytes=room[0], capacity=room[1]))


async def api_example(request):
    """A page drawn with example values only (examples.py), for preset thumbnails: never the person's own
    data, and nothing asked of Home Assistant, the internet or a data source. Same body as /api/preview,
    in the device's language."""
    with await device_words(runtime.SESSION, _device(request)):
        return await _example(request)


async def _example(request):
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("page") or {}, dict):
        raise web.HTTPBadRequest(text="expected {page}")
    page = body.get("page") or {}
    vals, series = await asyncio.to_thread(examples.page_values, page)
    return await _drawn(request, body, page, vals, series)


async def _drawn(request, body: dict, page: dict, vals: dict, series: dict, today=None):
    """A preview's PNG at the device's size and orientation, with the text sizes it got (X-Metrics)."""
    view = load_layouts(_device(request)["id"])
    try:
        orient = int(body.get("orientation") if "orientation" in body else view.get("orientation", 0))
    except (TypeError, ValueError):
        orient = 0
    if orient not in (0, 90, 180, 270):
        orient = 0
    display = body.get("display") or view.get("display", T.DEFAULT_DISPLAY)
    if body.get("from_canvas"):                         # a page made for another size, placed for this one
        page = {**page, "elements": _fit(page.get("elements") or [], str(body["from_canvas"]), display, orient)}
    metrics = []
    try:
        dist = float(body.get("distance") or 3.0)
    except (TypeError, ValueError):
        dist = 3.0
    img = await asyncio.to_thread(
        layout.render_page, page, vals,
        clock=clock.hm(datetime.now()),
        label=str(body.get("label") or "preview")[:40],
        series=series, metrics=metrics, orientation=orient,
        distance_m=dist, display=display, date_for_time=today)
    # Effective font sizes ride back on a header so the editor can report
    # what you actually got, in millimetres, rather than what you asked for.
    return web.Response(body=_png(T.to_1bit(img)), content_type="image/png",
                        headers={"X-Metrics": json.dumps(metrics)})


async def api_catalog(request):
    """Everything the editor needs to know that the server keeps (framework review #5): the leagues and
    racing series offered, each sport's words, state words by device, each widget's descriptor (name,
    box, fields, how often its value changes) and the time format. One request at the editor's start;
    the editor keeps no copies of these tables."""
    import timeformat
    import widgets
    from render import sport, states
    from sources import racing, sports
    from sources.geo import get_home_locale

    def said(w):
        return {"event": w.event, "events": w.events, "start": w.start, "day": w.day}
    return web.json_response({
        "leagues": [{"path": lg.path, "slug": lg.slug, "name": lg.name, "aliases": list(lg.aliases),
                     "sensor": lg.sensor, "words": said(sport.words(lg.path)), "busiest_day": lg.busiest_day}
                    for lg in sports.LEAGUES],
        "series": [{"slug": s.slug, "code": s.code, "title": s.title, "aliases": list(s.aliases),
                    "sensor": f"sensor.epaper_racing_{s.slug}"} for s in racing.SERIES.values()],
        "sport_words": {k: said(v) for k, v in sport.catalog().items()},
        "states": states.catalog(),
        "widgets": widgets.catalog(),
        "time_format": timeformat.describe(*await get_home_locale(runtime.SESSION))["resolved"],
        # The languages a device can speak, Home Assistant's, and the words presets write on a page
        # in each (render/words_table.py "page.*", "state.*"): the editor keeps no copy.
        "languages": {"choices": words.choices(), "home": words.resolve(home_language()),
                      "home_offered": words.offered(home_language())},
        "page_words": words.page_words(),
    })


async def api_timezones(request):
    """The cities a world clock can show: {"home": Home Assistant's zone, "zones": [{"tz", "city", "region",
    "offset"}]}, from the time zone database (render/worldclock.catalog)."""
    from render import worldclock
    return web.json_response({"home": await get_home_timezone(runtime.SESSION), "zones": worldclock.catalog()})


async def api_shows_time(request):
    """Which elements of a page show the time of day, however they're written (render/clocktime.py):
    {"time": [index...]}. The editor asks here instead of matching strings of its own."""
    from render import clocktime
    body = await _json(request)
    page = body.get("page") if isinstance(body, dict) else None
    if not isinstance(page, dict):
        raise web.HTTPBadRequest(text="expected {page}")
    return web.json_response({"time": clocktime.times(page)})


async def api_time_get(request):
    """12- or 24-hour: {"format": "auto"|"12h"|"24h", "resolved": "12h"|"24h", "country"}.
    Automatic follows Home Assistant's country."""
    import timeformat
    from sources.geo import get_home_locale
    return web.json_response(timeformat.describe(*await get_home_locale(runtime.SESSION)))


async def api_time_put(request):
    import timeformat
    from sources.geo import get_home_locale
    body = await _body(request)
    try:
        timeformat.save(str(body.get("format") or ""))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    locale = await get_home_locale(runtime.SESSION)
    timeformat.apply(*locale)
    await _rerender()                                   # every device's times change at once
    return web.json_response(timeformat.describe(*locale))


async def api_energy(request):
    """What the Energy dashboard is set up with, so a preset can say where its numbers come from
    (or that it needs setting up there): {"solar": [{"energy", "power"}], "grid": [{"flows", "power"}],
    "has_cost", "currency"}. Empty lists when there's no dashboard; 502 when Home Assistant didn't answer."""
    from sources import energy
    with live_data.waiting_for_fresh():
        got = await energy.fetch_dashboard(runtime.SESSION)
    if got is None:
        return web.json_response({"error": "Home Assistant didn't say how its Energy dashboard is set up"}, status=502)
    return web.json_response(got)


async def api_batteries(request):
    """Which battery sensors you charge yourself, by their device (sources.batteries):
    {"batteries": {entity: true|false|null}} (null for one with no device, {} offline), and "kinds":
    {entity: "swap"|"charge"} for every battery a Batteries page's rule can pick, battery-low sensors
    included: the one answer the add-on resolves its rule by (batteries.every_battery)."""
    from sources import batteries
    try:
        got = await batteries.fetch(runtime.SESSION)
        with live_data.waiting_for_fresh():
            every = await batteries.fetch_every(runtime.SESSION) or []
    except Exception as exc:
        return web.json_response({"error": health.describe(exc)}, status=502)
    return web.json_response({"batteries": got, "kinds": {b["entity"]: b["kind"] for b in every}})


async def api_changed(request):
    """When a sensor last really changed, for a "changed" condition's status line:
    {"state", "at", "to", "history", "now"} (sources.changes; epoch seconds, "now"
    the add-on's, so the editor counts minutes on the same clock as the panel)."""
    from sources import changes
    eid = (request.query.get("entity") or "").strip()
    if not valid_entity_id(eid):
        return web.json_response({"error": "That isn't an entity ID."}, status=400)
    minutes = max(1, min(1440, as_int(request.query.get("minutes"), 30)))
    try:
        with live_data.waiting_for_fresh():
            got = await changes.fetch_change(runtime.SESSION, eid, minutes)
    except Exception as exc:
        got = None
        print(f"changed {eid}: {health.describe(exc)}", flush=True)
    if got is None:
        return web.json_response({"error": "Home Assistant didn't say when it last changed."}, status=502)
    return web.json_response({**got, "now": time.time()})


async def api_entity_states(request):
    """The states an icon that follows an entity offers, each with Home Assistant's icon for it
    (sources.states_seen): {"states": [{"state", "word", "icon"}]}."""
    from sources import states_seen
    eid = (request.query.get("entity") or "").strip()
    if not valid_entity_id(eid):
        return web.json_response({"error": "That isn't an entity ID."}, status=400)
    try:
        got = await states_seen.fetch(runtime.SESSION, eid)
    except Exception as exc:
        print(f"states of {eid}: {health.describe(exc)}", flush=True)
        return web.json_response({"error": "Home Assistant didn't say what states it has."}, status=502)
    return web.json_response({"states": got})


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
                                                               "the add-on can't reach this device")})


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
        "timing": timing.describe(dev, **kind.timers),
        "setup": kind.setup_flow, "info": kind.describe(dev),
        "entity_suffix": dev.get("entity_suffix") or "",
        # Its language: its own choice ("" is Home Assistant's), and the one it speaks (render/words.py).
        "language": dev.get("language") or "", "speaks": words.for_device(dev.get("language"), home_language()),
        # Enough to offer "the same quiet hours as …" when adding a screen.
        "quiet": {k: (dev.get("quiet_hours") or {}).get(k) for k in ("enabled", "start", "end")},
    }


def _screens() -> dict:
    everyone = kinds.shown_devices()                   # a kind that's switched off shows nothing
    on = kinds.enabled_kinds()
    # The canvases of every profile of these kinds (one not offered still belongs to a
    # screen already set to it), and the sizes a TRMNL reported; the pickers offer k.displays().
    ids = {k.id for k in on}
    sizes = list(dict.fromkeys([*(d for d, v in T.DISPLAYS.items() if v.get("kind") in ids),
                                *(d for k in on for d in k.displays())]))
    return {"devices": [_screen(d, everyone) for d in everyone],
            "kinds": [{"id": k.id, "name": k.name, "setup": k.setup_flow,
                       # What Update every offers a new screen of this kind, and where sleeping starts.
                       "update_choices": timing.update_choices(**k.timers), "asleep_default": timing.ASLEEP_DEFAULT,
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
        raise web.HTTPBadRequest(text="Give the device a name.")
    taken = next((d for d in devices.all_devices() if d.get("name", "").casefold() == name.casefold() and d["id"] != exclude_id), None)
    if taken:
        raise web.HTTPBadRequest(text=f"There's already a device called {taken['name']}.")
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
    """Add a device (Add new device): {kind, name, display, orientation, pages: new|copy|same, from, quiet_hours_from}."""
    body = await _body(request)
    kind = kinds.KINDS.get(str(body.get("kind") or ""))
    if kind is None or not kind.enabled():
        raise web.HTTPBadRequest(text="That isn't a kind of device this add-on knows.")
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
        extra = {**timing.settings({"kind": kind.id}, body, **kind.timers), **kind.settings({"kind": kind.id}, body)}
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
        raise web.HTTPBadRequest(text="The device to copy from isn't there any more.")
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
    if "language" in body:
        lang = str(body.get("language") or "").strip().lower()
        if lang and lang not in words.LANGUAGES:
            raise web.HTTPBadRequest(text="Pick one of the languages offered, or Same as Home Assistant.")
        fields["language"] = lang or None                # none: Home Assistant's
    kind = kinds.of(dev)
    try:
        fields.update(timing.settings(dev, body, **kind.timers))
        fields.update(kind.settings(dev, body))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    old = dict(dev)
    dev = devices.update(dev["id"], **fields) if fields else dev
    note = None
    if (old.get("language") or None) != (dev.get("language") or None):
        await _rerender()                              # its words change at its next update
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
        raise web.HTTPConflict(text="This is the only device, so it can't be removed.")
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
        raise web.HTTPNotFound(text="There's no such device.")
    if not kinds.shown(dev):
        raise web.HTTPNotFound(text="There's no such device.")
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
        raise web.HTTPBadRequest(text="That size isn't one this device comes in.")
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
    # Set it up here too, so a visit right after the restart doesn't wait for the add-on's own check.
    comp = await companion.ensure(runtime.HASS) if HA_TOKEN else {"state": companion.UNKNOWN}
    running = comp["state"] == companion.RUNNING
    return {
        **s,
        "ha_address": ha_addr,
        # Where a tunnel app on Home Assistant points (Cloudflare Tunnel's "service").
        "service_address": reach.service_address(hostname),
        "companion": {"installed": installed is not None, "version": installed, "running": running,
                      "state": comp["state"], "disabled": comp.get("disabled", False),
                      "problem": comp.get("problem"),
                      "restart_needed": comp["state"] == companion.RESTART},
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
    """Install (or update) the companion integration; the status sets it up if Home Assistant already has it."""
    hostname = await reach.addon_hostname(runtime.SESSION)
    try:
        companion.install(reach.service_address(hostname))
    except (OSError, ValueError) as exc:
        raise web.HTTPConflict(text=f"Couldn't install it: {health.describe(exc)}")
    return web.json_response(await _reach_status())


async def api_reach_restart(request):
    """Restart Home Assistant so it loads the companion integration. The add-on sets it up once it's back."""
    ok, problem = await companion.restart_home_assistant(runtime.HASS)
    return web.json_response({"restarting": ok, "problem": problem or None})


async def api_services_get(request):
    """Settings › Services: every service, what uses it, its state and its addresses (services.py)."""
    return web.json_response({"services": services.listing()})


async def api_services_try(request):
    """Try again: ask a service now, as the add-on does. Asked by a person, so it may reach the internet."""
    try:
        got = await services.try_again(runtime.SESSION, request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="There's no such service.")
    return web.json_response(got)


async def api_services_address(request):
    """Use another address for a service ({key, address}), checked by the add-on's own reader first;
    an empty address goes back to the original. Refused with the reason, in plain words."""
    body = await _body(request)
    key = str(body.get("key") or "main")
    try:
        got = await services.set_address(runtime.SESSION, request.match_info["id"], key, body.get("address"))
    except KeyError:
        raise web.HTTPNotFound(text="There's no such address to change.")
    except services.Refused as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=422)
    return web.json_response({"ok": True, **got, "services": services.listing()})


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
    if feeds.fills(unmasked[0]):
        # One that fills a widget: read by the add-on's own reader for it (shapes.py), and said plainly.
        import shapes
        shape = shapes.get(feeds.fills(unmasked[0]))
        if shape is None:
            return web.json_response({"published": [], "error": "It fills a kind of page the add-on doesn't have."})
        try:
            items = shapes.read(shape.kind, await feeds.fetch_json(unmasked[0], runtime.SESSION))
        except ValueError as exc:
            return web.json_response({"published": [], "error": str(exc)})
        except Exception as exc:                # noqa: BLE001 -- said plainly, never with its headers
            return web.json_response({"published": [], "error": services.plain(health.describe(exc))})
        return web.json_response({"published": [], "error": None, "fills": f"Fills {shape.name} pages: {shape.summary(items)}"})
    ctx = {"ha_base": HA_BASE, "ha_token": HA_TOKEN, "session": runtime.SESSION}
    errors: list[str] = []
    rows = await feeds.run_all(unmasked, ctx, errors)
    return web.json_response({"published": [{"entity_id": e, "state": str(v)[:120],
                                             "attributes": a} for e, v, a in rows],
                              "error": errors[0] if errors else None})


async def api_jellyfin_check(request):
    """Try a Jellyfin address and key before a preset saves them: {"ok", "users", "titles"} or {"ok": false, "error"}.
    A key shown masked (editing a saved source, `name` or `id` given) is the saved one."""
    from feeds import jellyfin
    body = await _json(request)
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected {base, key}")
    src = feeds.unmask_secrets([{"type": "jellyfin", "name": body.get("name") or "watch", "id": body.get("id"),
                                 "key": str(body.get("key") or "")}], load_sources())[0]
    return web.json_response(await jellyfin.check(str(body.get("base") or ""), src.get("key") or "", runtime.SESSION))


async def api_jellyfin_suggest(request):
    """Jellyfin's address from JellyHA, when it's installed, so the preset can fill it in: {"address": "" | url}.
    JellyHA doesn't share its API key, so that's still typed."""
    if not HA_TOKEN:
        return web.json_response({"address": ""})
    try:
        registry = await runtime.HASS.ws({"type": "config/entity_registry/list"}) or []
        mine = [e.get("entity_id") for e in registry if isinstance(e, dict) and e.get("platform") == "jellyha"]
        for eid in mine:
            if not valid_entity_id(str(eid or "")):
                continue
            st = await ha_json(runtime.SESSION, f"/states/{urllib.parse.quote(eid, safe='.')}")
            url = str(((st or {}).get("attributes") or {}).get("config_external_url") or "").strip().rstrip("/")
            if url.startswith(("http://", "https://")):
                return web.json_response({"address": url})
    except Exception as exc:
        print(f"jellyfin suggest: {health.describe(exc)}", flush=True)
    return web.json_response({"address": ""})


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
    disk_yaml, _ = generate_esphome_yaml(cfg, dev, public)
    conn = await _detect_panel_connection(dev)
    return web.json_response({
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "problems": wifi_problems(cfg),
        "esphome": await _esphome_status(cfg, disk_yaml),
        "frame_port": cfg.get("frame_port", detected_port),
        "has_frame_token": True,
        "frame_protection": frame_token.status(),
        "panel": conn,
    })


async def _esphome_status(cfg: dict, disk_yaml: str) -> dict:
    """Whether ESPHome's copy of the file is current, and where its dashboard is."""
    dashboard = await panel_setup.esphome_dashboard(runtime.HASS) if HA_TOKEN else None
    return {**panel_setup.esphome_state(cfg, disk_yaml), "dashboard": dashboard}


async def api_panel_setup_esphome(request):
    """Send to ESPHome: write the panel's file (as saved) into Home Assistant's ESPHome folder."""
    dev = _device(request)
    cfg = load_panel_setup(dev)
    problems = wifi_problems(cfg)
    if problems:
        raise web.HTTPConflict(text=f"ESPHome wouldn't install this file. {problems[0]}")
    disk_yaml, _ = generate_esphome_yaml(cfg, dev, await reach.public_base(runtime.HASS))
    try:
        panel_setup.write_to_esphome(dev, cfg, disk_yaml)
    except FileNotFoundError:
        raise web.HTTPConflict(text="Home Assistant has no ESPHome folder. Install the ESPHome add-on first, "
                                    "or copy the file below.")
    except (OSError, ValueError) as exc:
        raise web.HTTPConflict(text=f"Couldn't write the file: {health.describe(exc)}")
    return web.json_response({"written": True, "esphome": await _esphome_status(cfg, disk_yaml)})


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
    # Its own Wi-Fi is never open: an empty password keeps the one it has (wifi_problems says what's wrong).
    if isinstance(body.get("hotspot_password"), str) and body["hotspot_password"]:
        cur["hotspot_password"] = body["hotspot_password"][:64]
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
    problems = wifi_problems(saved)
    esphome_synced = False
    if panel_setup.WRITE_ON_SAVE and not problems:
        try:
            panel_setup.write_to_esphome(dev, saved, disk_yaml)
            esphome_synced = True
        except (OSError, ValueError) as exc:
            print(f"esphome: couldn't write the file: {health.describe(exc)}", flush=True)
    conn = await _detect_panel_connection(dev)
    return web.json_response({
        "saved": True,
        "config": masked_cfg,
        "yaml": yaml_text,
        "secrets_yaml": secrets_text,
        "problems": problems,
        "esphome_synced": esphome_synced,
        "esphome": await _esphome_status(saved, disk_yaml),
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


# The old font path: the editor drew icons with these three before it drew outlines (api_icons).
# Kept, unused by the editor, as the way back with render/icons.FROM_FONT.
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


async def api_icons(request):
    """Every icon the panel can draw, by set, for the picker: {"sets": [{"prefix", "name", "count",
    "version", "from"}], "names": {prefix: [name, ...]}}. Names only; the outlines come in pages
    (api_icon_outlines). The same list `layout.can_draw_icon` answers from, so the picker never
    offers an icon the panel can't draw."""
    sets, names = [], {}
    for s in icons.sets():
        got = [n for n in icons.names(s["prefix"]) if layout.can_draw_icon(f"{s['prefix']}:{n}")]
        if got:
            sets.append({**s, "count": len(got)})
            names[s["prefix"]] = got
    tag = _quoted(f"{len(sets)}-" + "-".join(f"{s['prefix']}.{s['version']}.{s['count']}.{s['from']}" for s in sets))
    if request.headers.get("If-None-Match") == tag:
        return web.Response(status=304, headers={"ETag": tag})
    return web.json_response({"sets": sets, "names": names}, headers={"ETag": tag, "Cache-Control": "no-cache"})


async def api_icon_outlines(request):
    """The outlines of some icons, to draw them in the editor: {"names": ["mdi:cat", ...]} (at most
    600) -> {"icons": {name: record}}. A record is a path on the 24 grid, or {d, e, s, v}
    (render/vector); one the panel can't draw is left out."""
    try:
        body = await request.json()
    except Exception:
        body = None
    wanted = body.get("names") if isinstance(body, dict) else None
    if not isinstance(wanted, list) or len(wanted) > 600:
        return web.json_response({"error": "Ask for up to 600 icons by name."}, status=400)
    out = {}
    for n in wanted:
        if isinstance(n, str) and layout.can_draw_icon(n) and not n.startswith(icons.BUILT_IN + ":"):
            rec = icons.get(n)
            if rec is not None:
                out[n] = rec
    return web.json_response({"icons": out})


async def api_iconsets_get(request):
    """Settings › Icons: your own icons, the chosen Iconify sets and how each is doing
    (iconsets.status). The editor asks again while one is downloading."""
    return web.json_response(iconsets.status(), headers={"Cache-Control": "no-store"})


async def api_iconsets_available(request):
    """Add a set: the single-color sets Iconify offers, fetched only now (and kept); ?refresh=1
    asks Iconify again."""
    try:
        got = await iconsets.available(runtime.SESSION, refresh=request.query.get("refresh") == "1")
    except iconsets.SetError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    have = set(iconsets.chosen())
    return web.json_response({"sets": [{**s, "chosen": s["prefix"] in have} for s in got]})


async def api_iconsets_samples(request):
    """Previews for Add a set: {"prefixes": [...]} (the rows on screen, at most 24) -> {"samples":
    {prefix: [record, ...]}}, outlines like any other icon's."""
    try:
        body = await request.json()
    except Exception:
        body = None
    prefixes = body.get("prefixes") if isinstance(body, dict) else None
    if not isinstance(prefixes, list) or len(prefixes) > 24 or not all(isinstance(p, str) and icons.PREFIX_RE.match(p) for p in prefixes):
        return web.json_response({"error": "Ask for up to 24 sets by prefix."}, status=400)
    return web.json_response({"samples": await iconsets.samples(runtime.SESSION, prefixes)})


async def api_iconsets_add(request):
    """Choose a set, or try one again: {"prefix"}. It downloads in the background."""
    try:
        body = await request.json()
    except Exception:
        body = None
    prefix = body.get("prefix") if isinstance(body, dict) else None
    if not isinstance(prefix, str) or not icons.PREFIX_RE.match(prefix):
        return web.json_response({"error": "Choose a set from the list."}, status=400)
    try:
        await iconsets.add(runtime.SESSION, prefix, wait=1.5)
    except iconsets.SetError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    return web.json_response(iconsets.status())


async def api_iconsets_remove(request):
    prefix = request.match_info["prefix"]
    if not icons.PREFIX_RE.match(prefix):
        raise web.HTTPNotFound()
    await iconsets.remove(prefix)
    return web.json_response(iconsets.status())


async def api_iconsets_check(request):
    """Check for updates: each chosen set, in the background; the status says how it went."""
    await iconsets.check_updates(runtime.SESSION)
    return web.json_response(iconsets.status())


async def api_icons_own(request):
    """Add icons: {"files": [{"name", "svg"}]} (at most 40 at once, and under the editor's 1 MB a
    request) saved into the own folder as cleaned copies, then used."""
    try:
        body = await request.json()
    except Exception:
        body = None
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list) or not files or len(files) > 40 or not all(isinstance(f, dict) for f in files):
        return web.json_response({"error": "Choose up to 40 SVG files at a time."}, status=400)
    loop = asyncio.get_running_loop()
    try:
        said = await loop.run_in_executor(None, iconsets.save_own, files)
    except OSError as exc:
        return web.json_response({"error": f"Couldn't save into {iconsets.OWN_FOLDER.as_posix()}: {health.describe(exc)}"}, status=500)
    await loop.run_in_executor(None, lambda: iconsets.copy_custom(force=True))
    return web.json_response({**said, **iconsets.status()})


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
        web.get("/api/notify", api_notify_get),
        web.get("/api/notify/targets", api_notify_targets),
        web.post("/api/notify", api_notify_post),
        web.post("/api/notify/stop", api_notify_stop),
        web.put("/api/draft", api_draft_put),
        web.delete("/api/draft", api_draft_delete),
        web.get("/api/panel-device", api_panel_device_get),
        web.post("/api/panel-device", api_panel_device_post),
        web.get("/fonts/{name}", panel_font),
        web.get("/api/entities", api_entities),
        web.get("/api/attributes", api_attributes),
        web.post("/api/share/export", api_share_export),
        web.post("/api/share/open", api_share_open),
        web.get("/api/aircraft", api_aircraft),
        web.get("/api/airport", api_airport),
        web.get("/api/changed", api_changed),
        web.get("/api/entity_states", api_entity_states),
        web.get("/api/energy", api_energy),
        web.get("/api/batteries", api_batteries),
        web.get("/api/catalog", api_catalog),
        web.get("/api/timezones", api_timezones),
        web.post("/api/shows-time", api_shows_time),
        web.get("/api/settings/time", api_time_get),
        web.put("/api/settings/time", api_time_put),
        web.post("/api/preview", api_preview),
        web.post("/api/example", api_example),
        web.post("/api/fit", api_fit),
        web.post("/api/busy_day", api_busy_day),
        web.post("/api/as_template", api_as_template),
        web.post("/api/widget_data", api_widget_data),
        web.post("/api/push", api_push),
        web.get("/api/services", api_services_get),
        web.post("/api/services/{id}/try", api_services_try),
        web.put("/api/services/{id}/address", api_services_address),
        web.get("/api/sources", api_sources_get),
        web.put("/api/sources", api_sources_put),
        web.post("/api/sources/test", api_sources_test),
        web.post("/api/sources/jellyfin/check", api_jellyfin_check),
        web.get("/api/sources/jellyfin/suggest", api_jellyfin_suggest),
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
        web.post("/api/reach/restart", api_reach_restart),
        web.get("/api/panel-setup", api_panel_setup_get),
        web.post("/api/panel-setup", api_panel_setup_post),
        web.post("/api/panel-setup/esphome", api_panel_setup_esphome),
        web.get("/api/icons", api_icons),
        web.post("/api/icons/outlines", api_icon_outlines),
        web.post("/api/icons/own", api_icons_own),
        web.get("/api/iconsets", api_iconsets_get),
        web.get("/api/iconsets/available", api_iconsets_available),
        web.post("/api/iconsets", api_iconsets_add),
        web.post("/api/iconsets/check", api_iconsets_check),
        web.post("/api/iconsets/samples", api_iconsets_samples),
        web.delete("/api/iconsets/{prefix}", api_iconsets_remove),
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
