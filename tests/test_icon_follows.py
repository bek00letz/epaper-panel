"""An icon that follows a sensor ("Changes with a sensor" in the inspector): the states it
offers, each with Home Assistant's own icon (render/states.offered, sources/states_seen,
GET /api/entity_states), and the inspector's wiring (web/app/follows.js under node)."""
import asyncio
import json
import re
import subprocess
import unittest
from unittest import mock

import support  # noqa: F401
from render import states
from sources import states_seen
from test_editor_api import EditorClient

CAT = "sensor.pawpaw_location"
NOW = 1_800_000_000.0


class TestWhatAnEntityOffers(unittest.TestCase):
    def test_a_door_has_home_assistants_words_and_icons(self):
        got = states.offered("binary_sensor.front_door", "door", seen=[("off", "")])
        self.assertEqual(got, [{"state": "on", "word": "Open", "icon": "mdi:door-open"},
                               {"state": "off", "word": "Closed", "icon": "mdi:door-closed"}])

    def test_a_template_sensor_its_states_with_the_icon_each_had(self):
        # PawPaw's location: a template sensor whose icon changes with its state, newest first.
        seen = [("Outdoor Cat", "mdi:cat-outline"), ("Outdoor Cat", "mdi:cat-outline"), ("Indoor Cat", "mdi:cat"),
                ("unavailable", ""), ("outdoor cat", "mdi:cat-outline")]
        self.assertEqual(states.offered(CAT, seen=seen), [{"state": "Outdoor Cat", "word": "Outdoor Cat", "icon": "mdi:cat-outline"},
                                                          {"state": "Indoor Cat", "word": "Indoor Cat", "icon": "mdi:cat"}])

    def test_never_an_icon_the_panel_cant_draw(self):
        # Home Assistant gives Outdoor Cat mdi:cat-outline, which isn't in the panel's icon font:
        # offered without an icon (the editor gives it the icon's own), never one drawn as nothing.
        from render import layout
        self.assertFalse(layout.can_draw_icon("mdi:cat-outline"))
        self.assertTrue(layout.can_draw_icon("mdi:cat") and layout.can_draw_icon("custom:cat-sitting"))
        self.assertFalse(layout.can_draw_icon("custom:nope"))
        seen = [("Outdoor Cat", "mdi:cat-outline"), ("Indoor Cat", "mdi:cat")]
        got = states.offered(CAT, seen=seen, drawable=layout.can_draw_icon)
        self.assertEqual([(g["state"], g["icon"]) for g in got], [("Outdoor Cat", ""), ("Indoor Cat", "mdi:cat")],
                         "its icon changes with its state, so Indoor Cat's isn't Outdoor Cat's")
        door = states.offered("binary_sensor.d", "door", seen=[("on", "mdi:not-an-icon")], drawable=lambda ic: ic == "mdi:door-closed")
        self.assertEqual({g["state"]: g["icon"] for g in door}, {"on": "", "off": "mdi:door-closed"})

    def test_a_select_its_options_first(self):
        got = states.offered("input_select.mode", options=["Home", "Away", "Night"], seen=[("Night", "mdi:list-box")])
        self.assertEqual([g["state"] for g in got], ["Home", "Away", "Night"])
        self.assertEqual({g["icon"] for g in got}, {"mdi:list-box"}, "one icon it always has, for every state")

    def test_an_icon_template_wins_over_the_kinds(self):
        seen = [("on", "mdi:cat"), ("off", "mdi:cat-outline")]
        got = {g["state"]: g["icon"] for g in states.offered("binary_sensor.cat_inside", "occupancy", seen=seen)}
        self.assertEqual(got, {"on": "mdi:cat", "off": "mdi:cat-outline"})

    def test_an_unchanging_icon_doesnt_hide_the_kinds(self):
        got = {g["state"]: g["icon"] for g in states.offered("binary_sensor.flap", "door", seen=[("on", "mdi:cat"), ("off", "mdi:cat")])}
        self.assertEqual(got, {"on": "mdi:door-open", "off": "mdi:door-closed"})

    def test_no_value_is_never_a_state_and_a_long_list_stops(self):
        self.assertEqual(states.offered("sensor.x", seen=[("unknown", ""), ("", ""), (None, "")]), [])
        many = states.offered("sensor.x", seen=[(str(n), "") for n in range(100)])
        self.assertEqual(len(many), states.MOST)


