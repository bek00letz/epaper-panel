"""Countdown without a calendar (render/countdown.py), the user's call (21 Oct): a date of
yours, or your bins and their days, picked in place; Bin day is a Countdown that repeats.
The add-on counts from the element itself, so the panel, the canvas and the thumbnail agree."""
import json
import shutil
import subprocess
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import support
import examples
import frames
from render import binding, countdown, layout
from render.linger import Linger

TZ = ZoneInfo("Europe/Bucharest")
BINS = {"type": "countdown", "to": "bins", "bins": [
    {"name": "Recycling", "from": "2026-11-03", "every": 2},
    {"name": "General waste", "from": "2026-11-10", "every": 2}]}
APP_JS = support.APP / "web" / "app"


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def says(el, when):
    main, aside = countdown.describe(el, at(when))
    return main.value, main.caption, aside.value


class TestBins(unittest.TestCase):
    def test_tomorrow_the_evening_before_today_until_noon_then_the_next(self):
        self.assertEqual(says(BINS, "2026-11-02 19:00"), ("Tomorrow", "Recycling", "Tuesday 3 November"))
        self.assertEqual(says(BINS, "2026-11-03 09:00"), ("Today", "Recycling", "Tuesday 3 November"))
        self.assertEqual(says(BINS, "2026-11-03 12:30"), ("In 7 days", "General waste", "Tuesday 10 November"))

    def test_alternating_bins_take_turns(self):
        names = [says(BINS, f"2026-{d} 08:00")[1] for d in ("11-03", "11-10", "11-17", "11-24", "12-01")]
        self.assertEqual(names, ["Recycling", "General waste", "Recycling", "General waste", "Recycling"])

    def test_two_on_one_day_are_both_named(self):
        el = {**BINS, "bins": [{"name": "Recycling", "from": "2026-11-03", "every": 1}, {"name": "Garden", "from": "2026-11-03", "every": 4}]}
        self.assertEqual(says(el, "2026-11-02 18:00")[1], "Recycling and Garden")
        self.assertEqual(says(el, "2026-11-09 18:00")[1], "Recycling")

    def test_close_to_the_day_is_yours_to_choose(self):
        late = {**BINS, "today_until": "midnight"}
        self.assertEqual(says(late, "2026-11-03 20:00")[0], "Today", "Today until midnight")
        numbers = {**BINS, "today_until": "days"}
        self.assertEqual([says(numbers, t)[0] for t in ("2026-11-02 19:00", "2026-11-03 09:00", "2026-10-30 09:00")], ["1 day", "0 days", "4 days"])

    def test_a_first_collection_still_to_come(self):
        self.assertEqual(says(BINS, "2026-10-21 10:00"), ("In 13 days", "Recycling", "Tuesday 3 November"))

    def test_nothing_set_up_yet(self):
        self.assertIsNone(countdown.describe({"type": "countdown", "to": "bins", "bins": [{"name": "Recycling", "from": ""}]}, at("2026-11-02 10:00")))


class TestDate(unittest.TestCase):
    HOLIDAY = {"type": "countdown", "to": "date", "name": "Holiday", "at": "2026-12-24T18:00"}

    def test_days_then_hours_on_the_day(self):
        self.assertEqual(says(self.HOLIDAY, "2026-12-20 10:00"), ("In 4 days", "Holiday", "Thursday 24 December, 18:00"))
        self.assertEqual(says(self.HOLIDAY, "2026-12-23 10:00")[0], "Tomorrow")
        self.assertEqual(says(self.HOLIDAY, "2026-12-24 14:20")[0], "In 4 hours")
        self.assertEqual(says(self.HOLIDAY, "2026-12-24 17:30")[0], "In 30 min")

    def test_a_whole_day_is_today_until_it_ends(self):
        el = {**self.HOLIDAY, "at": "2026-12-24"}
        self.assertEqual(says(el, "2026-12-24 23:30")[0], "Today")
        self.assertFalse(countdown.passed(el, at("2026-12-24 23:30")))
        self.assertTrue(countdown.passed(el, at("2026-12-25 00:01")))

    def test_once_past_its_page_hides_itself(self):
        page = {"elements": [self.HOLIDAY]}
        self.assertFalse(countdown.page_passed(page, at("2026-12-24 17:59")))
        self.assertTrue(countdown.page_passed(page, at("2026-12-24 18:00")))
        self.assertFalse(countdown.page_passed({"elements": [BINS]}, at("2027-06-01 10:00")), "bins never end")

    def test_every_year_rolls_on(self):
        el = {"type": "countdown", "to": "date", "name": "Birthday", "at": "2000-03-01", "yearly": True}
        self.assertEqual(says(el, "2026-10-21 10:00"), ("In 131 days", "Birthday", "Monday 1 March 2027"))
        self.assertFalse(countdown.passed(el, at("2026-10-21 10:00")))
        leap = {**el, "at": "2024-02-29"}
        self.assertEqual(says(leap, "2026-02-27 10:00")[2], "Saturday 28 February", "29 February in a year without one")


