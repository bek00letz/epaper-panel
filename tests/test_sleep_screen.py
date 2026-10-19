"""The quiet-hours sleep screen in the frame file."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATA_DIR", "/tmp/epaper-data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon" / "app"))

import server  # noqa: E402
from render import epf, sleep  # noqa: E402


class TestSleepScreen(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server.DATA_DIR = Path(os.environ["DATA_DIR"])
        server.LAYOUTS_PATH = server.DATA_DIR / "layouts.json"
        server.PANEL_SETUP_PATH = server.DATA_DIR / "panel_setup.json"
        server.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._saved = server.LAYOUTS_PATH.read_text() if server.LAYOUTS_PATH.exists() else None

    async def asyncTearDown(self):
        if self._saved is None:
            server.LAYOUTS_PATH.unlink(missing_ok=True)
        else:
            server.LAYOUTS_PATH.write_text(self._saved)

    async def render(self, sleep_screen, quiet=True, reason="schedule (23:00–07:00)"):
        spec = json.loads(server.DEFAULTS_PATH.read_text())
        spec["quiet_hours"] = {"enabled": True, "start": "23:00", "end": "07:00", "sleep_screen": sleep_screen}
        server.save_layouts(server.sanitize_layouts(spec))
        with mock.patch.object(server, "evaluate_quiet_hours", mock.AsyncMock(return_value=(quiet, reason))):
            await server.refresh_frames(None)
        return epf.decode_epf(server.FRAMES.epf_strip)

    async def test_quiet_hours_start_with_the_sleep_screen(self):
        s = await self.render(True)
        self.assertTrue(s.categories[0].flags & epf.CAT_FLAG_SLEEP)
        self.assertEqual(s.categories[0].pill_width, 0, "no footer pill on the sleep screen")
        self.assertEqual(server.FRAMES.names[0], server.SLEEP_PAGE)
        self.assertTrue(all(not (c.flags & epf.CAT_FLAG_SLEEP) for c in s.categories[1:]))
        self.assertTrue(s.header.flags & epf.FLAG_QUIET_HOURS)

    async def test_switched_off_or_daytime_means_no_sleep_screen(self):
        for kwargs in ({"sleep_screen": False}, {"sleep_screen": True, "quiet": False}):
            s = await self.render(**kwargs)
            self.assertFalse(any(c.flags & epf.CAT_FLAG_SLEEP for c in s.categories), kwargs)
            self.assertNotIn(server.SLEEP_PAGE, server.FRAMES.names)

    def test_wake_text(self):
        self.assertEqual(sleep.wake_text("schedule (23:00–07:00)", "07:00"), "back at 07:00")
        self.assertEqual(sleep.wake_text("away (person.alex: not_home)", "07:00"), "back when someone’s home")

    def test_a_user_page_cannot_be_named_like_the_sleep_screen(self):
        self.assertIsNone(server.PAGE_RE.match(server.SLEEP_PAGE))


if __name__ == "__main__":
    unittest.main()
