"""The screen speaks Home Assistant's language (render/words.py, render/words_table.py).

Every word the add-on draws comes from one table, looked up one way, with English for a word a
language doesn't have yet; dates and numbers are written the language's way; the longest words
still fit every page at every size offered."""
import asyncio
import re
import string
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import support  # noqa: F401

from render import arrange, binding, clock, countdown, layout, race, sleep, sport, theme as T, todo, words
from render.words import say, speaking
from render.words_table import WORDS

APP = Path(support.APP)
TZ = ZoneInfo("Europe/Bucharest")
AT = datetime(2026, 10, 21, 14, 5, tzinfo=TZ)            # a Wednesday
OTHERS = [lang for lang in words.LANGUAGES if lang != "en"]
OFFERED = [(key, 0) for key, d in T.DISPLAYS.items() if d.get("offered") is not False] + [("crowpanel_420", 90)]


class TestTheTable(unittest.TestCase):
    def test_every_word_is_in_every_language(self):
        # The missing-word check: a language without a word says it in English meanwhile; this lists them.
        self.assertEqual(words.missing(), {lang: [] for lang in words.LANGUAGES})

    def test_each_language_fills_the_same_blanks(self):
        def blanks(text):
            forms = text.values() if isinstance(text, dict) else [text]
            return {f for t in forms for _, f, _, _ in string.Formatter().parse(t) if f} - {"n"}
        for key, row in WORDS.items():
            for lang, text in row.items():
                with self.subTest(key=key, lang=lang):
                    if isinstance(text, dict):
                        self.assertIn("other", text, "a count's text has its 'other' form")
                    # The count itself may be said in words ("Peste o zi"); every other blank is English's.
                    self.assertEqual(blanks(text), blanks(row["en"]))

    def test_every_word_the_add_on_says_is_in_the_table(self):
        said = set()
        for path in APP.rglob("*.py"):
            for m in re.finditer(r"""\bsay\(\s*["']([a-z_][\w.\- ]*)["']""", path.read_text()):
                said.add(m.group(1))
        self.assertTrue(said)
        self.assertEqual(sorted(k for k in said if k not in WORDS), [])

    def test_no_date_is_written_by_the_systems_locale(self):
        # Month and day names come from the table (clock.strftime), never Python's own %a %b.
        leaks = []
        allowed = {"render/clock.py", "render/words_table.py", "render/binding.py", "fixture.py"}
        for path in APP.rglob("*.py"):
            rel = path.relative_to(APP).as_posix()
            if rel in allowed or "firmware" in rel:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"""(:%[aAbBp][^"']*\}|(?<!clock)\.strftime\(\s*["'][^"']*%[aAbBp]|calendar\.(month|day)_(name|abbr))""", code):
                    leaks.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(leaks, [])


class TestLookingUp(unittest.TestCase):
    def test_a_word_in_each_language(self):
        got = {}
        for lang in words.LANGUAGES:
            with speaking(lang):
                got[lang] = say("day.tomorrow")
        self.assertEqual(got, {"en": "Tomorrow", "ro": "Mâine", "es": "Mañana", "de": "Morgen", "fr": "Demain"})

    def test_outside_a_device_it_is_english(self):
        self.assertEqual(words.language(), "en")
        self.assertEqual(say("todo.overdue"), "Overdue")

    def test_home_assistants_language_tag_picks_it(self):
        self.assertEqual([words.resolve(t) for t in ("de", "de-CH", "fr_CA", "RO", "es-419", "en-GB")],
                         ["de", "de", "fr", "ro", "es", "en"])
        self.assertEqual([words.resolve(t) for t in ("it", "pt-BR", "", None)], ["en"] * 4, "one we don't have: English")

    def test_a_missing_word_is_said_in_english(self):
        WORDS["test.only_english"] = {"en": "Only in English"}
        try:
            with speaking("de"):
                self.assertEqual(say("test.only_english"), "Only in English")
            self.assertIn("test.only_english", words.missing()["de"])
        finally:
            del WORDS["test.only_english"]

    def test_counts_take_their_languages_plural(self):
        def days(lang, n):
            with speaking(lang):
                return say("day.days", n)
        self.assertEqual([days("en", n) for n in (1, 2)], ["1 day", "2 days"])
        self.assertEqual([days("ro", n) for n in (1, 3, 19, 20, 101, 102, 120)],
                         ["1 zi", "3 zile", "19 zile", "20 de zile", "101 zile", "102 zile", "120 de zile"])
        self.assertEqual([days("fr", n) for n in (0, 1, 2)], ["0 jour", "1 jour", "2 jours"])
        self.assertEqual(days("de", 2), "2 Tage")

    def test_each_device_speaks_its_own_at_once(self):
        # Two devices drawn at the same time (the render cycle and an editor preview) don't mix.
        async def device(lang, out):
            with speaking(lang):
                await asyncio.sleep(0)
                out[lang] = say("day.today")
        out = {}

        async def both():
            await asyncio.gather(device("de", out), device("fr", out), asyncio.to_thread(lambda: out.setdefault("en", say("day.today"))))
        asyncio.run(both())
        self.assertEqual(out, {"de": "Heute", "fr": "Aujourd’hui", "en": "Today"})


