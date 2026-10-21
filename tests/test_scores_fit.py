"""Scores on an always-on panel: the editor says when a busy day can pass what it holds, and what
was left out when it did (the user's call, 21 Oct: only there, never a global page counter).

The editor has no JavaScript test runner, so these pin its wording and wiring in the source (as
test_editor_chrome does); the numbers are the add-on's (test_fit_and_render.TestBusyDay)."""
import unittest

import support

APP = support.APP / "web" / "app"


def js(name):
    return (APP / name).read_text()


class TestBusyDayLine(unittest.TestCase):
    def test_the_add_on_works_it_out_and_the_editor_only_words_it(self):
        src = js("busyday.js")
        self.assertIn('api("api/busy_day", { method: "POST", body })', src)
        self.assertIn("scores.room < scores.busiest", src, "nothing when a busy day fits")
        # The user's wording.
        self.assertIn("On a busy day ${leagues} can have a lot of scores, and ${who} can only show about ${scores.room} of them. ", src)
        self.assertIn("Pick your teams to make sure their scores show.", src)

    def test_it_sits_under_the_league_while_setting_up_and_in_the_inspector(self):
        self.assertIn('group, note, busy));', js("setup.js"))
        self.assertIn('if (p.choose !== "League") return;', js("setup.js"), "Scores only")
        self.assertIn('if (f.key === "league") s.append(busyNote(app, app.doc.spec));', js("inspector.js"))

class TestLeftOut(unittest.TestCase):
    def test_the_tile_says_it_in_the_pages_own_words(self):
        src = js("busyday.js")
        self.assertIn("(app.status?.fit?.trimmed || []).find((t) => t.page === n)", src, "the add-on's fit, nothing counted here")
        self.assertIn("`Showing ${cut.shown} of ${cut.of} ${cut.items}`", src)
        self.assertIn("if (cut) sub = leftOutShort(cut);", js("strip.js"))

    def test_the_inspector_says_more_and_keeps_up(self):
        src = js("busyday.js")
        self.assertIn("has room for ${cut.shown} of the ${cut.of} ${cut.items} right now, ", src)
        self.assertIn("body.append(leftOutNote(app, cur));", js("inspector.js"), "the page's inspector")
        self.assertIn("if (widget(el.type)?.sub_items) body.append(leftOutNote(app, doc.cur));", js("inspector.js"),
                      "and its Scores widget's, which fills the page")
        self.assertIn("refreshLeftOut(this);", js("main.js"), "gone by itself once nothing is left out")


class TestNoCounter(unittest.TestCase):
    def test_no_page_counter_anywhere(self):
        for name in ("strip.js", "sheets.js", "main.js"):
            self.assertNotIn("pages_wanted", js(name), name)
            self.assertNotIn("pages_shown", js(name), name)


if __name__ == "__main__":
    unittest.main()