class TestEverywhereTheSame(unittest.IsolatedAsyncioTestCase):
    """One place counts: the render cycle, the editor's canvas and the thumbnails all draw it."""

    def test_drawn_with_nothing_asked_of_anyone(self):
        page = {"elements": [{**BINS, "x": 24, "y": 14, "w": 744, "h": 208}]}
        vals, _ = examples.page_values(page)
        self.assertIn(0, vals)
        layout.render_page(page, vals)                        # draws; nothing to fetch
        self.assertEqual(layout.collect_templates(page), {}, "no template for Home Assistant")

    async def test_the_cycle_hides_a_past_date_and_keeps_the_rest(self):
        spec = {"rotation": ["holiday", "bins"], "pages": {
            "holiday": {"tier": "rotate", "elements": [{"type": "countdown", "to": "date", "name": "Holiday", "at": "2000-01-01"}]},
            "bins": {"tier": "rotate", "elements": [BINS]}}}
        live = await frames.eligible_pages(None, spec, Linger())
        self.assertEqual(live, ["bins"])

    def test_pages_made_from_a_calendar_keep_working(self):
        el = {"type": "number", "entity": "calendar.bins", "show": "days_until", "suffix": " days"}
        self.assertIn("calendar.bins", binding.template_for(el))


class TestKeptAndWaiting(unittest.TestCase):
    """The user's calls (21 Oct): a passed countdown stays, marked Passed, to reuse; and one set far
    ahead can start showing only some days before."""
    TRIP = {"type": "countdown", "to": "date", "name": "Trip", "at": "2027-04-21", "show_before": 30}

    def test_it_waits_until_its_time(self):
        self.assertEqual(countdown.status(self.TRIP, at("2026-10-21 10:00")), {"state": "waiting", "from": "Monday 22 March 2027"})
        self.assertTrue(countdown.page_hidden({"elements": [self.TRIP]}, at("2026-10-21 10:00")))
        self.assertEqual(countdown.status(self.TRIP, at("2027-03-22 08:00")), {"state": "showing"})
        self.assertFalse(countdown.page_hidden({"elements": [self.TRIP]}, at("2027-03-22 08:00")))

    def test_bins_can_show_only_the_evening_before(self):
        el = {**BINS, "show_before": 1}
        self.assertEqual(countdown.status(el, at("2026-10-31 10:00"))["state"], "waiting")
        self.assertEqual(countdown.status(el, at("2026-11-02 19:00"))["state"], "showing")

    def test_passed_is_said_and_kept(self):
        got = countdown.status({**self.TRIP, "show_before": 0}, at("2027-04-22 09:00"))
        self.assertEqual(got, {"state": "passed", "on": "Wednesday 21 April"})
        metrics = []
        layout.render_page({"elements": [{**self.TRIP, "at": "2000-01-01", "x": 24, "y": 14, "w": 744, "h": 208}]}, {0: {"tz": None}}, metrics=metrics)
        self.assertEqual(metrics[0]["countdown"]["state"], "passed", "the editor hears it from the render")

    def test_the_editor_shows_it_and_never_deletes_by_itself(self):
        strip = (APP_JS / "strip.js").read_text()
        self.assertIn('t.classList.toggle("passed", c?.state === "passed");', strip)
        self.assertIn("`Shows from ${c.from}`", strip)
        insp = (APP_JS / "inspector.js").read_text()
        self.assertIn('h("button", { class: "btn tinted danger", onclick: () => app.deletePage() }, icon("trash", "sm"), "Delete")', insp)
        css = (support.APP / "web" / "editor.css").read_text()
        self.assertIn(".tile.passed .thumbwrap { box-shadow: 0 0 0 2px var(--orange); opacity: 0.55; }", css, "an outline, not just a pill")
        self.assertNotIn("deletePage", (APP_JS / "countdown.js").read_text())
        # A page's buttons over the right third of its picture, beside the tile in its box; showing
        # all the time on a passed countdown (the user's design, 21 Oct).
        self.assertIn('box.classList.toggle("passed", c?.state === "passed");', strip)
        self.assertIn('act("dup", "Duplicate"', strip)
        self.assertIn('act("trash", "Delete"', strip)
        self.assertIn("slots.forEach((t) => list.append(t.box));", strip)
        self.assertIn("reorderable(list, slots,", strip, "dragging still moves the tiles themselves")
        self.assertIn(".tilebox.held .tileacts, .tilebox.passed .tileacts { opacity: 1;", css)
        self.assertIn(".tileacts { position: absolute; top: 0; right: 0; width: calc(100% / 3);", css)
        self.assertIn('[180, "6 months before"]', (APP_JS / "countdown.js").read_text())


