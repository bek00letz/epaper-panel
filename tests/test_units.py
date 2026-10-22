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


class TestAUnitFollowsItsSensor(unittest.TestCase):
    """Review 2 #3: a number or gauge keeps unit "entity" and shows its sensor's unit at every render."""

    def setUp(self):
        from render import layout, theme as T
        self.layout, self.T = layout, T

    def same_as_typed(self, el, value, unit):
        """The page drawn with the unit from its sensor is the page with that unit typed after it."""
        follows = self.layout.render_page({"elements": [el]}, {0: value, "__unit_0": unit})
        typed = {k: v for k, v in el.items() if k != "unit"}
        typed["suffix"] = units.suffix_for(unit)
        return follows.tobytes() == self.layout.render_page({"elements": [typed]}, {0: value}).tobytes()

    def test_the_render_asks_for_the_unit_and_shows_it(self):
        el = {"type": "number", "entity": "sensor.outside", "unit": "entity", "decimals": 1, "x": 0, "y": 0, "w": 300, "h": 90}
        tpls = self.layout.collect_templates({"elements": [el]})
        self.assertEqual(tpls["__unit_0"], "{{ state_attr('sensor.outside', 'unit_of_measurement') or '' }}")
        self.assertTrue(self.same_as_typed(el, "21.4", "°C"))
        self.assertTrue(self.same_as_typed(el, "70.5", "°F"), "Home Assistant switched units: so does the page")
        self.assertEqual(units.suffix_for("%"), "%")
        self.assertEqual(units.suffix_for(""), "")

    def test_a_gauge_follows_too_and_shows_no_made_up_percent(self):
        from PIL import Image
        bar = {"type": "bar", "entity": "sensor.load", "unit": "entity", "min_val": 0, "max_val": 5000, "show_label": True,
               "decimals": 0, "x": 0, "y": 0, "w": 400, "h": 80}
        a = self.layout.render_page({"elements": [bar]}, {0: "640", "__unit_0": "W"})
        b = self.layout.render_page({"elements": [bar]}, {0: "640", "__unit_0": "kW"})
        self.assertNotEqual(a.tobytes(), b.tobytes())

    def test_offline_the_fixtures_unit(self):
        import examples
        el = {"type": "number", "entity": "sensor.indoor_temperature", "unit": "entity"}
        vals, _ = examples.page_values({"elements": [el]})
        self.assertEqual(vals["__unit_0"], "°C")

    def test_pages_made_before_follow_when_their_unit_was_the_sensors(self):
        pages = {"p": {"elements": [
            {"type": "number", "entity": "sensor.t", "suffix": " °C"},                 # copied in: follows now
            {"type": "bar", "entity": "sensor.b", "suffix": "%"},
            {"type": "number", "entity": "sensor.w", "suffix": " watts"},              # your own word: stays
            {"type": "number", "entity": "sensor.t", "value": "{{ 1 }}", "suffix": " °C"},   # a template: yours
        ]}}
        self.assertEqual(units.follow_units(pages, {"sensor.t": "°C", "sensor.b": "%", "sensor.w": "W"}), ["p"])
        els = pages["p"]["elements"]
        self.assertEqual([(e.get("unit"), e.get("suffix")) for e in els],
                         [("entity", None), ("entity", None), (None, " watts"), (None, " °C")])
        self.assertEqual(units.follow_units(pages, {"sensor.t": "°C"}), [], "once")


class TestSavedPagesFollowAtRender(unittest.TestCase):
    def test_a_saved_design_follows_its_sensors_unit(self):
        import asyncio
        from unittest import mock
        import devices
        import frames
        import support as sup
        from sources import ha_services
        sup.fresh_data_dir()
        dev = devices.primary()
        found = devices.design(dev["design"])
        found["pages"] = {"temp": {"elements": [{"type": "number", "entity": "sensor.t", "suffix": " °C"}]}}
        devices._save_design(dev["design"], found)
        with mock.patch.object(ha_services, "fetch_units", mock.AsyncMock(return_value={"sensor.t": "°C"})):
            done = asyncio.run(frames.follow_sensor_units(None))
        self.assertEqual(done, [f"{dev['design']}:temp"])
        self.assertEqual(devices.design(dev["design"])["pages"]["temp"]["elements"][0]["unit"], "entity")
        sup.use_test_data_dir()
