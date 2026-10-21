"""The CrowPanel: ESPHome firmware that downloads a frame file of every page and pages through it itself.

It owns which page is shown and how often it fetches. The add-on packs the
pages into the EPF frame file (render/epf.py) with the footer geometry the
firmware draws its overlays with, fits the file to what the panel says it
holds (`?cap=`), and wakes it early through Home Assistant (panel_link).

**Update every** (timing.py) says how it's powered. 1 minute is always on:
it stays connected, checks every minute on its own timer (its "Refresh
interval" in Home Assistant, which the add-on keeps at that minute), and
turns its pages every Rotate every seconds. 2 minutes or more, it's a screen
that sleeps: the shared mode in paging.py picks the page for a timer wake
and says how long to sleep. The firmware is the same either way. On each
download the add-on decides: sleeping, the answer carries
`X-EPF-Sleep: <seconds>; awake=<seconds>` (how long until it next checks,
counted from this answer, and how long to stay awake first); always on, no
such header, and the panel stays connected, told by `X-EPF-Next: <ms>` when
its own timer should fetch next: a moment after the next minute's render
(cadence.py), so a clock it shows is right within seconds. A header, not a field in the frame
file, because a frame file is drawn once per cycle for every download while
the sleep time is worked out per download, and a 304 has no body. Older
firmware ignores headers it doesn't know.

What a panel that can sleep says when it fetches `/frames.epf`:
`wake=timer|button|boot` (why it's awake) and `awake_ms=` (how long it was
awake last time). A timer wake while it sleeps between updates gets one
page, picked; anything else gets every page, as always.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime
from email.utils import formatdate

from aiohttp import web
from PIL import Image

import cadence
import devices
import frames
import health
import paging
import panel_ops
import runtime
import timing
from render.clock import hm as clock_text
from config import HA_TOKEN, SLEEP_PAGE
from kinds import Kind, device_for, of as kind_of, register
from panel_link import PanelLink
from render import epf, sleep, stripmeta, subitems, theme as T


def node_of(dev: dict) -> str:
    """The panel's ESPHome node: from its Panel setup, or the add-on option for the first panel."""
    name = str((dev.get("setup") or {}).get("device_name") or "").strip()
    if name:
        return name.replace("-", "_")
    return runtime.ESPHOME_DEVICE if dev.get("install_token") else ""


def _span(minutes: int) -> str:
    if minutes < 60:
        return "a minute" if minutes == 1 else f"{minutes} minutes"
    return "an hour" if minutes == 60 else f"{minutes // 60} hours"


