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
import json
import os
import re
import time
import aiohttp
from aiohttp import web

import mqtt_bridge
import config
import runtime
from config import ADDON_VERSION, FRAME_PORT, HA_TOKEN, INGRESS_PORT, PROACTIVE_TIMED_PUSH, REFRESH, RETIRED_SENSORS
from entities import retired_sensors_in_use
from frames import refresh_frames
from layouts_store import load_layouts
from panel_ops import panel_link_loop, push_panel_update
from panel_setup import load_panel_setup
from web import make_apps


async def on_refresh_button():
    """The "Refresh panel" button in Home Assistant."""
    try:
        await refresh_frames(runtime.SESSION)
    except Exception as exc:
        print(f"render for refresh button failed: {health.describe(exc)}", flush=True)
    await push_panel_update("refresh button")


async def render_loop():
    was_alert = None
    runtime.LAST_PANEL_PUSH_TIME = time.time()
    if runtime.PUBLISHER is not None:
        await runtime.PUBLISHER.wait_ready(20)
    while True:
        try:
            await refresh_frames(runtime.SESSION)
            cur_alert = runtime.ALERT["name"]
            spec = load_layouts()
            allow_alerts = bool((spec.get("quiet_hours") or {}).get("allow_alerts", True))
            if cur_alert != was_alert:
                was_alert = cur_alert
                runtime.LAST_PANEL_PUSH_TIME = time.time()
                if not runtime.FRAMES.quiet_active or allow_alerts:
                    # Immediately push when an alert seizes or releases the screen.
                    await push_panel_update("alert " + (cur_alert or "released"))
            elif PROACTIVE_TIMED_PUSH:
                panel_cfg = load_panel_setup()
                m_int = re.search(r"\d+", str(panel_cfg.get("refresh_interval", "5")))
                panel_min = int(m_int.group(0)) if m_int else 5
                panel_sec = max(30, panel_min * 60)
                now = time.time()
                if now - runtime.LAST_PANEL_PUSH_TIME >= panel_sec:
                    runtime.LAST_PANEL_PUSH_TIME = now
                    if runtime.FRAMES.quiet_active and not (cur_alert and allow_alerts):
                        print(f"Quiet Hours active ({runtime.FRAMES.quiet_reason}) -- suppressing background panel refresh push", flush=True)
                    else:
                        print(f"proactive refresh push to panel ({panel_min} min interval)", flush=True)
                        await push_panel_update("timed")
        except Exception as exc:
            print(f"render loop error: {health.describe(exc)}", flush=True)
            runtime.FRAMES.error = health.describe(exc)
        # Render again on the cadence, or as soon as outside data arrives for
        # the first time (a newly added widget, or just after a start).
        if await runtime.LIVE.wait_for_news(REFRESH):
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
    runtime.PUBLISHER = mqtt_bridge.EntityPublisher(transport, runtime.HASS, config.DATA_DIR, ADDON_VERSION,
                                            on_button=on_refresh_button)
    in_use = retired_sensors_in_use(load_layouts())
    for eid in RETIRED_SENSORS:
        if eid not in in_use:
            runtime.PUBLISHER.retire(eid)
    print("mqtt: " + (f"broker at {host}" if transport else "no broker; values stay inside the add-on"), flush=True)


async def main():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if config.panel_setup_path().exists():
        try:
            saved_dev = json.loads(config.panel_setup_path().read_text()).get("device_name")
            if saved_dev:
                runtime.ESPHOME_DEVICE = re.sub(r"[^a-z0-9_]+", "_", saved_dev.lower()).strip("_") or runtime.ESPHOME_DEVICE
        except Exception:
            pass
    runners = []
    async with aiohttp.ClientSession(trace_configs=[health.trace_config()]) as session:
        runtime.SESSION = session
        start_entity_publisher()
        await start(runners)
        background = [asyncio.create_task(panel_link_loop()), asyncio.create_task(runtime.LIVE.run())]
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
