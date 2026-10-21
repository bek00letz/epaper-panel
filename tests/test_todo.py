"""To-do list pages: what a list shows and in what order, fetching it through
Home Assistant, drawing it, and the editor's preset."""
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import support
import conditions
import entities
import frames
from render import layout, theme as T, todo
from sources import ha_services

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 21, 15, 0, tzinfo=TZ)        # a Wednesday, 15:00


def item(summary, due="", status="needs_action"):
    return {"uid": summary, "summary": summary, "status": status, "due": due}


class TestWhatAListShows(unittest.TestCase):
    def test_due_first_then_the_lists_own_order(self):
        items = [item("Milk"), item("Change the bed", "2026-10-23"), item("Done", "2026-10-20", "completed"),
                 item("Bins out", "2026-10-21"), item("Bread"), item("Call the vet", "2026-10-21T09:00:00+03:00"),
                 item("Water the plants", "2026-10-19"), item("Dentist", "2026-10-21T17:30:00+03:00")]
        self.assertEqual([i["summary"] for i in todo.items_for(items, "open", NOW)],
                         ["Water the plants", "Call the vet", "Dentist", "Bins out", "Change the bed", "Milk", "Bread"],
                         "overdue first; a day's timed items before its all-day ones; undated in list order")

    def test_a_list_without_dates_is_the_list(self):
        names = ["Oat milk", "Coffee", "Lemons"]
        self.assertEqual([i["summary"] for i in todo.items_for([item(n) for n in names], "open", NOW)], names)

    def test_due_shows_only_today_and_overdue(self):
        items = [item("Later", "2026-10-22"), item("Bins out", "2026-10-21"), item("Undated"),
                 item("Old", "2026-10-01"), item("Tonight", "2026-10-21T22:00:00+03:00")]
        self.assertEqual([i["summary"] for i in todo.items_for(items, "due", NOW)], ["Old", "Tonight", "Bins out"])

    def test_due_labels(self):
        cases = {"2026-10-20": ("Overdue", True), "2026-10-21": ("Today", True),
                 "2026-10-21T18:00:00+03:00": ("Today 18:00", True), "2026-10-21T09:00:00+03:00": ("Overdue", True),
                 "2026-10-21T15:30:00Z": ("Today 18:30", True),          # in Home Assistant's zone
                 "2026-10-22": ("Tomorrow", False), "2026-10-24": ("Sat", False), "2026-11-03": ("3 Nov", False),
                 "": ("", False), "soon": ("", False)}
        for due, want in cases.items():
            self.assertEqual(todo.due_label(item("x", due), NOW), want, due)

    def test_how_many_fit(self):
        # The preset's box on the 5.79": five rows of 28 px under the header.
        top = 22 + 9
        self.assertEqual(todo.fit(5, 220 - top, 28)[1:], (5, 0))
        self.assertEqual(todo.fit(7, 220 - top, 28)[1:], (4, 3), "four items, then \"and 3 more\"")
        self.assertEqual(todo.fit(7, 40, 28)[1:], (1, 0), "one row: the header's count says the rest")
        self.assertEqual(todo.fit(0, 40, 28)[1:], (0, 0))


