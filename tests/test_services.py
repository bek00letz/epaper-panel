"""Outside services in the editor (services.py): one list the status card, Settings › Services,
health and the fetchers read.

* Every service says what uses it, how it's doing in plain words, and can be tried again.
* Another address is used only once the add-on's own reader has read a test answer from it, and
  it's refused with the reason otherwise. Use the original address is the way back.
* A mirror reports as its service, so its problem sensor is the same one.
"""
import asyncio
import contextlib
import io
import json
import unittest
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import support
import health
import runtime
import services
from sources import racing


def calendar(year: int) -> dict:
    return {"races": [{"name": "Test Grand Prix", "location": "Testville",
                       "sessions": {"qualifying": f"{year}-06-06T14:00:00Z", "gp": f"{year}-06-07T13:00:00Z"}}]}


class Mirror:
    """A local server in place of an outside service: a racing calendar mirror, a wrong one, a broken one."""

    def __init__(self):
        year = datetime.now(timezone.utc).year
        self.down = False
        self.app = web.Application()
        self.app.router.add_get(f"/good/f1/{year}.json",
                                lambda r: web.Response(status=404) if self.down else web.json_response(calendar(year)))
        self.app.router.add_get(f"/odd/f1/{year}.json", lambda r: web.json_response({"races": "not a list"}))
        self.app.router.add_get(f"/html/f1/{year}.json", lambda r: web.Response(text="<html>hello</html>"))
        self.app.router.add_get(f"/down/f1/{year}.json", lambda r: web.Response(status=503))

    async def __aenter__(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        await self.runner.cleanup()


class TestRegistry(unittest.TestCase):
    def test_what_uses_a_service_comes_from_the_pages(self):
        pages = [("Football", {"elements": [{"type": "sports_match", "league": "soccer/eng.1"}]}),
                 ("Formula E", {"elements": [{"type": "sports_racing", "series": "fe"}]}),
                 ("NASCAR", {"elements": [{"type": "sports_racing", "series": "nascar"}]}),
                 ("Planes", {"elements": [{"type": "flight_tracker"}]}),
                 ("My team", {"elements": [{"type": "sports_match", "entity": "sensor.team_tracker"}]}),
                 ("Updates", {"elements": [{"type": "badge", "counts": "all"}]})]
        used = {s["id"]: s["used_by"] for s in services.listing(pages)}
        self.assertEqual(used["espn"], ["Football", "NASCAR"], "a Team Tracker sensor isn't ESPN; Formula E isn't on it")
        self.assertEqual(used["racing_calendar"], ["Formula E"])
        self.assertEqual(used["formula_e"], ["Formula E"])
        self.assertEqual(used["flightradar24"], ["Planes"])
        self.assertEqual(used["opensky"], ["Planes"])
        self.assertEqual(used["home_assistant_repairs"], ["Updates"], "a badge counting everything asks for repairs")
        self.assertEqual(used["iconify"], [])

    def test_groups_in_order(self):
        groups = [s["group"] for s in services.listing([])]
        self.assertEqual(groups, sorted(groups, key=["outside", "home", "source"].index))

    def test_errors_in_plain_words(self):
        said = {
            "HTTP 503 from site.api.espn.com": "It's having trouble on its side (error 503).",
            "HTTP 404 Not Found from raw.githubusercontent.com/x": "It doesn't have what the add-on asks for there (error 404).",
            "HTTP 429 from opensky-network.org": "It asked the add-on to slow down (error 429). The add-on tries again later on its own.",
            "TimeoutError": "It didn't answer in time.",
            "ClientConnectorError: Cannot connect to host x:443 ssl:default": "Home Assistant couldn't connect to it. Check that Home Assistant is online.",
            "ClientConnectorDNSError: Cannot connect to host x:443 ssl:default [nodename nor servname provided]":
                "Home Assistant couldn't find it on the internet. Check that Home Assistant is online.",
            "its calendar page has no races in it": "Its calendar page has no races in it.",
            "RuntimeError: boom": "Something went wrong asking it.",
            "ClientConnectorCertificateError: Cannot connect to host x:443 ssl:True [SSLCertVerificationError]":
                "Its secure connection couldn't be checked.",
        }
        for raw, words in said.items():
            self.assertEqual(services.plain(raw), words, raw)

    def test_an_address_is_a_plain_web_address(self):
        for bad in ("ftp://x/y", "mirror.example.com", "https://x/y?key=1", "https://me:pw@x/y", "https://x/{year}"):
            with self.assertRaises(services.Refused, msg=bad):
                services.clean_address(bad)
        self.assertEqual(services.clean_address(" https://mirror.example.com/cal/ "), "https://mirror.example.com/cal")


class TestAnotherAddress(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        health.reset()

    async def asyncTearDown(self):
        support.use_test_data_dir()
        health.reset()

    async def test_a_mirror_in_the_same_form_is_used_and_reports_as_its_service(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            got = await services.set_address(s, "racing_calendar", "main", m.base + "/good/")
        self.assertIn("1 race", got["said"])
        self.assertEqual(services.url("racing_calendar"), m.base + "/good")
        self.assertEqual(json.loads((support.config.DATA_DIR / "services.json").read_text()),
                         {"racing_calendar": {"main": m.base + "/good"}}, "only what differs is stored")
        self.assertEqual(racing._sportstimes("f1").url, m.base + "/good/f1/{year}.json", "the calendars ask the mirror")
        self.assertEqual(health.service_for(m.base + "/good/f1/2026.json"), "Racing calendar",
                         "so its problem sensor is the racing calendar's")
        self.assertEqual(health.service_for(services.get("racing_calendar").addresses[0].original + "/f1/2026.json"),
                         "Racing calendar", "and the original still is")

    async def test_the_original_is_the_way_back(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            await services.set_address(s, "racing_calendar", "main", m.base + "/good")
            said = await services.set_address(s, "racing_calendar", "main", "")
        self.assertEqual(said["said"], "Back to the original address.")
        self.assertEqual(services.url("racing_calendar"), services.get("racing_calendar").addresses[0].original)
        self.assertIsNone(health.service_for(m.base + "/good/f1/2026.json"))

    async def test_an_address_in_another_form_is_refused_with_the_reason(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            for where, words in (("/odd", "not with a race calendar"), ("/html", "isn't JSON"),
                                 ("/down", "trouble on its side (error 503)"), ("/nothing", "error 404")):
                with self.subTest(where), self.assertRaises(services.Refused) as said:
                    await services.set_address(s, "racing_calendar", "main", m.base + where)
                self.assertIn(words, str(said.exception))
            with self.assertRaises(services.Refused) as said:
                await services.set_address(s, "racing_calendar", "main", "http://127.0.0.1:9/")
            self.assertIn("couldn't connect", str(said.exception))
        self.assertEqual(services.url("racing_calendar"), services.get("racing_calendar").addresses[0].original,
                         "nothing refused is kept")
        self.assertFalse((support.config.DATA_DIR / "services.json").exists())

    async def test_home_assistant_has_no_address_to_change(self):
        with self.assertRaises(KeyError):
            await services.set_address(None, "energy_dashboard", "main", "https://example.com")


class TestTryAgain(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        health.reset()

    async def asyncTearDown(self):
        support.use_test_data_dir()
        health.reset()

    async def test_it_answers_and_is_fine_again(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            await services.set_address(s, "racing_calendar", "main", m.base + "/good")
            health.fail("Racing calendar", "HTTP 503 from x")
            racing._calendar_cache["https://x/failed"] = {"at": 0, "ok": False, "races": None}
            got = await services.try_again(s, "racing_calendar")
        self.assertTrue(got["ok"], got)
        entry = next(e for e in health.status() if e["name"] == "Racing calendar")
        self.assertIsNone(entry["failing_since"])
        self.assertNotIn("https://x/failed", racing._calendar_cache, "a calendar that failed is asked again at once")

    async def test_it_fails_in_plain_words(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            await services.set_address(s, "racing_calendar", "main", m.base + "/good")
            m.down = True                             # the mirror stops serving it
            with contextlib.redirect_stdout(io.StringIO()):
                got = await services.try_again(s, "racing_calendar")
        self.assertFalse(got["ok"])
        self.assertIn("error 404", got["error"])
        self.assertIsNotNone(next(e for e in health.status() if e["name"] == "Racing calendar")["failing_since"])

    async def test_failed_live_values_are_asked_again(self):
        store = type(runtime.LIVE)(clock=lambda: 1000.0)

        async def broken():
            raise LookupError("no")
        await store.read(("x",), broken, 600)
        await asyncio.sleep(0.01)
        self.assertNotEqual(store._entries[("x",)].attempted_at, float("-inf"))
        store.retry_failed()
        self.assertEqual(store._entries[("x",)].attempted_at, float("-inf"))

    async def test_a_problem_shows_on_the_status_card(self):
        now = [1000.0]
        old, health.clock = health.clock, lambda: now[0]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                health.fail("ESPN", "HTTP 503 from site.api.espn.com")
            self.assertEqual(services.problems(), [], "not before its problem sensor is on")
            now[0] += health.GRACE
            self.assertEqual(services.problems(), [{"id": "espn", "name": "ESPN", "since": 1000.0,
                                                    "error": "HTTP 503 from site.api.espn.com",
                                                    "plain": "It's having trouble on its side (error 503)."}])
        finally:
            health.clock = old


class TestEditorApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.fresh_data_dir()
        health.reset()
        import frames
        import web as webmod
        await frames.refresh_frames(None)
        _, editor = webmod.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        support.use_test_data_dir()

    async def test_every_service_is_listed(self):
        body = await (await self.ed.get("/api/services")).json()
        ids = [s["id"] for s in body["services"]]
        self.assertEqual(ids[:len(services.SERVICES)], [s.id for s in services.SERVICES])
        espn = body["services"][0]
        self.assertEqual(espn["addresses"][0]["current"], espn["addresses"][0]["original"])
        self.assertFalse(espn["asked"])

    async def test_a_refused_address_says_why(self):
        async with Mirror() as m, aiohttp.ClientSession() as s:
            old, runtime.SESSION = runtime.SESSION, s
            try:
                r = await self.ed.put("/api/services/racing_calendar/address", json={"key": "main", "address": m.base + "/odd"})
                self.assertEqual(r.status, 422)
                self.assertIn("race calendar", (await r.json())["error"])
                r = await self.ed.put("/api/services/racing_calendar/address", json={"address": m.base + "/good"})
                self.assertEqual(r.status, 200)
                body = await r.json()
                self.assertTrue(body["ok"])
                cal = next(x for x in body["services"] if x["id"] == "racing_calendar")
                self.assertEqual(cal["addresses"][0]["current"], m.base + "/good")
            finally:
                runtime.SESSION = old

    async def test_no_such_service(self):
        self.assertEqual((await self.ed.post("/api/services/nope/try")).status, 404)
        self.assertEqual((await self.ed.put("/api/services/energy_dashboard/address", json={"address": "https://x"})).status, 404)

    async def test_the_status_says_which_are_failing(self):
        body = await (await self.ed.get("/api/status")).json()
        self.assertEqual(body["service_problems"], [])


if __name__ == "__main__":
    unittest.main()
