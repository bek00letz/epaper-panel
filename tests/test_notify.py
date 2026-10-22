"""Phone notifications for a page (notify.py): one sensor made only on request,
following its alert or "Only when" page, withdrawn when nothing wants or uses it."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest import mock

import support
import devices
import frames
import layouts_store
import mqtt_bridge
import notify
import runtime
from hass import HassError
from render.linger import Linger

NID, NID2 = "bins4u2", "door7x9"


class FakeHass:
    """Home Assistant as notify.py sees it: the registry, search/related, states,
    automations' configs and blueprints."""

    def __init__(self):
        self.registry = []
        self.related = {}              # entity_id -> {"automation": [...]}
        self.states = {}
        self.automations = {}          # config id -> config
        self.blueprints = {}           # path -> yaml
        self.calls = []
        self.down = False

    async def ws(self, payload, timeout=10):
        self.calls.append(("ws", payload["type"]))
        if self.down:
            raise HassError("not connected to Home Assistant")
        t = payload["type"]
        if t == "config/entity_registry/list":
            return list(self.registry)
        if t == "search/related":
            return self.related.get(payload["item_id"], {})
        if t == "blueprint/list":
            return {p: {"metadata": {}} for p in self.blueprints}
        if t == "blueprint/save":
            self.blueprints[payload["path"]] = payload["yaml"]
            return {"overrides_existing": False}
        raise AssertionError(payload)

    async def rest(self, method, path, json=None, timeout=15):
        self.calls.append((method, path))
        if self.down:
            raise HassError("not connected to Home Assistant")
        if method == "GET" and path.startswith("/states/"):
            eid = path[len("/states/"):]
            if eid not in self.states:
                raise HassError("Entity not found", 404)
            return self.states[eid]
        if path.startswith("/config/automation/config/"):
            cid = path.rsplit("/", 1)[1]
            if method == "GET":
                if cid not in self.automations:
                    raise HassError("Resource not found", 404)
                return self.automations[cid]
            if method == "POST":
                self.automations[cid] = json
                eid = "automation." + json["alias"].lower().replace(" ", "_")
                self.states[eid] = {"state": "on", "attributes": {"id": cid, "friendly_name": json["alias"]}}
                alert = json["use_blueprint"]["input"]["alert"]
                self.related.setdefault(alert, {}).setdefault("automation", []).append(eid)
                return {"result": "ok"}
            if method == "DELETE":
                self.automations.pop(cid)
                for found in self.related.values():
                    found["automation"] = [a for a in found.get("automation", [])
                                           if self.states.get(a, {}).get("attributes", {}).get("id") != cid]
                return {"result": "ok"}
        if method == "DELETE" and path.startswith("/states/"):
            raise HassError("Entity not found", 404)
        raise AssertionError((method, path))

    def use(self, entity_id, automation_id="1700000000000", ours=True, name="Notify iPhone about Bins out"):
        """An automation in Home Assistant that uses `entity_id`."""
        eid = "automation.notify_" + automation_id
        self.states[eid] = {"state": "on", "attributes": {"id": automation_id, "friendly_name": name}}
        self.automations[automation_id] = ({"use_blueprint": {"path": notify.BLUEPRINT_PATH,
                                                               "input": {"alert": entity_id, "notify": ["notify.iphone"]}}}
                                           if ours else {"triggers": [], "actions": []})
        self.related.setdefault(entity_id, {}).setdefault("automation", []).append(eid)


class FakeTransport:
    connected = True

    def __init__(self):
        self.messages, self.log = {}, []

    async def publish(self, topic, payload, retain=True):
        self.messages[topic] = payload
        self.log.append((topic, payload))
        return True

    async def subscribe(self, topic):
        pass


def run(coro):
    return asyncio.run(coro)


PAGES = {
    "bins_out": {"tier": "alert", "show_if": "{{ bins }}", "hold_minutes": 10, "notify": NID, "elements": []},
    "doorbell": {"tier": "when", "show_if": "{{ door }}", "notify": NID2, "elements": []},
    "dryer_done": {"tier": "alert", "show_if": "{{ dryer }}", "hold_minutes": 10, "elements": []},
    "clock": {"tier": "rotate", "elements": []},
}


class NotifyCase(unittest.TestCase):
    def setUp(self):
        support.fresh_data_dir()
        notify.PENDING.clear()
        notify._USAGE.clear()
        notify._SINCE.clear()
        runtime.SHOWING.clear()
        self.now = [1000.0]
        self.hass = FakeHass()
        self.t = FakeTransport()
        self.pub = mqtt_bridge.EntityPublisher(self.t, self.hass, support.temp_dir(), "0.20.0",
                                               clock=lambda: self.now[0])
        self.pub._ready = True
        self._was, runtime.PUBLISHER = runtime.PUBLISHER, self.pub
        self.dev = devices.primary()
        self.design = self.dev["design"]
        self.save(PAGES)

    def tearDown(self):
        runtime.PUBLISHER = self._was

    def save(self, pages, rotation=("doorbell", "clock")):
        devices.save_view(layouts_store.sanitize_layouts({"pages": pages, "rotation": list(rotation)}), self.dev["id"])

    def publish(self):
        run(notify.publish(self.hass))
        run(self.pub.sync())

    def config(self, nid):
        raw = self.t.messages.get(f"homeassistant/binary_sensor/epaper_panel/epaper_page_{nid}/config")
        return json.loads(raw) if raw else raw

    def state(self, nid):
        return self.t.messages.get(f"epaper_panel/epaper_page_{nid}/state")


