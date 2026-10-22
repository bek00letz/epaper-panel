"""Rendering: one at a time, robust to bad fields, fits the panel, pushes only when it should.

From the audit of 2026-10-19 (findings 5, 8, 10, 15, 16).
"""
import asyncio
import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import config  # noqa: E402
import devices  # noqa: E402
import feeds  # noqa: E402
import frames  # noqa: E402
import runtime  # noqa: E402
import web  # noqa: E402
from layouts_store import load_layouts, sanitize_layouts, save_layouts  # noqa: E402
from render import epf, subitems  # noqa: E402
from sources import sports  # noqa: E402

PAGE_579 = 99 * 272        # bytes per 5.79" page


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config.DATA_DIR = support.temp_dir()
        runtime.forget_devices_except([])
        self.dev_id = devices.primary()["id"]
        self.spec = sanitize_layouts(load_layouts())
        self.spec["rotation"] = self.spec["rotation"][:2]
        save_layouts(self.spec)


class TestOneRenderAtATime(Base):
    async def test_the_last_saved_pages_win(self):
        async with aiohttp.ClientSession() as s:
            real, calls = frames.check_alerts, {"n": 0}

            async def slow_first(session, sp, st, *more):
                calls["n"] += 1
                if calls["n"] == 1:
                    await asyncio.sleep(0.3)
                return await real(session, sp, st, *more)
            frames.check_alerts = slow_first
            try:
                loop_render = asyncio.create_task(frames.refresh_frames(s))
                await asyncio.sleep(0.05)
                new = dict(self.spec, rotation=self.spec["rotation"][:1])
                save_layouts(new)
                await frames.refresh_frames(s)
                await loop_render
            finally:
                frames.check_alerts = real
        self.assertEqual([n for n in support.first_frames().names if n != config.SLEEP_PAGE], new["rotation"])


class TestBadFields(Base):
    async def test_a_null_number_does_not_stop_rendering(self):
        name = self.spec["rotation"][0]
        self.spec["pages"][name]["elements"].append({"type": "curve", "entity": "sensor.x", "hours": None})
        save_layouts(sanitize_layouts(self.spec))
        async with aiohttp.ClientSession() as s:
            f = (await frames.refresh_frames(s))[devices.primary()["id"]]
        self.assertIn(name, f.names)


class TestFitThePanel(unittest.TestCase):
    def test_everything_fits_when_there_is_room(self):
        self.assertEqual(frames.fit_counts([1, 3, 2], PAGE_579, 1 << 20), [1, 3, 2])

    def test_each_page_keeps_one_and_extras_are_shared_fairly(self):
        # Room for 8 pages besides the sleep screen.
        cap = epf.encoded_size(9, 5, PAGE_579)
        self.assertEqual(frames.fit_counts([6, 1, 5, 6], PAGE_579, cap), [3, 1, 2, 2])

    def test_pages_at_the_end_go_when_even_one_each_does_not_fit(self):
        cap = epf.encoded_size(3, 3, PAGE_579)
        self.assertEqual(frames.fit_counts([2, 2, 2, 2], PAGE_579, cap), [1, 1, 0, 0])

    def test_what_was_left_out_is_recorded(self):
        plans = [{"name": "sport", "want": 6}, {"name": "cat", "want": 1}]
        fit = frames.record_fit(plans, [2, 1], 1 << 20)
        self.assertEqual(fit["trimmed"], [{"page": "sport", "shown": 2, "of": 6, "items": "items"}])
        self.assertEqual((fit["pages_shown"], fit["pages_wanted"]), (3, 7))

    def test_what_was_left_out_is_said_in_the_pages_own_words(self):
        # "Showing 14 of 23 games" on its tile: never a Premier League match called a game.
        def plan(sub_type, *els, feed=None):
            return {"name": "p", "want": 9, "sub_type": sub_type, "elements": list(els), "feed_entity": feed}
        self.assertEqual(frames.items_word(plan("sports", {"type": "sports_match", "league": "basketball/nba"})), "games")
        self.assertEqual(frames.items_word(plan("sports", {"type": "sports_match", "league": "epl"})), "matches")
        self.assertEqual(frames.items_word(plan("flight", {"type": "flight_tracker"})), "planes")
        self.assertEqual(frames.items_word(plan("media", {"type": "now_playing"})), "players")
        with unittest.mock.patch.object(feeds, "load", lambda _: [{"type": "jellyfin", "name": "Watch"}]):
            self.assertEqual(frames.items_word(plan("feed", {"type": "text"}, feed="sensor.epaper_watch")), "titles")
            self.assertEqual(frames.items_word(plan("feed", {"type": "text"}, feed="sensor.epaper_news")), "items")


