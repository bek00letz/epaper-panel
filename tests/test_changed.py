"""A "changed" condition: a page shows for N minutes after a sensor takes a new
value, and an alert fires at each change. A restart, or a sensor dropping out
and coming back with the same value, isn't a change."""
import json
import unittest
from unittest import mock

import support  # noqa: F401  (puts the add-on on the path)
import conditions
import frames
import runtime
from sources import changes

CAT = "sensor.pawpaw_location"
ANY = "{{ has_value('sensor.pawpaw_location') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}"
OUT = "{{ is_state('sensor.pawpaw_location','Outdoor Cat') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}"
NOW = 1_800_000_000.0


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class TestTheCondition(unittest.TestCase):
    def test_reads_the_simple_forms(self):
        self.assertEqual(conditions.changed(ANY), conditions.Changed(CAT, None, 30))
        self.assertEqual(conditions.changed(OUT), conditions.Changed(CAT, "Outdoor Cat", 30))

    def test_anything_else_isnt_one(self):
        for expr in ("{{ is_state('sensor.pawpaw_location','Outdoor Cat') }}",
                     "{{ has_value('sensor.other') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}",
                     "{{ has_value('sensor.pawpaw_location') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) and x }}",
                     "", None):
            self.assertIsNone(conditions.changed(expr), expr)

    def test_other_conditions_are_untouched(self):
        self.assertEqual(conditions.guarded(ANY), ANY)
        self.assertIsNone(conditions.local(ANY, {CAT: {"state": "Outdoor Cat"}}))

    def test_holds_for_its_minutes_after_the_change(self):
        c = conditions.changed(OUT)
        seen = {"state": "Outdoor Cat", "at": NOW - 29 * 60}
        self.assertTrue(conditions.changed_holds(c, seen, NOW))
        self.assertFalse(conditions.changed_holds(c, seen, NOW + 61), "gone after 30 minutes")
        self.assertTrue(conditions.changed_holds(c, seen, NOW + 61, minutes=60), "a window it's given wins")

    def test_to_a_value_and_no_value(self):
        c = conditions.changed(OUT)
        self.assertFalse(conditions.changed_holds(c, {"state": "Indoor Cat", "at": NOW - 60}, NOW))
        self.assertFalse(conditions.changed_holds(conditions.changed(ANY), {"state": "unavailable", "at": NOW - 60}, NOW))
        self.assertFalse(conditions.changed_holds(c, {"state": "Outdoor Cat", "at": None}, NOW), "no change")
        self.assertFalse(conditions.changed_holds(c, None, NOW), "nothing read yet")


class TestWhatCountsAsAChange(unittest.TestCase):
    def rows(self, *pairs):
        return [{"state": s, "last_changed": iso(t)} for s, t in pairs]

    def test_a_new_value(self):
        rows = self.rows(("Indoor Cat", NOW - 1800), ("Outdoor Cat", NOW - 600))
        self.assertEqual(changes.last_real_change(rows, NOW - 1800), (NOW - 600, "Outdoor Cat"))

    def test_a_restart_isnt_one(self):
        # Home Assistant writes the same value again as it starts.
        rows = self.rows(("Outdoor Cat", NOW - 1800), ("Outdoor Cat", NOW - 600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))

    def test_dropping_out_and_back_isnt_one(self):
        rows = self.rows(("Outdoor Cat", NOW - 1800), ("unavailable", NOW - 700), ("unknown", NOW - 650), ("Outdoor Cat", NOW - 600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))

    def test_coming_back_with_another_value_is_one(self):
        rows = self.rows(("Indoor Cat", NOW - 1800), ("unavailable", NOW - 700), ("Outdoor Cat", NOW - 600))
        self.assertEqual(changes.last_real_change(rows, NOW - 1800), (NOW - 600, "Outdoor Cat"))

    def test_only_inside_the_window(self):
        rows = self.rows(("Indoor Cat", NOW - 7200), ("Outdoor Cat", NOW - 3600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))


