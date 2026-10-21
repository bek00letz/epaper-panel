"""What hasn't been sent to the panel yet: the editor's one comparison
(`doc.changes`), which the 409 merge, the page strip and "Not sent yet" all
read, and putting one page or one setting back to what the panel has."""
import json
import re
import shutil
import subprocess
import unittest

import support

WEB = support.APP / "web"
DOC_JS = WEB / "app" / "doc.js"
STRIP_JS = WEB / "app" / "strip.js"
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "editor.css").read_text(), flags=re.S)


def css_rule(selector):
    return next(body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if sel.strip() == selector)


def run_js(body):
    """Run `body` with the editor's doc module as `D`; it prints JSON."""
    script = ("globalThis.navigator ??= { platform: '' };\n"
              f"const D = await import({json.dumps(DOC_JS.as_uri())});\n"
              f"const S = await import({json.dumps(STRIP_JS.as_uri())});\n"
              "const live = () => D.normalize({ pages: {"
              " solar: { elements: [{ id: 'a', type: 'text', x: 1 }, { id: 'b', type: 'text', x: 2 }] },"
              " clock: { elements: [{ id: 'c', type: 'text' }] },"
              " bins: { elements: [{ id: 'd', type: 'text' }] },"
              " news: { elements: [{ id: 'f', type: 'text' }] } },"
              " rotation: ['solar', 'clock', 'bins', 'news'] });\n"
              f"{body}")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's doc")