class TestDatesAndNumbers(unittest.TestCase):
    def written(self, kind, country=""):
        out = {}
        for lang in words.LANGUAGES:
            with speaking(lang, country):
                out[lang] = clock.date(AT, kind)
        return out

    def test_a_full_date_in_each_language(self):
        self.assertEqual(self.written("day_full"), {
            "en": "Wednesday, 21 October", "ro": "miercuri, 21 octombrie", "es": "miércoles, 21 de octubre",
            "de": "Mittwoch, 21. Oktober", "fr": "mercredi 21 octobre"})

    def test_a_short_date_in_each_language(self):
        self.assertEqual(self.written("short_day_date"), {
            "en": "Wed 21 Oct", "ro": "mie. 21 oct.", "es": "mié 21 oct", "de": "Mi. 21. Okt.", "fr": "mer. 21 oct."})

    def test_american_english_puts_the_month_first(self):
        with speaking("en", "US"):
            self.assertEqual((clock.date(AT, "date"), clock.date(AT, "day_full")), ("Oct 21", "Wednesday, October 21"))

    def test_the_12_hour_setting_still_wins(self):
        clock.use(True)
        try:
            with speaking("de"):
                self.assertEqual(clock.hm(AT), "2:05 PM")
            with speaking("es"):
                self.assertEqual(clock.hm(AT), "2:05 p. m.")
        finally:
            clock.use(False)
        with speaking("de"):
            self.assertEqual(clock.hm(AT), "14:05")

    def test_decimal_commas_and_grouping(self):
        got = {}
        for lang in words.LANGUAGES:
            with speaking(lang):
                got[lang] = (words.number(21.5, 1), words.number(10370, 0, group=True), words.number(1234, 0, group=True))
        self.assertEqual(got, {"en": ("21.5", "10,370", "1,234"), "ro": ("21,5", "10.370", "1.234"),
                               "es": ("21,5", "10.370", "1234"), "de": ("21,5", "10.370", "1.234"),
                               "fr": ("21,5", "10 370", "1 234")})

    def test_a_number_on_a_page_follows_it(self):
        with speaking("de"):
            self.assertEqual(layout.element_text({"type": "number", "decimals": 1, "suffix": " °C"}, {0: "21.46"}, 0), "21,5 °C")

    def test_home_assistant_gives_the_time_and_the_page_writes_it(self):
        # Home Assistant's own date formats and relative time speak English whatever its language.
        el = {"type": "text", "entity": "sensor.door", "show": "last_changed", "format": "day_date"}
        self.assertNotIn("timestamp_custom", binding.template_for(el))
        self.assertNotIn("relative_time", binding.template_for({**el, "format": "relative"}))
        with speaking("fr"):
            self.assertEqual(binding.shown(el, AT.isoformat()), "mer. 21 oct.")
            self.assertEqual(binding.shown({**el, "format": "relative"}, AT.isoformat(), now=AT.replace(hour=17)), "3 heures")
        self.assertEqual(binding.shown({**el, "format": "relative"}, AT.isoformat(), now=AT.replace(hour=15)), "1 hour")

    def test_the_add_ons_clock_is_written_when_drawn(self):
        # Values are fetched once per design, for every device showing it: the clock hands over the time.
        for el in ({"type": "text", "show": "now", "format": "day_full"},
                   {"type": "text", "value": "{{ now().strftime('%A') }}"}):
            got = binding.local_value(el, {})
            datetime.fromisoformat(got)
            with speaking("ro"):
                text = layout.element_text(el, {0: AT.isoformat()}, 0)
            self.assertIn("miercuri", text)
        self.assertIsNone(binding.clock_pattern({"type": "text", "value": "{{ now().strftime('%A') }} {{ states('x') }}"}))


