"""How often a free public service may be asked again after it failed: one rule for all of them.

A service that answers "slow down" (429), is down, or sends something unreadable is not asked
again at every tick. Each failure doubles the wait, from the reader's own interval up to `most`;
a service that says how long to wait (Retry-After) is waited for that long, within `most`. The
first answer that works ends it. While a wait runs nothing is sent at all: the reader raises
`Waiting`, live_data keeps the last good value (the page shows it with its age), and health keeps
the failure it already has (no request, so no new news either way).

Try again in Settings › Services (services.Service.forget) ends every wait of its service at once.

    PACE = pacing.Pace("Yahoo Finance", first=300, most=3600)
    PACE.check()                      # raises Waiting while a wait runs
    PACE.failed(retry_after="120")    # after a failure
    PACE.ok()                         # after an answer that worked
"""
from __future__ import annotations

import time

clock = time.time


class Waiting(LookupError):
    """Not asked: the service is being given time after it failed."""


def retry_after(headers) -> float | None:
    """Seconds a Retry-After header asks for (a number of seconds; a date is read as unknown)."""
    try:
        raw = (headers or {}).get("Retry-After")
        return max(0.0, float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError, AttributeError):
        return None


class Pace:
    def __init__(self, service: str, first: float, most: float = 3600.0):
        self.service, self.first, self.most = service, float(first), float(most)
        self.failures = 0
        self.until = 0.0

    def waiting(self) -> float:
        """Seconds left of the current wait, 0 when it may be asked."""
        return max(0.0, self.until - clock())

    def check(self) -> None:
        left = self.waiting()
        if left > 0:
            raise Waiting(f"{self.service} is given {int(left // 60) + 1} min more after it failed")

    def failed(self, retry_after: float | str | None = None) -> float:
        """Record a failure; returns how long it now waits."""
        self.failures += 1
        wait = self.first * (2 ** (self.failures - 1))
        try:
            asked = float(retry_after) if retry_after not in (None, "") else None
        except (TypeError, ValueError):
            asked = None
        if asked is not None:
            wait = max(wait, asked)
        wait = min(self.most, wait)
        self.until = clock() + wait
        return wait

    def ok(self) -> None:
        self.failures, self.until = 0, 0.0

    forget = ok                        # a person's Try again: ask at once


# How the add-on names itself to the free services that ask for it (Wikimedia does): a
# stable name and where to find who runs it, never a browser's or a library's default.
def user_agent() -> str:
    import config
    return f"epaper-panel/{config.ADDON_VERSION} (Home Assistant add-on; +https://github.com/bek00letz/epaper-panel)"


LIMIT = 8 * 1024 * 1024                 # no answer any of these services sends is bigger


class Missing(LookupError):
    """The service answered that it has no such thing (404): an answer, not a failure."""


async def get(session, url: str, pace: Pace, *, method: str = "GET", data=None, as_text: bool = False,
              missing_ok: bool = False, timeout: float = 20.0):
    """One polite request to a free service: its JSON (or text), within the pace. A refusal or a
    failure starts or lengthens the wait (Retry-After honoured) and raises; health has said so
    (the trace, or here for an answer it can't read). `missing_ok`: a 404 is Missing, not a failure."""
    import aiohttp
    import json as _json
    import health
    pace.check()
    try:
        async with session.request(method, url, data=data, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip"},
                                   timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=10),
                                   trace_request_ctx=health.Ask(missing_ok=missing_ok, judged=True)) as r:
            if r.status == 404 and missing_ok:
                raise Missing(url)
            if r.status != 200:
                pace.failed(retry_after(r.headers))
                health.fail(pace.service, f"HTTP {r.status} from {r.url.host}")
                raise LookupError(f"HTTP {r.status}")
            raw, too_big = b"", False
            async for chunk in r.content.iter_chunked(64 * 1024):     # to the end: read(n) stops at what has arrived
                raw += chunk
                if len(raw) > LIMIT:
                    too_big = True
                    break
    except (Missing, LookupError):
        raise
    except Exception as exc:            # noqa: BLE001 -- unreachable, timed out: the trace has said so
        pace.failed()
        raise LookupError(health.describe(exc)) from None
    if too_big:
        pace.failed()
        health.fail(pace.service, "it answered with far more than it should")
        raise LookupError("too big")
    text = raw.decode("utf-8", "replace")
    if as_text:
        return text
    try:
        return _json.loads(text)
    except ValueError:
        pace.failed()
        health.fail(pace.service, "it answered, but not in the form the add-on reads")
        raise LookupError("not JSON") from None


def answered(pace: Pace) -> None:
    """The answer was read: the service is fine and its wait is over."""
    import health
    pace.ok()
    health.ok(pace.service)


def unreadable(pace: Pace, what: str) -> None:
    """The answer came but isn't what the service sends: a problem to say, and a wait."""
    import health
    pace.failed()
    health.fail(pace.service, f"its {what} isn't in the form the add-on reads")