def _scores(league, team=""):
    return {"elements": [{"type": "sports_match", "league": league, "team": team}]}


TWO_MB = 2 * 1024 * 1024
PLAIN = {"elements": [{"type": "text", "value": "Hi"}]}


class TestBusyDay(unittest.TestCase):
    """The editor's line while setting up Scores: could the leagues' busiest day outgrow the panel?"""

    def test_what_a_page_can_have_at_once(self):
        self.assertEqual(subitems.busiest(_scores("basketball/nba")), 15)
        self.assertEqual(subitems.busiest(_scores("premier_league")), 10, "an alias, as a page may say it")
        self.assertEqual(subitems.busiest({"elements": [{"type": "sports_match", "league": "nba",
                                                         "entity": "sensor.team_tracker"}]}), 1, "a Team Tracker sensor is one game")
        self.assertEqual(subitems.busiest(_scores("soccer/xyz.9")), 1, "a league it doesn't know promises nothing")
        self.assertEqual(subitems.busiest({"elements": [{"type": "flight_tracker"}]}), 5)
        self.assertEqual(subitems.busiest({"elements": [{"type": "text", "entity": "sensor.epaper_watch"}]}), 5)
        self.assertEqual(subitems.busiest(PLAIN), 1)

    def test_three_leagues_can_outgrow_a_579(self):
        spec = {"pages": {"weather": PLAIN, "calendar": PLAIN, "pl": _scores("soccer/eng.1"),
                          "nba": _scores("basketball/nba"), "cfb": _scores("football/college-football")},
                "rotation": ["weather", "calendar", "pl", "nba", "cfb"]}
        got = frames.busy_day(spec, PAGE_579, TWO_MB)["scores"]
        # 76 pages fit besides the sleep screen; weather and the calendar take two.
        self.assertEqual(got, {"busiest": 105, "room": 74, "teams": False, "leagues": 3})

    def test_nothing_to_say_when_a_busy_day_fits(self):
        spec = {"pages": {"weather": PLAIN, "pl": _scores("soccer/eng.1", "Arsenal"), "nba": _scores("basketball/nba", "Celtics")},
                "rotation": ["weather", "pl", "nba"]}
        self.assertEqual(frames.busy_day(spec, PAGE_579, TWO_MB)["scores"], {"busiest": 25, "room": 25, "teams": True, "leagues": 2})

    def test_a_page_twice_counts_twice_and_alerts_not_at_all(self):
        spec = {"pages": {"nba": _scores("basketball/nba"), "goal": {**_scores("soccer/eng.1"), "tier": "alert"}},
                "rotation": ["nba", "nba", "goal", "gone"]}
        self.assertEqual(frames.busy_day(spec, PAGE_579, TWO_MB)["scores"]["busiest"], 30)

    def test_no_scores_page_no_line(self):
        self.assertIsNone(frames.busy_day({"pages": {"a": PLAIN}, "rotation": ["a"]}, PAGE_579, TWO_MB)["scores"])


class TestBusyDayForTheEditor(Base):
    async def test_only_an_always_on_panel_can_run_out(self):
        _, editor = web.make_apps()
        body = {"pages": {"cfb": _scores("football/college-football")}, "rotation": ["cfb"]}
        runtime.set_panel_capacity(self.dev_id, TWO_MB)
        async with TestClient(TestServer(editor)) as c:
            got = await (await c.post("/api/busy_day", json=body)).json()
            self.assertEqual(got["scores"], {"busiest": 80, "room": 76, "teams": False, "leagues": 1})
            devices.update(self.dev_id, update_minutes=10)       # it sleeps between updates: a page a wake
            self.addCleanup(devices.update, self.dev_id, update_minutes=None)
            self.assertIsNone((await (await c.post("/api/busy_day", json=body)).json())["scores"])

    async def test_what_was_left_out_reaches_the_editor_only_while_always_on(self):
        _, editor = web.make_apps()
        runtime.device(self.dev_id).fit = {"trimmed": [{"page": "nba", "shown": 14, "of": 23, "items": "games"}]}
        async with TestClient(TestServer(editor)) as c:
            got = await (await c.get("/api/status")).json()
            self.assertEqual(got["fit"]["trimmed"][0]["items"], "games")
            devices.update(self.dev_id, update_minutes=10)
            self.addCleanup(devices.update, self.dev_id, update_minutes=None)
            self.assertIsNone((await (await c.get("/api/status")).json())["fit"])


