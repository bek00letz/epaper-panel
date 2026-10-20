"""The shared mode for screens that sleep (paging.py), and a CrowPanel that sleeps between updates.

The cursor, "updated" as when a page last changed, the sleep time, quiet
hours at the wake, and the awake time. Then a CrowPanel that sleeps (Update
every 2 minutes or more), end to end through its device port: what tells it
to sleep, Rotate every, and that nothing tells it to sleep when it's always on.
"""
import os
import time
import unittest
from datetime import datetime, timedelta

from aiohttp.test_utils import TestClient, TestServer

import support
import config
import devices
import frames
import kinds
import paging
import runtime
import web
from kinds import trmnl
from render import epf

from test_trmnl import display_headers, setup_headers


def hhmm(dt):
    return dt.strftime("%H:%M")


def ahead(quiet_hours=None, quiet=False, reason="outside quiet window", alert=None):
    spec = {"pages": {"a": {}, "b": {}}, "quiet_hours": quiet_hours or {}}
    st = frames.DesignState(alert, ["a", "b"], [{"name": "a", "want": 2}, {"name": "b", "want": 1}])
    return paging.Ahead("crowpanel_579", spec, st, quiet, reason, {})


class TestTheCursor(unittest.TestCase):
    def test_step(self):
        plans = [{"name": "a", "want": 2}, {"name": "b", "want": 1}, {"name": "c", "want": 3}]
        self.assertEqual(paging.step(plans, {}, by_page=False), (0, 0), "a first wake starts at the start")
        self.assertEqual(paging.step(plans, {"pos": 0, "name": "a", "item": 0}, False), (0, 1))
        self.assertEqual(paging.step(plans, {"pos": 0, "name": "a", "item": 1}, False), (1, 0))
        self.assertEqual(paging.step(plans, {"pos": 0, "name": "a", "item": 0}, True), (1, 0), "a person skips items")
        self.assertEqual(paging.step(plans, {"pos": 2, "name": "c", "item": 2}, False), (0, 0), "round again")
        self.assertEqual(paging.step(plans, {"pos": 5, "name": "c", "item": 0}, False), (2, 1), "found by name")
        self.assertEqual(paging.step(plans, {"pos": 1, "name": "gone", "item": 0}, False), (0, 0))

    def test_the_day_joins_the_time_once_it_is_not_today(self):
        now = datetime(2026, 10, 20, 9, 0)
        self.assertEqual(paging.updated_label(datetime(2026, 10, 20, 8, 5), now), "updated 08:05")
        self.assertEqual(paging.updated_label(datetime(2026, 10, 19, 22, 5), now), "updated Mon 22:05")


class TestTheSleepTime(unittest.TestCase):
    dev = {"id": "9", "kind": "crowpanel", "update_minutes": 15}
    now = datetime(2026, 10, 20, 14, 0)

    def test_the_wake_interval(self):
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(), self.now, person=False), 900)

    def test_cut_short_to_wake_just_after_quiet_hours_start(self):
        qh = {"enabled": True, "start": "14:05", "end": "07:00"}
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(qh), self.now, False), 5 * 60 + paging.QUIET_MARGIN)

    def test_through_quiet_hours_until_they_end(self):
        qh = {"enabled": True, "start": "13:00", "end": "16:00"}
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(qh), self.now, False), 2 * 3600 + paging.QUIET_MARGIN)
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(qh), self.now, True), paging.GLANCE_SECONDS,
                         "a press shows a page for a while, then the sleep screen")

    def test_away_has_no_end_so_it_checks_at_its_interval(self):
        qh = {"enabled": True, "start": "23:00", "end": "07:00", "presence_entity": "person.someone"}
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(qh, True, "away (person.someone: not_home)"), self.now,
                                              False), 900)

    def test_an_alert_wakes_at_the_interval_through_quiet_hours(self):
        qh = {"enabled": True, "start": "13:00", "end": "16:00"}
        self.assertEqual(paging.sleep_seconds(self.dev, ahead(qh, alert="leak"), self.now, False), 900)

    def test_the_schedule_is_the_clock_at_the_wake_not_the_last_cycle(self):
        # The cycle a minute ago said quiet; they ended since. Sleeping "until they end"
        # would be a whole day.
        qh = {"enabled": True, "start": "23:00", "end": "07:00"}
        stale = ahead(qh, quiet=True, reason="schedule (23:00–07:00)")
        at = datetime(2026, 10, 20, 7, 0, 30)
        self.assertEqual(paging.quiet_now(stale, at), (False, "outside quiet window"))
        self.assertLessEqual(paging.sleep_seconds(self.dev, stale, at, False), 900)
        # And the other way: they started after the last cycle.
        self.assertTrue(paging.quiet_now(ahead(qh), datetime(2026, 10, 20, 23, 0, 20))[0])


