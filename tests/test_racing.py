"""Racing series: each series fetches its own data, never another's, and one rule says what's on."""
import json
import unittest
from datetime import datetime, timedelta, timezone

import support  # noqa: F401

from sources import racing

NOW = datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Reply:
    def __init__(self, body):
        self.status = 200 if body is not None else 404
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)


class FakeWeb:
    """Answers by address from `pages` (a part of the address: its body, None for 404), and remembers what was asked."""

    def __init__(self, pages=None):
        self.asked = []
        self.pages = pages if pages is not None else {
            "site.api.espn.com": lambda url: {"events": [{
                "name": f"Race on {url.split('/racing/')[1].split('/')[0]}", "date": iso(NOW + timedelta(days=2)),
                "circuit": {"fullName": "Track"},
                "status": {"type": {"state": "pre", "description": "Scheduled"}},
                "competitions": [{"competitors": [
                    {"athlete": {"displayName": "Kyle Larson"}, "team": {"displayName": "Hendrick"}}]}],
            }]},
            "sportstimes": lambda url: {"races": [{"name": f"Race on {url.split('/_db/')[1].split('/')[0]}",
                                                   "location": "Somewhere", "sessions": {"race": "2099-01-01T12:00:00Z"}}]},
        }

    def get(self, url, **kw):
        self.asked.append(url)
        for part, body in self.pages.items():
            if part in url:
                return _Reply(body(url) if callable(body) else body)
        return _Reply(None)