class TestADevicesOwnLanguage(unittest.TestCase):
    def test_its_own_else_home_assistants_else_english(self):
        self.assertEqual([words.for_device(own, home) for own, home in
                          (("de", "fr"), ("", "fr"), (None, "ro-RO"), ("", "it"), ("xx", "es"), ("", None))],
                         ["de", "fr", "ro", "en", "es", "en"])

    def test_its_pictures_are_drawn_in_it(self):
        import frames
        from unittest import mock

        async def locale(_):
            return "FR", "fr"

        async def drawn(dev):
            with mock.patch.object(frames, "get_home_locale", locale):
                with await frames.device_words(None, dev):
                    return words.language(), words.country()
        self.assertEqual(asyncio.run(drawn({"language": "de"})), ("de", "FR"))
        self.assertEqual(asyncio.run(drawn({})), ("fr", "FR"), "Same as Home Assistant")


class TestPresetsWriteTheDevicesWords(unittest.TestCase):
    """The user's call (26 Oct): a preset's labels are written in the device's language when the page
    is made; from then on they're the person's own words, never translated again."""

    def js(self, lang, body):
        import json
        import shutil
        import test_presets as tp
        if not shutil.which("node"):
            self.skipTest("no node to read the editor's presets")
        return tp.run_js(f"Cat.setSpeaking({json.dumps(lang)});\n{body}")

    def test_labels_and_page_names_in_the_devices_language(self):
        body = """const p = (id) => P.presetById(id), l = (id) => p(id).looks[0];
          const texts = (id, ent) => P.pageFor(p(id), l(id), ent).elements.filter((e) => e.type === "text" && e.value).map((e) => e.value);
          console.log(JSON.stringify({ climate: texts("climate", "sensor.indoor_temperature"), name: P.pageName(p("climate"), l("climate"), ""),
            weather: P.pageName(p("weather_forecast"), l("weather_forecast"), ""),
            status: P.pageFor(p("status"), l("status"), "binary_sensor.front_door").elements.find((e) => e.replace)?.replace }));"""
        de, fr, en = self.js("de", body), self.js("fr", body), self.js("en", body)
        self.assertEqual((de["climate"], de["name"], de["weather"]), (["Raumklima"], "Raumtemperatur", "Wetter"))
        self.assertEqual(fr["weather"], "Meteo", "a page's name is a plain-letter slug: accents folded")
        self.assertEqual((en["climate"], en["name"]), (["room climate"], "Room temperature"))
        self.assertEqual(de["status"], {"on": "An", "off": "Aus"}, "Home Assistant's state words, in German")

    def test_every_word_a_preset_writes_is_in_the_table(self):
        src = (APP / "web" / "app" / "presets.js").read_text()
        keys = {"page." + k for k in re.findall(r'pageWord\(\s*"([\w.]+)"', src)}
        keys |= {"page.name." + k for k in re.findall(r'pageNameWord\(\s*"(\w+)"', src)}
        keys |= {"page.name." + k for k in re.findall(r'^\s+id: "(\w+)", group:', src, re.M)
                 if k not in ("match", "race_weekend", "batteries")}     # named by their league, series or rule
        self.assertGreater(len(keys), 30)
        self.assertEqual(sorted(k for k in keys if k not in WORDS), [])

    def test_every_state_word_is_in_the_table(self):
        from render import states
        said = {w for v in states.STATES.values() for (w, _) in v.values()}
        self.assertEqual(sorted(w for w in said if f"state.{w}" not in WORDS), [])

    def test_the_catalog_carries_them_for_every_language(self):
        got = words.page_words()
        self.assertTrue(all(set(row) == set(words.LANGUAGES) for row in got.values()))
        self.assertEqual(got["page.room_climate"]["ro"], "climat interior")


