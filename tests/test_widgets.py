"""The 0.15 widgets: what each shows, at every size a screen can have."""
import asyncio
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import support  # noqa: F401

import frames
from render import arrange, layout, sun, theme as T

BASE = "792x272"
SIZES = (("crowpanel_579", 0), ("crowpanel_420", 0), ("crowpanel_290", 0), ("trmnl_og", 0), ("crowpanel_420", 90))
TZ = ZoneInfo("Europe/Bucharest")


def render(el: dict, value, disp="crowpanel_579", orient=0):
    target = arrange.canvas_key(*T.canvas_dims(orient, disp))
    page = arrange.pages_for({"pages": {"p": {"elements": [{"id": "w", **el}]}}}, BASE, target)["p"]
    return T.to_1bit(layout.render_page(page, {0: value}, clock="12:45", orientation=orient, display=disp))


def ink(img, box=None) -> int:
    """Black pixels, above the footer (or in a box)."""
    w, h = img.size
    box = box or (0, 0, w, h - T.band_height(h) - 2)
    return img.crop(box).histogram()[0]


class Sizes:
    """Mixin: a widget draws something, inside its box, at every size."""
    element: dict = {}
    value = None

    def test_draws_inside_its_box_at_every_size(self):
        for disp, orient in SIZES:
            target = arrange.canvas_key(*T.canvas_dims(orient, disp))
            el = {**self.element, **arrange.auto_box(self.element, BASE, target)}
            img = render(self.element, self.value, disp, orient)
            self.assertGreater(ink(img), 200, (disp, orient))
            x, y, w, h = el["x"], el["y"], el["w"], el["h"]
            outside = ink(img) - ink(img, (x, y, x + w + 1, y + h + 1))
            self.assertEqual(outside, 0, f"drew outside its box on {disp} {orient}")


class TestSun(Sizes, unittest.TestCase):
    element = {"type": "sun_times", "style": "next", "x": 24, "y": 14, "w": 744, "h": 208}
    value = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00", "tz": "Europe/Bucharest"}

    def test_the_next_one_comes_first_and_it_turns_round(self):
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-21T18:22:00+03:00"}
        self.assertFalse(sun.next_first(data, datetime(2026, 10, 21, 12, 0, tzinfo=TZ)))
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00"}
        self.assertTrue(sun.next_first(data, datetime(2026, 10, 21, 20, 0, tzinfo=TZ)))

    def test_a_time_just_past_is_no_longer_next(self):
        # Home Assistant's value is a little behind: the sunrise has just happened.
        data = {"rising": "2026-10-22T07:43:00+03:00", "setting": "2026-10-22T18:22:00+03:00"}
        self.assertFalse(sun.next_first(data, datetime(2026, 10, 22, 7, 45, tzinfo=TZ)))

    def test_times_are_in_home_assistants_zone_and_far_ones_say_the_day(self):
        data = {"rising": "2026-12-20T05:41:00+00:00", "setting": "2026-10-21T15:22:00+00:00"}
        rise, set_ = sun.facts(data, datetime(2026, 10, 21, 12, 0, tzinfo=TZ))
        self.assertEqual((set_.value, set_.caption), ("18:22", "sunset"))
        self.assertEqual((rise.value, rise.caption), ("07:41", "sunrise 20 Dec"))

    def test_both_alike(self):
        img = render({**self.element, "style": "both"}, self.value)
        self.assertGreater(ink(img), 2000)

    def test_not_fetched_yet_is_blank_and_no_sun_says_what_to_do(self):
        self.assertEqual(ink(render(self.element, None)), 0)
        self.assertGreater(ink(render(self.element, {"rising": "", "setting": "", "tz": "UTC"})), 200)

    def test_the_render_cycle_fetches_it_without_waiting(self):
        page = {"elements": [self.element]}
        vals = {}
        from sources import home
        self.assertTrue(hasattr(home.fetch_sun, "direct"))
        asyncio.run(frames.enrich_page_values(None, page, vals))     # first read: nothing yet, never waits
        got = asyncio.run(home.fetch_sun.direct(None))                # offline: example times
        self.assertTrue(got["rising"] and got["setting"])


if __name__ == "__main__":
    unittest.main()
