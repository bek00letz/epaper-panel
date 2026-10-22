"""Reaching home: who may come in which way, keys away from home, wrong keys, the companion integration."""
import asyncio
import json
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import support
import companion
from hass import HassError
import config
import devices
import frame_token
import frames
import kinds
import panel_setup
import reach
from kinds import crowpanel
from test_devices import fresh_data_dir

HOME_PEER, TUNNEL_PEER, HA_PEER = "192.168.1.40", "172.30.33.5", "172.30.32.1"


def request(path, peer=HOME_PEER, headers=None):
    transport = mock.Mock()
    transport.get_extra_info = lambda key, default=None: (peer, 40000) if key == "peername" else default
    return make_mocked_request("GET", path, headers=headers or {}, transport=transport)


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        self._token = config.FRAME_TOKEN
        config.FRAME_TOKEN = ""
        await frames.refresh_frames(None)
        self.key = frame_token.token()

    async def asyncTearDown(self):
        config.FRAME_TOKEN = self._token
        kinds.WRONG_KEYS = kinds.WrongKeys()
        support.use_test_data_dir()

    async def fetch(self, *args, **kw):
        return await crowpanel.frames_epf(request(*args, **kw))


class TestWhoComesInWhichWay(Base):
    async def test_at_home_a_screen_on_the_network_gets_in(self):
        self.assertEqual((await self.fetch(f"/frames.epf?token={self.key}")).status, 200)

    async def test_at_home_a_tunnel_pointed_at_the_add_on_is_refused(self):
        with self.assertRaises(web.HTTPForbidden):
            await self.fetch(f"/frames.epf?token={self.key}", TUNNEL_PEER, {"CF-Connecting-IP": "203.0.113.9"})

    async def test_your_own_address_lets_the_tunnel_in_with_a_key(self):
        reach.save("own", "panel.example.com")
        self.assertEqual(reach.settings()["address"], "https://panel.example.com")
        r = await self.fetch(f"/frames.epf?token={self.key}", TUNNEL_PEER, {"CF-Connecting-IP": "203.0.113.9"})
        self.assertEqual(r.status, 200)

    async def test_away_from_home_there_is_no_switch_over(self):
        self.assertFalse(frame_token.required(), "the first panel hasn't used its token yet")
        self.assertEqual((await self.fetch("/frames.epf")).status, 200, "so at home it still works without")
        reach.save("own", "https://panel.example.com")
        with self.assertRaises(web.HTTPUnauthorized):
            await self.fetch("/frames.epf")

    async def test_the_companion_route_only_while_it_is_chosen(self):
        via_ha = {"X-Forwarded-Prefix": "/api/epaper", "X-Forwarded-For": "203.0.113.9"}
        with self.assertRaises(web.HTTPForbidden):
            await self.fetch(f"/frames.epf?token={self.key}", HA_PEER, via_ha)
        reach.save("ha")
        self.assertEqual((await self.fetch(f"/frames.epf?token={self.key}", HA_PEER, via_ha)).status, 200)


class TestWrongKeys(Base):
    async def test_a_sender_with_too_many_wrong_keys_is_refused_for_a_while(self):
        reach.save("own", "https://panel.example.com")
        attacker = {"CF-Connecting-IP": "203.0.113.66"}
        for _ in range(kinds.WrongKeys.LIMIT):
            with self.assertRaises(web.HTTPUnauthorized):
                await self.fetch("/frames.epf?token=guess", TUNNEL_PEER, attacker)
        with self.assertRaises(web.HTTPTooManyRequests) as ctx:
            await self.fetch(f"/frames.epf?token={self.key}", TUNNEL_PEER, attacker)
        self.assertIn("Retry-After", ctx.exception.headers)
        friend = {"CF-Connecting-IP": "198.51.100.7"}
        self.assertEqual((await self.fetch(f"/frames.epf?token={self.key}", TUNNEL_PEER, friend)).status, 200,
                         "others behind the same tunnel aren't affected")

    async def test_through_the_companion_a_sender_cant_say_who_it_is(self):
        reach.save("ha")
        for i in range(kinds.WrongKeys.LIMIT):
            # Made-up addresses in headers the companion passes on untouched; it writes X-Forwarded-For itself.
            spoof = {"X-Forwarded-For": "203.0.113.66", "X-Forwarded-Prefix": reach.COMPANION_PREFIX,
                     "CF-Connecting-IP": f"198.51.100.{i}", "X-Real-IP": f"192.0.2.{i}"}
            with self.assertRaises(web.HTTPUnauthorized):
                await self.fetch("/frames.epf?token=guess", HA_PEER, spoof)
        with self.assertRaises(web.HTTPTooManyRequests):
            await self.fetch("/frames.epf?token=guess", HA_PEER, spoof)

    def test_it_lifts(self):
        now = [0.0]
        wk = kinds.WrongKeys(clock=lambda: now[0])
        for _ in range(wk.LIMIT):
            wk.wrong("x")
        self.assertGreater(wk.blocked_for("x"), 0)
        now[0] += wk.BLOCK + 1
        self.assertEqual(wk.blocked_for("x"), 0)


