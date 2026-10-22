"""How a widget's page shows "only when" comes from its descriptor (review 2 #4): one Gate, read by
the render cycle, the editor and the add-on's sensors, never a list of types or sensor names."""
import asyncio
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401
import frames
import widgets
from test_presets import APP_JS, catalog_json


class TestTheRenderCycleReadsTheGate(unittest.TestCase):
    def gated(self, page):
        return [el["type"] for el, _ in widgets.widget_part(page)]

    def test_every_gated_widget_has_its_part_whatever_the_page_says(self):
        match = {"type": "sports_match", "league": "soccer/eng.1"}
        self.assertEqual(self.gated({"elements": [match]}), ["sports_match"])
        self.assertEqual(self.gated({"elements": [match], "show_if": "{{ is_state('person.ada','home') }}"}), ["sports_match"])
        self.assertEqual(self.gated({"elements": [match], "by_widget": False}), [], "switched off")

    def test_what_the_editor_wrote_for_it_is_its_part_yours_stays(self):
        page = lambda el, s: {"tier": "when", "elements": [el], "show_if": s}
        self.assertTrue(widgets.wrote_for_widget(page({"type": "sports_match", "league": "soccer/eng.1"},
                                                      "{{ is_state('sensor.epaper_sports_premier_league','active') }}")))
        # What 0.9 pages say still counts as the widget's own.
        self.assertTrue(widgets.wrote_for_widget(page({"type": "sports_racing"}, "{{ is_state('sensor.f1_status','active') }}")))
        self.assertTrue(widgets.wrote_for_widget(page({"type": "flight_tracker"}, "{{ states('sensor.overhead_aircraft_count') | int > 0 }}")))
        self.assertFalse(widgets.wrote_for_widget(page({"type": "sports_match"}, "{{ is_state('person.ada','home') }}")))

    def test_a_count_gate_is_a_condition_home_assistant_answers(self):
        el = {"type": "todo_list", "entity": "todo.chores", "show": "due"}
        _, g = widgets.widget_part({"elements": [el]})[0]
        self.assertFalse(g.checks(el))
        self.assertEqual(g.asks(el), "{{ has_value('sensor.epaper_todo_chores_due') and states('sensor.epaper_todo_chores_due') | float(0) > 0 }}")
        self.assertEqual(self.gated({"elements": [{"type": "todo_list", "entity": ""}]}), [], "no list: nothing to wait for")

    def test_eligible_pages_ask_the_widgets_gate(self):
        asked = []

        async def window(session, el, tz):
            asked.append(el["type"])
            return False
        spec = {"rotation": ["scores", "plain"], "pages": {
            "scores": {"tier": "when", "elements": [{"type": "sports_match", "league": "basketball/nba"}]},
            "plain": {"tier": "rotate", "elements": []}}}
        gate = widgets.get("sports_match").gate
        with mock.patch.object(widgets.get("sports_match"), "gate", gate.__class__(**{**gate.__dict__, "check": window})), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            live = asyncio.run(frames.eligible_pages(None, spec, frames.runtime.linger("d")))
        self.assertEqual(asked, ["sports_match"])
        self.assertEqual(live, ["plain"])

    def test_no_list_of_types_or_sensor_names_is_left(self):
        src = Path(frames.__file__).read_text()
        for gone in ("builtin_patterns", "_is_builtin_widget_gate", "sensor.f1_status", '"flight_tracker"'):
            self.assertNotIn(gone, src)
        js = (APP_JS / "conditions.js").read_text()
        self.assertNotIn("BUILTIN_MARKERS", js)
        self.assertNotIn("flight_tracker", js)

    def test_the_catalog_carries_each_gate(self):
        cat = widgets.catalog()
        self.assertEqual(cat["sports_match"]["gate"]["sensor_of"], "league")
        self.assertEqual(cat["flight_tracker"]["gate"]["rule"], "count")
        self.assertTrue(cat["sports_racing"]["gate"]["checked"])
        self.assertIn("sensor.formula_e_status", cat["sports_racing"]["gate"]["markers"])
        self.assertNotIn("gate", cat["weather_forecast"])


def run_js(body):
    script = (f"import * as Cat from {json.dumps(str(APP_JS / 'catalog.js'))};"
              f"import * as C from {json.dumps(str(APP_JS / 'conditions.js'))};"
              f"import * as L from {json.dumps(str(APP_JS / 'legacy.js'))};"
              f"Cat.setCatalog({json.dumps(catalog_json())});\n{body}")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "no node to run the editor")
class TestTheEditorReadsTheGate(unittest.TestCase):
    def test_each_widgets_part_is_the_switch_not_a_written_condition(self):
        """Since 0.21.1 (the user's call): the editor writes nothing for a widget, and what it wrote before goes."""
        got = run_js("""
const pages = [{ type: "sports_match", league: "basketball/nba" }, { type: "sports_racing", series: "nascar_cup" },
  { type: "flight_tracker" }, { type: "notifications" }, { type: "todo_list", entity: "todo.chores", show: "due" }]
  .map((el) => {
    const p = { tier: "when", elements: [el] }; C.syncWidgetShowIf(p);
    const before = { tier: "when", show_if: L.gateShowIf(el), elements: [el] }; C.syncWidgetShowIf(before);
    return [L.getWidgetSensorId(el), p.show_if ?? null, before.show_if ?? null, C.partEls(p).length];
  });
console.log(JSON.stringify(pages));""")
        self.assertEqual(got[0], ["sensor.epaper_sports_nba", None, None, 1])
        self.assertEqual(got[1][0], "sensor.epaper_racing_nascar", "an alias finds its series")
        self.assertEqual([g[1:] for g in got], [[None, None, 1]] * 5)

    def test_a_condition_you_wrote_stays(self):
        got = run_js("""
const p = { tier: "when", show_if: "{{ is_state('person.ada','home') }}", elements: [{ type: "sports_match", league: "soccer/eng.1" }] };
C.syncWidgetShowIf(p); console.log(JSON.stringify(p.show_if));""")
        self.assertEqual(got, "{{ is_state('person.ada','home') }}")


if __name__ == "__main__":
    unittest.main()
