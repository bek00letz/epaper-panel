"""A screen's two timers (timing.py): Update every and Rotate every, and what a screen set before 0.13 means.

Then the one thing that keeps them the one source of truth on a CrowPanel
that's always on: its own timer in Home Assistant is kept at Update every.
"""
import unittest
from unittest import mock

import support
import devices
import runtime
import timing
from kinds import crowpanel


class TestUpdateEvery(unittest.TestCase):
    def test_always_on_by_default(self):
        self.assertEqual(timing.update_minutes({}), timing.ALWAYS_ON)
        self.assertFalse(timing.sleeps({}))

    def test_a_screen_set_before_0_13_means_what_it_meant(self):
        # Low Power Mode off was always on, whatever its wake interval or its panel's own refresh interval.
        self.assertEqual(timing.update_minutes({"low_power": False, "wake_minutes": 30,
                                                "setup": {"refresh_interval": "5min"}}), 1)
        self.assertEqual(timing.update_minutes({"low_power": True, "wake_minutes": 30}), 30, "on keeps its interval")
        self.assertEqual(timing.update_minutes({"low_power": True}), timing.ASLEEP_DEFAULT)
        self.assertEqual(timing.update_minutes({"wake_minutes": 60}, stays_on=False), 60, "a TRMNL")
        self.assertEqual(timing.update_minutes({"setup": {"wake_minutes": 30}}, stays_on=False), 30,
                         "a TRMNL paired before 0.12 kept it in its setup")
        self.assertEqual(timing.update_minutes({"update_minutes": 120, "low_power": False}), 120,
                         "once set, the old fields mean nothing")

    def test_a_screen_that_cant_stay_on_starts_at_five_minutes(self):
        self.assertEqual(timing.update_choices(False)[0], timing.ASLEEP_FROM)
        self.assertEqual(timing.update_minutes({}, stays_on=False), timing.ASLEEP_DEFAULT)
        self.assertEqual(timing.update_minutes({"update_minutes": 1}, stays_on=False), timing.ASLEEP_DEFAULT)
        self.assertTrue(timing.sleeps({}, stays_on=False))

    def test_the_choices(self):
        self.assertEqual(timing.UPDATE_CHOICES, (1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 720, 1440))
        self.assertEqual(timing.update_minutes({"update_minutes": 7}), 1, "not offered: the default")
        self.assertEqual(timing.settings({}, {"update_minutes": "1440"}), {"update_minutes": 1440})
        self.assertEqual(timing.settings({}, {"name": "x"}), {})
        for wrong in (7, 0, "soon", None):
            with self.assertRaises(ValueError):
                timing.settings({}, {"update_minutes": wrong})
        with self.assertRaises(ValueError):
            timing.settings({}, {"update_minutes": 2}, stays_on=False)


class TestRotateEvery(unittest.TestCase):
    def test_seconds_while_always_on(self):
        self.assertEqual(timing.rotate_seconds({}), timing.ROTATE_DEFAULT)
        self.assertEqual(timing.rotate_seconds({"rotate_seconds": 45}), 45, "what 0.12 kept with the pages")
        self.assertEqual(timing.rotate_seconds({"rotate_seconds": 99999}), 3600)
        with self.assertRaises(ValueError):
            timing.settings({}, {"rotate_seconds": 7})

    def test_a_multiple_of_update_every_while_asleep(self):
        self.assertEqual(timing.rotate_updates({"update_minutes": 15}), 1, "every update, as before 0.13")
        self.assertEqual(timing.rotate_updates({"update_minutes": 15, "rotate_updates": 4}), 4)
        self.assertEqual(timing.rotate_update_choices(15), [1, 2, 3, 4, 6, 8, 12, 24])
        self.assertEqual(timing.rotate_update_choices(720), [1, 2], "at least once a day")
        self.assertEqual(timing.rotate_update_choices(1440), [1])
        self.assertEqual(timing.rotate_updates({"update_minutes": 720, "rotate_updates": 8}), 2,
                         "a longer Update every keeps the most it can")
        self.assertEqual(timing.settings({"update_minutes": 15}, {"update_minutes": 60, "rotate_updates": 24}),
                         {"update_minutes": 60, "rotate_updates": 24})
        with self.assertRaises(ValueError):
            timing.settings({"update_minutes": 15}, {"update_minutes": 120, "rotate_updates": 24})

    def test_what_the_editor_gets(self):
        got = timing.describe({"update_minutes": 30, "rotate_updates": 2})
        self.assertEqual((got["update_minutes"], got["always_on"], got["can_stay_on"], got["rotate_updates"]),
                         (30, False, True, 2))
        self.assertEqual(got["rotate_update_choices"], [1, 2, 3, 4, 6, 8, 12, 24])


