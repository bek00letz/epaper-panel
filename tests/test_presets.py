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
from render import todo
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

    def test_the_shelves_never_widen_the_sheet(self):
        self.assertIn(".shelfbody > * { min-width: 0; }", CSS)
        self.assertNotRegex(CSS, r"(^|\})\s*\.newpage \.(row|shelf|pbtn)", "the strip's New page button owns .newpage")


if __name__ == "__main__":
    unittest.main()
