#!/usr/bin/env python3
"""E-paper panel service: the entry point.

Renders the rotation on a timer and serves it two ways:

  * port 8099  - frames for the panel on the LAN (web.make_apps, panel app).
  * ingress    - the editor and its API, behind Home Assistant's own login.

The work lives in modules: frames (building the frame file), entities (the
add-on's values), sources/ (outside data, through live_data), panel_link and
panel_ops (reaching the panel), panel_setup (its ESPHome YAML), web (HTTP),
config and state (settings and what the running add-on holds).
"""
import health
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import os
import time
import aiohttp
from aiohttp import web

import cadence
import mqtt_bridge
import companion
import config
import devices
import kinds
import reach
import runtime
from config import ADDON_VERSION, FRAME_PORT, HA_TOKEN, INGRESS_PORT, PROACTIVE_TIMED_PUSH, REFRESH, RETIRED_SENSORS
from entities import retired_sensors_in_use
from frames import refresh_frames
from layouts_store import load_layouts
from panel_ops import panel_link_loop, push_panel_update
from sources.geo import get_home_timezone
from web import make_apps


async def on_refresh_button(suffix: str = ""):
    """A screen's Refresh button in Home Assistant (its entity suffix; "" for the first)."""
    dev = next((d for d in devices.all_devices() if (d.get("entity_suffix") or "") == suffix), None)
    if dev is None:
        return
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"render for refresh button failed: {health.describe(exc)}", flush=True)
    await push_panel_update(dev["id"], "refresh button")


async def render_loop():
    shown_alert: dict[str, str | None] = {}            # per device: the alert it was last told about
    runtime.LAST_PANEL_PUSH_TIME = time.time()
    if runtime.PUBLISHER is not None:
        await runtime.PUBLISHER.wait_ready(20)
    while True:
        started = time.time()
        try:
            await refresh_frames(runtime.SESSION)
            for dev, spec in devices.all_views():
                cur_alert = runtime.alert(dev["design"])["name"]
                if shown_alert.get(dev["id"], None) == cur_alert:
                    shown_alert[dev["id"]] = cur_alert
                    continue                              # unchanged (or none since we started)
                shown_alert[dev["id"]] = cur_alert
                runtime.LAST_PANEL_PUSH_TIME = time.time()
                allow_alerts = bool((spec.get("quiet_hours") or {}).get("allow_alerts", True))
                if not runtime.device(dev["id"]).frames.quiet_active or allow_alerts:
                    # Immediately push when an alert seizes or releases the screen.
                    await push_panel_update(dev["id"], "alert " + (cur_alert or "released"))
            for dev_id in [k for k in shown_alert if k not in {d["id"] for d in devices.all_devices()}]:
                del shown_alert[dev_id]
            if PROACTIVE_TIMED_PUSH:
                # Switched off (config.PROACTIVE_TIMED_PUSH); kept as it was, for the first panel only.
                first = devices.primary()
                first_frames = runtime.device(first["id"]).frames
                cur_alert = runtime.alert(first["design"])["name"]
                allow_alerts = bool((load_layouts(first["id"]).get("quiet_hours") or {}).get("allow_alerts", True))
                panel_min = kinds.of(first).update_minutes(first)
                panel_sec = max(30, panel_min * 60)
                now = time.time()
                if now - runtime.LAST_PANEL_PUSH_TIME >= panel_sec:
                    runtime.LAST_PANEL_PUSH_TIME = now
                    if first_frames.quiet_active and not (cur_alert and allow_alerts):
                        print(f"Quiet Hours active ({first_frames.quiet_reason}) -- suppressing background panel refresh push", flush=True)
                    else:
                        print(f"proactive refresh push to panel ({panel_min} min interval)", flush=True)
                        await push_panel_update(first["id"], "timed")
        except Exception as exc:
            print(f"render loop error: {health.describe(exc)}", flush=True)
            for dev in devices.all_devices():
                runtime.device(dev["id"]).frames.error = health.describe(exc)
        # Render again just after the next minute starts (cadence.py), so the time on a
        # page is right when the devices ask a moment later; or as soon as outside data
        # arrives for the first time (a newly added widget, or just after a start).
        wait, late = cadence.after_render(started, time.time(), REFRESH,
                                          cadence.zone(await get_home_timezone(runtime.SESSION, default="")))
        if late:
            print(late, flush=True)
        if await runtime.LIVE.wait_for_news(wait):
            await asyncio.sleep(1)                        # let a burst of arrivals land together


async def start(app_runners):
    panel, editor = make_apps()
    for app, port in ((panel, FRAME_PORT), (editor, INGRESS_PORT)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
        app_runners.append(runner)
        print(f"listening on :{port}", flush=True)


def start_entity_publisher():
    """Create the MQTT publisher when the Supervisor offers a broker."""
    host = (os.environ.get("MQTT_HOST") or "").strip()
    transport = None
    if host and HA_TOKEN:
        transport = mqtt_bridge.MqttTransport(
            host, int(os.environ.get("MQTT_PORT") or 1883),
            os.environ.get("MQTT_USERNAME") or "", os.environ.get("MQTT_PASSWORD") or "")
    runtime.PUBLISHER = mqtt_bridge.EntityPublisher(
        transport, runtime.HASS, config.DATA_DIR, ADDON_VERSION, on_button=on_refresh_button,
        # A Refresh button for each screen the add-on can wake (not one that sleeps on its own timer).
        buttons=lambda: [(d.get("entity_suffix") or "", d.get("name") or "") for d in kinds.shown_devices()
                         if kinds.of(d).link(d) is not None])
    in_use = retired_sensors_in_use(load_layouts(devices.primary()["id"]))
    for eid in RETIRED_SENSORS:
        if eid not in in_use:
            runtime.PUBLISHER.retire(eid)
    print("mqtt: " + (f"broker at {host}" if transport else "no broker; values stay inside the add-on"), flush=True)


async def main():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"devices: {', '.join(d['name'] for d in devices.all_devices())}", flush=True)
    runners = []
    async with aiohttp.ClientSession(trace_configs=[health.trace_config()]) as session:
        runtime.SESSION = session
        # Keep the companion integration at this version (only if it's installed).
        if companion.refresh(reach.service_address(await reach.addon_hostname(session))):
            print("companion: updated; Home Assistant loads the new copy at its next restart", flush=True)
        start_entity_publisher()
        await start(runners)
        background = [asyncio.create_task(panel_link_loop()), asyncio.create_task(runtime.LIVE.run())]
        if HA_TOKEN:
            background.append(asyncio.create_task(companion.keep_set_up(runtime.HASS)))
        if runtime.PUBLISHER is not None:
            background.append(asyncio.create_task(runtime.PUBLISHER.run()))
        try:
            await render_loop()
        finally:
            for t in background:
                t.cancel()
            for r in runners:
                await r.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
