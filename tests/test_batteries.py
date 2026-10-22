"""Batteries: Dynamic status with a number rule. Each battery shows while its level is past the
page's threshold (or its own), lowest first, with Home Assistant's glyph for its level and the
level itself large. The user's call (22 Oct): built on Dynamic status, one threshold for the page
that any battery can override, picked batteries, one direction per page."""
import json
import shutil
import subprocess
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import support  # noqa: F401  (the add-on on the path)
import examples
from render import layout, states

BATTS = [("sensor.smoke_alarm_battery", "8"), ("sensor.door_sensor_battery", "21"),
         ("sensor.remote_battery", "34"), ("sensor.thermostat_battery", "76")]


def grid(rule="below", value=40, **extra):
    return {"type": "dynamic_grid", "x": 20, "y": 16, "w": 752, "h": 214, "filter_rule": rule, "filter_value": value,
            "header_title": "Low batteries", "header_icon": "mdi:battery-alert",
            "items": [{"entity": e, "name": "", "icon": ""} for e, _ in BATTS], **extra}


def resolved(levels=None):
    levels = levels or dict(BATTS)
    return json.dumps([{"entity": e, "state": v, "name": e.split(".")[1].replace("_", " ").title(), "unit": "%",
                        "device_class": "battery", "changed": "2 days ago"} for e, v in levels.items()])


def drawn(el, raw):
    """What the grid draws: its texts and icons, in order."""
    img = Image.new("1", (800, 480), 1)
    d = ImageDraw.Draw(img)
    texts, icons = [], []
    real_text = d.text
    d.text = lambda xy, txt, **kw: (texts.append(txt), real_text(xy, txt, **kw))
    with mock.patch.object(layout, "_draw_icon_glyph", lambda _d, name, *a: icons.append(name)):
        layout._draw_dynamic_grid(img, d, el, raw)
    return texts, icons


class TestTheRule(unittest.TestCase):
    def test_below_is_strict_at_least_includes_it(self):
        self.assertTrue(layout._past(39, "below", None, 40))
        self.assertFalse(layout._past(40, "below", None, 40))
        self.assertTrue(layout._past(90, "at_least", None, 90))
        self.assertFalse(layout._past(89, "at_least", None, 90))

    def test_a_battery_can_have_its_own(self):
        self.assertTrue(layout._past(12, "below", 15, 40))
        self.assertFalse(layout._past(20, "below", 15, 40), "its own 15 % wins over the page's 40 %")
        self.assertTrue(layout._past(20, "below", "", 40), "an empty override is the page's")
        self.assertFalse(layout._past(20, "below", None, None), "no threshold at all shows nothing")

    def test_home_assistants_glyph_for_a_level(self):
        self.assertEqual([states.battery_icon(v) for v in (3, 8, 21, 54, 96, 100, "unknown")],
                         ["mdi:battery-alert-variant-outline", "mdi:battery-10", "mdi:battery-20", "mdi:battery-50",
                          "mdi:battery", "mdi:battery", "mdi:battery-unknown"])


class TestTheGrid(unittest.TestCase):
    def test_only_whats_past_shows_lowest_first_with_its_level(self):
        texts, icons = drawn(grid(), resolved({"sensor.remote_battery": "34", "sensor.smoke_alarm_battery": "8",
                                               "sensor.thermostat_battery": "76", "sensor.door_sensor_battery": "21"}))
        self.assertEqual([t for t in texts if t.endswith("%")], ["8%", "21%", "34%"])
        self.assertEqual(icons[1:], ["mdi:battery-10", "mdi:battery-20", "mdi:battery-30"], "after the heading's own icon")
        self.assertIn("3 of 4", texts)
        self.assertFalse([t for t in texts if t in ("ON", "ACTIVE", "8", "21")], "no state pill: the level says it")

    def test_charged_is_fullest_first(self):
        texts, _ = drawn(grid("at_least", 30), resolved())
        self.assertEqual([t for t in texts if t.endswith("%")], ["76%", "34%"])

    def test_its_own_threshold_and_its_own_icon(self):
        el = grid()
        el["items"][2]["threshold"] = 30                  # the remote only when below 30 %
        el["items"][0]["icon"] = "mdi:smoke-detector"
        texts, icons = drawn(el, resolved())
        self.assertEqual([t for t in texts if t.endswith("%")], ["8%", "21%"])
        self.assertEqual(icons[1], "mdi:smoke-detector")

    def test_no_level_never_shows(self):
        texts, _ = drawn(grid(), resolved({"sensor.smoke_alarm_battery": "unavailable", "sensor.door_sensor_battery": "21"}))
        self.assertEqual([t for t in texts if t.endswith("%")], ["21%"])

    def test_one_battery_alone_reads_large(self):
        texts, icons = drawn(grid(), resolved({"sensor.smoke_alarm_battery": "8", "sensor.door_sensor_battery": "60"}))
        self.assertIn("8%", texts)
        self.assertNotIn("ACTIVE", texts)
        self.assertEqual(icons[-1], "mdi:battery-10")

    def test_a_state_grid_is_as_before(self):
        el = {"type": "dynamic_grid", "x": 20, "y": 16, "w": 752, "h": 214, "filter_state": "on",
              "items": [{"entity": "switch.a"}, {"entity": "switch.b"}]}
        raw = json.dumps([{"entity": "switch.a", "state": "on", "name": "A", "changed": "5 minutes ago"},
                          {"entity": "switch.b", "state": "on", "name": "B", "changed": ""}])
        texts, _ = drawn(el, raw)
        self.assertIn("ON", texts)