class TestChanges(unittest.TestCase):
    def test_the_same_pages_have_nothing_pending(self):
        c = run_js("console.log(JSON.stringify(D.changes(live(), live())));")
        self.assertEqual(c, {"pages": {}, "placed": {}, "rotation": False, "settings": [], "any": False})

    def test_the_order_keys_were_written_in_isnt_a_change(self):
        # The add-on writes a page "tier, show_if, elements"; a draft may have "tier, elements, show_if".
        c = run_js("""const m = live(); m.pages.solar = { elements: m.pages.solar.elements.map((e) => ({ x: e.x, type: e.type, id: e.id })) };
            const base = live(); base.pages.solar.tier = 'rotate'; m.pages.solar.tier = 'rotate';
            const d = new D.Doc(); d.live = base; d.spec = m;
            console.log(JSON.stringify([D.changes(base, m).any, d.dirty]));""")
        self.assertEqual(c, [False, False])

    def test_elements_are_compared_by_id(self):
        c = run_js("""const m = live();
            m.pages.solar.elements[0].x = 5;                       // a moved
            m.pages.solar.elements.push({ id: 'z', type: 'text' }); // z added
            m.pages.news.elements = [];                            // f removed
            console.log(JSON.stringify(D.changes(live(), m).pages));""")
        self.assertEqual(c["solar"], {"status": "changed", "elements": {"added": ["z"], "removed": [], "changed": ["a"]}, "order": False, "settings": False})
        self.assertEqual(c["news"]["elements"], {"added": [], "removed": ["f"], "changed": []})
        self.assertNotIn("clock", c)

    def test_layer_order_and_the_pages_own_settings(self):
        c = run_js("""const m = live();
            m.pages.solar.elements.reverse();
            m.pages.clock.tier = 'when';
            console.log(JSON.stringify(D.changes(live(), m).pages));""")
        self.assertTrue(c["solar"]["order"])
        self.assertEqual(c["solar"]["elements"]["changed"], [])
        self.assertTrue(c["clock"]["settings"])

    def test_a_group_following_its_members_isnt_a_change_of_its_own(self):
        c = run_js("""const base = live();
            base.pages.solar.elements.push({ id: 'g', type: 'group', members: ['a', 'b'], x: 1, y: 0, w: 10, h: 10 });
            const m = structuredClone(base);
            m.pages.solar.elements[0].x = 5; m.pages.solar.elements[2].x = 2;
            console.log(JSON.stringify(D.changes(base, m).pages.solar.elements));""")
        self.assertEqual(c["changed"], ["a"])

    def test_added_removed_and_renamed_pages(self):
        c = run_js("""const m = live();
            m.pages.clock_big = m.pages.clock; delete m.pages.clock;
            m.rotation = m.rotation.map((n) => n === 'clock' ? 'clock_big' : n);
            delete m.pages.bins; m.rotation = m.rotation.filter((n) => n !== 'bins');
            m.pages.todo = { elements: [{ id: 't', type: 'text' }] }; m.rotation.push('todo');
            console.log(JSON.stringify(D.changes(live(), m)));""")
        p = c["pages"]
        self.assertEqual(p["clock_big"]["status"], "renamed")
        self.assertEqual(p["clock_big"]["from"], "clock")
        self.assertEqual(p["clock"], {"status": "removed", "to": "clock_big"})
        self.assertEqual(p["bins"], {"status": "removed"})
        self.assertEqual(p["todo"], {"status": "added"})
        self.assertEqual(c["placed"], {}, "a rename, an addition and a removal don't move the others")

    def test_dragging_one_page_marks_only_it(self):
        c = run_js("""const m = live(); m.rotation = ['clock', 'bins', 'news', 'solar'];
            console.log(JSON.stringify(D.changes(live(), m)));""")
        self.assertEqual(c["placed"], {"solar": "moved"})
        self.assertEqual(c["pages"], {})
        self.assertTrue(c["rotation"])

    def test_into_and_out_of_the_rotation(self):
        c = run_js("""const m = live(); m.rotation = ['solar', 'clock', 'news', 'news'];
            const n = live(); n.rotation = ['solar', 'clock', 'news'];
            console.log(JSON.stringify([D.changes(live(), m).placed, D.changes(n, live()).placed]));""")
        self.assertEqual(c[0], {"bins": "out", "news": "moved"})
        self.assertEqual(c[1], {"bins": "in"})

    def test_settings_sent_with_the_pages(self):
        c = run_js("""const m = live(); m.quiet_hours.enabled = true; m.orientation = 90;
            console.log(JSON.stringify(D.changes(live(), m).settings));""")
        self.assertEqual(c, ["orientation", "quiet_hours"])


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's doc")
class TestMergeReadsTheSameComparison(unittest.TestCase):
    def test_a_page_changed_on_one_side_takes_that_side(self):
        c = run_js("""const mine = live(), theirs = live();
            mine.pages.solar.elements[0].x = 9; theirs.pages.clock.elements[0].text = 'hi';
            delete theirs.pages.bins; theirs.rotation = theirs.rotation.filter((n) => n !== 'bins');
            const { merged, clashes } = D.merge(live(), mine, theirs);
            console.log(JSON.stringify({ x: merged.pages.solar.elements[0].x, t: merged.pages.clock.elements[0].text, bins: !!merged.pages.bins, rotation: merged.rotation, clashes }));""")
        self.assertEqual(c, {"x": 9, "t": "hi", "bins": False, "rotation": ["solar", "clock", "news"], "clashes": []})

    def test_changed_on_both_sides_differently_is_a_clash(self):
        c = run_js("""const mine = live(), theirs = live();
            mine.pages.solar.elements[0].x = 9; theirs.pages.solar.elements[0].x = 7;
            mine.rotation.reverse(); theirs.rotation = ['news', 'solar', 'clock', 'bins'];
            mine.quiet_hours.enabled = true; theirs.quiet_hours.start = '22:00';
            console.log(JSON.stringify(D.merge(live(), mine, theirs).clashes.map((c) => [c.kind, c.name])));""")
        self.assertEqual(c, [["page", "solar"], ["rotation", "rotation"], ["setting", "quiet_hours"]])

    def test_the_same_change_on_both_sides_merges(self):
        c = run_js("""const mine = live(), theirs = live();
            mine.pages.solar.elements[0].x = 9; theirs.pages.solar.elements[0].x = 9;
            mine.orientation = 90; theirs.orientation = 90;
            const r = D.merge(live(), mine, theirs);
            console.log(JSON.stringify([r.clashes.length, r.merged.orientation]));""")
        self.assertEqual(c, [0, 90])


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's doc")
class TestPuttingBack(unittest.TestCase):
    """One page or one setting back to what the panel has, in one undo step."""

    def doc(self, edit, then):
        return run_js(f"""const doc = new D.Doc(); doc.scheduleSave = () => {{}};
            doc.live = live(); doc.spec = live(); doc.hist = [JSON.stringify(doc.spec)]; doc.hpos = 0; doc.cur = 'solar';
            const m = doc.spec; {edit}; doc.commit();
            {then}
            console.log(JSON.stringify({{ pending: doc.pending(), rotation: doc.spec.rotation, pages: Object.keys(doc.spec.pages), cur: doc.cur, undo: doc.hpos }}));""")

    def test_a_changed_page_goes_back_and_the_rest_stays(self):
        c = self.doc("m.pages.solar.elements[0].x = 9; m.pages.clock.elements[0].text = 'hi'", "doc.revertPage('solar');")
        self.assertEqual(list(c["pending"]["pages"]), ["clock"])
        self.assertEqual(c["undo"], 2, "one undo step")

    def test_an_added_page_goes(self):
        c = self.doc("m.pages.todo = { elements: [] }; m.rotation.push('todo'); doc.cur = 'todo'", "doc.revertPage('todo');")
        self.assertFalse(c["pending"]["any"])
        self.assertNotIn("todo", c["pages"])
        self.assertEqual(c["cur"], "solar")

    def test_a_removed_page_comes_back_where_it_was(self):
        c = self.doc("delete m.pages.bins; m.rotation = m.rotation.filter((n) => n !== 'bins')", "doc.revertPage('bins');")
        self.assertFalse(c["pending"]["any"])
        self.assertEqual(c["rotation"], ["solar", "clock", "bins", "news"])

    def test_a_renamed_page_gets_its_name_back(self):
        c = self.doc("m.pages.clock_big = m.pages.clock; delete m.pages.clock; m.rotation = m.rotation.map((n) => n === 'clock' ? 'clock_big' : n); doc.cur = 'clock_big'",
                     "doc.revertPage('clock_big');")
        self.assertFalse(c["pending"]["any"])
        self.assertEqual(c["cur"], "clock")

    def test_a_moved_page_goes_back_to_its_place(self):
        c = self.doc("m.rotation = ['clock', 'bins', 'news', 'solar']", "doc.revertPage('solar');")
        self.assertFalse(c["pending"]["any"])

    def test_a_page_taken_out_goes_back_in(self):
        c = self.doc("m.rotation = ['solar', 'bins', 'news']", "doc.revertPage('clock');")
        self.assertEqual(c["rotation"], ["solar", "clock", "bins", "news"])

    def test_one_setting(self):
        c = self.doc("m.quiet_hours.enabled = true; m.pages.solar.elements[0].x = 9", "doc.revertSetting('quiet_hours');")
        self.assertEqual(c["pending"]["settings"], [])
        self.assertEqual(list(c["pending"]["pages"]), ["solar"])


