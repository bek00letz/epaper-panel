"""The editor's chrome around the canvas: how the panel fills its area, the screen's
controls on the main view, and adding and naming screens.

The editor has no build step and no JavaScript test runner, so these pin the
rules and the wiring in its source (the way test_settings_layout does). What
they look like was measured in a browser while building them."""
import re
import unittest

import support

WEB = support.APP / "web"
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "editor.css").read_text(), flags=re.S)


def rules(selector_part):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if selector_part in sel]


def rule(selector):
    """The first rule for exactly this selector (later ones are narrow-window overrides)."""
    return next(body for sel, body in rules(selector) if sel == selector)


def js(name):
    return (WEB / "app" / name).read_text()


class TestFit(unittest.TestCase):
    def test_the_canvas_area_has_one_track_its_own_size(self):
        # With an auto track, Safari sized the frame's 100% to the panel's own
        # 792 px, so Fit never grew past actual size on a big window.
        body = rule(".canvasarea")
        self.assertIn("grid-template: minmax(0, 1fr) / minmax(0, 1fr)", body)

    def test_actual_size_scrolls_instead_of_spilling(self):
        body = rule(".canvasarea.actual")
        self.assertIn("grid-template: auto / auto", body)
        self.assertIn("overflow: auto", body)



class TestAddAScreen(unittest.TestCase):
    def setUp(self):
        src = js("sheets.js")
        self.sheet = src[src.index("export function openAddScreen"):src.index("export function openPairing")]

    def test_power_comes_before_pages(self):
        # On a short window Power sat below the fold, so a screen could be added without seeing it.
        self.assertLess(self.sheet.index('text: "Power" }'), self.sheet.index('text: "Pages" }'))

    def test_sleeping_says_how_often_and_offers_settings_times(self):
        self.assertIn('choice("sleep", "Sleeps between updates"', self.sheet)
        self.assertIn('"power", everySel)', self.sheet, "the picker sits on the card")
        self.assertIn("st.kind.update_choices.filter((m) => m !== 1)", self.sheet)
        self.assertIn('update_minutes: !pairs() && st.power === "on" ? 1 : st.minutes', self.sheet)

    def test_picking_a_time_picks_sleeping(self):
        self.assertIn('st.minutes = Number(v); st.power = "sleep"', self.sheet)

    def test_a_sheet_can_use_the_whole_window(self):
        self.assertIn("max-height: calc(100dvh - 48px)", rule(".sheet"))



class TestFindingAddAScreen(unittest.TestCase):
    def test_the_screen_name_looks_like_a_button(self):
        # It read as a title, so nobody looked in it for Add a screen.
        self.assertIn("background: var(--fill)", rule(".screenbtn"))
        self.assertIn('icon("panel", "sm"), h("span", { class: "sn"', js("main.js"))

    def test_settings_offers_it_next_to_remove(self):
        src = js("sheets.js")
        group = src[src.index("function removeGroup"):src.index("async function panelPane")]
        self.assertLess(group.index('"Add another screen"'), group.index('"Remove this screen"'))
        self.assertIn("openAddScreen(app)", group)



class TestErrorsSayWhy(unittest.TestCase):
    def test_a_plain_text_reason_reaches_the_person(self):
        # The add-on refuses with text ("There's already a screen called Kitchen."),
        # which the editor used to swap for "The add-on couldn't read that."
        api = js("util.js")
        api = api[api.index("export async function api"):api.index("export const clone")]
        self.assertIn("await r.text()", api)
        self.assertIn("|| said ||", api)
        self.assertIn("!/^\\d{3}: /.test(", api, "aiohttp's own '400: Bad Request' isn't a reason")



class TestRenaming(unittest.TestCase):
    def setUp(self):
        self.main = js("main.js")

    def test_the_screen_menu_renames_in_place(self):
        self.assertIn('{ label: "Rename…", run: () => this.startRename() }', self.main)
        self.assertIn("scr && this.renaming ? this.renameField(scr) : null", self.main)

    def test_a_double_click_on_the_name_renames_it(self):
        self.assertIn("if (e.detail === 2) { closeAll(); this.startRename(); }", self.main)

    def test_enter_and_clicking_away_keep_it_and_esc_puts_it_back(self):
        field = self.main[self.main.index("  renameField(scr) {"):self.main.index("  /* ---------- data")]
        self.assertIn('if (e.key === "Enter") { e.preventDefault(); finish(true); }', field)
        self.assertIn('else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }', field)
        self.assertIn('i.addEventListener("blur", () => { if (!i.disabled) finish(true); });', field)

    def test_a_redraw_while_typing_keeps_the_field(self):
        self.assertIn("if (field) { [...tb.children].forEach((c) => { if (c !== field) c.remove(); }); tb.append(...items.slice(1)); }", self.main)

    def test_the_field_is_the_buttons_size(self):
        self.assertIn("min-height: 32px", rule(".inp.screenname"))
        self.assertIn("font: 600 15px var(--font-display)", rule(".inp.screenname"))

    def test_settings_says_what_a_new_name_changes(self):
        self.assertIn("Home Assistant keeps calling it ${scr.keeps_ha_name}", js("sheets.js"))


if __name__ == "__main__":
    unittest.main()
