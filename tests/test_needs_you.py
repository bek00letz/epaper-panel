"""What needs you in Home Assistant: notifications, updates and Repairs, read and counted."""
import json
import unittest
import unittest.mock

import support  # noqa: F401

import entities
import health
import runtime
from sources import needs_you

# Rows as UPDATES_TEMPLATE gives them, shaped like a real Home Assistant (22 Oct): Home Assistant's own
# from the Supervisor, an add-on, HACS (no title), device firmware (one with no device), a NAS's software.
ROWS = [
    {"entity": "update.kitchen_light_firmware", "name": "Kitchen light Firmware", "title": None, "device": "Kitchen light",
     "version": "1.2.1", "class": "firmware", "busy": False, "from": ""},
    {"entity": "update.mosquitto_broker_update", "name": "Mosquitto broker Update", "title": "Mosquitto broker",
     "device": "Mosquitto broker", "version": "7.1.3", "class": None, "busy": False, "from": "hassio"},
    {"entity": "update.home_assistant_supervisor_update", "name": "Home Assistant Supervisor Update",
     "title": "Home Assistant Supervisor", "device": "Home Assistant Supervisor", "version": "2026.10.4", "busy": False,
     "from": "hassio"},
    {"entity": "update.home_assistant_core_update", "name": "Home Assistant Core Update", "title": "Home Assistant Core",
     "device": "Home Assistant Core", "version": "2026.10.2", "class": None, "busy": 40, "from": "hassio"},
    {"entity": "update.mushroom_update", "name": "Mushroom Update", "title": None, "device": "Mushroom",
     "version": "v5.3.0", "busy": False, "from": "hacs"},
    {"entity": "update.update_firmware", "name": "Update firmware", "title": None, "device": None,
     "version": "9.5.60", "class": "firmware", "busy": False, "from": ""},
    {"entity": "update.synology_dsm_update", "name": "Synology DSM", "title": "Synology DSM", "device": "NAS",
     "version": "DSM 7.3.2", "busy": None, "from": ""},
]


class TestReading(unittest.TestCase):
    def test_updates_are_grouped_as_home_assistant_shows_them(self):
        got = needs_you.updates_from(ROWS)
        self.assertEqual([(u["group"], u["name"]) for u in got], [
            ("home_assistant", "Home Assistant Core"), ("home_assistant", "Home Assistant Supervisor"),
            ("addons", "Mosquitto broker"), ("integrations", "Mushroom"),
            ("devices", "Kitchen light"), ("devices", "NAS"), ("devices", "Update firmware")])
        self.assertTrue(got[0]["installing"], "in_progress can be a percentage")
        self.assertFalse(got[1]["installing"])
        self.assertEqual(needs_you.by_group(got), {"home_assistant": 2, "addons": 1, "integrations": 1, "devices": 3})
        self.assertEqual(needs_you.short_name(got[0]), "Core")
        self.assertEqual(needs_you.short_name(got[2]), "Mosquitto broker")

    def test_an_add_on_called_home_assistant_something_is_an_add_on(self):
        row = {"entity": "update.gdrive", "title": "Home Assistant Google Drive Backup", "from": "hassio"}
        self.assertEqual(needs_you.updates_from([row])[0]["group"], "addons")

    def test_notifications_are_words_newest_first(self):
        got = needs_you.notifications_from([
            {"notification_id": "a", "title": "Old", "message": "x", "created_at": "2026-10-20T08:00:00+00:00"},
            {"notification_id": "b", "title": "**Backup** failed",
             "message": "## Oops\nSee [the logs](/config/logs) and `retry`.<br>Thanks", "created_at": "2026-10-22T08:00:00+00:00"},
            {"notification_id": "c", "title": None, "message": "Only a message", "created_at": "2026-10-21T08:00:00+00:00"},
            {"notification_id": "d", "title": "", "message": "", "created_at": "2026-10-21T09:00:00+00:00"},
            "junk"])
        self.assertEqual([n["id"] for n in got], ["b", "c", "a"])
        self.assertEqual(got[0]["title"], "Backup failed")
        self.assertEqual(got[0]["message"], "Oops See the logs and retry.Thanks")
        self.assertEqual((got[1]["title"], got[1]["message"]), ("Only a message", ""))

    def test_ignored_repairs_dont_count(self):
        self.assertEqual(needs_you.repairs_from({"issues": [{"ignored": False}, {"ignored": True}, {}]}), 2)
        self.assertEqual(needs_you.repairs_from(None), 0)

    def test_the_counts_pages_use(self):
        spec = {"pages": {
            "a": {"elements": [{"type": "notifications"}, {"type": "badge", "counts": "repairs"}]},
            "b": {"elements": [{"type": "badge"}]},
            "c": {"tier": "alert", "show_if": "{{ states('sensor.epaper_notifications') | int > 0 }}", "elements": []}}}
        self.assertEqual(needs_you.counts_in(spec), {"notifications", "repairs", "updates"})
        self.assertEqual(needs_you.counts_in({"pages": {"a": {"elements": [{"type": "badge", "counts": "all"}]}}}),
                         {"notifications", "repairs", "updates"})
        self.assertEqual(needs_you.counts_in({"pages": {"a": {"elements": [{"type": "text"}]}}}), set())
        self.assertEqual(needs_you.badge_counts({"counts": "nonsense"}), "updates")


