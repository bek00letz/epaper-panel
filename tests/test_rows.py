"""Every row in the editor, the inspector's (.field) and the grouped ones in Settings, New page and
the countdown (.gr): a label never wraps past two lines and a control is never squeezed; when they
don't fit on one line the control goes under the label, full width, its note under the label
(the user's call, 21 Oct: "Close to the day" read "Close / to / the / day" beside its menu).

There's no browser here, so the rule is pinned in the CSS and the code that feeds it, as
test_editor_chrome does; the layout was checked in the browser at 1280 and 375 wide across every
element type, the page's three modes, every New page step and every Settings pane."""
import json
import re
import subprocess
import unittest

import support

WEB = support.APP / "web"
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "editor.css").read_text(), flags=re.S)
UI = WEB / "app" / "ui.js"


def rule(selector):
    found = [body.strip() for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if sel.strip() == selector]
    if not found:
        raise AssertionError(f"no rule for {selector}")
    return found[-1]


class TestOneRuleForEveryRow(unittest.TestCase):
    def test_a_row_wraps_its_control_under_its_label(self):
        for sel in (".field", ".gr"):
            self.assertIn("display: flex", rule(sel), sel)
            self.assertIn("flex-wrap: wrap", rule(sel), sel)
        self.assertNotIn("grid-template-columns", rule(".field"), "a grid squeezes the control instead")

    def test_the_inspector_label_keeps_its_column(self):
        self.assertIn("flex: 0 0 92px", rule(".field > label, .field > .lab"))
        self.assertIn("flex: 1 1 var(--need, 8em)", rule(".field > *"))

    def test_a_control_asks_for_what_it_needs(self):
        self.assertIn("--need: max-content", rule('.field > :is(select, input[type="date"], input[type="time"], input[type="datetime-local"])'),
                      "a menu its longest choice, a date its own width")
        self.assertIn("flex: 1 1 var(--need, auto)", rule(".gr > :is(input, select, textarea, .inline, .segc)"),
                      "auto: a width the code gives a field (Port's 7em) still counts")
        self.assertIn("width: auto", rule(".gr .inp"))

    def test_a_grouped_label_has_room_for_two_lines_more_with_a_note(self):
        self.assertIn("flex: 999 1 9em", rule(".gr .gl"))
        self.assertIn("flex-basis: 15em", rule(".gr .gl:has(small)"))

    def test_under_its_label_a_control_takes_the_row_and_a_note_stays_under_the_label(self):
        self.assertIn("flex-basis: 100%", rule(".field.wide > *, .field.stack > *, .field.long > *, .field > .fnote"))
        self.assertIn("flex-basis: 100%", rule(".pair .field > *"))

    def test_no_narrow_screen_special_case(self):
        self.assertNotRegex(CSS, r"@media[^{]*\{[^@]*\.gr \{ flex-wrap: wrap; \}", "the rule holds at every width")


class TestALongLabelTakesTheRow(unittest.TestCase):
    def test_field_marks_a_label_too_long_for_two_lines(self):
        src = UI.read_text()
        fn = src[src.index("export function field("):src.index("export function input(")]
        self.assertIn("> LABEL_TWO_LINES", fn)
        self.assertIn('long ? " long"', fn)
        script = (f"globalThis.navigator ??= {{ platform: '' }}; const U = await import({json.dumps(UI.as_uri())});"
                  "console.log(JSON.stringify([U.LABEL_TWO_LINES, U.segNeed([28, 42, 30, 50]), U.segFits([30, 45], 141)]));")
        two, need, fits = json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertLess(two, 2 * 92, "two lines of the 92 px column, with room for where words break")
        self.assertEqual(need, 4 * (50 + 12) + 2 * 3 + 4)
        self.assertTrue(fits)


if __name__ == "__main__":
    unittest.main()