class TestFetching(unittest.IsolatedAsyncioTestCase):
    async def test_asks_home_assistant_for_the_open_items(self):
        calls = []

        async def ha(session, path, method="GET", json=None):
            calls.append((path, method, json))
            if path.startswith("/states/"):
                return {"attributes": {"friendly_name": "Chores"}}
            return {"service_response": {"todo.chores": {"items": [
                {"uid": "1", "summary": " Bins out ", "status": "needs_action", "due": "2026-10-21"},
                {"uid": "2", "summary": "Bread", "status": "needs_action"}]}}}

        with mock.patch.object(ha_services, "ha_json", ha), mock.patch.object(ha_services, "HA_TOKEN", "t"):
            got = await ha_services.fetch_todo_items.direct(None, "todo.chores")
        self.assertEqual(calls[1], ("/services/todo/get_items?return_response=1", "POST",
                                    {"entity_id": "todo.chores", "status": ["needs_action"]}))
        self.assertEqual(got, {"entity": "todo.chores", "name": "Chores", "items": [
            {"uid": "1", "summary": "Bins out", "status": "needs_action", "due": "2026-10-21"},
            {"uid": "2", "summary": "Bread", "status": "needs_action", "due": ""}]})

    async def test_only_to_do_lists_and_a_bad_answer_keeps_the_last_list(self):
        ha = mock.AsyncMock(return_value={"service_response": {}})
        with mock.patch.object(ha_services, "ha_json", ha), mock.patch.object(ha_services, "HA_TOKEN", "t"):
            self.assertIsNone(await ha_services.fetch_todo_items.direct(None, "sensor.battery"))
            self.assertIsNone(await ha_services.fetch_todo_items.direct(None, "todo.x'); drop"))
            ha.assert_not_called()
            with self.assertRaises(ValueError):           # live_data keeps the last good value
                await ha_services.fetch_todo_items.direct(None, "todo.chores")

    async def test_the_page_gets_the_list_and_home_assistants_zone(self):
        data = {"entity": "todo.chores", "name": "Chores", "items": [item("Bins out")]}
        page = {"elements": [{"type": "todo_list", "entity": "todo.chores"}, {"type": "todo_list", "entity": "nope"}]}
        vals = {}
        with mock.patch.object(frames, "fetch_todo_items", mock.AsyncMock(return_value=data)) as fetch, \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="Europe/Bucharest")):
            await frames.enrich_page_values(None, page, vals)
        fetch.assert_awaited_once_with(None, "todo.chores")
        self.assertEqual(vals, {0: {**data, "tz": "Europe/Bucharest"}})


class TestDueCount(unittest.IsolatedAsyncioTestCase):
    """The add-on's count of what's due today or overdue, per list on a page."""

    async def test_one_count_per_list_on_a_page(self):
        spec = {"pages": {
            "a:chores": {"elements": [{"type": "todo_list", "entity": "todo.chores", "show": "due"}]},
            "b:chores_again": {"elements": [{"type": "todo_list", "entity": "todo.chores"}]},
            "a:shop": {"elements": [{"type": "todo_list", "entity": "todo.shopping"}, {"type": "text", "entity": "todo.x"}]},
            "a:bad": {"elements": [{"type": "todo_list", "entity": "sensor.not_a_list"}]}}}
        lists = {"todo.chores": {"name": "Chores", "items": [item("Bins out", "2026-10-21"), item("Old", "2026-10-02"),
                                                             item("Later", "2026-10-30"), item("Bread")]},
                 "todo.shopping": None}                    # not fetched yet

        async def fetch(session, eid):
            return lists[eid]

        published = mock.AsyncMock()
        with mock.patch.object(entities, "fetch_todo_items", fetch), \
             mock.patch.object(entities, "publish_entity", published), \
             mock.patch.object(todo, "now_in", return_value=NOW):
            wanted = await entities.publish_todo_due(None, spec, "Europe/Bucharest")
        self.assertEqual(wanted, {"sensor.epaper_todo_chores_due", "sensor.epaper_todo_shopping_due"},
                         "a list not fetched yet keeps its entity")
        published.assert_awaited_once()
        _, sensor_id, state, attrs = published.await_args.args
        self.assertEqual((sensor_id, state), ("sensor.epaper_todo_chores_due", 2))
        self.assertEqual(attrs["items"], ["Old", "Bins out"])
        self.assertEqual(attrs["friendly_name"], "E-Paper · Chores due")

    def test_a_page_or_alert_can_show_by_it_without_a_broker(self):
        expr = "{{ has_value('sensor.epaper_todo_chores_due') and states('sensor.epaper_todo_chores_due') | float(0) > 0 }}"
        self.assertEqual(conditions.local(expr, {"sensor.epaper_todo_chores_due": {"state": 2}}), "True")
        self.assertEqual(conditions.local(expr, {"sensor.epaper_todo_chores_due": {"state": 0}}), "False")


