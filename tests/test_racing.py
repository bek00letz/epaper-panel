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

    async def test_a_driver_without_a_code_gets_one_from_the_surname(self):
        _, data = await self._fetch("nascar")
        self.assertEqual(data["standings"][0]["driver"], "LAR")

    async def test_a_live_formula_e_session_says_live(self):
        started = iso(NOW - timedelta(minutes=20))
        web = FakeWeb({"sportstimes": {"races": [{"name": "Live ePrix", "location": "Here",
                                                  "sessions": {"qualifying": started}}]}})
        data = await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["clock"]), ("IN", "Qualifying LIVE"))

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


if __name__ == "__main__":
    unittest.main()