class TestAskingHomeAssistant(unittest.IsolatedAsyncioTestCase):
    async def change(self, state, changed, history=(), before=()):
        asked = []

        async def template(session, tpl):
            return json.dumps({"state": state, "changed": changed})

        async def history_api(session, path):
            asked.append(path)
            return [list(before if len(asked) > 1 else history)]
        with mock.patch.object(changes, "HA_TOKEN", "token"), \
             mock.patch.object(changes, "ha_template", template), \
             mock.patch.object(changes, "ha_json", history_api):
            got = await changes.change(None, CAT, 30, now=NOW)
        return got, asked

    async def test_reads_no_history_when_nothing_happened(self):
        got, asked = await self.change("Outdoor Cat", NOW - 3 * 3600)
        self.assertIsNone(got["at"])
        self.assertEqual(asked, [], "its last_changed is older than the window")

    async def test_home_assistant_restarting(self):
        # last_changed moved as it restarted 5 minutes ago; history shows the same value.
        got, asked = await self.change("Outdoor Cat", NOW - 300,
                                       [{"state": "Outdoor Cat", "last_changed": iso(NOW - 1800)},
                                        {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}])
        self.assertIsNone(got["at"])
        self.assertEqual(len(asked), 1)
        self.assertIn("filter_entity_id=sensor.pawpaw_location", asked[0])

    async def test_a_real_change(self):
        got, _ = await self.change("Outdoor Cat", NOW - 300,
                                   [{"state": "Indoor Cat", "last_changed": iso(NOW - 1800)},
                                    {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}])
        self.assertEqual((got["at"], got["to"], got["history"]), (NOW - 300, "Outdoor Cat", True))

    async def test_the_window_starts_while_it_has_no_value(self):
        # Unavailable since before the window; what it was before that decides.
        window = [{"state": "unavailable", "last_changed": iso(NOW - 1800)},
                  {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}]
        got, asked = await self.change("Outdoor Cat", NOW - 300, window,
                                       [{"state": "Outdoor Cat", "last_changed": iso(NOW - 9000)}] + window)
        self.assertEqual(len(asked), 2)
        self.assertIsNone(got["at"], "back with the value it had")

    async def test_a_sensor_the_recorder_leaves_out(self):
        got, _ = await self.change("Outdoor Cat", NOW - 300, [])
        self.assertEqual((got["at"], got["history"]), (NOW - 300, False))

    async def test_no_value_now(self):
        got, asked = await self.change("unavailable", NOW - 60)
        self.assertIsNone(got["at"])
        self.assertEqual(asked, [])


class TestPages(unittest.IsolatedAsyncioTestCase):
    """Only when: the page joins the rotation for 30 minutes after a change."""

    async def live(self, seen, at):
        spec = {"pages": {"home": {"elements": []}, "cat": {"tier": "when", "show_if": OUT, "elements": []}},
                "rotation": ["home", "cat"]}
        fetch = mock.AsyncMock(return_value=seen)
        with mock.patch.object(changes, "fetch_change", fetch), \
             mock.patch.object(frames.time, "time", return_value=at), \
             mock.patch.object(frames, "resolve_templates", mock.AsyncMock(return_value={})), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            live = await frames.eligible_pages(None, spec, runtime.linger("test-changed"))
        fetch.assert_awaited_with(None, CAT, 30)
        return live

    async def test_shows_after_a_change_then_leaves(self):
        seen = {"state": "Outdoor Cat", "at": NOW, "to": "Outdoor Cat"}
        self.assertEqual(await self.live(seen, NOW + 60), ["home", "cat"])
        self.assertEqual(await self.live(seen, NOW + 1801), ["home"])

    async def test_not_after_a_restart(self):
        self.assertEqual(await self.live({"state": "Outdoor Cat", "at": None}, NOW), ["home"])


class TestAlerts(unittest.IsolatedAsyncioTestCase):
    """As an alert: fires at each change and holds for its own minutes."""

    def setUp(self):
        self.state = runtime.new_alert()
        self.spec = {"pages": {"cat": {"tier": "alert", "show_if": ANY, "hold_minutes": 10}}}
        self.windows = []

    async def check(self, seen, at):
        async def fetch(session, entity, minutes):
            self.windows.append(minutes)
            return seen
        with mock.patch.object(changes, "fetch_change", fetch), \
             mock.patch.object(frames.time, "time", return_value=at):
            return await frames.check_alerts(None, self.spec, self.state)

    async def test_fires_on_a_change_and_holds_for_its_minutes(self):
        out = {"state": "Outdoor Cat", "at": NOW}
        self.assertEqual(await self.check(out, NOW + 30), "cat")
        self.assertEqual(set(self.windows), {10}, "its window is the alert's hold, not the 30 written")
        self.assertEqual(await self.check(out, NOW + 300), "cat")
        self.assertIsNone(await self.check(out, NOW + 601), "given back after 10 minutes")
        self.assertIsNone(await self.check(out, NOW + 900))

    async def test_each_change_fires_again(self):
        await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 30)
        self.assertIsNone(await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 700))
        back = {"state": "Indoor Cat", "at": NOW + 760}
        self.assertEqual(await self.check(back, NOW + 790), "cat", "back in: a new alert")
        self.assertGreater(self.state["until"], NOW + 790 + 590)

    async def test_a_change_while_it_holds_starts_it_again(self):
        await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 30)
        await self.check({"state": "Indoor Cat", "at": NOW + 300}, NOW + 330)
        self.assertEqual(self.state["until"], NOW + 330 + 600)

    async def test_a_restart_doesnt_fire(self):
        self.assertIsNone(await self.check({"state": "Outdoor Cat", "at": None}, NOW))

    async def test_until_uses_its_limit(self):
        self.spec["pages"]["cat"].update(ends="until", until_if="{{ home }}", hold_minutes=120)
        with mock.patch.object(frames, "resolve_templates", mock.AsyncMock(return_value={"cat:until": "False"})):
            self.assertEqual(await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 3600), "cat")
        self.assertEqual(set(self.windows), {120})


if __name__ == "__main__":
    unittest.main()
