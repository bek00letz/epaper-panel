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


def run_js(body):
    script = (f"import * as P from {json.dumps(str(APP_JS / 'presets.js'))};"
              f"import * as L from {json.dumps(str(APP_JS / 'legacy.js'))};\n{body}")
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
        self.assertEqual(self.by_id["planes"]["group"], "outside")
        self.assertEqual(self.by_id["weather_forecast"]["group"], "outside")

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
          .map((q) => P.PRESETS.filter((p) => P.matches(p, q)).map((p) => p.id))));""")
        self.assertEqual(found, [["status"], ["dynamic_status"], ["race_weekend"], ["race_weekend"], ["planes"], ["match"], ["to_do"]])

    def test_every_league_and_series_the_add_on_fetches(self):
        leagues = run_js("console.log(JSON.stringify(P.LEAGUES.map(([l]) => l)))")
        self.assertEqual(set(leagues), {k for k in sports.LEAGUE_SLUGS if "/" in k})
        series = run_js("console.log(JSON.stringify(P.SERIES.map(([s]) => s)))")
        self.assertEqual(sorted({racing.series_slug(s)[0] for s in series}), sorted(series), "each series names its own sensor")

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
            self.assertEqual(look["page"]["show_if"], "{{ states('sensor.epaper_flights_overhead') | int(0) > 0 }}")
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

    def test_placed_on_another_size_as_the_add_on_places_a_design(self):
        """The editor's fit (presets.fitToCanvas) is arrange.auto_box, so a new page sits where the add-on would put it."""
        base = arrange.canvas_key(792, 272)
        el = {"type": "text", "x": 132, "y": 94, "w": 400, "h": 64, "size": 22}
        for key, d in T.DISPLAYS.items():
            if d.get("offered") is False:
                continue
            w, h = d["w"], d["h"]
            g = {"W": w, "H": h, "safeH": h - T.band_height(h), "portrait": False}
            got = run_js(f"console.log(JSON.stringify(P.fitToCanvas([{json.dumps(el)}], {json.dumps(g)})[0]))")
            want = {**el, **arrange.auto_box(el, base, arrange.canvas_key(w, h))}
            with self.subTest(display=key):
                self.assertEqual(got, want)


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
        self.assertIn("const SETUPS = { wifi: wifiSetup, jellyfin: jellyfinSetup", self.js)

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


class TestTheSheet(unittest.TestCase):
    """New page's wiring and look, pinned in its source."""

    def setUp(self):
        self.js = (APP_JS / "newpage.js").read_text()

    def test_it_is_the_new_page_sheet(self):
        self.assertIn('import { openPresets } from "./newpage.js";', (APP_JS / "main.js").read_text())

    def test_the_old_grid_is_kept_as_the_way_back(self):
        self.assertIn("export function openPresetsGrid(app)", (APP_JS / "sheets.js").read_text())

    def test_blank_page_is_pinned_in_the_footer_tinted(self):
        self.assertIn('h("button", { class: "btn tinted blankbtn"', self.js)
        self.assertIn('const foot = h("div", { class: "sheet-foot" }, blank,', self.js)

    def test_each_shelf_counts_its_presets(self):
        self.assertIn('h("span", { class: "count", "aria-label": `${cards.length} presets`, text: `(${cards.length})` })', self.js)

    def test_your_own_get_a_shelf_first_when_you_have_some(self):
        self.assertIn('mine.length ? shelf("yours", "Yours", mine.map(ownCard)) : null,', self.js)

    def test_arrows_on_hover_only_towards_more(self):
        arrow = next(b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if s.strip() == ".arrow")
        self.assertIn("opacity: 0", arrow)
        hover = re.search(r"@media \(hover: hover\) \{\s*([^{}]+)\{([^{}]*)\}", CSS)
        self.assertIn(".rowwrap.more-l:is(:hover, :focus-within) .arrow.l", hover.group(1))
        self.assertIn(".rowwrap.more-r:is(:hover, :focus-within) .arrow.r", hover.group(1))
        self.assertIn("opacity: 1", hover.group(2))
        self.assertRegex(CSS, r"@media \(hover: none\) \{ \.arrow \{ display: none; \} \}")

    def test_the_edge_fades_while_there_is_more_under_the_arrow_too(self):
        self.assertIn(".rowwrap.more-l .row { --fl: var(--fade); }", CSS)
        self.assertIn(".rowwrap.more-r .row { --fr: var(--fade); }", CSS)
        self.assertIn("mask-image: linear-gradient(to right, transparent 0, #000 var(--fl), #000 calc(100% - var(--fr)), transparent 100%)", CSS)
        self.assertIn("transition: --fl var(--t) var(--spring), --fr var(--t) var(--spring);", CSS)

    def test_phones_swipe(self):
        row = next(b for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if s.strip() == ".row")
        self.assertIn("overflow-x: auto", row)
        self.assertIn("scroll-snap-type: x mandatory", row)

    def test_smooth_only_without_reduce_motion(self):
        self.assertIn("@media (prefers-reduced-motion: no-preference) { .row { scroll-behavior: smooth; } }", CSS)

    def test_keyboard_moves_along_a_shelf_and_esc_goes_back(self):
        self.assertIn('if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;', self.js)
        self.assertIn('if (e.key === "Escape" && step) { e.preventDefault(); e.stopImmediatePropagation(); leave(); } }, true);', self.js)

    def test_title_shelves_and_footer_start_on_one_line(self):
        self.assertIn(".npsheet .sheet-head { padding-left: var(--gutter); }", CSS)
        self.assertIn(".npsheet .sheet-foot { padding-inline: var(--gutter); }", CSS)

    def test_close_stays_at_the_edge_in_a_step_on_a_phone(self):
        self.assertIn(".npsheet.stepping .sheet-head h2 { flex: 1; max-width: none; }", CSS)
        self.assertIn('node.classList.add("stepping")', self.js)

    def test_the_shelves_never_widen_the_sheet(self):
        self.assertIn(".shelfbody > * { min-width: 0; }", CSS)
        self.assertNotRegex(CSS, r"(^|\})\s*\.newpage \.(row|shelf|pbtn)", "the strip's New page button owns .newpage")


if __name__ == "__main__":
    unittest.main()
