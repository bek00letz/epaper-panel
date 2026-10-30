"""Place of the day (sources/place.py, render/place.py): one place a day, asked for once.

* The list is the add-on's own, spread across the world, and works with nothing fetched.
* Every device shows the same place on the same day; the days hop between continents.
* Wikipedia's and Wikidata's answers are read from saved samples (no network).
* Each part is asked for until it's in, kept on disk for the day, never asked again that day; a
  part that fails waits longer each time, and the rest of the page shows meanwhile.
* No map (the user's call, 30 Oct): its room goes to the place; Wikipedia is credited.
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
                self.assertTrue(p["wiki"] and p["name"] and p["region"])
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
        self.assertNotIn("map", got)
        self.assertLessEqual(len(s.asked), 8, "one place a day is a handful of requests")
        self.assertTrue(all(h["User-Agent"].startswith("epaper-panel/") for *_, h in s.asked), "it names itself, as they ask")
        again = FakeSession(Answers())
        self.assertEqual(self.fetch(again)["population"], 134308)
        self.assertEqual(again.asked, [], "the day's place is on disk: nothing asked again, a restart included")

    def test_an_answer_in_pieces_is_read_whole(self):
        # A network delivers a big answer in pieces; reading only what had arrived made the
        # first live try say "not in the form the add-on reads".
        s = FakeSession(Answers(), piece=1000)
        self.assertTrue(P.complete(self.fetch(s)))

    def test_a_failing_part_waits_and_the_rest_shows(self):
        s = FakeSession(Answers(fail="wikidata"))
        got = self.fetch(s)
        self.assertIsNone(got["population"])
        self.assertTrue(got["summary"]["en"], "the description came in all the same")
        self.assertEqual(P.PACE_DATA.waiting(), 7200, "Retry-After honoured")
        later = FakeSession(Answers())
        self.fetch(later)
        self.assertFalse(any("wikidata" in u for u in later.urls()), "not asked again while it waits")
        self.clock += 7201
        self.assertTrue(P.complete(self.fetch(later)))
        self.assertTrue(any(e["name"] == "Wikidata" for e in health.status()))

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
            lines = draw.plan(el, got, (24, 14, 744, 208))
        self.assertEqual(lines[0].text, P.of_day(today)["name"])


class TestThePage(unittest.TestCase):
    def data(self):
        import examples
        return examples.place()

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
                        lines = draw.plan({"asleep": asleep}, data, box)
                        self.assertTrue(lines)
                        for ln in lines:
                            self.assertTrue(ln.fits(), (ln.text, ln.w))
                            self.assertGreaterEqual(ln.px, 12)
                            self.assertLessEqual(ln.x + ln.w, box[0] + box[2])
                            self.assertLessEqual(ln.y + ln.px, box[1] + box[3] + 4)
                        texts = [ln.text for ln in lines]
                        self.assertIn(words.say("place.local_time" if not asleep else "place.time_apart"), texts,
                                      "the facts always fit")
                        rows = sorted((ln.y, ln.y + ln.px, ln.x) for ln in lines)
                        for (a0, a1, ax), (b0, b1, bx) in zip(rows, rows[1:]):
                            if ax == bx:
                                self.assertLessEqual(a1, b0 + 2, "lines in one column never overlap")

    def test_the_room_goes_to_the_place(self):
        # Wide: the place on the left, its description on the right in reading size; narrow: one column.
        with words.speaking("en"):
            wide = draw.plan({}, self.data(), (24, 14, 744, 208))
            narrow = draw.plan({}, self.data(), (20, 14, 360, 240))
            small = draw.plan({}, self.data(), (10, 10, 278, 78))
        credit = words.WORDS["place.credit"]["en"]
        desc = [ln for ln in wide if ln.x > 300 and ln.text != credit]
        self.assertGreaterEqual(min(ln.px for ln in desc), 20, "a paragraph you can read across a room")
        self.assertGreaterEqual(wide[0].px, 56, "the name large")
        self.assertIn(credit, [ln.text for ln in wide], "Wikipedia credited under its words")
        self.assertTrue(all(ln.x == 20 for ln in narrow[:-6]), "one column, the facts in a row at its foot")
        self.assertNotIn(credit, [ln.text for ln in small], "no room for the description, so no credit")

    def test_names_and_facts_in_the_screens_language(self):
        data = {**self.data(), "names": {"de": "Hermannstadt"}, "regions": {"de": "Kreis Sibiu"}}
        now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
        with words.speaking("de"):
            lines = draw.plan({}, data, (24, 14, 744, 208), now=now)
            texts = [ln.text for ln in lines]
            self.assertEqual(texts[:2], ["Hermannstadt", "Kreis Sibiu, Rumänien"])
            self.assertIn("134.308", texts)
            self.assertIn("Ortszeit", texts)
            self.assertIn("12:00", texts)

    def test_asleep_it_says_hours_apart(self):
        data = {**self.data(), "tz": "Asia/Tokyo"}
        now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
        with words.speaking("en"):
            texts = [ln.text for ln in draw.plan({"asleep": True}, data, (24, 14, 744, 208), now=now)]
        self.assertIn("+7 h", texts)
        self.assertNotIn("Local time", texts)

    def test_it_draws_and_has_no_map(self):
        from PIL import Image, ImageDraw
        import services
        img = Image.new("L", (800, 480), T.WHITE)
        with words.speaking("fr"):
            draw.draw(img, ImageDraw.Draw(img), (20, 14, 760, 420), {}, self.data())
        self.assertLess(min(img.tobytes()), 128)
        self.assertNotIn("openstreetmap", services.BY_ID, "no map, so no map service")
        self.assertNotIn("show_map", json.dumps(widgets.get("place_of_day").describe()))

    def test_the_widget_marks_itself_for_sleeping_devices(self):
        from render import clocktime
        self.assertIn("place_of_day", clocktime.AGES)
        self.assertIn("flight_follow", clocktime.AGES)


if __name__ == "__main__":
    unittest.main()
