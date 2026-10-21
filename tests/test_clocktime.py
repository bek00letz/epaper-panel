"""The date in place of the time on a device that sleeps (render/clocktime.py).

The user's call (21 Oct): per device and automatic. A design keeps its clock;
a device that sleeps between updates draws the date where the time would be,
one that's always on keeps the clock, and switching never changes the design."""
import contextlib
import copy
import io
import json
import unittest
from datetime import datetime
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import support
import devices
import frames
import web
from render import clocktime, layout

CLOCK = [
    {"type": "text", "value": "{{ now().strftime('%H:%M') }}", "size": 110, "bold": True, "x": 40, "y": 20, "w": 450, "h": 140, "align": "left"},
    {"type": "text", "value": "{{ now().strftime('%A, %-d %B') }}", "size": 36, "bold": False, "x": 44, "y": 168, "w": 500, "h": 46, "align": "left"},
    {"type": "icon", "icon": "mdi:clock-outline", "x": 620, "y": 40, "w": 120, "h": 120},
]
WED = datetime(2026, 9, 30, 12, 34)


class TestWhatShowsTheTime(unittest.TestCase):
    def test_times_and_not_times(self):
        yes = ["{{ now().strftime('%H:%M') }}", "{{ now().strftime('%I:%M %p') }}", "{{ now().strftime(\"%-H.%M\") }}", "at {{ now().strftime('%H:%M') }}",
               # The ways people write a clock in Home Assistant (framework review #11).
               "{{ as_timestamp(now()) | timestamp_custom('%H:%M') }}", "{{ states('sensor.time') }}",
               "{{ states.sensor.date_time.state }}", "{{ now().hour ~ ':' ~ '%02d' | format(now().minute) }}"]
        no = ["{{ now().strftime('%A, %-d %B') }}", "{{ as_timestamp(states.sensor.door.last_changed) | timestamp_custom('%H:%M') }}",
              "{{ states('sensor.timer_kitchen') }}", "{{ now().day }}", "12:30", ""]
        self.assertTrue(all(clocktime.shows_time({"type": "text", "value": v}) for v in yes))
        self.assertFalse(any(clocktime.shows_time({"type": "text", "value": v}) for v in no))
        self.assertFalse(clocktime.shows_time({"type": "number", "value": yes[0]}))
        # Bindings: the add-on's own clock, and the Time & Date sensor picked as an entity.
        self.assertTrue(clocktime.shows_time({"type": "text", "show": "now"}))
        self.assertTrue(clocktime.shows_time({"type": "text", "show": "now", "format": "time_12"}))
        self.assertFalse(clocktime.shows_time({"type": "text", "show": "now", "format": "day_full"}))
        self.assertTrue(clocktime.shows_time({"type": "text", "entity": "sensor.time", "show": "state"}))

    def test_the_clock_reads_as_the_date(self):
        page, before = {"elements": CLOCK}, copy.deepcopy(CLOCK)
        got, vals, times = clocktime.date_for_time(page, {0: "12:34", 1: "Wednesday, 30 September"}, WED)
        self.assertEqual(vals, {0: "Wednesday", 1: "30 September"}, "the weekday large, the date beside it without repeating it")
        self.assertEqual(times, {0})
        self.assertLessEqual(got["elements"][0]["size"], 110, "it fits the clock's box, never larger")
        self.assertEqual(CLOCK, before, "the design's page is never changed")

    def test_a_time_alone_becomes_the_whole_date(self):
        _, vals, _ = clocktime.date_for_time({"elements": [CLOCK[0]]}, {0: "12:34"}, WED)
        self.assertEqual(vals, {0: "Wednesday 30 September"})

    def test_it_fits_and_the_editor_is_told(self):
        metrics = []
        layout.render_page({"elements": CLOCK}, {0: "12:34", 1: "Wednesday, 30 September"}, metrics=metrics, date_for_time=WED)
        self.assertEqual([m["i"] for m in metrics if m.get("date_for_time")], [0])
        self.assertFalse([m for m in metrics if m.get("overflow")])
        metrics = []
        layout.render_page({"elements": CLOCK}, {0: "12:34", 1: "Wednesday, 30 September"}, metrics=metrics)
        self.assertFalse([m for m in metrics if m.get("date_for_time")], "always on keeps the clock")