class TestPagesSayIt(unittest.TestCase):
    def test_a_race_page_says_its_session_and_state(self):
        data = {"status": "IN", "session": "Qualifying", "session_start": "2026-10-24T21:00:00+00:00", "tz": "Europe/Bucharest"}
        with speaking("de"):
            self.assertEqual(race.forms(data), ["QUALIFYING · LIVE", "QUALIFYING"])
            self.assertEqual(race.detail({**data, "status": "PRE"}), "Qualifying · So. 25. Okt. · 00:00 EEST")
        with speaking("fr"):
            self.assertEqual(race.forms({"status": "OFF"}), ["INTERSAISON"])
            self.assertEqual(race.gap(race.LEADER), "EN TÊTE")
        self.assertEqual(race.session("Formula E Rookie Test"), "Formula E Rookie Test", "a source's own name stays")

    def test_a_scores_badge_in_its_sports_words(self):
        kick = datetime.now(TZ).replace(hour=20, minute=0, second=0, microsecond=0)
        game = {"status": "PRE", "kickoff_iso": kick.isoformat(), "tz": "Europe/Bucharest"}
        with speaking("de"):
            self.assertEqual(sport.badge(game, "soccer/ger.1"), "Anstoß 20:00")
            self.assertEqual(sport.badge({"status": "IN", "clock_val": "67'", "status_name": "STATUS_SECOND_HALF"}), "67' · 2. HALBZEIT")
        with speaking("es"):
            self.assertEqual(sport.badge({"status": "IN", "status_name": "STATUS_UNHEARD_OF", "status_text": "Extra Time"}),
                             "Extra Time", "ESPN's own words where the add-on has none")

    def test_countdown_and_to_do_words(self):
        now = AT.replace(hour=9)
        with speaking("ro"):
            got = countdown.describe({"type": "countdown", "to": "date", "name": "Concediu", "at": "2026-11-10"}, now)
            self.assertEqual((got[0].value, got[0].caption, got[1].value), ("Peste 20 de zile", "Concediu", "marți, 10 noiembrie"))
            self.assertEqual(todo.due_label({"due": "2026-10-23"}, now)[0], "Vin.")
        self.assertEqual(countdown.status({"type": "countdown", "to": "date", "at": "2026-10-01"}, now),
                         {"state": "passed", "on": "Thursday 1 October"}, "the editor's words stay English")

    def test_the_sleep_screen_says_when_in_its_hours(self):
        with speaking("es"):
            self.assertEqual(sleep.wake_text("schedule", "01:30"), "vuelve a la 01:30")
            self.assertEqual(sleep.wake_text("schedule", "07:00"), "vuelve a las 07:00")
        clock.use(True)
        try:
            self.assertEqual(sleep.wake_text("schedule", "19:00"), "back at 7:00 PM", "never a 24-hour time in 12-hour")
        finally:
            clock.use(False)


# ---------------------------------------------------------------- the longest words fit

def _inside(img, box) -> int:
    x, y, w, h = box
    return T.to_1bit(img).crop((x, y, x + w + 1, y + h + 1)).histogram()[0]


