"""Kinds of device: what each supports and how it is served. The core names none of them.

A kind says which display sizes it has, which routes it adds to the device
port, whether the add-on can wake it early, and how a device of that kind gets
its pages: `render` turns a design's pages for this cycle (frames.DesignState)
into what the device fetches.

Requests on the device port say which device they come from by its key
(devices.authenticate). `device_for` is the one place that's checked.
"""
from __future__ import annotations

import time

from aiohttp import web

import devices
import frame_token
import reach


class Kind:
    id = ""
    name = ""
    # Who decides which page is on screen, and how often it fetches: "device" or "addon".
    picks_page = "device"
    owns_interval = "device"

    def displays(self) -> list[str]:
        """Display profiles (render.theme.DISPLAYS) a device of this kind can have."""
        raise NotImplementedError

    def routes(self) -> list:
        """aiohttp routes this kind adds to the device port."""
        return []

    def link(self, dev: dict):
        """How the add-on reaches the device to wake it early (a PanelLink), or None if it can't."""
        return None

    async def render(self, session, dev: dict, spec: dict, st, quiet_active: bool, quiet_reason: str):
        """The device's new runtime.Frames from its design's state this cycle."""
        raise NotImplementedError


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    KINDS[kind.id] = kind
    return kind


def of(dev: dict) -> Kind:
    found = KINDS.get(dev.get("kind"))
    if found is None:
        raise KeyError(f"{dev.get('name')}: no kind of device called {str(dev.get('kind'))[:20]!r}")
    return found


def provided_key(request) -> str:
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return request.query.get("token") or request.headers.get("X-Frame-Token") or ""


class WrongKeys:
    """Wrong keys slow down: a sender that gets LIMIT wrong in WINDOW seconds is
    refused for BLOCK seconds, whatever it sends. Keys can't be guessed; this
    is for a frame token someone chose themselves, and for the noise."""
    LIMIT, WINDOW, BLOCK = 10, 600.0, 600.0

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._wrong: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def blocked_for(self, who: str) -> float:
        until = self._blocked.get(who, 0.0)
        left = until - self._clock()
        if left <= 0:
            self._blocked.pop(who, None)
            return 0.0
        return left

    def wrong(self, who: str) -> None:
        now = self._clock()
        recent = [t for t in self._wrong.get(who, []) if now - t < self.WINDOW] + [now]
        self._wrong[who] = recent
        if len(recent) >= self.LIMIT:
            self._blocked[who] = now + self.BLOCK
            self._wrong.pop(who, None)
            print(f"device port: {len(recent)} wrong keys from one sender; refusing it for "
                  f"{int(self.BLOCK // 60)} minutes", flush=True)
        if len(self._wrong) > 1000:                    # never grows without bound
            self._wrong = dict(list(self._wrong.items())[-500:])


WRONG_KEYS = WrongKeys()


def device_for(request, kind: str | None = None, *, always: bool = False) -> dict:
    """The device a request on the device port comes from, by its key.

    `always`: the request makes something happen, so it needs the key even
    while the first panel's frames are still switching over to it
    (frame_token). Away from home (reach.py) every request needs one.
    `kind`: the route belongs to that kind of device only.
    """
    why = reach.refusal(request)
    if why:
        raise web.HTTPForbidden(text=why)
    who = reach.sender(request)
    wait = WRONG_KEYS.blocked_for(who)
    if wait:
        raise web.HTTPTooManyRequests(text="Too many wrong keys. Try again later.",
                                      headers={"Retry-After": str(int(wait) + 1)})
    dev, verdict = devices.authenticate(provided_key(request))
    if (verdict == "missing" and not always and dev is not None and not frame_token.required()
            and not reach.remote_on()):
        verdict = "ok"
    if verdict == "wrong":
        WRONG_KEYS.wrong(who)
    if verdict != "ok":
        if always:
            raise web.HTTPUnauthorized(text="This needs the frame token (Panel setup shows it in the panel's YAML).")
        raise web.HTTPUnauthorized(text="invalid or missing token")
    if kind is not None and dev.get("kind") != kind:
        raise web.HTTPNotFound(text="not for this kind of device")
    return dev


from kinds import crowpanel  # noqa: E402,F401  (registers itself)
