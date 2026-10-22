"""The New page sheet's presets (web/app/presets.js), read under node and drawn by
the real renderer: what's offered and where, what each look's page is, and that
every preset's words fit their boxes at every size the add-on offers.

The sheet itself has no JavaScript test runner, so its wiring and its CSS are
pinned in the source, as test_editor_chrome does."""
import json
import re
import shutil
import subprocess
import unittest

import support
import fixture
from render import arrange, layout, theme as T, todo
from sources import racing, sports

WEB = support.APP / "web"
APP_JS = WEB / "app"
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "editor.css").read_text(), flags=re.S)


def calls(src, opener):
    """Each call's arguments, by matching brackets (a regex stops at the first ")" inside)."""
    out, at = [], 0
    while (at := src.find(opener, at)) >= 0:
        k, depth = at + len(opener), 1
        while depth and k < len(src):
            depth += {"(": 1, ")": -1}.get(src[k], 0)
            k += 1
        out.append(src[at + len(opener):k - 1])
        at = k
    return out


def top_level(args):
    """A call's arguments split at its own commas, not those inside brackets."""
    out, depth, cur = [], 0, ""
    for ch in args:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    return out + [cur]


_CATALOG = None


def catalog_json():
    """The add-on's own catalog (GET /api/catalog), as the editor reads it at its start."""
    global _CATALOG
    if _CATALOG is None:
        import asyncio
        import web
        from aiohttp.test_utils import TestClient, TestServer

        async def get():
            _, editor = web.make_apps()
            client = TestClient(TestServer(editor))
            await client.start_server()
            try:
                return await (await client.get("/api/catalog")).json()
            finally:
                await client.close()
        _CATALOG = asyncio.run(get())
    return _CATALOG


def run_js(body):
    script = (f"import * as Cat from {json.dumps(str(APP_JS / 'catalog.js'))};"
              f"import * as P from {json.dumps(str(APP_JS / 'presets.js'))};"
              f"import * as L from {json.dumps(str(APP_JS / 'legacy.js'))};"
              f"Cat.setCatalog({json.dumps(catalog_json())});\n{body}")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


CATALOGUE = """
const ents = { calendar: "calendar.family", todo: "todo.chores", sensor: "sensor.indoor_temperature", binary_sensor: "binary_sensor.front_door",
  weather: "weather.forecast_home", jellyfin: "sensor.epaper_films" };
console.log(JSON.stringify({ groups: P.GROUPS, canvas: P.CANVAS, presets: P.PRESETS.map((p) => ({
  id: p.id, group: p.group, title: p.title, was: p.was || "", choose: p.choose || "", asks: p.asks, needs: p.needs || "", prefer: p.prefer || null,
  looks: p.looks.map((l) => ({ id: l.id, name: l.name, page: P.pageFor(p, l, ents[p.asks] || ""), example: P.examplePage(p, l),
    name_of_page: P.pageName(p, l, ents[p.asks] || "", "Front door") })),
})) }));
"""


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestCatalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = run_js(CATALOGUE)
        cls.by_id = {p["id"]: p for p in cls.cat["presets"]}

    def test_the_groups_in_order(self):
        self.assertEqual([n for _, n in self.cat["groups"]], ["Your day", "Home", "Energy", "Outside", "Sports", "Watch and listen"])
        groups = {g for g, _ in self.cat["groups"]}
        for p in self.cat["presets"]:
            self.assertIn(p["group"], groups, p["id"])

    def test_one_preset_per_thing_its_looks_picked_next(self):
        looks = {pid: [l["name"] for l in p["looks"]] for pid, p in self.by_id.items()}
        self.assertEqual(looks["planes"], ["Nearest plane", "Radar", "Both"])
        self.assertEqual(looks["calendar"], ["Month and agenda", "Month"])
        self.assertEqual(looks["watch"], ["Newest", "Episode card", "Up next"])
        self.assertEqual(self.by_id["match"]["choose"], "League")
        self.assertEqual(self.by_id["race_weekend"]["choose"], "Series")
        titles = [p["title"] for p in self.cat["presets"]]
        self.assertEqual(len(titles), len(set(titles)), "no thing offered twice")

    def test_planes_are_outside_with_the_weather(self):
        outside = [p["title"] for p in self.cat["presets"] if p["group"] == "outside"]
        self.assertEqual(outside, ["Weather", "Sunrise and sunset", "Planes overhead"])

    def test_sunrise_and_sunset_in_its_two_styles(self):
        p = self.by_id["sun_times"]
        self.assertEqual([l["name"] for l in p["looks"]], ["Next one first", "Both alike"])
        from render import sun
        self.assertEqual([l["page"]["elements"][0]["style"] for l in p["looks"]], list(sun.STYLES))
        self.assertEqual(p["asks"], "", "nothing to set up: Home Assistant's own sun")
        style = next(f for f in catalog_json()["widgets"]["sun_times"]["fields"] if f["key"] == "style")
        self.assertEqual([o[0] for o in style["options"]], list(sun.STYLES), "the inspector's choices are the descriptor's")
    def test_the_to_do_list_in_its_three_styles_by_urgency_first(self):
        p = self.by_id["to_do"]
        self.assertEqual(p["group"], "day")
        self.assertEqual([l["name"] for l in p["looks"]], ["By urgency", "Inverted when due", "Outlined"])
        styles = [l["page"]["elements"][0]["style"] for l in p["looks"]]
        self.assertEqual(styles, ["urgency", "due", "outlined"])
        self.assertEqual(styles[0], todo.DEFAULT_STYLE)
        self.assertTrue(all(s in todo.STYLES for s in styles))
        self.assertEqual(p["looks"][0]["name_of_page"], "Front door", "a page per list, named after it")

    def test_clearer_names_and_search_still_finds_the_old_ones(self):
        self.assertEqual((self.by_id["status"]["title"], self.by_id["status"]["was"]), ("Status", "Door or pet"))
        self.assertEqual((self.by_id["dynamic_status"]["title"], self.by_id["dynamic_status"]["was"]), ("Dynamic status", "On now"))
        self.assertEqual((self.by_id["race_weekend"]["title"], self.by_id["race_weekend"]["was"]), ("Race weekend", "Formula 1"))
        found = run_js("""console.log(JSON.stringify(["door", "on now", "formula 1", "f1", "plane overhead", "bundesliga", "shopping"]
          .map((q) => P.search(q)[0].id)));""")
        self.assertEqual(found, ["status", "dynamic_status", "race_weekend", "race_weekend", "planes", "match", "to_do"])

    def test_scores_names_each_event_in_its_sports_own_word(self):
        """The user's call: Scores, not Match; and a Premier League match is never a game. The words
        are the add-on's (catalog: render/sport.py), the editor has none of its own."""
        p = self.by_id["match"]
        self.assertEqual((p["title"], p["was"]), ("Scores", "Match score"))
        words = run_js("""console.log(JSON.stringify(Object.fromEntries(Cat.leagues().map((l) => [l.name, Cat.sportWord(l.path)]))))""")
        self.assertEqual(words["Premier League"], "match")
        self.assertEqual(words["NBA"], "game")
        notes = run_js('console.log(JSON.stringify(P.presetById("match").looks.map((l) => l.note)))')
        self.assertEqual(notes[0], "Shows on match days.")
        self.assertIn("Shows on game days.", notes)
        window = next(f for f in catalog_json()["widgets"]["sports_match"]["fields"] if f["kind"] == "window")
        self.assertIn("{event}", window["label"])
        self.assertIn('out.label = (el) => f.label.replace("{event}", sportWord(el.league));', (APP_JS / "inspector.js").read_text())
        desc = run_js('console.log(JSON.stringify(P.presetById("match").desc))')
        self.assertNotRegex(desc, r"(?i)\b(match|game)|kick-off|whistle", "the preset itself stays neutral")
        self.assertEqual(run_js('console.log(JSON.stringify(P.search("match score")[0].id))'), "match")
    def test_the_editor_and_the_panel_use_the_same_words(self):
        from render import sport
        keys = list(sport.SPORTS) + ["unknown"]
        got = run_js(f"console.log(JSON.stringify({json.dumps(keys)}.map((k) => Cat.sportWord(k + '/x'))))")
        self.assertEqual(got, [sport.words(k + "/x").event for k in keys])
        src = (APP_JS / "presets.js").read_text()
        self.assertNotIn("SPORT_WORDS", src, "no copy of the table")
    def test_every_league_and_series_the_add_on_fetches(self):
        """Framework review #5: what's offered is the add-on's own list, both ways round."""
        got = run_js("""console.log(JSON.stringify([P.presetById("match").looks.map((l) => l.name), P.presetById("race_weekend").looks.map((l) => l.name)]))""")
        self.assertEqual(got[0], [lg.name for lg in sports.LEAGUES])
        self.assertEqual(got[1], [s.title for s in racing.SERIES.values()])
        for name in ("presets.js", "legacy.js", "inspector.js"):
            src = (APP_JS / name).read_text()
            for copy in ("LEAGUE_TO_SLUG", "export const LEAGUES", "export const SERIES", '"premier_league"', '"nascar-premier"'):
                self.assertNotIn(copy, src, f"{name} keeps no copy: {copy}")
    def test_the_inspector_offers_the_same_leagues_and_series(self):
        src = (APP_JS / "inspector.js").read_text()
        self.assertIn('if (f.options === "leagues") out.options = leagueOptions();', src)
        self.assertIn('if (f.options === "series") out.options = seriesOptions();', src)
        got = run_js("console.log(JSON.stringify([Cat.leagueOptions().length, Cat.seriesOptions().map(([s]) => s)]))")
        self.assertEqual(got, [len(sports.LEAGUES), list(racing.SERIES)])
        sensors = run_js("""console.log(JSON.stringify([L.getWidgetSensorId({ type: "sports_racing", series: "nascar_cup" }),
          L.getWidgetSensorId({ type: "sports_match", league: "epl" })]))""")
        self.assertEqual(sensors, ["sensor.epaper_racing_nascar", "sensor.epaper_sports_premier_league"], "aliases from the catalog (the review's nascar_cup)")
    def test_a_league_or_series_shows_by_its_own_sensor(self):
        for pid in ("match", "race_weekend"):
            for look in self.by_id[pid]["looks"]:
                page = look["page"]
                el = page["elements"][0]
                self.assertEqual(page["tier"], "when")
                if pid == "race_weekend":
                    slug = racing.series_slug(el["series"])[0]
                    self.assertEqual(page["show_if"], "{{ is_state('sensor.epaper_racing_%s','active') }}" % slug)
                else:
                    self.assertRegex(page["show_if"], r"^\{\{ is_state\('sensor\.epaper_sports_[a-z_]+','active'\) \}\}$")
                self.assertEqual(look["name_of_page"], look["name"], "the page is named after the league or series")

    def test_planes_show_while_one_is_near(self):
        for look in self.by_id["planes"]["looks"]:
            self.assertEqual(look["page"]["show_if"], "{{ has_value('sensor.epaper_flights_overhead') and states('sensor.epaper_flights_overhead') | float(0) > 0 }}")
        self.assertEqual([l["page"]["elements"][0]["style"] for l in self.by_id["planes"]["looks"]], ["card", "radar", "split"])

    def test_no_guessed_entity_ids(self):
        """A page shows what the person picked, or nothing: never an entity someone might happen to have."""
        cat = run_js(CATALOGUE.replace('const ents = {', 'const ents = {}; const _x = {'))
        for p in cat["presets"]:
            for look in p["looks"]:
                for el in look["page"]["elements"]:
                    if el.get("entity") and not el["entity"].startswith("sensor.epaper_"):
                        self.fail(f"{look['id']} guesses {el['entity']}")


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestGuestWifi(unittest.TestCase):
    def test_the_code_and_the_page_carry_your_network(self):
        els = run_js('console.log(JSON.stringify(P.guestWifi({ ssid: "Guests", password: "pass word", auth: "WPA" })))')
        qr = next(e for e in els if e["type"] == "qr")
        self.assertEqual((qr["wifi_ssid"], qr["wifi_password"], qr["wifi_auth"]), ("Guests", "pass word", "WPA"))
        self.assertIn("Guests", [e.get("value") for e in els])
        self.assertNotIn("pass word", [e.get("value") for e in els], "the password stays in the code")

    def test_it_asks_for_the_network(self):
        p = run_js('console.log(JSON.stringify(P.presetById("guest_wifi").needs))')
        self.assertEqual(p, "wifi")
        src = (APP_JS / "setup.js").read_text()
        self.assertTrue("ready: () => !!wifi.ssid.trim()," in src, "Add page waits for the network's name")

    def test_the_words_stay_left_of_the_code(self):
        els = run_js('console.log(JSON.stringify(P.guestWifi({ ssid: "A network name of thirty-two ch" })))')
        qr = next(e for e in els if e["type"] == "qr")
        for e in els:
            if e["type"] == "text":
                self.assertLessEqual(e["x"] + e["w"], qr["x"] - 16, e.get("value"))


