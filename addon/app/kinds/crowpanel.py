"""The CrowPanel: ESPHome firmware that downloads a frame file of every page and pages through it itself.

It owns which page is shown and how often it fetches. The add-on packs the
pages into the EPF frame file (render/epf.py) with the footer geometry the
firmware draws its overlays with, fits the file to what the panel says it
holds (`?cap=`), and wakes it early through Home Assistant (panel_link).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime
from email.utils import formatdate

from aiohttp import web
from PIL import Image

import devices
import frames
import health
import panel_ops
import runtime
from config import SLEEP_PAGE
from kinds import Kind, device_for, register
from panel_link import PanelLink
from render import epf, sleep, stripmeta, subitems, theme as T


def node_of(dev: dict) -> str:
    """The panel's ESPHome node: from its Panel setup, or the add-on option for the first panel."""
    name = str((dev.get("setup") or {}).get("device_name") or "").strip()
    if name:
        return name.replace("-", "_")
    return runtime.ESPHOME_DEVICE if dev.get("install_token") else ""


class CrowPanel(Kind):
    id = "crowpanel"
    name = "CrowPanel"
    picks_page = "device"
    owns_interval = "device"

    def displays(self) -> list[str]:
        return [k for k, d in T.DISPLAYS.items() if d.get("kind") == self.id]

    def routes(self) -> list:
        return [
            web.get("/frame.png", frame_png),
            web.get("/frames.png", frames_png),
            web.get("/frame.epf", frame_epf),
            web.get("/frames.epf", frames_epf),
            web.post("/api/action/refresh", api_action_refresh),
            web.post("/api/action/page", api_action_page),
            # Removed from the LAN port in 0.9.2: /api/layouts (exposed every
            # entity, template and custom location, with no token check at all),
            # /manifest.json and /api/manifest (page names, presence-based quiet
            # reason), and GET on the actions (a link preview could trigger them).
            # Nothing on the network used them; the editor keeps its own copies.
        ]

    def link(self, dev: dict) -> PanelLink:
        rt = runtime.device(dev["id"])
        if rt.link is None:
            dev_id = dev["id"]

            def preferred():
                try:
                    return node_of(devices.get(dev_id))
                except KeyError:
                    return ""

            def only_panel():
                # "The only panel in Home Assistant is ours" holds only while we drive one.
                return sum(1 for d in devices.all_devices() if d.get("kind") == self.id) == 1

            def ha_name():
                try:
                    dev_now = devices.get(dev_id)
                except KeyError:
                    return ""
                setup = dev_now.get("setup") or {}
                # Installed from a file that named it, or the name every panel had before that.
                return setup.get("installed_name") or ("E-paper panel" if dev_now.get("install_token") else "")

            rt.link = PanelLink(runtime.HASS, preferred, sole=only_panel, ha_name=ha_name)
        return rt.link

    def interval(self, dev: dict) -> int:
        """What its Panel setup says; the panel's own number, through its link, wins."""
        m = re.search(r"\d+", str((dev.get("setup") or {}).get("refresh_interval", "5")))
        return int(m.group(0)) if m else 5

    async def render(self, session, dev, spec, st, quiet_active, quiet_reason) -> runtime.Frames:
        orient = int(spec.get("orientation") or 0)
        if orient not in (0, 90, 180, 270):
            orient = 0
        display = spec.get("display", T.DEFAULT_DISPLAY)
        disp = T.get_display(display)
        dw, dh = disp["w"], disp["h"]
        try:
            rot_sec = max(5, min(3600, int(spec.get("rotate_seconds") or 30)))
        except (TypeError, ValueError):
            rot_sec = 30
        alert = st.alert
        rt = runtime.device(dev["id"])

        if not st.live:
            img = await asyncio.to_thread(frames.empty_page, orient, display)
            one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
            png = frames._png(one)
            cat_ids = [stripmeta.identity("empty")]
            sub_ids = [stripmeta.identity("empty:0")]
            # No pills on the empty page: width 0 tells the panel to draw no highlight.
            fg = T.footer_plan(clock=datetime.now().strftime("%H:%M"), orientation=orient, display=display)
            epf_data = epf.encode_epf(
                pages=[one], cat_ids=cat_ids, cat_offsets=[0], cat_sizes=[1], cat_pill_widths=[0], sub_ids=sub_ids,
                display_model=display, width=dw, height=dh, rotate_sec=rot_sec, quiet_hours=quiet_active,
                alert_interrupt=False, orientation_180=(orient == 180),
                geometry=frames.panel_geometry(fg, orient, display),
            )
            return _frames(png, png, [png], ["empty"], [0], [1], ["empty"], [110], rot_sec, cat_ids, sub_ids,
                           epf_data, epf_data)

        # The panel holds a limited number of pages. Every page keeps its first
        # item; extra items are shared out fairly; the rest are left out, and
        # said so (DeviceRuntime.fit, /api/status, sensor.epaper_panel_pages).
        plans = st.plans
        capacity = runtime.panel_capacity(dev["id"])
        counts = frames.fit_counts([p["want"] for p in plans], page_bytes=((dw + 7) // 8) * dh,
                                   capacity=capacity, extra_pages=0 if alert else 1)
        rt.fit = frames.record_fit(plans, counts, capacity, rt.fit, dev.get("name") or "the panel")

        imgs = []
        cat_offsets, cat_sizes, cat_names, cat_pill_widths, cat_sub_keys = [], [], [], [], []
        clock = datetime.now().strftime("%H:%M")       # one clock for the whole strip
        kept = [(p, c) for p, c in zip(plans, counts) if c > 0]
        # One footer for the whole strip, drawn with the same numbers the panel
        # draws its highlight and padlocks with, in every orientation.
        fg = T.footer_plan(clock=clock, pages=[(p["name"], c) for p, c in kept], orientation=orient, display=display)
        geo = frames.panel_geometry(fg, orient, display)

        for cat_i, (plan, sub_count) in enumerate(kept):
            cat_name = plan["name"]
            try:
                page_imgs = await frames.draw_category(plan, sub_count, cat_i, footer=fg,
                                                       page_def=spec["pages"][cat_name], orient=orient,
                                                       display=display)
            except Exception as exc:
                print(f"page {cat_name} left out: {health.describe(exc)}", flush=True)
                continue
            cat_offsets.append(len(imgs))
            cat_sizes.append(sub_count)
            cat_names.append(cat_name)
            cat_pill_widths.append(fg["pages"][cat_i]["w"])
            cat_sub_keys.append(plan["sub_keys"][:sub_count])
            imgs.extend(page_imgs)
        live = cat_names
        if not imgs:
            raise RuntimeError("no page could be drawn")

        # The sleep screen always goes first, so the panel can fall asleep
        # instantly (dial centre held, or its Sleep switch) without asking us.
        # The panel never pages onto it. During quiet hours with the sleep screen
        # on, it's also marked "auto": the panel goes to sleep by itself.
        cat_flags = [0] * len(cat_offsets)
        qh = spec.get("quiet_hours") or {}
        if not alert:
            auto = quiet_active and qh.get("sleep_screen", True)
            text = (sleep.wake_text(quiet_reason, qh.get("end") or "07:00") if quiet_active
                    else sleep.MANUAL_TEXT)
            sleep_img = await asyncio.to_thread(sleep.render_sleep_page, text, orient, display)
            imgs.insert(0, T.orient_for_panel(T.to_1bit(sleep_img), orient, display=display))
            cat_offsets = [0] + [o + 1 for o in cat_offsets]
            cat_sizes = [1] + cat_sizes
            cat_names = [SLEEP_PAGE] + cat_names
            cat_pill_widths = [0] + cat_pill_widths
            cat_sub_keys = [[f"{SLEEP_PAGE}:{text}"]] + cat_sub_keys     # new text, new identity: the panel redraws it
            cat_flags = [epf.CAT_FLAG_SLEEP | (epf.CAT_FLAG_SLEEP_AUTO if auto else 0)] + cat_flags
            live = [SLEEP_PAGE] + list(live)

        slice_pngs = [frames._png(im) for im in imgs]
        slices_digest = hashlib.md5(b"".join(slice_pngs)).digest()

        cat_ids, sub_ids = subitems.compute_identities(live, cat_sub_keys)
        meta = stripmeta.StripMeta(
            offsets=cat_offsets,
            sizes=cat_sizes,
            pill_widths=cat_pill_widths,
            cat_ids=cat_ids,
            sub_ids=sub_ids,
            quiet=quiet_active,
            rotate_seconds=rot_sec,
            content_hash=(slices_digest[0] << 8) | slices_digest[1],
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
            geometry=geo,
            cat_flags=cat_flags,
        )
        return _frames(frames._png(strip), slice_pngs[0], slice_pngs, live, cat_offsets, cat_sizes, cat_names,
                       cat_pill_widths, rot_sec, cat_ids, sub_ids, epf_data, epf.extract_page_epf(epf_data, 0))


def _frames(strip, single, slices, names, cat_offsets, cat_sizes, cat_names, cat_pill_widths, rot_sec,
            cat_ids, sub_ids, epf_strip, epf_single) -> runtime.Frames:
    f = runtime.Frames()
    f.strip, f.single, f.slices, f.names = strip, single, slices, names
    f.strip_etag = frames._etag(strip)
    f.single_etag = frames._etag(single)
    f.epf_strip, f.epf_single = epf_strip, epf_single
    f.epf_strip_etag = f'"{hashlib.blake2s(epf_strip, digest_size=8).hexdigest()}"'
    f.epf_single_etag = f'"{hashlib.blake2s(epf_single, digest_size=8).hexdigest()}"'
    f.cat_offsets, f.cat_sizes, f.cat_names, f.cat_pill_widths = cat_offsets, cat_sizes, cat_names, cat_pill_widths
    f.cat_ids, f.sub_ids = cat_ids, sub_ids
    f.cat_count = len(cat_offsets)
    f.rotate_seconds = rot_sec
    return f


# ---------------------------------------------------------------- the device port

def _cache_headers(f, etag=None):
    """Caching headers for frame responses.

    0.8.x also sent page names, category layout and the quiet-hours flag as
    X- headers. Nothing read them, and on an untokened LAN port they said more
    than a frame should (quiet hours can mean nobody is home).
    """
    h = {"Cache-Control": "no-cache",
         "Last-Modified": getattr(f, "last_modified", "") or formatdate(timeval=None, localtime=False, usegmt=True)}
    if etag:
        h["ETag"] = etag
    return h


def _frames_of(request):
    return runtime.device(device_for(request, CrowPanel.id)["id"]).frames


async def frame_png(request):
    f = _frames_of(request)
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
    etag = frames._etag(body)
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_cache_headers(f, etag))
    return web.Response(body=body, content_type="image/png", headers=_cache_headers(f, etag))