class TestTheNightTheClocksChange(unittest.TestCase):
    """A screen asleep until quiet hours end wakes at that time on the clock, not an hour off."""

    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Bucharest"           # clocks change at 03:00/04:00 local, like most of Europe
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_seconds_until_seven(self):
        self.assertEqual(paging.seconds_until("07:00", datetime(2026, 10, 20, 23, 0)), 8 * 3600, "a usual night")
        self.assertEqual(paging.seconds_until("07:00", datetime(2026, 10, 24, 23, 0)), 9 * 3600,
                         "autumn: the clocks go back, so 07:00 is an hour further")
        self.assertEqual(paging.seconds_until("07:00", datetime(2026, 3, 28, 23, 0)), 7 * 3600,
                         "spring: the clocks go forward, so it's an hour nearer")
        self.assertEqual(paging.seconds_until("07:00", datetime(2026, 10, 25, 2, 0).astimezone()), 6 * 3600,
                         "an aware time, during the night itself")

    def test_asleep_through_quiet_hours(self):
        qh = {"enabled": True, "start": "22:00", "end": "07:00"}
        dev = {"id": "9", "kind": "crowpanel", "update_minutes": 15}
        self.assertEqual(paging.sleep_seconds(dev, ahead(qh), datetime(2026, 10, 24, 23, 0), False),
                         9 * 3600 + paging.QUIET_MARGIN)


class TestAwake(unittest.TestCase):
    def setUp(self):
        support.fresh_data_dir()
        self.dev = devices.add("crowpanel", "Hall", "crowpanel_579", update_minutes=15)

    def tearDown(self):
        support.use_test_data_dir()

    def test_how_long_it_was_awake(self):
        self.assertIsNone(paging.awake_average(self.dev))
        for ms in ("4200", "3800", "nonsense", "0", "-5"):
            paging.note_awake(self.dev, ms)
        self.assertEqual(paging.awake_average(self.dev), 4.0)
        for _ in range(paging.KEEP_AWAKE_TIMES):
            paging.note_awake(self.dev, 1000)
        self.assertEqual(paging.awake_average(self.dev), 1.0, "a short history: the recent average")

    def test_a_person_keeps_it_awake_a_minute_and_an_update_ten(self):
        self.assertEqual(paging.awake_seconds(self.dev, person=False), 0)
        self.assertEqual(paging.awake_seconds(self.dev, person=True), paging.PERSON_AWAKE_SECONDS)
        info = paging.ask_to_stay_awake(self.dev)
        self.assertEqual(info, {"asked": True, "until": None}, "waits for its next wake")
        self.assertGreater(paging.awake_seconds(self.dev, person=False), paging.STAY_AWAKE_SECONDS - 5)
        self.assertTrue(paging.stay_awake_info(self.dev)["until"], "counts from the wake it was delivered at")
        self.assertGreater(paging.awake_seconds(self.dev, person=False), 500, "a later wake in the ten minutes too")
        paging.ask_to_stay_awake(self.dev, False)
        self.assertEqual(paging.awake_seconds(self.dev, person=False), 0)