def example_values(page):
    """A page's values as the offline fixture answers them: the example values."""
    vals = {}
    for i, tpl in layout.collect_templates(page).items():
        vals[i] = fixture.eval_fixture_template(tpl)
    return vals


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestEverythingFits(unittest.TestCase):
    """Every look's words fit their boxes, on the 5.79" and placed on every other size offered."""

    @classmethod
    def setUpClass(cls):
        cls.cat = run_js(CATALOGUE)

    def check(self, page, display, orientation=0):
        metrics = []
        layout.render_page(page, example_values(page), metrics=metrics, display=display, orientation=orientation)
        return [m for m in metrics if m.get("overflow")]

    def test_on_every_offered_size(self):
        base = arrange.canvas_key(T.DISPLAYS["crowpanel_579"]["w"], T.DISPLAYS["crowpanel_579"]["h"])
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            target = arrange.canvas_key(d["w"], d["h"])
            for p in self.cat["presets"]:
                for look in p["looks"]:
                    page = json.loads(json.dumps(look["example"]))
                    for el in page["elements"]:
                        el.update(arrange.auto_box(el, base, target))
                    with self.subTest(look=look["id"], display=key):
                        self.assertEqual(self.check(page, key), [])

    def test_the_presets_canvas_is_the_5_79(self):
        c = self.cat["canvas"]
        self.assertEqual((c["w"], c["h"], c["band"]), (T.DISPLAYS["crowpanel_579"]["w"], T.DISPLAYS["crowpanel_579"]["h"], T.band_height(272)))

    def test_placed_on_another_size_by_the_add_on(self):
        """Framework review #5: the editor keeps no copy of arrange.auto_box; New page asks POST /api/fit."""
        js = (APP_JS / "newpage.js").read_text()
        self.assertIn('api("api/fit", { method: "POST", body: { elements: els, from_canvas: `${CANVAS.w}x${CANVAS.h}`', js)
        self.assertIn("page.elements = await fitToDevice(app, page);", js)
        self.assertNotIn("fitToCanvas", (APP_JS / "presets.js").read_text())

@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestSensibleFirst(unittest.TestCase):
    ENTS = [
        {"entity_id": "sensor.power_meter", "unit": "W", "device_class": "power"},
        {"entity_id": "sensor.solar_month", "unit": "kWh", "device_class": "energy"},
        {"entity_id": "sensor.outdoor", "unit": "°F"},
        {"entity_id": "sensor.living_room", "unit": "°C", "device_class": "temperature"},
        {"entity_id": "sensor.pv_today", "unit": "kWh", "device_class": "energy"},
        {"entity_id": "binary_sensor.front_door", "unit": ""},
        {"entity_id": "person.sam", "unit": ""},
        {"entity_id": "light.hall", "unit": ""},
    ]

    def rank(self, preset, energy=None):
        return run_js(f"""console.log(JSON.stringify(P.rankSensors(P.presetById({json.dumps(preset)}), {json.dumps(self.ENTS)}, {json.dumps(energy or {})})
          .map(({{ e, tag }}) => [e.entity_id, tag])));""")

    def test_temperature_sensors_first(self):
        got = [e for e, _ in self.rank("climate")]
        self.assertEqual(got[:2], ["sensor.living_room", "sensor.outdoor"], "device class, then unit")
        self.assertEqual(len(got), 5, "every other sensor is still there, after them")

    def test_the_energy_dashboards_sensor_first_and_said_so(self):
        got = self.rank("solar", {"solar": ["sensor.pv_today"]})
        self.assertEqual(got[0], ["sensor.pv_today", "From your Energy dashboard"])
        self.assertEqual(got[1], ["sensor.solar_month", ""])

    def test_a_running_total_shows_its_change_today(self):
        """Framework review #3: still the sensor you pick, but a lifetime meter reads today's share."""
        got = run_js("""const p = P.presetById("solar");
          console.log(JSON.stringify(["total_increasing", "total", "measurement", ""].map((sc) =>
            P.pageFor(p, p.looks[0], "sensor.pv", undefined, () => ({ unit: "kWh", state_class: sc })).elements[1].show)))""")
        self.assertEqual(got, ["change_today", "change_today", "state", "state"])

    def test_without_an_energy_dashboard_energy_sensors_first(self):
        self.assertEqual([e for e, _ in self.rank("solar")][:2], ["sensor.solar_month", "sensor.pv_today"])

    def test_status_shows_any_state_door_sensors_first(self):
        got = [e for e, _ in self.rank("status")]
        self.assertEqual(got[:2], ["binary_sensor.front_door", "person.sam"])
        self.assertNotIn("light.hall", got)


