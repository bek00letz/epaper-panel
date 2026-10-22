"""When things happen on the clock: the render cycle just after each minute starts, and every
device's next fetch or wake a couple of seconds after it.

A clock on a page is drawn by the render cycle and shown when a device next fetches. Counted
from whenever the add-on and the device happened to start, the two drift apart: a panel that
fetches at :19 shows a clock drawn up to a minute before, for another minute. Lined up with
the start of each minute, the time on screen is right within a few seconds.

- **The render cycle** (`next_render`) starts half a second into each minute. A
  `refresh_seconds` under a minute adds renders at whole multiples of it within the minute;
  longer, it renders on whole minutes, every so many from midnight in Home Assistant's time
  zone (5 minutes: :00, :05, :10). A render that runs past the next one's start is followed by
  another at once, and the log says so (`after_render`): a minute is never skipped silently.
- **A device asks** `fetch_second()` into the minute: once the render has usually finished
  (the slowest of the last few renders, plus a margin). An always-on panel is told the
  milliseconds until then on every answer (`until_next_fetch_ms`, the `X-EPF-Next` header); a
  device that sleeps between updates has its sleep cut to wake then (`align_sleep`).

The add-on's own clock is the one clock: the devices need none, as every hint is "this long
from now". Whole minutes start at the same moment in every time zone (all offsets are whole
minutes), so only the multi-minute grid needs Home Assistant's.
"""
from __future__ import annotations

import math
import time
from collections import deque
from datetime import datetime, tzinfo

RENDER_AT = 0.5             # seconds into the minute the render cycle starts
MARGIN = 1.5                # after a render's usual end, before a device asks
USUAL_RENDER = 1.0          # seconds, until a render has been timed
FETCH_LATEST = 20.0         # seconds into the minute: never later, however slow renders are
LATE_NOTE = 5.0             # seconds late before the log says a render ran long
MIN_HINT = 2.0              # an always-on panel never asks again sooner than this
MIN_SLEEP = 30              # a kind's shortest sleep unless it says (Kind.shortest_sleep; a CrowPanel's epf_core.h MIN_SLEEP_SEC)

_took: deque[float] = deque(maxlen=10)
wall_clock = time.time        # the add-on's clock (a test sets its own)


def zone(name: str | None) -> tzinfo | None:
    """Home Assistant's time zone by name; None (the add-on's own) when it can't be had."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


# ---------------------------------------------------------------- the render cycle

def _slot_starts(after: float, refresh: int, tz: tzinfo | None):
    """The moments a render is due, from the minute `after` is in, in order."""
    minute = math.floor(after / 60) * 60
    if refresh < 60:
        for start in (minute, minute + 60):
            for k in range(0, 60, max(1, refresh)):
                yield start + k
        return
    every = max(1, round(refresh / 60))
    for i in range(24 * 60 + 2):
        t = minute + 60 * i
        local = datetime.fromtimestamp(t, tz) if tz else datetime.fromtimestamp(t).astimezone()
        if (local.hour * 60 + local.minute) % every == 0:
            yield t


def next_render(after: float, refresh: int, tz: tzinfo | None = None) -> float:
    """When the next render starts (epoch seconds): RENDER_AT past the first slot that begins
    after `after`. A render that started once a slot had begun covers it, so one started at
    :00.2 (outside data arriving) makes the :00.5 one unneeded, and one at :59.8 doesn't."""
    for start in _slot_starts(after, refresh, tz):
        if start > after:
            return start + RENDER_AT
    return math.floor(after / 60) * 60 + 60 + RENDER_AT     # a day without a slot: can't happen


def after_render(started: float, now: float, refresh: int, tz: tzinfo | None = None) -> tuple[float, str | None]:
    """How long to wait before the next render, and what to log when it's late. A render that
    ran past the next one's start is followed by another at once, never by skipping it."""
    due = next_render(started, refresh, tz)
    if now < due:
        return due - now, None
    late = now - (due - RENDER_AT)
    if late < LATE_NOTE:
        return 0.0, None
    at = (datetime.fromtimestamp(due, tz) if tz else datetime.fromtimestamp(due).astimezone()).strftime("%H:%M:%S")
    return 0.0, (f"render took {now - started:.0f} s, past the start of the one due at {at}: "
                 f"drawing again now, {late:.0f} s late")


def note_render(seconds: float) -> None:
    """How long a render took (frames.refresh_frames), for when devices should ask."""
    if seconds >= 0:
        _took.append(float(seconds))


# ---------------------------------------------------------------- devices

def fetch_second() -> float:
    """Seconds into the minute a device should ask: after the render has usually finished."""
    slowest = max(_took) if _took else USUAL_RENDER
    return min(FETCH_LATEST, RENDER_AT + slowest + MARGIN)


def next_fetch(now: float) -> float:
    """When an always-on device should next ask (epoch seconds): the next minute's
    fetch_second(), at least MIN_HINT from now."""
    at = math.floor(now / 60) * 60 + fetch_second()
    while at < now + MIN_HINT:
        at += 60
    return at


def until_next_fetch_ms(at: float | None = None) -> int:
    """The X-EPF-Next hint: milliseconds from this answer until the panel's next timed fetch."""
    at = wall_clock() if at is None else at
    return int(math.ceil((next_fetch(at) - at) * 1000))


def align_sleep(seconds: float, now: float, shortest: float = MIN_SLEEP) -> int:
    """A sleep of about `seconds`, cut to wake fetch_second() into a minute (never later than
    asked, so a wake just after quiet hours start or end stays after), and at least `shortest`,
    the device's kind's own floor (Kind.shortest_sleep).
    Whole seconds, rounded up so the wake never comes before the render."""
    want = now + seconds
    fs = fetch_second()
    at = math.floor((want - fs) / 60) * 60 + fs
    while at < now + shortest:
        at += 60
    return int(math.ceil(at - now))