class LowPowerBase(unittest.IsolatedAsyncioTestCase):
    """Device 1 stays connected; a second CrowPanel ("Hall") shows the same pages, copied."""

    async def asyncSetUp(self):
        support.fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        self.hall = devices.add("crowpanel", "Hall", "crowpanel_579", copy_from="1")
        self.key = devices.key_of(self.hall)
        panel, editor = web.make_apps()
        self.lan = TestClient(TestServer(panel))
        self.ed = TestClient(TestServer(editor))
        await self.lan.start_server()
        await self.ed.start_server()
        await frames.refresh_frames(None)

    async def asyncTearDown(self):
        await self.lan.close()
        await self.ed.close()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        support.use_test_data_dir()

    async def update_every(self, minutes=15, **more):
        r = await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"update_minutes": minutes, **more})
        self.assertEqual(r.status, 200, await r.text())
        return await r.json()

    async def fetch(self, **params):
        return await self.lan.get("/frames.epf", params={"token": self.key, **params})


class TestAlwaysOn(LowPowerBase):
    async def test_always_on_by_default_and_nothing_tells_it_to_sleep(self):
        self.assertNotIn("update_minutes", devices.get(self.hall["id"]), "nothing set: always on")
        for params in ({}, {"wake": "timer"}, {"wake": "button"}):
            r = await self.fetch(**params)
            self.assertEqual(r.status, 200)
            self.assertNotIn("X-EPF-Sleep", r.headers, "off: it stays connected, as today")
            self.assertGreater(epf.decode_epf(await r.read()).header.page_count, 1, "every page, as always")
        r = await self.fetch(wake="timer")
        self.assertEqual((await self.lan.get("/frames.epf", params={"token": self.key, "wake": "timer"},
                                             headers={"If-None-Match": r.headers["ETag"]})).status, 304)
        listed = await (await self.ed.get("/api/devices")).json()
        hall = next(d for d in listed["devices"] if d["id"] == self.hall["id"])
        self.assertEqual((hall["owns_interval"], hall["can_wake"], hall["timing"]["always_on"]), ("device", True, True))
        self.assertEqual(hall["timing"]["update_minutes"], 1)


