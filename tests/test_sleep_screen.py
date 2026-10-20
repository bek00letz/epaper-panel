"""The quiet-hours sleep screen in the frame file."""
import json
import unittest
from unittest import mock

import support
import config
import frames
import layouts_store
import runtime
import web
from render import epf, sleep


class TestSleepScreen(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        support.use_test_data_dir()
        self._saved = layouts_store.load_layouts()

    async def asyncTearDown(self):
        layouts_store.save_layouts(self._saved)

    async def render(self, sleep_screen, quiet=True, reason="schedule (23:00–07:00)"):
        spec = json.loads(config.DEFAULTS_PATH.read_text())
        spec["quiet_hours"] = {"enabled": True, "start": "23:00", "end": "07:00", "sleep_screen": sleep_screen}
        layouts_store.save_layouts(layouts_store.sanitize_layouts(spec))
        with mock.patch.object(frames, "evaluate_quiet_hours", mock.AsyncMock(return_value=(quiet, reason))):
            await frames.refresh_frames(None)
        return epf.decode_epf(support.first_frames().epf_strip)

    async def test_quiet_hours_mark_the_sleep_screen_auto(self):
        s = await self.render(True)
        first = s.categories[0]
        self.assertTrue(first.flags & epf.CAT_FLAG_SLEEP and first.flags & epf.CAT_FLAG_SLEEP_AUTO)
        self.assertEqual(first.pill_width, 0, "no footer pill on the sleep screen")
        self.assertTrue(all(not (c.flags & epf.CAT_FLAG_SLEEP) for c in s.categories[1:]))
        self.assertTrue(s.header.flags & epf.FLAG_QUIET_HOURS)

    async def test_the_sleep_screen_is_always_there_for_the_dial_centre(self):
        night_id = (await self.render(True)).pages[0].sub_id
        for kwargs in ({"sleep_screen": False}, {"sleep_screen": True, "quiet": False}):
            s = await self.render(**kwargs)
            self.assertTrue(s.categories[0].flags & epf.CAT_FLAG_SLEEP, kwargs)
            self.assertFalse(s.categories[0].flags & epf.CAT_FLAG_SLEEP_AUTO, f"{kwargs}: not asleep by itself")
        self.assertNotEqual(s.pages[0].sub_id, night_id, "different text, different identity: the panel redraws it")

    async def test_the_editor_doesnt_list_it_as_a_page(self):
        await self.render(True)
        from aiohttp.test_utils import make_mocked_request
        body = (await web.status(make_mocked_request("GET", "/api/status"))).text
        self.assertNotIn(config.SLEEP_PAGE, json.loads(body)["pages"])

    def test_wake_text(self):
        self.assertEqual(sleep.wake_text("schedule (23:00–07:00)", "07:00"), "back at 07:00")
        self.assertEqual(sleep.wake_text("away (person.alex: not_home)", "07:00"), "back when someone’s home")
        self.assertEqual(sleep.MANUAL_TEXT, "press any button to wake")

    def test_a_user_page_cannot_be_named_like_the_sleep_screen(self):
        self.assertIsNone(config.PAGE_RE.match(config.SLEEP_PAGE))


if __name__ == "__main__":
    unittest.main()
