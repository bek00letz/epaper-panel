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
import window  # noqa: E402
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


PAGE_750 = 100 * 480       # bytes per 7.5" page: frame files aren't compressed
XIAO_83 = 83 * 1024        # what the first Seeed XIAO 7.5" said it holds (0.23.0, its log)


class TestAPanelWithoutPsram(Base):
    """The Seeed XIAO 7.5" holds about one page (0.23.0: it said 83 KB, the add-on fitted 0 of 17
    pages and failed every render, so it showed nothing). One rule decides what fits, in bytes."""

    def test_one_page_without_the_sleep_screen_when_only_one_fits(self):
        got = frames.fit([1] * 17, PAGE_750, XIAO_83)
        self.assertEqual(got.counts, [1] + [0] * 16, "the first page of the rotation")
        self.assertFalse(got.sleep_screen, "no room for it too: the panel stays awake without one")
        self.assertLessEqual(epf.encoded_size(1, 1, PAGE_750), XIAO_83)

    def test_the_sleep_screen_comes_back_when_both_fit(self):
        got = frames.fit([1] * 17, PAGE_750, epf.encoded_size(2, 2, PAGE_750))
        self.assertEqual(got.counts, [1] + [0] * 16)
        self.assertTrue(got.sleep_screen)

    def test_nothing_only_when_not_even_one_page_fits(self):
        got = frames.fit([1] * 3, PAGE_750, epf.encoded_size(1, 1, PAGE_750) - 1)
        self.assertEqual(got.counts, [0, 0, 0])
        self.assertIn("one page needs 47 KB", frames.no_room_words("Hall", 40 * 1024, epf.encoded_size(1, 1, PAGE_750)))

    def test_the_rule_is_the_panels(self):
        # The firmware counts a frame file as epf.encoded_size does (epf_core.h frame_file_size):
        # the same four sizes, and a real file is exactly that long.
        core = (Path(__file__).resolve().parents[1] / "components" / "epf" / "epf_core.h").read_text()
        for name in ("HEADER_SIZE", "CAT_RECORD_SIZE", "PAGE_RECORD_SIZE", "CRC_SIZE"):
            self.assertIn(f"constexpr size_t {name} = {getattr(epf, name)};", core, name)
        self.assertIn("return HEADER_SIZE + pages * (CAT_RECORD_SIZE + PAGE_RECORD_SIZE + page_bytes) + CRC_SIZE;", core)

    async def render_xiao(self, capacity, **view):
        dev = devices.add("crowpanel", "Hall", "seeed_xiao_750", copy_from=self.dev_id, **view)
        runtime.set_panel_capacity(dev["id"], capacity)
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        return dev, runtime.device(dev["id"]).frames

    async def test_always_on_with_83_kb_shows_a_page(self):
        dev, f = await self.render_xiao(XIAO_83)
        self.assertIsNone(f.error)
        self.assertIsNone(f.no_room)
        self.assertEqual(f.names, [self.spec["rotation"][0]], "its first page, no sleep screen")
        self.assertLessEqual(len(f.epf_strip), XIAO_83, "what it gets fits what it holds")
        self.assertEqual(epf.decode_epf(f.epf_strip).header.page_count, 1)

    async def test_in_quiet_hours_its_one_page_is_the_sleep_screen(self):
        async def quiet(session, spec, dev=None):
            return True, "schedule"
        with unittest.mock.patch.object(frames, "evaluate_quiet_hours", quiet):
            dev, f = await self.render_xiao(XIAO_83)
        self.assertEqual(f.names, [config.SLEEP_PAGE])
        flags = epf.decode_epf(f.epf_strip).categories[0].flags
        self.assertEqual(flags, epf.CAT_FLAG_SLEEP | epf.CAT_FLAG_SLEEP_AUTO, "so it goes to sleep by itself")

    async def test_a_sleeping_one_gets_a_file_that_fits_on_any_wake(self):
        # A press or a start gets the whole file, not one picked page: it must fit too.
        dev, f = await self.render_xiao(XIAO_83, update_minutes=15)
        self.assertIsNone(f.error)
        self.assertLessEqual(len(f.epf_strip), XIAO_83)

    async def test_no_room_is_said_plainly_not_as_a_failed_render(self):
        dev, f = await self.render_xiao(32 * 1024)
        self.assertIsNone(f.error, "not a failed render")
        self.assertEqual(f.no_room, "Hall has room for 32 KB of pages, and one page needs 47 KB, "
                                    "so it keeps showing what it has.")
        _, editor = web.make_apps()
        async with TestClient(TestServer(editor)) as c:
            got = await (await c.get("/api/status", params={"device": dev["id"]})).json()
        self.assertEqual(got["no_room"], f.no_room)

    async def test_inflating_it_holds_the_whole_rotation(self):
        # Firmware that inflates (deflate=1, 0.24) gets each page deflated, weighed by the same
        # rule: every page and the sleep screen in 83 KB, where only one page fitted as they are.
        dev, _ = await self.render_xiao(XIAO_83)
        devices.set_state(dev["id"], inflates=True)
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        f = runtime.device(dev["id"]).frames
        self.assertIsNone(f.error)
        self.assertEqual(f.names, [config.SLEEP_PAGE] + self.spec["rotation"])
        got = epf.decode_epf(f.epf_strip)
        self.assertTrue(got.header.flags & epf.FLAG_DEFLATE)
        self.assertLessEqual(len(f.epf_strip), XIAO_83)
        self.assertEqual(len(f.epf_strip), epf.file_size(got.header.cat_count, [n for _, n in got.spans]))

    async def test_a_tight_fit_is_weighed_not_guessed(self):
        # Room for the sleep screen and one deflated page, by the file's own size.
        dev, _ = await self.render_xiao(XIAO_83)
        devices.set_state(dev["id"], inflates=True)
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        whole = epf.decode_epf(runtime.device(dev["id"]).frames.epf_strip)
        two = epf.file_size(2, [n for _, n in whole.spans[:2]])
        runtime.set_panel_capacity(dev["id"], max(two, runtime.MIN_CAPACITY))
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        f = runtime.device(dev["id"]).frames
        self.assertEqual(f.names[0], config.SLEEP_PAGE)
        self.assertLessEqual(len(f.epf_strip), max(two, runtime.MIN_CAPACITY))

    def test_one_rule_whatever_the_pictures_weigh(self):
        async def page_sized(i, k):
            return PAGE_750
        for cap in (XIAO_83, 2 * 1024 * 1024, epf.encoded_size(3, 3, PAGE_750)):
            weighed = asyncio.run(frames.fit_weighed([2, 1, 3, 1], cap, PAGE_750, page_sized))
            plain = frames.fit([2, 1, 3, 1], PAGE_750, cap)
            self.assertEqual((weighed.counts, weighed.sleep_screen), (plain.counts, plain.sleep_screen), cap)

    async def test_its_firmware_says_whether_it_inflates(self):
        dev, _ = await self.render_xiao(XIAO_83)
        panel, _ = web.make_apps()
        q = {"token": devices.key_of(devices.get(dev["id"])), "cap": str(XIAO_83)}
        async with TestClient(TestServer(panel)) as c:
            await c.get("/frames.epf", params={**q, "deflate": "1"})
            self.assertTrue(devices.state(dev["id"]).get("inflates"))
            await c.get("/frames.epf", params=q)                  # the way back: as they are again
            self.assertFalse(devices.state(dev["id"]).get("inflates"))

    async def test_never_more_than_it_holds(self):
        # Drawn before it said what it holds: refused, and its report sets off a render that fits.
        dev, _ = await self.render_xiao(1 << 20)
        runtime.device(dev["id"]).frames.epf_strip = bytes(200 * 1024)
        panel, _ = web.make_apps()
        q = {"token": devices.key_of(devices.get(dev["id"])), "cap": str(XIAO_83)}
        async with TestClient(TestServer(panel)) as c:
            r = await c.get("/frames.epf", params=q)
        self.assertEqual(r.status, 503)
        self.assertEqual(runtime.panel_capacity(dev["id"]), XIAO_83)


