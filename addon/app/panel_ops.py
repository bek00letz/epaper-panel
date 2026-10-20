"""Asking a device to refresh or step, through its kind's link (PanelLink)."""

import health
import asyncio

import devices
import kinds
from config import HA_TOKEN


def link_of(device_id):
    """The device's PanelLink, or None when the add-on can't reach it (unknown device, or a kind it can't wake)."""
    try:
        dev = devices.get(device_id)
        return kinds.of(dev).link(dev)
    except KeyError:
        return None


async def push_panel_update(device_id, reason="update"):
    """Ask a device to fetch new frames now.

    Returns whether it was delivered. If not, PanelLink keeps it pending and
    keeps retrying (panel_link_loop), so a refresh is never silently lost.
    """
    link = link_of(device_id)
    if not HA_TOKEN or link is None:
        return False
    link.request_refresh(reason)
    return await link.deliver()


async def push_all(reason="update"):
    """Ask every device the add-on can wake to fetch now. Returns whether all of them got it."""
    results = [await push_panel_update(dev["id"], reason) for dev in devices.all_devices()
               if link_of(dev["id"]) is not None]
    return bool(results) and all(results)


async def step_panel_page(device_id, delta=1):
    """Step a panel's page. Returns whether Home Assistant delivered it."""
    link = link_of(device_id)
    if not HA_TOKEN or link is None:
        return False
    ok, err = await link.step(int(delta))
    if not ok:
        print(f"panel: page step not delivered: {err}", flush=True)
    return ok


async def panel_link_loop():
    """Deliver pending refreshes (with backoff) independently of the render cadence."""
    while True:
        for dev in devices.all_devices():
            try:
                link = link_of(dev["id"])
                if link is not None:
                    await link.deliver()
            except Exception as exc:
                print(f"panel link loop error ({dev.get('name')}): {health.describe(exc)}", flush=True)
        await asyncio.sleep(5)
