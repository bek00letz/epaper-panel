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


NAMES = ["Smoke Alarm Battery", "Door Sensor Battery", "Remote Battery", "Thermostat Battery", "Kitchen Remote Battery", "Balcony Window Battery",
         "Hallway Sensor Battery", "Plant Sensor Battery", "Bedroom Remote Battery", "Garage Door Battery", "Office Button Battery", "Attic Smoke Battery"]


class TestTheList(unittest.TestCase):
    """The user's call (22 Oct): a row each, so names read at every size; the cards clipped them."""

    def listed(self, w, h, n):
        el = {**grid(), "x": 0, "y": 0, "w": w, "h": h, "layout_mode": "list",
              "items": [{"entity": f"sensor.b{i}", "name": "", "icon": ""} for i in range(n)]}
        raw = json.dumps([{"entity": f"sensor.b{i}", "state": str(5 + 3 * i), "name": NAMES[i], "unit": "%", "device_class": "battery"} for i in range(n)])
        return drawn(el, raw)[0]

    def test_no_name_is_cut_at_the_offered_sizes(self):
        for w, h, size in [(752, 214, '5.79"'), (376, 240, '4.2"'), (280, 100, '2.9"'), (240, 360, '4.2" upright')]:
            for n in (1, 3, 5, 8, 12):
                with self.subTest(size=size, batteries=n):
                    self.assertFalse([t for t in self.listed(w, h, n) if "…" in t])

    def test_what_doesnt_fit_is_counted(self):
        texts = self.listed(752, 214, 12)
        self.assertIn("and 3 more", texts)
        self.assertEqual(len([t for t in texts if t.endswith("%")]), 9)
        self.assertEqual([t for t in texts if t.endswith("%")][:2], ["5%", "8%"], "emptiest first, down the first column")


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

    def test_its_condition_is_said_in_words(self):
        """Found in the browser check: an alert's grid-written condition showed as a 398-character template."""
        js = (APP_JS / "inspector.js").read_text()
        self.assertIn("if (grid && gridWrote(p[c.key], grid)) {", js)
        self.assertIn("While one on its list ${what}. It follows the list as you change it.", js)
        self.assertIn('linkButton("Write my own condition", () => { app[c.raw] = true; app.refresh(); })', js)

    def test_the_inspector_offers_the_rule(self):
        js = (APP_JS / "inspector.js").read_text()
        self.assertIn('field("Shows each", select(GRID_RULES, gridRule(el)', js)
        self.assertIn("field(`Its own ${cmp.toLowerCase()}`, number(it.threshold", js)
        self.assertIn('if (v === "alert") syncDynamicGridShowIf(p);', (APP_JS / "main.js").read_text())