class TestTheLongestWordsFit(unittest.TestCase):
    """German and French run longer: every widget still draws inside its box, and every page's
    words fit their boxes, at every size offered, in every language."""

    def test_every_widget_stays_in_its_box(self):
        import test_widgets as tw
        cases = [c for c in vars(tw).values() if isinstance(c, type) and issubclass(c, tw.Sizes) and c is not tw.Sizes]
        self.assertGreater(len(cases), 5)
        for lang in OTHERS:
            for case in cases:
                for disp, orient in tw.SIZES:
                    target = arrange.canvas_key(*T.canvas_dims(orient, disp))
                    el = {**case.element, **arrange.auto_box(case.element, tw.BASE, target)}
                    with self.subTest(lang=lang, widget=case.__name__, display=disp, orient=orient), speaking(lang):
                        img = tw.render(case.element, case.value, disp, orient)
                        box = (el["x"], el["y"], el["w"], el["h"])
                        self.assertEqual(tw.ink(img) - _inside(img, box), 0, "drew outside its box")

    # Every widget, as New page makes it, drawn with its example value (examples.py) or none.
    WIDGETS = [(t, {}) for t in sorted(set(layout.DRAWERS) - {"text", "number", "icon", "line", "box", "bar", "bar_chart",
                                                           "qr", "curve", "countdown", "todo_list", "sports_racing",
                                                           "sports_match", "flight_tracker"})] + [
        ("countdown", {"to": "date", "name": "Weihnachten", "at": "2026-12-24"}),
        ("countdown", {"to": "bins", "bins": [{"name": "", "from": "2026-10-20", "every": 1}]}),
        ("countdown", {"to": "date", "at": "2026-12-24T18:00"}),
        ("todo_list", {"entity": "todo.shopping"}), ("todo_list", {"entity": "todo.shopping", "show": "due"}),
        ("sports_racing", {"series": "f1"}), ("sports_match", {"league": "soccer/ger.1"}),
        ("flight_tracker", {"style": "card"}), ("flight_tracker", {"style": "split"}), ("flight_tracker", {"style": "radar"}),
        ("weather_forecast", {"layout_mode": "stacked"}), ("weather_forecast", {"layout_mode": "hero_only"}),
    ]

    # Too small for these widgets in any language (a box 80 px tall on the 2.9"; upright on the 4.2"):
    # they draw past their box in English too. Not a matter of words; see the coordinator's backlog.
    TOO_SMALL_ANYWAY = {("crowpanel_290", 0, "sports_match"), ("crowpanel_290", 0, "flight_tracker"),
                        ("crowpanel_290", 0, "weather_forecast"), ("crowpanel_420", 90, "sports_match")}

    def outside(self, el, disp, orient) -> int:
        import examples
        cw, ch = T.canvas_dims(orient, disp)
        page = {"elements": [el]}
        vals, _ = examples.page_values(page)
        img = layout.render_page(page, vals, clock="12:45", orientation=orient, display=disp)
        return T.to_1bit(img).crop((0, 0, cw, ch - T.band_height(ch) - 2)).histogram()[0] \
            - _inside(img, (el["x"], el["y"], el["w"], el["h"]))

    def test_every_page_with_an_example_fits(self):
        # Each widget with its example value (what New page's thumbnails draw), filling every size offered.
        for disp, orient in OFFERED:
            cw, ch = T.canvas_dims(orient, disp)
            for t, extra in self.WIDGETS:
                el = {"type": t, "x": 8, "y": 8, "w": cw - 16, "h": ch - T.band_height(ch) - 16, **extra}
                english = self.outside(el, disp, orient)
                if (disp, orient, t) in self.TOO_SMALL_ANYWAY:
                    continue
                self.assertEqual(english, 0, (disp, orient, t, extra))
                for lang in OTHERS:
                    with self.subTest(lang=lang, widget=t, extra=extra, display=disp, orient=orient), speaking(lang):
                        self.assertEqual(self.outside(el, disp, orient), 0, "drew outside its box")

    # What a widget says when it has nothing to show or needs setting up: the longest sentences.
    MESSAGES = [({"type": "sun_times"}, {}), ({"type": "energy_total", "source": "solar"}, {}),
                ({"type": "energy_total", "source": "entity"}, {}), ({"type": "energy_cost"}, {}),
                ({"type": "grid_now"}, {"missing": True}), ({"type": "now_playing"}, []),
                ({"type": "world_clock", "zones": []}, {}), ({"type": "countdown", "to": "date"}, {}),
                ({"type": "countdown", "to": "bins"}, {}), ({"type": "tv_week"}, {}),
                ({"type": "tv_week", "entity": "calendar.tv"}, {"events": []}), ({"type": "todo_list"}, None),
                ({"type": "todo_list", "entity": "todo.x"}, {"items": []}),
                ({"type": "todo_list", "entity": "todo.x", "show": "due"}, {"items": []}),
                ({"type": "notifications"}, {"items": []}), ({"type": "updates"}, {"items": []}),
                ({"type": "calendar_agenda", "entity": "calendar.x"}, []), ({"type": "flight_tracker"}, [])]

    def test_every_message_fits(self):
        for lang in words.LANGUAGES:
            for disp, orient in OFFERED:
                cw, ch = T.canvas_dims(orient, disp)
                for extra, value in self.MESSAGES:
                    if (disp, orient, extra["type"]) in self.TOO_SMALL_ANYWAY:
                        continue
                    el = {"x": 8, "y": 8, "w": cw - 16, "h": ch - T.band_height(ch) - 16, **extra}
                    with self.subTest(lang=lang, widget=extra, display=disp, orient=orient), speaking(lang):
                        img = layout.render_page({"elements": [el]}, {0: value}, clock="12:45", orientation=orient, display=disp)
                        drawn = T.to_1bit(img).crop((0, 0, cw, ch - T.band_height(ch) - 2)).histogram()[0]
                        self.assertGreater(drawn, 0, "it says something")
                        self.assertEqual(drawn - _inside(img, (el["x"], el["y"], el["w"], el["h"])), 0)

    def test_a_word_fits_up_to_its_largest_size(self):
        # A preset's word that's longer in some languages is as large as fits, at most its max_size.
        el = {"type": "text", "max_size": 80, "bold": True, "x": 0, "y": 0, "w": 580, "h": 128}
        for word, want in (("Closed", 80), ("Geschlossen", 80), ("Manipulation erkannt", None)):
            got = []
            layout._draw_text(*T.new_canvas(), el, word, got)
            self.assertFalse(got[0]["overflow"], word)
            self.assertEqual(got[0]["size"], want or got[0]["size"])
            self.assertLessEqual(got[0]["size"], 80)
        self.assertEqual(arrange.auto_box(el, "792x272", "296x128")["max_size"], 30, "placed on a smaller size like a size")

    def test_every_preset_fits(self):
        # The presets' own fit check (test_presets.TestEverythingFits), with the labels they write in
        # each other language: on the 5.79" and placed on every other size offered.
        import json
        import shutil
        import test_presets as tp
        if not shutil.which("node"):
            self.skipTest("no node to read the editor's presets")
        fits = tp.TestEverythingFits("test_on_every_offered_size")
        base = arrange.canvas_key(T.DISPLAYS["crowpanel_579"]["w"], T.DISPLAYS["crowpanel_579"]["h"])
        for lang in OTHERS:
            cat = tp.run_js(f"Cat.setSpeaking({json.dumps(lang)});" + tp.CATALOGUE)
            for key, d in T.DISPLAYS.items():
                if d.get("offered") is False:
                    continue
                target = arrange.canvas_key(d["w"], d["h"])
                for p in cat["presets"]:
                    for look in p["looks"]:
                        page = json.loads(json.dumps(look["example"]))
                        for el in page["elements"]:
                            el.update(arrange.auto_box(el, base, target))
                        with self.subTest(lang=lang, look=look["id"], display=key), speaking(lang):
                            self.assertEqual(fits.check(page, key), [])

    def test_the_sleep_screen_fits(self):
        for lang in words.LANGUAGES:
            for disp, orient in OFFERED:
                cw, _ = T.canvas_dims(orient, disp)
                for text in (sleep.manual_text, lambda: sleep.wake_text("away", ""), lambda: sleep.wake_text("schedule", "07:00")):
                    with self.subTest(lang=lang, display=disp, orient=orient), speaking(lang):
                        said = text()
                        img = T.to_1bit(sleep.render_sleep_page(said, orient, disp))
                        cols = [x for x in range(cw) if img.crop((x, 0, x + 1, img.size[1])).histogram()[0]]
                        self.assertGreater(min(cols), 0, said)
                        self.assertLess(max(cols), cw - 1, said)

    def test_updated_and_its_day_leave_the_footer_its_pills(self):
        for lang in words.LANGUAGES:
            for twelve in (False, True):
                clock.use(twelve)
                with speaking(lang):
                    label = say("footer.updated", time=clock.day_and_time(AT))
                for disp, orient in OFFERED:
                    plan = T.footer_plan(clock=label, pages=[("Kitchen", 3)] * 6, orientation=orient, display=disp)
                    cw, _ = T.canvas_dims(orient, disp)
                    with self.subTest(lang=lang, twelve=twelve, display=disp, orient=orient):
                        self.assertLessEqual(plan["clock_end"], plan["cat_x0"])
                        self.assertLessEqual(plan["cat_x0"] + max(p["w"] for p in plan["pages"]), cw - plan["margin"])
        clock.use(False)