class TestSetsUpWhatItNeeds(unittest.TestCase):
    """New to watch connects Jellyfin in its own step and saves it where Settings shows it."""

    def setUp(self):
        self.js = (APP_JS / "setup.js").read_text()

    def test_new_to_watch_needs_jellyfin(self):
        self.assertEqual(run_js('console.log(JSON.stringify(P.presetById("watch").needs))'), "jellyfin")
        self.assertIn("const SETUPS = { wifi: wifiSetup, jellyfin: jellyfinSetup,", self.js)

    def test_one_store_the_one_settings_shows(self):
        self.assertIn('await api("api/sources", { method: "PUT", body: [...all, src] })', self.js)
        self.assertIn('const src = { type: "jellyfin", name: freeSourceName(all), base: form.base.trim(), key: form.key.trim(), user, days: 30 };', self.js)
        self.assertEqual(set(re.findall(r'"(\w+)", "', (APP_JS / "sheets.js").read_text().split("jellyfin: [", 1)[1].split("]],", 1)[0])),
                         {"name", "base", "key", "user", "days"}, "the fields Settings › Data sources edits")

    def test_a_second_page_reuses_it(self):
        self.assertIn('mine = all.filter((s) => s.type === "jellyfin");', self.js)
        self.assertIn("if (mine.length === 1) picked = mine[0];", self.js)
        self.assertIn('return { ent: sensorOf(picked) };', self.js)

    def test_a_new_one_never_takes_another_sources_name(self):
        got = run_js("""console.log(JSON.stringify([P.freeSourceName([]), P.freeSourceName([{ name: "watch" }]),
          P.freeSourceName([{ name: "watch" }, { name: "watch_2" }]), P.sensorOf({ name: "watch_2" })]))""")
        self.assertEqual(got, ["watch", "watch_2", "watch_3", "sensor.epaper_watch_2"])

    def test_it_says_where_the_key_is_and_fills_the_address_from_jellyha(self):
        self.assertIn("In Jellyfin: Dashboard › API Keys, then +", self.js)
        self.assertIn('api("api/sources/jellyfin/suggest")', self.js)
        self.assertIn('h("small", { text: "From JellyHA" })', self.js)

    def test_whose_unwatched_is_picked_from_who_is_there(self):
        self.assertIn('api("api/sources/jellyfin/check", { method: "POST", body: { base: form.base.trim(), key: form.key.trim() } })', self.js)
        self.assertIn('"aria-label": "Whose unwatched"', self.js)


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestWorldClock(unittest.TestCase):
    """Clock's Time zones look: up to four cities, each found by its city and named as you like,
    in the order you drag them to. The cities are the add-on's (GET /api/timezones), and so is
    the layout (render/worldclock.py): the editor only edits the element's `zones`."""

    def test_a_look_of_clock_that_sets_up_its_cities(self):
        got = run_js("""const p = P.presetById("clock"), look = p.looks.find((l) => l.id === "world_clock");
          const mine = [{ tz: "Europe/Lisbon", label: "Mum" }, { tz: "", label: "" }];
          console.log(JSON.stringify({ looks: p.looks.map((l) => l.name), needs: look.needs,
            made: P.pageFor(p, look, null, { zones: mine }).elements, alone: P.pageFor(p, look, null, {}).elements[0].zones }))""")
        self.assertEqual(got["looks"], ["Clock", "Time zones"])
        self.assertEqual(got["needs"], "zones")
        self.assertEqual(len(got["made"]), 1)
        self.assertEqual(got["made"][0]["type"], "world_clock")
        self.assertEqual(got["made"][0]["zones"], [{"tz": "Europe/Lisbon", "label": "Mum"}, {"tz": "", "label": ""}])
        self.assertEqual(got["alone"], [{"tz": "", "label": ""}], "with nothing picked, Home Assistant's own time")

    def test_its_step_is_the_cities(self):
        js = (APP_JS / "setup.js").read_text()
        self.assertIn("zones: zonesSetup", js)
        self.assertIn("zonesEditor(el, changed, { live: true })", js)
        self.assertIn('const extra = () => ({ zones: el.zones.map((z) => ({ tz: z.tz || "", label: String(z.label || "").trim() })) });', js)

    def test_the_inspector_edits_what_the_descriptor_asks(self):
        """One source: the widget's descriptor says it has a "zones" field, at most 4; the inspector
        draws that kind with the same editor, and every change is a commit, so the canvas redraws."""
        f = next(f for f in catalog_json()["widgets"]["world_clock"]["fields"] if f["key"] == "zones")
        self.assertEqual((f["kind"], f["most"]), ("zones", 4))
        self.assertIn('else if (f.kind === "zones") s.append(field(f.label || "Cities", zonesEditor(el, () => app.doc.commit(), { most: f.most || 4 }), { wide: true }));',
                      (APP_JS / "inspector.js").read_text())

    def test_the_cities_editor(self):
        js = (APP_JS / "zones.js").read_text()
        self.assertIn('api("api/timezones")', js, "the add-on's time zones, never a copy")
        self.assertIn('e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")', js, "reorder by keyboard, not only by drag")
        self.assertIn("dragToReorder(grip, k);", js)
        self.assertIn('h("span", { class: "o1", text: "Here" })', js, "Home Assistant's own zone, first")
        self.assertIn("el.zones.length < most && picking !== \"new\"", js, "Add a city up to the most")
        self.assertIn("text: `Up to ${most} cities.`", js)
        self.assertIn("placeholder: nameOf(z)", js, "an empty name reads as its city")
        self.assertIn("No city by that name. Try the nearest big city in the same time zone.", js)
        self.assertNotIn("innerHTML", js)

    def test_hit_targets(self):
        """Its buttons are the editor's own (.btn.icon: --ctl, 44 px on touch)."""
        js = (APP_JS / "zones.js").read_text()
        self.assertIn('h("button", { class: "btn icon zgrip"', js)
        self.assertIn('h("button", { class: "btn icon", "aria-label": `Remove ${nameOf(z)}`', js)



class TestEveryFieldKindHasAnEditor(unittest.TestCase):
    """The inspector draws a widget's settings from its descriptor's fields, by kind: one path."""

    def test_every_kind_a_descriptor_asks_for_has_an_editor(self):
        insp = (APP_JS / "inspector.js").read_text()
        kinds = {f["kind"] for w in catalog_json()["widgets"].values() for f in w.get("fields", []) if isinstance(f, dict) and f.get("kind")}
        for k in sorted(kinds):
            with self.subTest(kind=k):
                self.assertIn(f'f.kind === "{k}"', insp)


@unittest.skipUnless(shutil.which("node"), "no node to read the editor")
class TestCitySearch(unittest.TestCase):
    """Found by the browser check: "tok" listed Vostok before Tokyo, and Esc in the search left
    New page's step (and the cities picked) instead of closing the search."""

    def find(self, q):
        src = (APP_JS / "zones.js").as_uri()
        zones = [{"city": "Vostok", "region": "Antarctica", "tz": "Antarctica/Vostok"}, {"city": "Tokyo", "region": "Asia", "tz": "Asia/Tokyo"},
                 {"city": "Ho Chi Minh", "region": "Asia", "tz": "Asia/Ho_Chi_Minh"}, {"city": "Chicago", "region": "America", "tz": "America/Chicago"}]
        js = f"""globalThis.navigator = {{ platform: "", userAgent: "" }};
          const Z = await import({json.dumps(src)});
          console.log(JSON.stringify(Z.findCities({json.dumps(zones)}, {json.dumps(q)}).map((z) => z.city)));"""
        out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_a_city_that_starts_with_it_first(self):
        self.assertEqual(self.find("tok"), ["Tokyo", "Vostok"])
        self.assertEqual(self.find("chi"), ["Chicago", "Ho Chi Minh"])
        self.assertEqual(self.find("asia"), ["Tokyo", "Ho Chi Minh"])
        self.assertEqual(self.find("zzz"), [])

    def test_esc_closes_the_search_and_keeps_the_step(self):
        js = (APP_JS / "zones.js").read_text()
        self.assertIn('h("div", { class: "picker zpick", "data-own-esc": "" }', js)
        self.assertIn("const was = picking; picking = null; draw(); refocus(was);", js, "and focus goes back where it was opened")
        self.assertNotIn("drawAll", js, "the list's own draw() is drawList, so draw() is the whole editor")
        self.assertIn('if (e.key === "Escape" && step && !e.target.closest?.("[data-own-esc]"))', (APP_JS / "newpage.js").read_text())