async def frames_png(request):
    f = _frames_of(request)
    if not f.strip:
        raise web.HTTPServiceUnavailable(text="no frame rendered yet")
    if f.strip_etag and request.headers.get("If-None-Match") == f.strip_etag:
        raise web.HTTPNotModified(headers=_cache_headers(f, f.strip_etag))
    return web.Response(body=f.strip, content_type="image/png", headers=_cache_headers(f, f.strip_etag))


async def frame_epf(request):
    f = _frames_of(request)
    if not f.epf_strip:
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    page_q = request.query.get("page")
    body = f.epf_single
    if page_q is not None:
        try:
            page_idx = max(0, min(len(f.names) - 1, int(page_q)))
            body = epf.extract_page_epf(f.epf_strip, page_idx)
        except (ValueError, TypeError, IndexError):
            body = f.epf_single
    if not body:
        body = epf.extract_page_epf(f.epf_strip, 0)
    etag = f'"{hashlib.blake2s(body, digest_size=8).hexdigest()}"'
    if request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_cache_headers(f, etag))
    h = _cache_headers(f, etag)
    h["Content-Type"] = "application/octet-stream"
    h["X-EPF-Version"] = "3.0"
    return web.Response(body=body, headers=h)


async def frames_epf(request):
    dev = device_for(request, CrowPanel.id)
    try:
        if "cap" in request.query and runtime.set_panel_capacity(dev["id"], int(request.query["cap"])):
            runtime.LIVE._event().set()                # render to the new size now
    except ValueError:
        pass
    f = runtime.device(dev["id"]).frames
    if not f.epf_strip:
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet")
    etag = f.epf_strip_etag
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers=_cache_headers(f, etag))
    h = _cache_headers(f, etag)
    h["Content-Type"] = "application/octet-stream"
    h["X-EPF-Version"] = "3.0"
    return web.Response(body=f.epf_strip, headers=h)


async def api_action_refresh(request):
    """Re-render and make this panel redraw (scripts, webhooks). Always needs its key."""
    dev = device_for(request, CrowPanel.id, always=True)
    try:
        await frames.refresh_frames(runtime.SESSION)
        ha_pushed = await panel_ops.push_panel_update(dev["id"], "action endpoint")
        return web.json_response({"success": True, "action": "refresh", "ha_pushed": ha_pushed,
                                  "timestamp": datetime.now().isoformat()})
    except Exception as exc:
        return web.json_response({"success": False, "error": health.describe(exc)}, status=500)


async def api_action_page(request):
    """Step this panel's page. Always needs its key."""
    dev = device_for(request, CrowPanel.id, always=True)
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        delta = int(body.get("delta") if "delta" in body else (request.query.get("delta") or 1))
    except (TypeError, ValueError, OverflowError):
        delta = 1
    delta = max(-100, min(100, delta))                # the panel steps one page at a time
    ha_stepped = await panel_ops.step_panel_page(dev["id"], delta=delta)
    return web.json_response({"success": True, "action": "page_step", "delta": delta, "ha_stepped": ha_stepped})


register(CrowPanel())
