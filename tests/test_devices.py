"""Devices in the core: the move in from one panel, the parts of a view, and several screens at once."""
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import config
import devices
import frame_token
import frames
import kinds
import panel_link
import panel_setup
import runtime
import web
from layouts_store import layouts_etag, load_draft, load_layouts, sanitize_layouts, save_layouts
from render import epf

LEGACY_SPEC = {
    "display": "crowpanel_579",
    "orientation": 180,
    "rotate_seconds": 45,
    "quiet_hours": {"enabled": True, "start": "22:30", "end": "06:45", "presence_entity": "",
                    "allow_alerts": False, "sleep_screen": True},
    "custom_presets": [{"id": "custom_1", "name": "Mine", "title": "Mine", "desc": "", "tier": "rotate",
                        "show_if": "", "elements": [{"type": "text", "value": "hi"}]}],
    "location_presets": [{"label": "Work", "lat": 1.5, "lon": 2.5}],
    "rotation": ["solar", "cat"],
    "pages": {"solar": {"tier": "rotate", "elements": [{"type": "text", "value": "sun", "x": 0, "y": 0, "w": 100, "h": 40}]},
              "cat": {"tier": "rotate", "elements": [{"type": "text", "value": "cat", "x": 0, "y": 0, "w": 100, "h": 40}]}},
}
LEGACY_SETUP = {"device_name": "hallway-panel", "display": "crowpanel_579", "ha_host": "ha.local",
                "wifi_ssid": "net", "wifi_password": "secret", "api_encryption_key": "k" * 44,
                "refresh_interval": "10min", "use_secrets": False}


def fresh_data_dir() -> Path:
    config.DATA_DIR = Path(tempfile.mkdtemp())
    runtime.forget_devices_except([])
    runtime.ALERTS.clear()
    return config.DATA_DIR


def fixed_now(hour, minute=0):
    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 10, 20, hour, minute, tzinfo=tz)
    return FakeDatetime


class TestMoveIn(unittest.TestCase):
    def setUp(self):
        self.dir = fresh_data_dir()

    def tearDown(self):
        support.use_test_data_dir()

    def write_legacy(self):
        files = {
            "layouts.json": json.dumps(LEGACY_SPEC, indent=2),
            "panel_setup.json": json.dumps(LEGACY_SETUP),
            "draft.json": json.dumps({"version": 3, "base_etag": "abc", "base": None, "spec": {"pages": {}}}),
            "panel_capacity": "2097152",
        }
        for name, text in files.items():
            (self.dir / name).write_text(text)
        return {name: (self.dir / name).read_bytes() for name in files}

    def test_the_panel_becomes_device_1_and_nothing_changes(self):
        before = self.write_legacy()
        view = load_layouts()
        self.assertEqual(view, LEGACY_SPEC, "the editor sees exactly what layouts.json held")
        self.assertEqual(layouts_etag(view), layouts_etag(LEGACY_SPEC), "so an open editor's version still matches")
        dev = devices.primary()
        self.assertEqual((dev["id"], dev["kind"], dev["design"]), ("1", "crowpanel", "1"))
        self.assertTrue(dev["install_token"], "its key stays the install's frame token")
        self.assertEqual(dev["entity_suffix"], "", "its Home Assistant entities keep their names")
        self.assertEqual(dev["setup"]["device_name"], "hallway-panel")
        self.assertEqual(dev["setup"]["wifi_password"], "secret")
        self.assertNotIn("display", dev["setup"], "the size has one home: the device")
        self.assertEqual(load_draft()["version"], 3, "unsent changes come along")
        self.assertEqual(runtime.panel_capacity("1"), 2097152, "so does what the panel said it holds")
        for name, data in before.items():
            self.assertEqual((self.dir / name).read_bytes(), data, f"{name} is left as it was: the way back")
        self.assertEqual(stat.S_IMODE(os.stat(self.dir / "devices.json").st_mode), 0o600,
                         "devices.json holds keys and the Wi-Fi password")

    def test_it_moves_in_once(self):
        self.write_legacy()
        devices.primary()
        (self.dir / "layouts.json").write_text(json.dumps(dict(LEGACY_SPEC, rotation=["cat"])))
        self.assertEqual(load_layouts()["rotation"], ["solar", "cat"])

    def test_a_new_install_shows_the_shipped_pages_until_it_saves(self):
        shipped = json.loads(config.DEFAULTS_PATH.read_text())
        self.assertEqual(load_layouts(), shipped)
        self.assertFalse((self.dir / "designs" / "1.json").exists(),
                         "an unsaved design follows the shipped pages, as layouts.json did")

    def test_saving_puts_each_part_where_it_belongs(self):
        before = self.write_legacy()
        spec = sanitize_layouts(load_layouts())
        spec["rotation"] = ["cat"]
        spec["quiet_hours"]["enabled"] = False
        save_layouts(spec)
        design = json.loads((self.dir / "designs" / "1.json").read_text())
        self.assertEqual(set(design), {"rotation", "pages"})
        self.assertEqual(design["rotation"], ["cat"])
        self.assertFalse(devices.primary()["quiet_hours"]["enabled"])
        self.assertEqual(devices.primary()["orientation"], 180)
        self.assertEqual(json.loads((self.dir / "library.json").read_text())["location_presets"][0]["label"], "Work")
        self.assertEqual(load_layouts(), spec)
        self.assertEqual((self.dir / "layouts.json").read_bytes(), before["layouts.json"])

    def test_ids_name_files_so_only_digits_are_accepted(self):
        for bad in ("../layouts", "1/../2", "", "a"):
            with self.assertRaises(KeyError):
                devices.get(bad)