class TestCitiesEditorCanBeClicked(unittest.TestCase):
    def test_its_class_is_not_the_canvas_guides(self):
        """The canvas's guides are .zones (absolute, no pointer events): the editor named so couldn't be clicked."""
        self.assertIn('class: "zones"', (APP_JS / "canvas.js").read_text())
        self.assertNotIn('class: "zones"', (APP_JS / "zones.js").read_text())
        self.assertIn('h("div", { class: "cities" })', (APP_JS / "zones.js").read_text())


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestEnergy(unittest.TestCase):
    """The Energy dashboard's presets read it themselves, and set up a sensor in place when it lacks one."""
    # GET /api/energy, as sources/energy.summarise gives it (widgets-015).
    DASHBOARD = {"solar": [{"energy": "sensor.solar_energy", "power": "sensor.solar_power"}],
                 "grid": [{"flows": [{"import": "sensor.grid_in", "export": "sensor.grid_out", "cost": "", "compensation": ""}],
                           "power": {"plus": "sensor.grid_power", "minus": ""}}],
                 "has_cost": True, "currency": "EUR"}

    def dashboard(self):
        try:
            from sources import energy               # widgets-015's, once both are merged
            return {**energy.summarise(energy.OFFLINE_PREFS, energy.OFFLINE_INFO), "currency": "EUR"}
        except ImportError:
            return self.DASHBOARD

    def test_the_energy_shelf(self):
        titles = run_js('console.log(JSON.stringify(P.PRESETS.filter((p) => p.group === "energy").map((p) => p.title)))')
        self.assertEqual(titles, ["Solar today", "Solar this month", "Battery and solar", "Grid now", "Energy cost"])

    def test_the_dashboards_sensors_by_role(self):
        roles = run_js(f"console.log(JSON.stringify(P.energyRoles({json.dumps(self.dashboard())})))")
        self.assertTrue(roles["known"])
        self.assertTrue(roles["solar_energy"] and set(roles["solar_energy"]) <= set(roles["solar"]))
        self.assertTrue(roles["grid"] and set(roles["grid_power"]) <= set(roles["grid"]))
        self.assertTrue(roles["has_cost"])
        self.assertEqual(run_js("console.log(JSON.stringify(P.energyRoles({})))")["solar"], [], "no dashboard, nothing picked")

    def test_solar_today_opens_with_the_dashboards_sensor(self):
        roles = run_js(f"console.log(JSON.stringify(P.energyRoles({json.dumps(self.dashboard())})))")
        ents = [{"entity_id": "sensor.other_kwh", "unit": "kWh"}] + [{"entity_id": e, "unit": "kWh"} for e in roles["solar_energy"]]
        got = run_js(f"console.log(JSON.stringify(P.rankSensors(P.presetById('solar'), {json.dumps(ents)}, {json.dumps(roles)})[0]))")
        self.assertEqual((got["e"]["entity_id"], got["tag"]), (roles["solar_energy"][0], "From your Energy dashboard"))

    def test_nothing_to_pick_with_a_dashboard_a_sensor_without(self):
        got = run_js("""const p = P.presetById("solar_month"), g = P.presetById("grid_now");
          console.log(JSON.stringify([p.needs, p.energy, P.pageFor(p, p.looks[0], "").elements[0], P.pageFor(p, p.looks[0], "", { entity: "sensor.pv" }).elements[0],
            P.pageFor(g, g.looks[0], "", { entity: "sensor.meter", invert: true }).elements[0], P.presetById("energy_cost").looks[0].make()[0].type]))""")
        needs, role, from_dash, from_sensor, grid, cost = got
        self.assertEqual((needs, role), ("energy", "solar"))
        self.assertEqual((from_dash["type"], from_dash["source"], from_dash["period"], from_dash["entity"]), ("energy_total", "solar", "month", ""))
        self.assertEqual((from_sensor["source"], from_sensor["entity"]), ("entity", "sensor.pv"))
        self.assertEqual((grid["type"], grid["entity"], grid["invert"]), ("grid_now", "sensor.meter", True))
        self.assertEqual(cost, "energy_cost")

    def test_it_says_where_to_set_the_dashboard_up(self):
        js = (APP_JS / "setup.js").read_text()
        self.assertIn("energy: energySetup", js)
        self.assertEqual(js.count("(in Home Assistant: Settings › Dashboards › Energy)"), 3)


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestWatchAndListen(unittest.TestCase):
    def test_the_shelf(self):
        titles = run_js('console.log(JSON.stringify(P.PRESETS.filter((p) => p.group === "media").map((p) => p.title)))')
        self.assertEqual(titles, ["Now playing", "On TV this week", "New to watch"])

    def test_now_playing_shows_while_its_players_play(self):
        got = run_js("""const p = P.presetById("now_playing");
          console.log(JSON.stringify([P.pageFor(p, p.looks[0], "", { entity: "media_player.kitchen, media_player.tv" }), P.pageFor(p, p.looks[0], "").show_if]))""")
        page, every = got
        self.assertEqual(page["tier"], "when")
        self.assertEqual(page["elements"][0], {"type": "now_playing", "entity": "media_player.kitchen, media_player.tv", "x": 24, "y": 14, "w": 744, "h": 208})
        self.assertEqual(page["show_if"], "{{ expand(['media_player.kitchen','media_player.tv']) | selectattr('state', 'eq', 'playing') | list | count > 0 }}")
        self.assertEqual(every, "{{ states.media_player | selectattr('state', 'eq', 'playing') | list | count > 0 }}")
        self.assertEqual(run_js('console.log(JSON.stringify(P.playingShowIf("x\'); bad, media_player.ok")))'),
                         "{{ expand(['media_player.ok']) | selectattr('state', 'eq', 'playing') | list | count > 0 }}", "only real entity IDs reach the template")

    def test_a_calendar_of_shows_first(self):
        ents = [{"entity_id": "calendar.family", "name": "Family"}, {"entity_id": "calendar.sonarr", "name": "Sonarr"}, {"entity_id": "sensor.x"}]
        got = run_js(f"console.log(JSON.stringify(P.rankSensors(P.presetById('tv_week'), {json.dumps(ents)}).map(({{ e }}) => e.entity_id)))")
        self.assertEqual(got, ["calendar.sonarr", "calendar.family"])

    def test_a_rain_total_is_refused_with_its_reason(self):
        """Framework review #13: a rate or an on/off sensor; a total is refused in the field, with the
        add-on's own reason (the descriptor's "accepts")."""
        rain = next(f for f in catalog_json()["widgets"]["weather_forecast"]["fields"] if f.get("key") == "rain_sensor")
        self.assertTrue(rain["accepts"]["reason"])
        src = (APP_JS / "inspector.js").read_text()
        self.assertIn("if (f.accepts) out.check = (e) => {", src)
        self.assertIn("return a.reason ||", src)
        self.assertIn('if (why) { s.querySelector(".note.refused")?.remove();', src, "and keeps what it had")
    def test_the_inspector_knows_them(self):
        """Framework review #7: a widget's fields are its descriptor's, not a list in the editor."""
        src = (APP_JS / "inspector.js").read_text()
        self.assertIn("const fields = fieldsFor(el.type);", src)
        for t in ("now_playing", "tv_week", "sun_times", "todo_list", "sports_match", "weather_forecast"):
            self.assertNotIn(f"  {t}: [", src, f"{t}'s fields come from its descriptor")
        keys = {f.get("key") for f in catalog_json()["widgets"]["weather_forecast"]["fields"]}
        for key in ("now_entity", "temperature_sensor", "humidity_sensor", "wind_sensor", "rain_sensor", "pressure_sensor", "solar_sensor"):
            self.assertIn(key, keys, "weather from your own station")