class TestAddresses(unittest.TestCase):
    def test_only_https_away_from_home(self):
        with self.assertRaises(ValueError):
            reach.clean_address("http://panel.example.com")
        with self.assertRaises(ValueError):
            reach.clean_address("")
        self.assertEqual(reach.clean_address("https://panel.example.com/"), "https://panel.example.com")

    def test_your_own_address_can_be_picked_before_there_is_one(self):
        # Picking it used to be refused ("Enter the address…"), and the address field only
        # shows once it's picked, so it could never be chosen.
        fresh_data_dir()
        try:
            reach.save("ha")
            s = reach.save("own", "")
            self.assertEqual((s["chosen"], s["mode"]), ("own", "ha"), "screens keep the way they had")
            self.assertEqual(reach.settings()["chosen"], "own")
            with self.assertRaises(ValueError):
                reach.save("own", "http://panel.example.com")
            self.assertEqual(reach.settings()["mode"], "ha", "a wrong address changes nothing")
            s = reach.save("own", "panel.example.com")
            self.assertEqual((s["chosen"], s["mode"], s["address"]), ("own", "own", "https://panel.example.com"))
            s = reach.save("home")
            self.assertEqual((s["chosen"], s["mode"]), ("home", "home"))
            s = reach.save("own", "")
            self.assertEqual((s["mode"], s["address"]), ("own", "https://panel.example.com"), "the saved one comes back")
        finally:
            support.use_test_data_dir()

    def test_a_file_from_before_has_its_way_picked(self):
        fresh_data_dir()
        try:
            (config.DATA_DIR / reach.FILE).write_text('{"mode": "ha", "address": ""}')
            self.assertEqual(reach.settings()["chosen"], "ha")
        finally:
            support.use_test_data_dir()

    def test_the_pane_shows_what_is_picked_and_what_screens_use(self):
        pane = (support.APP / "web" / "app" / "sheets.js").read_text()
        pane = pane[pane.index("async function reachPane"):pane.index("async function sourcesPane")]
        self.assertIn('String(picked() === m)', pane)
        self.assertIn('if (picked() === "own") {', pane)
        self.assertIn("Until you save an https address here, devices keep reaching the add-on", pane)

    def test_the_panel_file_uses_the_outside_address(self):
        fresh_data_dir()
        try:
            dev = devices.primary()
            yaml_text, _ = panel_setup.generate_esphome_yaml(panel_setup.load_panel_setup(dev), dev,
                                                             "https://panel.example.com")
            self.assertIn(f"https://panel.example.com/frames.epf?token={frame_token.token()}", yaml_text)
        finally:
            support.use_test_data_dir()


