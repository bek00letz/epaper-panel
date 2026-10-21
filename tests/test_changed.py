"""A "changed" condition: a page shows for N minutes after a sensor takes a new
value, and an alert fires at each change. A restart, or a sensor dropping out
and coming back with the same value, isn't a change."""
import json
import unittest
from unittest import mock

import support
import conditions
import frames
import runtime
from sources import changes

CAT = "sensor.pawpaw_location"
ANY = "{{ has_value('sensor.pawpaw_location') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}"
OUT = "{{ is_state('sensor.pawpaw_location','Outdoor Cat') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}"
NOW = 1_800_000_000.0


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class TestTheCondition(unittest.TestCase):
    def test_reads_the_simple_forms(self):
        self.assertEqual(conditions.changed(ANY), conditions.Changed(CAT, None, 30))
        self.assertEqual(conditions.changed(OUT), conditions.Changed(CAT, "Outdoor Cat", 30))

    def test_anything_else_isnt_one(self):
        for expr in ("{{ is_state('sensor.pawpaw_location','Outdoor Cat') }}",
                     "{{ has_value('sensor.other') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) }}",
                     "{{ has_value('sensor.pawpaw_location') and now() - states['sensor.pawpaw_location'].last_changed < timedelta(minutes=30) and x }}",
                     "", None):
            self.assertIsNone(conditions.changed(expr), expr)

    def test_other_conditions_are_untouched(self):
        self.assertEqual(conditions.guarded(ANY), ANY)
        self.assertIsNone(conditions.local(ANY, {CAT: {"state": "Outdoor Cat"}}))

    def test_holds_for_its_minutes_after_the_change(self):
        c = conditions.changed(OUT)
        seen = {"state": "Outdoor Cat", "at": NOW - 29 * 60}
        self.assertTrue(conditions.changed_holds(c, seen, NOW))
        self.assertFalse(conditions.changed_holds(c, seen, NOW + 61), "gone after 30 minutes")
        self.assertTrue(conditions.changed_holds(c, seen, NOW + 61, minutes=60), "a window it's given wins")

    def test_to_a_value_and_no_value(self):
        c = conditions.changed(OUT)
        self.assertFalse(conditions.changed_holds(c, {"state": "Indoor Cat", "at": NOW - 60}, NOW))
        self.assertFalse(conditions.changed_holds(conditions.changed(ANY), {"state": "unavailable", "at": NOW - 60}, NOW))
        self.assertFalse(conditions.changed_holds(c, {"state": "Outdoor Cat", "at": None}, NOW), "no change")
        self.assertFalse(conditions.changed_holds(c, None, NOW), "nothing read yet")


class TestWhatCountsAsAChange(unittest.TestCase):
    def rows(self, *pairs):
        return [{"state": s, "last_changed": iso(t)} for s, t in pairs]

    def test_a_new_value(self):
        rows = self.rows(("Indoor Cat", NOW - 1800), ("Outdoor Cat", NOW - 600))
        self.assertEqual(changes.last_real_change(rows, NOW - 1800), (NOW - 600, "Outdoor Cat"))

    def test_a_restart_isnt_one(self):
        # Home Assistant writes the same value again as it starts.
        rows = self.rows(("Outdoor Cat", NOW - 1800), ("Outdoor Cat", NOW - 600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))

    def test_dropping_out_and_back_isnt_one(self):
        rows = self.rows(("Outdoor Cat", NOW - 1800), ("unavailable", NOW - 700), ("unknown", NOW - 650), ("Outdoor Cat", NOW - 600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))

    def test_coming_back_with_another_value_is_one(self):
        rows = self.rows(("Indoor Cat", NOW - 1800), ("unavailable", NOW - 700), ("Outdoor Cat", NOW - 600))
        self.assertEqual(changes.last_real_change(rows, NOW - 1800), (NOW - 600, "Outdoor Cat"))

    def test_only_inside_the_window(self):
        rows = self.rows(("Indoor Cat", NOW - 7200), ("Outdoor Cat", NOW - 3600))
        self.assertIsNone(changes.last_real_change(rows, NOW - 1800))


