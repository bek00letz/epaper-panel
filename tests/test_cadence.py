"""The clock lined up (cadence.py): the render cycle just after each minute starts, and every
device asking a moment after it, so the time on a page is right within a few seconds.
"""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import support  # noqa: F401
import cadence

UTC = timezone.utc


def at(hh, mm, ss=0.0, tz=UTC):
    """Epoch seconds for today-ish at hh:mm:ss in `tz` (a fixed day, so tests never cross midnight by accident)."""
    whole = int(ss)
    return datetime(2026, 10, 21, hh, mm, whole, tzinfo=tz).timestamp() + (ss - whole)


def clock(t, tz=UTC):
    return datetime.fromtimestamp(t, tz).strftime("%H:%M:%S.%f")[:-3]


class Fresh(unittest.TestCase):
    def setUp(self):
        cadence._took.clear()
        self.addCleanup(cadence._took.clear)


class TestRenderCycle(Fresh):
    def test_every_minute_just_after_it_starts(self):
        self.assertEqual(clock(cadence.next_render(at(10, 0, 19), 60)), "10:01:00.500",
                         "an add-on started at :19 renders next at the minute, not at :19")
        self.assertEqual(clock(cadence.next_render(at(10, 1, 0.5), 60)), "10:02:00.500")

    def test_a_render_after_the_minute_started_covers_it(self):
        # Outside data arriving set off a render at :00.2: it already shows the new minute.
        self.assertEqual(clock(cadence.next_render(at(10, 0, 0.2), 60)), "10:01:00.500")
        # One that started at :59.8 shows the old minute, so the :00.5 one still runs.
        self.assertEqual(clock(cadence.next_render(at(9, 59, 59.8), 60)), "10:00:00.500")
        # A timer that fires a hair early never renders the same minute twice.
        self.assertEqual(clock(cadence.next_render(at(10, 0, 0.4999), 60)), "10:01:00.500")

    def test_under_a_minute_adds_renders_within_it(self):
        self.assertEqual(clock(cadence.next_render(at(10, 0, 12), 30)), "10:00:30.500")
        self.assertEqual(clock(cadence.next_render(at(10, 0, 31), 30)), "10:01:00.500")
        # 45 doesn't divide a minute: :00 and :45, starting again at each minute.
        self.assertEqual(clock(cadence.next_render(at(10, 0, 46), 45)), "10:01:00.500")

    def test_longer_on_whole_minutes_from_midnight_in_home_assistants_zone(self):
        self.assertEqual(clock(cadence.next_render(at(10, 2, 19), 300)), "10:05:00.500")
        self.assertEqual(clock(cadence.next_render(at(10, 2, 19), 90)), "10:04:00.500", "90 s: every 2 minutes")
        # Kathmandu is 5:45 ahead: its 10:05 is not UTC's xx:05, and the grid follows the home clock.
        ktm = ZoneInfo("Asia/Kathmandu")
        self.assertEqual(clock(cadence.next_render(at(10, 2, 19, ktm), 600, ktm), ktm), "10:10:00.500")
        self.assertEqual(clock(cadence.next_render(at(10, 2, 19, ktm), 3600, ktm), ktm), "11:00:00.500")

    def test_a_long_render_never_skips_a_minute_silently(self):
        wait, late = cadence.after_render(at(10, 0, 0.5), at(10, 0, 2.5), 60)
        self.assertAlmostEqual(wait, 58.0)
        self.assertIsNone(late)
        # It ran 72 s, past 10:01's start: the next render is at once, and the log says so.
        wait, late = cadence.after_render(at(10, 0, 0.5), at(10, 1, 12.5), 60)
        self.assertEqual(wait, 0.0)
        self.assertIn("render took 72 s", late)
        self.assertIn("12 s late", late)
        # Just past (a render set off at :59.8 by outside data): again at once, nothing to say.
        wait, late = cadence.after_render(at(9, 59, 59.8), at(10, 0, 1.0), 60)
        self.assertEqual((wait, late), (0.0, None))

    def test_the_render_loop_runs_on_it(self):
        import server
        now = [at(10, 0, 19)]
        renders, waits = [], []

        async def render(_session):
            renders.append(clock(now[0]))
            now[0] += 72 if len(renders) == 3 else 1.5      # the third one runs long

        async def wait_for_news(seconds):
            waits.append(seconds)
            now[0] += seconds
            if len(waits) == 5:
                raise asyncio.CancelledError
            return False

        printed = []
        with mock.patch.object(server, "refresh_frames", render), \
                mock.patch.object(server.time, "time", lambda: now[0]), \
                mock.patch.object(server.runtime.LIVE, "wait_for_news", wait_for_news), \
                mock.patch.object(server.devices, "all_views", lambda: []), \
                mock.patch.object(server.devices, "all_devices", lambda: []), \
                mock.patch.object(server.runtime, "PUBLISHER", None), \
                mock.patch.object(server, "get_home_timezone", mock.AsyncMock(return_value="UTC")), \
                mock.patch("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(server.render_loop())
        self.assertEqual(renders, ["10:00:19.000", "10:01:00.500", "10:02:00.500", "10:03:12.500", "10:04:00.500"],
                         "at once at start, then just after each minute; the long one is followed at once")
        self.assertTrue(any("render took 72 s" in p for p in printed), printed)


class TestDevicesAsk(Fresh):
    def test_after_the_render_has_usually_finished(self):
        self.assertAlmostEqual(cadence.fetch_second(), cadence.RENDER_AT + cadence.USUAL_RENDER + cadence.MARGIN)
        for took in (0.8, 4.0, 1.2):
            cadence.note_render(took)
        self.assertAlmostEqual(cadence.fetch_second(), 0.5 + 4.0 + 1.5, msg="the slowest of the last few")
        cadence.note_render(300)
        self.assertEqual(cadence.fetch_second(), cadence.FETCH_LATEST, "never later than this into the minute")

    def test_the_hint_for_an_always_on_panel(self):
        fs = cadence.fetch_second()                                       # 3.0 s
        # It first fetched at :19 (its boot): the next is at the minute's fetch second.
        self.assertEqual(cadence.until_next_fetch_ms(at(10, 0, 19)), round((60 - 19 + fs) * 1000))
        # A fetch at the aligned time: a minute on.
        self.assertEqual(cadence.until_next_fetch_ms(at(10, 1, fs)), 60000)
        # A press at :59: the next minute's render is caught, not skipped.
        self.assertEqual(cadence.until_next_fetch_ms(at(10, 1, 59)), round((1 + fs) * 1000))
        # Just before the aligned time: never a fetch straight after this one.
        self.assertEqual(cadence.until_next_fetch_ms(at(10, 2, fs - 0.5)), round(60500))

    def test_a_sleep_wakes_just_after_a_minute_starts(self):
        fs = cadence.fetch_second()
        now = at(10, 0, 19)
        s = cadence.align_sleep(15 * 60, now)
        self.assertEqual(clock(now + s), "10:15:03.000", "never later than asked: 10:15:19 becomes 10:15:03")
        self.assertEqual(cadence.align_sleep(15 * 60, at(10, 0, fs)), 15 * 60, "already aligned stays")
        # Quiet hours end at 07:00; a wake asked for 07:01:18 (a minute's margin) lands at 07:01:03.
        self.assertEqual(clock(at(6, 50, 19) + cadence.align_sleep(659, at(6, 50, 19))), "07:01:03.000")
        self.assertGreaterEqual(cadence.align_sleep(31, at(10, 0, 40)), cadence.MIN_SLEEP, "the panel's floor")


if __name__ == "__main__":
    unittest.main()