class TestOnDemand(NotifyCase):
    def test_only_pages_that_ask_get_a_sensor(self):
        self.publish()
        made = sorted(o for o in self.pub.desired if o.startswith(mqtt_bridge.SIGNAL_PREFIX))
        self.assertEqual(made, sorted([f"epaper_page_{NID}", f"epaper_page_{NID2}"]),
                         "the alert without notify and the always page get nothing")
        cfg = self.config(NID)
        self.assertEqual(cfg["unique_id"], f"epaper_studio_epaper_page_{NID}")
        self.assertEqual(cfg["default_entity_id"], "binary_sensor.epaper_alert_bins_out")
        self.assertEqual(cfg["name"], "Bins out alert")
        self.assertNotIn("entity_category", cfg, "something to automate on, not a diagnostic")
        self.assertEqual(self.config(NID2)["default_entity_id"], "binary_sensor.epaper_showing_doorbell")
        self.assertEqual(self.config(NID2)["name"], "Doorbell showing")
        self.assertEqual(self.state(NID), "OFF")
        attrs = json.loads(self.t.messages[f"epaper_panel/epaper_page_{NID}/attributes"])
        self.assertEqual(attrs["page"], "Bins out")
        self.assertNotIn("default_entity_id", attrs)

    def test_a_page_asking_in_an_unsent_draft_has_its_sensor_already(self):
        pages = {**PAGES, "dryer_done": {**PAGES["dryer_done"], "notify": "dry3r00"}}
        layouts_store.save_draft({"version": 1, "spec": layouts_store.sanitize_layouts(
            {"pages": pages, "rotation": ["doorbell"]})}, self.dev["id"])
        self.assertIn("dry3r00", notify.requested())
        self.assertFalse(notify.requested()["dry3r00"]["sent"])
        self.assertIn("epaper_page_dry3r00", notify.kept())

    def test_renaming_the_page_keeps_its_unique_id(self):
        self.publish()
        pages = {k: v for k, v in PAGES.items() if k != "bins_out"}
        pages["bins_day"] = PAGES["bins_out"]
        self.save(pages)
        self.publish()
        cfg = self.config(NID)
        self.assertEqual(cfg["unique_id"], f"epaper_studio_epaper_page_{NID}")
        self.assertEqual(cfg["name"], "Bins day alert")

    def test_saving_keeps_a_notify_id_and_drops_anything_else(self):
        clean = layouts_store.sanitize_layouts({"pages": {
            "a": {"tier": "alert", "show_if": "x", "notify": NID},
            "b": {"tier": "when", "show_if": "x", "notify": "../../etc"},
            "c": {"tier": "when", "show_if": "x", "notify": 7}}})
        self.assertEqual(clean["pages"]["a"]["notify"], NID)
        self.assertNotIn("notify", clean["pages"]["b"])
        self.assertNotIn("notify", clean["pages"]["c"])


class TestFollowsThePage(NotifyCase):
    def test_on_while_the_alert_holds(self):
        runtime.alert(self.design)["active"] = {"bins_out": {"until": 9e9, "at": 1000.0}}
        self.publish()
        self.assertEqual(self.state(NID), "ON")
        attrs = json.loads(self.t.messages[f"epaper_panel/epaper_page_{NID}/attributes"])
        self.assertTrue(attrs["fired_at"])
        runtime.alert(self.design)["active"] = {}
        self.publish()
        self.assertEqual(self.state(NID), "OFF")

    def test_firing_again_while_on_turns_it_off_and_on(self):
        """A change alert held by the last change fires again at the next (the doorbell twice):
        "turns on" is the one thing an automation needs to watch."""
        runtime.alert(self.design)["active"] = {"bins_out": {"until": 9e9, "at": 1000.0}}
        self.publish()
        n = len(self.t.log)
        runtime.alert(self.design)["active"] = {"bins_out": {"until": 9e9, "at": 1300.0}}
        self.publish()
        states = [p for topic, p in self.t.log[n:] if topic == f"epaper_panel/epaper_page_{NID}/state"]
        self.assertEqual(states, ["OFF", "ON"])
        n = len(self.t.log)
        self.publish()
        self.assertEqual([p for topic, p in self.t.log[n:] if topic.endswith("/state")], [], "no change, nothing sent")

    def test_on_while_an_only_when_page_shows(self):
        runtime.showing(self.design).add("doorbell")
        self.publish()
        self.assertEqual(self.state(NID2), "ON")
        runtime.showing(self.design).clear()
        self.publish()
        self.assertEqual(self.state(NID2), "OFF")

    def test_a_draft_page_is_off_until_it_is_sent(self):
        layouts_store.save_draft({"version": 1, "spec": layouts_store.sanitize_layouts({"pages": {
            "new_one": {"tier": "when", "show_if": "x", "notify": "new0000"}}, "rotation": ["new_one"]})},
            self.dev["id"])
        runtime.showing(self.design).add("new_one")
        self.publish()
        self.assertEqual(self.state("new0000"), "OFF")


