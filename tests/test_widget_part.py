"""A page's "Shows" in one place (0.21.1, the user's call, 22 Oct): its widget part ("something on it
to show", from each widget's gate) and its own condition hold together. Before, one or the other
decided: a condition you wrote silently left the widget out, and a widget's own condition left yours
out. The user's case: show for 2 minutes after a presence sensor changes to home, only while a
battery is low."""
import asyncio
import itertools
import json
import shutil
import subprocess
import unittest
from unittest import mock

import support  # noqa: F401
import frames
import widgets

BATTERIES = {"type": "dynamic_grid", "batteries": "swap", "except": [], "also": [], "filter_rule": "below",
             "filter_value": 20, "items": []}
PRESENCE = {"changed": "binary_sensor.bedroom_presence", "minutes": 2, "to": "on"}
OWN = "{{ is_state('person.ada','home') }}"
_runs = itertools.count()


def answers(own: bool, counts: dict | None = None):
    """Home Assistant's answers: the page's own condition, and any widget part it's asked."""
    async def resolve(session, conds, minutes=None):
        out = {}
        for k in conds:
            if "#" in k:
                out[k] = "True" if (counts or {}).get(k) else "False"
            elif not k.endswith(":until"):
                out[k] = "True" if own else "False"
        return out
    return resolve


def run(spec, own, battery_low, counts=None, alert=False):
    check = mock.AsyncMock(return_value=battery_low)
    gate = widgets.get("dynamic_grid").gate
    with mock.patch.object(widgets.get("dynamic_grid"), "gate", gate.__class__(**{**gate.__dict__, "check": check})), \
         mock.patch.object(frames, "resolve_conditions", answers(own, counts)), \
         mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
        if alert:
            return asyncio.run(frames.check_alerts(None, spec, {"name": None, "until": 0.0, "fired": {}}))
        # A fresh linger each time: a page that showed stays a few minutes (that's kept).
        return asyncio.run(frames.eligible_pages(None, spec, frames.runtime.linger(f"widget-part-{next(_runs)}")))


def rotation(page):
    return {"rotation": ["low", "clock"], "pages": {"low": page, "clock": {"tier": "rotate", "elements": []}}}


class TestBothHoldInTheRotation(unittest.TestCase):
    page = {"tier": "when", "show_if": PRESENCE, "elements": [BATTERIES]}

    def test_a_battery_low_and_the_presence_change(self):
        self.assertEqual(run(rotation(self.page), own=True, battery_low=True), ["low", "clock"])

    def test_your_condition_alone_isnt_enough(self):
        """Before 0.21.1 a condition you wrote left the widget out: this page showed with no battery low."""
        self.assertEqual(run(rotation(self.page), own=True, battery_low=False), ["clock"])

    def test_the_widget_alone_isnt_enough(self):
        self.assertEqual(run(rotation(self.page), own=False, battery_low=True), ["clock"])

    def test_switched_off_it_goes_by_yours_alone(self):
        page = {**self.page, "by_widget": False}
        self.assertEqual(run(rotation(page), own=True, battery_low=False), ["low", "clock"])

    def test_a_count_gate_is_asked_of_home_assistant_with_yours(self):
        page = {"tier": "when", "show_if": OWN, "elements": [{"type": "todo_list", "entity": "todo.chores"}]}
        self.assertEqual(run(rotation(page), own=True, battery_low=False), ["clock"], "nothing to do")
        self.assertEqual(run(rotation(page), own=True, battery_low=False, counts={"low#0": True}), ["low", "clock"])

    def test_any_widget_with_something_to_show_is_enough(self):
        page = {"tier": "when", "elements": [{"type": "todo_list", "entity": "todo.chores"}, BATTERIES]}
        self.assertEqual(run(rotation(page), own=True, battery_low=True), ["low", "clock"])
        self.assertEqual(run(rotation(page), own=True, battery_low=False, counts={"low#0": True}), ["low", "clock"])


class TestBothHoldForAnAlert(unittest.TestCase):
    page = {"tier": "alert", "show_if": OWN, "elements": [BATTERIES]}

    def test_it_fires_only_when_both_hold(self):
        spec = {"pages": {"low": self.page}}
        self.assertEqual(run(spec, own=True, battery_low=True, alert=True), "low")
        self.assertIsNone(run(spec, own=True, battery_low=False, alert=True),
                          "before 0.21.1 your condition alone fired it")
        self.assertIsNone(run(spec, own=False, battery_low=True, alert=True))

    def test_with_no_condition_of_its_own_the_widget_fires_it(self):
        self.assertEqual(run({"pages": {"low": {**self.page, "show_if": ""}}}, own=False, battery_low=True, alert=True), "low")