class FakeLink:
    def __init__(self, have):
        self.have, self.set_to = have, None

    async def discover(self):
        return True

    async def refresh_interval(self):
        return self.have

    async def set_refresh_interval(self, minutes):
        self.set_to = minutes
        return True, ""


class TestItsOwnTimer(unittest.IsolatedAsyncioTestCase):
    """Always on, a CrowPanel checks every minute on its own timer. A panel upgraded from 0.12
    keeps the number it had (5 minutes was the default), even through a reinstall."""

    def setUp(self):
        support.fresh_data_dir()
        self.dev = devices.add("crowpanel", "Hall", "crowpanel_579")

    def tearDown(self):
        support.use_test_data_dir()

    async def test_it_is_kept_at_update_every(self):
        runtime.device(self.dev["id"]).link = link = FakeLink(have=5)
        self.assertTrue(await crowpanel.keep_its_timer_now(self.dev["id"]))
        self.assertEqual(link.set_to, 1)

    async def test_left_alone_when_it_agrees_or_sleeps_or_cant_be_read(self):
        runtime.device(self.dev["id"]).link = link = FakeLink(have=1)
        self.assertFalse(await crowpanel.keep_its_timer_now(self.dev["id"]))
        link.have = None
        self.assertIsNone(await crowpanel.keep_its_timer_now(self.dev["id"]))
        devices.update(self.dev["id"], update_minutes=15)
        link.have = 5
        self.assertIsNone(await crowpanel.keep_its_timer_now(self.dev["id"]), "asleep, its own timer doesn't run")
        self.assertIsNone(link.set_to)

    async def test_checked_now_and_then_in_the_background(self):
        runtime.device(self.dev["id"]).link = link = FakeLink(have=5)
        rt = runtime.device(self.dev["id"]).kind
        rt.pop("timer_checked", None)
        with mock.patch.object(crowpanel, "HA_TOKEN", "token"):
            crowpanel.keep_its_timer(self.dev)
            task = rt["timer_task"]
            crowpanel.keep_its_timer(self.dev)                    # one at a time
            self.assertIs(rt.get("timer_task"), task)
            await task
            self.assertEqual(link.set_to, 1)
            link.set_to = None
            crowpanel.keep_its_timer(self.dev)
            self.assertNotIn("timer_task", rt, "not again for a while")
        rt.pop("timer_checked")
        crowpanel.keep_its_timer(self.dev)
        self.assertNotIn("timer_task", rt, "without Home Assistant there's nothing to check")


if __name__ == "__main__":
    unittest.main()


class TestAKindsShortestUpdate(unittest.TestCase):
    """A kind that can't stay connected says its own shortest Update every; 5 minutes is TRMNL's, not the core's."""

    def test_a_kind_that_can_wake_every_two_minutes_is_offered_two(self):
        import kinds

        class Quick(kinds.Kind):
            id = "quick"
            stays_on = False
            shortest_update = 2

        self.assertEqual(timing.update_choices(**Quick().timers)[0], 2)
        self.assertEqual(Quick().update_minutes({"update_minutes": 2}), 2)
        self.assertEqual(timing.settings({}, {"update_minutes": 2}, **Quick().timers), {"update_minutes": 2})
        self.assertEqual(timing.describe({"update_minutes": 2}, **Quick().timers)["update_choices"][0], 2)

    def test_a_trmnl_still_starts_at_five(self):
        from kinds import trmnl
        kind = next(k for k in vars(trmnl).values() if isinstance(k, type) and getattr(k, "id", "") == "trmnl")
        self.assertEqual(timing.update_choices(**kind().timers)[0], 5)
