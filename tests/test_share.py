"""Sharing pages as a file (share.py writes and opens it; the editor's app/share.js fills it in).

What these pin: nothing of the sender's home is in the file (entity IDs, their names, the Wi-Fi,
places, data sources, keys, notifications); a page of every kind of element comes back the same
in another home, with that home's sensors; and a file this version can't show is refused with
the reason, never opened as a broken page."""
import copy
import json
import re
import shutil
import subprocess
import unittest

import support

import share
import widgets
from layouts_store import sanitize_layouts

SHARE_JS = support.APP / "web" / "app" / "share.js"

# The sender's home: what must never leave it.
SENDER = [
    {"entity_id": "sensor.annas_bedroom_temperature", "name": "Anna's bedroom temperature", "unit": "°C", "device_class": "temperature"},
    {"entity_id": "binary_sensor.annas_window", "name": "Anna's window", "device_class": "window"},
    {"entity_id": "calendar.smith_family", "name": "Smith family"},
    {"entity_id": "todo.smith_groceries", "name": "Smith groceries"},
    {"entity_id": "weather.elm_street", "name": "Elm Street"},
    {"entity_id": "media_player.annas_speaker", "name": "Anna's speaker"},
    {"entity_id": "media_player.kitchen_sonos_17", "name": "Kitchen Sonos"},
    {"entity_id": "person.anna_smith", "name": "Anna Smith"},
    {"entity_id": "sensor.smith_grid_power", "name": "Smith grid power", "unit": "W", "device_class": "power"},
    {"entity_id": "sensor.anna_phone_battery", "name": "Anna's phone battery", "unit": "%", "device_class": "battery"},
    {"entity_id": "sensor.epaper_smithflix", "name": "E-Paper · smithflix", "is_epaper": True},
    {"entity_id": "sensor.epaper_smithflix_count", "name": "E-Paper · smithflix count", "is_epaper": True},
    {"entity_id": "sensor.epaper_sports_eng_1", "name": "E-Paper · Premier League", "is_epaper": True},
]
SOURCES = [{"name": "smithflix", "type": "jellyfin", "base": "http://10.0.0.17:8096", "key": "0123456789abcdef0123456789abcdef", "user": "Anna"}]
SSID, PASSWORD = "Smith-Home-5G", "correct horse battery"
PLACE = {"lat": 44.4268, "lon": 26.1025, "location_name": "Grandma's"}
SECRETS = [e["entity_id"] for e in SENDER if not e.get("is_epaper")] + ["smithflix", "10.0.0.17", SOURCES[0]["key"],
           SSID, PASSWORD, "44.4268", "26.1025", "Grandma", "notifyme1", "anna_phone"]
NAMES = [e["name"] for e in SENDER if not e.get("is_epaper")]

ENTITY_FOR = {"sensor": "sensor.annas_bedroom_temperature", "binary_sensor": "binary_sensor.annas_window",
              "calendar": "calendar.smith_family", "todo": "todo.smith_groceries", "weather": "weather.elm_street",
              "media_player": "media_player.annas_speaker", "person": "person.anna_smith"}
# Where an element's own sensor goes when its descriptor doesn't say (the widget's basic `entity`).
DEFAULT_ENTITY = {"todo_list": "todo.smith_groceries", "calendar_month": "calendar.smith_family",
                  "calendar_agenda": "calendar.smith_family", "tv_week": "calendar.smith_family",
                  "weather_forecast": "weather.elm_street", "grid_now": "sensor.smith_grid_power",
                  "now_playing": "media_player.annas_speaker, media_player.kitchen_sonos_17"}