class CrowPanel(Kind):
    id = "crowpanel"
    name = "CrowPanel"
    picks_page = "device"
    owns_interval = "device"

    def displays(self) -> list[str]:
        """The sizes offered: not one Elecrow doesn't make (`offered: False`), which
        stays in DISPLAYS only so a screen already set to it still renders."""
        return [k for k, d in T.DISPLAYS.items() if d.get("kind") == self.id and d.get("offered", True)]

    async def switched(self, old: dict, dev: dict) -> str | None:
        """Sleeping or always on takes effect at the panel's next download. To sleep, the add-on asks
        a connected panel to download now; to stay on, the panel is asleep and finds out when it checks."""
        if not self.sleeps(dev):
            runtime.device(dev["id"]).kind.pop("timer_checked", None)    # check its own timer at once
            return (f"It stays on from its next update, within {_span(self.update_minutes(old))}, "
                    "or as soon as you press a button on it.")
        link = self.connected_link(dev)
        if HA_TOKEN:
            link.request_refresh("it sleeps between updates now")
            if await link.deliver():
                return "It starts sleeping now."
            link.pending = None                        # not retried: it would be asleep by then
        return "It starts sleeping at its next update."

    def editor_routes(self) -> list:
        return [
            web.post("/api/devices/{id}/stay-awake", editor_stay_awake),
            web.delete("/api/devices/{id}/stay-awake", editor_stay_awake),
        ]

    def describe(self, dev: dict) -> dict:
        st = devices.state(dev["id"])
        return {
            # Whether its firmware has said why it woke: only firmware that can sleep does.
            "firmware_sleeps": bool(st.get("sleeps_seen")),
            "last_seen": st.get("last_seen") if self.sleeps(dev) else None,
            "awake_s": paging.awake_average(dev),
            "stay_awake": paging.stay_awake_info(dev),
        }

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

    def link(self, dev: dict) -> PanelLink | None:
        if self.sleeps(dev):
            return None                                # asleep between checks: it can't be woken early
        return self.connected_link(dev)

    def connected_link(self, dev: dict) -> PanelLink:
        """Its link through Home Assistant, whatever mode it's in (for the last push before it sleeps)."""
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

    async def render(self, session, dev, spec, st, quiet_active, quiet_reason) -> runtime.Frames:
        orient = int(spec.get("orientation") or 0)
        if orient not in (0, 90, 180, 270):
            orient = 0
        display = spec.get("display", T.DEFAULT_DISPLAY)
        dw, dh = T.panel_dims(display)          # the panel's own memory, which the frames fill
        rot_sec = timing.rotate_seconds(dev)
        alert = st.alert
        rt = runtime.device(dev["id"])
        if self.sleeps(dev):
            # Sleeping between updates: a timer wake gets one page, picked from these.
            await paging.draw_ahead(dev, spec, st, quiet_active, quiet_reason, ART)
        else:
            paging.forget(dev)
            keep_its_timer(dev)

        if not st.live:
            img = await asyncio.to_thread(frames.empty_page, orient, display)
            one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
            png = frames._png(one)
            cat_ids = [stripmeta.identity("empty")]
            sub_ids = [stripmeta.identity("empty:0")]
            # No pills on the empty page: width 0 tells the panel to draw no highlight.
            fg = T.footer_plan(clock=clock_text(datetime.now()), orientation=orient, display=display)
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
        clock = clock_text(datetime.now())             # one clock for the whole strip
        kept = [(p, c) for p, c in zip(plans, counts) if c > 0]
        today = await frames.date_for_time(self.sleeps(dev))    # it sleeps: the date where a time would be
        # One footer for the whole strip, drawn with the same numbers the panel
        # draws its highlight and padlocks with, in every orientation.
        fg = T.footer_plan(clock=clock, pages=[(p["name"], c) for p, c in kept], orientation=orient, display=display)
        geo = frames.panel_geometry(fg, orient, display)

        for cat_i, (plan, sub_count) in enumerate(kept):
            cat_name = plan["name"]
            try:
                page_imgs = await frames.draw_category(plan, sub_count, cat_i, footer=fg,
                                                       page_def=spec["pages"][cat_name], orient=orient,
                                                       display=display, today=today)
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


def _single_epf(img, *, dev: dict, name: str, sub_key: str, spec: dict, fg: dict, pill_w: int, quiet: bool,
                cat_flags: int = 0, cat_id: int | None = None, sub_id: int | None = None) -> bytes:
    """One page as a frame file of its own, with the identities it has in the strip."""
    orient, display = _orient(spec), T.get_display(spec.get("display"))["id"]
    if cat_id is None or sub_id is None:
        cat_ids, sub_ids = subitems.compute_identities([name], [[sub_key]])
        cat_id, sub_id = cat_ids[0], sub_ids[0]
    digest = hashlib.md5(img.tobytes()).digest()
    return epf.encode_epf(
        pages=[img], cat_ids=[cat_id], cat_offsets=[0], cat_sizes=[1], cat_pill_widths=[pill_w],
        sub_ids=[sub_id], display_model=display, width=T.panel_dims(display)[0], height=T.panel_dims(display)[1],
        rotate_sec=timing.rotate_seconds(dev), quiet_hours=quiet, alert_interrupt=False,
        orientation_180=(orient == 180), content_hash=int.from_bytes(digest[:8], "big"),
        geometry=frames.panel_geometry(fg, orient, display), cat_flags=[cat_flags])


def _orient(spec: dict) -> int:
    try:
        orient = int(spec.get("orientation") or 0)
    except (TypeError, ValueError):
        orient = 0
    return orient if orient in (0, 90, 180, 270) else 0