@unittest.skipUnless(shutil.which("node"), "no node to run the editor's strip")
class TestTheStripSaysWhatsWaiting(unittest.TestCase):
    def test_in_words(self):
        c = run_js("""const m = live();
            m.pages.solar.elements[0].x = 9; m.pages.solar.elements.push({ id: 'z', type: 'text' });
            m.pages.clock_big = m.pages.clock; delete m.pages.clock;
            delete m.pages.bins; m.pages.todo = { elements: [] };
            m.rotation = ['news', 'solar', 'clock_big', 'todo'];
            const p = D.changes(live(), m);
            const names = ['solar', 'clock_big', 'clock', 'bins', 'todo', 'news'];
            console.log(JSON.stringify(names.map((n) => [S.unsentWords(p, n), S.tileWords(p, n)])));""")
        self.assertEqual(c, [
            ["2 changes", "2 changes, not sent"],
            ["Renamed from Clock", "Renamed, not sent"],
            [None, None],                                # renamed away: its new name says it
            ["Removed", "Removed, not sent"],
            ["Added", "New, not sent"],
            ["Moved in the rotation", "Moved, not sent"],
        ])

    def test_changes_and_a_new_place_together(self):
        c = run_js("""const m = live(); m.pages.solar.elements[0].x = 9; m.rotation = ['clock', 'bins', 'news', 'solar'];
            console.log(JSON.stringify(S.unsentWords(D.changes(live(), m), 'solar')));""")
        self.assertEqual(c, "1 change · moved")

    def test_orange_ring_means_only_not_sent(self):
        self.assertIn("var(--orange)", css_rule(".tile.unsent .thumbwrap"))
        self.assertNotIn("box-shadow", css_rule(".tile.passed .thumbwrap"), "a passed countdown is greyed, not ringed")
        self.assertIn("var(--accent)", css_rule('.tile.unsent[aria-current="page"] .thumbwrap'), "the open page keeps its ring")
        self.assertIn("box-shadow", css_rule(".tile.unsent:focus-visible .thumbwrap"), "and the focus ring shows")

    def test_every_tile_reads_the_one_comparison(self):
        strip = STRIP_JS.read_text()
        self.assertIn("pend = doc.pending()", strip)
        calls = re.findall(r"(?<!function )\btile\(app, n, \{[^}]*\}", strip)
        self.assertEqual(len(calls), 3, "rotation, not in rotation and alerts")
        for c in calls:
            self.assertIn("pend", c)

    def test_removed_pages_stay_until_sent_and_a_click_puts_one_back(self):
        strip = STRIP_JS.read_text()
        self.assertIn('"Removed, not sent"', strip)
        self.assertIn("thumbnail(app, n, img, app.doc.live.pages[n])", strip, "drawn as the panel has it")
        self.assertIn("onclick: () => app.revertPage(n)", strip)
        main = (WEB / "app" / "main.js").read_text()
        self.assertRegex(main, r"revertPage\(name\) \{[^}]*doc\.revertPage\(name\)")
        self.assertIn('{ label: "Undo", run: () => doc.undo() }', main[main.index("revertPage(name) {"):main.index("setTier(v)")])