def every_element():
    """One element of every kind the add-on draws, each using the sender's home wherever it can."""
    els = []
    for t, w in widgets.WIDGETS.items():
        el = {"id": "w_" + t, "type": t, "x": 10, "y": 10, "w": 300, "h": 120, **copy.deepcopy(w.defaults)}
        for f in w.fields:
            if f.get("kind") == "entity":
                el[f["key"]] = ENTITY_FOR.get((f.get("domains") or ["sensor"])[0], "sensor.annas_bedroom_temperature")
        el["entity"] = DEFAULT_ENTITY.get(t, el.get("entity") or "sensor.annas_bedroom_temperature")
        if t == "flight_tracker":
            el.update(PLACE)
        if t in ("sports_match", "sports_racing", "flight_tracker"):
            el["data"] = {"source": "smithflix"}
        if t == "sports_match":
            el["entity"] = "sensor.epaper_sports_eng_1"
        els.append(el)
    els += [
        {"id": "n", "type": "number", "entity": "sensor.annas_bedroom_temperature", "unit": "entity", "x": 0, "y": 0, "w": 100, "h": 50},
        {"id": "t", "type": "text", "value": "{{ states('sensor.annas_bedroom_temperature') }} in Anna's room", "size": 20, "x": 0, "y": 60, "w": 200, "h": 30},
        {"id": "s", "type": "text", "entity": "binary_sensor.annas_window", "show": "last_changed", "prefix": "since ", "x": 0, "y": 90, "w": 200, "h": 30},
        {"id": "i", "type": "icon", "icon": "mdi:account", "entity": "person.anna_smith", "state_icons": {"home": "mdi:home", "not_home": "mdi:car"}, "x": 200, "y": 0, "w": 60, "h": 60},
        {"id": "c", "type": "curve", "entity": "sensor.smith_grid_power", "hours": 24, "x": 300, "y": 0, "w": 200, "h": 60},
        {"id": "b", "type": "bar", "entity": "sensor.anna_phone_battery", "x": 300, "y": 70, "w": 200, "h": 20},
        {"id": "bc", "type": "bar_chart", "entity": "sensor.smith_grid_power", "x": 300, "y": 100, "w": 200, "h": 60},
        {"id": "bx", "type": "box", "x": 0, "y": 0, "w": 10, "h": 10},
        {"id": "l", "type": "line", "x": 0, "y": 0, "w": 10, "h": 2},
        {"id": "q", "type": "qr", "qr_mode": "wifi", "wifi_ssid": SSID, "wifi_password": PASSWORD, "wifi_auth": "WPA", "x": 500, "y": 0, "w": 150, "h": 150},
        {"id": "qn", "type": "text", "value": SSID, "pill": True, "x": 500, "y": 160, "w": 150, "h": 30},
        {"id": "g", "type": "group", "style": "outline", "members": ["n", "t"]},
        {"id": "dg", "type": "dynamic_grid", "x": 0, "y": 0, "w": 300, "h": 100, "header_title": "On now",
         "items": [{"entity": "person.anna_smith", "name": "Anna", "icon": ""}, {"entity": "media_player.kitchen_sonos_17", "name": "", "icon": ""}]},
        {"id": "bat", "type": "dynamic_grid", "x": 0, "y": 0, "w": 300, "h": 100, "batteries": "swap", "filter_rule": "below", "filter_value": 20,
         "except": ["sensor.anna_phone_battery"], "also": [], "items": [{"entity": "sensor.anna_phone_battery", "threshold": 30}]},
        {"id": "wt", "type": "text", "entity": "sensor.epaper_smithflix", "show": "state", "x": 0, "y": 0, "w": 100, "h": 30},
    ]
    return els


def sender_pages():
    return {
        "anna": {"tier": "when", "show_if": "{{ is_state('binary_sensor.annas_window', 'on') }}", "notify": "notifyme1",
                 "elements": every_element()},
        "watch": {"tier": "when", "show_if": "{{ states('sensor.epaper_smithflix_count') | int(0) > 0 }}",
                  "elements": [{"id": "wx", "type": "text", "entity": "sensor.epaper_smithflix", "x": 0, "y": 0, "w": 100, "h": 30}]},
        "changed": {"tier": "alert", "show_if": {"changed": "person.anna_smith", "minutes": 10}, "ends": "until",
                    "until_if": "{{ is_state('person.anna_smith', 'home') }}", "elements": []},
    }


def fill(pages, answers):
    """The editor's own filling (app/share.js), under node."""
    script = (f"const S = await import({json.dumps(SHARE_JS.as_uri())});\n"
              f"console.log(JSON.stringify(S.fill({json.dumps(pages)}, {json.dumps(answers)})));")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def slots_of(original, exported, found=None):
    """Which of the sender's IDs each slot stands for, by lining the file up with the pages it came
    from (the file itself never says)."""
    found = {} if found is None else found
    if isinstance(exported, str) and isinstance(original, str):
        parts = re.split(r"(%slot:\d+(?:\.[a-z]+)?%)", exported)
        if len(parts) > 1:
            pattern = "".join("(.*?)" if share._TOKEN.fullmatch(p) else re.escape(p) for p in parts)
            m = re.fullmatch(pattern, original, re.S)
            if m:
                for tok, val in zip([p for p in parts if share._TOKEN.fullmatch(p)], m.groups()):
                    t = share._TOKEN.fullmatch(tok)
                    if t.group(2) is None:
                        found[int(t.group(1))] = val
    elif isinstance(exported, dict) and isinstance(original, dict):
        for k, v in exported.items():
            slots_of(original.get(k), v, found)
    elif isinstance(exported, list) and isinstance(original, list):
        for o, e in zip(original, exported):
            slots_of(o, e, found)
    return found


def elsewhere(eid: str) -> str:
    """The same kind of sensor in another home."""
    domain, obj = eid.split(".", 1)
    return f"{domain}.other_home_{obj[-6:]}"