class TestMovingWindow(Base):
    """Firmware that says window=1 (0.24) holds the part of its rotation around the page it shows
    when the whole rotation doesn't fit, and is handed the rest as it goes (window.py; the user's
    call, 30 Oct). Older firmware keeps today's trimming."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.spec = sanitize_layouts(load_layouts())
        self.spec["rotation"] = self.spec["rotation"][:2] * 3          # six pages of one item
        save_layouts(self.spec)

    async def render(self, capacity, window=True, inflates=False):
        dev = devices.add("crowpanel", "Hall", "seeed_xiao_750", copy_from=self.dev_id)
        devices.set_state(dev["id"], window=window, inflates=inflates)
        runtime.set_panel_capacity(dev["id"], capacity)
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        return dev, runtime.device(dev["id"]).frames

    THREE = epf.encoded_size(4, 4, PAGE_750)        # the sleep screen and three pages as they are

    async def test_everything_fits_so_the_whole_rotation_as_before(self):
        dev, f = await self.render(1 << 20)
        self.assertIsNone(f.window, "no window while the rotation fits")
        got = epf.decode_epf(f.epf_strip)
        self.assertEqual(f.names, [config.SLEEP_PAGE] + self.spec["rotation"])
        self.assertTrue(all(c.place == 0 and not c.flags & epf.CAT_FLAG_AT for c in got.categories),
                        "the file a panel always had: no places, nothing for the firmware to move")
        runtime.device(dev["id"]).frames = runtime.Frames()
        devices.set_state(dev["id"], window=False)
        async with aiohttp.ClientSession() as s:
            await frames.refresh_frames(s)
        old = epf.decode_epf(runtime.device(dev["id"]).frames.epf_strip)
        self.assertEqual([(c.cat_id, c.page_count, c.flags) for c in old.categories],
                         [(c.cat_id, c.page_count, c.flags) for c in got.categories], "the same as older firmware's")
        _, editor = web.make_apps()
        async with TestClient(TestServer(editor)) as c:
            status = await (await c.get("/api/status", params={"device": dev["id"]})).json()
        self.assertIsNone(status["window"])

    async def test_more_than_fits_moves_a_window(self):
        dev, f = await self.render(self.THREE)
        self.assertIsNotNone(f.window)
        self.assertIsNone(f.error)
        self.assertEqual(f.names, [config.SLEEP_PAGE] + self.spec["rotation"], "every page, none left out")
        self.assertLessEqual(len(f.epf_strip), self.THREE)
        for at in range(6):
            body, _ = f.window.file(at, 0)
            self.assertLessEqual(len(body), self.THREE, at)
            got = epf.decode_epf(body)
            pages = [c for c in got.categories if not c.flags & epf.CAT_FLAG_SLEEP]
            self.assertEqual([c.rot_pos for c in pages], [(at - 1) % 6, at, (at + 1) % 6],
                             "the one before, the one it shows, the next, in rotation order")
            self.assertEqual({c.rot_len for c in pages}, {6})
            self.assertEqual([bool(c.flags & epf.CAT_FLAG_AT) for c in pages], [False, True, False])
            self.assertTrue(got.categories[0].flags & epf.CAT_FLAG_SLEEP, "the sleep screen still goes first")
        self.assertEqual(runtime.device(dev["id"]).fit["window"], {"holds": 3, "of": 6})
        self.assertEqual(runtime.device(dev["id"]).fit["trimmed"], [], "nothing left out")

    async def test_a_scroll_past_the_window_is_one_download_with_the_window_around_it(self):
        dev, f = await self.render(self.THREE)
        panel, _ = web.make_apps()
        q = {"token": devices.key_of(devices.get(dev["id"])), "cap": str(self.THREE), "window": "1"}

        async def never(*a, **k):
            raise AssertionError("a download drew a page")
        with unittest.mock.patch.object(frames, "draw_category", never):
            async with TestClient(TestServer(panel)) as c:
                r = await c.get("/frames.epf", params={**q, "at": "4", "item": "0"})
                body = await r.read()
                self.assertEqual(r.status, 200)
                again = await c.get("/frames.epf", params={**q, "at": "4", "item": "0"},
                                    headers={"If-None-Match": r.headers["ETag"]})
                self.assertEqual(again.status, 304, "the same place, the same window")
                shown = await (await c.get("/frames.epf", params={**q, "page": "1", "at": "4"})).read()
        got = epf.decode_epf(body)
        at = [c for c in got.categories if c.flags & epf.CAT_FLAG_AT]
        self.assertEqual([c.rot_pos for c in at], [4], "the page it asked for")
        self.assertIn(3, [c.rot_pos for c in got.categories if c.place], "with the one before, to scroll back")
        self.assertEqual([c.rot_pos for c in epf.decode_epf(shown).categories if c.flags & epf.CAT_FLAG_AT], [1],
                         "Home Assistant's show_page counts every page of the rotation")

    def window(self, wants, room, sleep=True):
        page = 1000
        pages = [[bytes([i, k]) * (page // 2) for k in range(n)] for i, n in enumerate(wants)]
        return window.Window(pages, [100 + i for i in range(len(wants))],
                             [[1000 * (i + 1) + k for k in range(n)] for i, n in enumerate(wants)], [0] * len(wants),
                             epf.file_size(room + sleep, [page] * (room + sleep)),
                             window.Sleep(b"\xff" * page, 9, 90, epf.CAT_FLAG_SLEEP) if sleep else None,
                             dict(display_model="crowpanel_290", width=page * 8, height=1))

    def test_a_page_too_big_to_hold_is_a_run_of_its_items(self):
        w = self.window([1, 9, 1], 4)
        got = epf.decode_epf(w.file(1, 3)[0])
        self.assertEqual(len(got.categories), 2, "the sleep screen and the run, nothing else")
        run = got.categories[1]
        self.assertEqual(run.flags, epf.CAT_FLAG_AT | epf.CAT_FLAG_PART)
        self.assertEqual([p.sub_index for p in got.pages[1:]], [3, 4, 5, 6], "from the item it shows next")
        self.assertEqual([p.sub_id for p in got.pages[1:]], [2003, 2004, 2005, 2006], "each item its own identity")
        tail = epf.decode_epf(w.file(1, 7)[0])
        self.assertEqual([p.sub_index for p in tail.pages[1:]], [7, 8, 0, 1], "the last ones, then round to the first")
        whole = epf.decode_epf(w.file(0, 0)[0])
        self.assertEqual([c.rot_pos for c in whole.categories[1:]], [2, 0], "a page too big is left out of a "
                         "window ahead, and the window stops there")

    def test_nothing_is_ever_dropped(self):
        for wants, room in (([1] * 9, 4), ([1, 3, 1, 9, 1, 2], 5), ([2, 2], 3), ([5], 2)):
            w = self.window(wants, room)
            for at, n in enumerate(wants):
                for item in range(n):
                    got = epf.decode_epf(w.file(at, item)[0])
                    held = {(c.rot_pos, p.sub_index) for c in got.categories if c.place
                            for p in got.pages[c.offset_page:c.offset_page + c.page_count]}
                    self.assertIn((at, item), held, f"{wants} at {at} item {item}: the page it asked for")
                    self.assertLessEqual(len(w.file(at, item)[0]), w.capacity)

    def test_the_window_is_the_fit_rule_in_the_files_own_bytes(self):
        w = self.window([1, 2, 1, 3, 1], 4)
        for at in range(5):
            body = w.file(at, 0)[0]
            got = epf.decode_epf(body)
            self.assertEqual(len(body), epf.file_size(got.header.cat_count, [n for _, n in got.spans]))
            self.assertLessEqual(len(body), w.capacity)
        everything = frames.fit_window([1, 2, 1], 0, 0, 1 << 20, 10, lambda i, k: 10)
        self.assertEqual(everything.counts, frames.fit([1, 2, 1], 10, 1 << 20).counts, "room for all: all")
        self.assertEqual(frames.window_order(5, 0), [0, 1, 4, 2, 3])

    async def test_older_firmware_still_gets_trimming(self):
        dev, f = await self.render(self.THREE, window=False)
        self.assertIsNone(f.window)
        self.assertEqual(f.names, [config.SLEEP_PAGE] + self.spec["rotation"][:3], "the last pages left out, as before")
        self.assertTrue(all(c.place == 0 for c in epf.decode_epf(f.epf_strip).categories))
        self.assertNotIn("window", runtime.device(dev["id"]).fit)

    async def test_its_firmware_says_whether_it_moves_a_window(self):
        dev, _ = await self.render(self.THREE, window=False)
        panel, _ = web.make_apps()
        q = {"token": devices.key_of(devices.get(dev["id"])), "cap": str(self.THREE)}
        async with TestClient(TestServer(panel)) as c:
            await c.get("/frames.epf", params={**q, "window": "1"})
            self.assertTrue(devices.state(dev["id"]).get("window"))
            await c.get("/frames.epf", params=q)                  # the way back: trimmed again
            self.assertFalse(devices.state(dev["id"]).get("window"))

    async def test_the_status_says_it_calmly(self):
        dev, f = await self.render(self.THREE)
        _, editor = web.make_apps()
        async with TestClient(TestServer(editor)) as c:
            got = await (await c.get("/api/status", params={"device": dev["id"]})).json()
        self.assertEqual(got["window"], {"holds": 3, "of": 6})
        self.assertIsNone(got["error"])
        self.assertIsNone(got["no_room"])
        self.assertIsNone(got["fit"], "nothing left out, so nothing for a page's tile to say")
        js = (Path(__file__).resolve().parents[1] / "addon" / "app" / "web" / "app" / "sheets.js").read_text()
        self.assertIn("Holds ${s.window.holds} of ${s.window.of} pages; the rest arrive as it goes.", js)


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
