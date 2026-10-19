"""Outside services: never in the way, never silent, never leaking a secret.

* A data source is fetched in the background: a slow or silent server never
  holds up a render (audit 2026-10-19, finding 2).
* A configured source that is failing keeps its Home Assistant entity; one
  that was removed is withdrawn (finding 3).
* Every service reports its health, and Home Assistant gets a problem sensor.
* No error text carries the add-on's token or a source's key (finding 1).
* An aircraft list too old to trust is not shown (finding 7).
"""
import asyncio
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402

import config  # noqa: E402
import entities  # noqa: E402
import feeds  # noqa: E402
import frames  # noqa: E402
import ha  # noqa: E402
import health  # noqa: E402
import mqtt_bridge  # noqa: E402
import runtime  # noqa: E402
from feeds import statistics  # noqa: E402
from sources import flights  # noqa: E402

SECRET = "TOP-SECRET-TOKEN-0123456789"


class Server:
    """A local HTTP server: slow, silent, or answering 502."""

    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/slow", self.slow)
        self.app.router.add_get("/websocket", self.silent_ws)
        self.app.router.add_route("*", "/bad/{tail:.*}", self.bad)

    async def slow(self, request):
        await asyncio.sleep(3)
        return web.json_response({"v": 1})

    async def silent_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await asyncio.sleep(2)
        return ws

    async def bad(self, request):
        return web.Response(status=502, text="502: Bad Gateway")

    async def __aenter__(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        await self.runner.cleanup()


class FakeTransport:
    connected = True

    def __init__(self):
        self.log = []

    async def publish(self, topic, payload, retain=True):
        self.log.append((topic, payload))
        return True

    async def subscribe(self, topic):
        pass


class FakeHass:
    async def ws(self, payload):
        return []

    async def rest(self, *a, **k):
        return None


class TestSourcesStayOutOfTheWay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config.DATA_DIR = Path(tempfile.mkdtemp())
        runtime.LIVE = type(runtime.LIVE)()
        health.reset()

    async def test_a_slow_source_does_not_hold_up_the_render(self):
        async with Server() as srv, aiohttp.ClientSession() as s:
            runtime.SESSION = s
            feeds.save(config.DATA_DIR, [{"type": "rest", "name": "slowthing", "url": f"{srv.base}/slow"}])
            start = time.monotonic()
            await frames.refresh_frames(s)
            self.assertLess(time.monotonic() - start, 2, "the render waited on a data source")

    async def test_a_silent_statistics_websocket_gives_up(self):
        async with Server() as srv, aiohttp.ClientSession() as s:
            old = statistics.TIMEOUT
            statistics.TIMEOUT = 0.5
            try:
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(statistics.fetch(
                        {"name": "x", "entity": "sensor.energy"},
                        {"ha_base": srv.base, "ha_token": "t", "session": s}), 5)
            finally:
                statistics.TIMEOUT = old


class TestEntitiesSurviveOutages(unittest.IsolatedAsyncioTestCase):
    async def test_failing_source_keeps_its_entity_and_a_removed_one_goes(self):
        now = [1_000_000.0]
        t = FakeTransport()
        pub = mqtt_bridge.EntityPublisher(t, FakeHass(), tempfile.mkdtemp(), "test", clock=lambda: now[0])
        await pub._on_connect()
        for _ in range(120):                              # two healthy hours
            pub.set("sensor.epaper_watch", "Severance", {})
            pub.set("sensor.epaper_old", "1", {})
            pub.keep({"sensor.epaper_watch", "sensor.epaper_old"})
            await pub.sync()
            now[0] += 60
        for _ in range(180):                              # watch's server is off for three hours; old is removed
            pub.keep({"sensor.epaper_watch"})
            await pub.sync()
            now[0] += 60
        cleared = {topic for topic, payload in t.log if payload == "" and topic.endswith("/config")}
        self.assertNotIn("homeassistant/sensor/epaper_panel/epaper_watch/config", cleared)
        self.assertIn("homeassistant/sensor/epaper_panel/epaper_old/config", cleared)

    async def test_problem_sensor_is_a_binary_sensor(self):
        t = FakeTransport()
        pub = mqtt_bridge.EntityPublisher(t, FakeHass(), tempfile.mkdtemp(), "test")
        await pub._on_connect()
        pub.set_problem("espn", "ESPN", True, {"error": "HTTP 503"})
        await pub.sync()
        topics = dict(t.log)
        self.assertIn("homeassistant/binary_sensor/epaper_panel/epaper_problem_espn/config", topics)
        self.assertIn('"device_class": "problem"', topics["homeassistant/binary_sensor/epaper_panel/epaper_problem_espn/config"])
        self.assertEqual(topics["epaper_panel/epaper_problem_espn/state"], "ON")


class TestHealth(unittest.TestCase):
    def setUp(self):
        health.reset()
        self.now = [5000.0]
        health.clock = lambda: self.now[0]

    def tearDown(self):
        health.clock = time.time

    def test_a_blip_is_not_a_problem_but_a_lasting_failure_is(self):
        with contextlib.redirect_stdout(io.StringIO()):
            health.fail("ESPN", "HTTP 503 from site.api.espn.com")
            self.assertFalse(health.status()[0]["problem"])
            self.now[0] += health.GRACE + 1
            health.fail("ESPN", "HTTP 503 from site.api.espn.com")
            self.assertTrue(health.status()[0]["problem"])
            health.ok("ESPN")
        self.assertFalse(health.status()[0]["problem"])

    def test_a_service_nobody_uses_is_forgotten_after_a_day(self):
        health.ok("OpenSky")
        self.now[0] += health.FORGET_AFTER + 1
        self.assertEqual(health.status(), [])


class TestNoSecretsInErrors(unittest.IsolatedAsyncioTestCase):
    async def test_failures_never_print_the_token_or_a_key(self):
        out = io.StringIO()
        async with Server() as srv, aiohttp.ClientSession() as s:
            old_base, old_token = ha.HA_BASE, ha.HA_TOKEN
            ha.HA_BASE, ha.HA_TOKEN = f"{srv.base}/bad", SECRET
            try:
                with contextlib.redirect_stdout(out):
                    try:
                        await ha.ha_json(s, "/states/weather.home")
                    except Exception as exc:
                        print(f"fetch_weather_forecast error: {health.describe(exc)}")
                    errors = []
                    await feeds.run_all([
                        {"type": "jellyfin", "name": "jelly", "base": f"{srv.base}/bad", "key": SECRET, "user": "x"},
                        {"type": "rest", "name": "r", "url": f"{srv.base}/bad/x?api_key={SECRET}",
                         "headers": f"Authorization: Bearer {SECRET}"},
                    ], {"session": s}, errors)
            finally:
                ha.HA_BASE, ha.HA_TOKEN = old_base, old_token
        text = out.getvalue() + " ".join(errors)
        self.assertIn("HTTP 502", text)
        self.assertNotIn(SECRET, text)

    def test_describe_redacts_secrets_in_plain_messages(self):
        text = health.describe(ValueError(f"Authorization: Bearer {SECRET} at http://x/y?token={SECRET}"))
        self.assertNotIn(SECRET, text)


class TestOldAircraftAreNotShown(unittest.IsolatedAsyncioTestCase):
    async def test_a_list_older_than_max_age_is_dropped(self):
        clock = [1000.0]
        store = type(runtime.LIVE)(clock=lambda: clock[0])
        answers = [[{"callsign": "ROT123"}]]

        async def fetch():
            if answers:
                return answers.pop()
            raise LookupError("no aircraft service answered")

        self.assertIsNone(await store.read(("f",), fetch, 30, stale_after=flights.MAX_AGE))
        await asyncio.sleep(0.01)
        self.assertEqual(await store.read(("f",), fetch, 30, stale_after=flights.MAX_AGE), [{"callsign": "ROT123"}])
        clock[0] += flights.MAX_AGE + 31
        await store.read(("f",), fetch, 30, stale_after=flights.MAX_AGE)      # schedules a fetch that fails
        await asyncio.sleep(0.01)
        self.assertIsNone(await store.read(("f",), fetch, 30, stale_after=flights.MAX_AGE))

    async def test_nothing_overhead_clears_the_closest_aircraft(self):
        runtime.PUBLISHED.clear()
        runtime.PUBLISHED["sensor.epaper_closest_aircraft"] = {"state": "PGT76LZ", "attributes": {}}

        async def none_overhead(session, **kw):
            return []
        old = entities.fetch_overhead_aircraft
        entities.fetch_overhead_aircraft = none_overhead
        try:
            await entities.publish_flights(None, None, None, 35.0, "")
        finally:
            entities.fetch_overhead_aircraft = old
        self.assertEqual(runtime.PUBLISHED["sensor.epaper_flights_overhead"]["state"], "0")
        self.assertEqual(runtime.PUBLISHED["sensor.epaper_closest_aircraft"]["state"], "")


if __name__ == "__main__":
    unittest.main()
