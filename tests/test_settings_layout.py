"""The Settings sheet's spacing: one rhythm on the 4/8 grid, so nothing in a pane runs into the next thing.

Measured in a browser while building it (16 between blocks, 24 above a section
title and 8 below it); these pin the rules that give it."""
import re
import unittest

import support

CSS = (support.APP / "web" / "editor.css").read_text()


def rules(selector_part):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if selector_part in sel]


class TestSettingsRhythm(unittest.TestCase):
    def test_every_block_in_a_pane_has_space_after_it(self):
        found = [body for sel, body in rules(".setpane :is(") if "margin: 0 0 16px" in body]
        self.assertTrue(found, "blocks in a settings pane need 16 px between them")
        sel = next(sel for sel, _ in rules(".setpane :is("))
        for block in ("p", ".group", ".choices", ".btnrow", "textarea"):
            self.assertIn(block, sel)

    def test_a_section_title_sits_with_its_group(self):
        self.assertTrue(any("margin: 24px 0 8px" in body for _, body in rules(".setpane .gtitle")))

    def test_settings_spacing_is_on_the_grid(self):
        for sel, body in rules(".setpane") + rules(".panetitle") + rules(".gtitle"):
            for prop, value in re.findall(r"(margin[\w-]*|padding[\w-]*|gap)\s*:\s*([^;]+)", body):
                for px in re.findall(r"(-?\d+(?:\.\d+)?)px", value):
                    self.assertEqual(float(px) % 4, 0, f"{sel} {prop}: {px}px is off the 4 px grid")

    def test_a_notes_icon_matches_its_colour(self):
        # An orange tick on a green note was what the 0.13.0 pane showed.
        self.assertTrue(any("color: var(--green)" in body for sel, body in rules(".note .ic") if sel == ".note .ic"))


if __name__ == "__main__":
    unittest.main()
