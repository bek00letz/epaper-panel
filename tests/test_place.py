"""Place of the day (sources/place.py, render/place.py): one place a day, asked for once.

* The list is the add-on's own, spread across the world, and works with nothing fetched.
* Every device shows the same place on the same day; the days hop between continents.
* Wikipedia's, Wikidata's and OpenStreetMap's answers are read from saved samples (no network).
* Each part is asked for until it's in, kept on disk for the day, never asked again that day; a
  part that fails waits longer each time, and the rest of the page shows meanwhile.
* The map is OpenStreetMap's lines, never its tiles, and carries its credits.
* Every word fits at every size offered, in every language; asleep, no local time that would stop.
"""
import asyncio
import json
import math
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import support
from fake_http import FakeSession, sample

import health
import pacing
import widgets
from render import arrange, place as draw, theme as T, words
from sources import place as P


class TestTheList(unittest.TestCase):
    def test_every_place_is_whole(self):
        ids = [p["id"] for p in P.places()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 50)
        for p in P.places():
            with self.subTest(place=p["id"]):
                ZoneInfo(p["tz"])
                self.assertTrue(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180)
                self.assertIn(p["kind"], ("city", "wonder"))
                self.assertTrue(0.8 <= p["km"] <= 5)
                row = words.WORDS[f"country.{p['country']}"]
                self.assertEqual([lang for lang in words.LANGUAGES if not row.get(lang)], [], "its country in every language")

    def test_spread_across_the_world(self):
        self.assertGreaterEqual(len({P.continent(p) for p in P.places()}), 5)
        self.assertGreaterEqual(len({p["country"] for p in P.places()}), 40)


class TestOneADay(unittest.TestCase):
    def test_the_same_place_for_everyone_on_a_day(self):
        d = date(2026, 10, 30)
        self.assertEqual(P.of_day(d)["id"], P.of_day(date(2026, 10, 30))["id"])

    def test_every_place_in_turn(self):
        start = date(2026, 1, 1)
        seen = {P.of_day(start + timedelta(days=k))["id"] for k in range(len(P.places()))}
        self.assertEqual(len(seen), len(P.places()))

    def test_a_week_hops_between_continents(self):
        for start in (date(2026, 1, 1), date(2026, 6, 15), date(2027, 3, 3)):
            week = [P.continent(P.of_day(start + timedelta(days=k))) for k in range(7)]
            self.assertGreaterEqual(len(set(week)), 3, week)
            self.assertFalse(any(a == b == c for a, b, c in zip(week, week[1:], week[2:])), week)


class TestReading(unittest.TestCase):
    def test_a_summary(self):
        got = P.read_summary(sample("wikipedia_summary_en.json"))
        self.assertEqual(got["qid"], "Q83324")
        self.assertTrue(got["text"].startswith("Sibiu"))
        ro = P.read_summary(sample("wikipedia_summary_ro.json"))
        self.assertLessEqual(len(ro["text"]), P.EXTRACT_MOST + 1)
        self.assertIsNone(P.read_summary({"type": "disambiguation", "extract": "Sibiu may refer to"}))

    def test_facts_wikidata_stands_by(self):
        got = P.read_entity(sample("wikidata_entity.json"), "Q83324")
        self.assertEqual(got["population"], 134308, "the preferred count, the 2021 census, not 2011's")
        self.assertEqual(got["elevation"], 434)
        self.assertEqual(got["region"], "Q184797")
        self.assertEqual(got["titles"]["de"], "Hermannstadt")
        self.assertEqual(got["names"]["de"], "Hermannstadt")
        with self.assertRaises(ValueError):
            P.read_entity({"entities": {}}, "Q83324")

    def test_a_region_in_each_language(self):
        got = P.read_labels(sample("wikidata_labels.json"), "Q184797")
        self.assertEqual((got["en"], got["de"]), ("Sibiu County", "Kreis Sibiu"))

    def test_the_map_is_lines_in_metres(self):
        m = P.read_map(sample("overpass_sibiu.json"), 45.7975, 24.1520)
        kinds = {k for k, _ in m["lines"]}
        self.assertTrue({"major", "minor", "river"} <= kinds)
        self.assertEqual([k for k, _ in m["lines"]][-1], "major", "main roads drawn last, over the rest")
        inside = [p for _, pts in m["lines"] for p in pts if abs(p[0]) <= 800 and abs(p[1]) <= 800]
        self.assertGreater(len(inside), 100, "the town is round the middle, in metres from it")
        with self.assertRaises(ValueError):
            P.read_map({"remark": "runtime error"}, 0, 0)

    def test_the_query_asks_for_streets_and_water_round_it(self):
        q = P.overpass_query(45.7975, 24.1520, 1.6, paths=False)
        import re
        s_, w_, n_, e_ = map(float, re.search(r"\[bbox:([^\]]+)\]", q).group(1).split(","))
        self.assertAlmostEqual((n_ - s_) * 110.54, 1.6, places=2)          # 1.6 km north to south
        self.assertAlmostEqual((e_ - w_) * 111.32 * math.cos(math.radians(45.7975)), 1.6, places=2)   # and east to west
        self.assertNotIn("footway", q)
        self.assertIn("footway", P.overpass_query(-13.1631, -72.545, 1.6, paths=True), "a wonder's paths are its streets")
        self.assertIn('"natural"="water"', q)


