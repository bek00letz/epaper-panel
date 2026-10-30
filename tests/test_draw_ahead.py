"""The rule every kind keeps: a request never draws (kinds/__init__.py).

The render cycle draws everything a device can fetch; the device port's routes
only hand over what's ready. Here every kind's device routes are driven after a
render cycle, in every mode a screen can be in, and anything drawn while a
request is answered fails the test. A new kind, or a new route, has to be added
to DRIVEN below (or to COMMANDS, with the reason), or this fails too.

The one exception, a wake that finds nothing drawn for the size the screen has
now, is pinned at the end, with the line it logs.
"""
import contextlib
import io
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import config
import devices
import frames
import kinds
import paging
import web
import reporters
from kinds import trmnl
from render import layout, sleep

from test_trmnl import display_headers, image_headers, log_headers, setup_headers

# Routes that ask for something to happen rather than fetch: what they ask for may be a
# render cycle (frames.refresh_frames), which is where drawing belongs.
COMMANDS = {
    "/api/action/refresh": "re-renders on purpose: it asks for a render cycle, then wakes the panel",
}


class Draws:
    """Counts every page, sleep screen and empty page drawn while it's on."""

    def __init__(self):
        self.seen = []
        self._patches = []

    def __enter__(self):
        for owner, name in ((layout, "render_page"), (sleep, "render_sleep_page"), (frames, "draw_category"),
                            (frames, "empty_page")):
            real = getattr(owner, name)

            def counted(*a, _real=real, _name=name, **kw):
                self.seen.append(_name)
                return _real(*a, **kw)
            p = mock.patch.object(owner, name, counted)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestARequestNeverDraws(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        trmnl._PAIRING.clear()
        # Device 1 stays connected (as every install's first panel), a second CrowPanel sleeps
        # between updates, and a TRMNL is paired. Several pages, so wakes move through them.
        self.hall = devices.add("crowpanel", "Hall", "crowpanel_579", copy_from="1", update_minutes=15)
        self.desk = devices.add("trmnl", "Desk", "trmnl_og", copy_from="1")
        panel, editor = web.make_apps()
        self.lan = TestClient(TestServer(panel))
        self.ed = TestClient(TestServer(editor))
        await self.lan.start_server()
        await self.ed.start_server()
        await self.ed.post(f"/api/devices/{self.desk['id']}/pair")
        got = await (await self.lan.get("/api/setup", headers=setup_headers())).json()
        self.desk_key = got["api_key"]
        await frames.refresh_frames(None)                     # the cycle: everything drawn here

    async def asyncTearDown(self):
        await self.lan.close()
        await self.ed.close()
        trmnl._PAIRING.clear()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        support.use_test_data_dir()

    # Each kind: how its device routes are driven, in each mode its screens can be in.
    async def drive_crowpanel(self) -> set[str]:
        hall = {"token": devices.key_of(devices.get(self.hall["id"]))}
        first = {"token": devices.key_of(devices.primary())}
        for q in (first, hall):
            for path in ("/frame.png", "/frames.png", "/frame.epf", "/frames.epf"):
                r = await self.lan.get(path, params=q)
                self.assertEqual(r.status, 200, path)
                etag = r.headers.get("ETag")
                self.assertEqual((await self.lan.get(path, params=q, headers={"If-None-Match": etag})).status, 304)
            await self.lan.get("/frame.png", params={**q, "page": "2"})
            await self.lan.get("/frame.epf", params={**q, "page": "2"})
            for wake in ("timer", "timer", "button", "boot"):
                r = await self.lan.get("/frames.epf", params={**q, "wake": wake, "cap": "2097152", "awake_ms": "3100"})
                self.assertEqual(r.status, 200, wake)
            r = await self.lan.post("/api/action/page", params=q, json={"delta": 1})
            self.assertEqual(r.status, 200)
        return {"/frame.png", "/frames.png", "/frame.epf", "/frames.epf", "/api/action/page"}

    async def drive_trmnl(self) -> set[str]:
        await self.lan.get("/api/setup", headers=setup_headers())            # outside the window: refused
        names = []
        for source in ("timer", "timer", "button", "timer", "powercycle"):
            r = await self.lan.get("/api/display", headers=display_headers(self.desk_key, source=source))
            body = await r.json()
            self.assertEqual(r.status, 200)
            self.assertTrue(body["filename"], "a picture, from what the cycle drew")
            names.append(body["image_url"])
        base = str(self.lan.make_url(""))
        r = await self.lan.get(names[-1][len(base):], headers=image_headers(self.desk_key))
        self.assertEqual(r.status, 200)
        await self.lan.post("/api/log", json={"logs": [{"message": "hello"}]}, headers=log_headers(self.desk_key))
        return {"/api/setup", "/api/display", "/api/log", "/api/image/{name}"}

    async def drive_reporters(self):
        """A computer that reports AI usage (reporters.py): it pairs and sends; nothing is drawn for it."""
        code = reporters.open_pairing()["code"]
        got = await (await self.lan.post("/api/usage/pair", json={"code": code, "platform": "macos"})).json()
        r = await self.lan.post("/api/usage", headers={reporters.KEY_HEADER: got["key"]},
                                json={"format": 1, "providers": []})
        self.assertEqual(r.status, 200)
        return {"/api/usage/pair", "/api/usage"}

    async def test_every_kinds_device_routes_only_hand_over_what_the_cycle_drew(self):
        drivers = {"crowpanel": self.drive_crowpanel, "trmnl": self.drive_trmnl}
        self.assertEqual(set(kinds.KINDS), set(drivers), "a new kind needs its routes driven here")
        driven = set()
        with Draws() as draws:
            for kind_id in kinds.KINDS:
                driven |= await drivers[kind_id]()
            driven |= await self.drive_reporters()
            r = await self.lan.get("/status", params={"token": devices.key_of(devices.primary())})
            self.assertEqual(r.status, 200)
        self.assertEqual(draws.seen, [], "something was drawn while a device waited for its answer")
        for route in reporters.routes():
            self.assertIn(route.path, driven, f"reporters: {route.path} isn't driven by this test")
        for kind in kinds.KINDS.values():
            for route in kind.routes():
                path = route.path
                self.assertTrue(path in driven or path in COMMANDS, f"{kind.id}: {path} isn't driven by this test")

    async def test_a_new_size_is_the_one_wake_drawn_on_request_and_it_says_so(self):
        log = io.StringIO()
        with Draws() as draws, contextlib.redirect_stdout(log):
            r = await self.lan.get("/api/display", headers=display_headers(self.desk_key, width=1872, height=1404))
        self.assertEqual(r.status, 200)
        self.assertTrue((await r.json())["filename"])
        self.assertIn("render_page", draws.seen)
        self.assertIn("drawing its picture while it waits (it said it has a new size)", log.getvalue())
        await frames.refresh_frames(None)                     # the next cycle draws ahead at the new size
        with Draws() as draws:
            await self.lan.get("/api/display", headers=display_headers(self.desk_key, width=1872, height=1404))
        self.assertEqual(draws.seen, [])

    async def test_before_the_first_cycle_nothing_is_drawn_either(self):
        paging.forget(devices.get(self.desk["id"]))
        with Draws() as draws:
            r = await self.lan.get("/api/display", headers=display_headers(self.desk_key))
        body = await r.json()
        self.assertEqual(body["refresh_rate"], paging.FIRST_RENDER_SECONDS, "asks again in a minute")
        self.assertEqual(draws.seen, [])


if __name__ == "__main__":
    unittest.main()