class TestPanelCapacity(Base):
    async def test_the_panel_reports_what_it_holds(self):
        _, _ = None, None
        panel, _ = web.make_apps()
        support.first_frames().epf_strip, support.first_frames().names = b"x", ["a"]
        async with TestClient(TestServer(panel)) as c:
            await c.get("/frames.epf?cap=2097152")
        self.assertEqual(runtime.panel_capacity(self.dev_id), 2097152)
        runtime.forget_devices_except([])
        self.assertEqual(runtime.panel_capacity(self.dev_id), 2097152, "remembered across a restart")

    async def test_non_ascii_token_is_refused_not_an_error(self):
        os.environ.pop("FRAME_TOKEN", None)
        config.FRAME_TOKEN = "abc"
        try:
            panel, _ = web.make_apps()
            support.first_frames().epf_strip, support.first_frames().names = b"x", ["a"]
            async with TestClient(TestServer(panel)) as c:
                r = await c.get("/frames.epf?token=%C3%A9")
            self.assertEqual(r.status, 401)
        finally:
            config.FRAME_TOKEN = ""


class TestPushPolicy(Base):
    async def test_pages_changing_shape_waits_for_the_panel(self):
        pushes = []

        async def fake_push(device_id, reason="update"):
            pushes.append(reason)
            return True
        real = frames.push_panel_update
        frames.push_panel_update = fake_push
        try:
            async with aiohttp.ClientSession() as s:
                await frames.refresh_frames(s)
                save_layouts(dict(self.spec, rotation=self.spec["rotation"][:1]))
                await frames.refresh_frames(s)
        finally:
            frames.push_panel_update = real
        self.assertEqual(pushes, [], "only alerts, quiet hours and people wake the panel early")


    async def test_a_new_sleep_screen_wakes_it_once(self):
        """06:00: the schedule ends but nobody's home, so it stays asleep with new words."""
        pushes = []

        async def fake_push(device_id, reason="update"):
            pushes.append(reason)
            return True
        reasons = iter([(True, "schedule (00:00–06:00)"), (True, "schedule (00:00–06:00)"),
                        (True, "away (person.me: not_home)"), (True, "away (person.me: not_home)"),
                        (True, "away (person.me: away)")])

        async def fake_quiet(session, spec, dev=None):
            return next(reasons)
        save_layouts(dict(self.spec, quiet_hours={"enabled": True, "start": "00:00", "end": "06:00"}))
        real_push, real_quiet = frames.push_panel_update, frames.evaluate_quiet_hours
        frames.push_panel_update, frames.evaluate_quiet_hours = fake_push, fake_quiet
        try:
            async with aiohttp.ClientSession() as s:
                for _ in range(5):
                    await frames.refresh_frames(s)
        finally:
            frames.push_panel_update, frames.evaluate_quiet_hours = real_push, real_quiet
        self.assertEqual(pushes, ["sleep screen changed"],
                         "one wake when the words change; none for the same words, however the reason is put")


class TestIdentities(unittest.TestCase):
    def test_a_page_listed_twice_has_its_own_items(self):
        _, sub_ids = subitems.compute_identities(["cat", "solar", "cat"], [["0"], ["0"], ["0"]])
        self.assertNotEqual(sub_ids[0], sub_ids[2])
        _, alone = subitems.compute_identities(["cat"], [["0"]])
        self.assertEqual(sub_ids[0], alone[0], "the first copy keeps the identity it always had")


class TestMatchOrder(unittest.TestCase):
    def test_your_team_then_live_then_upcoming_then_finished(self):
        ms = [{"home_team": "A", "away_team": "B", "status": "POST"},
              {"home_team": "C", "away_team": "D", "status": "PRE"},
              {"home_team": "E", "away_team": "F", "status": "IN"},
              {"home_team": "Arsenal", "away_team": "G", "status": "PRE"},
              {"home_team": "H", "away_team": "Lakers", "status": "POST"}]
        ms.sort(key=lambda m: sports.match_priority(m, "arsenal, lakers"))
        self.assertEqual([m["home_team"] for m in ms], ["Arsenal", "H", "E", "C", "A"])


class TestSourceIds(unittest.TestCase):
    def test_renaming_a_source_keeps_its_key(self):
        d = support.temp_dir()
        feeds.save(d, [{"type": "jellyfin", "name": "jelly", "base": "http://nas", "key": "K"}])
        stored = feeds.load(d)
        shown = feeds.mask_secrets(stored)
        renamed = [dict(shown[0], name="tv")]
        self.assertEqual(feeds.unmask_secrets(renamed, stored)[0]["key"], "K")


if __name__ == "__main__":
    unittest.main()