TIMER_CHECK_SECONDS = 600


def keep_its_timer(dev: dict) -> None:
    """Always on, the panel checks on its own timer: its "Refresh interval" in Home Assistant.
    Update every is the one source of truth, so that number is kept at it: set after an
    upgrade (the panel keeps the number it had, even through a reinstall), and again if it's
    changed in Home Assistant. Checked now and then, in the background: a render never
    waits on Home Assistant."""
    rt = runtime.device(dev["id"]).kind
    now = time.monotonic()
    if not HA_TOKEN or rt.get("timer_task") or now - rt.get("timer_checked", -1e9) < TIMER_CHECK_SECONDS:
        return
    rt["timer_checked"] = now
    rt["timer_task"] = asyncio.create_task(keep_its_timer_now(dev["id"]))


async def keep_its_timer_now(dev_id: str) -> bool | None:
    """Set the panel's own timer to Update every if it isn't. Whether it was changed (None: couldn't tell)."""
    try:
        dev = devices.get(dev_id)
        if KIND.sleeps(dev):
            return None                                # asleep, its own timer doesn't run
        want = KIND.update_minutes(dev)
        link = KIND.connected_link(dev)
        if not await link.discover():
            return None
        have = await link.refresh_interval()
        if have is None or have == want:
            return None if have is None else False
        ok, err = await link.set_refresh_interval(want)
        print(f"{dev.get('name')}: its own timer said every {have} min; "
              + (f"set to {want}, as Update every says" if ok else f"couldn't set it to {want}: {err}"), flush=True)
        return ok
    except Exception as exc:
        print(f"couldn't check a panel's own timer: {health.describe(exc)}", flush=True)
        return None
    finally:
        runtime.device(dev_id).kind.pop("timer_task", None)


class _Art(paging.Art):
    """A CrowPanel's pictures while it sleeps between updates: one page each, as a frame file."""

    async def page(self, dev, spec, st, plans, pos, item, clock) -> bytes:
        orient, display = _orient(spec), T.get_display(spec.get("display"))["id"]
        plan = plans[pos]
        count = max(1, plan["want"])
        item = min(item, count - 1)
        fg = T.footer_plan(clock=clock, pages=[(p["name"], max(1, p["want"])) for p in plans],
                           orientation=orient, display=display)
        imgs = await frames.draw_category(plan, count, pos, footer=fg, page_def=spec["pages"][plan["name"]],
                                          orient=orient, display=display, only=item,
                                          today=await frames.date_for_time(kind_of(dev).sleeps(dev)))
        # The identities it has in the frame file of every page, so a press after this wake keeps its place.
        keys = [(p["sub_keys"] or [p["name"]])[:max(1, p["want"])] for p in plans]
        cat_ids, sub_ids = subitems.compute_identities([p["name"] for p in plans], keys)
        first = sum(len(k) for k in keys[:pos])
        sub_id = sub_ids[first + min(item, len(keys[pos]) - 1)]
        return _single_epf(imgs[0], dev=dev, name=plan["name"], sub_key="", spec=spec, fg=fg,
                           pill_w=fg["pages"][pos]["w"], quiet=False, cat_id=cat_ids[pos], sub_id=sub_id)

    async def sleep(self, dev, spec, text) -> bytes:
        orient, display = _orient(spec), T.get_display(spec.get("display"))["id"]
        img = await asyncio.to_thread(sleep.render_sleep_page, text, orient, display)
        one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
        fg = T.footer_plan(clock="", orientation=orient, display=display)
        return _single_epf(one, dev=dev, name=SLEEP_PAGE, sub_key=f"{SLEEP_PAGE}:{text}", spec=spec, fg=fg, pill_w=0,
                           quiet=True, cat_flags=epf.CAT_FLAG_SLEEP | epf.CAT_FLAG_SLEEP_AUTO)

    async def empty(self, dev, spec, clock) -> bytes:
        orient, display = _orient(spec), T.get_display(spec.get("display"))["id"]
        img = await asyncio.to_thread(frames.empty_page, orient, display, clock)
        one = T.orient_for_panel(T.to_1bit(img), orient, display=display)
        fg = T.footer_plan(clock=clock, orientation=orient, display=display)
        return _single_epf(one, dev=dev, name="empty", sub_key="empty:0", spec=spec, fg=fg, pill_w=0, quiet=False)


