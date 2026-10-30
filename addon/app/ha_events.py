"""Home Assistant's events, heard as they happen: one websocket for every kind the add-on listens to.

Most of what pages show is a state, read when it's needed. A few things are only ever said as an
event (the IMAP integration announces each new message as `imap_content`), so they must be heard
when they happen. A module asks with `listen(event_type, handler)`, from a fetch, only once a page
needs it: nothing is listened to that no page shows.

One connection carries every subscription. It reconnects on its own, waiting longer each time it
fails (5 s up to 5 min), and reports as the service that asked, so a lost connection shows in its
problem sensor. A handler that fails is logged and the others still run.
"""
from __future__ import annotations

import asyncio
from typing import Callable

import aiohttp

import health
import runtime
from config import HA_BASE, HA_TOKEN

_handlers: dict[str, list[Callable[[dict], None]]] = {}
_services: dict[str, str] = {}          # event type -> the service it reports as
_task: asyncio.Task | None = None
RETRY = (5, 15, 60, 300)


def listen(event_type: str, handler: Callable[[dict], None], service: str = "") -> None:
    """Hear every `event_type` from now on (its data goes to `handler`). Safe to call again: a
    handler is added once, and the connection starts once."""
    global _task
    got = _handlers.setdefault(event_type, [])
    if handler not in got:
        got.append(handler)
    if service:
        _services[event_type] = service
    if not HA_TOKEN:
        return
    if _task is None or _task.done():
        try:
            _task = asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            pass                                # not in the add-on's loop (a test): nothing to connect


def listening() -> list[str]:
    return sorted(_handlers)


def dispatch(event: dict) -> None:
    """One event to its handlers."""
    for handler in list(_handlers.get(str((event or {}).get("event_type") or ""), [])):
        try:
            handler((event or {}).get("data") or {})
        except Exception as exc:                # noqa: BLE001 -- one handler must not stop the rest
            print(f"ha_events: a handler for {event.get('event_type')} failed: {health.describe(exc)}", flush=True)


def _report(ok: bool, exc=None) -> None:
    for name in set(_services.values()):
        health.ok(name) if ok else health.fail(name, exc or "Home Assistant's event connection closed")


async def _connect_once(session) -> None:
    url = HA_BASE.replace("http://", "ws://").replace("https://", "wss://") + "/websocket"
    async with session.ws_connect(url, heartbeat=30, timeout=aiohttp.ClientWSTimeout(ws_close=15)) as ws:
        await ws.receive_json(timeout=15)
        await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
        if (await ws.receive_json(timeout=15)).get("type") != "auth_ok":
            raise PermissionError("Home Assistant refused the add-on's token")
        subscribed: set[str] = set()
        ids = iter(range(1, 1 << 30))
        _report(True)
        while True:
            for event_type in set(_handlers) - subscribed:      # one asked for after connecting
                await ws.send_json({"id": next(ids), "type": "subscribe_events", "event_type": event_type})
                subscribed.add(event_type)
            try:
                msg = await ws.receive_json(timeout=60)
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "event":
                dispatch(msg.get("event") or {})


async def _run() -> None:
    tries = 0
    while True:
        session = runtime.SESSION
        try:
            if session is None:
                raise ConnectionError("no connection yet")
            await _connect_once(session)
            tries = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:                # noqa: BLE001 -- said in plain words, then tried again
            _report(False, exc)
        await asyncio.sleep(RETRY[min(tries, len(RETRY) - 1)])
        tries += 1