@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestThumbnailsHaveValues(unittest.TestCase):
    """Every preset's thumbnail has a value for everything it shows: the example values
    widgets-015's /api/example draws (examples.page_values), never "--"."""

    def test_every_look_has_example_values(self):
        try:
            import examples                        # widgets-015's, once both are merged
        except ImportError:
            self.skipTest("the example values arrive with widgets-015")
        cat = run_js(CATALOGUE)
        for p in cat["presets"]:
            for look in p["looks"]:
                page = look["example"]
                vals, series = examples.page_values(page)
                for i, el in enumerate(page["elements"]):
                    # An icon always draws its own icon (its state's, once it has one): nothing to be empty.
                    shows = el["type"] != "icon" and (el.get("entity") or "{{" in str(el.get("value", "")) or el["type"] in ("dynamic_grid", "weather_forecast"))
                    if not shows:
                        continue
                    with self.subTest(look=look["id"], element=i, type=el["type"]):
                        got = series.get(i) if el["type"] in ("curve", "bar_chart") else vals.get(i)
                        self.assertNotIn(got, (None, "", "--", "unknown", "unavailable", [], {}))


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestDateOnASleepingDevice(unittest.TestCase):
    """The user's call (21 Oct): on a device that sleeps between updates a clock would stop at its
    last update and flash at every wake, so Clock is a large Date there."""

    def test_clock_everywhere_saying_so_where_it_sleeps(self):
        """Framework review #10, the user's call: New page offers Clock on every device; on one that
        sleeps its card says so and the renderer draws the date (render/clocktime.py)."""
        got = run_js("""console.log(JSON.stringify([P.presetById("clock").onSleeping, P.presetById("date").looks[0].make()[0].value]))""")
        self.assertEqual(got, ["Shows the date here", "{{ now().strftime('%A') }}"])
        js = (APP_JS / "newpage.js").read_text()
        self.assertIn("const PRESETS = ALL_PRESETS, sleeps = sleepsBetweenUpdates(app.screen);", js)
        self.assertIn('const asleep = sleeps && p.onSleeping ? p.onSleeping : "";', js)
        self.assertNotIn("forDevice(", js, "the design is never made differently for one device")

    def test_the_clock_is_the_add_ons_own_in_your_12_or_24_hours(self):
        """Framework review #9: the Clock preset uses the time helper (binding show "now"), and the
        12/24-hour setting lives in Settings › Time and language (the user's call)."""
        els = run_js('console.log(JSON.stringify(P.presetById("clock").looks[0].make()))')
        self.assertEqual([(e.get("show"), e.get("format")) for e in els if e["type"] == "text"], [("now", "time"), ("now", "day_full")])
        self.assertFalse(any("strftime('%H" in str(e.get("value", "")) for e in els), "no 24-hour clock of its own")
        sheets = (APP_JS / "sheets.js").read_text()
        self.assertIn('time: ["Time and language", "clock", () => timePane(app, pane)],', sheets)
        self.assertIn('select([["auto", `As in Home Assistant (${word(r.resolved)} here)`], ["12h", "12-hour, like 2:30 PM"], ["24h", "24-hour, like 14:30"]]', sheets)
        self.assertIn('api("api/settings/time", { method: "PUT", body: { format: v } })', sheets)
        insp = (APP_JS / "inspector.js").read_text()
        self.assertIn('export const FROM = [["text", "Text"], ["sensor", "Sensor"], ["clock", "Time"], ["template", "Template"]];', (APP_JS / "shows.js").read_text())
        self.assertIn("seg(FROM, source,", insp)

    def test_sleeping_is_read_from_the_timers_not_the_kind(self):
        got = run_js("""console.log(JSON.stringify([{ timing: { always_on: false } }, { timing: { always_on: true } }, { kind: "trmnl", timing: { always_on: false } },
          { sleeps: true }, {}, null].map(P.sleepsBetweenUpdates)))""")
        self.assertEqual(got, [True, False, True, True, False, False])
        self.assertNotIn("trmnl", (APP_JS / "presets.js").read_text().split("export const sleepsBetweenUpdates", 1)[1].split("\n", 1)[0])

    def test_the_date_shows_no_time(self):
        els = run_js("console.log(JSON.stringify(P.DATE_LOOK.make()))")
        texts = [e["value"] for e in els if e["type"] == "text"]
        self.assertEqual(texts, ["{{ now().strftime('%A') }}", "{{ now().strftime('%-d %B %Y') }}"])
        self.assertFalse(run_js("console.log(JSON.stringify(P.DATE_LOOK.make().some(P.showsTime)))"))

    def test_the_date_fits_at_every_size(self):
        base = arrange.canvas_key(792, 272)
        page = {"elements": run_js("console.log(JSON.stringify(P.DATE_LOOK.make()))")}
        long = {0: "Wednesday", 1: "30 September 2026"}
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            placed = json.loads(json.dumps(page))
            for el in placed["elements"]:
                el.update(arrange.auto_box(el, base, arrange.canvas_key(d["w"], d["h"])))
            metrics = []
            layout.render_page(placed, long, metrics=metrics, display=key)
            with self.subTest(display=key):
                self.assertEqual([m for m in metrics if m.get("overflow")], [])

    def test_a_clock_page_turns_into_the_date_where_it_was(self):
        # The way back (kept off) knew 0.14's template clock; the preset now uses the add-on's own clock.
        # The 4.2" placement is the add-on's own (arrange.auto_box).
        base = [{"id": "e0", "x": 40, "y": 20, "w": 450, "h": 140, "size": 110}, {"id": "e1", "x": 44, "y": 168, "w": 500, "h": 46, "size": 36},
                {"id": "e2", "x": 620, "y": 40, "w": 120, "h": 120}]
        small = {e["id"]: arrange.auto_box(e, "792x272", "400x300") for e in base}
        got = run_js("const SMALL = " + json.dumps(small) + ";\n" + """const clock = [{ type: "text", value: "{{ now().strftime('%H:%M') }}", size: 110, bold: true, x: 40, y: 20, w: 450, h: 140, align: "left" },
            { type: "text", value: "{{ now().strftime('%A, %-d %B') }}", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46, align: "left" },
            { type: "icon", icon: "mdi:clock-outline", x: 620, y: 40, w: 120, h: 120 }].map((e, k) => ({ ...e, id: "e" + k }));
          const small = clock.map((e) => ({ ...e, ...SMALL[e.id] }));
          const mixed = [{ type: "text", id: "t", value: "{{ now().strftime('%I:%M %p') }}" }, { type: "number", id: "n", entity: "sensor.x" }];
          console.log(JSON.stringify([P.dateInstead(clock), P.dateInstead(small), P.dateInstead(mixed), P.clockPages({ a: { elements: clock }, b: { elements: mixed }, c: { elements: [] } })]))""")
        full, small, mixed, pages = got
        self.assertEqual([e["id"] for e in full], ["e0", "e1", "e2"], "each part keeps its ID, so its other sizes stay")
        self.assertEqual(full, [{**e, "id": f"e{k}"} for k, e in enumerate(run_js("console.log(JSON.stringify(P.DATE_LOOK.make()))"))])
        self.assertTrue(all(e["x"] + e["w"] <= 400 and e["y"] + e["h"] <= 268 for e in small), "a clock fitted to a 4.2\" stays on it")
        self.assertEqual(mixed, [{"type": "text", "id": "t", "value": "{{ now().strftime('%-d %B') }}"}, {"type": "number", "id": "n", "entity": "sensor.x"}])
        self.assertEqual(pages, ["a", "b"])

    def test_new_page_offers_the_date_on_a_sleeping_device(self):
        self.assertIn('id: "date", group: "day", title: "Date"', (APP_JS / "presets.js").read_text())
        # Switching a device to sleep changes no page: the renderer draws the date (test_clocktime).


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestNotedNeverHidden(unittest.TestCase):
    """The user's call (21 Oct): what changes faster than a sleeping device updates is noted with
    its interval, never hidden. One rule (presets.changesEvery), not a list of presets."""
    ASLEEP = {"timing": {"always_on": False, "update_minutes": 15}}

    def test_the_rule_finds_the_five(self):
        """The user's five, and Race weekend (live timing, framework review #6), from each widget's
        descriptor and the watts rule."""
        got = run_js("console.log(JSON.stringify(P.PRESETS.filter((p) => P.presetChangesEvery(p) != null).map((p) => p.title)))")
        self.assertEqual(sorted(got), sorted(["Planes overhead", "Now playing", "Scores", "Race weekend", "Grid now", "Battery and solar"]))
    def test_the_line_names_the_devices_own_interval(self):
        got = run_js(f"""const asleep = {json.dumps(self.ASLEEP)};
          console.log(JSON.stringify([P.staleNote(1, asleep), P.staleNote(1, asleep, {{ short: true }}),
            P.staleNote(1, {{ timing: {{ always_on: false, update_minutes: 120 }} }}), P.staleNote(1, {{ timing: {{ always_on: true, update_minutes: 1 }} }}),
            P.staleNote(null, asleep)]))""")
        self.assertEqual(got, ["Changes faster than this device updates (every 15 min), so it can be up to 15 min old.",
                               "Up to 15 min old here",
                               "Changes faster than this device updates (every 2 hours), so it can be up to 2 hours old.", "", ""])

    def test_watts_are_now_watt_hours_are_not(self):
        got = run_js("""const ents = new Map([["sensor.load", { unit: "kW" }], ["sensor.today", { unit: "kWh" }]]);
          console.log(JSON.stringify([{ type: "number", entity: "sensor.load" }, { type: "number", entity: "sensor.today" }, { type: "bar", suffix: " W" },
            { type: "flight_tracker" }, { type: "weather_forecast" }, { type: "text", value: "Hello" }].map((e) => P.changesEvery(e, ents))))""")
        self.assertEqual(got, [1, None, 1, 1, None, None])

    def test_a_widget_is_live_as_its_descriptor_says(self):
        """widgets-015's descriptors give only what really changes (a calendar's fetch isn't one), so the
        editor takes them as they are: a Weather is live with your own station, a forecast alone isn't."""
        got = run_js("""console.log(JSON.stringify([{ type: "weather_forecast" }, { type: "weather_forecast", wind_sensor: "sensor.wind" },
            { type: "calendar_agenda" }, { type: "todo_list" }, { type: "now_playing" }].map((e) => P.changesEvery(e, new Map()))))""")
        self.assertEqual(got, [None, 1, None, None, 1])
        self.assertNotIn("s >= 60", (APP_JS / "catalog.js").read_text(), "no cutoff of its own")

    def test_a_sensor_changes_as_the_entity_list_says(self):
        """/api/entities says how often each sensor changes (widgets.sensor_changes_every); the editor
        reads it, and falls back to the unit only for a sensor the list doesn't know."""
        got = run_js("""const ents = new Map([["sensor.wind", { unit: "km/h", changes_every: 60 }], ["sensor.meter", { unit: "kW", changes_every: null }],
            ["sensor.slow", { unit: "W", changes_every: 900 }]]);
          console.log(JSON.stringify(["sensor.wind", "sensor.meter", "sensor.slow", "sensor.gone"].map((entity) => P.changesEvery({ type: "number", entity, suffix: " W" }, ents))))""")
        self.assertEqual(got, [1, None, 15, 1])

    def test_shown_in_the_sheet_and_the_inspector_not_hidden(self):
        js = (APP_JS / "newpage.js").read_text()
        self.assertIn("const stale = staleNote(presetChangesEvery(p), app.screen, { short: true });", js)
        self.assertIn("const stale = staleNote(presetChangesEvery(p), app.screen);", (APP_JS / "setup.js").read_text())
        insp = (APP_JS / "inspector.js").read_text()
        self.assertIn("staleNote(pageChangesEvery(p.elements, app.entMap), app.screen)", insp)
        self.assertIn("staleNote(changesEvery(el, app.entMap), app.screen)", insp)
        self.assertNotIn("presetChangesEvery(p) != null && sleeps", js, "never filtered out")


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestUnitsAreTheSensors(unittest.TestCase):
    """Framework review #1: a preset never writes a unit; a °F home reads °F, a Wh meter Wh."""
    UNITS = ("°C", "°F", "K", "kWh", "Wh", "MWh", "W", "kW", "%")

    def made(self, unit):
        return run_js(f"""const unitOf = () => {json.dumps(unit)};
          const parts = {{ battery: "sensor.a", load: "sensor.b", solar: "sensor.c" }};
          console.log(JSON.stringify(P.PRESETS.flatMap((p) => p.looks.map((l) => [l.id,
            P.pageFor(p, l, "sensor.picked", p.needs === "parts" ? parts : undefined, unitOf).elements]))))""")

    def test_every_value_shows_its_sensors_unit(self):
        for unit in ("°F", "Wh"):
            for look, els in self.made(unit):
                for el in els:
                    if el.get("type") in ("number", "bar") and str(el.get("entity", "")).startswith("sensor.") and el.get("show", "state") == "state":
                        with self.subTest(look=look, unit=unit):
                            # It follows the sensor at every render (review 2 #3), never a copy of today's unit.
                            self.assertEqual((el.get("unit"), el.get("suffix")), ("entity", None))

    def test_none_when_the_sensor_has_none(self):
        for look, els in self.made(""):
            for el in els:
                self.assertNotIn(el.get("suffix", "").strip(), self.UNITS, look)

    def test_no_preset_writes_a_unit_of_its_own(self):
        src = (APP_JS / "presets.js").read_text()
        looks = src.split("export const PRESETS", 1)[1].split("/* Guest Wi-Fi", 1)[0]
        for unit in self.UNITS:
            self.assertNotIn(f'suffix: " {unit}"', looks)
            self.assertNotIn(f'suffix: "{unit}"', looks)

    def test_changing_a_values_sensor_changes_its_unit(self):
        src = (APP_JS / "inspector.js").read_text()
        self.assertIn('if (el.type === "number" && el.unit !== "entity" && (!mine || mine === was)) { el.unit = "entity"; delete el.suffix; }', src,
                      "it follows the new sensor; your own words stay")

    def test_a_power_gauge_follows_its_unit(self):
        got = run_js("""console.log(JSON.stringify(["W", "kW"].map((u) => P.withUnits([{ type: "bar", entity: "sensor.x", unit: "entity", max_val: "power" }], () => u)[0])))""")
        self.assertEqual([(g["max_val"], g["unit"]) for g in got], [(5000, "entity"), (5, "entity")])

    def test_the_examples_units_are_the_example_sensors(self):
        states = json.loads((support.APP / "render" / "fixture.json").read_text())["states"]
        units = run_js("console.log(JSON.stringify(P.EXAMPLE_UNITS))")
        for ent, unit in units.items():
            if ent in states:
                self.assertEqual(states[ent].get("unit"), unit, ent)


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestBatteryAndSolarAsksForEachPart(unittest.TestCase):
    """Framework review #4: every part it shows is asked for, the Energy dashboard's first."""

    def test_three_parts_and_each_lands_in_its_place(self):
        got = run_js("""const p = P.presetById("energy_gauges");
          console.log(JSON.stringify([p.needs, p.parts.map((x) => x.key), P.pageFor(p, p.looks[0], "", { battery: "sensor.b", load: "sensor.l", solar: "sensor.s" }).elements.map((e) => e.entity || null)]))""")
        needs, keys, ents = got
        self.assertEqual((needs, keys), ("parts", ["battery", "load", "solar"]))
        self.assertEqual([e for e in ents if e], ["sensor.b", "sensor.l", "sensor.s"])

    def test_the_dashboards_solar_power_first(self):
        roles = run_js("""console.log(JSON.stringify(P.energyRoles({ solar: [{ energy: "sensor.pv_kwh", power: "sensor.pv_w" }] })))""")
        self.assertEqual(roles["solar_power"], ["sensor.pv_w"])
        ents = [{"entity_id": "sensor.other_w", "unit": "W", "device_class": "power"}, {"entity_id": "sensor.pv_w", "unit": "W", "device_class": "power"}]
        first = run_js(f"""const p = P.presetById("energy_gauges"), part = p.parts.find((x) => x.key === "solar");
          console.log(JSON.stringify(P.rankSensors({{ asks: "sensor", prefer: part.prefer }}, {json.dumps(ents)}, {json.dumps(roles)})[0]))""")
        self.assertEqual((first["e"]["entity_id"], first["tag"]), ("sensor.pv_w", "From your Energy dashboard"))

    def test_asked_in_place(self):
        self.assertIn("parts: partsSetup", (APP_JS / "setup.js").read_text())