class TestPerDevice(unittest.IsolatedAsyncioTestCase):
    """One design, two devices: the first always on, Hall sleeping between updates."""

    async def asyncSetUp(self):
        support.fresh_data_dir()
        first = devices.primary()
        spec = devices.view(first["id"])
        spec["pages"] = {"clock": {"tier": "rotate", "elements": copy.deepcopy(CLOCK)}}
        spec["rotation"] = ["clock"]
        devices.save_view(spec, first["id"])
        self.first = first
        self.hall = devices.add("crowpanel", "Hall", "crowpanel_420", design=first["design"], update_minutes=15)
        _, editor = web.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        support.use_test_data_dir()

    async def drawn(self):
        """What each display got for the clock's text: (date_for_time given?, per display)."""
        seen = {}
        real = layout.render_page

        def spy(page, vals, **kw):
            if any(clocktime.shows_time(e) for e in page.get("elements", [])):
                seen.setdefault(kw.get("display"), set()).add(kw.get("date_for_time") is not None)
            return real(page, vals, **kw)
        out = io.StringIO()
        with mock.patch.object(layout, "render_page", spy), contextlib.redirect_stdout(out):
            await frames.refresh_frames(None)
        self.assertNotIn("couldn't draw", out.getvalue(), "every page drawn ahead, the sleeping one's too")
        return seen

    async def preview(self, dev):
        r = await self.ed.post("/api/preview", params={"device": dev["id"]}, json={"page": {"elements": CLOCK}})
        self.assertEqual(r.status, 200)
        return [m["i"] for m in json.loads(r.headers["X-Metrics"]) if m.get("date_for_time")]

    def design(self):
        return copy.deepcopy(devices.view(self.first["id"])["pages"])

    async def test_the_sleeping_one_draws_the_date_the_other_the_clock(self):
        seen = await self.drawn()
        self.assertEqual(seen.get("crowpanel_420"), {True}, "Hall sleeps: the date")
        self.assertEqual(seen.get("crowpanel_579"), {False}, "the first is always on: the clock")
        self.assertEqual(await self.preview(self.hall), [0], "Hall's canvas in the editor shows it, and says so")
        self.assertEqual(await self.preview(self.first), [])

    async def test_switching_back_brings_the_clock_back_and_the_design_never_changes(self):
        before = self.design()
        r = await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"update_minutes": 1})
        self.assertEqual(r.status, 200)
        self.assertEqual((await self.drawn()).get("crowpanel_420"), {False})
        self.assertEqual(await self.preview(self.hall), [])
        r = await self.ed.patch(f"/api/devices/{self.hall['id']}", json={"update_minutes": 30})
        self.assertEqual(r.status, 200)
        self.assertEqual((await self.drawn()).get("crowpanel_420"), {True})
        self.assertEqual(self.design(), before, "switching never changes the design")


WORLD = {"type": "world_clock", "zones": [{"tz": "", "label": ""}, {"tz": "Asia/Tokyo", "label": ""}], "x": 24, "y": 14, "w": 744, "h": 208}


class TestTheEditor(unittest.TestCase):
    def test_a_world_clock_reports_no_legibility_reading(self):
        """Selecting a world clock on a sleeping device broke the inspector: its metric has no
        `verdict` (it's no text the renderer measures), and the legibility line read one."""
        metrics = []
        layout.render_page({"elements": [WORLD]}, {}, metrics=metrics, date_for_time=WED)
        self.assertTrue(metrics and all("verdict" not in m for m in metrics if m["i"] == 0))
        src = (support.APP / "web" / "app" / "inspector.js").read_text()
        self.assertIn("if (dist > 0 && m.verdict) {", src)

    def test_the_note_on_the_clock_comes_from_the_render(self):
        src = (support.APP / "web" / "app" / "inspector.js").read_text()
        self.assertIn("if (app.canvas.metrics.find((x) => x.i === i)?.date_for_time)", src)
        self.assertIn("sleeps between updates, so it shows the date here.", src)

    def test_no_prompt_and_the_old_conversion_is_kept_off(self):
        src = (support.APP / "web" / "app" / "sheets.js").read_text()
        timers = src.split("export async function changeTimers", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("offerTheDate(", timers, "switching asks nothing and changes no page")
        self.assertIn("function offerTheDate(app, scr) {", src, "the way back, off")
        self.assertIn("app.canvas?.preview(true);", timers, "the canvas redraws as the device now draws")


if __name__ == "__main__":
    unittest.main()