ENTS = """[
  { entity_id: "sensor.remote_battery", state: "34", unit: "%", device_class: "battery", name: "Remote Battery" },
  { entity_id: "sensor.smoke_alarm_battery", state: "8", unit: "%", device_class: "battery", name: "Smoke Alarm Battery" },
  { entity_id: "sensor.phone_battery_level", state: "95", unit: "%", device_class: "battery", name: "Phone Battery level" },
  { entity_id: "sensor.phone_battery_state", state: "Charging", unit: "", device_class: "", name: "Phone Battery state" },
  { entity_id: "sensor.car_battery", state: "62", unit: "%", device_class: "battery", name: "Car Battery" },
  { entity_id: "binary_sensor.car_charging", state: "off", unit: "", device_class: "battery_charging", name: "Car Charging" },
  { entity_id: "sensor.gone_battery", state: "unavailable", unit: "%", device_class: "battery", name: "Gone Battery" },
  { entity_id: "sensor.voltage_battery", state: "2.9", unit: "V", device_class: "voltage", name: "Remote Battery voltage" }]"""


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestThePreset(unittest.TestCase):
    def setUp(self):
        from test_presets import run_js
        self.js = run_js

    def test_the_batteries_emptiest_first(self):
        got = self.js(f"console.log(JSON.stringify(P.batterySensors({ENTS}).map((e) => e.entity_id)))")
        self.assertEqual(got, ["sensor.smoke_alarm_battery", "sensor.remote_battery", "sensor.car_battery", "sensor.phone_battery_level",
                               "sensor.gone_battery"], "levels in %, no level last; a voltage isn't one")

    def test_ticked_to_start_with_by_what_they_are(self):
        """Low: what you swap (no charging state beside it), with a level. Charged: what you charge."""
        got = self.js(f"""console.log(JSON.stringify([P.preselectBatteries({ENTS}, "below"), P.preselectBatteries({ENTS}, "at_least")]))""")
        self.assertEqual(got[0], ["sensor.smoke_alarm_battery", "sensor.remote_battery"])
        self.assertEqual(got[1], ["sensor.car_battery", "sensor.phone_battery_level"])

    def test_how_many_would_show(self):
        got = self.js(f"""const c = new Set(["sensor.smoke_alarm_battery", "sensor.remote_battery", "sensor.gone_battery"]);
          console.log(JSON.stringify([P.batteriesPast({ENTS}, c, "below", 20), P.batteriesPast({ENTS}, c, "below", 40), P.batteriesPast({ENTS}, c, "at_least", 30)]))""")
        self.assertEqual(got, [1, 2, 1])

    def test_the_page_it_makes(self):
        got = self.js("""const p = P.presetById("batteries"), l = p.looks[0];
          const low = P.pageFor(p, l, "", { rule: "below", value: 30, items: ["sensor.a", "sensor.b"], tier: "when" });
          const full = P.pageFor(p, l, "", { rule: "at_least", value: 95, items: ["sensor.c"], tier: "alert" });
          console.log(JSON.stringify({ low, full, names: [P.pageName(p, l, "", "", { rule: "below" }), P.pageName(p, l, "", "", { rule: "at_least" })],
            group: p.group, needs: p.needs, example: P.examplePage(p, l) }))""")
        g = got["low"]["elements"][0]
        self.assertEqual((got["low"]["tier"], g["type"], g["filter_rule"], g["filter_value"], g["header_title"]), ("when", "dynamic_grid", "below", 30, "Low batteries"))
        self.assertEqual([i["entity"] for i in g["items"]], ["sensor.a", "sensor.b"])
        self.assertEqual([i["icon"] for i in g["items"]], ["", ""], "Home Assistant's glyph for each level")
        f = got["full"]["elements"][0]
        self.assertEqual((got["full"]["tier"], f["filter_rule"], f["filter_value"], f["header_title"]), ("alert", "at_least", 95, "Charged"))
        self.assertEqual(got["names"], ["Low batteries", "Charged"])
        self.assertEqual((got["group"], got["needs"]), ("home", "batteries"))
        self.assertEqual(len(got["example"]["elements"][0]["items"]), 4)

    def test_the_example_thumbnail_shows_three_of_four(self):
        page = self.js("""const p = P.presetById("batteries"); console.log(JSON.stringify(P.examplePage(p, p.looks[0])))""")
        vals, _ = examples.page_values(page)
        texts, icons = drawn(page["elements"][0], vals[0])
        self.assertEqual([t for t in texts if t.endswith("%")], ["8%", "21%", "34%"])
        self.assertIn("Smoke Alarm", texts, "\"Battery\" dropped from each name on a page of batteries")

    def test_it_lists_them(self):
        page = self.js("""const p = P.presetById("batteries"); console.log(JSON.stringify(P.examplePage(p, p.looks[0])))""")
        self.assertEqual(page["elements"][0]["layout_mode"], "list")
        self.assertIn('["list", "List"]', (APP_JS / "inspector.js").read_text())

    def test_its_step(self):
        js = (APP_JS / "setup.js").read_text()
        self.assertIn("batteries: batteriesSetup };", js)
        self.assertIn('seg([["below", "Low, to charge"], ["at_least", "Charged, to unplug"]]', js)
        self.assertIn('seg([["when", "With the pages"], ["alert", "As an alert"]]', js)
        self.assertIn("if (!touched) chosen = new Set(preselectBatteries(app.ents, rule));", js)
        self.assertIn("syncDynamicGridShowIf(page);", (APP_JS / "newpage.js").read_text(), "an alert takes its grid's condition")


if __name__ == "__main__":
    unittest.main()