class TestDrawing(unittest.TestCase):
    BOX = {"type": "todo_list", "entity": "todo.chores", "x": 40, "y": 14, "w": 712, "h": 220}

    def ink(self, data, el=None, region=None):
        img = T.to_1bit(layout.render_page({"elements": [el or self.BOX]}, {0: data}, clock="14:05"))
        if region:
            img = img.crop(region)
        return img.convert("L").histogram()[0]

    def test_draws_the_list_and_designs_its_empty_states(self):
        data = {"entity": "todo.chores", "name": "Chores", "tz": "UTC",
                "items": [item(f"Thing {k}") for k in range(9)]}
        self.assertGreater(self.ink(data, region=(40, 40, 400, 234)), 2000)
        middle = (200, 100, 600, 170)
        self.assertGreater(self.ink({**data, "items": []}, region=middle), 300, "Nothing to do")
        self.assertEqual(self.ink(None, region=middle), 0, "not fetched yet: nothing claims it's empty")
        self.assertGreater(self.ink(None, el={**self.BOX, "entity": ""}, region=middle), 300, "Choose a to-do list")

    def test_reports_its_text_size_for_the_legibility_note(self):
        metrics = []
        layout.render_page({"elements": [self.BOX]}, {0: {"items": [], "tz": "UTC"}}, metrics=metrics)
        self.assertEqual([(m["i"], m["size"]) for m in metrics], [(0, layout.TODO_ITEM_PX)])


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's preset")
class TestPreset(unittest.TestCase):
    def run_js(self, body):
        app = support.APP / "web" / "app"
        script = (f"import {{ PRESETS }} from {json.dumps(str(app / 'legacy.js'))};"
                  f"import * as C from {json.dumps(str(app / 'conditions.js'))};\n{body}")
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_shows_while_the_list_has_something_to_do(self):
        got = self.run_js("""
const p = PRESETS.find((x) => x.id === "to_do");
const show_if = p.showIf("todo.chores");
console.log(JSON.stringify({ asks: p.asks, named: p.namedByEntity, tier: p.tier, show_if, parsed: C.parseShowIf(show_if),
  compiled: C.compileShowIf({ ent: "todo.chores", op: "gt", val: "0" }), els: p.makeElements("todo.chores"), skip: p.showIf("") }));""")
        self.assertEqual((got["asks"], got["tier"]), ("todo", "when"))
        self.assertEqual(got["show_if"], got["compiled"], "written as the simple form writes it")
        self.assertEqual(got["parsed"], {"mode": "simple", "ent": "todo.chores", "op": "gt", "val": "0"})
        self.assertEqual(conditions.guarded(got["show_if"]), got["show_if"])
        self.assertEqual(got["els"][0]["type"], "todo_list")
        self.assertTrue(got["named"], "a page per list, named after it")
        self.assertEqual(got["skip"], "")

    def test_due_shows_by_the_add_ons_count(self):
        got = self.run_js("""
import("%s").then((L) => {
  const el = { type: "todo_list", entity: "todo.chores", show: "due" };
  const page = { tier: "when", show_if: "{{ has_value('todo.chores') and states('todo.chores') | float(0) > 0 }}", elements: [el] };
  C.syncWidgetShowIf(page, el);
  console.log(JSON.stringify([page.show_if, L.getWidgetSensorId(el), L.todoDueSensor("sensor.x")]));
});""" % (support.APP / "web" / "app" / "legacy.js"))
        sensor = todo.due_sensor("todo.chores")
        self.assertEqual(got, ["{{ has_value('%s') and states('%s') | float(0) > 0 }}" % (sensor, sensor), sensor, ""],
                         "the editor names the sensor the add-on publishes")

    def test_new_page_names_it_after_the_list(self):
        src = (support.APP / "web" / "app" / "sheets.js").read_text()
        self.assertIn('p.namedByEntity && ent ? slug(app.entMap.get(ent)?.name', src)

    def test_the_condition_follows_the_list_but_never_replaces_your_own(self):
        got = self.run_js("""
const el = { type: "todo_list", entity: "todo.shopping" };
const ours = { tier: "when", show_if: "{{ has_value('todo.chores') and states('todo.chores') | float(0) > 0 }}", elements: [el] };
const yours = { tier: "when", show_if: "{{ now().hour > 7 }}", elements: [el] };
C.syncWidgetShowIf(ours, el); C.syncWidgetShowIf(yours, el);
console.log(JSON.stringify([ours.show_if, yours.show_if]));""")
        self.assertEqual(got, ["{{ has_value('todo.shopping') and states('todo.shopping') | float(0) > 0 }}", "{{ now().hour > 7 }}"])


if __name__ == "__main__":
    unittest.main()
