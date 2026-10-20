"""PanelLink, the MQTT entity publisher, widget linger and local values, against fakes."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon" / "app"))

import mqtt_bridge  # noqa: E402
import panel_link  # noqa: E402
from hass import HassError  # noqa: E402
from render import binding  # noqa: E402
from render.linger import Linger  # noqa: E402

PANEL_SERVICES = {"crowpanel_epaper_refresh_now": {}, "crowpanel_epaper_page_step": {},
                  "crowpanel_epaper_show_page": {}, "other_device_restart": {}}

PANEL_REGISTRY = [
    {"entity_id": "number.living_room_e_paper_panel_refresh_interval", "platform": "esphome",
     "device_id": "dev1", "unique_id": "44:1B:F6:D1:45:04/0/number/Refresh interval"},
    {"entity_id": "sensor.e_paper_panel_panel_ip", "platform": "esphome",
     "device_id": "dev1", "unique_id": "44:1B:F6:D1:45:04/0/text_sensor/Panel IP"},
    {"entity_id": "sensor.e_paper_panel_panel_wi_fi", "platform": "esphome",
     "device_id": "dev1", "unique_id": "44:1B:F6:D1:45:04/0/sensor/Panel Wi-Fi"},
]


class FakeHass:
    available = True

    def __init__(self, services=None, registry=None):
        self.services = dict(PANEL_SERVICES if services is None else services)
        self.registry = list(PANEL_REGISTRY if registry is None else registry)
        self.states = {}
        self.calls = []
        self.fail_actions = 0
        self.renames = []

    async def rest(self, method, path, json=None, timeout=15):
        self.calls.append((method, path, json))
        if method == "GET" and path == "/services":
            return [{"domain": "esphome", "services": self.services}]
        if method == "POST" and path.startswith("/services/esphome/"):
            if self.fail_actions > 0:
                self.fail_actions -= 1
                raise HassError("Failed to execute the action: Not connected to crowpanel-epaper", 500)
            return []
        if method == "POST" and path == "/services/number/set_value":
            return []
        if method == "GET" and path.startswith("/states/"):
            eid = path[len("/states/"):]
            if eid not in self.states:
                raise HassError("Entity not found", 404)
            return self.states[eid]
        if method == "DELETE" and path.startswith("/states/"):
            eid = path[len("/states/"):]
            if self.states.pop(eid, None) is None:
                raise HassError("Entity not found", 404)
            return None
        raise AssertionError(f"unexpected call {method} {path}")

    async def ws(self, payload, timeout=10):
        if payload["type"] == "config/entity_registry/list":
            return list(self.registry)
        if payload["type"] == "config/entity_registry/update":
            if payload["new_entity_id"] in self.states:
                raise HassError("Entity ID is already in use")
            for e in self.registry:
                if e["entity_id"] == payload["entity_id"]:
                    e["entity_id"] = payload["new_entity_id"]
            self.renames.append((payload["entity_id"], payload["new_entity_id"]))
            return {}
        raise AssertionError(payload)


class FakeTransport:
    connected = True

    def __init__(self):
        self.messages = {}
        self.log = []

    async def publish(self, topic, payload, retain=True):
        self.messages[topic] = payload
        self.log.append((topic, payload))
        return True

    async def subscribe(self, topic):
        pass


def run(coro):
    return asyncio.run(coro)


class TestPanelLink(unittest.TestCase):
    def test_finds_panel_and_entities_without_guessing_names(self):
        link = panel_link.PanelLink(FakeHass(), lambda: "")
        self.assertTrue(run(link.discover()))
        self.assertEqual(link.node, "crowpanel_epaper")
        self.assertEqual(link.entities["refresh"], "number.living_room_e_paper_panel_refresh_interval")
        self.assertEqual(link.entities["ip"], "sensor.e_paper_panel_panel_ip")

    def test_older_esphome_unique_id_format(self):
        self.assertTrue(panel_link.unique_id_is("441bf6d14504-number-refresh_interval", "number", "Refresh interval"))
        self.assertFalse(panel_link.unique_id_is("441bf6d14504-number-volume", "number", "Refresh interval"))

    def test_two_panels_without_a_choice_is_reported_not_guessed(self):
        services = dict(PANEL_SERVICES)
        services.update({"kitchen_panel_refresh_now": {}, "kitchen_panel_page_step": {},
                         "kitchen_panel_show_page": {}})
        link = panel_link.PanelLink(FakeHass(services=services), lambda: "")
        self.assertFalse(run(link.discover()))
        self.assertIn("found 2 panels", link.problem)
        link = panel_link.PanelLink(FakeHass(services=services), lambda: "kitchen_panel")
        self.assertTrue(run(link.discover()))
        self.assertEqual(link.node, "kitchen_panel")

    def test_refresh_stays_pending_until_delivered(self):
        hass = FakeHass()
        hass.fail_actions = 2
        link = panel_link.PanelLink(hass, lambda: "")

        async def scenario():
            link.request_refresh("quiet hours ended")
            self.assertFalse(await link.deliver())
            self.assertEqual(link.pending, "quiet hours ended")
            self.assertIn("offline", link.last_error)
            self.assertFalse(await link.deliver())         # backoff: not even attempted yet
            link._next_attempt = 0
            self.assertFalse(await link.deliver())         # second failure
            link._next_attempt = 0
            self.assertTrue(await link.deliver())
            self.assertIsNone(link.pending)

        run(scenario())
        attempts = [c for c in hass.calls if c[1] == "/services/esphome/crowpanel_epaper_refresh_now"]
        self.assertEqual(len(attempts), 3)

    def test_requests_coalesce(self):
        hass = FakeHass()
        link = panel_link.PanelLink(hass, lambda: "")
        link.request_refresh("pages changed")
        link.request_refresh("alert dryer")
        run(link.deliver())
        attempts = [c for c in hass.calls if c[1].endswith("_refresh_now")]
        self.assertEqual(len(attempts), 1)

    def test_set_refresh_interval_targets_the_real_entity(self):
        hass = FakeHass()
        link = panel_link.PanelLink(hass, lambda: "")
        ok, err = run(link.set_refresh_interval(3))
        self.assertTrue(ok, err)
        self.assertIn(("POST", "/services/number/set_value",
                       {"entity_id": "number.living_room_e_paper_panel_refresh_interval", "value": 3}), hass.calls)


class TestEntityPublisher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1000.0]

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, hass):
        t = FakeTransport()
        pub = mqtt_bridge.EntityPublisher(t, hass, Path(self.tmp.name), "0.9.0", clock=lambda: self.now[0])
        return pub, t

    def test_dedupes_0_8_entities_and_restores_their_ids(self):
        hass = FakeHass(registry=[
            {"entity_id": "sensor.epaper_jelly_2", "platform": "mqtt", "unique_id": "epaper_studio_epaper_jelly"},
            {"entity_id": "sensor.my_renamed_one", "platform": "mqtt", "unique_id": "epaper_studio_epaper_solar_month"},
        ])
        hass.states["sensor.epaper_jelly"] = {"state": "Brothers"}            # written directly by 0.8.x
        pub, t = self.make(hass)
        pub.set("sensor.epaper_jelly", "Brothers", {"friendly_name": "E-Paper · Next to watch"})
        run(pub._on_connect())
        self.assertEqual(hass.renames, [("sensor.epaper_jelly_2", "sensor.epaper_jelly")])
        self.assertNotIn("sensor.epaper_jelly", hass.states)
        cfg = json.loads(t.messages["homeassistant/sensor/epaper_panel/epaper_jelly/config"])
        self.assertEqual(cfg["unique_id"], "epaper_studio_epaper_jelly")
        self.assertEqual(cfg["name"], "Next to watch")
        self.assertEqual(cfg["availability_topic"], "epaper_panel/status")
        self.assertEqual(t.messages["epaper_panel/epaper_jelly/state"], "Brothers")
        self.assertEqual(t.messages["epaper_panel/status"], "online")
        # The old, non-standard retained state topics are cleared.
        self.assertEqual(t.messages["homeassistant/epaper_panel/epaper_jelly/state"], "")
        # Runs once.
        hass.renames.clear()
        run(pub._on_connect())
        self.assertEqual(hass.renames, [])

    def test_only_changes_are_published(self):
        pub, t = self.make(FakeHass(registry=[]))
        run(pub._on_connect())
        pub.set("sensor.epaper_solar_month", "335.8", {"unit_of_measurement": "kWh"})
        run(pub.sync())
        n = len(t.log)
        pub.set("sensor.epaper_solar_month", "335.8", {"unit_of_measurement": "kWh"})
        run(pub.sync())
        self.assertEqual(len(t.log), n)
        pub.set("sensor.epaper_solar_month", "336.0", {"unit_of_measurement": "kWh"})
        run(pub.sync())
        self.assertEqual(t.messages["epaper_panel/epaper_solar_month/state"], "336.0")

    def test_withdraws_retired_and_stale_but_never_right_after_start(self):
        pub, t = self.make(FakeHass(registry=[
            {"entity_id": "sensor.epaper_category_count", "platform": "mqtt",
             "unique_id": "epaper_studio_epaper_category_count"}]))
        pub.retire("sensor.epaper_category_count")
        pub.retire("sensor.epaper_category_names")                   # already gone from HA
        run(pub._on_connect())
        self.assertNotIn("homeassistant/sensor/epaper_panel/epaper_category_names/config", t.messages)
        pub.set("sensor.epaper_flights_overhead", "1", {})
        run(pub.sync())
        self.now[0] += 120
        run(pub.sync())
        self.assertEqual(t.messages["homeassistant/sensor/epaper_panel/epaper_category_count/config"], "")
        self.assertIn("epaper_flights_overhead", pub.desired)            # not stale yet
        self.now[0] += mqtt_bridge.STALE_AFTER + 1
        run(pub.sync())
        self.assertEqual(t.messages["homeassistant/sensor/epaper_panel/epaper_flights_overhead/config"], "")

    def test_button_press_calls_back(self):
        pressed = []

        async def on_button(suffix=""):
            pressed.append(suffix)

        pub, t = self.make(FakeHass(registry=[]))
        pub.on_button = on_button
        run(pub._on_connect())
        self.assertIn("homeassistant/button/epaper_panel/refresh/config", t.messages)
        run(pub._on_message(mqtt_bridge.BUTTON_COMMAND, b"PRESS"))
        self.assertEqual(pressed, [""])

    def test_each_screen_has_its_own_button_and_loses_it_when_removed(self):
        pressed, screens = [], [("", "Living room"), ("_kitchen", "Kitchen")]

        async def on_button(suffix=""):
            pressed.append(suffix)

        pub, t = self.make(FakeHass(registry=[]))
        pub.on_button, pub.buttons = on_button, lambda: list(screens)
        run(pub._on_connect())
        cfg = json.loads(t.messages["homeassistant/button/epaper_panel/refresh_kitchen/config"])
        self.assertEqual((cfg["name"], cfg["unique_id"]), ("Refresh Kitchen", "epaper_panel_refresh_button_kitchen"))
        run(pub._on_message(cfg["command_topic"], b"PRESS"))
        self.assertEqual(pressed, ["_kitchen"])
        screens.pop()
        run(pub.sync())
        self.assertEqual(t.messages["homeassistant/button/epaper_panel/refresh_kitchen/config"], "")

    def test_first_render_waits_until_entities_are_back_online(self):
        async def scenario():
            pub, t = self.make(FakeHass(registry=[]))
            waiter = asyncio.create_task(pub.wait_ready(5))
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            await pub._on_connect()
            self.assertTrue(await waiter)
            self.assertFalse(await self.make(FakeHass(registry=[]))[0].wait_ready(0.01))  # gives up, renders anyway

        run(scenario())

    def test_without_a_broker_it_says_so_plainly(self):
        pub = mqtt_bridge.EntityPublisher(None, FakeHass(), Path(self.tmp.name), "0.9.0")
        self.assertEqual(pub.status()["mode"], "off")
        self.assertIn("panel works either way", pub.status()["problem"])
        pub.set("sensor.epaper_x", "1", {})
        run(pub.sync())                                                  # no-op, no crash


class TestLingerAndLocalValues(unittest.TestCase):
    def test_flickering_widget_keeps_its_page(self):
        lg = Linger(300)
        self.assertTrue(lg.keep("flight_tracker", True, now=0))
        self.assertTrue(lg.keep("flight_tracker", False, now=60))       # plane left the radius
        self.assertTrue(lg.keep("flight_tracker", False, now=299))
        self.assertFalse(lg.keep("flight_tracker", False, now=301))
        self.assertFalse(lg.keep("never_shown", False, now=10))

    def test_bindings_to_own_sensors_resolve_locally(self):
        reg = {"sensor.epaper_jelly": {"state": "Brothers", "attributes": {"detail": "S1 · E2", "items": [1]}}}
        self.assertEqual(binding.local_value({"entity": "sensor.epaper_jelly"}, reg), "Brothers")
        self.assertEqual(binding.local_value({"entity": "sensor.epaper_jelly", "show": "attribute",
                                              "attribute": "detail"}, reg), "S1 · E2")
        self.assertEqual(binding.local_value({"entity": "sensor.epaper_jelly", "replace": {"Brothers": "Bros"}}, reg),
                         "Bros")
        # Not ours, a raw template, or a show that needs Home Assistant: fall back.
        self.assertIsNone(binding.local_value({"entity": "sensor.outdoor_temp"}, reg))
        self.assertIsNone(binding.local_value({"entity": "sensor.epaper_jelly", "value": "{{ 1 }}"}, reg))
        self.assertIsNone(binding.local_value({"entity": "sensor.epaper_jelly", "show": "last_changed"}, reg))


if __name__ == "__main__":
    unittest.main()