class TestSleeping(LowPowerBase):
    async def test_switching_to_sleeping_in_the_editor(self):
        body = await self.update_every(15)
        hall = body["device"]
        self.assertFalse(hall["timing"]["always_on"])
        self.assertEqual(hall["owns_interval"], "addon", "it wakes when the add-on says")
        self.assertFalse(hall["can_wake"], "asleep between updates: alerts show at its next update")
        self.assertEqual(body["note"], "It starts sleeping at its next update.")
        self.assertFalse(hall["info"]["firmware_sleeps"], "until its firmware says why it woke")
        await self.fetch(wake="timer")
        listed = await (await self.ed.get("/api/devices")).json()
        self.assertTrue(next(d for d in listed["devices"] if d["id"] == self.hall["id"])["info"]["firmware_sleeps"])
        status = await (await self.ed.get(f"/api/status?device={self.hall['id']}")).json()
        self.assertIsNone(status["panel_link"], "no early wakes queued for a panel that's asleep")
        on = await self.update_every(1)
        self.assertIn("within 15 minutes", on["note"])
        self.assertIsNone((await self.update_every(1))["note"], "nothing switched")

    async def test_a_timer_wake_gets_one_picked_page_and_how_long_to_sleep(self):
        await self.update_every()
        r = await self.fetch(wake="timer", awake_ms="3100")
        self.assertEqual(r.headers["X-EPF-Sleep"], "900; awake=0")
        first = epf.decode_epf(await r.read())
        self.assertEqual(first.header.page_count, 1, "one page: a quarter of the decode time of the strip")
        r2 = await self.fetch(wake="timer")
        second = epf.decode_epf(await r2.read())
        self.assertNotEqual(first.categories[0].cat_id, second.categories[0].cat_id, "the next page each wake")
        # The page keeps the identity it has among every page, so a press after it keeps its place.
        strip = epf.decode_epf(runtime.device(self.hall["id"]).frames.epf_strip)
        self.assertIn(first.categories[0].cat_id, [c.cat_id for c in strip.categories])
        self.assertEqual(paging.awake_average(devices.get(self.hall["id"])), 3.1)

    async def test_an_unchanged_page_is_not_downloaded_again(self):
        await self.update_every(60)
        devices.set_state(self.hall["id"], cursor={})
        r = await self.fetch(wake="timer")
        etag = r.headers["ETag"]
        await frames.refresh_frames(None)
        devices.set_state(self.hall["id"], cursor={})                # the same page again, next cycle
        r = await self.lan.get("/frames.epf", params={"token": self.key, "wake": "timer"},
                               headers={"If-None-Match": etag})
        self.assertEqual(r.status, 304, "updated is when it last changed: same picture, same tag")
        self.assertEqual(r.headers["X-EPF-Sleep"], "3600; awake=0", "a 304 still says how long to sleep")

    async def test_a_press_gets_every_page_and_a_minute_awake(self):
        await self.update_every()
        r = await self.fetch(wake="button")
        self.assertGreater(epf.decode_epf(await r.read()).header.page_count, 1)
        self.assertEqual(r.headers["X-EPF-Sleep"], f"900; awake={paging.PERSON_AWAKE_SECONDS}")
        r = await self.fetch()
        self.assertIn("X-EPF-Sleep", r.headers, "firmware that can't sleep yet ignores it")

    async def test_a_later_download_while_awake_adds_no_minute(self):
        # Only the first download after a wake says wake=; later ones (the panel's own refresh
        # timer, every minute on some panels) must not start another minute, or it never sleeps.
        await self.update_every()
        self.assertTrue((await self.fetch(wake="button")).headers["X-EPF-Sleep"].endswith(
            f"awake={paging.PERSON_AWAKE_SECONDS}"))
        self.assertEqual((await self.fetch()).headers["X-EPF-Sleep"], "900; awake=0")
        await self.ed.post(f"/api/devices/{self.hall['id']}/stay-awake")
        await self.fetch(wake="timer")
        awake = int((await self.fetch()).headers["X-EPF-Sleep"].split("awake=")[1])
        self.assertGreater(awake, paging.STAY_AWAKE_SECONDS - 5, "asked to stay awake: what's left of it")

    async def test_stay_awake_for_an_update(self):
        await self.update_every()
        r = await self.ed.post(f"/api/devices/{self.hall['id']}/stay-awake")
        self.assertEqual((await r.json())["stay_awake"], {"asked": True, "until": None})
        r = await self.fetch(wake="timer")
        sleep_for, awake = r.headers["X-EPF-Sleep"].split("; awake=")
        self.assertGreater(int(awake), paging.STAY_AWAKE_SECONDS - 5, "the same field carries it")
        await self.ed.delete(f"/api/devices/{self.hall['id']}/stay-awake")
        self.assertEqual((await self.fetch(wake="timer")).headers["X-EPF-Sleep"], "900; awake=0")
        await self.update_every(1)
        self.assertEqual((await self.ed.post(f"/api/devices/{self.hall['id']}/stay-awake")).status, 409)

    async def test_quiet_hours_send_the_sleep_screen_until_they_end(self):
        now = datetime.now()
        devices.update(self.hall["id"], update_minutes=15,
                       quiet_hours={"enabled": True, "start": hhmm(now - timedelta(hours=1)),
                                    "end": hhmm(now + timedelta(hours=2))})
        await frames.refresh_frames(None)
        r = await self.fetch(wake="timer")
        page = epf.decode_epf(await r.read())
        self.assertEqual(page.categories[0].flags, epf.CAT_FLAG_SLEEP | epf.CAT_FLAG_SLEEP_AUTO)
        sleep_for = int(r.headers["X-EPF-Sleep"].split(";")[0])
        until_end = ((now + timedelta(hours=2)).replace(second=0, microsecond=0) - now).total_seconds()
        self.assertAlmostEqual(sleep_for, until_end + paging.QUIET_MARGIN, delta=90)

    async def test_update_every_is_how_long_it_sleeps(self):
        await self.update_every(30)
        self.assertEqual(devices.get(self.hall["id"])["update_minutes"], 30)
        self.assertEqual((await self.fetch(wake="timer")).headers["X-EPF-Sleep"], "1800; awake=0")
        await self.update_every(1440)
        self.assertEqual((await self.fetch(wake="timer")).headers["X-EPF-Sleep"], "86400; awake=0", "up to a day")
        self.assertEqual((await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"update_minutes": 7})).status, 400)
        status = await (await self.ed.get(f"/api/status?device={self.hall['id']}")).json()
        self.assertEqual(status["panel_interval"], 1440)

    async def test_rotate_every_n_updates(self):
        await self.update_every(15, rotate_updates=3)
        devices.set_state(self.hall["id"], cursor={})
        ids = [epf.decode_epf(await (await self.fetch(wake="timer")).read()).categories[0].cat_id for _ in range(7)]
        self.assertEqual(len(set(ids[0:3])), 1, "each update refreshes the page it's on")
        self.assertEqual(len(set(ids[3:6])), 1)
        self.assertNotEqual(ids[2], ids[3], "every third moves on")
        self.assertNotEqual(ids[5], ids[6])
        await self.update_every(15, rotate_updates=1)
        before = epf.decode_epf(await (await self.fetch(wake="timer")).read()).categories[0].cat_id
        after = epf.decode_epf(await (await self.fetch(wake="timer")).read()).categories[0].cat_id
        self.assertNotEqual(before, after, "every update: the next page each wake, as before 0.13")
        await self.fetch(wake="button")
        self.assertEqual(devices.state(self.hall["id"])["cursor"]["shown"], 1, "a press starts the count again")
        r = await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"rotate_updates": 5})
        self.assertEqual(r.status, 400, "only the multiples offered")
        r = await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"update_minutes": 720, "rotate_updates": 3})
        self.assertEqual(r.status, 400, "a page moves on at least once a day")

    async def test_each_mode_keeps_its_own_rotation(self):
        body = await self.update_every(1, rotate_seconds=45)
        await self.update_every(15, rotate_updates=4)
        timers = (await self.update_every(1))["device"]["timing"]
        self.assertEqual((timers["rotate_seconds"], timers["rotate_updates"]), (45, 4))
        self.assertEqual(runtime.device(self.hall["id"]).frames.rotate_seconds, 45, "always on, the panel turns them")
        self.assertEqual((await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"rotate_seconds": 7})).status, 400)
        self.assertEqual(body["device"]["timing"]["rotate_seconds_choices"], [15, 30, 45, 60, 120, 300])

    async def test_added_sleeping(self):
        r = await self.ed.post("/api/devices", json={"kind": "crowpanel", "name": "Porch", "display": "crowpanel_579",
                                                     "pages": "new", "update_minutes": 15})
        self.assertEqual(r.status, 200, await r.text())
        dev = (await r.json())["device"]
        self.assertEqual((dev["timing"]["update_minutes"], dev["sleeps"]), (15, True))
        r = await self.ed.post("/api/devices", json={"kind": "crowpanel", "name": "Shed", "display": "crowpanel_579",
                                                     "update_minutes": "yes"})
        self.assertEqual(r.status, 400)
        r = await self.ed.post("/api/devices", json={"kind": "crowpanel", "name": "Shed", "display": "crowpanel_579"})
        self.assertEqual((await r.json())["device"]["timing"]["update_minutes"], 1, "always on by default")


