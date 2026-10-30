"""Follow one flight (sources/flights.py, render/follow.py): by its number or callsign, anywhere.

* Flightradar24's feed finds it either way and says both, with its route (a saved sample here).
* While it flies: from, to, height, speed, how long is left (or, on a device that sleeps, when it
  arrives). Before and after: "Not in the air", "Landed in …", "Out of view", plainly.
* Asked every minute while it flies, every few minutes while it doesn't; longer waits after a
  failure, with the last position kept and its age said.
* Every word fits at every size offered, in every language.
"""
import asyncio
import time
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import support  # noqa: F401
from fake_http import FakeSession, sample

import health
import pacing
import widgets
from render import arrange, follow as draw, theme as T, words
from sources import flights as F


def run(coro):
    return asyncio.run(coro)


class TestWhichFlight(unittest.TestCase):
    def test_as_typed(self):
        self.assertEqual(F.ident_of(" w4 3186 "), "W43186")
        self.assertEqual(F.ident_of("baw-17r"), "BAW17R")
        for bad in ("", "BA", "WIZZAIR", "<b>1</b>", "123456789"):
            self.assertEqual(F.ident_of(bad), "", bad)

    def test_a_number_or_a_callsign(self):
        self.assertEqual([F.asks_by(x) for x in ("W43186", "BA117", "0B1234", "BAW17R", "WMT4ZZ")],
                         ["flight", "flight", "flight", "callsign", "callsign"])

    def test_printed_as_airlines_print_it(self):
        self.assertEqual([draw.spaced(x) for x in ("W43186", "BA117", "BAW17R", "U21234A")], ["W4 3186", "BA 117", "BAW17R", "U2 1234A"])


class TestReading(unittest.TestCase):
    def test_found_by_number_or_callsign(self):
        body = sample("flightradar24_follow.json")
        for ident in ("W43186", "WMT4ZZ"):
            p = F.read_follow(body, ident)
            self.assertEqual((p["flight"], p["callsign"], p["from"], p["to"]), ("W43186", "WMT4ZZ", "VLC", "OTP"))
            self.assertEqual((p["altitude_m"], p["speed_kmh"], p["on_ground"]), (968, 478, False))
        self.assertIsNone(F.read_follow(body, "W4318"), "a flight is matched whole, never by its start")
        with self.assertRaises(ValueError):
            F.read_follow({"error": "x"}, "W43186")


class TestWhatItsDoing(unittest.TestCase):
    PLANE = F.read_follow(sample("flightradar24_follow.json"), "W43186")

    def test_in_the_air(self):
        got = F.describe("W43186", {**self.PLANE, "latitude": 44.0, "longitude": 15.0, "altitude_m": 11000, "speed_kmh": 840},
                         None, 1000.0)
        # The add-on's one airport table (OurAirports) names the town each airport is in.
        self.assertEqual((got["status"], got["from_city"], got["to_city"]), ("air", "Valencia", "Otopeni"))
        self.assertGreater(got["total_km"], got["left_km"])
        self.assertAlmostEqual(got["arrives"] - got["seen_at"], got["left_km"] / 840 * 3600, delta=5)        # its distance is said in whole km

    def test_landed_when_gone_low_near_its_destination(self):
        seen = {"plane": self.PLANE, "at": 1000.0}
        got = F.describe("W43186", None, seen, 1600.0)
        self.assertEqual((got["status"], got["to"]), ("landed", "OTP"))

    def test_out_of_view_when_gone_mid_flight(self):
        seen = {"plane": {**self.PLANE, "latitude": 50.0, "longitude": -30.0, "altitude_m": 11000}, "at": 1000.0}
        self.assertEqual(F.describe("W43186", None, seen, 1600.0)["status"], "lost")

    def test_long_after_its_not_in_the_air(self):
        seen = {"plane": self.PLANE, "at": 1000.0}
        self.assertEqual(F.describe("W43186", None, seen, 1000.0 + F.REMEMBER + 1)["status"], "waiting")
        self.assertEqual(F.describe("W43186", None, None, 1000.0)["status"], "waiting")

    def test_on_the_ground_before_it(self):
        got = F.describe("W43186", {**self.PLANE, "on_ground": True}, None, 1000.0)
        self.assertEqual((got["status"], got["from"], got["to"]), ("waiting", "VLC", "OTP"))