class Answers:
    """Every service's sample answer, by address; `fail` makes one answer 429."""

    def __init__(self, fail=""):
        self.fail = fail

    def __call__(self, method, url, data):
        if self.fail and self.fail in url:
            return 429, "slow down", {"Retry-After": "7200"}
        if "wikipedia.org" in url:
            return 200, sample("wikipedia_summary_ro.json" if url.startswith("https://ro.") else "wikipedia_summary_en.json"), {}
        if "wikidata.org" in url:
            return 200, sample("wikidata_labels.json" if "ids=Q184797" in url else "wikidata_entity.json"), {}
        if "overpass" in url:
            return 200, sample("overpass_sibiu.json"), {}
        return 404, "", {}


class TestAskedOnceADay(unittest.TestCase):
    DAY = "2026-10-30"                           # Sibiu's day

    def setUp(self):
        support.fresh_data_dir()
        health.reset()
        P.forget()
        self.clock = 1_000_000.0
        pacing.clock = lambda: self.clock

    def tearDown(self):
        import time
        pacing.clock = time.time

    def fetch(self, s):
        return asyncio.run(P.fetch_place.direct(s, self.DAY))

    def test_every_part_once(self):
        self.assertEqual(P.of_day(date.fromisoformat(self.DAY))["id"], "sibiu")
        s = FakeSession(Answers())
        got = self.fetch(s)
        self.assertTrue(P.complete(got))
        self.assertEqual(got["population"], 134308)
        self.assertEqual(got["regions"]["de"], "Kreis Sibiu")
        self.assertIn("ro", got["summary"])
        self.assertTrue(got["map"]["lines"])
        asked = len(s.asked)
        self.assertLessEqual(asked, 9, "one place a day is a handful of requests")
        self.assertEqual(sum("overpass" in u for u in s.urls()), 1)
        self.assertTrue(all(h["User-Agent"].startswith("epaper-panel/") for *_, h in s.asked), "it names itself, as they ask")
        again = FakeSession(Answers())
        self.assertEqual(self.fetch(again)["population"], 134308)
        self.assertEqual(again.asked, [], "the day's place is on disk: nothing asked again, a restart included")

    def test_an_answer_in_pieces_is_read_whole(self):
        # A network delivers a big answer (a town's streets) in pieces; reading only what had
        # arrived made it "not in the form the add-on reads" on the first live try.
        s = FakeSession(Answers(), piece=1000)
        self.assertTrue(P.complete(self.fetch(s)))

    def test_a_failing_part_waits_and_the_rest_shows(self):
        s = FakeSession(Answers(fail="overpass"))
        got = self.fetch(s)
        self.assertIsNone(got["map"])
        self.assertEqual(got["population"], 134308, "the facts came in all the same")
        self.assertEqual(P.PACE_OSM.waiting(), 7200, "Retry-After honoured")
        later = FakeSession(Answers())
        self.fetch(later)
        self.assertFalse(any("overpass" in u for u in later.urls()), "not asked again while it waits")
        self.clock += 7201
        self.assertTrue(P.complete(self.fetch(later)))
        self.assertTrue(any(e["name"] == "OpenStreetMap" for e in health.status()))

    def test_nothing_fetched_still_shows_the_place(self):
        el, ctx = {"type": "place_of_day"}, widgets.Ctx(home_tz="Europe/Bucharest")
        import runtime
        from live_data import LiveData
        was = runtime.LIVE
        runtime.LIVE = LiveData()
        try:
            async def go():
                return await widgets.fetch(None, el, ctx)
            got = asyncio.run(go())
        finally:
            runtime.LIVE = was
        today = datetime.now(ZoneInfo("Europe/Bucharest")).date()
        self.assertEqual(got["id"], P.of_day(today)["id"])
        self.assertEqual(got["home_tz"], "Europe/Bucharest")
        with words.speaking("en"):
            lines, _ = draw.plan(el, got, (24, 14, 744, 208))
        self.assertEqual(lines[0].text, P.of_day(today)["name"])