class TestTrmnlAwakeTime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        kinds.WRONG_KEYS = kinds.WrongKeys()
        trmnl._PAIRING.clear()
        self._on = config.TRMNL
        config.TRMNL = True
        self.dev = devices.add("trmnl", "Desk", "trmnl_og")
        panel, editor = web.make_apps()
        self.lan = TestClient(TestServer(panel))
        self.ed = TestClient(TestServer(editor))
        await self.lan.start_server()
        await self.ed.start_server()
        await self.ed.post(f"/api/devices/{self.dev['id']}/pair")
        self.key = (await (await self.lan.get("/api/setup", headers=setup_headers())).json())["api_key"]
        await frames.refresh_frames(None)

    async def asyncTearDown(self):
        await self.lan.close()
        await self.ed.close()
        config.TRMNL = self._on
        trmnl._PAIRING.clear()
        support.use_test_data_dir()

    async def test_its_wake_time_header_becomes_the_editors_average(self):
        for ms in ("5000", "4000"):
            headers = {**display_headers(self.key), "Wake-Time": ms}
            self.assertEqual((await self.lan.get("/api/display", headers=headers)).status, 200)
        info = await (await self.ed.get(f"/api/devices/{self.dev['id']}/pair")).json()
        self.assertEqual(info["awake_s"], 4.5)


if __name__ == "__main__":
    unittest.main()