class TestReadingThemFromHomeAssistant(unittest.IsolatedAsyncioTestCase):
    def ha(self, attrs, history):
        async def ha_json(session, path, **kw):
            if path.startswith("/states/"):
                return {"state": "Outdoor Cat", "attributes": attrs}
            self.assertIn("filter_entity_id=sensor.pawpaw_location", path)
            self.assertNotIn("no_attributes", path, "the icon each state had is an attribute")
            return [history]
        return ha_json

    async def test_the_recorders_last_days(self):
        rows = [{"state": "Indoor Cat", "attributes": {"icon": "mdi:cat"}}, {"state": "Outdoor Cat", "attributes": {"icon": "mdi:paw"}}]
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", self.ha({"icon": "mdi:paw"}, rows)):
            got = await states_seen.fetch(None, CAT, now=NOW)
        self.assertEqual([(g["state"], g["icon"]) for g in got], [("Outdoor Cat", "mdi:paw"), ("Indoor Cat", "mdi:cat")])

    async def test_only_icons_the_panel_draws(self):
        rows = [{"state": "Indoor Cat", "attributes": {"icon": "mdi:cat"}}]
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", self.ha({"icon": "mdi:cat-outline"}, rows)):
            got = await states_seen.fetch(None, CAT, now=NOW)
        self.assertEqual([(g["state"], g["icon"]) for g in got], [("Outdoor Cat", ""), ("Indoor Cat", "mdi:cat")])

    async def test_a_measurement_has_no_states(self):
        ha = mock.AsyncMock(return_value={"state": "21.2", "attributes": {"unit_of_measurement": "°C", "state_class": "measurement"}})
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", ha):
            self.assertEqual(await states_seen.fetch(None, "sensor.indoor_temperature"), [])
        self.assertEqual(ha.await_count, 1, "its history isn't read")

    async def test_no_recorder_still_offers_the_rest(self):
        async def ha_json(session, path, **kw):
            if path.startswith("/states/"):
                return {"state": "off", "attributes": {"device_class": "door"}}
            raise ConnectionError("no recorder")
        with mock.patch.object(states_seen, "HA_TOKEN", "t"), mock.patch.object(states_seen, "ha_json", ha_json):
            got = await states_seen.fetch(None, "binary_sensor.front_door")
        self.assertEqual([g["state"] for g in got], ["on", "off"])


class TestTheRoute(EditorClient):
    async def test_states_of_an_entity(self):
        got = await (await self.ed.get("/api/entity_states?entity=binary_sensor.front_door")).json()
        self.assertEqual([s["word"] for s in got["states"]], ["Open", "Closed"])
        got = await (await self.ed.get("/api/entity_states?entity=sensor.cat_location")).json()
        self.assertEqual([s["state"] for s in got["states"]], ["Outdoor Cat"])

    async def test_not_an_entity(self):
        r = await self.ed.get("/api/entity_states?entity=nope")
        self.assertEqual(r.status, 400)
        self.assertIn("entity ID", (await r.json())["error"])

    async def test_home_assistant_not_answering(self):
        with mock.patch.object(states_seen, "fetch", mock.AsyncMock(side_effect=asyncio.TimeoutError())):
            r = await self.ed.get("/api/entity_states?entity=sensor.cat_location")
        self.assertEqual(r.status, 502)
        self.assertIn("didn't say", (await r.json())["error"])


FOLLOWS = support.APP / "web" / "app" / "follows.js"
INSPECTOR = (support.APP / "web" / "app" / "inspector.js").read_text()


def run_js(body):
    script = f"import * as F from {json.dumps(str(FOLLOWS))};\n{body}"
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)