@unittest.skipUnless(shutil.which("node"), "no node to read the editor's presets")
class TestThePreset(unittest.TestCase):
    def run_js(self, body):
        script = f"import * as P from {json.dumps(str(APP_JS / 'presets.js'))};\n{body}"
        return json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_bin_day_is_a_countdown_that_repeats(self):
        got = self.run_js("""const p = P.presetById("countdown");
          console.log(JSON.stringify([p.choose, p.looks.map((l) => [l.name, P.needsOf(p, l) || "", P.asksOf(p, l) || ""]), !!P.presetById("bin_day"),
            P.search("bin")[0].id, P.search("bin day")[0].id, P.search("birthday")[0].id]))""")
        choose, looks, old, *found = got
        self.assertEqual(choose, "Counts down to")
        self.assertEqual(looks, [["A date", "date", ""], ["Bin day", "bins", ""], ["A calendar event", "", "calendar"]])
        self.assertFalse(old, "one preset, not two")
        self.assertEqual(found, ["countdown", "countdown", "countdown"])

    def test_its_pages_carry_what_they_count_to(self):
        got = self.run_js("""const p = P.presetById("countdown");
          const bins = { bins: [{ name: "Recycling", from: "2026-11-03", every: 2 }], today_until: "midnight" };
          console.log(JSON.stringify([P.pageFor(p, p.looks[0], "", { name: "Holiday", at: "2026-12-24T18:00", yearly: false }).elements[0],
            P.pageFor(p, p.looks[1], "", bins).elements[0], P.pageName(p, p.looks[1], "", "", bins), P.pageName(p, p.looks[0], "", "", { name: "Holiday" }),
            P.pageFor(p, p.looks[2], "calendar.family").elements.map((e) => e.entity || "")]))""")
        date, bins, bin_name, date_name, calendar = got
        self.assertEqual((date["type"], date["to"], date["at"], date["name"]), ("countdown", "date", "2026-12-24T18:00", "Holiday"))
        self.assertEqual((bins["to"], bins["today_until"], bins["bins"][0]["every"]), ("bins", "midnight", 2))
        self.assertEqual((bin_name, date_name), ("Bin day", "Holiday"))
        self.assertEqual(calendar[1:], ["calendar.family"] * 3, "a calendar stays the alternative")

    def test_set_up_in_place_and_editable_later(self):
        setup = (APP_JS / "setup.js").read_text()
        self.assertIn('date: countSetup("date"), bins: countSetup("bins")', setup)
        self.assertIn("need = needs && SETUPS[needs] ? SETUPS[needs]({ app, p, look: look(), changed }) : null;", setup, "each look sets up its own")
        insp = (APP_JS / "inspector.js").read_text()
        self.assertIn('else if (f.kind === "countdown") s.append((el.to === "bins" ? binsEditor : dateEditor)(el, () => app.doc.commit()));', insp)
        ed = (APP_JS / "countdown.js").read_text()
        self.assertIn('["noon", "Tomorrow, then Today until noon"]', ed)
        self.assertNotIn("getDate() -", ed, "the editor never counts days itself")


if __name__ == "__main__":
    unittest.main()
