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

    def test_one_word_keeps_its_ends(self):
        """The coordinator's call: on the 2.9" upright, a word too long even at the smallest keeps its start
        and its end around an ellipsis."""
        texts = self.listed(110, 260, 5)
        self.assertIn("Ther…stat", texts)
        self.assertEqual(layout._fit_middle("Thermostat", 1000, layout.T.font(14)), "Thermostat")
        self.assertEqual(layout.LIST_TEXT_MIN, 14)

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
          const low = P.pageFor(p, l, "", { rule: "below", value: 30, except: ["sensor.a"], also: ["sensor.b"], tier: "when" });
          const full = P.pageFor(p, l, "", { rule: "at_least", value: 95, except: [], also: [], tier: "alert" });
          console.log(JSON.stringify({ low, full, names: [P.pageName(p, l, "", "", { rule: "below" }), P.pageName(p, l, "", "", { rule: "at_least" })],
            group: p.group, needs: p.needs, example: P.examplePage(p, l) }))""")
        g = got["low"]["elements"][0]
        self.assertEqual((got["low"]["tier"], g["type"], g["filter_rule"], g["filter_value"], g["header_title"]), ("when", "dynamic_grid", "below", 30, "Low batteries"))
        # A rule, not today's list (review 2 #5): its kind, minus the unticked, plus the other kind's ticked.
        self.assertEqual((g["batteries"], g["except"], g["also"], g["items"]), ("swap", ["sensor.a"], ["sensor.b"], []))
        f = got["full"]["elements"][0]
        self.assertEqual((got["full"]["tier"], f["filter_rule"], f["filter_value"], f["header_title"], f["batteries"]),
                         ("alert", "at_least", 95, "Charged", "charge"))
        self.assertEqual(got["names"], ["Low batteries", "Charged"])
        self.assertEqual((got["group"], got["needs"]), ("home", "batteries"))
        self.assertEqual(got["example"]["elements"][0]["batteries"], "swap", "the example follows the rule too")

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
        self.assertIn("if (!touched && byDevice) chosen = new Set(preselectBatteries(app.ents, rule, byDevice));", js)
        self.assertIn("syncDynamicGridShowIf(page);", (APP_JS / "newpage.js").read_text(), "an alert takes its grid's condition")


class TestChargedByYouByDevice(unittest.TestCase):
    """The coordinator's call (22 Oct): which batteries you charge is read from their devices, not
    their names. Two devices named unlike any pattern: one with a charging sensor, one without."""
    STATES = [
        {"entity_id": "sensor.alpha_level", "state": "70", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "binary_sensor.plug_detect", "state": "off", "attributes": {"device_class": "battery_charging"}},
        {"entity_id": "sensor.beta_power_left", "state": "40", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "sensor.beta_signal", "state": "-60", "attributes": {"device_class": "signal_strength"}},
        {"entity_id": "sensor.gamma_pct", "state": "55", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "sensor.gamma_mode", "state": "Not Charging", "attributes": {}},
        {"entity_id": "sensor.delta_pct", "state": "88", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "sensor.delta_status", "state": "idle", "attributes": {"device_class": "enum", "options": ["charging", "discharging", "idle"]}},
        {"entity_id": "sensor.loose_battery", "state": "12", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "sensor.alpha_volts", "state": "3.9", "attributes": {"device_class": "voltage", "unit_of_measurement": "V"}},
    ]
    REGISTRY = [{"entity_id": "sensor.alpha_level", "device_id": "d1"}, {"entity_id": "binary_sensor.plug_detect", "device_id": "d1"},
                {"entity_id": "sensor.alpha_volts", "device_id": "d1"},
                {"entity_id": "sensor.beta_power_left", "device_id": "d2"}, {"entity_id": "sensor.beta_signal", "device_id": "d2"},
                {"entity_id": "sensor.gamma_pct", "device_id": "d3"}, {"entity_id": "sensor.gamma_mode", "device_id": "d3"},
                {"entity_id": "sensor.delta_pct", "device_id": "d4"}, {"entity_id": "sensor.delta_status", "device_id": "d4"},
                {"entity_id": "sensor.loose_battery", "device_id": None}]

    def test_by_device(self):
        from sources import batteries
        self.assertEqual(batteries.charged_by_you(self.REGISTRY, self.STATES),
                         {"sensor.alpha_level": True, "sensor.beta_power_left": False, "sensor.gamma_pct": True,
                          "sensor.delta_pct": True, "sensor.loose_battery": None})

    def test_offline_it_says_nothing(self):
        import asyncio
        from sources import batteries
        with mock.patch.object(batteries, "HA_TOKEN", ""):
            self.assertEqual(asyncio.run(batteries.fetch(None)), {})

    @unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
    def test_the_step_ticks_by_device_then_by_name(self):
        from test_presets import run_js
        ents = """[{ entity_id: "sensor.alpha_level", state: "70", unit: "%", device_class: "battery" },
          { entity_id: "sensor.beta_power_left", state: "40", unit: "%", device_class: "battery" },
          { entity_id: "sensor.pad_battery", state: "30", unit: "%", device_class: "battery" },
          { entity_id: "sensor.pad_battery_state", state: "Charging", unit: "", device_class: "" },
          { entity_id: "sensor.loose_battery", state: "12", unit: "%", device_class: "battery" },
          { entity_id: "sensor.loose_battery_state", state: "Charging", unit: "", device_class: "" }]"""
        dev = '{ "sensor.alpha_level": true, "sensor.beta_power_left": false, "sensor.pad_battery": false, "sensor.loose_battery": null }'
        got = run_js(f"""console.log(JSON.stringify([P.preselectBatteries({ents}, "below", {dev}), P.preselectBatteries({ents}, "at_least", {dev})]))""")
        # The pad's device has no charging sensor, whatever sits beside it by name; the loose one has no device: its name decides.
        self.assertEqual(got, [["sensor.pad_battery", "sensor.beta_power_left"], ["sensor.loose_battery", "sensor.alpha_level"]])
        js = (APP_JS / "setup.js").read_text()
        self.assertIn('api("api/batteries")', js)
        self.assertIn("if (!touched) chosen = new Set(preselectBatteries(app.ents, rule, byDevice));", js)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- Batteries as a rule (review 2 #5)

import asyncio  # noqa: E402

import frames  # noqa: E402
import widgets  # noqa: E402
from sources import batteries  # noqa: E402

REGISTRY = [{"entity_id": "sensor.phone_battery_level", "device_id": "phone"}, {"entity_id": "sensor.phone_battery_state", "device_id": "phone"},
            {"entity_id": "sensor.door_battery", "device_id": "door"}, {"entity_id": "binary_sensor.remote_battery_low", "device_id": "remote"}]


def st(eid, state, dc="battery", unit="%", **attrs):
    return {"entity_id": eid, "state": state, "attributes": {"device_class": dc, "unit_of_measurement": unit, **attrs}}


STATES = [st("sensor.phone_battery_level", "95"), st("sensor.phone_battery_state", "charging", dc=None, unit=None),
          st("sensor.door_battery", "12"), st("binary_sensor.remote_battery_low", "on", unit=None),
          st("sensor.outside_temperature", "3", dc="temperature", unit="°C")]


class TestTheRuleResolves(unittest.TestCase):
    every = batteries.every_battery(REGISTRY, STATES)

    def test_every_battery_low_sensors_included_by_kind(self):
        self.assertEqual({b["entity"]: b["kind"] for b in self.every},
                         {"sensor.phone_battery_level": "charge", "sensor.door_battery": "swap", "binary_sensor.remote_battery_low": "swap"})

    def test_its_kind_minus_except_plus_also(self):
        el = {"batteries": "swap", "except": ["sensor.door_battery"], "also": ["sensor.phone_battery_level"]}
        self.assertEqual([b["entity"] for b in batteries.chosen(el, self.every)],
                         ["sensor.phone_battery_level", "binary_sensor.remote_battery_low"])

    def test_a_low_sensor_is_below_while_on_and_never_charged(self):
        low = next(b for b in self.every if b["entity"].startswith("binary_"))
        self.assertTrue(batteries.past(low, {"filter_rule": "below", "filter_value": 20}))
        self.assertFalse(batteries.past(low, {"filter_rule": "at_least", "filter_value": 20}))
        self.assertFalse(batteries.past({**low, "state": "off"}, {"filter_rule": "below", "filter_value": 20}))

    def test_a_battery_added_later_shows_without_editing_the_page(self):
        el = {"type": "dynamic_grid", "batteries": "swap", "except": [], "also": [], "filter_rule": "below", "filter_value": 20}
        later = batteries.every_battery(REGISTRY, STATES + [st("sensor.new_lock_battery", "5")])
        self.assertIn("sensor.new_lock_battery", [b["entity"] for b in batteries.chosen(el, later)])

    def test_drawn_from_the_rule_with_its_own_settings(self):
        el = {**grid("below", 20), "batteries": "swap", "except": [], "also": [],
              "items": [{"entity": "sensor.door_battery", "threshold": 10}]}
        texts, _ = drawn(el, batteries.chosen(el, self.every))
        self.assertIn("Low", texts, "a low sensor says Low")
        self.assertNotIn("12%", texts, "its own number: 12 isn't below 10")


class TestPagesMadeBeforeTheRule(unittest.TestCase):
    every = batteries.every_battery(REGISTRY, STATES + [st("sensor.lock_battery", "40")])

    def page(self, items, rule="below"):
        return {"tier": "when", "show_if": "{{ (has_value('sensor.door_battery') and states('sensor.door_battery') | float(0) < 20) }}",
                "elements": [{"type": "dynamic_grid", "filter_rule": rule, "filter_value": 20,
                              "items": [{"entity": e, "name": "", "icon": ""} for e in items]}]}

    def test_they_keep_showing_what_they_showed_then_follow_the_rule(self):
        pages = {"low": self.page(["sensor.door_battery", "sensor.phone_battery_level"])}
        self.assertEqual(batteries.migrate(pages, self.every), ["low"])
        el = pages["low"]["elements"][0]
        self.assertEqual((el["batteries"], sorted(el["except"]), el["also"]),
                         ("swap", ["binary_sensor.remote_battery_low", "sensor.lock_battery"], ["sensor.phone_battery_level"]))
        self.assertNotIn("show_if", pages["low"], "the condition over the old list goes; the rule decides")
        today = [b["entity"] for b in batteries.chosen(el, self.every)]
        self.assertEqual(sorted(today), ["sensor.door_battery", "sensor.phone_battery_level"])
        later = self.every + batteries.every_battery([], [st("sensor.new_lock_battery", "5")])
        self.assertIn("sensor.new_lock_battery", [b["entity"] for b in batteries.chosen(el, later)])
        self.assertEqual(batteries.migrate(pages, self.every), [], "once")

    def test_a_grid_of_other_numbers_is_left_alone(self):
        pages = {"temps": self.page(["sensor.outside_temperature"])}
        self.assertEqual(batteries.migrate(pages, self.every), [])
        self.assertNotIn("batteries", pages["temps"]["elements"][0])

    def test_saved_designs_follow_the_rule_at_render(self):
        import devices
        support.fresh_data_dir()
        dev = devices.primary()
        found = devices.design(dev["design"])
        found["pages"] = {"low": self.page(["sensor.door_battery"])}
        devices._save_design(dev["design"], found)
        with mock.patch.object(batteries, "fetch_every", mock.AsyncMock(return_value=self.every)):
            done = asyncio.run(frames.follow_battery_rules(None))
        self.assertEqual(done, [f"{dev['design']}:low"])
        self.assertEqual(devices.design(dev["design"])["pages"]["low"]["elements"][0]["batteries"], "swap")
        support.use_test_data_dir()


class TestThePageShowsByTheRule(unittest.TestCase):
    def test_the_widgets_gate_answers_for_the_page_and_an_alert(self):
        el = {"type": "dynamic_grid", "batteries": "swap", "except": [], "also": [], "filter_rule": "below", "filter_value": 20}
        page = {"tier": "when", "elements": [el]}
        got = widgets.gate_of(page)
        self.assertIs(got[0], el)
        every = batteries.every_battery(REGISTRY, STATES)
        with mock.patch.object(batteries, "fetch_every", mock.AsyncMock(return_value=every)):
            self.assertTrue(asyncio.run(got[1].check(None, el, "UTC")))
            with mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
                state = {"name": None, "until": 0.0, "fired": {}}
                fired = asyncio.run(frames.check_alerts(None, {"pages": {"low": {**page, "tier": "alert"}}}, state))
        self.assertEqual(fired, "low")
        self.assertIsNone(widgets.gate_of({"elements": [{"type": "dynamic_grid", "items": []}]}), "a grid of states has its own condition")

    def test_the_widget_fetches_its_batteries_not_the_grid_now(self):
        """0.20.2 and 0.21.0 shipped a Batteries page that asked for the power grid (two fetches called
        _grid): it drew the placeholder, never a battery."""
        el = {"type": "dynamic_grid", "batteries": "swap", "except": [], "also": [], "filter_rule": "below",
              "filter_value": 20, "items": []}
        every = batteries.every_battery(REGISTRY, STATES)
        with mock.patch.object(batteries, "fetch_every", mock.AsyncMock(return_value=every)):
            got = asyncio.run(widgets.get("dynamic_grid").fetch(None, el, None))
        self.assertEqual([b["entity"] for b in got], [b["entity"] for b in batteries.chosen(el, every)])
        self.assertTrue(got, "the rule picks some")
        texts, _ = drawn(el, got)
        self.assertNotIn("Sample Zone", texts)
        self.assertIsNot(widgets.get("dynamic_grid").fetch, widgets.get("grid_now").fetch)


@unittest.skipUnless(shutil.which("node"), "no node to run the editor")
class TestTheEditorLeavesItToTheRule(unittest.TestCase):
    def test_a_condition_over_the_old_list_goes_yours_stays(self):
        got = node("""
const el = { type: "dynamic_grid", batteries: "swap", except: [], also: [], filter_rule: "below", filter_value: 20, items: [] };
const old = { tier: "alert", show_if: "{{ (has_value('sensor.a') and states('sensor.a') | float(0) < 20) }}", elements: [el] };
const yours = { tier: "when", show_if: "{{ is_state('person.ada','home') }}", elements: [el] };
C.syncDynamicGridShowIf(old); C.syncDynamicGridShowIf(yours);
console.log(JSON.stringify([old.show_if ?? null, yours.show_if]));""")
        self.assertEqual(got, [None, "{{ is_state('person.ada','home') }}"])