class TestTheEditorsSide(unittest.TestCase):
    def test_on_and_off_keep_the_plain_icon(self):
        got = run_js("""
const el = { type: "icon", icon: "mdi:cat" };
const before = F.isFollowing(el);
F.startFollowing(el); F.setEntity(el, "sensor.pawpaw_location");
F.addState(el, "Outdoor Cat", "mdi:cat-outline");
const on = JSON.parse(JSON.stringify(el));
F.stopFollowing(el);
console.log(JSON.stringify({ before, on, off: el, text: F.isFollowing({ type: "text", state_icons: {} }) }));""")
        self.assertFalse(got["before"])
        self.assertEqual(got["on"], {"type": "icon", "icon": "mdi:cat", "entity": "sensor.pawpaw_location",
                                     "state_icons": {"Outdoor Cat": {"icon": "mdi:cat-outline", "look": "plain"}}})
        self.assertEqual(got["off"], {"type": "icon", "icon": "mdi:cat"}, "off: the plain icon, nothing else")
        self.assertFalse(got["text"], "only an icon follows")

    def test_the_cat_in_a_few_clicks(self):
        # Pick the sensor, tap its two suggested states: each comes with Home Assistant's icon.
        offered = [{"state": "Outdoor Cat", "word": "Outdoor Cat", "icon": "mdi:cat-outline"}, {"state": "Indoor Cat", "word": "Indoor Cat", "icon": "mdi:cat"}]
        got = run_js(f"""
const offered = {json.dumps(offered)};
const el = {{ type: "icon", icon: "mdi:help" }};
F.startFollowing(el); F.setEntity(el, "sensor.pawpaw_location");
const first = F.suggestions(el, offered);
for (const o of first) F.addState(el, o.state, o.icon);
console.log(JSON.stringify({{ first, after: F.suggestions(el, offered), map: el.state_icons }}));""")
        self.assertEqual([(o["word"], o["icon"]) for o in got["first"]], [("Outdoor Cat", "mdi:cat-outline"), ("Indoor Cat", "mdi:cat")])
        self.assertEqual(got["after"], [], "an added state isn't offered again")
        self.assertEqual(got["map"], {"Outdoor Cat": {"icon": "mdi:cat-outline", "look": "plain"}, "Indoor Cat": {"icon": "mdi:cat", "look": "plain"}})

    def test_a_state_is_one_row_whatever_its_case(self):
        got = run_js("""
const el = { type: "icon", icon: "mdi:cat" }; F.startFollowing(el);
const a = F.addState(el, "Outdoor Cat", "mdi:cat-outline"), b = F.addState(el, " outdoor cat ", "mdi:x"), c = F.addState(el, "  ");
F.setStateIcon(el, "OUTDOOR CAT", "mdi:cat-off"); const typed = F.addState(el, "Away");
const offer = F.suggestions(el, [{ state: "outdoor CAT", icon: "mdi:y" }, { state: "Home" }]);
F.removeState(el, "away");
console.log(JSON.stringify({ a, b, c, typed, offer, map: el.state_icons }));""")
        self.assertEqual((got["a"], got["b"], got["c"], got["typed"]), ("Outdoor Cat", "", "", "Away"))
        self.assertEqual(got["map"], {"Outdoor Cat": {"icon": "mdi:cat-off", "look": "plain"}})
        self.assertEqual(got["offer"], [{"state": "Home", "word": "Home", "icon": "mdi:cat"}], "no icon known: its own")

    def test_another_sensor_clears_the_states_of_the_one_before(self):
        got = run_js("""
const el = { type: "icon", icon: "mdi:cat" }; F.startFollowing(el);
const none = F.setEntity(el, "sensor.a"); F.addState(el, "x"); F.addState(el, "y");
const same = F.setEntity(el, "sensor.a"), other = F.setEntity(el, "sensor.b");
console.log(JSON.stringify({ none, same, other, map: el.state_icons, entity: el.entity }));""")
        self.assertEqual((got["none"], got["same"], got["other"]), (0, 0, 2))
        self.assertEqual((got["map"], got["entity"]), ({}, "sensor.b"))

    def test_each_state_has_its_own_look(self):
        got = run_js("""
const el = { type: "icon", icon: "mdi:cat", pill: true, state_icons: { on: "mdi:door-open" } };
const old = F.lookOf(el, "ON");                                   // just an icon: the icon's Style
F.addState(el, "Outdoor Cat", "mdi:paw");                          // a new row starts with the Style
F.setStateLook(el, "outdoor cat", "invert"); F.setStateIcon(el, "Outdoor Cat", "mdi:cat");
F.setStateLook(el, "on", "plain"); F.setStateLook(el, "on", "sparkly");
const framedPlain = F.framed({ type: "icon", state_icons: { a: { icon: "x", look: "plain" } } });
const framedRow = F.framed({ type: "icon", state_icons: { a: { icon: "x", look: "invert" } } });
F.setStyle(el, "invert"); const own = [F.styleOf(el), el.pill];
console.log(JSON.stringify({ old, map: el.state_icons, framedPlain, framedRow, own, after: F.lookOf(el, "Outdoor Cat") }));""")
        self.assertEqual(got["old"], "pill")
        self.assertEqual(got["map"], {"on": {"icon": "mdi:door-open", "look": "plain"}, "Outdoor Cat": {"icon": "mdi:cat", "look": "invert"}},
                         "its look kept when its icon changes; a look that isn't one is ignored")
        self.assertEqual((got["framedPlain"], got["framedRow"]), (False, True), "Corners show when anything has a shape")
        self.assertEqual(got["own"], ["invert", None])
        self.assertEqual(got["after"], "invert", "the icon's Style is Anything else's, not the rows'")

    def test_the_look_is_chosen_in_the_icon_picker(self):
        pickers = (support.APP / "web" / "app" / "pickers.js").read_text()
        self.assertIn('h("span", { class: "lab", text: "Look" })', pickers)
        self.assertIn("seg(LOOKS, look.value", pickers)
        rows = INSPECTOR[INSPECTOR.index("function iconRows"):INSPECTOR.index("function addStates")]
        self.assertIn("setStateLook(el, st, l)", rows)
        self.assertIn('"Icon for anything else", own)', rows, "Anything else's look is the icon's Style")
        style = INSPECTOR[INSPECTOR.index("function styleRows"):INSPECTOR.index("function element(")]
        self.assertIn("isFollowing(el) ? []", style, "no second Style control while it follows")

    def test_a_row_says_home_assistants_word(self):
        got = run_js("""
const kind = { on: { word: "Open" }, off: { word: "Closed" } };
console.log(JSON.stringify([F.wordFor("on", null, kind), F.wordFor("off", [{ state: "off", word: "Shut" }], kind), F.wordFor("Outdoor Cat", null, null)]));""")
        self.assertEqual(got, ["Open", "Shut", "Outdoor Cat"])

    def test_the_inspector_wiring(self):
        rows = INSPECTOR[INSPECTOR.index("function iconRows"):INSPECTOR.index("function addStates")]
        self.assertIn('toggleRow("Changes with a sensor"', rows)
        self.assertLess(rows.index("const sw = toggleRow"), rows.index("iconButton(app, el.icon"), "the switch first, so it never moves")
        self.assertIn('if (!on) return [sw, iconButton(app, el.icon', rows, "off: the plain icon right under the switch")
        self.assertIn('row("Anything else"', rows, "on: its own icon is the last row")
        self.assertEqual(rows.count("iconButton(app, el.icon"), 2, "one control for its own icon in each case, never two")
        self.assertIn("api/entity_states?entity=", INSPECTOR, "the states come from the add-on")
        self.assertIn('section("Icon", ...iconRows(app, el, set)', INSPECTOR)
        self.assertNotRegex(rows, r"KNOWN_STATES", "no editor copy of the states")
        self.assertIn('label: "Undo"', rows, "removing a row has an Undo")


if __name__ == "__main__":
    unittest.main()
