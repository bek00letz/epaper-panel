"""Dynamic units: values that pick their own unit, and labels that follow."""
import unittest

import support  # noqa: F401
from render import binding, layout, units


def number(**kw):
    return {"type": "number", "entity": "sensor.solar_power", "decimals": 0, **kw}


class TestScaling(unittest.TestCase):
    def test_watts_step_up_to_kilowatts(self):
        el = number(units={"base": "W", "mode": "scale", "decimals": 2})
        self.assertEqual(layout.element_text(el, {0: "950"}, 0), "950 W")
        self.assertEqual(layout.element_text(el, {0: "1234"}, 0), "1.23 kW")
        self.assertEqual(layout.element_text(el, {0: "2500000"}, 0), "2.50 MW")
        self.assertEqual(layout.element_text(el, {0: "-1500"}, 0), "-1.50 kW", "export to the grid scales too")

    def test_never_steps_below_the_sensors_own_unit(self):
        el = number(units={"base": "kW", "mode": "scale"}, decimals=2)
        self.assertEqual(layout.element_text(el, {0: "0.5"}, 0), "0.50 kW")

    def test_other_families(self):
        self.assertEqual(units.apply(1500, {"base": "g"})[:2], (1.5, "kg"))
        self.assertEqual(units.apply(2500, {"base": "m"})[:2], (2.5, "km"))
        self.assertEqual(units.apply(5400, {"base": "s"})[:2], (1.5, "h"))
        self.assertEqual(units.apply(12_000_000, {"base": "B"})[:2], (12.0, "MB"))
        self.assertEqual(units.apply(3200, {"base": "Wh"})[:2], (3.2, "kWh"))

    def test_conversions(self):
        v, u, changed = units.apply(10, {"base": "m/s", "mode": "convert", "to": "km/h"})
        self.assertAlmostEqual(v, 36.0)
        self.assertEqual((u, changed), ("km/h", True))
        self.assertEqual(units.apply(100, {"base": "°C", "mode": "convert", "to": "°F"})[:2], (212.0, "°F"))
        self.assertEqual(units.apply(5, {"base": "W", "mode": "convert", "to": "nonsense"})[:2], (5, "W"))

    def test_prefix_and_suffix_still_wrap_it(self):
        el = number(units={"base": "W"}, prefix="now ", suffix=" used")
        self.assertEqual(layout.element_text(el, {0: "1234"}, 0), "now 1.23 kW used")

    def test_unknown_unit_or_text_is_left_alone(self):
        self.assertEqual(layout.element_text(number(units={"base": "lux"}), {0: "1234"}, 0), "1234 lux")
        self.assertEqual(layout.element_text(number(units={"base": "W"}, fallback="--"), {0: "unavailable"}, 0), "--")

    def test_number_alone_when_a_label_says_the_unit(self):
        el = number(units={"base": "W", "decimals": 2, "show_unit": False})
        self.assertEqual(layout.element_text(el, {0: "355"}, 0), "355")
        self.assertEqual(layout.element_text(el, {0: "1234"}, 0), "1.23", "still steps up, just without the unit")
        label = {"type": "text", "entity": "sensor.solar_power", "show": "unit", "units": {"base": "W", "show_unit": False}}
        self.assertEqual(layout.element_text(label, {0: "1234"}, 0), "kW", "the label follows either way")

    def test_without_units_nothing_changes(self):
        self.assertEqual(layout.element_text(number(suffix=" W"), {0: "1234"}, 0), "1234 W")


class TestUnitLabels(unittest.TestCase):
    def label(self, **kw):
        return {"type": "text", "entity": "sensor.solar_power", "show": "unit", "units": {"base": "W"}, **kw}

    def test_label_follows_the_value(self):
        el = self.label(suffix=" used", replace={"W": "Watts"})
        self.assertEqual(layout.element_text(el, {0: "950"}, 0), "Watts used")
        self.assertEqual(layout.element_text(el, {0: "1234"}, 0), "kW used")

    def test_label_asks_home_assistant_for_the_value_not_a_replaced_one(self):
        tpl = binding.template_for(self.label(replace={"W": "Watts"}))
        self.assertEqual(tpl, "{{ states('sensor.solar_power') }}")

    def test_label_from_the_add_ons_own_sensor(self):
        reg = {"sensor.epaper_power": {"state": "2048"}}
        el = self.label(entity="sensor.epaper_power", replace={"W": "Watts"})
        self.assertEqual(binding.local_value(el, reg), "2048", "replacements wait for the unit")


if __name__ == "__main__":
    unittest.main()
