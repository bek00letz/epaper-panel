"""Racing series: each series fetches its own data, never another's."""
import unittest

import support  # noqa: F401

from sources import racing


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


class FakeWeb:
    """Answers ESPN's scoreboards and the session calendars by address, and remembers what was asked."""

    def __init__(self):
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        if "site.api.espn.com" in url:
            board = url.split("/racing/")[1].split("/")[0]
            return _Reply({"events": [{
                "name": f"Race on {board}", "date": "2026-10-25T18:00Z",
                "circuit": {"fullName": f"Track of {board}"},
                "status": {"type": {"state": "pre", "description": "Scheduled"}},
                "competitions": [{"competitors": [
                    {"athlete": {"displayName": "Kyle Larson"}, "team": {"displayName": "Hendrick"}}]}],
            }]})
        if "sportstimes" in url:
            cal = url.split("/_db/")[1].split("/")[0]
            return _Reply({"races": [{"name": f"Race on {cal}", "location": "Somewhere",
                                      "sessions": {"race": "2099-01-01T12:00:00Z"}}]})
        return _Reply(None)


class TestEverySeriesFetchesItsOwn(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        racing._racing_cache.clear()
        racing._racing_window_cache.clear()

    async def _fetch(self, series):
        web = FakeWeb()
        data = await racing.fetch_racing_data.direct(web, series, tz_name="UTC")
        return web, data

    async def test_nascar_reads_nascars_scoreboard(self):
        web, data = await self._fetch("nascar")
        self.assertEqual(web.asked, ["https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/scoreboard"])
        self.assertEqual((data["series"], data["event_name"]), ("NASCAR", "Race on nascar-premier"))

    async def test_indycar_reads_indycars_scoreboard(self):
        web, data = await self._fetch("indycar")
        self.assertEqual(web.asked, ["https://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard"])
        self.assertEqual((data["series"], data["event_name"]), ("INDYCAR", "Race on irl"))

    async def test_formula_1_reads_f1s_scoreboard(self):
        web, data = await self._fetch("f1")
        self.assertEqual(web.asked, ["https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"])
        self.assertEqual(data["series"], "F1")

    async def test_formula_e_reads_its_calendar(self):
        web, data = await self._fetch("formula_e")
        self.assertTrue(web.asked and all("/_db/fe/" in u for u in web.asked), web.asked)
        self.assertEqual((data["series"], data["event_name"]), ("FE", "Race on fe"))

    async def test_a_driver_without_a_code_gets_one_from_the_surname(self):
        _, data = await self._fetch("nascar")
        self.assertEqual(data["standings"][0]["driver"], "LAR")

    async def test_the_race_window_asks_the_same_places(self):
        for series, want in (("nascar", "/racing/nascar-premier/"), ("indycar", "/racing/irl/"),
                             ("f1", "/_db/f1/"), ("fe", "/_db/fe/")):
            web = FakeWeb()
            win = await racing.compute_racing_active_window.direct(web, series, tz_name="UTC")
            self.assertTrue(any(want in u for u in web.asked), (series, web.asked))
            self.assertEqual(win["slug"], racing.series_of(series).slug)

    async def test_a_live_formula_e_session_says_live(self):
        from datetime import datetime, timedelta, timezone
        started = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        web = FakeWeb()
        web.get = lambda url, **kw: _Reply({"races": [{"name": "Live ePrix", "location": "Here",
                                                       "sessions": {"qualifying": started}}]})
        data = await racing.fetch_racing_data.direct(web, "fe", tz_name="UTC")
        self.assertEqual((data["status"], data["clock"]), ("IN", "Qualifying LIVE"))

    def test_every_name_a_page_uses_finds_its_series(self):
        for alias, slug in (("nascar", "nascar"), ("NASCAR-premier", "nascar"), ("irl", "indycar"),
                            ("IndyCar", "indycar"), ("formula-e", "fe"), ("f1", "f1"), ("sensor.f1", "f1")):
            self.assertEqual(racing.series_slug(alias)[0], slug, alias)


if __name__ == "__main__":
    unittest.main()
