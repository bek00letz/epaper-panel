"""Kinds of device: what each supports and how it is served. The core names none of them.

A kind says which display sizes it has, which routes it adds to the device
port, whether the add-on can wake it early, and how a device of that kind gets
its pages: `render` turns a design's pages for this cycle (frames.DesignState)
into what the device fetches.

**The rule: a request never draws.** The render cycle (frames.refresh_frames,
which calls `render`) draws everything a device can fetch before the next
cycle; the device port's routes only hand over what's ready. A device's radio
is on while it waits for an answer, so drawing then is paid for in battery,
and it's the cycle's job anyway. The one exception: a device that asks before
anything was drawn for the size it has now (just after a start, or it just
said it has a new size) may be drawn for there and then, and the log says so.
tests/test_draw_ahead.py drives every kind's device routes to pin this.

Every screen has two timers, Update every and Rotate every (timing.py), the
same settings for every kind. Updating every minute is always on; anything
longer, the screen sleeps between updates and uses the shared mode in
paging.py, the add-on picking its page: its kind keeps only the protocol. A
kind that can't stay connected (a TRMNL) has no always-on choice (`stays_on`).

A kind can be optional (an add-on option turns it on). While it's off its
routes don't exist, its devices aren't drawn and the editor shows none of
them (`enabled`, `shown`).

Requests on the device port say which device they come from by its key
(devices.authenticate). `device_for` is the one place that's checked.
"""
from __future__ import annotations

import time

from aiohttp import web

import devices
import frame_token
import reach
import cadence
import timing


class Kind:
    id = ""
    name = ""
    # Who decides which page is on screen, and how often it fetches: "device" or "addon".
    picks_page = "device"
    owns_interval = "device"
    # How a new one is set up in the editor: "install" (Panel setup) or "pair".
    setup_flow = "install"
    # Whether it can stay connected (Update every 1 minute, always on), or always sleeps between updates.
    stays_on = True
    # The shortest Update every, in minutes, of a kind that can't stay connected (a TRMNL: 5).
    shortest_update = timing.ASLEEP_FROM
    # The shortest sleep, in seconds, this kind's firmware takes (cadence.align_sleep).
    shortest_sleep = cadence.MIN_SLEEP

    @property
    def timers(self) -> dict:
        """What timing.py needs to know about this kind: whether it can stay on, and its shortest update."""
        return {"stays_on": self.stays_on, "shortest": self.shortest_update}

    def enabled(self) -> bool:
        """Whether this kind is on (an optional kind has an add-on option)."""
        return True

    def displays(self) -> list[str]:
        """Display profiles (render.theme.DISPLAYS) a device of this kind can have."""
        raise NotImplementedError

    def routes(self) -> list:
        """aiohttp routes this kind adds to the device port."""
        return []

    def editor_routes(self) -> list:
        """aiohttp routes this kind adds to the editor's API (behind Ingress)."""
        return []

    def link(self, dev: dict):
        """How the add-on reaches the device to wake it early (a PanelLink), or None if it can't."""
        return None

    def update_minutes(self, dev: dict) -> int:
        """Update every: minutes between fetches (timing.py). 1 is always on."""
        return timing.update_minutes(dev, **self.timers)

    def describe(self, dev: dict) -> dict:
        """What the editor shows about the device beyond the core's fields. Never its key."""
        return {}

    def settings(self, dev: dict, body: dict) -> dict:
        """The device fields an editor change asks for ({} when it asks for none of this kind's).
        Raises ValueError, with what to fix, for a value it can't take."""
        return {}

    def entities(self, dev: dict) -> set[str]:
        """Home Assistant entities this kind publishes for the device (without its suffix):
        kept while the device is quiet, however long it sleeps."""
        return set()

    def sleeps(self, dev: dict) -> bool:
        """Whether this screen sleeps between updates, the add-on picking its page and when it
        wakes (paging.py): anything but always on. Its Update every says, never its kind."""
        return timing.sleeps(dev, **self.timers)

    def room(self, dev: dict) -> tuple[int, int] | None:
        """(bytes a page takes, bytes it holds) for a screen that keeps its whole rotation in its own
        memory and can run out of room (an always-on CrowPanel); None for one that fetches a page
        at a time, which never does."""
        return None

    async def switched(self, old: dict, dev: dict) -> str | None:
        """The screen started or stopped sleeping between updates (`sleeps`). What the editor should
        say about when that takes effect, or None."""
        return None

    async def render(self, session, dev: dict, spec: dict, st, quiet_active: bool, quiet_reason: str):
        """The device's new runtime.Frames from its design's state this cycle: everything it can
        fetch until the next cycle, drawn now (the rule above). Its routes only hand it over."""
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


def enabled_kinds() -> list[Kind]:
    return [k for k in KINDS.values() if k.enabled()]


def shown(dev: dict) -> bool:
    """Whether the add-on drives this device now: its kind exists and is on."""
    found = KINDS.get(dev.get("kind"))
    return found is not None and found.enabled()


def shown_devices() -> list[dict]:
    """The devices the add-on drives now, in the order they were added."""
    return [d for d in devices.all_devices() if shown(d)]


def provided_key(request) -> str:
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    # Access-Token: how a TRMNL sends its key (usetrmnl/firmware, request_headers.cpp).
    return (request.query.get("token") or request.headers.get("X-Frame-Token")
            or request.headers.get("Access-Token") or "")


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
    if not shown(dev):
        raise web.HTTPUnauthorized(text="invalid or missing token")      # its kind is off
    if kind is not None and dev.get("kind") != kind:
        raise web.HTTPNotFound(text="not for this kind of device")
    return dev


async def _home_host() -> str:
    """Home Assistant's name on the home network: what a panel's setup was given, or its own home
    address. Never the browser's, which may be a tunnel's (reach.home_address)."""
    import urllib.parse
    import runtime
    for dev in devices.all_devices():
        raw = str((dev.get("setup") or {}).get("ha_host") or "").strip()
        host = urllib.parse.urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
        if reach.HOST_RE.fullmatch(host):
            return host                                # what a panel's setup was given
    return await reach.home_address(runtime.HASS, runtime.SESSION)


async def device_port_addresses() -> list[dict]:
    """Where something on the home network, and away from it, reaches the device port: what a TRMNL
    is told when it pairs, and where an AI usage reporter sends (reporters.py). [{"where", "url"}],
    home first, away only while Reaching home is on."""
    import panel_setup
    import runtime
    port = await panel_setup._detect_external_port(runtime.SESSION)
    out = [{"where": "home", "url": f"http://{await _home_host()}:{port}"}]
    away = await reach.public_base(runtime.HASS)
    if away:
        out.append({"where": "away", "url": away})
    return out


from kinds import crowpanel, trmnl  # noqa: E402,F401  (register themselves)
