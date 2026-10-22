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
    """The counts are the add-on's own values: pages and alerts read them, Home Assistant gets no entity."""

    async def asyncSetUp(self):
        self.old = runtime.PUBLISHER
        self.sent = []
        runtime.PUBLISHER = unittest.mock.Mock(set=lambda *a, **kw: self.sent.append(a))
        for sensor in needs_you.SENSOR.values():
            runtime.PUBLISHED.pop(sensor, None)

    async def asyncTearDown(self):
        runtime.PUBLISHER = self.old
        for sensor in needs_you.SENSOR.values():
            runtime.PUBLISHED.pop(sensor, None)

    async def publish(self, spec, notes):
        async def ups(session):
            return needs_you.updates_from(ROWS)

        async def got_notes(session):
            return notes

        async def reps(session):
            return 2
        with unittest.mock.patch.object(needs_you, "fetch_updates", ups), \
             unittest.mock.patch.object(needs_you, "fetch_notifications", got_notes), \
             unittest.mock.patch.object(needs_you, "fetch_repairs", reps):
            return await entities.publish_needs_you(None, spec)

    async def test_a_fresh_install_makes_no_entities_in_home_assistant(self):
        spec = {"pages": {"a": {"elements": [{"type": "notifications"}, {"type": "updates"}, {"type": "badge", "counts": "all"}]}}}
        kept = await self.publish(spec, [{"title": "Private words", "message": "more"}])
        self.assertEqual(kept, set(), "nothing kept in Home Assistant")
        self.assertEqual(self.sent, [], "nothing sent to the broker")
        own = {k: runtime.PUBLISHED[k] for k in needs_you.SENSOR.values()}
        self.assertEqual({k: v["state"] for k, v in own.items()},
                         {"sensor.epaper_notifications": "1", "sensor.epaper_updates": "7", "sensor.epaper_repairs": "2"})
        self.assertFalse(any(v["register_mqtt"] for v in own.values()))
        self.assertNotIn("Private words", json.dumps(own), "the words stay on the page")
        self.assertEqual(own["sensor.epaper_updates"]["attributes"]["devices"], 3)

    async def test_nothing_used_nothing_kept(self):
        self.assertEqual(await self.publish({"pages": {"a": {"elements": [{"type": "text"}]}}}, []), set())
        self.assertFalse(any(k in runtime.PUBLISHED for k in needs_you.SENSOR.values()))

    async def test_the_page_shows_only_while_there_are_any_without_home_assistant(self):
        import conditions
        cond = "{{ has_value('sensor.epaper_notifications') and states('sensor.epaper_notifications') | float(0) > 0 }}"
        spec = {"pages": {"a": {"tier": "when", "show_if": cond, "elements": [{"type": "notifications"}]}}}
        await self.publish(spec, [{"title": "x"}])
        self.assertEqual(conditions.local(cond, runtime.PUBLISHED), "True")
        await self.publish(spec, [])
        self.assertEqual(conditions.local(cond, runtime.PUBLISHED), "False")
        self.assertEqual(self.sent, [])


# ---------------------------------------------------------------- drawn

from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import examples  # noqa: E402
import widgets  # noqa: E402
from render import clock, clocktime  # noqa: E402
from render import needs_you as drawn  # noqa: E402
from test_widgets import Sizes, ink, render  # noqa: E402

TZ = ZoneInfo("Europe/Bucharest")


