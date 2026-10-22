"""Outside data, fetched in the background; rendering only ever reads it.

ESPN, Flightradar24, OpenSky, racing calendars, weather and calendar services
can each take seconds or fail outright. If a render waited on them, every
panel update and every editor preview would wait too, and an outage anywhere
would show up as a stalled panel. Instead:

  * the first read of a value schedules a fetch and returns at once (the
    caller's fallback, usually "nothing yet"); when the value lands, the
    render loop is woken so it appears within seconds;
  * later reads return the latest value at once, and a background loop keeps
    it fresh on its own cadence;
  * a failed fetch keeps the last good value, unless the value has a
    `stale_after` age and is older than that (an aircraft list from an hour
    ago is worse than none);
  * a value nobody has read for a while is dropped.

The editor's preview can ask to wait for a value it has never had
(`waiting_for_fresh()`), because there a person asked for it.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import time
from dataclasses import dataclass, field

_wait_for_fresh = contextvars.ContextVar("live_wait_for_fresh", default=False)

FETCH_TIMEOUT = 20.0
FORGET_AFTER = 900.0
TICK = 2.0
MAX_IN_FLIGHT = 4


@contextlib.contextmanager
def waiting_for_fresh():
    """Within this block, a value never fetched before is fetched and waited for."""
    token = _wait_for_fresh.set(True)
    try:
        yield
    finally:
        _wait_for_fresh.reset(token)


@dataclass
class _Entry:
    factory: object
    interval: float
    value: object = None
    has_value: bool = False
    attempted_at: float = float("-inf")
    last_read: float = 0.0
    inflight: asyncio.Task | None = None
    error: str | None = None
    name: str = ""
    ok_at: float = float("-inf")
    stale_after: float | None = None


@dataclass
class LiveData:
    clock: object = time.monotonic
    _entries: dict = field(default_factory=dict)
    _news: asyncio.Event | None = None

    # ------------------------------------------------------------------ reading
    async def read(self, key, factory, interval: float, stale_after: float | None = None):
        now = self.clock()
        e = self._entries.get(key)
        if e is None:
            e = self._entries[key] = _Entry(factory=factory, interval=interval, name=str(key[0]))
        e.factory, e.interval, e.last_read, e.stale_after = factory, interval, now, stale_after
        if not e.has_value and _wait_for_fresh.get():
            await self._fetch(e)
        elif now - e.attempted_at >= e.interval:
            self._schedule(e)
        if not e.has_value or (e.stale_after is not None and now - e.ok_at > e.stale_after):
            return None
        return e.value

    def decorate(self, interval: float, session_getter, stale_after: float | None = None):
        """Make an `async def f(session, ...)` read from this store.

        Its `fallback=` argument (if any) is what callers get while there is no
        value yet. It is also input (an entity's current state, say), so the
        next background fetch gets the latest one; but it isn't part of what
        identifies the value, or every render would be a new value.
        """
        def wrap(fn):
            @functools.wraps(fn)
            async def reader(session, *args, **kwargs):
                fallback = kwargs.get("fallback")
                key = (fn.__name__, args, tuple(sorted((k, v) for k, v in kwargs.items() if k != "fallback")))

                async def fetch():
                    return await fn(session_getter() or session, *args, **kwargs)

                value = await self.read(key, fetch, interval, stale_after)
                return fallback if value is None else value

            reader.direct = fn          # the network call itself, for tests
            reader.interval = interval  # how often its value is fetched (widgets.Widget.changes_every)
            return reader
        return wrap

    # ------------------------------------------------------------------ background
    async def run(self):
        while True:
            self.tick()
            await asyncio.sleep(TICK)

    def tick(self):
        now = self.clock()
        in_flight = sum(1 for e in self._entries.values() if e.inflight is not None)
        for key, e in list(self._entries.items()):
            if now - e.last_read > FORGET_AFTER:
                if e.inflight is None:
                    del self._entries[key]
                continue
            if in_flight < MAX_IN_FLIGHT and e.inflight is None and now - e.attempted_at >= e.interval:
                self._schedule(e)
                in_flight += 1

    async def wait_for_news(self, timeout: float) -> bool:
        """Sleep up to `timeout`; wake early when a value arrives for the first time."""
        news = self._event()
        try:
            await asyncio.wait_for(news.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            news.clear()

    def retry_failed(self):
        """Values whose last fetch failed are fetched again at the next tick (a person's Try again)."""
        for e in self._entries.values():
            if e.error is not None:
                e.attempted_at = float("-inf")

    def status(self) -> list[dict]:
        now = self.clock()
        return [{"source": e.name, "has_value": e.has_value, "error": e.error,
                 "age_s": None if e.attempted_at == float("-inf") else round(now - e.attempted_at)}
                for e in self._entries.values()]

    # ------------------------------------------------------------------ internals
    def _event(self) -> asyncio.Event:
        if self._news is None:
            self._news = asyncio.Event()
        return self._news

    def _schedule(self, e: _Entry):
        if e.inflight is None:
            e.inflight = asyncio.get_running_loop().create_task(self._fetch(e))

    async def _fetch(self, e: _Entry):
        if e.inflight is not None and e.inflight is not asyncio.current_task():
            await asyncio.shield(e.inflight)
            return
        e.attempted_at = self.clock()
        try:
            value = await asyncio.wait_for(e.factory(), FETCH_TIMEOUT)
            first = not e.has_value
            e.value, e.has_value, e.error, e.ok_at = value, True, None, self.clock()
            if first:
                self._event().set()
        except Exception as exc:
            import health
            msg = health.describe(exc)
            if e.error != msg:
                print(f"live data: {e.name} failed ({msg}); keeping the last value", flush=True)
            e.error = msg
        finally:
            if e.inflight is asyncio.current_task():
                e.inflight = None