def official_page(*races, season="Season 13"):
    """A calendar page with its season as schema.org events, as Formula E's is."""
    items = [{"@type": "ListItem", "position": i + 1, "item": {
        "@type": "SportsEvent", "name": f"R{i + 1:02d} {name}", "startDate": day, "endDate": day,
        "location": {"@type": "Place", "name": city, "address": {"@type": "PostalAddress", "addressLocality": city}},
        "superEvent": {"@type": "EventSeries", "name": season}}} for i, (name, city, day) in enumerate(races)]
    ld = json.dumps({"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items})
    return f'<html><head><script type="application/ld+json">{ld}</script></head><body>…</body></html>'


def sessions_file(*races):
    return {"races": [{"name": name, "location": city, "sessions": {"qualifying": iso(t - timedelta(hours=4)), "race": iso(t)}}
                      for name, city, t in races]}


def forget():
    racing._calendar_cache.clear()
    racing._board_cache.clear()
    racing._racing_window_cache.clear()


class TestEverySeriesFetchesItsOwn(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        forget()

    async def _fetch(self, series):
        web = FakeWeb()
        data = await racing.fetch_racing_data.direct(web, series, tz_name="UTC")
        return web, data

    async def test_nascar_reads_nascars_scoreboard(self):
        web, data = await self._fetch("nascar")
        self.assertEqual(web.asked, ["https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/scoreboard"])
        self.assertEqual((data["series"], data["event_name"]), ("NASCAR", "Race on nascar-premier"))

    async def test_indycar_reads_indycars_scoreboard_and_calendar(self):
        web, data = await self._fetch("indycar")
        self.assertEqual(set(web.asked), {"https://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard",
                                          *(f"https://raw.githubusercontent.com/sportstimes/f1/main/_db/indycar/{y}.json"
                                            for y in (NOW.year, NOW.year + 1))})
        self.assertEqual((data["series"], data["event_name"]), ("INDYCAR", "Race on irl"))

    async def test_formula_1_reads_f1s_scoreboard_and_calendar(self):
        web, data = await self._fetch("f1")
        self.assertIn("https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard", web.asked)
        self.assertTrue(all("/racing/f1/" in u or "/_db/f1/" in u for u in web.asked), web.asked)
        self.assertEqual(data["series"], "F1")

    async def test_formula_e_reads_its_own_calendars(self):
        web, data = await self._fetch("formula_e")
        self.assertEqual(web.asked[0], "https://www.fiaformulae.com/en/calendar", "its own calendar first")
        self.assertTrue(all("/_db/fe/" in u or "formulaecal.com" in u for u in web.asked[1:]), web.asked)
        self.assertEqual((data["series"], data["event_name"]), ("FE", "Race on fe"))

    async def _live(self, series):
        """A board whose one session runs now, as NASCAR's does on race day."""
        web = FakeWeb({"site.api.espn.com": {"events": [{
            "name": "Race now", "date": iso(NOW - timedelta(minutes=30)), "circuit": {"fullName": "Track"},
            "status": {"type": {"state": "in", "description": "In Progress"}},
            "competitions": [{"competitors": [{"athlete": {"displayName": "Kyle Larson"}, "team": {"displayName": "Hendrick"}}]}],
        }]}})
        return await racing.fetch_racing_data.direct(web, series, tz_name="UTC")

    async def test_a_driver_without_a_code_gets_one_from_the_surname(self):
        data = await self._live("nascar")
        self.assertEqual(data["standings"][0]["driver"], "LAR")

    async def test_a_board_before_its_session_is_no_leaderboard(self):
        # ESPN lists who's entered before a session runs: never an order, under any name.
        _, data = await self._fetch("nascar")
        self.assertEqual((data["status"], data["standings"]), ("PRE", []))

    async def test_no_driver_gets_a_tyre_nobody_gave(self):
        # Every driver had a medium tyre box: ESPN gives no tyres, the add-on made one up.
        data = await self._live("nascar")
        self.assertTrue(data["standings"])
        self.assertTrue(all("tyre" not in row for row in data["standings"]), data["standings"])

    async def test_a_live_formula_e_session_says_live(self):
        started = iso(NOW - timedelta(minutes=20))
        web = FakeWeb({"sportstimes": {"races": [{"name": "Live ePrix", "location": "Here",
                                                  "sessions": {"qualifying": started}}]}})
        data = await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["session"], data["badge"]), ("IN", "Qualifying", ["QUALIFYING · LIVE", "QUALIFYING"]))
        self.assertEqual(data["standings"], [], "no source has its order: the card, not someone else's")

    async def test_the_race_window_asks_the_same_places(self):
        for series, want in (("nascar", "/racing/nascar-premier/"), ("indycar", "/racing/irl/"),
                             ("f1", "/_db/f1/"), ("fe", "fiaformulae.com")):
            web = FakeWeb()
            win = await racing.compute_racing_active_window.direct(web, series, tz_name="UTC")
            self.assertTrue(any(want in u for u in web.asked), (series, web.asked))
            self.assertEqual(win["slug"], racing.series_of(series).slug)

    def test_every_name_a_page_uses_finds_its_series(self):
        for alias, slug in (("nascar", "nascar"), ("NASCAR-premier", "nascar"), ("irl", "indycar"),
                            ("IndyCar", "indycar"), ("formula-e", "fe"), ("f1", "f1"), ("sensor.f1", "f1")):
            self.assertEqual(racing.series_slug(alias)[0], slug, alias)


class TestBetweenSeasons(unittest.IsolatedAsyncioTestCase):
    """The user's find (22 Oct): Formula E showed last season's final race as if it were on."""

    def setUp(self):
        forget()

    async def both(self, web, series):
        data = await racing.fetch_racing_data.direct(web, series, tz_name="UTC")
        win = await racing.compute_racing_active_window.direct(web, series, tz_name="UTC")
        return data, win

    async def test_formula_e_with_only_a_past_season_says_the_calendar_isnt_out(self):
        london = NOW - timedelta(days=66)
        web = FakeWeb({f"/_db/fe/{NOW.year}.json": sessions_file(("London ePrix", "London", london)),
                       "formulaecal.com/api/year/%d" % NOW.year: sessions_file(("London ePrix", "London", london))})
        data, win = await self.both(web, "fe")
        self.assertEqual((data["status"], data["clock"]), ("OFF", "OFF SEASON"))
        self.assertEqual(data["event_name"], "", "never last season's race as if it were on")
        self.assertEqual(data["detail"], "Next season's calendar isn't out yet")
        self.assertTrue(data["last_race_end"].startswith(london.date().isoformat()))
        self.assertFalse(win["is_active"], "the page stays out of the rotation")

    async def test_the_official_calendar_knows_the_next_season_before_the_community_ones(self):
        london = NOW - timedelta(days=66)
        jeddah = (NOW + timedelta(days=58)).date()
        web = FakeWeb({"fiaformulae.com": official_page(("Jeddah E-Prix", "Jeddah", jeddah.isoformat()),
                                                         ("Jeddah E-Prix", "Jeddah", (jeddah + timedelta(days=1)).isoformat())),
                       f"/_db/fe/{NOW.year}.json": sessions_file(("London ePrix", "London", london))})
        data, win = await self.both(web, "fe")
        self.assertEqual((data["status"], data["event_name"], data["circuit"], data["season"]),
                         ("OFF", "Jeddah E-Prix", "Jeddah", "Season 13"))
        self.assertEqual(data["detail"], "Season starts " + racing._day(jeddah))
        self.assertFalse(win["is_active"])

    async def test_the_official_calendar_names_a_race_and_a_community_one_times_it(self):
        race = NOW + timedelta(days=3)
        web = FakeWeb({"fiaformulae.com": official_page(("Jeddah E-Prix", "Jeddah", race.date().isoformat())),
                       f"/_db/fe/{NOW.year + 1}.json": sessions_file(("Saudi Arabia ePrix", "Diriyah", race)),
                       f"/_db/fe/{NOW.year}.json": sessions_file(("Saudi Arabia ePrix", "Diriyah", race))})
        data = await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["event_name"]), ("PRE", "Jeddah E-Prix"))
        self.assertTrue(data["detail"].startswith("Qualifying · "), data["detail"])

    async def test_a_race_known_only_by_its_day_says_race_day(self):
        day = (NOW + timedelta(days=3)).date()
        web = FakeWeb({"fiaformulae.com": official_page(("Jeddah E-Prix", "Jeddah", day.isoformat()))})
        data = await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["detail"]),
                         ("PRE", "Race day · " + racing._day(day)), "a season opener a week off")

    async def test_espn_with_no_race_to_come_is_the_off_season_not_its_last_result(self):
        monterey = NOW - timedelta(days=45)
        board = {"events": [{"name": "Grand Prix of Monterey", "date": iso(monterey),
                             "status": {"type": {"state": "post", "description": "Final"}},
                             "competitions": [{"date": iso(monterey), "status": {"type": {"state": "post"}},
                                               "competitors": [{"athlete": {"displayName": "Alex Palou"}}]}]}],
                 "leagues": [{"calendar": [{"label": "Grand Prix of Monterey", "startDate": iso(monterey),
                                            "endDate": iso(monterey)}]}]}
        for series in ("indycar", "f1", "nascar"):
            forget()
            data, win = await self.both(FakeWeb({"site.api.espn.com": board}), series)
            self.assertEqual((data["status"], data["standings"]), ("OFF", []), series)
            self.assertEqual(data["detail"], "Next season's calendar isn't out yet")
            self.assertFalse(win["is_active"])

    async def test_a_finished_race_shows_its_result_for_a_few_hours_then_the_next(self):
        done = NOW - timedelta(hours=3)
        nxt = NOW + timedelta(days=14)
        board = {"events": [{"name": "Phoenix", "date": iso(done), "status": {"type": {"state": "post", "description": "Final"}},
                             "competitions": [{"date": iso(done), "status": {"type": {"state": "post"}},
                                               "competitors": [{"athlete": {"displayName": "Ryan Blaney"}}]}]}],
                 "leagues": [{"calendar": [{"label": "Phoenix", "startDate": iso(done), "endDate": iso(done)},
                                           {"label": "Talladega", "startDate": iso(nxt), "endDate": iso(nxt)}]}]}
        data = await racing.fetch_racing_data.direct(FakeWeb({"site.api.espn.com": board}), "nascar", tz_name="UTC")
        self.assertEqual((data["status"], data["event_name"], data["standings"][0]["driver"]), ("POST", "Phoenix", "BLA"))
        forget()
        done = NOW - timedelta(hours=8)
        board["events"][0]["date"] = board["events"][0]["competitions"][0]["date"] = iso(done)
        board["leagues"][0]["calendar"][0].update(startDate=iso(done), endDate=iso(done))
        data = await racing.fetch_racing_data.direct(FakeWeb({"site.api.espn.com": board}), "nascar", tz_name="UTC")
        self.assertEqual((data["status"], data["event_name"], data["standings"]), ("PRE", "Talladega", []))

    async def test_a_newly_published_season_is_picked_up(self):
        london = NOW - timedelta(days=66)
        pages = {f"/_db/fe/{NOW.year}.json": sessions_file(("London ePrix", "London", london))}
        data = await racing.fetch_racing_data.direct(FakeWeb(pages), "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["event_name"]), ("OFF", ""))
        opener = NOW + timedelta(days=40)
        pages[f"/_db/fe/{NOW.year + 1}.json"] = sessions_file(("Sao Paulo ePrix", "Sao Paulo", opener))
        data = await racing.fetch_racing_data.direct(FakeWeb(pages), "fe", tz_name="UTC")
        self.assertEqual(data["event_name"], "", "a calendar is read again within the hour, not every minute")
        for c in racing._calendar_cache.values():
            c["at"] -= racing.CALENDAR_EVERY
        data = await racing.fetch_racing_data.direct(FakeWeb(pages), "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["event_name"]), ("OFF", "Sao Paulo ePrix"))
        self.assertTrue(data["detail"].startswith("Season starts "))

    async def test_a_calendar_that_cant_be_read_keeps_its_last_season(self):
        pages = {f"/_db/fe/{NOW.year}.json": sessions_file(("Mexico City ePrix", "Mexico City", NOW + timedelta(days=2)))}
        first = await racing.fetch_racing_data.direct(FakeWeb(pages), "fe", tz_name="UTC")
        for c in racing._calendar_cache.values():
            c["at"] -= racing.CALENDAR_EVERY

        class Down(FakeWeb):
            def get(self, url, **kw):
                raise OSError("down")
        again = await racing.fetch_racing_data.direct(Down(), "fe", tz_name="UTC")
        self.assertEqual(again["event_name"], first["event_name"])
        forget()
        self.assertIsNone(await racing.fetch_racing_data.direct(Down(), "fe", tz_name="UTC"),
                          "nothing read yet: nothing to show, never a made-up season")

    async def test_an_official_page_that_stops_listing_its_season_is_a_problem(self):
        import health
        health.reset()
        web = FakeWeb({"fiaformulae.com": "<html><body>A new design</body></html>"})
        await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        entry = next(e for e in health.status() if e["name"] == "Formula E")
        self.assertIsNotNone(entry["failing_since"])
        self.assertIn("no races", entry["error"])

    async def test_a_calendar_in_another_shape_is_a_problem_and_keeps_its_last_season(self):
        # It was ignored silently: a shape error isn't a ValueError, and the catch-all assumed
        # health's trace had already said so, which it only does for the network.
        import health
        health.reset()
        url_part = f"/_db/f1/{NOW.year}.json"
        good = {url_part: sessions_file(("Las Vegas Grand Prix", "Las Vegas", NOW + timedelta(days=2)))}
        first = await racing.fetch_racing_data.direct(FakeWeb(good), "f1", tz_name="UTC")
        for c in racing._calendar_cache.values():
            c["at"] -= racing.CALENDAR_EVERY
        for odd in ({"races": [{"name": "x", "sessions": ["2099-01-01T12:00:00Z"]}]},
                    {"races": ["Las Vegas"]},
                    {"races": {"name": "x"}}):
            web = FakeWeb({url_part: odd, "site.api.espn.com": {"events": []}})
            again = await racing.fetch_racing_data.direct(web, "f1", tz_name="UTC")
            self.assertEqual(again["event_name"], first["event_name"], f"kept its last season with {odd}")
            entry = next((e for e in health.status() if e["name"] == "Racing calendar"), None)
            self.assertIsNotNone(entry and entry["failing_since"], f"said so with {odd}")
            for c in racing._calendar_cache.values():
                c["at"] -= racing.CALENDAR_EVERY


# The 2026 United States GP as ESPN's board has it (checked 26 Oct): one event, a competition per
# session ("FP1", "FP2", "FP3", "Qual", "Race"), each with its own state and its own order.
GP = ("FP1", "FP2", "FP3", "Qual", "Race")
LEADERS = {"FP1": "Charles Leclerc", "FP2": "Oscar Piastri", "FP3": "Lewis Hamilton", "Qual": "Kimi Antonelli",
           "Race": "Max Verstappen"}


def gp_board(starts: dict, states: dict) -> dict:
    """ESPN's board for a weekend: each session's start, and the state ESPN gives it ("pre" if not said)."""
    def comp(abbr):
        st = states.get(abbr, "pre")
        out = {"type": {"abbreviation": abbr}, "date": iso(starts[abbr]),
               "status": {"type": {"state": st, "description": {"pre": "Scheduled", "in": "In Progress"}.get(st, "Final")}}}
        out["competitors"] = [{"order": 2, "athlete": {"displayName": "George Russell"}},
                              {"order": 1, "athlete": {"displayName": LEADERS[abbr]}}]
        return out
    ev_state = "in" if "in" in states.values() else "post" if states.get("Race") == "post" else "pre"
    return {"events": [{"name": "United States Grand Prix", "date": iso(starts["FP1"]),
                        "circuit": {"fullName": "Circuit of the Americas", "address": {"city": "Austin"}},
                        "status": {"type": {"state": ev_state, "description": "In Progress" if ev_state == "in" else "Final"}},
                        "competitions": [comp(a) for a in GP]}]}


def weekend(fp3: datetime) -> dict:
    """A weekend's starts from its third practice: as Austin's, Qualifying 3½ hours later, the race the day after."""
    return {"FP1": fp3 - timedelta(hours=24), "FP2": fp3 - timedelta(hours=20.5), "FP3": fp3,
            "Qual": fp3 + timedelta(hours=3.5), "Race": fp3 + timedelta(hours=26.5)}


class TestTheSessionShown(unittest.IsolatedAsyncioTestCase):
    """The user's find (26 Oct): on a race weekend nothing said which session the page was for, and
    the standings could be another session's. One rule picks the session; its order is its own."""

    def setUp(self):
        forget()

    async def page(self, starts, states, **kw):
        forget()
        web = FakeWeb({"site.api.espn.com": gp_board(starts, states), "sportstimes": None})
        return await racing.fetch_racing_data.direct(web, "f1", tz_name="UTC", **kw)

    def leader(self, data):
        return data["standings"][0]["driver"] if data["standings"] else None

    async def test_saturday_morning_between_practice_3_and_qualifying(self):
        done = {"FP1": "post", "FP2": "post", "FP3": "post"}
        # Practice 3 ended an hour ago: its own order, named, by ESPN's order (not its list's).
        data = await self.page(weekend(NOW - timedelta(hours=2.5)), done)
        self.assertEqual((data["status"], data["session"], self.leader(data)), ("POST", "Practice 3", "HAM"))
        self.assertEqual(data["badge"], ["PRACTICE 3 · FINAL", "PRACTICE 3"])
        self.assertEqual([r["pos"] for r in data["standings"]], [1, 2])
        # Austin's Qualifying starts 2 hours after Practice 3 ends, so with Hours after at 2 its result
        # shows until then. At 1, past it: the next session's card, never Practice 3's order under it.
        data = await self.page(weekend(NOW - timedelta(hours=2.7)), done, post_buffer_hours=1.0)
        self.assertEqual((data["status"], data["session"], data["standings"]), ("PRE", "Qualifying", []))
        self.assertTrue(data["detail"].startswith("Qualifying · "), data["detail"])
        self.assertEqual(data["badge"], ["SCHEDULED"])

    async def test_the_page_leaves_a_result_when_its_gate_does(self):
        done = {"FP1": "post", "FP2": "post", "FP3": "post"}
        for after in (0.25, 1.0, 1.5):                  # all before Qualifying starts, 2 hours on
            for past, shows in ((after - 0.05, True), (after + 0.05, False)):
                fp3 = NOW - timedelta(hours=1.5 + past)
                data = await self.page(weekend(fp3), done, post_buffer_hours=after)
                self.assertEqual(data["session"] == "Practice 3", shows, (after, past, data["session"]))
                forget()
                web = FakeWeb({"site.api.espn.com": gp_board(weekend(fp3), done), "sportstimes": None})
                win = await racing.compute_racing_active_window.direct(web, "f1", pre_buffer_hours=0,
                                                                       post_buffer_hours=after, tz_name="UTC")
                self.assertEqual(win["is_active"], shows, ("the gate counts the same hours", after, past))

    async def test_during_qualifying(self):
        data = await self.page(weekend(NOW - timedelta(hours=3.8)), {"FP1": "post", "FP2": "post", "FP3": "post", "Qual": "in"})
        self.assertEqual((data["status"], data["session"], self.leader(data)), ("IN", "Qualifying", "ANT"))
        self.assertEqual(data["badge"], ["QUALIFYING · LIVE", "QUALIFYING"])
        self.assertEqual(data["clock"], "QUALIFYING · LIVE", "Home Assistant's sensor says the same")
        self.assertEqual(data["event_name"], "United States Grand Prix")
        forget()
        web = FakeWeb({"site.api.espn.com": gp_board(weekend(NOW - timedelta(hours=3.8)), {}), "sportstimes": None})
        win = await racing.compute_racing_active_window.direct(web, "f1", tz_name="UTC")
        self.assertEqual(win["session_name"], "Qualifying", "Home Assistant's sensor says it as the page does, not \"Qual\"")

    async def test_a_session_running_late_is_still_live(self):
        # Its calendar time is over, but ESPN says it still runs (a red flag): it's the one shown.
        data = await self.page(weekend(NOW - timedelta(hours=5.5)), {"FP1": "post", "FP2": "post", "FP3": "post", "Qual": "in"})
        self.assertEqual((data["status"], data["session"], self.leader(data)), ("IN", "Qualifying", "ANT"))

    async def test_after_the_race(self):
        states = dict.fromkeys(GP, "post")
        for hours_ago, shows in ((0.5, True), (3.5, True), (4.5, False)):
            race = NOW - timedelta(hours=2.5 + hours_ago)
            data = await self.page(weekend(race - timedelta(hours=26.5)), states)
            if shows:
                self.assertEqual((data["status"], data["session"], self.leader(data)), ("POST", "Race", "VER"), hours_ago)
                self.assertEqual(data["badge"], ["RACE · FINAL", "RACE"])
            else:
                self.assertEqual((data["status"], data["standings"]), ("OFF", []), "its result for AFTER_HOURS, then not")

    async def test_formula_e_with_its_own_sessions(self):
        # Formula E has no ESPN board: its calendar's sessions, by the same rule, and no order to show.
        q = NOW - timedelta(minutes=20)
        file = {"races": [{"name": "Miami ePrix", "location": "Miami", "sessions": {
            "fp1": iso(q - timedelta(hours=26)), "fp2": iso(q - timedelta(hours=3)), "qualifying": iso(q),
            "race": iso(q + timedelta(hours=4))}}]}
        data = await racing.fetch_racing_data.direct(FakeWeb({"sportstimes": file}), "fe", tz_name="UTC")
        self.assertEqual((data["series"], data["status"], data["session"], data["standings"]),
                         ("FE", "IN", "Qualifying", []))
        self.assertEqual(data["badge"], ["QUALIFYING · LIVE", "QUALIFYING"])
        forget()
        file["races"][0]["sessions"]["qualifying"] = iso(NOW - timedelta(hours=1.6))
        data = await racing.fetch_racing_data.direct(FakeWeb({"sportstimes": file}), "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["session"], data["badge"]), ("POST", "Qualifying", ["QUALIFYING · FINAL", "QUALIFYING"]))

    async def test_a_sensor_of_your_own_names_its_session_or_shows_a_result(self):
        board = [{"pos": 1, "driver": "VER"}, {"pos": 2, "driver": "NOR"}]
        state = {"state": "in", "attributes": {"standings": board, "session": "qual", "lap": None}}
        data = await racing.fetch_racing_data.direct(FakeWeb({}), "f1", fallback=state, tz_name="UTC")
        self.assertEqual((data["session"], data["badge"]), ("Qualifying", ["QUALIFYING · LIVE", "QUALIFYING"]))
        state = {"state": "in", "attributes": {"standings": board, "lap": 34, "total_laps": 57, "session": "Race"}}
        data = await racing.fetch_racing_data.direct(FakeWeb({}), "f1", fallback=state, tz_name="UTC")
        self.assertEqual(data["badge"], ["RACE · LAP 34/57", "RACE"])
        state = {"state": "post", "attributes": {"standings": board}}
        data = await racing.fetch_racing_data.direct(FakeWeb({}), "f1", fallback=state, tz_name="UTC")
        self.assertEqual((data["session"], data["badge"]), ("", ["RESULT"]), "a session nobody said isn't guessed")


class TestTheBadge(unittest.TestCase):
    """A leaderboard is never drawn without its session's name: in the badge, shorter where it must
    be, or in the header where the badge steps aside."""

    def drawn(self, data, w):
        from PIL import Image, ImageDraw
        from render import layout
        img = Image.new("L", (800, 300), 255)
        d = ImageDraw.Draw(img)
        texts = []
        real = d.text
        d.text = lambda xy, txt, **kw: (texts.append(txt), real(xy, txt, **kw))
        layout._draw_sports_racing(img, d, {"type": "sports_racing", "x": 0, "y": 0, "w": w, "h": 235}, json.dumps(data))
        return texts

    def test_every_series_names_its_session_at_every_width(self):
        import examples
        practice = {**examples.race("f1"), "session": "Practice 3", "status": "POST", "lap": None,
                    "badge": racing.badge("Practice 3", "POST")}
        for series in racing.SERIES:
            for data in (examples.race(series), practice):
                for w in (752, 480, 360, 300, 260, 240, 200, 180, 150):     # narrower is cut with an ellipsis
                    texts = self.drawn(data, w)
                    self.assertTrue(any(data["badge"][-1] in t for t in texts), (series, w, texts))
        self.assertIn("RACE · LAP 42/53", self.drawn(examples.race("f1"), 752), "the whole of it where there's room")
        self.assertIn("RACE", self.drawn(examples.race("f1"), 240), "the session's name, its state left out")
        self.assertIn("F1 · PRACTICE 3", self.drawn(practice, 200), "the badge steps aside: the header says it")

    def test_the_words_of_a_badge(self):
        self.assertEqual(racing.badge("Qualifying", "IN"), ["QUALIFYING · LIVE", "QUALIFYING"])
        self.assertEqual(racing.badge("Race", "IN", 34, 57), ["RACE · LAP 34/57", "RACE"])
        self.assertEqual(racing.badge("Practice 3", "POST"), ["PRACTICE 3 · FINAL", "PRACTICE 3"])
        self.assertEqual(racing.badge("", "POST"), ["RESULT"])
        self.assertEqual(racing.badge("", "IN"), ["LIVE"])


if __name__ == "__main__":
    unittest.main()
