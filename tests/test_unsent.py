"""What hasn't been sent to the panel yet: the editor's one comparison
(`doc.changes`), which the 409 merge, the page strip and "Not sent yet" all
read, and putting one page or one setting back to what the panel has."""
import json
import shutil
import subprocess
import unittest

import support

DOC_JS = support.APP / "web" / "app" / "doc.js"


def run_js(body):
    """Run `body` with the editor's doc module as `D`; it prints JSON."""
    script = ("globalThis.navigator ??= { platform: '' };\n"
              f"const D = await import({json.dumps(DOC_JS.as_uri())});\n"
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


if __name__ == "__main__":
    unittest.main()
