"""The add-on's own fields for races, games and planes (shapes.py), and your own source filling them.

* A source's answer is read into the add-on's own fields, or refused with what's wrong, plainly.
* A widget whose data says "your source" reads it through the same rule as the services' data
  (racing's one rule, the games' view, planes measured from home), and never asks the services.
* A source that fills a page is no sensor in Home Assistant.
"""
import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import support
import feeds
import health
import live_data
import runtime
import services
import shapes
import widgets
from sources import flights, racing, sports


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
RACES = {"races": [
    {"race": "Last Grand Prix", "place": "Old Town", "sessions": {"Race": iso(NOW - timedelta(days=20))}},
    {"race": "Own Grand Prix", "place": "Testville",
     "sessions": [{"session": "Qualifying", "start": iso(NOW - timedelta(hours=4))},
                  {"session": "Race", "start": iso(NOW + timedelta(days=1))}],
     "result": [{"position": 1, "driver": "abc", "team": "One", "gap": ""}, {"position": 2, "driver": "DEF", "gap": "+1.0"}]},
]}
GAMES = {"games": [
    {"home": "Finished FC", "away": "Done United", "start": iso(NOW - timedelta(hours=5)), "status": "post", "home_score": 1, "away_score": 0},
    {"home": "Home Town", "away": "Away City", "start": iso(NOW - timedelta(minutes=30)), "status": "in",
     "home_score": 2, "away_score": 1, "clock": "31'", "league": "Our League", "home_scorers": ["Someone (12')"]},
]}
PLANES = {"planes": [
    {"callsign": "near1", "latitude": 0.05, "longitude": 0.05, "altitude_m": 3000, "speed_kmh": 500, "from": "AAA", "to": "BBB", "aircraft": "A320"},
    {"callsign": "FAR1", "latitude": 5.0, "longitude": 5.0},
]}


class TestReading(unittest.TestCase):
    def test_races_into_the_add_ons_own(self):
        races = shapes.read("racing", RACES)
        self.assertEqual([r.name for r in races], ["Last Grand Prix", "Own Grand Prix"])
        own = races[1]
        self.assertEqual(own.location, "Testville")
        self.assertEqual([s[0] for s in own.sessions], ["Qualifying", "Race"])
        self.assertEqual(own.results[0], ("", "", ({"pos": 1, "driver": "ABC", "team": "One", "gap": ""},
                                                   {"pos": 2, "driver": "DEF", "team": "", "gap": "+1.0"})),
                         "no \"result_session\": an order whose session it does not say")

    def test_what_is_wrong_is_said_plainly(self):
        wrong = {
            "racing": [({}, "no list of races"), ({"races": []}, "empty"), ({"races": [{"sessions": {}}]}, "no name"),
                       ({"races": [{"race": "X"}]}, "no sessions"),
                       ({"races": [{"race": "X", "sessions": {"Race": "soon"}}]}, "a start the add-on can read"),
                       ({"races": ["x"]}, "isn't a set of fields")],
            "scores": [({"games": [{"home": "A"}]}, "both teams"), ({"games": [{"home": "A", "away": "B"}]}, "no start"),
                       ({"games": [{"home": "A", "away": "B", "start": iso(NOW), "status": "live"}]}, '"pre", "in" or "post"')],
            "flights": [({"planes": [{"callsign": "X", "latitude": 95, "longitude": 0}]}, "latitude"),
                        ({"planes": [{"callsign": "X"}]}, "latitude")],
        }
        for kind, cases in wrong.items():
            for body, words in cases:
                with self.subTest(kind=kind, body=body), self.assertRaises(ValueError) as said:
                    shapes.read(kind, body)
                self.assertIn(words, str(said.exception))

    def test_every_outside_widget_has_its_form_in_the_catalog(self):
        for t in ("sports_racing", "sports_match", "flight_tracker"):
            d = widgets.get(t).describe()
            self.assertIn("shape", d, t)
            self.assertTrue(d["shape"]["fields"])
            shapes.read(d["shape"]["kind"], d["shape"]["example"])       # its own example reads
            self.assertIn({"kind": "data"}, d["fields"], "the inspector shows its data")

    def test_a_source_that_fills_a_page_is_no_sensor(self):
        src = {"type": "rest", "name": "races", "url": "https://x/y", "fills": "racing", "id": "a1"}
        self.assertEqual(feeds.source_entities(src), set())
        self.assertEqual(feeds.fills(src), "racing")
        self.assertEqual(feeds.fills({**src, "type": "jellyfin"}), "", "only a JSON address can fill a page")