class TestAskingCarefully(unittest.TestCase):
    def setUp(self):
        health.reset()
        F._seen.clear()
        F.PACE_FR24.ok()

    def test_by_number_or_callsign_named_by_itself(self):
        s = FakeSession(lambda m, u, d: (200, sample("flightradar24_follow.json"), {}))
        got = run(F.fetch_followed.direct(s, "w4 3186"))
        run(F.fetch_followed.direct(s, "WMT4ZZ"))
        self.assertEqual(got["status"], "air")
        self.assertIn("?flight=W43186&", s.urls()[0])
        self.assertIn("?callsign=WMT4ZZ&", s.urls()[1])
        self.assertTrue(s.asked[0][3]["User-Agent"].startswith("epaper-panel/"), "never a browser's name")

    def test_not_in_the_air_is_looked_for_every_few_minutes(self):
        s = FakeSession(lambda m, u, d: (200, {"full_count": 1, "version": 4}, {}))
        first = run(F.fetch_followed.direct(s, "BA117"))
        again = run(F.fetch_followed.direct(s, "BA117"))
        self.assertEqual((first["status"], len(s.asked)), ("waiting", 1))
        self.assertIs(again, first)
        F._seen["BA117"]["absent_at"] -= F.QUIET + 1
        run(F.fetch_followed.direct(s, "BA117"))
        self.assertEqual(len(s.asked), 2)

    def test_in_the_air_every_minute(self):
        s = FakeSession(lambda m, u, d: (200, sample("flightradar24_follow.json"), {}))
        run(F.fetch_followed.direct(s, "W43186"))
        run(F.fetch_followed.direct(s, "W43186"))
        self.assertEqual(len(s.asked), 2)
        self.assertEqual(F.fetch_followed.interval, 60)

    def test_a_failure_waits_longer_each_time(self):
        clock = [1_000_000.0]
        pacing.clock = lambda: clock[0]
        try:
            s = FakeSession(lambda m, u, d: (500, "error", {}))
            with self.assertRaises(LookupError):
                run(F.fetch_followed.direct(s, "W43186"))
            with self.assertRaises(pacing.Waiting):
                run(F.fetch_followed.direct(s, "W43186"))
            self.assertEqual(len(s.asked), 1)
            clock[0] += 61
            with self.assertRaises(LookupError):
                run(F.fetch_followed.direct(s, "W43186"))
            self.assertEqual(F.PACE_FR24.waiting(), 120)
        finally:
            pacing.clock = time.time

    def test_it_counts_in_flightradar24s_service(self):
        import services
        fr = services.get("flightradar24")
        self.assertTrue(fr.uses({"type": "flight_follow", "flight": "W43186"}))
        F.PACE_FR24.failed()
        fr.forget()
        self.assertEqual(F.PACE_FR24.waiting(), 0)


class TestShowsWhileInTheAir(unittest.TestCase):
    def test_its_part_of_when_the_page_shows(self):
        page = {"tier": "when", "elements": [{"type": "flight_follow", "flight": "W43186"}]}
        self.assertEqual(len(widgets.widget_part(page)), 1)
        self.assertEqual(widgets.widget_part({"elements": [{"type": "flight_follow", "flight": ""}]}), [])


