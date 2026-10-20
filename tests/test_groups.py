"""A style around several elements: outline, pill or inverted, shaped by its members."""
import unittest

import support  # noqa: F401
from render import layout, theme as T

CANVAS = (792, 272)


def els(style="outline", pad=10):
    return [
        {"type": "group", "id": "g", "members": ["a", "b"], "style": style, "pad": pad},
        {"type": "text", "id": "a", "value": "outside", "size": 40, "x": 100, "y": 40, "w": 200, "h": 50},
        {"type": "text", "id": "b", "value": "since", "size": 26, "x": 100, "y": 100, "w": 120, "h": 30},
    ]


def ink(img, box):
    x0, y0, x1, y1 = box
    return sum(1 for x in range(x0, x1) for y in range(y0, y1) if img.getpixel((x, y)) < 128)


class TestGroupShape(unittest.TestCase):
    def test_around_its_members_with_space(self):
        e = els()
        self.assertEqual(layout.group_box(e[0], e[1:], CANVAS), (90, 30, 220, 110))

    def test_kept_on_the_canvas(self):
        e = els(pad=60)
        x, y, w, h = layout.group_box(e[0], e[1:], CANVAS)
        self.assertGreaterEqual(min(x, y), 0)

    def test_no_members_no_shape(self):
        self.assertIsNone(layout.group_box(els()[0], [], CANVAS))


class TestGroupDrawing(unittest.TestCase):
    def render(self, elements, vals=None):
        return T.to_1bit(layout.render_page({"elements": elements}, vals or {}, display="crowpanel_579")).convert("L")

    def test_an_outline_is_drawn_around_them(self):
        img = self.render(els("outline"))
        self.assertGreater(ink(img, (90, 60, 93, 80)), 0, "the left edge of the outline")

    def test_inverted_turns_the_area_black_and_the_text_white(self):
        img = self.render(els("invert"))
        self.assertEqual(ink(img, (92, 60, 98, 80)), 6 * 20, "the padding is black")
        plain = self.render(els("outline"))
        self.assertLess(ink(img, (100, 40, 300, 90)), (200 * 50) - ink(plain, (100, 40, 300, 90)) + 1,
                        "the text inside is white on black")

    def test_a_hidden_member_leaves_the_shape(self):
        e = els("outline")
        e[2]["show_if"] = "{{ false }}"
        img = self.render(e, {"__vis_2": "false"})
        self.assertEqual(ink(img, (90, 125, 300, 145)), 0, "the shape ends at the member that shows")
