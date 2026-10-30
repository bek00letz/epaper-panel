"""Pages built on what Home Assistant already has: the year grid, commute times, departures and the
mail list. What each reads and how (sources/hass_read.py, yeargrid.py, commute.py, departures.py,
mail.py), how each fits its box (render/yeargrid.py, render/listing.py), and the editor's side."""
import asyncio
import json
import os
import shutil
import unittest
import unittest.mock
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import support

import examples
import ha_events
import runtime
import widgets
from render import arrange, commute as draw_commute, departures as draw_departures, layout, listing, theme as T, yeargrid
from render.words import speaking
from sources import commute, departures, hass_read, mail, yeargrid as year_days
from test_widgets import BASE, SIZES, Sizes, ink, render

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 10, 30, 8, 10, tzinfo=TZ)
WEB = support.APP / "web" / "app"


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- every page at every size

class TestYearGridSizes(Sizes, unittest.TestCase):
    element = {"type": "year_grid", "source": "statistic", "x": 24, "y": 14, "w": 744, "h": 208}
    value = examples.year_grid("statistic", NOW.date())


class TestYearGridGitHubSizes(Sizes, unittest.TestCase):
    element = {"type": "year_grid", "source": "github", "x": 24, "y": 14, "w": 744, "h": 208}
    value = examples.year_grid("github", NOW.date())