class TestCompanion(unittest.TestCase):
    def setUp(self):
        self._dir, self._version = config.HA_CONFIG_DIR, config.ADDON_VERSION
        config.HA_CONFIG_DIR = support.temp_dir()
        config.ADDON_VERSION = "0.11.0"

    def tearDown(self):
        config.HA_CONFIG_DIR, config.ADDON_VERSION = self._dir, self._version

    def test_installed_at_the_add_ons_version_and_address(self):
        companion.install("http://0ab7a54f-epaper-panel:8099")
        dest = config.HA_CONFIG_DIR / "custom_components" / "epaper_panel"
        self.assertEqual(json.loads((dest / "manifest.json").read_text())["version"], "0.11.0")
        self.assertEqual(json.loads((dest / "target.json").read_text())["url"], "http://0ab7a54f-epaper-panel:8099")
        self.assertTrue((dest / "config_flow.py").exists())
        self.assertFalse(companion.refresh("http://0ab7a54f-epaper-panel:8099"), "nothing to do")
        config.ADDON_VERSION = "0.11.1"
        self.assertTrue(companion.refresh("http://0ab7a54f-epaper-panel:8099"), "an update follows the add-on")
        self.assertEqual(companion.installed_version(), "0.11.1")

    def test_not_installed_means_not_touched(self):
        self.assertFalse(companion.refresh("http://x:8099"))
        self.assertFalse((config.HA_CONFIG_DIR / "custom_components").exists())

    def test_it_passes_on_every_header_a_screen_reads(self):
        # Home Assistant isn't installed here, so read the integration's list from its source.
        import ast
        tree = ast.parse((companion.SOURCE / "__init__.py").read_text())
        kept = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "KEEP_RESPONSE")
        # Every X-EPF- header the device port can send, found in the kinds' source, so one added
        # later can't be forgotten here (X-EPF-Next was: clock alignment never reached a panel
        # fetching through Home Assistant's address).
        import re
        sent = set()
        for path in (companion.SOURCE.parents[1] / "kinds").glob("*.py"):
            sent |= set(re.findall(r"[\"'](X-EPF-[A-Za-z-]+)[\"']", path.read_text()))
        self.assertIn("X-EPF-Sleep", sent)
        answered = {*sent, "ETag", "Retry-After"}
        for header in answered:
            self.assertIn(header.lower(), kept, f"{header} must reach a screen away from home")

    def test_it_never_passes_home_assistant_logins_on(self):
        source = (companion.SOURCE / "__init__.py").read_text()
        for header in ('"authorization"', '"cookie"'):
            self.assertIn(header, source)


class CompanionHass:
    """Home Assistant as the companion sees it: what it loaded at its last start, and its config entries."""
    available = True

    def __init__(self, loaded=None, entries=None, refuse=False):
        self.loaded = loaded          # the manifest version Home Assistant read when it started, None if it hasn't
        self.entries = list(entries or [])
        self.refuse = refuse          # its flow refuses to create the entry
        self.flows = 0

    def restart(self):
        self.loaded = companion.installed_version()
        for e in self.entries:
            e["state"] = "loaded"

    async def ws(self, payload, timeout=10):
        if payload["type"] == "manifest/get":
            if self.loaded is None:
                raise HassError("Integration not found", code="not_found")
            return {"domain": companion.DOMAIN, "version": self.loaded}
        if payload["type"] == "config_entries/get":
            return [dict(e) for e in self.entries]
        raise AssertionError(payload)

    async def rest(self, method, path, json=None, timeout=15):
        if (method, path) == ("POST", "/config/config_entries/flow") and json == {"handler": companion.DOMAIN}:
            self.flows += 1
            if self.loaded is None:
                raise HassError("Invalid handler specified", 404)
            if self.refuse:
                return {"type": "abort", "reason": "unknown"}
            self.entries.append({"domain": companion.DOMAIN, "state": "loaded", "disabled_by": None})
            return {"type": "create_entry"}
        raise AssertionError(f"unexpected call {method} {path}")