class TestAskingHomeAssistant(unittest.IsolatedAsyncioTestCase):
    async def change(self, state, changed, history=(), before=()):
        asked = []

        async def template(session, tpl):
            return json.dumps({"state": state, "changed": changed})

        async def history_api(session, path):
            asked.append(path)
            return [list(before if len(asked) > 1 else history)]
        with mock.patch.object(changes, "HA_TOKEN", "token"), \
             mock.patch.object(changes, "ha_template", template), \
             mock.patch.object(changes, "ha_json", history_api):
            got = await changes.change(None, CAT, 30, now=NOW)
        return got, asked

    async def test_reads_no_history_when_nothing_happened(self):
        got, asked = await self.change("Outdoor Cat", NOW - 3 * 3600)
        self.assertIsNone(got["at"])
        self.assertEqual(asked, [], "its last_changed is older than the window")

    async def test_home_assistant_restarting(self):
        # last_changed moved as it restarted 5 minutes ago; history shows the same value.
        got, asked = await self.change("Outdoor Cat", NOW - 300,
                                       [{"state": "Outdoor Cat", "last_changed": iso(NOW - 1800)},
                                        {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}])
        self.assertIsNone(got["at"])
        self.assertEqual(len(asked), 1)
        self.assertIn("filter_entity_id=sensor.pawpaw_location", asked[0])

    async def test_a_real_change(self):
        got, _ = await self.change("Outdoor Cat", NOW - 300,
                                   [{"state": "Indoor Cat", "last_changed": iso(NOW - 1800)},
                                    {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}])
        self.assertEqual((got["at"], got["to"], got["history"]), (NOW - 300, "Outdoor Cat", True))

    async def test_the_window_starts_while_it_has_no_value(self):
        # Unavailable since before the window; what it was before that decides.
        window = [{"state": "unavailable", "last_changed": iso(NOW - 1800)},
                  {"state": "Outdoor Cat", "last_changed": iso(NOW - 300)}]
        got, asked = await self.change("Outdoor Cat", NOW - 300, window,
                                       [{"state": "Outdoor Cat", "last_changed": iso(NOW - 9000)}] + window)
        self.assertEqual(len(asked), 2)
        self.assertIsNone(got["at"], "back with the value it had")

    async def test_a_sensor_the_recorder_leaves_out(self):
        got, _ = await self.change("Outdoor Cat", NOW - 300, [])
        self.assertEqual((got["at"], got["history"]), (NOW - 300, False))

    async def test_no_value_now(self):
        got, asked = await self.change("unavailable", NOW - 60)
        self.assertIsNone(got["at"])
        self.assertEqual(asked, [])


class TestPages(unittest.IsolatedAsyncioTestCase):
    """Only when: the page joins the rotation for 30 minutes after a change."""

    async def live(self, seen, at):
        spec = {"pages": {"home": {"elements": []}, "cat": {"tier": "when", "show_if": OUT, "elements": []}},
                "rotation": ["home", "cat"]}
        fetch = mock.AsyncMock(return_value=seen)
        with mock.patch.object(changes, "fetch_change", fetch), \
             mock.patch.object(frames.time, "time", return_value=at), \
             mock.patch.object(frames, "resolve_templates", mock.AsyncMock(return_value={})), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            live = await frames.eligible_pages(None, spec, runtime.linger("test-changed"))
        fetch.assert_awaited_with(None, CAT, 30)
        return live

    async def test_shows_after_a_change_then_leaves(self):
        seen = {"state": "Outdoor Cat", "at": NOW, "to": "Outdoor Cat"}
        self.assertEqual(await self.live(seen, NOW + 60), ["home", "cat"])
        self.assertEqual(await self.live(seen, NOW + 1801), ["home"])

    async def test_not_after_a_restart(self):
        self.assertEqual(await self.live({"state": "Outdoor Cat", "at": None}, NOW), ["home"])


