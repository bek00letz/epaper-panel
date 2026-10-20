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


if __name__ == "__main__":
    unittest.main()
