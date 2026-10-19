"""Asking the panel to refresh or step, through PanelLink."""

import asyncio

import runtime
from config import HA_TOKEN


async def push_panel_update(reason="update"):
    """Ask the panel to fetch new frames now.

    Returns whether it was delivered. If not, PanelLink keeps it pending and
    keeps retrying (panel_link_loop), so a refresh is never silently lost.
    """
    if not HA_TOKEN:
        return False
    runtime.LINK.request_refresh(reason)
    return await runtime.LINK.deliver()


async def step_panel_page(delta=1):
    """Step the physical panel's page. Returns whether Home Assistant delivered it."""
    if not HA_TOKEN:
        return False
    ok, err = await runtime.LINK.step(int(delta))
    if not ok:
        print(f"panel: page step not delivered: {err}", flush=True)
    return ok


async def panel_link_loop():
    """Deliver pending refreshes (with backoff) independently of the render cadence."""
    while True:
        try:
            await runtime.LINK.deliver()
        except Exception as exc:
            print(f"panel link loop error: {exc!r}", flush=True)
        await asyncio.sleep(5)
