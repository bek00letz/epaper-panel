"""Each place a Planes page watches gets its own pair of aircraft sensors
(entities.place_suffixes). The first keeps the plain names; the rest are told
apart by label, coordinates, or Home and radius, and never share a name."""
import unittest

import support  # noqa: F401  (puts the add-on on the path)
from entities import place_suffixes
from sources.flights import place_of


class TestPlaceSuffixes(unittest.TestCase):
    def test_the_first_place_keeps_the_plain_names(self):
        self.assertEqual(place_suffixes([(None, None, 35.0, "", "")]), [""])

    def test_a_label_then_coordinates_name_the_others(self):
        places = [(None, None, 35.0, "", ""), (44.43, 26.1, 20.0, "Office", ""), (-33.87, 151.21, 20.0, "", "")]
        self.assertEqual(place_suffixes(places), ["", "_office", "_m33_87_151_21"])

    def test_a_second_home_place_differs_by_its_radius(self):
        # A copied Planes page at Home with another radius: this used to stop every render.
        pages = [{"type": "flights"}, {"type": "flights", "radius": 20}]
        places = [(*place_of(el), "") for el in pages]
        self.assertEqual(place_suffixes(places), ["", "_home_20km"])
        self.assertEqual(place_suffixes([(None, None, 35.0, "", ""), (None, None, 12.5, "", "")]),
                         ["", "_home_12_5km"])

    def test_two_places_never_share_a_name(self):
        places = [(None, None, 35.0, "", ""), (1.0, 2.0, 10.0, "Office", ""), (3.0, 4.0, 10.0, "Office", ""),
                  (5.0, 6.0, 10.0, "Office", "")]
        suffixes = place_suffixes(places)
        self.assertEqual(suffixes, ["", "_office", "_office_2", "_office_3"])
        self.assertEqual(len(set(suffixes)), len(suffixes))


if __name__ == "__main__":
    unittest.main()