def as_imported(pages: dict) -> dict:
    """What another home should get: the sender's IDs swapped for its own, and what stays home gone."""
    text = json.dumps(pages)
    for e in SENDER:
        if not e.get("is_epaper"):
            text = re.sub(re.escape(e["entity_id"]) + r"(?![a-z0-9_])", elsewhere(e["entity_id"]), text)
    text = text.replace("sensor.epaper_smithflix", "sensor.epaper_watch")
    text = text.replace(SSID, "Guests").replace(PASSWORD, "welcome-in")
    out = json.loads(text)
    for p in out.values():
        p.pop("notify", None)
        for el in p["elements"]:
            for k in share._PLACE_KEYS:
                el.pop(k, None)
            if isinstance(el.get("data"), dict):
                el.pop("data")
            if el.get("batteries"):
                el.update({"except": [], "also": [], "items": []})
            if el.get("type") == "qr" and el.get("wifi_ssid"):
                el["wifi_auth"] = "WPA2"
    return sanitize_layouts({"pages": out, "rotation": list(out)})["pages"]


class TestNothingPrivateLeaves(unittest.TestCase):
    def setUp(self):
        self.file = share.export(sender_pages(), ["anna", "watch"], "792x272", SENDER, SOURCES)
        self.text = json.dumps(self.file, ensure_ascii=False)

    def test_no_ids_names_places_wifi_sources_or_keys(self):
        for secret in SECRETS + NAMES:
            self.assertNotIn(secret, self.text, f"{secret!r} left the sender's home")

    def test_every_one_of_the_senders_sensors_is_a_slot(self):
        kinds = sorted(s["kind"] for s in self.file["slots"])
        self.assertEqual(kinds.count("wifi"), 1)
        self.assertEqual(kinds.count("jellyfin"), 1)
        self.assertGreaterEqual(kinds.count("entity"), 8)
        for s in self.file["slots"]:
            self.assertTrue(s["uses"], s)

    def test_a_slot_says_only_what_ranks_the_importers_sensors(self):
        temp = next(s for s in self.file["slots"] if s.get("device_class") == "temperature")
        self.assertEqual((temp["domain"], temp["unit"]), ("sensor", "°C"))
        self.assertEqual(set(temp), {"id", "kind", "domain", "device_class", "unit", "needed", "uses"})

    def test_what_a_condition_or_template_needs_is_needed(self):
        window = next(s for s in self.file["slots"] if s.get("device_class") == "window")
        self.assertTrue(window["needed"])
        battery = next(s for s in self.file["slots"] if s.get("device_class") == "battery")
        self.assertFalse(battery["needed"])

    def test_the_add_ons_own_sensors_stay_as_they_are(self):
        self.assertIn("sensor.epaper_sports_eng_1", self.text)

    def test_the_words_typed_go_and_are_listed(self):
        words = share.words(self.file)
        self.assertIn("… in Anna's room", words)
        self.assertIn("since", words)
        self.assertIn("Anna", words)                       # a Devices grid item's own name, as written
        self.assertFalse([w for w in words if "%slot" in w or "{{" in w or w.startswith("mdi:")], words)
        typed_id = share.words({"pages": [{"name": "x", "elements": [{"type": "text", "value": "sensor.epaper_watch"}]}]})
        self.assertEqual(typed_id, ["X"])

    def test_the_file_name(self):
        self.assertEqual(share.file_name("Kitchen"), "Kitchen.epaper.json")
        self.assertEqual(share.file_name("A/B: c?"), "A B c.epaper.json")
        self.assertEqual(share.file_name(""), "Page.epaper.json")