class TestPagesFromBefore(unittest.TestCase):
    def test_what_the_editor_wrote_for_the_widget_goes_yours_stays(self):
        pages = {
            "scores": {"tier": "when", "show_if": "{{ is_state('sensor.epaper_sports_nba','active') }}",
                       "elements": [{"type": "sports_match", "league": "basketball/nba"}]},
            "lights": {"tier": "alert", "show_if": "{{ is_state('light.a','on') or is_state('light.b','on') }}",
                       "elements": [{"type": "dynamic_grid", "items": [{"entity": "light.a"}, {"entity": "light.b"}]}]},
            "chores": {"tier": "when", "show_if": "{{ has_value('todo.chores') and states('todo.chores') | float(0) > 0 }}",
                       "elements": [{"type": "todo_list", "entity": "todo.chores"}]},
            "yours": {"tier": "when", "show_if": OWN, "elements": [{"type": "flight_tracker", "auto_window": True}]},
            "off": {"tier": "when", "by_widget": False, "show_if": "{{ is_state('sensor.epaper_sports_nba','active') }}",
                    "elements": [{"type": "sports_match", "league": "basketball/nba"}]},
            "plain": {"tier": "rotate", "show_if": "{{ is_state('light.a','on') }}",
                      "elements": [{"type": "dynamic_grid", "items": [{"entity": "light.a"}]}]},
        }
        self.assertEqual(sorted(widgets.follow_widget_parts(pages)), ["chores", "lights", "scores"])
        self.assertEqual(pages["yours"]["show_if"], OWN)
        self.assertIn("show_if", pages["off"], "switched off: it's the page's own")
        self.assertIn("show_if", pages["plain"])
        self.assertEqual(widgets.follow_widget_parts(pages), [], "once")

    def test_saved_designs_and_drafts_are_upgraded(self):
        import devices
        support.fresh_data_dir()
        try:
            dev = devices.primary()
            found = devices.design(dev["design"])
            found["pages"] = {"nba": {"tier": "when", "show_if": "{{ is_state('sensor.epaper_sports_nba','active') }}",
                                      "elements": [{"type": "sports_match", "league": "basketball/nba"}]}}
            devices._save_design(dev["design"], found)
            self.assertEqual(frames.follow_widget_parts(), [f"{dev['design']}:nba"])
            self.assertNotIn("show_if", devices.design(dev["design"])["pages"]["nba"])
        finally:
            support.use_test_data_dir()


class TestTheEditorIsTold(unittest.TestCase):
    def test_each_pages_part_is_kept_for_the_page_panel(self):
        answered = {}
        check = mock.AsyncMock(return_value=False)
        gate = widgets.get("dynamic_grid").gate
        page = {"tier": "when", "elements": [BATTERIES]}
        with mock.patch.object(widgets.get("dynamic_grid"), "gate", gate.__class__(**{**gate.__dict__, "check": check})), \
             mock.patch.object(frames, "resolve_conditions", answers(True)), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            asyncio.run(frames.eligible_pages(None, rotation(page), frames.runtime.linger(f"widget-part-{next(_runs)}"),
                                              None, answered))
        self.assertEqual(answered, {"low": False})
        import web
        self.assertIn('"parts": runtime.parts(dev["design"])', open(web.__file__).read())


APP_JS = support.APP / "web" / "app"


def editor(js):
    from test_presets import catalog_json
    script = (f"import * as Cat from {json.dumps((APP_JS / 'catalog.js').as_uri())};"
              f"import * as C from {json.dumps((APP_JS / 'conditions.js').as_uri())};"
              f"Cat.setCatalog({json.dumps(catalog_json())});\n{js}")
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "no node to run the editor")
class TestThePagePanelSaysBoth(unittest.TestCase):
    def test_the_users_case_in_words(self):
        got = editor("""
const ents = new Map([["binary_sensor.bedroom_presence", { name: "Bedroom presence", state: "on", device_class: "presence" }]]);
const el = %s;
const say = (p) => C.showsWords(p, ents);
console.log(JSON.stringify([
  say({ tier: "when", show_if: %s, elements: [el] }),
  say({ tier: "alert", elements: [{ type: "sports_match", league: "basketball/nba" }, { type: "flight_tracker" }] }),
  say({ tier: "when", by_widget: false, show_if: "{{ is_state('binary_sensor.bedroom_presence','on') }}", elements: [el] }),
  say({ tier: "when", elements: [{ type: "dynamic_grid", filter_state: "on", items: [{ entity: "light.a" }] }] }),
  say({ tier: "when", elements: [{ type: "todo_list", entity: "todo.chores", show: "due" }] }),
  say({ tier: "when", elements: [{ ...el, no_answer_hours: "never" }] }),
]));""" % (json.dumps(BATTERIES), json.dumps(PRESENCE)))
        self.assertEqual(got[0], "Only when one of its batteries is low, or hasn't answered for 12 hours, "
                                 "and Bedroom presence changed to Home in the last 2 minutes")
        self.assertEqual(got[1], "As an alert when it's a game day, or a plane is near")
        self.assertEqual(got[2], "Only when Bedroom presence is Home", "switched off: yours alone")
        self.assertEqual(got[3], "Only when one of them is on")
        self.assertEqual(got[4], "Only when something on its list is due")
        self.assertEqual(got[5], "Only when one of its batteries is low")

    def test_a_widget_with_nothing_to_wait_for_has_no_part(self):
        got = editor("""console.log(JSON.stringify([C.partEls({ elements: [{ type: "todo_list", entity: "" },
  { type: "dynamic_grid", filter_state: "*", items: [{ entity: "light.a" }] }, { type: "weather_forecast" }] }).length,
  C.partOn({ elements: [{ type: "notifications" }] }), C.partOn({ by_widget: false, elements: [{ type: "notifications" }] })]));""")
        self.assertEqual(got, [0, True, False])

    def test_the_panel_has_the_switch_and_the_widget_points_to_it(self):
        src = (APP_JS / "inspector.js").read_text()
        self.assertIn('toggleRow("Something on it to show"', src)
        self.assertIn('field("And when", conditionRows(app, p)', src)
        self.assertIn("when.append(...showsRows(app, p))", src)
        self.assertIn("const WINDOW_TOGGLES = false;", src)
        self.assertIn('else if (f.kind === "window" && !WINDOW_TOGGLES) s.append(showsPointer(app));', src)
        # The way back is kept, switched off.
        self.assertIn('"Hide the page when nothing shows"', src)
        self.assertIn("export const WIDGET_WRITES_CONDITION = false;", (APP_JS / "legacy.js").read_text())


if __name__ == "__main__":
    unittest.main()