class TestNotificationsDrawn(Sizes, unittest.TestCase):
    element = {"type": "notifications", "x": 40, "y": 14, "w": 712, "h": 220}
    value = {"items": examples.notifications(), "tz": None}

    def test_how_long_ago_in_few_letters(self):
        now = datetime(2026, 10, 22, 15, 0, tzinfo=TZ)
        ago = lambda **kw: (now - timedelta(**kw)).isoformat()     # noqa: E731
        self.assertEqual([drawn.age_label(ago(seconds=20), now), drawn.age_label(ago(minutes=12), now),
                          drawn.age_label(ago(hours=2, minutes=50), now), drawn.age_label(ago(hours=20), now),
                          drawn.age_label(ago(days=3), now), drawn.age_label(ago(days=30), now)],
                         ["now", "12 min", "2 h", "Yesterday", "Mon", "22 Sep"])
        self.assertEqual(drawn.age_label("2026-10-22T09:00:00+00:00", now), "3 h", "Home Assistant's UTC, in its own zone")
        self.assertEqual(drawn.age_label("garbage", now), "")

    def test_a_sleeping_device_shows_when_it_came(self):
        now = datetime(2026, 10, 22, 15, 0, tzinfo=TZ)
        clock.use(False)
        self.assertEqual(drawn.age_label((now - timedelta(minutes=12)).isoformat(), now, asleep=True), "14:48")
        self.assertEqual(drawn.age_label((now - timedelta(days=1)).isoformat(), now, asleep=True), "Yesterday")
        page = {"elements": [{"type": "notifications"}, {"type": "text", "value": "hi"}]}
        out, _, times = clocktime.date_for_time(page, {}, now)
        self.assertTrue(out["elements"][0].get("asleep"))
        self.assertFalse(page["elements"][0].get("asleep"), "the design keeps its own")
        self.assertEqual(times, set(), "nothing for the editor to say: it isn't a clock")

    def test_the_message_only_when_there_is_room(self):
        one = [{"title": "Backup failed", "message": "It couldn't reach its location.", "created": ""}]
        three = [dict(one[0]) for _ in range(3)]
        bare = [{**one[0], "message": ""}]
        with_msg, without = render(self.element, {"items": one}), render(self.element, {"items": bare})
        self.assertGreater(ink(with_msg), ink(without) + 300)
        no_msgs = [{**i, "message": ""} for i in three]
        self.assertEqual(ink(render(self.element, {"items": three})), ink(render(self.element, {"items": no_msgs})),
                         "three get no messages")

    def test_and_more_when_they_dont_fit(self):
        many = [{"title": f"Notification {k}", "message": "", "created": ""} for k in range(9)]
        self.assertEqual(drawn._fit(9, 180, 41, 41), (3, 6))
        self.assertGreater(ink(render(self.element, {"items": many})), ink(render(self.element, {"items": many[:3]})))

    def test_none_says_so_and_not_read_yet_is_only_the_heading(self):
        empty, unread = render(self.element, {"items": []}), render(self.element, None)
        self.assertGreater(ink(empty), ink(unread) + 300)
        self.assertGreater(ink(unread), 100)

    def test_fetched_in_the_render_cycle_with_home_assistants_zone(self):
        async def notes(session):
            return [{"title": "x"}]
        with unittest.mock.patch.object(needs_you, "fetch_notifications", notes):
            got = asyncio.run(widgets.fetch(None, {"type": "notifications"}, widgets.Ctx(home_tz="Europe/Bucharest")))
        self.assertEqual(got, {"items": [{"title": "x"}], "tz": "Europe/Bucharest"})

    def test_its_page_shows_by_the_add_ons_count(self):
        d = widgets.catalog()["notifications"]
        self.assertEqual((d["sensor"], d["window"]), ("sensor.epaper_notifications", True))
        note = next(f for f in d["fields"] if f["kind"] == "sensorid")["note"]
        self.assertIn("{sensor}", note)


import asyncio  # noqa: E402
import shutil  # noqa: E402

from test_presets import run_js  # noqa: E402


@unittest.skipUnless(shutil.which("node"), "no node to read the editor")
class TestNotificationsInTheEditor(unittest.TestCase):
    def test_the_preset_and_the_inspector_write_the_same_condition(self):
        got = run_js("""
import * as C from %s;
const p = P.presetById("notifications"), page = P.pageFor(p, p.looks[0], "");
const fresh = { tier: "when", elements: [{ type: "notifications" }] };
C.syncWidgetShowIf(fresh);
const own = { tier: "when", show_if: "{{ is_state('input_boolean.x','on') }}", elements: [{ type: "notifications" }] };
C.syncWidgetShowIf(own);
console.log(JSON.stringify({ group: p.group, page, fresh: fresh.show_if, own: own.show_if,
  parsed: C.parseShowIf(page.show_if), sensor: L.getWidgetSensorId({ type: "notifications" }) }));
""" % json.dumps(str(support.APP / "web" / "app" / "conditions.js")))
        cond = "{{ has_value('sensor.epaper_notifications') and states('sensor.epaper_notifications') | float(0) > 0 }}"
        self.assertEqual((got["group"], got["page"]["tier"], got["page"]["show_if"]), ("home", "when", cond))
        self.assertEqual(got["fresh"], cond)
        self.assertEqual(got["own"], "{{ is_state('input_boolean.x','on') }}", "the person's own condition stays")
        self.assertEqual((got["parsed"]["mode"], got["parsed"]["ent"]), ("simple", "sensor.epaper_notifications"))
        self.assertEqual(got["sensor"], "sensor.epaper_notifications")


