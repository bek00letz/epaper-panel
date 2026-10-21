"""Page conditions: the editor's simple form, what the add-on sends Home
Assistant, and the offline stand-in. A sensor with no value never meets
"isn't" or a number comparison."""
import json
import shutil
import subprocess
import unittest
from unittest import mock

import support
import conditions
import fixture
import frames
import runtime

CONDITIONS_JS = support.APP / "web" / "app" / "conditions.js"


def run_js(body):
    """Run `body` with the editor's conditions module as `C`; it prints JSON."""
    script = f"import * as C from {json.dumps(str(CONDITIONS_JS))};\n{body}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class TestGuarded(unittest.TestCase):
    def test_numbers_and_isnt_need_a_value(self):
        self.assertEqual(conditions.guarded("{{ states('sensor.watch_battery') | float(0) < 20 }}"),
                         "{{ has_value('sensor.watch_battery') and states('sensor.watch_battery') | float(0) < 20 }}")
        self.assertEqual(conditions.guarded("{{ not is_state('person.alex','home') }}"),
                         "{{ has_value('person.alex') and not is_state('person.alex','home') }}")

    def test_everything_else_is_left_alone(self):
        for expr in ("{{ is_state('person.alex','home') }}",
                     "{{ has_value('sensor.x') and states('sensor.x') | float(0) < 20 }}",
                     "{{ states('sensor.x') | float(0) < 20 and is_state('y','on') }}",
                     "{{ now().hour > 7 }}", ""):
            self.assertEqual(conditions.guarded(expr), expr.strip())


class TestFixture(unittest.TestCase):
    def setUp(self):
        runtime.PUBLISHED["sensor.test_battery"] = {"state": "unavailable"}

    def tearDown(self):
        runtime.PUBLISHED.pop("sensor.test_battery", None)

    def test_the_guard_and_comparisons_offline(self):
        ev = fixture.eval_fixture_template
        below = "{{ has_value('sensor.test_battery') and states('sensor.test_battery') | float(0) < 20 }}"
        self.assertEqual(ev(below), "False", "unavailable is not below 20")
        runtime.PUBLISHED["sensor.test_battery"] = {"state": "15"}
        self.assertEqual(ev(below), "True")
        self.assertEqual(ev("{{ has_value('sensor.test_battery') and not is_state('sensor.test_battery','15') }}"), "False")
        self.assertEqual(ev("{{ states('sensor.test_battery') | int(0) > 14 }}"), "True")


class TestWhatHomeAssistantIsAsked(unittest.IsolatedAsyncioTestCase):
    OLD = "{{ states('sensor.watch_battery') | float(0) < 20 }}"

    async def test_old_conditions_are_sent_guarded(self):
        sent = []

        async def resolve(session, templates):
            sent.append(dict(templates))
            return {k: "false" for k in templates}

        spec = {"pages": {"low": {"tier": "alert", "show_if": self.OLD},
                          "when": {"tier": "when", "show_if": self.OLD, "elements": []}},
                "rotation": ["when"]}
        with mock.patch.object(frames, "resolve_templates", resolve), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            await frames.check_alerts(None, spec, runtime.new_alert())
            await frames.eligible_pages(None, spec, runtime.linger("test-conditions"))
        guarded = conditions.guarded(self.OLD)
        self.assertEqual(sent[0]["low"], guarded)
        self.assertEqual(sent[1]["when"], guarded)


