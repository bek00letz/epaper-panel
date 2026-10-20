"""Alerts, quiet hours, saving layouts and saving Panel setup."""
import json
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import make_mocked_request

import support
import config
import devices
import frames
import layouts_store
import runtime
import web


def fixed_now(hour, minute=0):
    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 10, 19, hour, minute, tzinfo=tz)
    return FakeDatetime


class TestAlerts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = runtime.new_alert()
        self.spec = {"pages": {"dryer_done": {"tier": "alert", "show_if": "{{ x }}", "hold_minutes": 10}}}

    async def check(self, truthy, at):
        with mock.patch.object(frames, "resolve_templates",
                               mock.AsyncMock(return_value={"dryer_done": "true" if truthy else "false"})), \
             mock.patch.object(frames.time, "time", return_value=at):
            return await frames.check_alerts(None, self.spec, self.state)

    async def test_fires_once_holds_then_hands_back(self):
        self.assertEqual(await self.check(True, 1000), "dryer_done")
        self.assertEqual(await self.check(True, 1000 + 300), "dryer_done", "held while true")
        self.assertIsNone(await self.check(True, 1000 + 601), "released after hold_minutes")
        self.assertIsNone(await self.check(True, 1000 + 900), "still true: doesn't fire again")
        self.assertIsNone(await self.check(False, 1000 + 960), "goes false: re-armed")
        self.assertEqual(await self.check(True, 1000 + 1000), "dryer_done", "fires again next time")

    async def test_released_as_soon_as_it_goes_false(self):
        await self.check(True, 1000)
        self.assertIsNone(await self.check(False, 1060))


class TestQuietHours(unittest.IsolatedAsyncioTestCase):
    async def evaluate(self, qh, hour, minute=0, presence_state=None):
        ha = mock.AsyncMock(return_value={"state": presence_state})
        with mock.patch.object(frames, "datetime", fixed_now(hour, minute)), \
             mock.patch.object(frames, "publish_entity", mock.AsyncMock()), \
             mock.patch.object(frames, "ha_json", ha), \
             mock.patch.object(frames, "HA_TOKEN", "token"):
            return await frames.evaluate_quiet_hours(None, {"quiet_hours": qh})

    async def test_overnight_window(self):
        qh = {"enabled": True, "start": "23:00", "end": "07:00"}
        self.assertTrue((await self.evaluate(qh, 23, 30))[0])
        self.assertTrue((await self.evaluate(qh, 6, 59))[0])
        self.assertFalse((await self.evaluate(qh, 7, 0))[0], "the end minute is awake")
        self.assertFalse((await self.evaluate(qh, 12))[0])

    async def test_daytime_window_and_disabled(self):
        qh = {"enabled": True, "start": "09:00", "end": "17:00"}
        self.assertTrue((await self.evaluate(qh, 10))[0])
        self.assertFalse((await self.evaluate(qh, 18))[0])
        self.assertEqual(await self.evaluate({**qh, "enabled": False}, 10), (False, "disabled"))

    async def test_nobody_home_outside_the_window(self):
        qh = {"enabled": True, "start": "23:00", "end": "07:00", "presence_entity": "person.alex"}
        active, reason = await self.evaluate(qh, 14, presence_state="not_home")
        self.assertTrue(active)
        self.assertTrue(reason.startswith("away"))
        self.assertFalse((await self.evaluate(qh, 14, presence_state="home"))[0])


class TestSavingLayouts(unittest.TestCase):
    def test_bad_input_is_cleaned_not_saved(self):
        clean = layouts_store.sanitize_layouts({
            "pages": {
                "solar": {"tier": "rotate", "elements": [{"type": "text"}, "not an element"]},
                "bad name!": {"elements": []},
                "dryer": {"tier": "alert", "show_if": "{{ 1 }}", "hold_minutes": 99999},
                "flights": {"tier": "nonsense", "elements": [{"entity": "sensor.overhead_aircraft_count"}]},
            },
            "rotation": ["solar", "dryer", "missing", "flights"],
            "orientation": 45, "rotate_seconds": 1,
            "quiet_hours": {"enabled": True, "start": "late", "end": "07:30", "presence_entity": "not an entity"},
        })
        self.assertEqual(sorted(clean["pages"]), ["dryer", "flights", "solar"])
        self.assertEqual(len(clean["pages"]["solar"]["elements"]), 1)
        self.assertEqual(clean["rotation"], ["solar", "flights"], "alerts and unknown pages never rotate")
        self.assertEqual(clean["pages"]["flights"]["tier"], "rotate")
        self.assertEqual(clean["pages"]["dryer"]["hold_minutes"], 1440)
        self.assertEqual(clean["orientation"], 0)
        self.assertNotIn("rotate_seconds", clean, "Rotate every is the screen's own, never sent with pages")
        self.assertEqual(clean["quiet_hours"]["start"], "23:00")
        self.assertEqual(clean["quiet_hours"]["end"], "07:30")
        self.assertEqual(clean["quiet_hours"]["presence_entity"], "")
        self.assertTrue(clean["quiet_hours"]["sleep_screen"])
        self.assertEqual(clean["pages"]["flights"]["elements"][0]["entity"], "sensor.epaper_flights_overhead",
                         "0.8 entity names are migrated")

    def test_pages_must_be_an_object(self):
        with self.assertRaises(ValueError):
            layouts_store.sanitize_layouts({"pages": []})


class TestPanelSetupSave(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.use_test_data_dir()
        self.tmp = tempfile.TemporaryDirectory()
        self._esphome = config.ESPHOME_DIR
        config.ESPHOME_DIR = Path(self.tmp.name)

    async def asyncTearDown(self):
        config.ESPHOME_DIR = self._esphome
        self.tmp.cleanup()

    async def post(self, body):
        req = make_mocked_request("POST", "/api/panel-setup")
        req.json = mock.AsyncMock(return_value=body)
        with mock.patch.object(web, "_detect_panel_connection", mock.AsyncMock(return_value={})):
            return json.loads((await web.api_panel_setup_post(req)).text)

    async def test_untouched_password_never_reaches_the_file_masked(self):
        await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "real-secret"})
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "••••••••"})
        written = (Path(self.tmp.name) / "crowpanel_epaper.yaml").read_text()
        self.assertIn('"real-secret"', written)
        self.assertNotIn("••••", written)
        self.assertNotIn("real-secret", res["yaml"], "the browser gets the masked copy")

    async def test_a_changed_file_keeps_the_previous_one(self):
        await self.post({"device_name": "crowpanel-epaper", "wifi_password": "one-one-one"})
        await self.post({"device_name": "crowpanel-epaper", "wifi_password": "two-two-two"})
        folder = Path(self.tmp.name)
        self.assertIn('"two-two-two"', (folder / "crowpanel_epaper.yaml").read_text())
        self.assertIn('"one-one-one"', (folder / "crowpanel_epaper.yaml.previous").read_text())

    async def test_its_own_timer_starts_at_update_every(self):
        # Always on, it checks every minute on its own timer; the form has no interval of its own.
        res = await self.post({"device_name": "crowpanel-epaper", "refresh_interval": "7min"})
        self.assertIn("initial_value: 1\n", res["yaml"])
        first = devices.primary()["id"]
        self.addCleanup(devices.update, first, update_minutes=None)
        devices.update(first, update_minutes=30)
        res = await self.post({"device_name": "crowpanel-epaper"})
        self.assertIn("initial_value: 30\n", res["yaml"], "sleeping, its own timer doesn't run; it says the same")


if __name__ == "__main__":
    unittest.main()