class TestUpdatesDrawn(Sizes, unittest.TestCase):
    element = {"type": "updates", "x": 40, "y": 14, "w": 712, "h": 220}
    value = {"items": examples.updates()}

    def test_groups_in_a_column_where_theres_room_and_full_names_where_not(self):
        items = needs_you.updates_from(ROWS[:4])
        wide = render(self.element, {"items": items})
        narrow = render(self.element, {"items": items}, "crowpanel_290")
        self.assertGreater(ink(wide), 1000)
        self.assertGreater(ink(narrow), 300)
        # The column: the group's name drawn once, in the left part, on the 5.79".
        self.assertGreater(ink(wide, (40, 40, 200, 80)), 50)

    def test_a_version_whole_or_not_at_all(self):
        one = [{"group": "home_assistant", "name": "Home Assistant Core", "version": "2026.10.2", "installing": False}]
        no_version = [{**one[0], "version": ""}]
        small = lambda v: ink(render(self.element, {"items": v}, "crowpanel_290"))    # noqa: E731
        self.assertEqual(small(one), small(no_version), "no cut version on the 2.9 inch")
        self.assertGreater(ink(render(self.element, {"items": one})), ink(render(self.element, {"items": no_version})))

    def test_up_to_date_says_so(self):
        self.assertGreater(ink(render(self.element, {"items": []})), ink(render(self.element, None)) + 300)

    def test_its_page_shows_by_the_add_ons_count(self):
        self.assertEqual(widgets.catalog()["updates"]["sensor"], "sensor.epaper_updates")
        got = run_js("""const p = P.presetById("updates"); console.log(JSON.stringify(P.pageFor(p, p.looks[0], "")));""") \
            if shutil.which("node") else None
        if got:
            self.assertEqual(got["show_if"], "{{ has_value('sensor.epaper_updates') and states('sensor.epaper_updates') | float(0) > 0 }}")


class TestBadgeDrawn(Sizes, unittest.TestCase):
    element = {"type": "badge", "counts": "updates", "x": 672, "y": 14, "w": 96, "h": 96}
    value = 2

    def test_nothing_at_all_at_zero_or_before_its_read(self):
        for value in (0, None, "unknown", -1):
            self.assertEqual(ink(render(self.element, value)), 0, value)

    def test_the_number_in_a_dot_that_grows_into_a_pill(self):
        self.assertEqual([drawn.badge_text(n) for n in (1, 42, 99, 100)], ["1", "42", "99", "99+"])
        one, many = render(self.element, 1), render(self.element, 120)
        self.assertGreater(ink(many), ink(one))
        # The dot is solid, at the top right of the box, with the number in white inside it.
        dot = one.crop((672 + 60, 14, 672 + 92, 14 + 30)).histogram()
        self.assertGreater(dot[0], dot[-1])

    def test_each_count_has_its_own_icon(self):
        drawn_icons = {c: ink(render({**self.element, "counts": c}, 3)) for c in needs_you.COUNTS}
        self.assertEqual(len(set(drawn_icons.values())), len(needs_you.COUNTS))
        from render import layout
        self.assertTrue(all(layout.can_draw_icon(i) for i in drawn.BADGE_ICONS.values()))
        self.assertEqual(set(drawn.BADGE_ICONS), set(needs_you.COUNTS))

    def test_counts_what_its_set_to(self):
        async def ups(session):
            return [{}, {}]

        async def notes(session):
            return [{}]

        async def reps(session):
            return 4
        with unittest.mock.patch.object(needs_you, "fetch_updates", ups), \
             unittest.mock.patch.object(needs_you, "fetch_notifications", notes), \
             unittest.mock.patch.object(needs_you, "fetch_repairs", reps):
            got = {c: asyncio.run(widgets.fetch(None, {"type": "badge", "counts": c}, widgets.Ctx())) for c in needs_you.COUNTS}
        self.assertEqual(got, {"updates": 2, "notifications": 1, "repairs": 4, "all": 7})
        field = next(f for f in widgets.catalog()["badge"]["fields"] if f["key"] == "counts")
        self.assertEqual([o[0] for o in field["options"]], list(needs_you.COUNTS), "the inspector offers what it counts")
        self.assertEqual(field["def"], "updates")
        self.assertEqual(examples.badge("all"), 8)