@unittest.skipUnless(shutil.which("node"), "no node to fill a file in as the editor does")
class TestRoundTrip(unittest.TestCase):
    def test_every_kind_of_element_comes_back_the_same_with_the_other_homes_sensors(self):
        pages = sender_pages()
        file = share.export(pages, ["anna", "watch"], "792x272", SENDER, SOURCES)
        opened = share.open_file(json.dumps(file))
        self.assertEqual([p["name"] for p in opened["pages"]], ["anna", "watch", "changed"])
        self.assertEqual(opened["rotation"], ["anna", "watch"])
        self.assertEqual(opened["canvas"], "792x272")
        was = slots_of({p["name"]: {k: v for k, v in pages[p["name"]].items()} for p in file["pages"]},
                       {p["name"]: {k: v for k, v in p.items() if k != "name"} for p in file["pages"]})
        answers = {}
        for s in opened["slots"]:
            if s["kind"] == "wifi":
                answers[s["id"]] = {"ssid": "Guests", "password": "welcome-in", "auth": "WPA2"}
            elif s["kind"] == "jellyfin":
                answers[s["id"]] = "sensor.epaper_watch"
            else:
                answers[s["id"]] = elsewhere(was[s["id"]])
        got = {p.pop("name"): p for p in fill(opened["pages"], answers)}
        want = as_imported(pages)
        self.assertEqual(sorted(got), sorted(want))
        for name in want:
            for g, w in zip(got[name]["elements"], want[name]["elements"]):
                self.assertEqual(g, w, f"{name}: {w.get('type')}")
            self.assertEqual(got[name], want[name], name)

    def test_every_widget_the_add_on_draws_is_in_the_round_trip(self):
        types = {el["type"] for el in every_element()}
        self.assertEqual(types, share.drawable())

    def test_a_page_with_nothing_of_the_home_needs_no_answers(self):
        page = {"clock": {"tier": "rotate", "elements": [{"id": "a", "type": "text", "show": "now", "format": "time", "x": 0, "y": 0, "w": 9, "h": 9}]}}
        opened = share.open_file(json.dumps(share.export(page, ["clock"], "800x480", SENDER, SOURCES)))
        self.assertEqual(opened["slots"], [])
        self.assertEqual(opened["canvas"], "800x480")
        self.assertEqual(fill(opened["pages"], {})[0]["elements"], page["clock"]["elements"])


class TestOpening(unittest.TestCase):
    def file(self, **over):
        return json.dumps({**share.export(sender_pages(), ["anna"], "792x272", SENDER, SOURCES), **over})

    def refused(self, text):
        with self.assertRaises(share.Refused) as r:
            share.open_file(text)
        return str(r.exception)

    def test_something_else_is_refused_plainly(self):
        for text in ("", "not json", "[]", json.dumps({"pages": []}), self.file(format="other"), self.file(version=0),
                     self.file(version="1"), self.file(pages=[]), self.file(slots=[{"id": 1, "kind": "password"}])):
            self.assertIn("isn't a shared page", self.refused(text))

    def test_a_newer_file_says_to_update(self):
        said = self.refused(self.file(version=share.VERSION + 1, made_with="0.30.0"))
        self.assertEqual(said, "This was shared from a newer e-Paper Panel (0.30.0). Update the add-on, then open it again.")

    def test_something_this_version_cant_draw_is_refused_by_name(self):
        f = json.loads(self.file())
        f["pages"][0]["elements"].append({"id": "z", "type": "aurora_forecast", "x": 0, "y": 0, "w": 9, "h": 9})
        said = self.refused(json.dumps(f))
        self.assertIn("(Aurora forecast)", said)
        self.assertIn("Update the add-on", said)

    def test_a_token_with_no_slot_is_refused(self):
        f = json.loads(self.file())
        f["slots"] = []
        self.assertIn("isn't a shared page", self.refused(json.dumps(f)))

    def test_its_notifications_never_come_in(self):
        f = json.loads(self.file())
        f["pages"][0]["notify"] = "abcdef12"
        self.assertNotIn("notify", share.open_file(json.dumps(f))["pages"][0])

    def test_page_names_are_made_safe_and_unique(self):
        f = json.loads(self.file())
        f["pages"] = [{**f["pages"][0], "name": "Kitchen / Hall"}, {**f["pages"][0], "name": "kitchen_hall"}]
        f["rotation"] = ["Kitchen / Hall", "kitchen_hall"]
        opened = share.open_file(json.dumps(f))
        self.assertEqual([p["name"] for p in opened["pages"]], ["kitchen_hall", "kitchen_hall_2"])
        self.assertEqual(opened["rotation"], ["kitchen_hall", "kitchen_hall_2"])

    def test_a_slot_shows_an_example_of_its_kind_until_its_picked(self):
        opened = share.open_file(self.file())
        temp = next(s for s in opened["slots"] if s.get("device_class") == "temperature")
        self.assertTrue(temp["example"].startswith("sensor."))
        wifi = next(s for s in opened["slots"] if s["kind"] == "wifi")
        self.assertEqual(wifi["example"]["ssid"], "Your network")


class TestEditorEntryPoints(unittest.TestCase):
    """Where Share and Open live (the user's call, 26 Oct): the page's inspector and menu, the device
    menu, New page's footer, the first run and a file dropped on the editor."""

    def test_they_are_where_the_user_chose(self):
        web = support.APP / "web" / "app"
        main, inspector, newpage = ((web / f).read_text() for f in ("main.js", "inspector.js", "newpage.js"))
        self.assertIn('label: "Share…"', main)
        self.assertIn('label: "Share all pages…"', main)
        self.assertIn("app.sharePage()", inspector)
        self.assertIn("openFileButton(", newpage)
        self.assertIn("openFileButton(", main)
        self.assertIn('addEventListener("drop"', main)


if __name__ == "__main__":
    unittest.main()
