"""Where a text or value gets what it shows ("From" in the inspector: Text, Sensor, Time,
Template; web/app/shows.js under node), and a binding written out as a template
(binding.as_template, POST /api/as_template). Every choice is reachable from every other."""
import json
import subprocess
import unittest

import support
from render import binding
from test_editor_api import EditorClient

SHOWS = support.APP / "web" / "app" / "shows.js"
INSPECTOR = (support.APP / "web" / "app" / "inspector.js").read_text()
SINCE = "since {{ as_timestamp(states.sensor.pawpaw_location.last_changed) | timestamp_custom('%H:%M') }}"
FROM = ("text", "sensor", "clock", "template")


def run_js(body):
    script = f"import * as S from {json.dumps(str(SHOWS))};\n{body}"
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)


class TestFrom(unittest.TestCase):
    def test_every_choice_from_every_other(self):
        starts = {"text": {"type": "text", "value": "Hello"}, "sensor": {"type": "text", "entity": "sensor.pawpaw_location"},
                  "clock": {"type": "text", "show": "now", "format": "time"}, "template": {"type": "text", "value": SINCE}}
        got = run_js(f"""
const starts = {json.dumps(starts)}, out = {{}};
for (const [a, el0] of Object.entries(starts)) for (const b of {json.dumps(FROM)}) {{
  const el = structuredClone(el0); S.switchSource(el, b, {{ template: "{{{{ 1 }}}}" }}); out[a + ">" + b] = S.sourceOf(el);
  if (S.sourceOf(el0) !== a) out[a] = "starts as " + S.sourceOf(el0);
}}
console.log(JSON.stringify(out));""")
        for a in FROM:
            self.assertNotIn(a, got, got.get(a))
            for b in FROM:
                self.assertEqual(got[f"{a}>{b}"], b, f"{a} to {b}")

    def test_a_template_to_sensor_takes_the_sensor_it_reads(self):
        got = run_js(f"""
const one = {{ type: "text", value: {json.dumps(SINCE)} }}; const a = S.switchSource(one, "sensor", {{ known: new Map([["sensor.pawpaw_location", {{}}]]) }});
const two = {{ type: "text", value: "{{{{ states('sensor.a') }}}} {{{{ is_state(\\"sensor.b\\", 'on') }}}}" }}; const b = S.switchSource(two, "sensor", {{}});
const none = {{ type: "text", value: "{{{{ now() }}}}" }}; const c = S.switchSource(none, "sensor", {{}});
console.log(JSON.stringify({{ a, one, b, two, c, none }}));""")
        self.assertEqual((got["a"], got["one"]), ("", {"type": "text", "entity": "sensor.pawpaw_location"}))
        self.assertEqual((got["b"], got["two"]["entity"]), ("pick", ""), "two sensors: ask which")
        self.assertEqual((got["c"], got["none"]["entity"]), ("pick", ""), "none: ask")

    def test_the_sensor_it_reads_over_the_one_it_had(self):
        got = run_js(f"""
const el = {{ type: "text", entity: "sensor.cat_location", value: {json.dumps(SINCE)} }}; S.switchSource(el, "sensor", {{}});
const kept = {{ type: "text", entity: "sensor.cat_location", value: "{{{{ now() }}}}" }}; const k = S.switchSource(kept, "sensor", {{}});
console.log(JSON.stringify([el.entity, kept.entity, k]));""")
        self.assertEqual(got, ["sensor.pawpaw_location", "sensor.cat_location", ""])

    def test_the_sensors_a_template_reads(self):
        got = run_js("""console.log(JSON.stringify([
  S.templateEntities("{{ states('sensor.a') }} {{ states.binary_sensor.door.state }} {{ states['light.x'] }} {{ '%d.%m' }} {{ 'pic.png' }}"),
  S.templateEntities("{{ 'pic.png' }} {{ states('sensor.a') }}", new Set(["sensor.a"]))]));""")
        self.assertEqual(sorted(got[0]), ["binary_sensor.door", "light.x", "pic.png", "sensor.a"])
        self.assertEqual(got[1], ["sensor.a"], "only ones that exist, when the list is known")

    def test_plain_text_wins_as_on_the_panel(self):
        got = run_js("""console.log(JSON.stringify([S.sourceOf({ type: "text", entity: "sensor.a", value: "Hi" }),
  S.sourceOf({ type: "number", value: 42 }), S.sourceOf({ type: "number" }), S.sourceOf({ type: "text", entity: "" })]));""")
        self.assertEqual(got, ["text", "text", "sensor", "sensor"])

    def test_the_inspector_asks_the_add_on_and_opens_the_picker(self):
        fn = INSPECTOR[INSPECTOR.index("function shows(app, el, set)"):INSPECTOR.index('  if (source === "clock") {')]
        self.assertIn('api("api/as_template"', fn)
        self.assertIn("switchSource(el, v, { known: app.entMap, template })", fn)
        self.assertIn('querySelector(".shows-sensor")?.click()', fn)
        self.assertNotIn("delete el.value", fn, "the switching is shows.js's")


