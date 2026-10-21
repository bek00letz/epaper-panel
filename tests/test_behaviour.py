"""Alerts, quiet hours, saving layouts and saving Panel setup."""
import json
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import mock

from aiohttp import web as web_exc
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


class TestAlertsUntil(unittest.IsolatedAsyncioTestCase):
    """An alert that ends when something happens: Watch battery below 20%,
    until it's charging (it's still below 20% while it charges)."""

    def setUp(self):
        self.state = runtime.new_alert()
        self.page = {"tier": "alert", "show_if": "{{ low }}", "ends": "until",
                     "until_if": "{{ charging }}", "hold_minutes": 120}
        self.spec = {"pages": {"watch_low": self.page}}
        self.asked = {}

    async def check(self, low, charging, at):
        async def resolve(session, templates):
            self.asked = dict(templates)
            out = {"watch_low": "true" if low else "false"}
            if charging is not None:                  # None: Home Assistant couldn't say
                out["watch_low:until"] = "True" if charging else "False"
            return {k: out.get(k, "") for k in templates}
        with mock.patch.object(frames, "resolve_templates", resolve), \
             mock.patch.object(frames.time, "time", return_value=at):
            return await frames.check_alerts(None, self.spec, self.state)

    async def test_holds_until_it_happens_not_for_a_time(self):
        self.assertEqual(await self.check(True, False, 1000), "watch_low")
        self.assertEqual(self.asked, {"watch_low": "{{ low }}", "watch_low:until": "{{ charging }}"})
        self.assertEqual(await self.check(True, False, 1000 + 3600), "watch_low", "an hour on: still held")
        self.assertIsNone(await self.check(True, True, 1000 + 3660), "charging ends it while still low")
        self.assertIsNone(await self.check(True, True, 1000 + 3720), "and it stays away while it charges")

    async def test_comes_back_when_the_end_is_undone(self):
        await self.check(True, False, 1000)
        await self.check(True, True, 1060)
        self.assertEqual(await self.check(True, False, 1120), "watch_low", "unplugged at 15%: back")

    async def test_lets_go_when_the_start_turns_false(self):
        await self.check(True, False, 1000)
        self.assertIsNone(await self.check(False, False, 1060))

    async def test_the_limit_ends_it_and_it_waits_for_a_new_start(self):
        await self.check(True, False, 1000)
        self.assertIsNone(await self.check(True, False, 1000 + 7201), "released at the 2-hour limit")
        self.assertIsNone(await self.check(True, False, 1000 + 7300), "doesn't fire again at once")
        self.assertIsNone(await self.check(False, False, 1000 + 7400))
        self.assertEqual(await self.check(True, False, 1000 + 7500), "watch_low")

    async def test_an_until_it_cant_read_isnt_met(self):
        self.assertEqual(await self.check(True, None, 1000), "watch_low")

    async def test_never_fires_if_it_has_already_happened(self):
        self.assertIsNone(await self.check(True, True, 1000), "already charging when it drops below 20%")

    async def test_without_an_until_it_is_todays_alert(self):
        for page in ({"ends": "until"}, {"until_if": "{{ charging }}"}):
            self.state = runtime.new_alert()
            self.spec = {"pages": {"watch_low": {"tier": "alert", "show_if": "{{ low }}", "hold_minutes": 10, **page}}}
            self.assertEqual(await self.check(True, True, 1000), "watch_low")
            self.assertNotIn("watch_low:until", self.asked)
            self.assertIsNone(await self.check(True, True, 1000 + 601), "released after hold_minutes")


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
        self.assertNotIn("ends", clean["pages"]["dryer"])
        self.assertEqual(clean["orientation"], 0)
        self.assertNotIn("rotate_seconds", clean, "Rotate every is the screen's own, never sent with pages")
        self.assertEqual(clean["quiet_hours"]["start"], "23:00")
        self.assertEqual(clean["quiet_hours"]["end"], "07:30")
        self.assertEqual(clean["quiet_hours"]["presence_entity"], "")
        self.assertTrue(clean["quiet_hours"]["sleep_screen"])
        self.assertEqual(clean["pages"]["flights"]["elements"][0]["entity"], "sensor.epaper_flights_overhead",
                         "0.8 entity names are migrated")

    def test_an_alert_keeps_its_until(self):
        pages = layouts_store.sanitize_layouts({"pages": {
            "low": {"tier": "alert", "show_if": "{{ a }}", "ends": "until", "until_if": " {{ b }} "},
            "timed": {"tier": "alert", "show_if": "{{ a }}", "ends": "nonsense", "until_if": "{{ b }}"},
            "when": {"tier": "when", "show_if": "{{ a }}", "ends": "until", "until_if": "{{ b }}"},
        }})["pages"]
        self.assertEqual(pages["low"], {"tier": "alert", "elements": [], "show_if": "{{ a }}",
                                        "ends": "until", "until_if": "{{ b }}", "hold_minutes": 120})
        self.assertEqual(pages["timed"]["hold_minutes"], 10)
        self.assertNotIn("until_if", pages["timed"])
        self.assertNotIn("ends", pages["when"], "only alerts end")

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

    async def post(self, body, send=True):
        """Save the setup, then Send to ESPHome (what a person does before Install)."""
        req = make_mocked_request("POST", "/api/panel-setup")
        req.json = mock.AsyncMock(return_value=body)
        with mock.patch.object(web, "_detect_panel_connection", mock.AsyncMock(return_value={})):
            res = json.loads((await web.api_panel_setup_post(req)).text)
        if send:
            try:
                res["sent"] = await self.send()
            except web_exc.HTTPConflict as exc:
                res["sent"] = exc.text
        return res

    async def send(self):
        req = make_mocked_request("POST", "/api/panel-setup/esphome")
        return json.loads((await web.api_panel_setup_esphome(req)).text)

    async def test_untouched_password_never_reaches_the_file_masked(self):
        await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "real-secret"})
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "••••••••"})
        written = (Path(self.tmp.name) / "crowpanel_epaper.yaml").read_text()
        self.assertIn('"real-secret"', written)
        self.assertNotIn("••••", written)
        self.assertNotIn("real-secret", res["yaml"], "the browser gets the masked copy")

    async def test_a_changed_file_keeps_the_previous_one(self):
        await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "one-one-one"})
        await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "two-two-two"})
        folder = Path(self.tmp.name)
        self.assertIn('"two-two-two"', (folder / "crowpanel_epaper.yaml").read_text())
        self.assertIn('"one-one-one"', (folder / "crowpanel_epaper.yaml.previous").read_text())

    async def test_no_way_online_is_said_before_install_and_not_written(self):
        folder = Path(self.tmp.name)
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "long-enough"})
        self.assertEqual(res["problems"], [])
        written = (folder / "crowpanel_epaper.yaml").read_text()
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "", "wifi_networks": [], "hotspot": False})
        self.assertEqual(len(res["problems"]), 1)
        self.assertIn("no way online", res["problems"][0])
        self.assertIn("wouldn't install", res["sent"])
        self.assertEqual((folder / "crowpanel_epaper.yaml").read_text(), written, "the last good file stays")
        res = await self.post({"device_name": "crowpanel-epaper", "hotspot": True})
        self.assertEqual(res["problems"], [], "its own Wi-Fi is a way online: set up from a phone")

    async def test_wifi_passwords_esphome_would_refuse(self):
        for password, ok in (("", True), ("12345678", True), ("x" * 63, True), ("ab12" * 16, True),
                             ("short", False), ("x" * 64, False), ("x" * 65, False)):
            res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": password,
                                   "wifi_networks": [], "hotspot": True})
            self.assertEqual(res["problems"] == [], ok, f"{len(password)} characters")
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "long-enough",
                               "wifi_networks": [{"ssid": "Work", "password": "abc"}]})
        self.assertEqual(len(res["problems"]), 1)
        self.assertIn("Work", res["problems"][0], "says which network")

    async def test_its_own_wifi_password_can_be_changed(self):
        folder = Path(self.tmp.name)
        base = {"device_name": "crowpanel-epaper", "wifi_ssid": "home", "wifi_password": "long-enough",
                "wifi_networks": [], "hotspot": True}
        res = await self.post({**base, "hotspot_password": "kitchen-panel"})
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["config"]["hotspot_password"], "kitchen-panel", "shown, for typing on a phone")
        self.assertIn('password: "kitchen-panel"', (folder / "crowpanel_epaper.yaml").read_text())
        for password in ("short", "x" * 64):
            res = await self.post({**base, "hotspot_password": password})
            self.assertEqual(len(res["problems"]), 1, f"{len(password)} characters")
            self.assertIn("its own Wi-Fi", res["problems"][0])
            self.assertIn("wouldn't install", res["sent"], "ESPHome would refuse it")
            self.assertIn('password: "kitchen-panel"', (folder / "crowpanel_epaper.yaml").read_text())
        res = await self.post({**base, "hotspot_password": "x" * 63})
        self.assertEqual(res["problems"], [])
        res = await self.post({**base, "hotspot_password": ""})
        self.assertEqual(res["config"]["hotspot_password"], "x" * 63, "never open: an empty one keeps the old")
        res = await self.post({**base, "hotspot": False, "hotspot_password": "short"})
        self.assertEqual(res["problems"], [], "off, its password doesn't matter")
        await self.post({**base, "hotspot_password": "abcdefghjkmn"})      # the next tests start from a good one

    async def test_saving_alone_leaves_esphome_alone(self):
        folder = Path(self.tmp.name)
        res = await self.post({"device_name": "kitchen", "wifi_ssid": "home", "wifi_password": "long-enough", "wifi_networks": []}, send=False)
        self.assertFalse((folder / "kitchen.yaml").exists())
        self.assertEqual(res["esphome"]["state"], "missing")
        self.assertEqual(res["esphome"]["file"], "esphome/kitchen.yaml")

    async def test_send_to_esphome_says_when_its_copy_is_older(self):
        folder = Path(self.tmp.name)
        res = await self.post({"device_name": "kitchen", "wifi_ssid": "home", "wifi_password": "one-one-one", "wifi_networks": []})
        self.assertEqual(res["sent"]["esphome"]["state"], "same")
        self.assertIn('"one-one-one"', (folder / "kitchen.yaml").read_text())
        res = await self.post({"device_name": "kitchen", "wifi_ssid": "home", "wifi_password": "two-two-two", "wifi_networks": []}, send=False)
        self.assertEqual(res["esphome"]["state"], "differs", "the editor would write something else now")
        req = make_mocked_request("GET", "/api/panel-setup")
        with mock.patch.object(web, "_detect_panel_connection", mock.AsyncMock(return_value={})), \
                mock.patch.object(web, "_detect_external_port", mock.AsyncMock(return_value=8099)):
            got = json.loads((await web.api_panel_setup_get(req)).text)
        self.assertEqual(got["esphome"]["state"], "differs", "said when the pane opens too")
        sent = await self.send()
        self.assertEqual(sent["esphome"]["state"], "same")
        self.assertIn('"one-one-one"', (folder / "kitchen.yaml.previous").read_text())

    async def test_without_an_esphome_folder(self):
        config.ESPHOME_DIR = Path(self.tmp.name) / "nowhere"
        res = await self.post({"device_name": "kitchen", "wifi_ssid": "home", "wifi_password": "long-enough", "wifi_networks": []})
        self.assertEqual(res["esphome"]["state"], "no_folder")
        self.assertIn("no ESPHome folder", res["sent"])

    async def test_no_first_network_but_others(self):
        # ESPHome refuses a blank network name; the first of the others leads instead.
        res = await self.post({"device_name": "crowpanel-epaper", "wifi_ssid": "", "wifi_password": "",
                               "wifi_networks": [{"ssid": "Work", "password": "work-pass"},
                                                 {"ssid": "Cabin", "password": "cabin-pass"}]})
        self.assertEqual(res["problems"], [])
        self.assertNotIn('ssid: ""', res["yaml"])
        self.assertIn('ssid: "Work"', res["yaml"])
        self.assertIn('ssid: "Cabin"', res["yaml"])

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