class TestThePage(unittest.TestCase):
    NOW = datetime(2026, 10, 30, 14, 0, tzinfo=ZoneInfo("Europe/Bucharest"))

    def air(self, **more):
        import examples
        return {**examples.followed(self.NOW), "tz": "Europe/Bucharest", **more}

    def texts(self, el, data, box=(24, 14, 744, 208), lang="en"):
        with words.speaking(lang):
            got = draw.plan({"flight": "W43186", **el}, data, box, now=self.NOW)
        return [ln.text for ln in got[0]], got[1]

    def test_in_the_air(self):
        texts, extra = self.texts({}, self.air())
        self.assertEqual(texts[:2], ["W4 3186", "Valencia → Bucharest"])
        self.assertIn("53 min", texts)
        self.assertIn("11,278 m", texts)
        self.assertAlmostEqual(extra["done"], 1 - 742 / 2296, places=3)

    def test_asleep_it_says_when_it_arrives(self):
        texts, _ = self.texts({"asleep": True}, self.air())
        self.assertIn("about 14:52", texts)
        self.assertNotIn("Time left", texts)

    def test_landing(self):
        texts, _ = self.texts({}, self.air(left_km=12, altitude_m=900))
        self.assertIn("Landing", texts)

    def test_before_and_after(self):
        seen = self.NOW.timestamp() - 600
        cases = {"waiting": ["W4 3186", "Not in the air", "Valencia → Bucharest"],
                 "landed": ["W4 3186", "Landed in Bucharest", "Last seen at 13:50"],
                 "lost": ["W4 3186", "Out of view", "Last seen at 13:50 · Valencia → Bucharest"]}
        for status, want in cases.items():
            with self.subTest(status=status):
                texts, _ = self.texts({}, self.air(status=status, seen_at=seen))
                self.assertEqual(texts, want)
        texts, _ = self.texts({}, {"ident": "BA117", "flight": "BA117", "status": "waiting", "tz": None})
        self.assertEqual(texts, ["BA 117", "Not in the air", "It shows here once it takes off."])

    def test_an_old_position_says_so(self):
        texts, _ = self.texts({}, self.air(seen_at=self.NOW.timestamp() - 900))
        self.assertIn("Position from 13:45", texts)

    def test_messages(self):
        with words.speaking("fr"):
            lines, extra = draw.plan({"flight": ""}, None, (0, 0, 744, 208))
            self.assertTrue(extra["message"])
            self.assertEqual(lines[0].text, "Saisissez un numéro de vol")
            lines, extra = draw.plan({"flight": "W43186"}, {"ident": "W43186", "failing": True}, (0, 0, 744, 208))
            self.assertIn("ne répond pas", lines[0].text)
        self.assertIsNone(draw.plan({"flight": "W43186"}, None, (0, 0, 744, 208)), "nothing fetched yet stays blank")

    def test_every_word_fits_everywhere(self):
        base = arrange.canvas_key(792, 272)
        seen = self.NOW.timestamp() - 900
        states = [self.air(), self.air(status="landed", seen_at=seen), self.air(status="lost", seen_at=seen),
                  {"ident": "BAW17R", "flight": "BAW17R", "status": "waiting"}]
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            p = arrange.auto_box({"x": 24, "y": 14, "w": 744, "h": 208}, base, arrange.canvas_key(d["w"], d["h"]))
            for box in ((p["x"], p["y"], p["w"], p["h"]), (20, 14, d["w"] - 40, d["h"] - T.band_height(d["h"]) - 24)):
                for lang in words.LANGUAGES:
                    for data in states:
                        for asleep in (False, True):
                            with self.subTest(display=key, box=box, lang=lang, status=data["status"], asleep=asleep), words.speaking(lang):
                                lines, extra = draw.plan({"flight": data["flight"], "asleep": asleep}, data, box, now=self.NOW)
                                for ln in lines:
                                    self.assertTrue(ln.fits(), (ln.text, ln.w))
                                    self.assertLessEqual(ln.x + ln.w, box[0] + box[2])
                                    self.assertLessEqual(ln.y + ln.px, box[1] + box[3] + 4, ln.text)
                                ys = sorted((ln.y, ln.y + ln.px, ln.x) for ln in lines)
                                for (a0, a1, ax), (b0, b1, bx) in zip(ys, ys[1:]):
                                    if ax == bx:
                                        self.assertLessEqual(a1, b0 + 2, "lines in one column never overlap")

    def test_it_draws(self):
        from PIL import Image, ImageDraw
        img = Image.new("L", (792, 272), T.WHITE)
        draw.draw(img, ImageDraw.Draw(img), (24, 14, 744, 208), {"flight": "W43186"}, self.air())
        self.assertLess(min(img.tobytes()), 128)


if __name__ == "__main__":
    unittest.main()


class TestTheEditorReadsItTheSameWay(unittest.TestCase):
    def test_flight_ident(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("no node to read the editor")
        from test_presets import run_js
        typed = [" w4 3186 ", "baw-17r", "", "BA", "WIZZAIR", "<b>1</b>", "123456789", "0B1234"]
        got = run_js(f"console.log(JSON.stringify({json_list(typed)}.map(P.flightIdent)))")
        self.assertEqual(got, [F.ident_of(t) for t in typed])


def json_list(xs):
    import json
    return json.dumps(xs)