class TestCommuteSizes(Sizes, unittest.TestCase):
    element = {"type": "commute", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {**examples.commute(NOW), "tz": "Europe/Bucharest"}


class TestOneRouteSizes(Sizes, unittest.TestCase):
    element = {"type": "commute", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"routes": examples.commute(NOW)["routes"][:1], "tz": "Europe/Bucharest"}


class TestDeparturesSizes(Sizes, unittest.TestCase):
    element = {"type": "departures", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {**examples.departures(datetime.now().astimezone()), "tz": None}


class TestMailSizes(Sizes, unittest.TestCase):
    element = {"type": "mail_list", "x": 40, "y": 14, "w": 712, "h": 220}
    value = {**examples.mail(), "tz": None}


class TestWhatTheyShowBeforeAndInstead(unittest.TestCase):
    """Not read yet: nothing (no made-up grid, no empty heading flashing). Something missing: what to
    do, in words, inside the box."""

    CASES = [("year_grid", {"days": [], "missing": "user", "user": "nobody"}),
             ("year_grid", {"days": [], "missing": "statistics", "name": "Steps"}),
             ("year_grid", {"days": [], "missing": "choose"}),
             ("year_grid", {"days": [["2026-10-29", None], ["2026-10-30", None]]}),
             ("commute", {"routes": [], "missing": "integration"}),
             ("commute", {"routes": [{"name": "Work", "minutes": None, "state": "unavailable"}]}),
             ("departures", {"departures": [], "missing": "integration"}),
             ("departures", {"departures": [], "missing": "unavailable"}),
             ("departures", {"departures": [], "tz": None}),
             ("mail_list", {"messages": [], "missing": "integration"}),
             ("mail_list", {"messages": [], "missing": "unavailable", "name": "Work mail"}),
             ("mail_list", {"messages": [], "count": 0, "more": 0}),
             ("mail_list", {"messages": [], "count": 4, "more": 4})]

    def test_nothing_before_it_is_read(self):
        for t in ("year_grid", "commute", "departures", "mail_list"):
            with self.subTest(t):
                self.assertEqual(ink(render({"type": t, "x": 24, "y": 14, "w": 744, "h": 208}, None)), 0)

    def test_each_problem_says_something_inside_its_box(self):
        for t, value in self.CASES:
            for disp, orient in SIZES:
                el = {"type": t, "x": 24, "y": 14, "w": 744, "h": 208}
                target = arrange.canvas_key(*T.canvas_dims(orient, disp))
                box = {**el, **arrange.auto_box(el, BASE, target)}
                with self.subTest(t=t, value=value, display=disp, orient=orient):
                    img = render(el, value, disp, orient)
                    self.assertGreater(ink(img), 100)
                    inside = ink(img, (box["x"], box["y"], box["x"] + box["w"] + 1, box["y"] + box["h"] + 1))
                    self.assertEqual(ink(img) - inside, 0)


# ---------------------------------------------------------------- the year grid

class TestYearGridDays(unittest.TestCase):
    def test_quartiles_not_the_busiest_day_set_the_sizes(self):
        cuts = yeargrid.thresholds([0, 1, 2, 3, 4, 100])
        self.assertEqual(yeargrid.level(0, cuts), 0)
        self.assertEqual(yeargrid.level(None, cuts), 0)
        self.assertEqual(yeargrid.level(1, cuts), 1)
        self.assertEqual(yeargrid.level(3.5, cuts), 3)
        self.assertEqual(yeargrid.level(100, cuts), 4)
        self.assertGreaterEqual(yeargrid.level(4, cuts), 3, "one huge day doesn't shrink the rest to dots")

    def test_streaks_total_busiest_and_average(self):
        today = date(2026, 10, 30)
        days = [(today - timedelta(days=k), v) for k, v in enumerate([0, 2, 3, 0, 1, 1, 1, 1, None, 5])][::-1]
        s = yeargrid.summary(days, today)
        self.assertEqual(s.total, 14)
        self.assertEqual(s.current, 2, "today has nothing yet: the run ends yesterday")
        self.assertEqual(s.longest, 4)
        self.assertEqual(s.busiest, (today - timedelta(days=9), 5))
        self.assertAlmostEqual(s.average, 14 / 9)
        self.assertEqual(yeargrid.summary(days[:-1] + [(today, 1)], today).current, 3, "today counts once it has something")

    def test_a_day_nothing_is_known_about_breaks_a_run(self):
        today = date(2026, 10, 30)
        days = [(today - timedelta(days=2), 1), (today - timedelta(days=1), None), (today, 1)]
        self.assertEqual(yeargrid.summary(days, today).longest, 1)

    def test_github_levels_without_counts_leave_the_totals_out(self):
        data = {"days": [["2026-10-30", 2]], "what": "github", "levels_only": True}
        self.assertEqual(yeargrid.facts(yeargrid.days_of(data), data, date(2026, 10, 30), date(2026, 1, 1)), [])

    def test_a_count_is_its_number_and_a_reading_has_its_unit(self):
        self.assertEqual(yeargrid.amount(1204, {"what": "github"}), "1,204")
        self.assertEqual(yeargrid.amount(12.46, {"unit": "kWh"}), "12.5 kWh")
        self.assertEqual(yeargrid.amount(4666, {"unit": "kWh"}), "4,666 kWh")
        with speaking("de"):
            self.assertEqual(yeargrid.amount(4666, {"unit": "kWh"}), "4.666 kWh")


class TestYearGridFits(unittest.TestCase):
    def box(self, disp, orient=0):
        cw, ch = T.canvas_dims(orient, disp)
        return cw - 16, ch - T.band_height(ch) - 16

    def test_a_year_on_every_screen_large_enough_to_see(self):
        for disp, orient in SIZES:
            w, h = self.box(disp, orient)
            p = yeargrid.plan(w, h, 53, (120, 60))
            with self.subTest(display=disp, orient=orient):
                self.assertGreaterEqual(p.pitch, yeargrid.MIN_PITCH)
                cols = -(-p.weeks // p.bands)
                self.assertLessEqual(cols * p.pitch, p.grid[2])
                self.assertLessEqual(7 * p.bands * p.pitch + p.bands * p.labels, p.grid[3])

    def test_a_tall_screen_wraps_the_weeks_rather_than_leave_it_empty(self):
        w, h = self.box("trmnl_og")
        p = yeargrid.plan(w, h, 53, (0, 0))
        self.assertEqual(p.weeks, 53)
        self.assertGreater(p.bands, 1)
        self.assertGreaterEqual(p.pitch, 20)

    def test_the_totals_stay_while_enough_weeks_fit_beside_them(self):
        w, h = self.box("crowpanel_290")
        with_totals = yeargrid.plan(w, h, 53, (110, 0))
        self.assertIsNotNone(with_totals.facts)
        self.assertGreaterEqual(with_totals.weeks, yeargrid.FEWEST_WEEKS)
        self.assertIsNone(yeargrid.plan(w, h, 53, (w - 20, 0)).facts, "no room: they give way to the grid")

    def test_a_shorter_span_is_larger(self):
        w, h = self.box("crowpanel_579")
        self.assertGreater(yeargrid.plan(w, h, 13, (200, 60)).pitch, yeargrid.plan(w, h, 53, (200, 60)).pitch)

    def test_more_is_a_larger_square(self):
        self.assertEqual(list(yeargrid.LEVELS), sorted(set(yeargrid.LEVELS)))
        cuts = yeargrid.thresholds(range(1, 41))
        levels = [yeargrid.level(v, cuts) for v in range(0, 45)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual((levels[0], levels[-1]), (0, 4))


GITHUB = """<table><tbody><tr>
<td tabindex="0" data-ix="0" style="width: 10px" data-date="2026-10-28" id="contribution-day-component-0-0" data-level="0" class="ContributionCalendar-day"></td>
<td tabindex="0" data-ix="1" data-date="2026-10-29" id="contribution-day-component-1-0" data-level="2" class="ContributionCalendar-day"></td>
<td tabindex="0" data-ix="2" data-date="2026-10-30" id="contribution-day-component-2-0" data-level="4" class="ContributionCalendar-day"></td>
</tr></tbody></table>
<tool-tip id="t1" for="contribution-day-component-0-0" class="sr-only">No contributions on October 28th.</tool-tip>
<tool-tip id="t2" for="contribution-day-component-1-0" class="sr-only">1 contribution on October 29th.</tool-tip>
<tool-tip id="t3" for="contribution-day-component-2-0" class="sr-only">1,204 contributions on October 30th.</tool-tip>"""


class TestGitHub(unittest.TestCase):
    def test_its_calendar_as_days(self):
        got = year_days.read_github(GITHUB)
        self.assertEqual(got["days"], [["2026-10-28", 0], ["2026-10-29", 1], ["2026-10-30", 1204]])
        self.assertEqual((got["today"], got["what"]), ("2026-10-30", "github"))
        self.assertNotIn("levels_only", got)

    def test_without_its_words_the_levels_still_draw(self):
        got = year_days.read_github(GITHUB.split("<tool-tip")[0])
        self.assertEqual([v for _, v in got["days"]], [0, 2, 4])
        self.assertTrue(got["levels_only"])

    def test_anything_else_is_not_a_calendar(self):
        with self.assertRaises(ValueError):
            year_days.read_github("<html>Rate limited</html>")

    def test_a_username_as_github_allows_them(self):
        self.assertEqual(year_days.clean_user(" @octo-cat "), "octo-cat")
        for bad in ("-x", "a--b", "a/b", "x" * 40, "../etc", "a b", ""):
            self.assertEqual(year_days.clean_user(bad), "", bad)

    def test_github_is_asked_a_few_times_a_day_at_most(self):
        self.assertGreaterEqual(year_days.fetch_github.interval, 4 * 3600)

    def test_its_address_is_the_registrys(self):
        import services
        self.assertEqual(services.get("github").addresses[0].original, "https://github.com/users")

    def test_no_such_user_and_a_real_one(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        import services

        async def page(request):
            if request.match_info["user"] != "octocat":
                return web.Response(status=404)
            return web.Response(text=GITHUB, content_type="text/html")

        async def go():
            app = web.Application()
            app.router.add_get("/users/{user}/contributions", page)
            server = TestServer(app)
            await server.start_server()
            try:
                import aiohttp
                async with aiohttp.ClientSession() as s:
                    with unittest.mock.patch.object(services, "url", lambda sid, key="main": str(server.make_url("/users"))):
                        return (await year_days.fetch_github.direct(s, "octocat"),
                                await year_days.fetch_github.direct(s, "nobody"))
            finally:
                await server.close()
        found, missing = run(go())
        self.assertEqual(found["days"][-1], ["2026-10-30", 1204])
        self.assertEqual(missing, {"days": [], "missing": "user", "user": "nobody"})


class FakeHass:
    def __init__(self, meta=None, rows=None):
        self.meta, self.rows, self.asked = meta or {}, rows or {}, []

    async def ws(self, payload, timeout=10):
        self.asked.append(payload)
        if payload["type"] == "recorder/get_statistics_metadata":
            return [self.meta[i] for i in payload["statistic_ids"] if i in self.meta]
        if payload["type"] == "recorder/statistics_during_period":
            return {k: v for k, v in self.rows.items() if k in payload["statistic_ids"]}
        raise AssertionError(payload)


class TestStatistics(unittest.TestCase):
    def test_a_counter_is_each_days_change_anything_else_its_highest(self):
        self.assertEqual(year_days.how_for({"has_sum": True}), "change")
        self.assertEqual(year_days.how_for({"has_sum": False, "mean_type": 1}), "max")
        self.assertEqual(year_days.how_for({"has_sum": True}, "mean"), "mean")

    def test_rows_become_every_day_none_where_nothing_is_known(self):
        ms = lambda d: int(datetime(2026, 10, d, tzinfo=TZ).timestamp() * 1000)     # noqa: E731
        days = year_days.days_from_rows([{"start": ms(28), "change": 3.21}, {"start": ms(30), "change": 0}], "change",
                                        date(2026, 10, 30), TZ, days=4)
        self.assertEqual(days, [["2026-10-27", None], ["2026-10-28", 3.21], ["2026-10-29", None], ["2026-10-30", 0.0]])

    def test_a_sensor_without_statistics_says_so(self):
        hass = FakeHass()
        with unittest.mock.patch.object(year_days, "HA_TOKEN", "t"), unittest.mock.patch.object(runtime, "HASS", hass), \
                unittest.mock.patch.object(hass_read, "states_of", unittest.mock.AsyncMock(return_value=[{"name": "Steps"}])), \
                unittest.mock.patch.object(hass_read, "home_now", unittest.mock.AsyncMock(return_value=NOW)):
            got = run(year_days.fetch_statistic.direct(None, "sensor.steps"))
        self.assertEqual(got["missing"], "statistics")
        self.assertEqual(got["name"], "Steps")

    def test_a_year_of_days_in_home_assistants_zone(self):
        start = int(datetime(2026, 10, 30, tzinfo=TZ).timestamp() * 1000)
        hass = FakeHass({"sensor.solar": {"statistic_id": "sensor.solar", "has_sum": True, "statistics_unit_of_measurement": "kWh"}},
                        {"sensor.solar": [{"start": start, "change": 12.5}]})
        with unittest.mock.patch.object(year_days, "HA_TOKEN", "t"), unittest.mock.patch.object(runtime, "HASS", hass), \
                unittest.mock.patch.object(hass_read, "home_now", unittest.mock.AsyncMock(return_value=NOW)):
            got = run(year_days.fetch_statistic.direct(None, "sensor.solar"))
        asked = hass.asked[-1]
        self.assertEqual((asked["period"], asked["types"]), ("day", ["change"]))
        self.assertEqual(len(got["days"]), year_days.DAYS)
        self.assertEqual(got["days"][-1], ["2026-10-30", 12.5])
        self.assertEqual(got["unit"], "kWh")


# ---------------------------------------------------------------- commute

class TestCommute(unittest.TestCase):
    def test_minutes_in_any_unit_the_sensor_shows(self):
        self.assertEqual(commute.minutes("32", "min"), 32.0)
        self.assertEqual(commute.minutes("0.5", "h"), 30.0)
        self.assertIsNone(commute.minutes("unavailable", "min"))

    def test_routes_from_their_sensors(self):
        rows = [{"entity": "sensor.work", "state": "31.4", "name": "Work", "attributes": {"route": "A1; DN1", "unit_of_measurement": "min"}},
                {"entity": "sensor.gym", "state": "unavailable", "name": "Gym", "attributes": {}},
                {"entity": "sensor.gone", "state": None, "name": "", "attributes": {}}]
        got = commute.routes_from(rows)
        self.assertEqual([(r["name"], r["minutes"], r["route"], r["state"]) for r in got],
                         [("Work", 31.4, "A1; DN1", "ok"), ("Gym", None, "", "unavailable"), ("gone", None, "", "missing")])

    def test_usual_is_this_hour_on_this_kind_of_day(self):
        def row(day, hour, mean):
            return {"start": datetime(2026, 10, day, hour, tzinfo=TZ).isoformat(), "mean": mean}
        rows = [row(26, 8, 20), row(27, 8, 24), row(28, 8, 22), row(24, 8, 12), row(25, 8, 14), row(27, 17, 40), row(28, 17, 44)]
        table = commute.usual_table(rows, TZ)
        self.assertEqual(commute.usual_at(table, datetime(2026, 10, 29, 8, 30, tzinfo=TZ)), 22, "a weekday: the weekdays' middle")
        self.assertEqual(commute.usual_at(table, datetime(2026, 10, 31, 8, 30, tzinfo=TZ)), 13, "a Saturday: the weekend's")
        self.assertEqual(commute.usual_at(table, datetime(2026, 11, 1, 17, 0, tzinfo=TZ)), 42, "no weekend yet: any day's")
        self.assertIsNone(commute.usual_at(table, datetime(2026, 10, 29, 3, 0, tzinfo=TZ)))

    def test_one_hour_once_is_not_a_usual(self):
        self.assertEqual(commute.usual_table([{"start": NOW.isoformat(), "mean": 30}], TZ), {})

    def test_against_the_usual(self):
        self.assertEqual(draw_commute.slower(26, 25), 0, "a minute's wobble is as usual")
        self.assertEqual(draw_commute.slower(34, 25), 9)
        self.assertEqual(draw_commute.slower(20, 30), -10)
        self.assertIsNone(draw_commute.slower(20, None))
        self.assertTrue(draw_commute.loud(34, 25))
        self.assertFalse(draw_commute.loud(64, 60), "four minutes on an hour isn't loud")
        self.assertEqual(draw_commute.compared(34, 25), "9 min slower")
        with speaking("de"):
            self.assertEqual(draw_commute.compared(20, 30), "10 Min. kürzer")

    def test_the_first_page_finds_your_travel_times(self):
        found = unittest.mock.AsyncMock(return_value=["sensor.to_work"])
        states = unittest.mock.AsyncMock(return_value=[{"entity": "sensor.to_work", "state": "30", "name": "Work", "attributes": {}}])
        with unittest.mock.patch.object(commute, "HA_TOKEN", "t"), unittest.mock.patch.object(hass_read, "found_by", found), \
                unittest.mock.patch.object(hass_read, "states_of", states), \
                unittest.mock.patch.object(hass_read, "home_now", unittest.mock.AsyncMock(return_value=NOW)), \
                unittest.mock.patch.object(commute, "fetch_usual", unittest.mock.AsyncMock(return_value={})):
            got = run(commute.fetch_routes.direct(None, ()))
        self.assertEqual(found.call_args.args[1], commute.INTEGRATIONS)
        self.assertIn("waze_travel_time", commute.INTEGRATIONS)
        self.assertEqual(got["routes"][0]["minutes"], 30.0)
        self.assertTrue(got["found"])

    def test_without_any_it_says_what_to_add(self):
        with unittest.mock.patch.object(commute, "HA_TOKEN", "t"), \
                unittest.mock.patch.object(hass_read, "found_by", unittest.mock.AsyncMock(return_value=[])), \
                unittest.mock.patch.object(hass_read, "home_now", unittest.mock.AsyncMock(return_value=NOW)):
            self.assertEqual(run(commute.fetch_routes.direct(None, ())), {"routes": [], "missing": "integration"})


# ---------------------------------------------------------------- departures

UPDATED = NOW.timestamp()


class TestDepartureShapes(unittest.TestCase):
    """Each integration's shape, read into one."""

    def read(self, attrs, state="unknown", keys=None):
        row = {"entity": "sensor.stop", "state": state, "name": "Stop", "attributes": attrs, "updated": UPDATED}
        return departures.merged([row], keys or departures.keys_of({}), NOW)

    def test_a_list_of_departures_in_minutes(self):
        # RMV, Rejseplanen: the state is the next one's minutes, and a list of the rest.
        got = self.read({"unit_of_measurement": "min", "line": "S1", "direction": "Airport",
                         "next_departures": [{"line": "S1", "direction": "Airport", "minutes": 4},
                                             {"line": "U4", "direction": "Old Town", "minutes": 11, "delay": 2}]}, state="4")
        self.assertEqual([(d["line"], d["destination"], d["delay"]) for d in got], [("S1", "Airport", 0), ("U4", "Old Town", 2)])
        self.assertEqual(datetime.fromisoformat(got[0]["at"]), NOW + timedelta(minutes=4))

    def test_a_timestamp_sensor_with_its_line(self):
        # HVV, Swiss public transport, NextBus: the state is when, the line and destination beside it.
        at = (NOW + timedelta(minutes=7)).isoformat()
        got = self.read({"device_class": "timestamp", "line": "12", "destination": "Riverside", "platform": "2",
                         "next": [{"line": "12", "direction": "Riverside", "departure": (NOW + timedelta(minutes=27)).isoformat()}]}, state=at)
        self.assertEqual([(d["line"], d["destination"], d["platform"]) for d in got], [("12", "Riverside", "2"), ("12", "Riverside", "")])

    def test_gtfs_words_with_spaces_and_times_of_day(self):
        got = self.read({"device_class": "timestamp", "Route Short Name": "40", "Destination Station Stop Name": "University",
                         "next_departures": ["08:40:00", "09:10:00"]}, state=(NOW + timedelta(minutes=10)).isoformat())
        self.assertEqual([(d["line"], d["destination"], d["at"][11:16]) for d in got],
                         [("40", "University", "08:20"), ("40", "University", "08:40"), ("40", "University", "09:10")])

    def test_a_time_of_day_already_past_is_tomorrows(self):
        got = departures.when("06:00", NOW)
        self.assertEqual(got.date(), NOW.date() + timedelta(days=1))
        self.assertEqual(departures.when("07:50", NOW).date(), NOW.date(), "a little late is still today")

    def test_seconds_since_1970_in_seconds_or_milliseconds(self):
        t = NOW + timedelta(minutes=3)
        self.assertEqual(departures.when(int(t.timestamp()), NOW), t)
        self.assertEqual(departures.when(int(t.timestamp() * 1000), NOW), t)

    def test_named_attributes_win_when_unusual(self):
        attrs = {"journeys": [{"wann": (NOW + timedelta(minutes=5)).isoformat(), "linie": "N3", "ziel": "Harbour"}]}
        keys = {"list": "journeys", "time": "wann", "line": "linie", "to": "ziel"}
        got = self.read(attrs, keys=keys)
        self.assertEqual([(d["line"], d["destination"]) for d in got], [("N3", "Harbour")])

    def test_gone_and_twice_said_are_left_out_soonest_first(self):
        soon = (NOW + timedelta(minutes=2)).isoformat()
        got = self.read({"device_class": "timestamp", "line": "12",
                         "departures": [{"line": "12", "destination": "Old Town", "time": soon},
                                        {"line": "7", "destination": "Zoo", "time": (NOW - timedelta(minutes=3)).isoformat()},
                                        {"line": "9", "destination": "Mall", "time": (NOW + timedelta(minutes=1)).isoformat()}]}, state=soon)
        self.assertEqual([d["line"] for d in got], ["9", "12"])
        self.assertEqual(got[1]["destination"], "Old Town", "the fuller of the two is kept")

    def test_soon_in_minutes_later_and_asleep_as_the_time(self):
        self.assertEqual(draw_departures.leaves(NOW + timedelta(seconds=20), NOW), "now")
        self.assertEqual(draw_departures.leaves(NOW + timedelta(minutes=4, seconds=30), NOW), "4 min")
        self.assertEqual(draw_departures.leaves(NOW + timedelta(minutes=75), NOW), "09:25")
        self.assertEqual(draw_departures.leaves(NOW + timedelta(minutes=4), NOW, asleep=True), "08:14")

    def test_a_board_on_a_sleeping_device_says_when_not_how_long(self):
        from render import clocktime
        self.assertIn("departures", clocktime.AGES)
        self.assertIn("mail_list", clocktime.AGES)


# ---------------------------------------------------------------- mail

class TestMail(unittest.TestCase):
    def setUp(self):
        support.fresh_data_dir()
        mail._heard = None

    def event(self, uid, subject, minutes_ago=0, entry="e1", sender="Ana Pop <ana@example.com>"):
        return {"entry_id": entry, "uid": str(uid), "sender": sender, "subject": subject, "text": "the whole message",
                "date": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "username": "me@example.com"}

    def test_only_who_what_and_when_are_kept_and_only_the_add_on_reads_them(self):
        mail.remember(self.event(1, "Dinner?"))
        stored = json.loads(mail._path().read_text())
        self.assertEqual(stored[0]["sender"], "Ana Pop")
        self.assertNotIn("text", stored[0])
        self.assertNotIn("username", json.dumps(stored))
        self.assertEqual(os.stat(mail._path()).st_mode & 0o777, 0o600)

    def test_newest_first_each_once_a_few_per_mailbox(self):
        for k in range(mail.KEEP + 5):
            mail.remember(self.event(k, f"Message {k}", minutes_ago=100 - k))
        mail.remember(self.event(3, "Message 3 again", minutes_ago=97))
        mail.remember(self.event(1, "Other mailbox", entry="e2"))
        heard = mail._load()
        self.assertEqual(sum(1 for m in heard if m["entry"] == "e1"), mail.KEEP)
        self.assertEqual(heard[0]["subject"], "Other mailbox")
        self.assertEqual([m["subject"] for m in heard if m["uid"] == "3" and m["entry"] == "e1"], [])

    def test_as_many_as_unread_the_rest_said_as_more(self):
        heard = [{"entry": "e1", "subject": f"m{k}"} for k in range(3)] + [{"entry": "e2", "subject": "x"}]
        self.assertEqual([m["subject"] for m in mail.shown(heard, "e1", 2, False)[0]], ["m0", "m1"])
        self.assertEqual(mail.shown(heard, "e1", 5, False)[1], 2, "two unread it never heard about")
        self.assertEqual(mail.shown(heard, "e1", 0, False), ([], 0))

    def test_it_listens_only_once_a_page_asks(self):
        self.assertNotIn(mail.EVENT, ha_events.listening())
        with unittest.mock.patch.object(mail, "HA_TOKEN", "t"), \
                unittest.mock.patch.object(hass_read, "found_by", unittest.mock.AsyncMock(return_value=[])):
            got = run(mail.fetch_mail.direct(None, ""))
        self.assertEqual(got, {"messages": [], "missing": "integration"})
        self.assertIn(mail.EVENT, ha_events.listening())

    def test_one_handler_failing_never_stops_the_others(self):
        heard = []
        ha_events.listen("test_event", lambda data: 1 / 0)
        ha_events.listen("test_event", heard.append)
        ha_events.dispatch({"event_type": "test_event", "data": {"x": 1}})
        self.assertEqual(heard, [{"x": 1}])

    def test_its_page_shows_while_there_is_unread_mail(self):
        gate = widgets.get("mail_list").gate
        self.assertTrue(gate.checks({"type": "mail_list"}))
        for count, want in ((3, True), (0, False)):
            with unittest.mock.patch.object(mail, "fetch_mail", unittest.mock.AsyncMock(return_value={"count": count})):
                self.assertIs(run(gate.check(None, {"type": "mail_list"}, None)), want)


# ---------------------------------------------------------------- one way of reading and fitting

class TestOneWayOfReading(unittest.TestCase):
    def test_ids_are_checked_before_any_template(self):
        self.assertEqual(hass_read.clean_ids(["sensor.a", "sensor.a", "x'); drop", "", "sensor.b"]), ["sensor.a", "sensor.b"])

    def test_found_by_asks_home_assistant_for_each_integration(self):
        seen = {}

        async def tpl(session, t):
            seen["t"] = t
            return '["sensor.x"]'
        with unittest.mock.patch.object(hass_read, "ha_template", tpl):
            self.assertEqual(run(hass_read.found_by(None, ("waze_travel_time", "bad name'"))), ["sensor.x"])
        self.assertIn("'waze_travel_time'", seen["t"])
        self.assertNotIn("bad name", seen["t"])

    def test_statistics_of_both_ages(self):
        self.assertTrue(hass_read.mean_kind({"mean_type": 1}))
        self.assertFalse(hass_read.mean_kind({"mean_type": 0, "has_mean": True}))
        self.assertTrue(hass_read.mean_kind({"has_mean": True}))


class TestOneWayOfFitting(unittest.TestCase):
    def test_and_more_takes_the_last_row(self):
        self.assertEqual(listing.fit(5, 120, 40), (2, 3))
        self.assertEqual(listing.fit(3, 120, 40), (3, 0))
        self.assertEqual(listing.fit(5, 40, 40), (1, 0), "no room to say more")
        self.assertEqual(listing.fit(2, 160, 40, more=3), (2, 3), "unread mail it never heard about")

    def test_a_second_line_only_when_it_keeps_every_row(self):
        rows = [listing.Row(f"Row {k}", sub="details") for k in range(4)]
        tight = listing.arrange(200, rows, 1.0, w=700)
        self.assertEqual(tight.shown, 4)
        self.assertFalse(tight.two_lines)
        roomy = listing.arrange(420, rows, 1.0, w=700)
        self.assertTrue(roomy.two_lines)

    def test_few_rows_grow_to_fill_but_never_lose_their_words(self):
        few = listing.arrange(400, [listing.Row("Work", value="34 min")], 1.0, w=700)
        self.assertGreater(few.item_px, listing.ITEM_PX)
        narrow = listing.arrange(400, [listing.Row("A long destination name", value="12 min", badge="N3")], 1.0, w=260)
        self.assertTrue(listing._whole([listing.Row("A long destination name", value="12 min", badge="N3")], 260, narrow.item_px)
                        or narrow.item_px == listing.sizes(400, 1.0)[0])

    def test_a_short_box_drops_the_heading_before_a_row(self):
        rows = [listing.Row("Work", value="34 min"), listing.Row("School", value="12 min")]
        lay = listing.arrange(87, rows, 1.0, w=280)
        self.assertFalse(lay.show_head)
        self.assertEqual(lay.shown, 2)


class TestSharing(unittest.TestCase):
    def test_a_shared_page_keeps_no_one_s_github_or_sensors(self):
        import share
        page = {"elements": [{"id": "a", "type": "year_grid", "source": "github", "user": "someone", "x": 0, "y": 0, "w": 9, "h": 9},
                             {"id": "b", "type": "commute", "entities": ["sensor.to_work"], "x": 0, "y": 0, "w": 9, "h": 9},
                             {"id": "c", "type": "mail_list", "entity": "sensor.imap_me", "x": 0, "y": 0, "w": 9, "h": 9}]}
        text = json.dumps(share.export({"p": page}, ["p"], "792x272", [], []))
        for private in ("someone", "sensor.to_work", "sensor.imap_me"):
            self.assertNotIn(private, text)


# ---------------------------------------------------------------- the editor

@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestTheEditor(unittest.TestCase):
    def test_four_presets_each_setting_up_what_it_needs(self):
        from test_presets import run_js
        got = run_js("console.log(JSON.stringify(Object.fromEntries(['commute', 'departures', 'mail', 'year_grid'].map((id) => { const p = P.presetById(id); "
                     "return [id, { group: p.group, needs: p.needs || '', looks: p.looks.map((l) => [l.id, P.needsOf(p, l) || '', P.asksOf(p, l) || '']), "
                     "types: p.looks.map((l) => P.examplePage(p, l).elements[0].type) }]; }))))")
        self.assertEqual(got["commute"]["needs"], "found")
        self.assertEqual(got["departures"]["needs"], "found")
        self.assertEqual(got["mail"]["needs"], "mail")
        self.assertEqual(got["year_grid"]["looks"], [["year_grid_sensor", "", "sensor"], ["year_grid_github", "github", ""]])
        self.assertEqual({t for p in got.values() for t in p["types"]}, {"commute", "departures", "mail_list", "year_grid"})

    def test_each_setup_is_in_the_one_list(self):
        js = (WEB / "setup.js").read_text()
        self.assertIn("found: foundSetup, mail: mailSetup, github: githubSetup", js)
        self.assertIn('api("api/found?what=" + what)', js, "what the add-on finds, by its own rules")
        self.assertIn("Your password stays in Home Assistant.", js)
        self.assertIn("Settings › Devices & services › Add integration › IMAP", js)
        self.assertNotIn("innerHTML", js)

    def test_several_sensors_have_an_editor(self):
        js = (WEB / "inspector.js").read_text()
        self.assertIn('f.kind === "entities"', js)
        self.assertIn("aria-label\": `Remove ${nameOf(id)}`", js)


class TestTheEditorsApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import web
        from aiohttp.test_utils import TestClient, TestServer
        _, editor = web.make_apps()
        self.client = TestClient(TestServer(editor))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_what_it_finds_by_itself(self):
        r = await self.client.get("/api/found?what=commute")
        self.assertEqual(r.status, 200)
        self.assertTrue((await r.json())["found"])
        self.assertEqual((await self.client.get("/api/found?what=everything")).status, 400)

    async def test_a_username_github_would_refuse_is_refused_here(self):
        body = await (await self.client.get("/api/github/check?user=../x")).json()
        self.assertFalse(body["ok"])
        self.assertIn("isn't a GitHub username", body["error"])


if __name__ == "__main__":
    unittest.main()
