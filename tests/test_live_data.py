"""Rendering never waits on outside services."""
import asyncio
import time
import unittest

import support  # noqa: F401
import live_data


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestLiveData(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.store = live_data.LiveData(clock=self.clock)
        self.calls = []
        self.gate = asyncio.Event()

        @self.store.decorate(30, lambda: "shared-session")
        async def slow_feed(session, league, fallback=None):
            self.calls.append((session, league, fallback))
            await self.gate.wait()                       # a slow outside service
            return {"league": league, "seen": fallback}

        self.feed = slow_feed

    async def test_first_read_returns_at_once_then_the_value_lands(self):
        start = time.monotonic()
        self.assertEqual(await self.feed(None, "eng.1", fallback="nothing yet"), "nothing yet")
        self.assertLess(time.monotonic() - start, 0.05, "a render must not wait on the service")
        self.gate.set()
        self.assertTrue(await self.store.wait_for_news(1), "first arrival wakes the render loop")
        self.assertEqual(await self.feed(None, "eng.1", fallback="x"), {"league": "eng.1", "seen": "nothing yet"})
        self.assertEqual(self.calls[0][0], "shared-session")

    async def test_stale_value_served_while_refreshing_and_kept_on_failure(self):
        self.gate.set()
        await self.feed(None, "eng.1")
        await self.store.wait_for_news(1)
        n = len(self.calls)
        self.assertIsNotNone(await self.feed(None, "eng.1"))
        self.assertEqual(len(self.calls), n, "fresh value: no new fetch")

        self.clock.t += 31
        boom = True

        async def failing(session, *a, **k):
            if boom:
                raise RuntimeError("ESPN is down")
        entry = next(iter(self.store._entries.values()))
        entry.factory = lambda: failing(None)
        self.store.tick()
        await asyncio.sleep(0.01)
        self.assertEqual(entry.error, "RuntimeError: ESPN is down")
        self.assertEqual(entry.value, {"league": "eng.1", "seen": None}, "a failure keeps the last good value")

    async def test_fallback_is_input_but_not_identity(self):
        self.gate.set()
        await self.feed(None, "eng.1", fallback="a")
        await self.feed(None, "eng.1", fallback="b")
        self.assertEqual(len(self.store._entries), 1, "different fallbacks are the same value")

    async def test_preview_can_wait_for_a_value_it_never_had(self):
        self.gate.set()
        with live_data.waiting_for_fresh():
            self.assertEqual(await self.feed(None, "usa.1"), {"league": "usa.1", "seen": None})

    async def test_unread_values_are_forgotten(self):
        self.gate.set()
        await self.feed(None, "eng.1")
        await asyncio.sleep(0.01)
        self.clock.t += live_data.FORGET_AFTER + 1
        self.store.tick()
        self.assertEqual(self.store._entries, {})


class TestServerRendersWithoutWaiting(unittest.IsolatedAsyncioTestCase):
    async def test_every_outside_fetcher_goes_through_the_store(self):
        from sources import energy, flights, ha_services, home, racing, sports, station
        for mod, name in ((flights, "fetch_overhead_aircraft"), (ha_services, "fetch_weather_forecast"),
                          (ha_services, "fetch_calendar_events"), (racing, "fetch_racing_data"),
                          (racing, "compute_racing_active_window"), (sports, "compute_sports_active_window"),
                          (sports, "fetch_sports_match"), (home, "fetch_sun"), (home, "fetch_now_playing"), (station, "fetch_station"), (energy, "fetch_dashboard"),
                          (energy, "fetch_total"), (energy, "fetch_grid_power"), (energy, "fetch_grid_hours"),
                          (energy, "fetch_cost")):
            self.assertTrue(hasattr(getattr(mod, name), "direct"), name)


if __name__ == "__main__":
    unittest.main()