class FakeHass:
    def __init__(self, fail=None):
        self.asked, self.fail = [], fail or set()

    async def ws(self, payload, timeout=10):
        self.asked.append(payload["type"])
        if payload["type"] in self.fail:
            raise RuntimeError("unauthorized")
        if payload["type"] == "persistent_notification/get":
            return [{"notification_id": "n", "title": "Hello", "message": "", "created_at": "2026-10-22T08:00:00+00:00"}]
        if payload["type"] == "repairs/list_issues":
            return {"issues": [{"ignored": False}]}
        raise AssertionError(payload)


class TestFetching(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old = (needs_you.HA_TOKEN, runtime.HASS)
        needs_you.HA_TOKEN, runtime.HASS = "t", FakeHass()
        health.reset()
        runtime.LIVE._entries.clear()

    async def asyncTearDown(self):
        needs_you.HA_TOKEN, runtime.HASS = self.old
        health.reset()
        runtime.LIVE._entries.clear()

    def test_each_is_read_in_the_background(self):
        self.assertEqual(needs_you.fetch_notifications.interval, 60)
        self.assertEqual(needs_you.fetch_updates.interval, 120)
        self.assertEqual(needs_you.fetch_repairs.interval, 300)

    async def test_notifications_and_repairs_over_the_websocket(self):
        got = await needs_you.fetch_notifications.direct(None)
        self.assertEqual([n["title"] for n in got], ["Hello"])
        self.assertEqual(await needs_you.fetch_repairs.direct(None), 1)
        self.assertEqual(runtime.HASS.asked, ["persistent_notification/get", "repairs/list_issues"])
        self.assertEqual({s["name"] for s in health.status() if s["ok_at"]}, {needs_you.NOTIFICATIONS, needs_you.REPAIRS})

    async def test_updates_in_one_template(self):
        asked = []

        async def template(session, tpl):
            asked.append(tpl)
            return json.dumps(ROWS)
        with unittest.mock.patch.object(needs_you, "ha_template", template):
            got = await needs_you.fetch_updates.direct(None)
        self.assertEqual(len(got), len(ROWS))
        self.assertEqual(len(asked), 1)
        self.assertIn("integration_entities('hassio')", asked[0])
        self.assertIn("selectattr('state', 'eq', 'on')", asked[0], "a skipped version is off, so it isn't counted")

    async def test_a_failure_is_visible_and_keeps_the_last_reading(self):
        runtime.HASS = FakeHass(fail={"repairs/list_issues"})
        with self.assertRaises(RuntimeError):
            await needs_you.fetch_repairs.direct(None)
        with unittest.mock.patch.object(needs_you, "ha_template", unittest.mock.AsyncMock(return_value=None)):
            with self.assertRaises(ValueError):
                await needs_you.fetch_updates.direct(None)
        failing = {s["name"]: s["error"] for s in health.status() if s["error"]}
        self.assertEqual(set(failing), {needs_you.REPAIRS, needs_you.UPDATES})
        self.assertNotIn("Bearer", failing[needs_you.REPAIRS])

    async def test_offline_its_the_examples(self):
        needs_you.HA_TOKEN = ""
        self.assertEqual(len(await needs_you.fetch_notifications.direct(None)), 3)
        self.assertEqual({u["group"] for u in await needs_you.fetch_updates.direct(None)},
                         {g for g, _ in needs_you.GROUPS})
        self.assertEqual(runtime.HASS.asked, [])

    async def test_all_adds_up_what_has_been_read(self):
        async def ups(session):
            return [{}, {}]

        async def notes(session):
            return [{}]

        async def none(session):
            return None
        with unittest.mock.patch.object(needs_you, "fetch_updates", ups), \
             unittest.mock.patch.object(needs_you, "fetch_notifications", notes), \
             unittest.mock.patch.object(needs_you, "fetch_repairs", none):
            got = await needs_you.counts(None)
        self.assertEqual(got, {"updates": 2, "notifications": 1, "repairs": None, "all": 3})


class TestSensors(unittest.IsolatedAsyncioTestCase):
    async def test_counts_for_pages_and_alerts_and_only_counts(self):
        published = {}

        async def publish(session, eid, state, attrs=None, **kw):
            published[eid] = (state, attrs)

        async def ups(session):
            return needs_you.updates_from(ROWS)

        async def notes(session):
            return [{"title": "Private words", "message": "more"}]
        spec = {"pages": {"a": {"elements": [{"type": "notifications"}, {"type": "updates"}]}}}
        with unittest.mock.patch.object(entities, "publish_entity", publish), \
             unittest.mock.patch.object(needs_you, "fetch_updates", ups), \
             unittest.mock.patch.object(needs_you, "fetch_notifications", notes):
            wanted = await entities.publish_needs_you(None, spec)
        self.assertEqual(wanted, {"sensor.epaper_notifications", "sensor.epaper_updates"})
        self.assertEqual(published["sensor.epaper_notifications"][0], 1)
        self.assertNotIn("Private words", json.dumps(published), "the words stay on the page")
        self.assertEqual(published["sensor.epaper_updates"][0], 7)
        self.assertEqual(published["sensor.epaper_updates"][1]["devices"], 3)


if __name__ == "__main__":
    unittest.main()