class TestAGaugeNeverMakesUpAValue(unittest.TestCase):
    """The user saw "House power 68%" for a gauge with no sensor: the renderer drew a made-up 68,
    and a gauge with no unit added its own "%"."""
    BAR = {"type": "bar", "title": "HOUSE POWER", "min_val": 0, "max_val": 5000, "show_label": True, "x": 34, "y": 152, "w": 324, "h": 64}

    def drawn(self, el, vals):
        from unittest import mock
        from PIL import ImageDraw
        said, real = [], ImageDraw.ImageDraw.text
        def spy(self_, xy, text, *a, **kw):
            said.append(text)
            return real(self_, xy, text, *a, **kw)
        with mock.patch.object(ImageDraw.ImageDraw, "text", spy):
            layout.render_page({"elements": [el]}, vals)
        return said

    def test_no_sensor_no_number(self):
        said = self.drawn({**self.BAR, "entity": "", "suffix": ""}, {})
        self.assertIn("HOUSE POWER", said)
        self.assertFalse([t for t in said if "68" in t or "%" in t], said)

    def test_its_own_unit_and_decimals(self):
        said = self.drawn({**self.BAR, "entity": "sensor.house", "suffix": " kW", "decimals": 1, "max_val": 5}, {0: "1.84"})
        self.assertIn("1.8 kW", said)
        said = self.drawn({**self.BAR, "entity": "sensor.house", "suffix": ""}, {0: "640"})
        self.assertIn("640", said, "no unit stays no unit, not %")


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestStatusSpeaksTheSensorsKind(unittest.TestCase):
    """Framework review #2: Status uses Home Assistant's words and icon for the picked sensor's kind
    (the catalog's state table, render/states.py), editable after."""

    def page(self, ent, device_class):
        return run_js(f"""const p = P.presetById("status");
          console.log(JSON.stringify(P.pageFor(p, p.looks[0], {json.dumps(ent)}, undefined, () => ({{ device_class: {json.dumps(device_class)} }})).elements))""")

    def test_by_device_class_then_domain(self):
        from render import states
        cat = states.catalog()
        for ent, dc in (("binary_sensor.front_door", "door"), ("binary_sensor.hall", "motion"), ("switch.guest_mode", ""), ("lock.front", ""), ("person.sam", "")):
            icon, text = self.page(ent, dc)[:2]
            words = cat.get(f"{ent.split('.')[0]}.{dc}") or cat[ent.split(".")[0]]
            with self.subTest(entity=ent):
                self.assertEqual(text["replace"], {k: v["word"] for k, v in words.items()})
                self.assertEqual(icon["state_icons"], {k: v["icon"] for k, v in words.items() if v.get("icon")})
                self.assertNotIn("words", text)
        self.assertEqual(self.page("binary_sensor.hall", "motion")[1]["replace"]["on"], "Detected", "never \"Open\" for motion")
        self.assertEqual(self.page("switch.guest_mode", "")[1]["replace"]["on"], "On")

    def test_its_thumbnail_is_a_doors(self):
        els = run_js('const p = P.presetById("status"); console.log(JSON.stringify(P.examplePage(p, p.looks[0]).elements))')
        self.assertEqual(els[1]["replace"]["on"], "Open")


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestUprightAsksWhatShowsTheTime(unittest.TestCase):
    """Framework review #11: turning a page upright arranges a clock as a clock by the add-on's
    answer (render/clocktime.times, POST /api/shows-time, the render's shows_time), not a string
    match of the editor's own."""

    def test_the_clock_preset_upright(self):
        from render import clocktime
        page = {"elements": run_js('console.log(JSON.stringify(P.presetById("clock").looks[0].make()))')}
        times = clocktime.times(page)
        self.assertEqual(times, [0], "the add-on's own clock (show now) is a time")
        got = run_js(f"""const page = {{ elements: {json.dumps(page["elements"])} }};
          L.reflowPageElements(page, true, {{ portrait: {{ w: 272, h: 792, band: 36, margin: 12 }}, landscape: {{ w: 792, h: 272, band: 32, margin: 12 }} }}, {json.dumps(times)});
          console.log(JSON.stringify(page.elements[0]))""")
        self.assertEqual((got["align"], got["bold"]), ("center", True))
        self.assertLessEqual(got["size"], 76, "laid out as the clock it is")

    def test_no_detector_of_its_own(self):
        src = (APP_JS / "legacy.js").read_text()
        self.assertNotIn('"%H:%M"', src)
        self.assertIn("const times = (app.canvas.metrics || []).filter((m) => m.shows_time).map((m) => m.i);", (APP_JS / "sheets.js").read_text())
        self.assertIn('api("api/shows-time", { method: "POST", body: { page } })', (APP_JS / "newpage.js").read_text())