class TestTheStatusCardListsIt(unittest.TestCase):
    """The "Not sent yet" pill opens the status card, which lists what's waiting by page (the
    user's call, 21 Oct): a line opens its page, Undo puts that one back, never a question."""

    def setUp(self):
        sheets = (WEB / "app" / "sheets.js").read_text()
        self.card = sheets[sheets.index("export function openStatus"):sheets.index("export function openFullStrip")]

    def test_right_under_the_line_that_says_so(self):
        self.assertIn('...notes.slice(0, 1),\n      ...(doc.dirty && doc.saving !== "error" ? [unsentList(app, close)] : []), ...notes.slice(1));', self.card)

    def test_a_line_per_page_in_the_strips_order_then_the_settings(self):
        self.assertIn("[...new Set([...doc.spec.rotation, ...Object.keys(doc.spec.pages), ...Object.keys(pend.pages)])]", self.card)
        self.assertIn("unsentWords(pend, n)", self.card)
        self.assertIn("for (const s of pend.settings)", self.card)
        self.assertIn("SETTING_NAMES[s]", self.card)

    def test_a_line_opens_its_page_with_its_changes_outlined(self):
        self.assertIn("app.showChanges(n)", self.card)
        main = (WEB / "app" / "main.js").read_text()
        show = main[main.index("  showChanges(name) {"):]
        self.assertIn("this.canvas.showChanges([...p.elements.added, ...p.elements.changed]", show)
        self.assertIn("p.elements.removed.includes(e.id)", show, "dashed where removed ones were")

    def test_undo_is_one_thing_with_a_toast_and_the_list_stays(self):
        self.assertIn("undo: () => app.revertPage(n)", self.card)
        self.assertIn("() => app.revertSetting(s)", self.card)
        self.assertIn("onclick: () => { undo(); draw(i); }", self.card)
        self.assertIn("if (!pend.any) { close(); return; }", self.card)
        self.assertNotIn("confirm(", self.card)

    def test_a_new_model_or_mounting_has_no_undo_of_its_own(self):
        # Changing either placed every page for it: putting the setting back alone would leave them wrong.
        self.assertIn('undo: placing ? null : () => app.revertSetting(s)', self.card)

    def test_throw_away_says_all(self):
        self.assertIn('"Throw away all unsent changes"', self.card)

    def test_lines_are_big_enough_to_touch(self):
        self.assertIn("min-height: 44px", css_rule(".urow"))
        self.assertIn("min-height: 44px", css_rule(".uopen"))


class TestTheCanvasOutlinesThemForAMoment(unittest.TestCase):
    def setUp(self):
        self.canvas = (WEB / "app" / "canvas.js").read_text()

    def test_faded_by_the_first_click_or_edit(self):
        self.assertIn('this.doc.on("change", () => this.fadeChanges());', self.canvas)
        self.assertIn('p.addEventListener("pointerdown", (e) => {\n      this.fadeChanges();', self.canvas)
        self.assertIn("animation: fadeout", css_rule(".ob.chg.going"))

    def test_only_on_their_page(self):
        self.assertIn("const ch = this.changes?.page === this.doc.cur ? this.changes : null;", self.canvas)

    def test_orange_and_dashed_where_one_was_removed(self):
        self.assertIn("var(--orange)", css_rule(".ob.chg"))
        self.assertIn("dashed var(--orange)", css_rule(".ob.chg.gone"))


if __name__ == "__main__":
    unittest.main()