class OwnSource(unittest.IsolatedAsyncioTestCase):
    """A local server answering in the add-on's own form, saved as a data source that fills pages."""

    async def asyncSetUp(self):
        support.fresh_data_dir()
        health.reset()
        runtime.LIVE._entries.clear()          # noqa: SLF001 -- every test asks afresh (the readers keep this store)
        racing._racing_window_cache.clear()
        sports._sports_window_cache.clear()
        self.asked = []
        app = web.Application()
        for path, body in (("/races", RACES), ("/games", GAMES), ("/planes", PLANES), ("/odd", {"races": "no"})):
            app.router.add_get(path, self._answer(path, body))
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        feeds.save(support.config.DATA_DIR, [
            {"id": "r1", "type": "rest", "name": "races", "url": base + "/races", "fills": "racing"},
            {"id": "g1", "type": "rest", "name": "games", "url": base + "/games", "fills": "scores"},
            {"id": "p1", "type": "rest", "name": "planes", "url": base + "/planes", "fills": "flights"},
            {"id": "o1", "type": "rest", "name": "odd", "url": base + "/odd", "fills": "racing"},
        ])
        # The services an own source stands in for: nowhere, so asking one would show.
        self.session = aiohttp.ClientSession(trace_configs=[health.trace_config()])

    def _answer(self, path, body):
        async def handler(request):
            self.asked.append(path)
            return web.json_response(body)
        return handler

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        support.use_test_data_dir()
        health.reset()

    def asked_a_service(self):
        return [e["name"] for e in health.status() if e["kind"] == "service"]

    async def test_a_race_page_reads_your_races_by_the_one_rule(self):
        el = {"type": "sports_racing", "series": "f1", "data": {"source": "r1"}}
        with live_data.waiting_for_fresh():
            got = await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC"))
        self.assertEqual(got["event_name"], "Own Grand Prix")
        self.assertEqual(got["circuit"], "Testville")
        self.assertEqual(got["status"], "PRE", "its race is tomorrow: the next session is the one shown")
        self.assertEqual(got["session"], "Race")
        self.assertEqual(self.asked_a_service(), [], "neither the calendars nor ESPN were asked")
        self.assertEqual(self.asked, ["/races"])
        with live_data.waiting_for_fresh():
            on = await widgets._race_on(self.session, {**el, "pre_buffer_hours": 30}, "UTC")
        self.assertTrue(on, "its window comes from your races too")
        self.assertEqual(self.asked_a_service(), [])
        fields = dict(shapes.get("racing").shown(got))
        self.assertEqual((fields["Series"], fields["Race"], fields["Session"]), ("Formula 1", "Own Grand Prix", "Race"))

    async def test_a_result_shows_while_its_race_is_on(self):
        races = {"races": [{**RACES["races"][1], "sessions": [{"session": "Race", "start": iso(NOW - timedelta(hours=1))}]}]}
        got = racing._describe(racing.SERIES["f1"], racing._pick(shapes.read("racing", races), NOW), "UTC")
        self.assertEqual(got["status"], "IN")
        self.assertEqual([r["driver"] for r in got["standings"]], ["ABC", "DEF"])
        self.assertEqual((got["session"], got["badge"]), ("", ["RESULT"]),
                         "it doesn't say whose result it is: shown as a result, never as the race's")

    async def test_a_result_shows_under_its_own_session_only(self):
        def page(quali_ago, race_ago=None, after=2.0, said="qualifying"):
            sessions = [{"session": "Qualifying", "start": iso(NOW - timedelta(hours=quali_ago))},
                        {"session": "Race", "start": iso(NOW - timedelta(hours=race_ago) if race_ago is not None
                                                         else NOW + timedelta(days=1))}]
            races = {"races": [{**RACES["races"][1], "sessions": sessions, "result_session": said}]}
            return racing._describe(racing.SERIES["f1"], racing._pick(shapes.read("racing", races), NOW, after), "UTC")
        got = page(0.5)
        self.assertEqual((got["status"], got["session"], len(got["standings"])), ("IN", "Qualifying", 2))
        self.assertEqual(got["badge"], ["QUALIFYING · LIVE", "QUALIFYING"])
        got = page(2.5)
        self.assertEqual((got["status"], got["session"], got["badge"][0]), ("POST", "Qualifying", "QUALIFYING · FINAL"))
        got = page(2.5, after=0.5)
        self.assertEqual((got["status"], got["session"], got["standings"]), ("PRE", "Race", []), "past its Hours after")
        got = page(20, race_ago=0.5)
        self.assertEqual((got["status"], got["session"], got["standings"]), ("IN", "Race", []),
                         "Qualifying's order is never the race's")
        self.assertEqual(got["badge"], ["RACE · LIVE", "RACE"])

    async def test_a_scores_page_reads_your_games(self):
        el = {"type": "sports_match", "league": "soccer/eng.1", "data": {"source": "g1"}}
        with live_data.waiting_for_fresh():
            got = await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC"))
        self.assertEqual([g["home_team"] for g in got], ["Home Town", "Finished FC"], "playing first")
        live = got[0]
        self.assertEqual((live["home_score"], live["away_score"], live["status"], live["league"]), (2, 1, "IN", "Our League"))
        self.assertIn("31'", live["clock"])
        self.assertEqual(live["events_home"], "Someone (12')")
        with live_data.waiting_for_fresh():
            self.assertTrue(await widgets._match_on(self.session, el, "UTC"), "a game on now opens its window")
        self.assertEqual(self.asked_a_service(), [])

    async def test_a_flights_page_measures_your_planes_from_home(self):
        el = {"type": "flight_tracker", "lat": 0, "lon": 0, "radius": 35, "data": {"source": "p1"}}
        with live_data.waiting_for_fresh():
            got = await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC"))
        self.assertEqual([p["callsign"] for p in got], ["NEAR1"], "the far one is outside the radius")
        p = got[0]
        self.assertEqual((p["origin"], p["destination"], p["model"]), ("AAA", "BBB", "A320"))
        self.assertGreater(p["distance_km"], 0)
        self.assertEqual(self.asked_a_service(), [])

    async def test_a_source_in_another_form_is_its_problem_not_a_services(self):
        el = {"type": "sports_racing", "series": "f1", "data": {"source": "o1"}}
        with live_data.waiting_for_fresh(), contextlib.redirect_stdout(io.StringIO()):
            got = await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC"))
        self.assertIsNone(got)
        entry = next(e for e in health.status() if e["name"] == "Source “odd”")
        self.assertIn("no list of races", entry["error"])
        self.assertEqual(self.asked_a_service(), [])

    async def test_a_removed_source_shows_nothing(self):
        el = {"type": "sports_racing", "series": "f1", "data": {"source": "gone"}}
        with live_data.waiting_for_fresh():
            self.assertIsNone(await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC")))

    async def test_a_home_assistant_sensor_can_give_the_fields(self):
        import ha
        states = {"sensor.my_races": {"state": "ok", "attributes": {"races": RACES["races"], "friendly_name": "Mine"}},
                  "sensor.wrong": {"state": "ok", "attributes": {"something": "else"}}}

        async def fake(session, path, *a, **kw):
            return states[path.removeprefix("/states/")]
        old, ha.ha_json = ha.ha_json, fake
        try:
            el = {"type": "sports_racing", "series": "f1", "data": {"entity": "sensor.my_races"}}
            self.assertEqual(shapes.own_source(el), "entity:sensor.my_races")
            with live_data.waiting_for_fresh():
                got = await widgets.fetch(self.session, el, widgets.Ctx(home_tz="UTC"))
            self.assertEqual(got["event_name"], "Own Grand Prix")
            self.assertEqual(self.asked_a_service(), [], "the calendars and ESPN weren't asked")
            wrong = {**el, "data": {"entity": "sensor.wrong"}}
            with live_data.waiting_for_fresh(), contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(await widgets.fetch(self.session, wrong, widgets.Ctx(home_tz="UTC")))
            self.assertIn("no list of races", shapes.problem(shapes.own_source(wrong)))
            self.assertNotIn("Sensor", [e["name"] for e in health.status()], "a sensor gets no problem sensor of its own")
            self.assertEqual(shapes.own_source({**el, "data": {"entity": ""}}), "", "until one is chosen: the services")
            used = {x["id"]: x["used_by"] for x in services.listing([("Mine", {"elements": [el]})])}
            self.assertEqual(used["racing_calendar"], [])
        finally:
            ha.ha_json = old

    async def test_try_again_reads_a_source_that_fills_a_page(self):
        got = await services.try_again(self.session, "source_races")
        self.assertEqual(got, {"ok": True, "said": "Racing pages' data, 2 races"})
        with contextlib.redirect_stdout(io.StringIO()):
            got = await services.try_again(self.session, "source_odd")
        self.assertFalse(got["ok"])
        self.assertIn("no list of races", got["error"])

    async def test_settings_says_who_uses_what(self):
        pages = [("Mine", {"elements": [{"type": "sports_racing", "series": "f1", "data": {"source": "r1"}}]}),
                 ("Theirs", {"elements": [{"type": "sports_racing", "series": "f1"}]})]
        used = {s["name"]: s["used_by"] for s in services.listing(pages)}
        self.assertEqual(used["Racing calendar"], ["Theirs"])
        self.assertEqual(used["ESPN"], ["Theirs"])
        self.assertEqual(used["Source “races”"], ["Mine"])


class TestEditorApi(OwnSource):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        import frames
        import web as webmod
        await frames.refresh_frames(None)
        _, editor = webmod.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()
        self.old, runtime.SESSION = runtime.SESSION, self.session

    async def asyncTearDown(self):
        runtime.SESSION = self.old
        await self.ed.close()
        await super().asyncTearDown()

    async def test_test_says_what_it_fills(self):
        srcs = feeds.load(support.config.DATA_DIR)
        r = await (await self.ed.post("/api/sources/test", json=srcs[0])).json()
        self.assertEqual(r["fills"], "Fills Racing pages: 2 races")
        r = await (await self.ed.post("/api/sources/test", json=srcs[3])).json()
        self.assertIn("no list of races", r["error"])

    async def test_the_inspector_gets_its_fields(self):
        el = {"type": "sports_match", "league": "soccer/eng.1", "data": {"source": "g1"}}
        r = await (await self.ed.post("/api/widget_data", json={"element": el})).json()
        self.assertEqual(r["source"]["name"], "Source “games”")
        self.assertEqual(r["services"], [], "it reads none of the add-on's services")
        fields = {f["label"]: f["value"] for f in r["fields"]}
        self.assertEqual((fields["Home"], fields["Away"], fields["Score"], fields["Status"]), ("Home Town", "Away City", "2–1", "Playing"))
        r = await (await self.ed.post("/api/widget_data", json={"element": {"type": "sports_match", "data": {"source": "gone"}}})).json()
        self.assertTrue(r["source"]["missing"])
        self.assertEqual((await self.ed.post("/api/widget_data", json={"element": {"type": "text"}})).status, 400)


if __name__ == "__main__":
    unittest.main()