class TestThePage(unittest.TestCase):
    def data(self):
        import examples
        d = examples.place()
        d["map"] = P.read_map(sample("overpass_sibiu.json"), 45.7975, 24.152)
        return d

    def boxes(self):
        base = arrange.canvas_key(792, 272)
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            placed = arrange.auto_box({"x": 24, "y": 14, "w": 744, "h": 208}, base, arrange.canvas_key(d["w"], d["h"]))
            yield key, (placed["x"], placed["y"], placed["w"], placed["h"])
            yield key + " filled", (20, 14, d["w"] - 40, d["h"] - T.band_height(d["h"]) - 24)

    def test_every_word_fits_everywhere(self):
        data = self.data()
        for key, box in self.boxes():
            for lang in words.LANGUAGES:
                for asleep in (False, True):
                    with self.subTest(display=key, lang=lang, asleep=asleep), words.speaking(lang):
                        lines, mbox = draw.plan({"asleep": asleep}, data, box)
                        self.assertTrue(lines)
                        for ln in lines:
                            self.assertTrue(ln.fits(), (ln.text, ln.w))
                            self.assertGreaterEqual(ln.px, 12)
                            self.assertLessEqual(ln.x + ln.w, box[0] + box[2])
                            self.assertLessEqual(ln.y + ln.px, box[1] + box[3] + 4)
                        if mbox:
                            self.assertGreaterEqual(min(mbox[2], mbox[3]), draw.MAP_MIN * 0.8)
                            self.assertLessEqual(mbox[0] + mbox[2], box[0] + box[2])

    def test_a_small_box_leaves_the_map_out(self):
        _, mbox = draw.plan({}, self.data(), (10, 10, 278, 78))
        self.assertIsNone(mbox)
        _, mbox = draw.plan({}, self.data(), (24, 14, 744, 208))
        self.assertIsNotNone(mbox)
        _, mbox = draw.plan({"show_map": False}, self.data(), (24, 14, 744, 208))
        self.assertIsNone(mbox)

    def test_names_and_facts_in_the_screens_language(self):
        data = {**self.data(), "names": {"de": "Hermannstadt"}, "regions": {"de": "Kreis Sibiu"}}
        now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
        with words.speaking("de"):
            lines, _ = draw.plan({}, data, (24, 14, 744, 208), now=now)
            texts = [ln.text for ln in lines]
            self.assertEqual(texts[:2], ["Hermannstadt", "Kreis Sibiu, Rumänien"])
            self.assertIn("134.308", texts)
            self.assertIn("Ortszeit", texts)
            self.assertIn("12:00", texts)

    def test_asleep_it_says_hours_apart(self):
        data = {**self.data(), "tz": "Asia/Tokyo"}
        now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
        with words.speaking("en"):
            texts = [ln.text for ln in draw.plan({"asleep": True}, data, (24, 14, 744, 208), now=now)[0]]
        self.assertIn("+7 h", texts)
        self.assertNotIn("Local time", texts)

    def test_the_map_carries_its_credits(self):
        from PIL import Image, ImageDraw
        img = Image.new("L", (800, 480), T.WHITE)
        with words.speaking("fr"):
            draw.draw(img, ImageDraw.Draw(img), (20, 14, 760, 420), {}, self.data())
        self.assertLess(min(img.crop((440, 14, 780, 434)).tobytes()), 128, "a map was drawn")
        for lang in words.LANGUAGES:
            with words.speaking(lang):
                self.assertIn("OpenStreetMap", words.say("place.credit_short"))

    def test_the_widget_marks_itself_for_sleeping_devices(self):
        from render import clocktime
        self.assertIn("place_of_day", clocktime.AGES)
        self.assertIn("flight_follow", clocktime.AGES)


if __name__ == "__main__":
    unittest.main()