class TestTheTemplateAndTheExamples(unittest.TestCase):
    def test_the_values_carry_unit_and_kind(self):
        tpl = layout.collect_templates({"elements": [grid()]})[0]
        self.assertIn('"unit": {{ (state_attr(e, "unit_of_measurement") or "") | to_json }}', tpl)
        self.assertIn('"device_class": {{ (state_attr(e, "device_class") or "") | to_json }}', tpl)

    def test_the_example_batteries(self):
        vals, _ = examples.page_values({"elements": [grid()]})
        got = {r["entity"]: (r["state"], r["unit"], r["device_class"]) for r in json.loads(vals[0])}
        self.assertEqual(got["sensor.smoke_alarm_battery"], ("8", "%", "battery"))
        self.assertEqual(len(got), 4)


APP_JS = support.APP / "web" / "app"


def node(js):
    src = (APP_JS / "conditions.js").as_uri()
    out = subprocess.run(["node", "--input-type=module", "-e", f"import * as C from {json.dumps(src)};\n{js}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@unittest.skipUnless(shutil.which("node"), "no node to read the editor")
class TestThePageShowsWhileOneDoes(unittest.TestCase):
    GRID = """{ type: "dynamic_grid", filter_rule: "below", filter_value: 40,
                items: [{ entity: "sensor.a" }, { entity: "sensor.b", threshold: 15 }, { entity: "" }] }"""

    def test_the_condition_is_guarded_and_takes_each_ones_own(self):
        got = node(f"console.log(JSON.stringify(C.gridShowIf({self.GRID})))")
        self.assertEqual(got, "{{ (has_value('sensor.a') and states('sensor.a') | float(0) < 40) or "
                              "(has_value('sensor.b') and states('sensor.b') | float(0) < 15) }}")
        got = node("""console.log(JSON.stringify(C.gridShowIf({ filter_rule: "at_least", filter_value: 90, items: [{ entity: "sensor.a" }] })))""")
        self.assertEqual(got, "{{ (has_value('sensor.a') and states('sensor.a') | float(0) >= 90) }}")

    def test_a_state_grid_writes_what_it_wrote_before(self):
        got = node("""console.log(JSON.stringify(C.gridShowIf({ filter_state: "on", items: [{ entity: "switch.x" }, { entity: "switch.y" }] })))""")
        self.assertEqual(got, "{{ is_state('switch.x','on') or is_state('switch.y','on') }}")

    def test_an_alert_follows_its_grid_but_keeps_your_own_condition(self):
        got = node(f"""const g = {self.GRID};
          const fresh = {{ tier: "alert", elements: [g] }}; C.syncDynamicGridShowIf(fresh);
          const yours = {{ tier: "alert", show_if: "{{{{ is_state('person.x','home') }}}}", elements: [g] }}; C.syncDynamicGridShowIf(yours);
          g.items.splice(0, 1); C.syncDynamicGridShowIf(fresh);
          console.log(JSON.stringify([fresh.show_if, yours.show_if]))""")
        self.assertEqual(got[0], "{{ (has_value('sensor.b') and states('sensor.b') | float(0) < 15) }}", "and keeps following after a removal")
        self.assertEqual(got[1], "{{ is_state('person.x','home') }}")

    def test_the_inspector_offers_the_rule(self):
        js = (APP_JS / "inspector.js").read_text()
        self.assertIn('field("Shows each", select(GRID_RULES, gridRule(el)', js)
        self.assertIn("field(`Its own ${cmp.toLowerCase()}`, number(it.threshold", js)
        self.assertIn('if (v === "alert") syncDynamicGridShowIf(p);', (APP_JS / "main.js").read_text())


if __name__ == "__main__":
    unittest.main()