class TestCompanionState(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._dir, self._version = config.HA_CONFIG_DIR, config.ADDON_VERSION
        config.HA_CONFIG_DIR = support.temp_dir()
        config.ADDON_VERSION = "0.13.1"

    def tearDown(self):
        config.HA_CONFIG_DIR, config.ADDON_VERSION = self._dir, self._version

    async def test_not_installed(self):
        hass = CompanionHass()
        self.assertEqual((await companion.ensure(hass))["state"], companion.ABSENT)
        self.assertEqual(hass.flows, 0)

    async def test_installed_but_not_loaded_needs_a_restart_and_nothing_is_tried(self):
        companion.install("http://x:8099")
        hass = CompanionHass()
        self.assertEqual((await companion.ensure(hass))["state"], companion.RESTART)
        self.assertEqual(hass.flows, 0, "Home Assistant doesn't know the integration yet")

    async def test_after_the_restart_the_add_on_creates_the_entry_itself(self):
        # The user's 0.13.0: loaded after a restart, but nobody created its entry, so /api/epaper was a 404.
        companion.install("http://x:8099")
        hass = CompanionHass()
        hass.restart()
        self.assertEqual((await companion.state(hass))["state"], companion.SET_UP, "loaded, entry missing")
        self.assertEqual((await companion.ensure(hass))["state"], companion.RUNNING)
        self.assertEqual(hass.flows, 1)
        self.assertEqual((await companion.ensure(hass))["state"], companion.RUNNING)
        self.assertEqual(hass.flows, 1, "one entry, made once")

    async def test_the_check_loop_does_it_without_the_editor(self):
        companion.install("http://x:8099")
        hass = CompanionHass()
        hass.restart()
        sleeps = []

        async def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await companion.keep_set_up(hass, sleep=sleep)
        self.assertEqual(hass.flows, 1)
        self.assertEqual((await companion.state(hass))["state"], companion.RUNNING)

    async def test_a_refusal_is_reported(self):
        companion.install("http://x:8099")
        hass = CompanionHass(refuse=True)
        hass.restart()
        s = await companion.ensure(hass)
        self.assertEqual(s["state"], companion.SET_UP)
        self.assertEqual(s["problem"], "unknown")

    async def test_an_entry_that_is_off_or_failed_is_not_running(self):
        companion.install("http://x:8099")
        hass = CompanionHass(entries=[{"domain": companion.DOMAIN, "state": "not_loaded", "disabled_by": "user"}])
        hass.loaded = companion.installed_version()
        s = await companion.ensure(hass)
        self.assertEqual((s["state"], s["disabled"]), (companion.STOPPED, True))
        hass.entries = [{"domain": companion.DOMAIN, "state": "setup_error", "disabled_by": None}]
        s = await companion.ensure(hass)
        self.assertEqual((s["state"], s["disabled"]), (companion.STOPPED, False))

    async def test_home_assistant_not_answering_is_unknown(self):
        companion.install("http://x:8099")

        class Down(CompanionHass):
            async def ws(self, payload, timeout=10):
                raise HassError("Cannot connect to host")
        self.assertEqual((await companion.ensure(Down()))["state"], companion.UNKNOWN)

    async def test_an_update_needs_a_restart_until_home_assistant_runs_the_new_copy(self):
        companion.install("http://x:8099")
        hass = CompanionHass()
        hass.restart()
        await companion.ensure(hass)
        config.ADDON_VERSION = "0.13.2"
        self.assertTrue(companion.refresh("http://x:8099"))
        s = await companion.ensure(hass)
        self.assertEqual((s["state"], s["loaded_version"], s["version"]), (companion.RESTART, "0.13.1", "0.13.2"))
        hass.restart()
        s = await companion.ensure(hass)
        self.assertEqual((s["state"], s["loaded_version"]), (companion.RUNNING, "0.13.2"),
                         "the add-on itself didn't restart, and the Restart row still goes")

    async def test_the_editor_sees_each_state(self):
        import runtime
        import web as web_module
        companion.install("http://x:8099")
        hass = CompanionHass()
        with mock.patch.object(runtime, "HASS", hass), mock.patch.object(web_module, "HA_TOKEN", "t"), \
                mock.patch.object(reach, "addon_hostname", mock.AsyncMock(return_value="x")), \
                mock.patch.object(reach, "ha_address", mock.AsyncMock(return_value="https://ha.example.com")):
            c = (await web_module._reach_status())["companion"]
            self.assertEqual((c["state"], c["restart_needed"], c["running"]), (companion.RESTART, True, False))
            hass.restart()
            c = (await web_module._reach_status())["companion"]
            self.assertEqual((c["state"], c["restart_needed"], c["running"]), (companion.RUNNING, False, True))
            config.ADDON_VERSION = "0.13.2"
            companion.refresh("http://x:8099")
            c = (await web_module._reach_status())["companion"]
            self.assertEqual((c["state"], c["restart_needed"]), (companion.RESTART, True))
            hass.restart()
            c = (await web_module._reach_status())["companion"]
            self.assertEqual((c["state"], c["restart_needed"]), (companion.RUNNING, False))