class TestAlerts(unittest.IsolatedAsyncioTestCase):
    """As an alert: fires at each change and holds for its own minutes."""

    def setUp(self):
        self.state = runtime.new_alert()
        self.spec = {"pages": {"cat": {"tier": "alert", "show_if": ANY, "hold_minutes": 10}}}
        self.windows = []

    async def check(self, seen, at):
        async def fetch(session, entity, minutes):
            self.windows.append(minutes)
            return seen
        with mock.patch.object(changes, "fetch_change", fetch), \
             mock.patch.object(frames.time, "time", return_value=at):
            return await frames.check_alerts(None, self.spec, self.state)

    async def test_fires_on_a_change_and_holds_for_its_minutes(self):
        out = {"state": "Outdoor Cat", "at": NOW}
        self.assertEqual(await self.check(out, NOW + 30), "cat")
        self.assertEqual(set(self.windows), {10}, "its window is the alert's hold, not the 30 written")
        self.assertEqual(await self.check(out, NOW + 300), "cat")
        self.assertIsNone(await self.check(out, NOW + 601), "given back after 10 minutes")
        self.assertIsNone(await self.check(out, NOW + 900))

    async def test_each_change_fires_again(self):
        await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 30)
        self.assertIsNone(await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 700))
        back = {"state": "Indoor Cat", "at": NOW + 760}
        self.assertEqual(await self.check(back, NOW + 790), "cat", "back in: a new alert")
        self.assertGreater(self.state["until"], NOW + 790 + 590)

    async def test_a_change_while_it_holds_starts_it_again(self):
        await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 30)
        await self.check({"state": "Indoor Cat", "at": NOW + 300}, NOW + 330)
        self.assertEqual(self.state["until"], NOW + 330 + 600)

    async def test_a_restart_doesnt_fire(self):
        self.assertIsNone(await self.check({"state": "Outdoor Cat", "at": None}, NOW))

    async def test_until_uses_its_limit(self):
        self.spec["pages"]["cat"].update(ends="until", until_if="{{ home }}", hold_minutes=120)
        with mock.patch.object(frames, "resolve_templates", mock.AsyncMock(return_value={"cat:until": "False"})):
            self.assertEqual(await self.check({"state": "Outdoor Cat", "at": NOW}, NOW + 3600), "cat")
        self.assertEqual(set(self.windows), {120})


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- the editor
import subprocess  # noqa: E402

CONDITIONS_JS = support.APP / "web" / "app" / "conditions.js"
INSPECTOR_JS = (support.APP / "web" / "app" / "inspector.js").read_text()


def run_js(body):
    script = f"import * as C from {json.dumps(str(CONDITIONS_JS))};\n{body}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class TestTheEditorsForm(unittest.TestCase):
    def test_writes_what_the_add_on_reads(self):
        got = run_js("""console.log(JSON.stringify([
          C.compileShowIf({ent: 'sensor.pawpaw_location', op: 'changed', val: '', minutes: 30}),
          C.compileShowIf({ent: 'sensor.pawpaw_location', op: 'changed', val: 'Outdoor Cat', minutes: 30}),
          C.compileShowIf({ent: 'sensor.pawpaw_location', op: 'changed', val: ''}),
          C.compileShowIf({ent: 'sensor.pawpaw_location', op: 'changed', val: '', minutes: 99999}),
        ]))""")
        self.assertEqual(got[:3], [ANY, OUT, ANY])
        self.assertEqual(conditions.changed(got[3]).minutes, 1440)

    def test_reads_it_back(self):
        got = run_js(f"console.log(JSON.stringify([C.parseShowIf({json.dumps(ANY)}), C.parseShowIf({json.dumps(OUT)})]))")
        self.assertEqual(got[0], {"mode": "simple", "ent": CAT, "op": "changed", "val": "", "minutes": 30})
        self.assertEqual(got[1]["val"], "Outdoor Cat")

    def test_every_other_comparison_is_as_it_was(self):
        got = run_js("""const out = [];
          for (const [op, val] of [['eq','on'],['ne','on'],['gt','5'],['lt','5'],['ge','5'],['le','5']]) {
            const s = C.compileShowIf({ent: 'sensor.x', op, val}); out.push([s, C.parseShowIf(s)]); }
          console.log(JSON.stringify(out))""")
        self.assertEqual([s for s, _ in got], [
            "{{ is_state('sensor.x','on') }}", "{{ has_value('sensor.x') and not is_state('sensor.x','on') }}",
            "{{ has_value('sensor.x') and states('sensor.x') | float(0) > 5 }}", "{{ has_value('sensor.x') and states('sensor.x') | float(0) < 5 }}",
            "{{ has_value('sensor.x') and states('sensor.x') | float(0) >= 5 }}", "{{ has_value('sensor.x') and states('sensor.x') | float(0) <= 5 }}"])
        self.assertTrue(all("minutes" not in p and p["mode"] == "simple" for _, p in got))
        for s, _ in got:
            self.assertIsNone(conditions.changed(s), s)

    def test_only_the_add_on_can_say_if_it_holds(self):
        got = run_js(f"console.log(JSON.stringify(C.evaluate(C.parseShowIf({json.dumps(OUT)}), new Map([['{CAT}', {{state: 'Outdoor Cat'}}]]))))")
        self.assertIsNone(got, "Home Assistant's last_changed alone would count a restart")

    def line(self, expr, got, **opts):
        return run_js(f"console.log(JSON.stringify(C.changedLine(C.parseShowIf({json.dumps(expr)}), {json.dumps(got)}, {json.dumps(opts)})))")

    def test_the_status_line(self):
        out = {"state": "Outdoor Cat", "at": NOW - 18 * 60, "to": "Outdoor Cat", "history": True, "now": NOW}
        self.assertEqual(self.line(OUT, out), {"holds": True, "note": "",
                         "text": "Changed to Outdoor Cat 18 min ago, so it shows for 12 more minutes."})
        self.assertEqual(self.line(OUT, {**out, "at": NOW - 29 * 60 - 30})["text"],
                         "Changed to Outdoor Cat 29 min ago, so it shows for 1 more minute.")
        self.assertEqual(self.line(OUT, {**out, "at": None})["text"], "Hidden now: no change to Outdoor Cat in the last 30 minutes.")
        self.assertEqual(self.line(ANY, {**out, "at": None})["text"], "Hidden now: no change in the last 30 minutes.")
        indoor = {**out, "state": "Indoor Cat", "to": "Indoor Cat", "at": NOW - 300}
        self.assertEqual(self.line(OUT, indoor)["text"], "Hidden now: it changed to Indoor Cat 5 min ago.")
        self.assertFalse(self.line(ANY, {**out, "state": "unavailable"})["holds"])

    def test_as_an_alert(self):
        out = {"state": "Outdoor Cat", "at": NOW - 4 * 60, "to": "Outdoor Cat", "history": True, "now": NOW}
        self.assertEqual(self.line(ANY, out, minutes=10, alert="time")["text"],
                         "Changed to Outdoor Cat 4 min ago, so it shows for 6 more minutes.")
        self.assertEqual(self.line(ANY, out, minutes=120, alert="until")["text"],
                         "Changed to Outdoor Cat 4 min ago, so it's showing until something happens.")
        self.assertEqual(self.line(OUT, {**out, "at": None}, minutes=10, alert="time")["text"], "Waiting for a change to Outdoor Cat.")

    def test_says_when_there_is_no_history(self):
        got = self.line(ANY, {"state": "Outdoor Cat", "at": NOW - 60, "to": "Outdoor Cat", "history": False, "now": NOW})
        self.assertIn("restarts count as changes", got["note"])

    def test_in_words(self):
        got = run_js(f"console.log(JSON.stringify(C.describe({json.dumps(OUT)}, new Map([['{CAT}', {{name: 'Pawpaw Location'}}]]))))")
        self.assertEqual(got["text"], "Shows for 30 minutes after Pawpaw Location changes to Outdoor Cat")