if __name__ == "__main__":
    unittest.main()


from test_editor_api import EditorClient  # noqa: E402


class TestTheLanguageSetting(EditorClient):
    """Settings › Device "Language": Same as Home Assistant ("") or one of the five."""

    async def test_set_it_read_it_and_go_back_to_home_assistants(self):
        dev = (await (await self.ed.get("/api/devices")).json())["devices"][0]
        self.assertEqual((dev["language"], dev["speaks"]), ("", "en"))
        r = await self.ed.patch(f"/api/devices/{dev['id']}", json={"language": "de"})
        self.assertEqual(r.status, 200)
        self.assertEqual(((await r.json())["device"]["language"], (await r.json())["device"]["speaks"]), ("de", "de"))
        r = await self.ed.patch(f"/api/devices/{dev['id']}", json={"language": "it"})
        self.assertEqual(r.status, 400, "only the languages offered")
        r = await self.ed.patch(f"/api/devices/{dev['id']}", json={"language": ""})
        self.assertEqual((await r.json())["device"]["language"], "")
        import devices
        self.assertNotIn("language", devices.get(dev["id"]), "Home Assistant's: nothing stored")

    async def test_the_catalog_offers_them(self):
        cat = await (await self.ed.get("/api/catalog")).json()
        self.assertEqual([c for c, _ in cat["languages"]["choices"]], list(words.LANGUAGES))
        self.assertIn("page.room_climate", cat["page_words"])