class TestTheSheet(unittest.TestCase):
    """New page's wiring and look, pinned in its source."""

    def setUp(self):
        self.js = (APP_JS / "newpage.js").read_text()

    def test_preset_thumbnails_are_examples_never_your_data(self):
        self.assertIn('api(job.example ? "api/example" : "api/preview"', (APP_JS / "strip.js").read_text())
        self.assertIn('thumb(app, `preset:${look.id}:example`, examplePage(p, look), { example: true })', self.js)
        self.assertNotIn("guess(app", self.js, "no longer drawn from a guessed sensor (the -- bug)")

    def test_it_is_the_new_page_sheet(self):
        self.assertIn('import { openPresets } from "./newpage.js";', (APP_JS / "main.js").read_text())

    def test_the_old_grid_is_kept_as_the_way_back(self):
        self.assertIn("export function openPresetsGrid(app)", (APP_JS / "sheets.js").read_text())

    def test_blank_page_is_pinned_in_the_footer_tinted(self):
        self.assertIn('h("button", { class: "btn tinted blankbtn"', self.js)
        self.assertIn('const foot = h("div", { class: "sheet-foot" }, blank,', self.js)

    def test_each_shelf_counts_its_presets(self):
        self.assertIn('h("span", { class: "count", "aria-hidden": "true", text: `(${cards.length})` })', self.js)
        self.assertIn('"aria-label": `${name}, ${cards.length} ${cards.length === 1 ? "preset" : "presets"}`', self.js, "and said aloud")

    def test_a_card_stays_a_button_to_voiceover(self):
        self.assertIn('h("div", { role: "listitem" }, c)', self.js)

    def test_your_own_get_a_shelf_first_when_you_have_some(self):
        self.assertIn('mine.length ? shelf("yours", "Yours", mine.map(ownCard)) : null,', self.js)

    def test_arrows_on_hover_only_towards_more(self):
        arrow = next(b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if s.strip() == ".arrow")
        self.assertIn("opacity: 0", arrow)
        hover = re.search(r"@media \(hover: hover\) \{\s*([^{}]+)\{([^{}]*)\}", CSS[CSS.index(".slider"):])
        self.assertIn(".slider:not(.vertical).more-l:is(:hover, :focus-within) > .arrow.l", hover.group(1))
        self.assertIn(".slider:not(.vertical).more-r:is(:hover, :focus-within) > .arrow.r", hover.group(1))
        self.assertIn("opacity: 1", hover.group(2))
        self.assertRegex(CSS, r"@media \(hover: none\) \{ \.arrow \{ display: none; \} \}")

    def test_the_edge_fades_while_there_is_more_under_the_arrow_too(self):
        self.assertIn(".slider.more-l > .slides { --fl: var(--fade); }", CSS)
        self.assertIn(".slider.more-r > .slides { --fr: var(--fade); }", CSS)
        self.assertIn("mask-image: linear-gradient(to right, transparent 0, #000 var(--fl), #000 calc(100% - var(--fr)), transparent 100%)", CSS)
        self.assertIn("transition: --fl var(--t) var(--spring), --fr var(--t) var(--spring);", CSS)

    def test_the_page_strip_has_three_sizes(self):
        # The user's call, 21 Oct: Small is the old Standard, Standard the old Large, Large is new.
        sheets = (APP_JS / "sheets.js").read_text()
        self.assertIn('grow("Page strip size", "How large its pages are", select([["small", "Small"], ["standard", "Standard"], ["large", "Large"]], app.stripSize(), (v) => { app.prefs.set("page_strip_size", v);', sheets)
        self.assertIn("#app { --tile-w: 248px; --side-w: 300px; }", CSS)
        self.assertIn('#app[data-stripsize="small"] { --tile-w: 188px; --side-w: 240px; }', CSS)
        self.assertIn('#app[data-stripsize="large"] { --tile-w: 320px; --side-w: 372px; }', CSS)
        self.assertIn(".tile { flex: none; width: var(--tile-w);", CSS)
        self.assertIn(".stripfront { flex: none; width: min(var(--tile-w), 188px);", CSS)
        self.assertIn("this.el.app.dataset.stripsize = this.stripSize();", (APP_JS / "main.js").read_text())

    def test_a_size_chosen_before_keeps_its_look(self):
        main = (APP_JS / "main.js").read_text()
        body = main[main.index("  stripSize() {"):]
        self.assertIn('v = old ? "small" : "standard";', body, "every old size is nearest the new Small")
        self.assertIn('if (old) prefs.set("page_strip_size", v);', body)
        self.assertNotIn('prefs.set("strip_size"', main + (APP_JS / "sheets.js").read_text(), "the old choice stays for an older editor")

    def test_the_small_size_holds_two_buttons_in_the_last_third(self):
        """The user's call, 21 Oct: the sizes grew so the last third of the widest picture holds two."""
        widest = max(T.DISPLAYS.values(), key=lambda d: d["w"] / d["h"])
        small = int(re.search(r'#app\[data-stripsize="small"\] \{ --tile-w: (\d+)px', CSS).group(1))
        self.assertGreaterEqual(small / (widest["w"] / widest["h"]) / 2, 32, "each button at least 32 px tall")
        self.assertGreaterEqual(small / 3, 44, "and a third at least 44 wide")

    def test_duplicate_and_delete_on_its_picture(self):
        """Two buttons over the picture (the user's design, 21 Oct): Duplicate, and Delete, which
        offers Delete page or Take out of rotation. Over the last third, or across the bottom half
        (a setting for each strip size). 44 pt to touch at every size."""
        strip = (APP_JS / "strip.js").read_text()
        self.assertIn('style: { aspectRatio: `${g.W} / ${g.H}` } }, dup, del);', strip, "over the picture, not the name under it")
        self.assertIn("app.duplicatePage(n)", strip)
        self.assertIn("app.openDeleteMenu(n, del, slot)", strip)
        self.assertNotIn("openPageMenu(ev, n, more)", strip, "no menu button: the right-click keeps the fuller list")
        self.assertIn("timer = setTimeout(() => {", strip.split("function holdToReveal", 1)[1], "a hold shows them on a touch screen")
        self.assertIn('if (!drag) { if (it.dataset.held) delete it.dataset.held; else onOpen(idx); return; }', strip, "and the hold doesn't open the page")
        self.assertIn('.tileact::before { content: ""; position: absolute; right: 0; width: max(100%, 44px); height: max(100%, 44px); }', CSS)
        self.assertIn(".tileact.dup::before { bottom: 0; }", CSS, "Duplicate's tap area reaches up")
        self.assertIn(".tileact.del::before { top: 0; }", CSS, "Delete's down, so they never overlap")
        self.assertIn('#app[data-tilebuttons="half"] .tileacts { grid-template-columns: 1fr 1fr;', CSS)
        self.assertIn("pointer-events: none;", re.search(r"\.tileacts \{([^}]*)\}", CSS).group(1), "the picture under them still opens the page")
        self.assertIn("@media (hover: hover) {\n  .tilebox:hover .tileacts, .tilebox:focus-within .tileacts { opacity: 1;", CSS)

    def test_a_hold_on_a_phone_is_ours_not_the_photo_menus(self):
        # iOS offered Save to Photos on a held thumbnail, over the page's buttons (the user, 21 Oct).
        self.assertIn(".thumb, .tile, .tileact { -webkit-touch-callout: none; -webkit-user-select: none; user-select: none; }", CSS)
        strip = (APP_JS / "strip.js").read_text()
        self.assertIn("if (!t.dataset.touched) app.openPageMenu(e, n);", strip, "nor Android's long-press menu")
        self.assertIn('if (e.pointerType !== "touch") { delete t.dataset.touched; return; }', strip, "a mouse's right-click still opens it")

    def test_delete_is_a_choice_not_a_question(self):
        main = (APP_JS / "main.js").read_text()
        menu = main[main.index("  openDeleteMenu(n, anchor, slot) {"):main.index("  takeOut(n, slot) {")]
        self.assertIn('"Take out of rotation"', menu)
        self.assertIn('{ label: "Delete page", icon: "trash", danger: true, run: () => this.deletePage(n) }', menu)
        take = main[main.index("  takeOut(n, slot) {"):main.index("  tileButtons(")]
        self.assertIn('{ label: "Undo", run: () => doc.undo() }', take)
        self.assertIn("r[slot] === n ? slot : r.lastIndexOf(n)", take, "the place in the rotation that tile is")

    def test_where_the_buttons_sit_is_kept_for_each_size(self):
        main = (APP_JS / "main.js").read_text()
        self.assertIn('return prefs.get("tile_buttons_" + size) === "half" ? "half" : "third";', main)
        self.assertIn("this.el.app.dataset.tilebuttons = this.tileButtons();", main)
        sheets = (APP_JS / "sheets.js").read_text()
        self.assertIn('app.prefs.set("tile_buttons_" + app.stripSize(), v)', sheets)
        self.assertIn("buttons.value = app.tileButtons();", sheets, "changing the size shows that size's choice")

    def test_one_slider_for_the_shelves_and_the_page_strip(self):
        self.assertIn("const wrap = slider(row, { name });", self.js)
        strip = (APP_JS / "strip.js").read_text()
        self.assertIn('strip.append(slider(list, { name: "the pages", vertical: () => app.stripVertical() }));', strip)
        self.assertIn(".slider.vertical > .slides {", CSS, "down the side it fades top and bottom")
        self.assertIn(".slider.still > .slides { transition: none; }", CSS, "a strip drawn again doesn't fade in each time")
        self.assertIn('n.closest(".slider")?.sync();', (APP_JS / "main.js").read_text())
        self.assertIn('#app[data-strip="side"] .strip > .slider { flex: 1 1 0; min-height: 0; flex-direction: column;', CSS, "down the side, the column scrolls")

    def test_phones_swipe(self):
        row = next(b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if s.strip() == ".row")
        self.assertIn("overflow-x: auto", row)
        self.assertIn("scroll-snap-type: x mandatory", row)

    def test_smooth_only_without_reduce_motion(self):
        self.assertIn("@media (prefers-reduced-motion: no-preference) { .row { scroll-behavior: smooth; } }", CSS)

    def test_keyboard_moves_along_a_shelf_and_esc_goes_back(self):
        self.assertIn('if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;', self.js)
        self.assertIn('if (e.key === "Escape" && step && !e.target.closest?.("[data-own-esc]")) { e.preventDefault(); e.stopImmediatePropagation(); leave(); }', self.js)

    def test_title_shelves_and_footer_start_on_one_line(self):
        self.assertIn(".npsheet .sheet-head { padding-left: var(--gutter); }", CSS)
        self.assertIn(".npsheet .sheet-foot { padding-inline: var(--gutter); }", CSS)

    def test_close_stays_at_the_edge_in_a_step_on_a_phone(self):
        self.assertIn(".npsheet.stepping .sheet-head h2 { flex: 1; max-width: none; }", CSS)
        self.assertIn('node.classList.add("stepping")', self.js)

    def test_no_stray_null_on_screen(self):
        """replaceChildren() writes a null as the word "null": what's left out is filtered first."""
        for name in ("newpage.js", "setup.js"):
            src = (APP_JS / name).read_text()
            for call in calls(src, ".replaceChildren("):
                for arg in top_level(call):
                    self.assertFalse(re.search(r":\s*null\s*$", arg.strip()), f"{name}: {arg.strip()[:80]}")

    def test_the_sheets_styles_stay_the_sheets(self):
        """.npsheet is New page's sheet; .newpage is the strip's New page button and the pickers' row.
        A rename once reached both, and New page down the side shrank to 5 px."""
        self.assertIn('#app[data-strip="side"] .stathead, #app[data-strip="side"] .newpage { flex: none; min-height: 40px; }', CSS)
        self.assertIn(".opt.newpage {", CSS)
        self.assertNotIn(".opt.npsheet", CSS)
        self.assertNotRegex(CSS, r'data-strip="side"\] \.npsheet')

    def test_the_shelves_never_widen_the_sheet(self):
        self.assertIn(".shelfbody > * { min-width: 0; }", CSS)
        self.assertNotRegex(CSS, r"(^|\})\s*\.newpage \.(row|shelf|pbtn)", "the strip's New page button owns .newpage")


if __name__ == "__main__":
    unittest.main()