class TestAsTemplate(unittest.TestCase):
    def test_a_sensor_shows_the_same_as_a_template(self):
        el = {"type": "text", "entity": "sensor.pawpaw_location", "show": "last_changed", "format": "relative", "prefix": "since ", "replace": {"x": "y"}}
        got = binding.as_template(el)
        self.assertTrue(got.startswith("since {{ "), got)
        self.assertIn(binding.template_for(el, readable=True)[3:-3], got)

    def test_before_and_after_with_braces_stay_words(self):
        got = binding.as_template({"type": "text", "entity": "sensor.a", "suffix": " {%"})
        self.assertEqual(got, "{{ states('sensor.a') }}{{ ' {%' }}")

    def test_a_number_keeps_its_before_and_after_on_the_element(self):
        self.assertEqual(binding.as_template({"type": "number", "entity": "sensor.a", "suffix": " W"}), "{{ states('sensor.a') }}")

    def test_the_clock_text_and_a_total_today(self):
        self.assertIn("now().strftime", binding.as_template({"type": "text", "show": "now", "format": "time"}))
        self.assertEqual(binding.as_template({"type": "text", "value": "It's Ana's"}), "{{ 'It\\'s Ana\\'s' }}")
        self.assertEqual(binding.as_template({"type": "number", "entity": "sensor.solar", "show": "change_today"}), "{{ states('sensor.solar') }}")
        self.assertEqual(binding.as_template({"type": "text", "value": SINCE}), SINCE, "a template stays itself")
        self.assertEqual(binding.as_template({"type": "text"}), "")


class TestTheRoute(EditorClient):
    async def test_as_template(self):
        r = await self.ed.post("/api/as_template", json={"element": {"type": "text", "entity": "sensor.a"}})
        self.assertEqual((await r.json())["template"], "{{ states('sensor.a') }}")
        self.assertEqual((await self.ed.post("/api/as_template", json={"element": "x"})).status, 400)


if __name__ == "__main__":
    unittest.main()


UI = support.APP / "web" / "app" / "ui.js"
CSS = (support.APP / "web" / "editor.css").read_text()


class TestNothingCutOff(unittest.TestCase):
    """A segmented control beside its label goes under it when its choices don't fit there
    (the user's call, 21 Oct): "Template" read "emplat" in the 320 px inspector."""

    def fits(self, widths, room):
        script = (f"globalThis.navigator ??= {{ platform: '' }}; const U = await import({json.dumps(UI.as_uri())});"
                  f"console.log(JSON.stringify(U.segFits({json.dumps(widths)}, {room})));")
        return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_the_widest_choice_decides_beside_the_label(self):
        # Text, Sensor, Time, Template at 12.5 px semibold, beside a 92 px label in the inspector.
        self.assertFalse(self.fits([28, 42, 30, 50], 141))
        self.assertTrue(self.fits([28, 42, 30, 50], 258))
        self.assertTrue(self.fits([30, 45], 141), "Bold | Regular stays beside")

    def test_every_segmented_control_asks_for_its_choices(self):
        # Since the row rule (test_rows): its need, set when it's made, decides where the row puts it.
        src = UI.read_text()
        seg = src[src.index("export function seg("):]
        self.assertIn('c.style.setProperty("--need", segNeed(', seg)
        self.assertIn("if (SEG_LIVE) { fitting?.observe(c); return c; }", seg, "the live measuring kept as the way back")
        self.assertIn("const SEG_LIVE = false;", src)
