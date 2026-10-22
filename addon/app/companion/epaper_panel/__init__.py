"""e-Paper Panel: lets screens reach the add-on through Home Assistant's own address.

Installed and kept up to date by the e-Paper Panel add-on (its Settings,
Reaching home). It does one thing: everything under /api/epaper/ is passed
to the add-on's device port on Home Assistant's internal network, and the
answer comes back. It needs no Home Assistant login, because screens can't
log in; the add-on checks every screen's own key, and refuses anything
without one.

What reaches the add-on: the request's path, query, body and headers, except
Home Assistant's own login (Authorization, cookies), so a logged-in browser
never hands its token to the add-on.
"""
from __future__ import annotations

import json
from pathlib import Path

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

DOMAIN = "epaper_panel"
PREFIX = "/api/epaper"
# Where the add-on is, written by the add-on when it installs this.
TARGET_FILE = Path(__file__).parent / "target.json"

DROP_REQUEST = {"authorization", "cookie", "host", "connection", "keep-alive", "proxy-authorization",
                "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade", "content-length",
                "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-prefix"}
KEEP_RESPONSE = {"content-type", "etag", "last-modified", "cache-control", "retry-after", "x-epf-version",
                 "x-epf-sleep",               # how long a panel that sleeps between updates sleeps
                 "x-epf-next"}                # when an always-on panel fetches next (clock alignment)
TIMEOUT = aiohttp.ClientTimeout(total=30)


def _target() -> str:
    try:
        return str(json.loads(TARGET_FILE.read_text())["url"]).rstrip("/")
    except (OSError, ValueError, KeyError):
        return ""


class DeviceView(HomeAssistantView):
    url = PREFIX + "/{path:.*}"
    name = "api:epaper_panel"
    requires_auth = False          # screens can't log in; the add-on checks their keys

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.enabled = True

    async def _forward(self, request: web.Request, path: str) -> web.Response:
        target = _target()
        if not self.enabled or not target:
            return web.Response(status=404, text="The e-Paper Panel add-on isn't set up for this.")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQUEST}
        # Who asked and how, so the add-on can slow down wrong keys per sender and
        # build addresses the screen can use.
        headers["X-Forwarded-For"] = request.remote or ""
        headers["X-Forwarded-Host"] = request.host
        headers["X-Forwarded-Proto"] = request.scheme
        headers["X-Forwarded-Prefix"] = PREFIX
        body = await request.read() if request.can_read_body else None
        session = async_get_clientsession(self.hass)
        try:
            async with session.request(request.method, f"{target}/{path}", params=request.query,
                                       headers=headers, data=body, allow_redirects=False, timeout=TIMEOUT) as r:
                data = await r.read()
                out = {k: v for k, v in r.headers.items() if k.lower() in KEEP_RESPONSE}
                return web.Response(status=r.status, body=data, headers=out)
        except (aiohttp.ClientError, TimeoutError):
            return web.Response(status=502, text="The e-Paper Panel add-on isn't answering.")

    async def get(self, request: web.Request, path: str) -> web.Response:
        return await self._forward(request, path)

    async def post(self, request: web.Request, path: str) -> web.Response:
        return await self._forward(request, path)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    view = hass.data.get(DOMAIN)
    if view is None:
        # A view can't be taken back out of Home Assistant, so it's registered
        # once and switched off when the entry goes.
        view = hass.data[DOMAIN] = DeviceView(hass)
        hass.http.register_view(view)
    view.enabled = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    view = hass.data.get(DOMAIN)
    if view is not None:
        view.enabled = False
    return True
