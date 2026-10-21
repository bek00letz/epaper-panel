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

    def test_a_chosen_zoom_scrolls_instead_of_spilling(self):
        body = rule(".canvasarea.zoomed")
        self.assertIn("grid-template: auto / auto", body)
        self.assertIn("overflow: auto", body)
        self.assertIn("width: calc(var(--pw, 792px) * var(--zoom, 1) + 24px)", rule(".canvasarea.zoomed .device"))


class TestZoom(unittest.TestCase):
    """Between actual size and Fit (the user's call): a menu of steps, − and +, ⌘+ ⌘− ⌘0, a pinch."""
    def setUp(self):
        self.main = js("main.js")

    def test_the_steps_and_the_menu(self):
        self.assertIn("const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2];", self.main)
        control = self.main[self.main.index("  zoomControl() {"):self.main.index("  renderBar() {")]
        for part in ('"Zoom out"', '{ label: "Fit"', "...ZOOM_STEPS.map(", '"Zoom in"'):
            self.assertIn(part, control)

    def test_the_keys(self):
        self.assertIn('if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); this.zoomStep(1); return; }', self.main)
        self.assertIn('if (mod && e.key === "0") { e.preventDefault(); this.setZoom(1); return; }', self.main)
        self.assertIn('["Zoom in, out, actual size"', js("sheets.js"))

    def test_a_pinch_keeps_what_is_under_the_fingers(self):
        pinch = self.main[self.main.index("  wirePinch() {"):self.main.index("  zoomControl() {")]
        self.assertIn("if (!e.ctrlKey || narrow()) return;", pinch)
        self.assertIn('"gesturechange"', pinch, "Safari pinches with gesture events")
        zoom = self.main[self.main.index("  setZoom(z, at) {"):self.main.index("  applyZoom() {")]
        self.assertIn("area.scrollLeft += after.left + fx * after.width - x;", zoom)

    def test_the_old_actual_size_is_100_percent(self):
        self.assertIn('if (z === "actual") return 1;', self.main)

    def test_fit_is_worked_out_not_measured(self):
        # Fit's frame springs to its size; stepping from a frame still moving picked the wrong step.
        scale = self.main[self.main.index("  shownScale() {"):self.main.index("  setZoom(z, at) {")]
        self.assertNotIn("canvas.device.getBoundingClientRect", scale)



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
        self.assertLess(group.index('"Add another device"'), group.index('"Remove this device"'))
        self.assertIn("openAddScreen(app)", group)
        self.assertIn("removeScreen(app, scr)", group)

    def test_the_screen_menu_is_screens_then_this_ones_then_adding(self):
        # The user's order: the screens, a line, Rename and Remove (red), a line, Add new device.
        main = js("main.js")
        menu = main[main.index("  openScreens(anchor) {"):main.index("  startRename() {")]
        rename, remove = menu.index('label: "Rename…"'), menu.index('label: "Remove", danger: true, disabled: only')
        line_after = menu.index('"sep",', remove)
        self.assertLess(menu.index('[...items, "sep"'), rename)
        self.assertLess(rename, remove)
        self.assertLess(line_after, menu.index('label: "Add new device…"'))
        self.assertIn("removeScreen(this, this.screen)", menu)

    def test_it_says_device_so_it_isnt_taken_for_a_page(self):
        sheets = js("sheets.js")
        self.assertIn('sheet("Add new device"', sheets)
        self.assertNotIn('"Add a screen…"', js("main.js"))



class TestErrorsSayWhy(unittest.TestCase):
    def test_a_plain_text_reason_reaches_the_person(self):
        # The add-on refuses with text ("There's already a device called Kitchen."),
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
        self.assertIn('grow("Name", "Home Assistant takes it at the next install.", name)', js("sheets.js"))



class TestScreenBar(unittest.TestCase):
    def setUp(self):
        self.bar = js("screenbar.js")

    def test_it_sits_under_the_canvas_in_the_flow(self):
        html = (WEB / "index.html").read_text()
        self.assertLess(html.index('class="canvaswrap"'), html.index('id="screenbar"'))
        self.assertIn("renderScreenBar(this)", js("main.js"))
        self.assertIn("#app[data-strip=\"bottom\"] .screenbar { order: 2; }", CSS, "above a strip at the bottom")
        self.assertIn('#app[data-strip="side"] .screenbar { grid-column: 2; grid-row: 3; }', CSS)

    def test_folded_it_says_how_the_screen_runs(self):
        self.assertIn('const power = t.always_on ? "Always on" : `Sleeps · updates every', self.bar)
        self.assertIn("`next page every", self.bar)
        self.assertIn('qh.enabled ? `quiet ${qh.start}–${qh.end}` : "no quiet hours"', self.bar)
        self.assertIn('prefs.get("screenbar") === "open"', self.bar, "it remembers whether it was open")

    def test_it_changes_things_the_way_settings_does(self):
        # Like Control Center next to Settings: a second place, never a second way.
        for shared in ("changeTimers", "rotateOptions", "rotateChange", "ORIENTATIONS", "setMounted"):
            self.assertIn(shared, self.bar)
            self.assertRegex(js("sheets.js"), rf"export (async function|const) {shared}\b")
        timers = js("sheets.js")[js("sheets.js").index("function timersBox"):]
        self.assertIn("await changeTimers(app, scr, body, said)", timers)

    def test_only_the_four_everyday_settings(self):
        cards = re.findall(r'card\("([^"]+)"', self.bar)
        self.assertEqual(sorted(set(cards)), ["Mounted", "Next page", "Power", "Quiet hours"])

    def test_toasts_rise_above_it(self):
        self.assertIn("#toast { bottom: max(24px, calc(var(--sb-room, 0px) + 8px)); }", CSS)

    def test_esc_folds_it(self):
        self.assertIn('if (e.key === "Escape") { e.stopPropagation(); setOpen(false, "pill"); }', self.bar)

    def test_big_enough_to_touch(self):
        self.assertIn("@media (pointer: coarse) { .sbpill { min-height: 44px;", CSS)



class TestDeviceNotScreen(unittest.TestCase):
    """The things you add and manage are devices in everything a person reads (the user's
    call, 21 Oct). "Screen" stays where it means the display itself."""
    DISPLAY = ("sleep screen", "sleep_screen", "on screen", "its own screen", "its screen says", "cleans the screen",
               "one screen on the panel", "on one screen", "screenname")

    def test_the_editor_says_device(self):
        found = []
        for f in sorted((WEB / "app").glob("*.js")) + [WEB / "index.html"]:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if line.strip().startswith(("//", "/*", "*")):
                    continue
                for lit in re.findall(r'"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`', line):
                    words = re.sub(r"\$\{[^}]*\}", "", lit)        # what's inside ${…} is code
                    if " " in words and re.search(r"screen", words, re.I) and not any(d in words.lower() for d in self.DISPLAY):
                        found.append(f"{f.name}:{n}: {lit[:80]}")
        self.assertEqual(found, [])

    def test_the_add_ons_messages_say_device(self):
        found = []
        for f in [support.APP / "web.py", support.APP / "devices.py", support.APP / "reach.py", support.APP / "panel_setup.py",
                  *sorted((support.APP / "kinds").glob("*.py"))]:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if re.search(r'(text=|Error\(|_refused\(|NOT_PAIRING = |return ")f?"[^"]*\bscreens?\b', line):
                    found.append(f"{f.name}:{n}")
        self.assertEqual(found, [])

    def test_the_settings_section_is_device(self):
        self.assertIn('panel: ["Device", "panel",', js("sheets.js"))


if __name__ == "__main__":
    unittest.main()