class TestEsphomeDashboard(unittest.IsolatedAsyncioTestCase):
    """Send to ESPHome opens the ESPHome add-on's page, found by its slug, never assumed."""

    def setUp(self):
        import panel_setup
        self.ps = panel_setup
        panel_setup._dashboard_cache.update(at=0.0, url=None)

    def hass(self, addons=None, fail=False):
        from hass import HassError
        calls = []

        class H:
            async def ws(self, payload, timeout=10):
                calls.append(payload)
                if fail:
                    raise HassError("Unauthorized")
                return {"addons": addons or []}
        return H(), calls

    async def test_finds_the_running_stable_one(self):
        hass, calls = self.hass([{"slug": "a0d7b954_vscode", "state": "started"},
                                 {"slug": "5c53de3b_esphome-beta", "state": "started"},
                                 {"slug": "5c53de3b_esphome", "state": "started"},
                                 {"slug": "1234abcd_not_esphome", "state": "started"}])
        self.assertEqual(await self.ps.esphome_dashboard(hass, clock=lambda: 1000.0), "/hassio/ingress/5c53de3b_esphome")
        self.assertEqual(calls[0], {"type": "supervisor/api", "endpoint": "/addons", "method": "get"})
        await self.ps.esphome_dashboard(hass, clock=lambda: 1100.0)
        self.assertEqual(len(calls), 1, "remembered for a while")

    async def test_a_stopped_one_comes_after_a_running_one(self):
        hass, _ = self.hass([{"slug": "5c53de3b_esphome", "state": "stopped"},
                             {"slug": "5c53de3b_esphome-dev", "state": "started"}])
        self.assertEqual(await self.ps.esphome_dashboard(hass, clock=lambda: 1000.0), "/hassio/ingress/5c53de3b_esphome-dev")

    async def test_none_installed_or_no_answer(self):
        hass, _ = self.hass([{"slug": "core_mosquitto", "state": "started"}])
        self.assertIsNone(await self.ps.esphome_dashboard(hass, clock=lambda: 1000.0))
        self.ps._dashboard_cache.update(at=0.0, url=None)
        hass, _ = self.hass(fail=True)
        self.assertIsNone(await self.ps.esphome_dashboard(hass, clock=lambda: 1000.0))