class TestSeveralScreens(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fresh_data_dir()
        self._token = config.FRAME_TOKEN
        config.FRAME_TOKEN = ""
        self.first = devices.primary()
        self.kitchen = devices.add("crowpanel", "Kitchen", "crowpanel_420", design=self.first["design"])

    async def asyncTearDown(self):
        config.FRAME_TOKEN = self._token
        support.use_test_data_dir()

    def frames_of(self, dev):
        return runtime.device(dev["id"]).frames

    async def test_each_screen_gets_the_pages_at_its_own_size(self):
        await frames.refresh_frames(None)
        big = epf.decode_epf(self.frames_of(self.first).epf_strip).header
        small = epf.decode_epf(self.frames_of(self.kitchen).epf_strip).header
        self.assertEqual((big.width, big.height), (792, 272))
        self.assertEqual((small.width, small.height), (400, 300))
        self.assertEqual(self.frames_of(self.first).names, self.frames_of(self.kitchen).names,
                         "the same design, so the same pages")

    async def test_a_screen_with_its_own_design_changes_alone(self):
        desk = devices.add("crowpanel", "Desk", "crowpanel_579")
        self.assertNotEqual(desk["design"], self.first["design"])
        spec = sanitize_layouts(load_layouts(desk["id"]))
        spec["rotation"] = spec["rotation"][:1]
        save_layouts(spec, desk["id"])
        await frames.refresh_frames(None)
        self.assertEqual(len([n for n in self.frames_of(desk).names if n != config.SLEEP_PAGE]), 1)
        self.assertGreater(len([n for n in self.frames_of(self.first).names if n != config.SLEEP_PAGE]), 1)

    async def test_quiet_hours_are_per_screen(self):
        spec = sanitize_layouts(load_layouts(self.kitchen["id"]))
        spec["quiet_hours"] = {"enabled": True, "start": "13:00", "end": "15:00"}
        save_layouts(sanitize_layouts(spec), self.kitchen["id"])
        with mock.patch.object(frames, "datetime", fixed_now(14)):
            await frames.refresh_frames(None)
        kitchen_sleep = epf.decode_epf(self.frames_of(self.kitchen).epf_strip).categories[0]
        first_sleep = epf.decode_epf(self.frames_of(self.first).epf_strip).categories[0]
        self.assertTrue(kitchen_sleep.flags & epf.CAT_FLAG_SLEEP_AUTO, "the kitchen sleeps")
        self.assertFalse(first_sleep.flags & epf.CAT_FLAG_SLEEP_AUTO, "the first panel doesn't")
        self.assertIsNone(load_layouts(self.first["id"]).get("quiet_hours"), "the first panel's weren't touched")
        self.assertEqual(runtime.PUBLISHED["sensor.epaper_quiet_hours_kitchen"]["state"], "active")
        self.assertEqual(runtime.PUBLISHED["sensor.epaper_quiet_hours"]["state"], "inactive",
                         "the first panel's entity keeps its name")

    async def test_the_key_says_which_screen_is_asking(self):
        await frames.refresh_frames(None)
        panel, _ = web.make_apps()
        async with TestClient(TestServer(panel)) as lan:
            r = await lan.get("/frames.epf")
            self.assertEqual(epf.decode_epf(await r.read()).header.width, 792,
                             "no key: the first panel, until it has used its token")
            r = await lan.get(f"/frames.epf?token={self.kitchen['key']}")
            self.assertEqual(epf.decode_epf(await r.read()).header.width, 400)
            r = await lan.get("/frames.epf", headers={"Authorization": f"Bearer {self.kitchen['key']}"})
            self.assertEqual(r.status, 200)
            r = await lan.get(f"/frames.epf?token={frame_token.token()}")
            self.assertEqual(epf.decode_epf(await r.read()).header.width, 792)
            self.assertEqual((await lan.get("/frames.epf")).status, 401,
                             "once the first panel uses its token, frames need a key")
            self.assertEqual((await lan.get("/frames.epf?token=nope")).status, 401)
            self.assertEqual((await lan.post("/api/action/refresh")).status, 401)
            r = await lan.get(f"/frame.png?token={self.kitchen['key']}")
            self.assertEqual(r.status, 200)

    async def test_a_new_screens_key_is_its_own(self):
        self.assertNotEqual(self.kitchen["key"], frame_token.token())
        self.assertGreaterEqual(len(self.kitchen["key"]), 32)
        dev, verdict = devices.authenticate(self.kitchen["key"])
        self.assertEqual((dev["id"], verdict), (self.kitchen["id"], "ok"))
        self.assertFalse((config.DATA_DIR / frame_token.SEEN_FILE).exists(),
                         "another screen's key doesn't switch the first panel's protection on")

    async def test_the_editor_names_the_screen(self):
        _, editor = web.make_apps()
        async with TestClient(TestServer(editor)) as ed:
            body = await (await ed.get(f"/api/layouts?device={self.kitchen['id']}")).json()
            self.assertEqual(body["display"], "crowpanel_420")
            body = await (await ed.get("/api/layouts")).json()
            self.assertEqual(body.get("display", "crowpanel_579"), "crowpanel_579", "no screen named: the first")
            for bad in ("99", "../1"):
                self.assertEqual((await ed.get(f"/api/layouts?device={bad}")).status, 404)

    async def test_each_panels_install_file_carries_its_own_key(self):
        setup = panel_setup.load_panel_setup(self.kitchen)
        self.assertEqual(setup["device_name"], "kitchen")
        yaml_text, _ = panel_setup.generate_esphome_yaml(setup, devices.get(self.kitchen["id"]))
        self.assertIn(f"/frames.epf?token={self.kitchen['key']}", yaml_text)
        self.assertNotIn(frame_token.token(), yaml_text)

    async def test_entity_names_stay_put_when_a_screen_is_renamed(self):
        devices.update(self.kitchen["id"], name="Galley")
        self.assertEqual(devices.entity_id("sensor.epaper_panel_pages", devices.get(self.kitchen["id"])),
                         "sensor.epaper_panel_pages_kitchen")
        again = devices.add("crowpanel", "Kitchen", "crowpanel_290", design="1")
        self.assertEqual(again["entity_suffix"], "_kitchen_2", "never two screens with one entity")

    def test_the_only_panel_in_home_assistant_is_ours_only_while_we_drive_one(self):
        link = kinds.of(self.kitchen).link(devices.get(self.kitchen["id"]))
        self.assertFalse(link._sole())
        self.assertFalse(kinds.of(self.first).link(self.first)._sole())


class TestPickingAPanel(unittest.TestCase):
    def test_with_several_screens_an_unnamed_panel_is_not_taken(self):
        from test_panel_link_and_entities import FakeHass, run
        link = panel_link.PanelLink(FakeHass(), lambda: "", sole=lambda: False)
        self.assertFalse(run(link.discover()))
        self.assertIn("found 1 panel (crowpanel_epaper)", link.problem)
        link = panel_link.PanelLink(FakeHass(), lambda: "kitchen", sole=lambda: False)
        self.assertFalse(run(link.discover()))
        self.assertIn("no panel called kitchen", link.problem)