class TestTheAddonsOwnValues(unittest.IsolatedAsyncioTestCase):
    """Conditions on the add-on's own values are answered from its record, as
    pages read those values, so they work without an MQTT broker."""
    REG = {"sensor.epaper_watch_count": {"state": "2"}, "sensor.epaper_todo_chores_due": {"state": 0},
           "sensor.epaper_quiet_hours": {"state": "unavailable"}}

    def test_answers_the_simple_form(self):
        cases = {
            "{{ states('sensor.epaper_watch_count') | int(0) > 0 }}": "True",
            "{{ has_value('sensor.epaper_todo_chores_due') and states('sensor.epaper_todo_chores_due') | float(0) > 0 }}": "False",
            "{{ is_state('sensor.epaper_watch_count','2') }}": "True",
            "{{ has_value('sensor.epaper_quiet_hours') and not is_state('sensor.epaper_quiet_hours','on') }}": "False",
            "{{ states('sensor.epaper_quiet_hours') | float(0) < 5 }}": "False",
        }
        for expr, want in cases.items():
            self.assertEqual(conditions.local(expr, self.REG), want, expr)

    def test_leaves_everything_else_to_home_assistant(self):
        for expr in ("{{ states('sensor.watch_battery') | float(0) < 20 }}",
                     "{{ has_value('sensor.x') and states('sensor.epaper_watch_count') | int(0) > 0 }}",
                     "{{ states('sensor.epaper_watch_count') | int(0) > 0 and now().hour > 7 }}", ""):
            self.assertIsNone(conditions.local(expr, self.REG), expr)

    async def test_only_the_rest_is_sent(self):
        sent = {}

        async def resolve(session, templates):
            sent.update(templates)
            return {k: "True" for k in templates}

        conds = {"watch": "{{ states('sensor.epaper_watch_count') | int(0) > 0 }}",
                 "low": "{{ has_value('sensor.b') and states('sensor.b') | float(0) < 20 }}"}
        with mock.patch.object(frames, "resolve_templates", resolve), \
             mock.patch.dict(runtime.PUBLISHED, {"sensor.epaper_watch_count": {"state": "0"}}):
            got = await frames.resolve_conditions(None, conds)
        self.assertEqual(sent, {"low": conds["low"]})
        self.assertEqual(got, {"watch": "False", "low": "True"})


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's conditions")
class TestSimpleForm(unittest.TestCase):
    def test_compiles_with_the_guard_and_reads_back(self):
        out = run_js("""
const cases = [["eq", "home"], ["ne", "home"], ["lt", "20"], ["ge", "5"]];
console.log(JSON.stringify(cases.map(([op, val]) => {
  const c = C.compileShowIf({ ent: "sensor.watch_battery", op, val });
  return [c, C.parseShowIf(c)];
})));""")
        (eq, eq_p), (ne, ne_p), (lt, lt_p), (ge, ge_p) = out
        self.assertEqual(eq, "{{ is_state('sensor.watch_battery','home') }}")
        self.assertEqual(ne, "{{ has_value('sensor.watch_battery') and not is_state('sensor.watch_battery','home') }}")
        self.assertEqual(lt, "{{ has_value('sensor.watch_battery') and states('sensor.watch_battery') | float(0) < 20 }}")
        for parsed, op, val in ((eq_p, "eq", "home"), (ne_p, "ne", "home"), (lt_p, "lt", "20"), (ge_p, "ge", "5")):
            self.assertEqual(parsed, {"mode": "simple", "ent": "sensor.watch_battery", "op": op, "val": val})
        # What Python adds to an old condition is what the editor writes now.
        self.assertEqual(conditions.guarded("{{ states('sensor.watch_battery') | float(0) < 20 }}"), lt)

    def test_old_conditions_still_read_and_a_mismatched_guard_is_custom(self):
        out = run_js("""
console.log(JSON.stringify([
  C.parseShowIf("{{ states('sensor.a') | float(0) < 20 }}"),
  C.parseShowIf("{{ has_value('sensor.b') and states('sensor.a') | float(0) < 20 }}").mode,
]));""")
        self.assertEqual(out[0], {"mode": "simple", "ent": "sensor.a", "op": "lt", "val": "20"})
        self.assertEqual(out[1], "raw")

    def test_no_value_is_false_now_in_the_editor(self):
        out = run_js("""
const m = new Map([["sensor.b", { state: "unavailable" }], ["person.a", { state: "unknown" }]]);
console.log(JSON.stringify([
  C.evaluate({ mode: "simple", ent: "sensor.b", op: "lt", val: "20" }, m),
  C.evaluate({ mode: "simple", ent: "person.a", op: "ne", val: "home" }, m),
  C.evaluate({ mode: "simple", ent: "person.a", op: "eq", val: "unknown" }, m),
]));""")
        self.assertEqual(out, [False, False, True])


class TestUntilInTheEditor(unittest.TestCase):
    """The editor has no JavaScript test runner for its DOM, so this pins the
    wiring: what it writes is what layouts_store keeps and frames reads."""

    def test_an_alert_offers_both_ways_to_end(self):
        src = (support.APP / "web" / "app" / "inspector.js").read_text()
        self.assertIn('[["time", "After a time"], ["until", "When something happens"]]', src)
        self.assertIn('key: "until_if"', src)
        self.assertIn("const HOLD = { time: %d, until: %d };" % (conditions.HOLD_DEFAULT, conditions.UNTIL_LIMIT_DEFAULT), src)
        self.assertIn('if (v === "until") p.ends = "until"', src)


if __name__ == "__main__":
    unittest.main()