class TestTheInspector(unittest.TestCase):
    """Wiring, pinned in the source (the editor has no test runner)."""

    def test_offered_for_when_it_shows_not_for_until(self):
        self.assertIn('select(c === SHOW ? OPS : OPS.filter(([k]) => k !== "changed")', INSPECTOR_JS)
        self.assertIn('(c !== SHOW && parsed.op === "changed")', INSPECTOR_JS, "a hand-written one stays as written")

    def test_a_page_says_how_long_an_alert_uses_its_hold(self):
        self.assertIn('field("Shows for"', INSPECTOR_JS)
        self.assertIn('const minutes = alert ? (p.hold_minutes || HOLD[alert])', INSPECTOR_JS)

    def test_the_status_line_comes_from_the_add_on(self):
        self.assertIn('api("api/changed?entity="', INSPECTOR_JS)
        self.assertIn("changedLine(parsed, got, { minutes, alert })", INSPECTOR_JS)


class TestTheEndpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        import web
        support.fresh_data_dir()
        _, editor = web.make_apps()
        self.ed = TestClient(TestServer(editor))
        await self.ed.start_server()

    async def asyncTearDown(self):
        await self.ed.close()
        support.use_test_data_dir()

    async def test_answers_with_the_add_ons_clock(self):
        seen = {"state": "Outdoor Cat", "at": NOW, "to": "Outdoor Cat", "history": True}
        fetch = mock.AsyncMock(return_value=seen)
        with mock.patch.object(changes, "fetch_change", fetch):
            r = await self.ed.get(f"/api/changed?entity={CAT}&minutes=45")
            body = await r.json()
        self.assertEqual(r.status, 200)
        self.assertEqual({k: body[k] for k in seen}, seen)
        self.assertIn("now", body)
        self.assertEqual(fetch.await_args.args[1:], (CAT, 45))

    async def test_refuses_what_isnt_an_entity(self):
        r = await self.ed.get("/api/changed?entity=../states")
        self.assertEqual(r.status, 400)

    async def test_says_when_home_assistant_didnt_answer(self):
        with mock.patch.object(changes, "fetch_change", mock.AsyncMock(return_value=None)):
            r = await self.ed.get(f"/api/changed?entity={CAT}")
        self.assertEqual(r.status, 502)