class TestWithdrawal(NotifyCase):
    def setUp(self):
        super().setUp()
        self.publish()
        self.eid = "binary_sensor.epaper_alert_bins_out"
        self.hass.registry.append({"entity_id": self.eid, "platform": "mqtt",
                                   "unique_id": f"epaper_studio_epaper_page_{NID}"})

    def remove_the_page(self):
        self.save({k: v for k, v in PAGES.items() if k != "bins_out"})

    def test_withdrawn_at_once_when_nothing_uses_it(self):
        self.remove_the_page()
        self.publish()
        self.assertEqual(self.t.messages[f"homeassistant/binary_sensor/epaper_panel/epaper_page_{NID}/config"], "")
        self.assertNotIn(f"epaper_page_{NID}", self.pub.desired)
        self.assertEqual(self.config(NID2)["unique_id"], f"epaper_studio_epaper_page_{NID2}", "the other one stays")

    def test_kept_while_an_automation_uses_it(self):
        self.hass.use(self.eid)
        self.remove_the_page()
        self.publish()
        self.assertTrue(self.config(NID), "not withdrawn")
        self.assertEqual(self.state(NID), "OFF")
        self.assertTrue(self.pub.desired[f"epaper_page_{NID}"]["attrs"]["page_removed"])
        self.assertIn(f"epaper_page_{NID}", notify.kept())
        self.now[0] += mqtt_bridge.STALE_AFTER * 3
        self.pub.keep(notify.kept())
        self.publish()
        self.assertTrue(self.config(NID), "still there hours later: kept, not stale")

    def test_kept_when_home_assistant_cant_say(self):
        self.hass.down = True
        self.remove_the_page()
        self.publish()
        self.assertTrue(self.config(NID))

    def test_withdrawn_once_the_automation_is_gone(self):
        self.hass.use(self.eid)
        self.remove_the_page()
        self.publish()
        self.hass.related.clear()
        notify._USAGE.clear()                           # asked again after a while
        self.publish()
        self.assertEqual(self.t.messages[f"homeassistant/binary_sensor/epaper_panel/epaper_page_{NID}/config"], "")


class TestAlertState(unittest.IsolatedAsyncioTestCase):
    """What frames keeps for notify.py: every alert that holds, and the "Only when" pages whose condition holds."""

    async def test_each_alert_stays_active_for_its_own_hold(self):
        spec = {"pages": {"a": {"tier": "alert", "show_if": "{{ a }}", "hold_minutes": 10},
                          "b": {"tier": "alert", "show_if": "{{ b }}", "hold_minutes": 10}}}
        state = runtime.new_alert()

        async def check(a, b, at):
            with mock.patch.object(frames, "resolve_templates",
                                   mock.AsyncMock(return_value={"a": str(a), "b": str(b)})), \
                 mock.patch.object(frames.time, "time", return_value=at):
                return await frames.check_alerts(None, spec, state)

        self.assertEqual(await check(True, False, 1000), "a")
        self.assertEqual(await check(True, True, 1060), "b", "b takes the screen")
        self.assertEqual(set(state["active"]), {"a", "b"}, "a still holds: its notification isn't over")
        await check(False, True, 1120)
        self.assertEqual(set(state["active"]), {"b"}, "a let go when it turned false")
        await check(False, True, 1060 + 601)
        self.assertEqual(state["active"], {}, "b past its hold")

    async def test_showing_is_the_pages_whose_condition_holds_never_the_fallback(self):
        spec = {"rotation": ["door", "bins"], "pages": {
            "door": {"tier": "when", "show_if": "{{ door }}"}, "bins": {"tier": "when", "show_if": "{{ bins }}"}}}
        shown = set()
        with mock.patch.object(frames, "resolve_templates",
                               mock.AsyncMock(return_value={"door": "False", "bins": "False"})), \
             mock.patch.object(frames, "get_home_timezone", mock.AsyncMock(return_value="UTC")):
            live = await frames.eligible_pages(None, spec, Linger(), shown)
        self.assertEqual(live, ["door"], "the panel still shows something")
        self.assertEqual(shown, set(), "but the door page's condition doesn't hold")


if __name__ == "__main__":
    unittest.main()
