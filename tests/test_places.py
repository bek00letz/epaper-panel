"""The flight widget's places: airport codes, saved places, and coordinates."""
import json
import unittest

from aiohttp.test_utils import make_mocked_request

import support  # noqa: F401
import airports
import layouts_store
import web
from sources.flights import place_of


class TestAirports(unittest.IsolatedAsyncioTestCase):
    def test_codes_resolve_offline(self):
        lhr = airports.lookup("lhr")
        self.assertEqual(lhr["code"], "LHR")
        self.assertAlmostEqual(lhr["lat"], 51.47, places=1)
        self.assertIn("Heathrow", lhr["name"])
        self.assertIsNone(airports.lookup("ZZZ"))
        self.assertIsNone(airports.lookup("LONDON"))

    async def test_endpoint_explains_a_miss(self):
        r = await web.api_airport(make_mocked_request("GET", "/api/airport?code=qqq"))
        self.assertEqual(r.status, 404)
        self.assertIn("QQQ", json.loads(r.text)["error"])


class TestPlaces(unittest.TestCase):
    def test_zero_is_a_real_coordinate(self):
        self.assertEqual(place_of({"lat": 0, "lon": 0})[:2], (0.0, 0.0))
        self.assertEqual(place_of({"latitude": "51.5", "longitude": "-0.1"})[:2], (51.5, -0.1))
        self.assertEqual(place_of({"lat": 51.5})[:2], (None, None), "half a place is Home")
        self.assertEqual(place_of({})[2], 35.0)

    def test_saved_places_are_yours_and_at_most_four(self):
        spec = {"pages": {}, "location_presets": [
            {"label": "TSR", "lat": 45.81, "lon": 21.34}, {"label": "Mum's", "lat": "44.4", "lon": "26.1"},
            {"label": "bad", "lat": 200, "lon": 0}, {"label": "x", "lat": "nope"},
            {"label": "A", "lat": 1, "lon": 1}, {"label": "B", "lat": 2, "lon": 2}, {"label": "C", "lat": 3, "lon": 3}]}
        places = layouts_store.sanitize_layouts(spec)["location_presets"]
        self.assertEqual([p["label"] for p in places], ["TSR", "Mum's", "A", "B"], "four valid places, the rest dropped")
        self.assertEqual(places[1]["lat"], 44.4)


if __name__ == "__main__":
    unittest.main()
