"""The places Planes pages watch, and each one's pair of aircraft sensors
(entities.aircraft_places, entities.place_suffixes). A place is where it is:
pages at the same spot share it whatever distance each watches. The first place
keeps the plain sensor names; the rest are told apart by label, coordinates or
"home", and never share a name."""
import unittest

import support  # noqa: F401  (puts the add-on on the path)
from entities import aircraft_places, place_suffixes


class TestAircraftPlaces(unittest.TestCase):
    def test_home_is_one_place_whatever_the_distance(self):
        # A copied Planes page at Home with another distance: this used to stop every render.
        places = aircraft_places([{"type": "flights"}, {"type": "flights", "radius": 20},
                                  {"type": "flights", "radius": 50}])
        self.assertEqual(places, [(None, None, 50.0, "", "")])
        self.assertEqual(place_suffixes(places), [""])

    def test_the_same_spot_shares_its_first_name(self):
        places = aircraft_places([{"lat": 44.43, "lon": 26.1, "radius": 10},
                                  {"lat": 44.43, "lon": 26.1, "radius": 30, "location_name": "Office"}])
        self.assertEqual(places, [(44.43, 26.1, 30.0, "Office", "")])

    def test_different_spots_stay_apart(self):
        places = aircraft_places([{"type": "flights"}, {"lat": 44.43, "lon": 26.1, "location_name": "Office"}])
        self.assertEqual([p[:2] for p in places], [(None, None), (44.43, 26.1)])


class TestPlaceSuffixes(unittest.TestCase):
    def test_the_first_place_keeps_the_plain_names(self):
        self.assertEqual(place_suffixes([(None, None, 35.0, "", "")]), [""])

    def test_a_label_then_coordinates_then_home_name_the_others(self):
        places = [(44.43, 26.1, 20.0, "Office", ""), (-33.87, 151.21, 20.0, "", ""), (None, None, 35.0, "", "")]
        self.assertEqual(place_suffixes(places), ["", "_m33_87_151_21", "_home"])

    def test_two_places_never_share_a_name(self):
        places = [(None, None, 35.0, "", ""), (1.0, 2.0, 10.0, "Office", ""), (3.0, 4.0, 10.0, "Office", ""),
                  (5.0, 6.0, 10.0, "Office", "")]
        suffixes = place_suffixes(places)
        self.assertEqual(suffixes, ["", "_office", "_office_2", "_office_3"])
        self.assertEqual(len(set(suffixes)), len(suffixes))


if __name__ == "__main__":
    unittest.main()
