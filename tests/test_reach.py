"""Reaching home: who may come in which way, keys away from home, wrong keys, the companion integration."""
import json
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import support
import companion
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

    def test_it_never_passes_home_assistant_logins_on(self):
        source = (companion.SOURCE / "__init__.py").read_text()
        for header in ('"authorization"', '"cookie"'):
            self.assertIn(header, source)