ART = _Art()


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


WAKES = ("timer", "button", "boot")


def sleep_header(got: paging.Wake) -> dict:
    """What tells a panel that sleeps between updates to sleep. Absent, it stays connected."""
    return {"X-EPF-Sleep": f"{int(got.sleep)}; awake={int(got.awake)}"}


def next_header() -> dict:
    """What tells an always-on panel when to fetch next: the milliseconds until a moment after
    the next minute's render (cadence.py), so the time it shows is never a minute behind.
    Older firmware ignores it and keeps its own interval."""
    return {"X-EPF-Next": str(cadence.until_next_fetch_ms())}


async def frames_epf(request):
    dev = device_for(request, CrowPanel.id)
    try:
        if "cap" in request.query and runtime.set_panel_capacity(dev["id"], int(request.query["cap"])):
            runtime.LIVE._event().set()                # render to the new size now
    except ValueError:
        pass
    wake = str(request.query.get("wake") or "").lower()
    if wake:
        # Only firmware that can sleep says why it woke.
        wake = wake if wake in WAKES else "boot"
        devices.set_state(dev["id"], sleeps_seen=True, wake_source=wake,
                          last_seen=datetime.now().astimezone().isoformat(timespec="seconds"))
        paging.note_awake(dev, request.query.get("awake_ms"))
    f = runtime.device(dev["id"]).frames
    sleeps = KIND.sleeps(dev)
    asleep = {} if sleeps else next_header()
    body, etag = f.epf_strip, f.epf_strip_etag
    if sleeps:
        if wake == "timer":
            got = await paging.wake(dev, person=False, art=ART)
            if got.picture is not None:
                body, etag = got.picture, f'"{paging.digest(got.picture)}"'
            elif request.headers.get("If-None-Match"):
                # Keep what it shows (quiet hours without the sleep screen).
                raise web.HTTPNotModified(headers={**_cache_headers(f), **sleep_header(got)})
        else:
            got = paging.timing(dev, person=True)
            if not wake:
                # Not a wake: a later download while it's up (its own timer, a refresh after
                # scrolling). The panel counts presses itself; another minute here would
                # restart at every download, and with a one-minute refresh it never slept.
                got.awake = paging.awake_seconds(dev, person=False)
        asleep = sleep_header(got)
    if not body:
        raise web.HTTPServiceUnavailable(text="no epf frame rendered yet", headers=asleep)
    if etag and request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified(headers={**_cache_headers(f, etag), **asleep})
    h = {**_cache_headers(f, etag), **asleep}
    h["Content-Type"] = "application/octet-stream"
    h["X-EPF-Version"] = "3.0"
    return web.Response(body=body, headers=h)


async def api_action_refresh(request):
    """Re-render and make this panel redraw (scripts, webhooks). Always needs its key."""
    dev = device_for(request, CrowPanel.id, always=True)
    try:
        await frames.refresh_frames(runtime.SESSION)
        ha_pushed = await panel_ops.push_panel_update(dev["id"], "action endpoint")
        return web.json_response({"success": True, "action": "refresh", "ha_pushed": ha_pushed,
                                  "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")})
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


# ---------------------------------------------------------------- the editor

async def editor_stay_awake(request):
    """Ask a panel that sleeps to stay awake ten minutes at its next update (POST), or stop asking (DELETE)."""
    try:
        dev = devices.get(request.match_info["id"])
    except KeyError:
        raise web.HTTPNotFound(text="There's no such device.")
    if dev.get("kind") != CrowPanel.id:
        raise web.HTTPNotFound(text="That device isn't a CrowPanel.")
    if not KIND.sleeps(dev):
        raise web.HTTPConflict(text="It's always on, so it's already awake.")
    info = paging.ask_to_stay_awake(dev, request.method == "POST")
    return web.json_response({"stay_awake": info})


KIND = register(CrowPanel())
