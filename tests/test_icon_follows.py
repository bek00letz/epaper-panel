"""An icon that follows a sensor ("Changes with a sensor" in the inspector): the states it
offers, each with Home Assistant's own icon (render/states.offered, sources/states_seen,
GET /api/entity_states), and the inspector's wiring (web/app/follows.js under node)."""
import asyncio
import unittest
from unittest import mock

import support  # noqa: F401
from render import states
from sources import states_seen
from test_editor_api import EditorClient

CAT = "sensor.pawpaw_location"
NOW = 1_800_000_000.0


class TestWhatAnEntityOffers(unittest.TestCase):
    def test_a_door_has_home_assistants_words_and_icons(self):
        got = states.offered("binary_sensor.front_door", "door", seen=[("off", "")])
        self.assertEqual(got, [{"state": "on", "word": "Open", "icon": "mdi:door-open"},
                               {"state": "off", "word": "Closed", "icon": "mdi:door-closed"}])

    def test_a_template_sensor_its_states_with_the_icon_each_had(self):
        # PawPaw's location: a template sensor whose icon changes with its state, newest first.
        seen = [("Outdoor Cat", "mdi:cat-outline"), ("Outdoor Cat", "mdi:cat-outline"), ("Indoor Cat", "mdi:cat"),
                ("unavailable", ""), ("outdoor cat", "mdi:cat-outline")]
        self.assertEqual(states.offered(CAT, seen=seen), [{"state": "Outdoor Cat", "word": "Outdoor Cat", "icon": "mdi:cat-outline"},
                                                          {"state": "Indoor Cat", "word": "Indoor Cat", "icon": "mdi:cat"}])

    def test_a_select_its_options_first(self):
        got = states.offered("input_select.mode", options=["Home", "Away", "Night"], seen=[("Night", "mdi:list-box")])
        self.assertEqual([g["state"] for g in got], ["Home", "Away", "Night"])
        self.assertEqual({g["icon"] for g in got}, {"mdi:list-box"}, "one icon it always has, for every state")

    def test_an_icon_template_wins_over_the_kinds(self):
        seen = [("on", "mdi:cat"), ("off", "mdi:cat-outline")]
        got = {g["state"]: g["icon"] for g in states.offered("binary_sensor.cat_inside", "occupancy", seen=seen)}
        self.assertEqual(got, {"on": "mdi:cat", "off": "mdi:cat-outline"})

    def test_an_unchanging_icon_doesnt_hide_the_kinds(self):
        got = {g["state"]: g["icon"] for g in states.offered("binary_sensor.flap", "door", seen=[("on", "mdi:cat"), ("off", "mdi:cat")])}
        self.assertEqual(got, {"on": "mdi:door-open", "off": "mdi:door-closed"})

    def test_no_value_is_never_a_state_and_a_long_list_stops(self):
        self.assertEqual(states.offered("sensor.x", seen=[("unknown", ""), ("", ""), (None, "")]), [])
        many = states.offered("sensor.x", seen=[(str(n), "") for n in range(100)])
        self.assertEqual(len(many), states.MOST)


class TestReadingThemFromHomeAssistant(unittest.IsolatedAsyncioTestCase):
    def ha(self, attrs, history):
        async def ha_json(session, path, **kw):
            if path.startswith("/states/"):
                return {"state": "Outdoor Cat", "attributes": attrs}
            self.assertIn("filter_entity_id=sensor.pawpaw_location", path)
            self.assertNotIn("no_attributes", path, "the icon each state had is an attribute")
            return [history]
        return ha_json

    async def test_the_recorders_last_days(self):
        rows = [{"state": "Indoor Cat", "attributes": {"icon": "mdi:cat"}}, {"state": "Outdoor Cat", "attributes": {"icon": "mdi:cat-outline"}}]
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", self.ha({"icon": "mdi:cat-outline"}, rows)):
            got = await states_seen.fetch(None, CAT, now=NOW)
        self.assertEqual([(g["state"], g["icon"]) for g in got], [("Outdoor Cat", "mdi:cat-outline"), ("Indoor Cat", "mdi:cat")])

    async def test_a_measurement_has_no_states(self):
        ha = mock.AsyncMock(return_value={"state": "21.2", "attributes": {"unit_of_measurement": "°C", "state_class": "measurement"}})
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", ha):
            self.assertEqual(await states_seen.fetch(None, "sensor.indoor_temperature"), [])
        self.assertEqual(ha.await_count, 1, "its history isn't read")

    async def test_no_recorder_still_offers_the_rest(self):
        async def ha_json(session, path, **kw):
            if path.startswith("/states/"):
                return {"state": "off", "attributes": {"device_class": "door"}}
            raise ConnectionError("no recorder")
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", ha_json):
            got = await states_seen.fetch(None, "binary_sensor.front_door")
        self.assertEqual([g["state"] for g in got], ["on", "off"])


class TestTheRoute(EditorClient):
    async def test_states_of_an_entity(self):
        got = await (await self.ed.get("/api/entity_states?entity=binary_sensor.front_door")).json()
        self.assertEqual([s["word"] for s in got["states"]], ["Open", "Closed"])
        got = await (await self.ed.get("/api/entity_states?entity=sensor.cat_location")).json()
        self.assertEqual([s["state"] for s in got["states"]], ["Outdoor Cat"])

    async def test_not_an_entity(self):
        r = await self.ed.get("/api/entity_states?entity=nope")
        self.assertEqual(r.status, 400)
        self.assertIn("entity ID", (await r.json())["error"])

    async def test_home_assistant_not_answering(self):
        with mock.patch.object(states_seen, "fetch", mock.AsyncMock(side_effect=asyncio.TimeoutError())):
            r = await self.ed.get("/api/entity_states?entity=sensor.cat_location")
        self.assertEqual(r.status, 502)
        self.assertIn("didn't say", (await r.json())["error"])


if __name__ == "__main__":
    unittest.main()
